"""`OpenSTA error-abort left armed` — a tree that disarms OpenSTA's error-abort.

THE DEFECT THE GATE EXISTS FOR, in its own measurement: with the variable at its
default 0 a FILE script whose `read_verilog` fails exits rc 1; with the variable
set non-zero the SAME failure exits rc 0 having linked no design. Every timing
gate downstream is then reporting success over a run that never happened.

THE MUTATION IS THE VALUE AND NOTHING ELSE. Both arms ship the same file, at the
same path, with the same assignment statement in the same Tcl dialect; the
can-pass arm assigns `0` and the can-fail arm assigns `1`. Nothing else about
the subject moves, so a green can-pass followed by a red can-fail isolates the
predicate the guard actually claims — "assigned to a value that is not literally
zero" — rather than "a .tcl file appeared".

WHY THE CAN-PASS ARM ASSIGNS RATHER THAN STAYS SILENT. An empty tree passes this
guard trivially, and a fixture built that way would prove only that the guard
does not fire at random. Assigning `0` exercises the one branch that most nearly
looks like the violation: the guard has to parse the assignment, read the value
and decide it is safe. `_is_zero` is the line under test in that arm.

THE VARIABLE IS ASSEMBLED FROM FRAGMENTS HERE for the same reason the guard
assembles it: a fixture that spelled a non-zero assignment of the real name as a
literal would be a violation sitting in the repo, and this file is inside the
tree the gate scans when it runs for real.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "OpenSTA error-abort left armed"

#: Assembled, never spelled — see the module docstring.
_VAR = "sta" + "_continue_on_error"

_TCL = """# Fixture-only timing setup. Describes no real design.
read_liberty  fixture.lib
read_verilog  fixture.v
link_design   fixture_top
set {var} {value}
report_checks -path_delay max
"""


def _tree(work: Path, value: str) -> Path:
    root = F.git_init(work / "subject")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "sta_setup.tcl").write_text(
        _TCL.format(var=_VAR, value=value), encoding="utf-8")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    """Explicit `0` — a restatement of the default, and the one safe thing to
    write. The guard must read the value and accept it."""
    return _tree(work, "0")


def can_fail(work: Path):
    """The same file, the same statement, the value changed to a non-zero."""
    return _tree(work, "1"), "violation(s)"
