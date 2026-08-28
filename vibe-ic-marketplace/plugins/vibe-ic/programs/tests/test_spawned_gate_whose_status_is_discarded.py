"""The discarded-gate-spawn rule, driven in both directions and both clauses."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "spawned_gate_whose_status_is_discarded.py")

#: CLAUSE A, the defect: unbound + check off + a handler that swallows all,
#: under a comment calling it blocking.
_DEFECT_A = '''\
import subprocess
import sys


def resign(project):
    try:
        # This direct, BLOCKING flow_compliance re-run keeps the headline
        # from ever lagging its own sign-off.
        subprocess.run([sys.executable, "programs/flow_compliance_check.py",
                        str(project)], timeout=300, check=False)
    except Exception:
        pass
    return True
'''

#: The remedy: bind the result and read its status.
_REPAIRED_A = '''\
import subprocess
import sys


def resign(project):
    try:
        r = subprocess.run([sys.executable, "programs/flow_compliance_check.py",
                            str(project)], timeout=300, check=False)
    except Exception:
        return False
    if r.returncode != 0:
        return False
    return True
'''

#: The other remedy the rule accepts: say so at the call site.
_DECLARED_ADVISORY = '''\
import subprocess
import sys


def resign(project):
    try:
        # ADVISORY: the artefact carries the verdict; this spawn only writes it.
        subprocess.run([sys.executable, "programs/thermal_screen_check.py",
                        str(project)], timeout=300, check=False)
    except Exception:
        pass
    return True
'''

#: check=True raises. That IS a gate and must not be flagged.
_CHECK_ON = _DEFECT_A.replace("check=False", "check=True")

#: CLAUSE B, the mirror: a program whose subject is whether something RAN,
#: with no way to start a process and no way to read a status.
_DEFECT_B = '''\
"""Whether the full suite actually ran."""


def main(argv):
    line = open("command.log").read()
    if "pytest programs/tests" in line:
        print("[PASS] the full suite ran")
        return 0
    print("[FAIL] the full suite did not run")
    return 1
'''


def _tree(files: dict, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="sgs_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    for name, body in files.items():
        (progs / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True)


def test_clause_a_a_discarded_gate_spawn_is_refused():
    """NEGATIVE CONTROL for clause A."""
    r = _run(_tree({"sample_runner.py": _DEFECT_A}))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "flow_compliance_check.py" in r.stdout
    assert "result unbound" in r.stdout


def test_clause_b_a_run_subject_that_cannot_run_is_refused():
    """NEGATIVE CONTROL for clause B — the mirror shape, no spawn at all."""
    r = _run(_tree({"suite_run_check.py": _DEFECT_B}))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "suite_run_check.py" in r.stdout
    assert "neither start a process nor read a status" in r.stdout


def test_a_bound_and_read_status_is_not_refused():
    r = _run(_tree({"sample_runner.py": _REPAIRED_A}))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_declared_advisory_spawn_is_not_refused():
    r = _run(_tree({"sample_runner.py": _DECLARED_ADVISORY}))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_check_true_is_not_refused():
    """A spawn that raises on failure IS a gate. All three conditions or none."""
    r = _run(_tree({"sample_runner.py": _CHECK_ON}))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_spawn_outside_a_swallowing_handler_is_not_refused():
    body = _DEFECT_A.replace("    try:\n", "").replace(
        "    except Exception:\n        pass\n", "").replace(
        "        # This", "    # This").replace(
        "        subprocess.run", "    subprocess.run").replace(
        "        # from ever", "    # from ever").replace(
        "                        str(project)", "                    str(project)")
    r = _run(_tree({"sample_runner.py": body}))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree({"sample_runner.py": _REPAIRED_A}, inventory=[
        {"key": "A::programs/gone.py::x_check.py", "reason": "stale"}]))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_run_states_each_clause_population_not_only_its_findings():
    """Two clauses, two denominators, and they are not equal in strength.

    Clause A is a rule over 654 modules. Clause B has a population of ONE and
    finds it, which makes it a regression guard. A verdict printing only the
    finding counts lets the second read as coverage — the exact confusion this
    rule family exists to end.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert "clause A population:" in r.stdout
    assert "clause B population:" in r.stdout
    assert "REGRESSION GUARD" in r.stdout, (
        "clause B must be labelled in the verdict, not only in the docstring")


def test_clause_b_is_honest_about_finding_one_of_one():
    """Pins the shape of the admission, not just its wording.

    If clause B's population ever grows beyond the one module, it stops being a
    regression guard and the COVERAGE section has to be re-derived — so this
    fails rather than silently keeping a stale label.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    sys.path.insert(0, str(PROG.parent))
    import spawned_gate_whose_status_is_discarded as S

    pop = set()
    for base in (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                 root / "tools"):
        if not base.is_dir():
            continue
        for f in base.rglob("*.py"):
            if "tests" in f.parts or "node_modules" in f.parts:
                continue
            if S._RUN_SUBJECT_RE.search(f.name):
                pop.add(f.name)

    assert pop == {"full_suite_run_check.py"}, (
        f"clause B's population MOVED: entered "
        f"{sorted(pop - {'full_suite_run_check.py'})}, left "
        f"{sorted({'full_suite_run_check.py'} - pop)}. Re-derive the COVERAGE "
        f"section — the 'regression guard, not a rule' label may no longer be "
        f"true, in either direction.")


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"

_DEFECT_OS_SYSTEM = """\
import os


def resign(project):
    try:
        # This BLOCKING re-run keeps the headline honest.
        os.system("python3 programs/flow_compliance_check.py " + str(project))
    except Exception:
        pass
    return True
"""


def test_os_system_is_a_spawn_too():
    """`os.system` returns an exit code and has NO `check=` at all.

    It is the archetypal discarded status, and this file's `_SPAWNERS` tuple
    omitted it until an audit of the enumeration on 2026-08-22. There are zero
    real `os.system` sites in the tree, so without this test the widening is
    unfalsifiable — a latent gap closed with nothing proving it closed.
    """
    r = _run(_tree({"sample_runner.py": _DEFECT_OS_SYSTEM}))
    assert r.returncode == 1, (
        f"os.system in a swallowing handler was not seen as a spawn "
        f"(rc={r.returncode})\n{r.stdout}\n{r.stderr}")
    assert "flow_compliance_check.py" in r.stdout
