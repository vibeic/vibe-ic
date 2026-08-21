"""`chip-AGNOSTIC source guard` — a forbidden vendor/SKU token in plugin source.

THE MUTATION IS SYNTHESISED, NEVER STORED. This gate's whole purpose is to keep
those tokens out of the tree, so a fixture that carried one as a literal would
be the artefact the gate exists to reject — and would be found by the gate
itself, by `nda_tracked_tree_scan`, and by the repo's NDA rules, in that order.

The token is therefore read at run time from the gate's OWN canonical deny
list, `programs/tests/chip_deny_list.txt`. That also keeps the fixture true: a
token added to the deny list tomorrow is the token this fixture uses tomorrow,
with no edit here, so the evidence cannot drift away from the rule.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F

GATE = "chip-AGNOSTIC source guard"

_DENY = F.PROGRAMS / "tests" / "chip_deny_list.txt"


def _a_forbidden_token() -> str:
    """One token, straight out of the gate's canonical list. Never stored here."""
    for line in _DENY.read_text(errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and s.isalnum():
            return s
    raise RuntimeError(
        f"{_DENY} carries no usable token — this fixture cannot synthesise the "
        f"mutation, and must say so rather than pass vacuously")


def _tree(work: Path, prose: str) -> Path:
    """The three directories this gate insists on scanning, each non-empty.

    Non-empty on purpose: the gate refuses (rc 2) over an empty scan, and a
    fixture that tripped that refusal would be measuring the zero-denominator
    guard rather than the token scan.
    """
    root = F.git_init(work / "subject")
    for d in ("programs", "skills", "commands"):
        (root / d).mkdir()
        (root / d / "notes.md").write_text("open-source EDA flow notes\n")
    (root / "programs" / "tool.py").write_text(
        "#!/usr/bin/env python3\n# " + prose + "\nTARGET = 1\n")
    F.git_commit(root)
    return root


def can_pass(work: Path) -> Path:
    return _tree(work, "targets a generic open technology")


def can_fail(work: Path):
    return _tree(work, "targets " + _a_forbidden_token()), "FAIL"
