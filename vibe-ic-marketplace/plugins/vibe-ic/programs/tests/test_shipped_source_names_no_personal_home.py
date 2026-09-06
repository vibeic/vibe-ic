"""The shipped tree carries no personal home path — asserted, not remembered.

MEASURED (vibe-ic#2062 addendum). `shipped_path_portability_check` was RED on
main from v1.17.77 on exactly one line, and nothing in the test suite said so,
so the gate's own verdict was the only thing that knew. The offending line was
not a code path at all: it was a rationale COMMENT quoting, verbatim, the
runtime error that explains why the LVS runset is told where to write its
extracted netlist —

    ERROR: RuntimeError: Unable to open file: /home/<user>//ldo_extracted.cir

— i.e. the post-mortem quoted the defect, and the guard read the citation. The
remedy the gate itself prescribes for that case is the one applied: write the
user as a placeholder. The quotation is otherwise untouched, because it is the
evidence for the fix in the code beneath it.

BOTH DIRECTIONS. The first test asserts the tree is clean; the second breaks a
file on purpose in a scratch copy of the tree and asserts the gate goes red, so
a gate that has quietly stopped checking cannot pass this file.
"""
import shutil
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _PROGRAMS.parent
_GATE = _PROGRAMS / "shipped_path_portability_check.py"


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_GATE), str(root)],
                          capture_output=True, text=True)


def test_the_shipped_tree_carries_no_personal_home_path():
    cp = _run(_PLUGIN_ROOT)
    assert cp.returncode == 0, (cp.stdout + cp.stderr)[-3000:]
    assert "PASS" in (cp.stdout + cp.stderr)


def test_the_gate_still_goes_red_when_a_home_path_is_planted(tmp_path):
    """A check that cannot fail is not a check. Planted in a COPY, never in
    the tree under test."""
    root = tmp_path / "plugin"
    shutil.copytree(_PLUGIN_ROOT, root, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The gate scans git-tracked files; the copy is not a work tree, so it
    # scans what is on disk. Plant on the very file the finding was on.
    victim = root / "programs" / "analog_a6_native_pv.py"
    # ASSEMBLED, never written out. A literal here would be a personal home
    # path in a SHIPPED, git-tracked file, and the gate scans this file too —
    # so writing the mutation plainly makes the test the finding. That is the
    # same "the guard reads its own citation" shape as the defect this module
    # is about, one level up, and it is worth the two lines to avoid.
    planted = "/" + "home" + "/" + "somebody" + "/x.cir"
    victim.write_text(victim.read_text()
                      + f'\n_PLANTED = "{planted}"\n')
    cp = _run(root)
    assert cp.returncode != 0 or "FAIL" in (cp.stdout + cp.stderr), \
        (cp.stdout + cp.stderr)[-3000:]
