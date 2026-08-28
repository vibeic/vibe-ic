"""`a verdict arm decided by a constant` — the refusal that was switched off.

THE MUTATION IS THE MEASURED DEFECT, read out of the mutant tree the 68x9
campaign produced on 2026-08-28: a wafer-sort yield gate whose refusal arm was
disabled with one token —

    if False and measured + 1e-9 < target:

— lets a 12.5% yield pass a 90% target while 0 of 612 matrix cells change
colour.

BOTH TREES CARRY THE SAME TWO GATES AND THE SAME TWO ARMS. Nothing is added and
nothing is deleted; the second gate's condition gains one constant operand. The
can-pass tree also carries the default-value idiom the rule must NOT report
(`(w or 1) > 1`), so the direction that stays green stays green because the
predicate discriminates and not because the subject is bare.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401

GATE = "a verdict arm decided by a constant"

_LIVE = '''"""A synthetic yield gate whose refusal arm the run decides."""


def widths(ports):
    return [d for d, w in ports if d == "output" and (w or 1) > 1]


def main(measured, target):
    if measured + 1e-9 < target:
        print("YIELD_BELOW_TARGET")
        return 1
    return 0
'''

_SWITCHED_OFF = '''"""A synthetic yield gate whose refusal arm the run decides."""


def widths(ports):
    return [d for d, w in ports if d == "output" and (w or 1) > 1]


def main(measured, target):
    if False and measured + 1e-9 < target:
        print("YIELD_BELOW_TARGET")
        return 1
    return 0
'''


def _tree(work: Path, source: str) -> Path:
    root = work / "subject"
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "synthetic_yield_check.py").write_text(source, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The arm the run decides, next to the default-value idiom."""
    return _tree(work, _LIVE)


def can_fail(work: Path):
    """The same arm, with one constant operand in front of it."""
    return _tree(work, _SWITCHED_OFF), "verdict arm(s) decided by a constant"
