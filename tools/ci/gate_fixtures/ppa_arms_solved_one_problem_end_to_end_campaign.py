"""`PPA arms solved one problem (end-to-end campaign)` — two arms of one problem, at the corpus this row names.

The subject comes from `_two_arm_contracts`, which is shared with the other
campaign row and skipped by the fixture loader because it is underscore-named.
This module carries only the corpus its own declaration passes to `--corpus`.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _two_arm_contracts as _base  # noqa: E402

GATE = "PPA arms solved one problem (end-to-end campaign)"

#: Byte-for-byte the directory the end-to-end row passes to `--corpus`.
CORPUS = "ppa-e2e"


def can_pass(work: Path) -> Path:
    """Two contracts, one problem group, one pair compared, no conflict."""
    return _base.build_can_pass(work, CORPUS)


def can_fail(work: Path):
    """The two arms disagree on toolchain identity — PPA-C-012, rc 1."""
    return _base.build_can_fail(work, CORPUS)
