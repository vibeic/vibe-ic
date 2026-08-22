"""CANDIDATE test pinning F3d. It goes RED on the current tree, by design.

It lives HERE and not in `programs/tests/` deliberately: it fails on `main`
today, and landing a red test would block every push on the repo. It is the
artefact the fix ships with, not a fix.

WHAT IT PINS. Upstream derives the opposite side of a pad ring by MIRRORING --
`north = south.flipX()`, `east = west.flipY()`, stated in two lines of the
tool's own source. Our step derives it by a HALF TURN, through a helper whose
docstring says "one quarter turn clockwise", applied twice.

WHY THE OBVIOUS TEST DOES NOT WORK, and this file demonstrates it rather than
asserting it: for a rectangular master a half turn and a mirror occupy the SAME
bounding box, so any extent-based assertion passes under both. The first test
below is that mistake, written out and shown passing on the broken tree, so the
next author does not reinvent it and believe it.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[2] / "vibe-ic-marketplace/plugins/vibe-ic/programs"
sys.path.insert(0, str(_PROGRAMS))
import _pad_ring as PR                                        # noqa: E402

#: What the tool does, read out of its source at the pinned commit:
#:     north_rotation_ver = south_rotation_ver.flipX()
#:     east_rotation_hor  = west_rotation_hor.flipY()
#: The tool's own flipX, enumerated from its orientation algebra rather than
#: guessed -- R0->MX, R90->MXR90, R180->MY, R270->MYR90 -- then written in DEF
#: spelling through the module's own alias table (R0=N, R90=W, R180=S, R270=E;
#: MX=FS, MXR90=FW, MY=FN, MYR90=FE). It is an involution, so each pair appears
#: both ways round.
#:
#: THE FIRST VERSION OF THIS TABLE WAS WRONG on the E/W entries -- it had E->FW
#: and W->FE, the two exchanged. Writing the test caught it; the note stays
#: because a test whose ORACLE is wrong is worse than no test, and this one
#: would have reported a divergence that was mine.
_FLIP_X = {"N": "FS", "FS": "N",      # R0   <-> MX
           "W": "FW", "FW": "W",      # R90  <-> MXR90
           "S": "FN", "FN": "S",      # R180 <-> MY
           "E": "FE", "FE": "E"}      # R270 <-> MYR90


def _ours_opposite(orient: str) -> str:
    """What our step derives for the opposite side: a half turn."""
    return PR.rotate_cw(orient, 2)


def test_the_extent_assertion_cannot_see_the_defect():
    """THE MISTAKE, written out. Passes on the broken tree -- that is the point.

    An assertion on the footprint agrees under a mirror and under a half turn,
    so a test written this way reads as coverage and provides none.
    """
    size = (75.0, 350.0)          # a rectangular pad master, w x h
    units = 1000
    for start in ("N", "S", "E", "W"):
        ours = _ours_opposite(start)
        theirs = _FLIP_X[start]
        assert PR.footprint(size, ours, units) == PR.footprint(size, theirs, units), (
            "if this ever fails the demonstration is stale -- rewrite the note")
    # It passed. That is the finding: extents are blind here.


def test_the_opposite_side_is_the_upstream_MIRROR_not_a_half_turn():
    """THE REAL PIN. Compares the ORIENTATION TOKEN. RED on the current tree."""
    failures = []
    for start in ("N", "S", "E", "W", "FN", "FS", "FE", "FW"):
        ours = _ours_opposite(start)
        theirs = _FLIP_X[start]
        if ours != theirs:
            failures.append(f"from {start}: ours={ours} upstream(flipX)={theirs}")
    assert not failures, (
        "the opposite side must be upstream's MIRROR, not a half turn:\n  "
        + "\n  ".join(failures))


if __name__ == "__main__":
    import traceback
    rc = 0
    for fn in (test_the_extent_assertion_cannot_see_the_defect,
               test_the_opposite_side_is_the_upstream_MIRROR_not_a_half_turn):
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError:
            rc = 1
            print(f"FAIL  {fn.__name__}")
            print("      " + str(sys.exc_info()[1]).replace("\n", "\n      ")[:800])
    sys.exit(rc)
