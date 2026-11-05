"""Every interpreter the landing path starts runs inside the tree it audits.

vibe-ic#1893. `tools/ci/repo_hygiene_gates.sh:52` exports
`PYTHONDONTWRITEBYTECODE=1` and writes down why: a `.pyc` "lands inside the tree
the later attestation and host-independence gates re-derive and compare. `git
status --porcelain` cannot see it (`.gitignore`) and `_run_isolation.snapshot`
can, and that asymmetry is the measured 13-of-39 differential failure
`attestation_preflight_check` was written from."

That export protects the children of THAT script. Two interpreters upstream of
it had no guard at all, and both import out of the `programs/` directory they
are auditing:

    tools/gatekeeper-land.sh          -> python3 "$PROGRAMS/gatekeeper_review.py"
    gatekeeper_review.repo_hygiene_gate -> python3 .../repo_hygiene_parallel.py

MEASURED on a pristine worktree of a4604d3fa:

    gatekeeper_review.py --help, unguarded          6 .pyc in programs/
    the same, with -B and the variable              0
    repo_hygiene_parallel.py, unguarded            10 .pyc — exactly its own
                                                   import list
    the same, with -B and the variable              0

and the consequence, one full parallel hygiene DAG each, same commit, same
pristine worktree shape, the guard the only variable:

    unguarded   attestation preflight       FAIL   (checkout rc=1)
                gates are host-independent  FAIL   — "1 of 140 probed corpus
                gate(s) did not give one reproducible verdict across two trees",
                and the one gate is `attestation preflight`
                failed=11
    guarded     attestation preflight       PASS
                gates are host-independent  PASS
                failed=9,  residue: none,  tree dirty: 0

So it was never host dependence. It was dirt the run wrote seconds earlier, and
one unguarded interpreter reddened two gates.

BOTH HALVES ARE REQUIRED, and that is asserted here as an experiment rather than
quoted as a rule: `-B` freezes the interpreter it is given to and does not
propagate to a child; the variable propagates and is discarded by `-I`, which
implies `-E`. `tools/gatekeeper-land.sh:1169` records the measured cost of
supplying only one — "it wrote 500+ `.pyc` into $ROOT in 7 minutes of one
landing".
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
ROOT = PROGRAMS.parents[3]
LAND = ROOT / "tools" / "gatekeeper-land.sh"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "gatekeeper_review", PROGRAMS / "gatekeeper_review.py")
GR = importlib.util.module_from_spec(_spec)
sys.modules["gatekeeper_review"] = GR       # @dataclass resolves through this
_spec.loader.exec_module(GR)

_REL = "vibe-ic-marketplace/plugins/vibe-ic/programs/repo_hygiene_parallel.py"


# ── the mechanism, as a real experiment ──────────────────────────────────────

def _writes_bytecode(tmp_path: Path, *, flag: bool, var: bool,
                     isolated: bool = False) -> bool:
    """Does an interpreter importing from `pkg/` leave a `__pycache__` there?"""
    pkg = tmp_path / f"pkg_{int(flag)}{int(var)}{int(isolated)}"
    pkg.mkdir()
    (pkg / "leaf.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "main.py").write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(pkg)!r})
        import leaf
        assert leaf.VALUE == 1
    """), encoding="utf-8")
    argv = [sys.executable]
    if isolated:
        argv.append("-I")
    if flag:
        argv.append("-B")
    argv.append(str(pkg / "main.py"))
    env = dict(os.environ)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.pop("PYTHONPYCACHEPREFIX", None)  # the pinned image sets it to /tmp/pycache
    if var:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run(argv, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return (pkg / "__pycache__").is_dir()


def test_an_unguarded_interpreter_writes_into_the_directory_it_imports_from(
        tmp_path):
    """The defect, reduced to its mechanism. Nothing here is about this repo —
    it is what CPython does, which is why every call site has to say so."""
    assert _writes_bytecode(tmp_path, flag=False, var=False) is True


def test_either_half_alone_stops_a_PLAIN_interpreter(tmp_path):
    assert _writes_bytecode(tmp_path, flag=True, var=False) is False
    assert _writes_bytecode(tmp_path, flag=False, var=True) is False


def test_the_VARIABLE_ALONE_does_not_reach_an_ISOLATED_child(tmp_path):
    """Why both halves are required and not one. `-I` implies `-E`, which
    discards every `PYTHON*` name, so the variable cannot reach it — this is the
    measured 500+ `.pyc` shape `gatekeeper-land.sh:1169` records."""
    assert _writes_bytecode(tmp_path, flag=False, var=True, isolated=True) is True
    assert _writes_bytecode(tmp_path, flag=True, var=True, isolated=True) is False


# ── the coordinator launch site ──────────────────────────────────────────────







# ── the program guards its own import phase ─────────────────────────────────





def test_CONTROL_an_ORDINARY_program_in_that_directory_still_writes(tmp_path):
    """Green in both arms, and it is what stops the test above passing for the
    wrong reason. If the host, the copy, or the interpreter had stopped writing
    bytecode at all, the assertion would be vacuous — so a neighbouring program
    with no guard must still leave residue under the same conditions."""
    prog = tmp_path / "programs"
    prog.mkdir()
    for src in PROGRAMS.glob("*.py"):
        (prog / src.name).write_bytes(src.read_bytes())
    (prog / "_probe_entry.py").write_text(
        "import _watchdog\nprint('ok')\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env.pop("PYTHONPYCACHEPREFIX", None)  # the pinned image sets it to /tmp/pycache
    env["PYTHONPATH"] = str(prog)
    r = subprocess.run([sys.executable, str(prog / "_probe_entry.py")],
                       capture_output=True, text=True, env=env,
                       cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (prog / "__pycache__").is_dir(), (
        "nothing writes bytecode here at all, so the guard test above proves "
        "nothing about the guard")


# ── the direct isolated coordinator entry ──────────────────────────────────









@pytest.mark.skipif(not LAND.is_file(), reason="landing driver not in this tree")
def test_CONTROL_the_isolated_call_sites_keep_their_own_flag():
    """Green in both arms, and the reason this fix is TWO halves rather than
    one. `-I` implies `-E`, which discards every `PYTHON*` name, so the variable
    this program exports cannot reach an isolated child; those call sites carry
    their own `-B` and must keep it. Nothing in this PR edits that file."""
    body = LAND.read_text(encoding="utf-8")
    isolated = [line for line in body.splitlines()
                if "python3 -I" in line and not line.lstrip().startswith("#")]
    assert isolated, "no isolated call site found to control against"
    for line in isolated:
        assert "python3 -I -B" in line, (
            f"an isolated child lost its own `-B` and cannot see the variable: "
            f"{line.strip()}")
