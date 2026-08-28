"""`gate red is more than absence` — a census whose population is one-sided.

WHAT THE GATE LINE ASSERTS. This is a CENSUS, so the wired line runs
`--self-test`, not the corpus verdict: the counts are a maintainer's backlog,
and what can silently rot is the CLASSIFIER — its ability to tell a red earned
on a design that DID something from a red earned because nothing was there.

THE MUTATION IS THE MEASURED DEFECT. On the 68x9 matrix (plugin v1.12.33),
dimension D2 counted 121 reds as evidence of falsifiability; 54 of them were
earned on an EMPTY tree, where the FAIL text is `REQUIRED_ARTEFACT_MISSING` /
`MISSING_NETLIST` / "no file on disk matches pattern". Killing a gate's
namesake verdict while leaving its absence arm alive left D2 green.

BOTH TREES CARRY THE SAME TWO GATES. Nothing is added or removed: the second
gate's CONTENT arm — the red it can reach on a design that produced the file —
is what changes. In the can-fail direction every gate in the tree lands in one
bucket, so the census walked a population that exercises only one side of its
own predicate, and it says so instead of printing counts.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401

GATE = "gate red is more than absence"

_ABSENCE_ONLY = '''"""A synthetic gate that can only fail on an absent input."""
from pathlib import Path


def main(path):
    if not Path(path).exists():
        print("REQUIRED_ARTEFACT_MISSING: no clock plan on disk")
        return 1
    return 0
'''

_WITH_VERDICT = '''"""A synthetic gate that can fail on what the design produced."""
import json
from pathlib import Path


def main(path):
    if not Path(path).exists():
        print("REQUIRED_ARTEFACT_MISSING: no clock plan on disk")
        return 1
    doc = json.loads(Path(path).read_text())
    if not doc["clocks"]:
        print("CLOCK_PLAN_EMPTY: the plan declares zero clocks")
        return 1
    return 0
'''


def _tree(work: Path, second: str) -> Path:
    root = work / "subject"
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    (programs / "synthetic_presence_check.py").write_text(
        _ABSENCE_ONLY, encoding="utf-8")
    (programs / "synthetic_content_check.py").write_text(second, encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """One gate of each kind — the classifier's separation is exercised."""
    return _tree(work, _WITH_VERDICT)


def can_fail(work: Path):
    """The second gate loses its content arm; every gate is now one-sided."""
    return _tree(work, _ABSENCE_ONLY), "exercises only one side"
