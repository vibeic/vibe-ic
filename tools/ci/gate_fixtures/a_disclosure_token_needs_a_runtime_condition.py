"""`a disclosure token needs a runtime condition` — a skip nobody can decline.

THE MUTATION IS THE MEASURED DEFECT. On the 68x9 matrix (plugin v1.12.33),
making a gate stop working and say NOTHING reddened dimension D6 hard; making
the SAME gate stop working and say `VACUOUS_PASS` left D6 byte-identical to
the clean tree. A disclosure token bought a green cell.

BOTH TREES CARRY THE SAME TWO GATES AND THE SAME TWO DISCLOSURES. Nothing is
added and nothing is deleted: the population walked is identical in both
directions, and only the CONDITION around the second disclosure changes. So
the direction that goes red goes red because the answer changed, not because
the corpus did.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401

GATE = "a disclosure token needs a runtime condition"

#: Two gates. Both disclose; both disclosures are reached only when something
#: on disk says so — the shape the rule accepts.
_CONDITIONED = '''"""A synthetic gate that declines to judge, and says why."""
from pathlib import Path


def check_clock_plan(path):
    if not Path(path).exists():
        print("VACUOUS_PASS: no clock plan on disk — nothing was judged")
        return 0
    return 0


def check_pad_ring(path):
    if not Path(path).exists():
        print("SKIPPED-CONDITION: no pad ring declared — nothing was judged")
        return 0
    return 0
'''

#: The SAME two gates and the SAME two sentences. The second one now prints
#: whatever the input is: it cannot decline, so it says nothing about the run.
_UNCONDITIONED = '''"""A synthetic gate that declines to judge, and says why."""
from pathlib import Path


def check_clock_plan(path):
    if not Path(path).exists():
        print("VACUOUS_PASS: no clock plan on disk — nothing was judged")
        return 0
    return 0


def check_pad_ring(path):
    print("SKIPPED-CONDITION: no pad ring declared — nothing was judged")
    return 0
'''


def _tree(work: Path, source: str) -> Path:
    root = work / "subject"
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "synthetic_skip_check.py").write_text(source, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Two disclosures, both guarded by a fact the run decides."""
    return _tree(work, _CONDITIONED)


def can_fail(work: Path):
    """The same two disclosures; the second one is now unconditional."""
    return _tree(work, _UNCONDITIONED), "unconditioned disclosure"
