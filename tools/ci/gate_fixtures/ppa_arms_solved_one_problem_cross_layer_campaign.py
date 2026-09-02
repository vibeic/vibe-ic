"""`PPA arms solved one problem (cross-layer campaign)` — two arms of one problem, at the corpus this row names.

The subject comes from `_two_arm_contracts`, which is shared with the other
campaign row and skipped by the fixture loader because it is underscore-named.
This module carries only the corpus its own declaration passes to `--corpus`.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
# `gate_mutation_fixtures` lives one directory up; the loader imports this
# module BY PATH, so the parent is not on `sys.path` unless it is put there.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402
import _two_arm_contracts as _base  # noqa: E402

GATE = "PPA arms solved one problem (cross-layer campaign)"

#: Byte-for-byte the directory the cross-layer row passes to `--corpus`.
#: ASKED OF THE ROW, NEVER RE-TYPED (vibe-ic#2019 fallout). The campaign trees
#: moved to `docs/campaigns/` and this literal did not follow, so the subject
#: was built where the gate no longer looks and the CAN-PASS arm was rejected
#: rc 2 "no corpus at …". `declared_subject_path` reads the `--corpus` this row
#: actually passes, so the fixture and its row cannot disagree.
_TAIL = "ppa-crosslayer"


def _corpus() -> str:
    """This row's corpus path, from the row.

    Resolved lazily: a missing row must fail THIS fixture, not the census that
    imports every fixture module.
    """
    return F.declared_subject_path(GATE, _TAIL)



def can_pass(work: Path) -> Path:
    """Two contracts, one problem group, one pair compared, no conflict."""
    return _base.build_can_pass(work, _corpus())


def can_fail(work: Path):
    """The two arms disagree on toolchain identity — PPA-C-012, rc 1."""
    return _base.build_can_fail(work, _corpus())
