# SUPERSEDED — NOT A TEST, AND NO LONGER NAMED LIKE ONE.
#
# Renamed out of `test_*.py` on 2026-08-29 because it was still being COLLECTED.
# `landing_unselectable_pytest_corpus.py` takes its population from
# `git ls-files` filtered by `^(test_.*\.py|.*_test\.py)$` and excludes NOTHING
# (`_EXCLUDED = ()`), and `gatekeeper-land.sh:run_unselectable_pytest` runs that
# corpus on EVERY landing, not on a cadence. So "kept out of `programs/tests/`
# so a red cannot block a push", which is what the README beside this file says
# and what this header replaces, WAS NEVER TRUE: the file blocked every landing
# from the moment it was tracked. The directory it sat in was never the thing
# that kept it out of the gate.
#
# It did not even reach its own assertion. `pad_ring_gen.py:427` now reads
# `side_orient = dict(PR.SIDE_ORIENT)`, and the AST walk below expects a dict
# LITERAL, so both files died with
#     AttributeError: 'Call' object has no attribute 'keys'
# — measured in ghcr.io/vibeic/vibeic-eda:0.3.16, 2 failed / 1 passed. A test
# that dies before its assertion is not testing what it says.
#
# WHY IT WAS NOT REPAIRED INSTEAD: THE DEFECT IS FIXED AND THE ORACLE IS WRONG.
#
# (1) The half turn this file was written to catch is GONE on both axes.
#     Computed from `_pad_ring`'s own algebra against the shipped constants:
#         rotate_cw(S=N,2)  = S   shipped N = FS   -> not a half turn
#         rotate_cw(W=FW,2) = FE  shipped E = W    -> not a half turn
#
# (2) Where the file still has an opinion, the opinion is REFUTED BY THE TOOL.
#     `_FLIP_X` below is right — flipX(S) = FS = the shipped north — but the
#     docstring's other half, "east = west.flipY()", is not what OpenROAD does.
#     Asked directly, at the pinned commit (OpenROAD 26Q3-1581, the build the
#     constants were measured on, gf180mcuD IO library):
#         ORIENT ps R0      ORIENT pn MX      ORIENT pw MXR90     ORIENT pe R90
#     West is a MIRROR and east is a PURE ROTATION — the placer alternates the
#     two, exactly as `_pad_ring.CORNER_ORIENT` already documents for corners.
#     `flipY(FW)` is E; the tool writes W. Repairing this file to read
#     `PR.SIDE_ORIENT` would therefore make it RED against a value three
#     OpenROAD builds agree on, and the only way to "fix" that red would be to
#     change a measured constant to satisfy a hand-transcribed table. That is
#     the failure this whole capture exists to record — see `../PROGRESS.md`,
#     which retracts an earlier conclusion drawn the same way.
#
# The coverage that replaced it asks the tool instead of the source text:
# `programs/tests/test_pad_ring.py::test_the_shipped_orientations_are_what_the_placer_produces`.

"""CANDIDATE test pinning F3d. RED on the current tree, GREEN under the fix.

Lives here and not in `programs/tests/` because it fails on `main` today, and a
red test there blocks every push. It moves in with the fix.

WHAT IT PINS. Upstream derives the opposite side of a pad ring by MIRRORING --
`north = south.flipX()`, `east = west.flipY()`, two lines of the tool's own
source. Our step derives it by a HALF TURN.

WHERE IT LOOKS, AND WHY THAT MATTERS. At the CALL SITE, not at the helper.
`rotate_cw` is a rotation helper; it is correctly named and correctly
implemented, and a correct fix does not touch it -- it adds a mirror and changes
who is called. AN EARLIER VERSION OF THIS FILE ASSERTED `rotate_cw(o, 2) ==
flipX(o)`, which demands a rotation helper behave like a mirror. That test was
RED on the broken tree and would have stayed RED after a correct fix: it was
UNSATISFIABLE. A test that can never go green gets muted, and muting it is
indistinguishable from the defect being fixed. The rewrite targets the call
site, which is what actually has to change.
"""
import ast
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[2] / "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: Helpers that MIRROR. A correct fix calls one of these for the opposite side.
_MIRRORING = {"flip_x", "flip_y", "flipx", "flipy", "mirror", "mirror_x",
              "mirror_y", "opposite_side_orient"}
#: Helpers that ROTATE. Correct in themselves; wrong for this job.
_ROTATING = {"rotate_cw", "rotate_ccw", "rotate"}

#: The tool's own mirror-about-X algebra, in DEF spelling: R0<->MX, R90<->MXR90,
#: R180<->MY, R270<->MYR90. Written out rather than derived so a wrong entry is
#: visible; an earlier draft of this table had E and W exchanged.
_FLIP_X = {"N": "FS", "FS": "N", "S": "FN", "FN": "S",
           "E": "FE", "FE": "E", "W": "FW", "FW": "W"}

#: The sides derived FROM another side. South and west are the declared ones;
#: north and east are their opposites, and upstream mirrors to get them.
_DERIVED_SIDES = ("N", "E")


def _opposite_side_calls(src: str) -> dict:
    """For each derived side, the helper `_place`'s `side_orient` calls."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", "") == "side_orient" for t in node.targets):
            continue
        out = {}
        for key, val in zip(node.value.keys, node.value.values):
            called = {getattr(c.func, "attr", "") or getattr(c.func, "id", "")
                      for c in ast.walk(val) if isinstance(c, ast.Call)}
            out[key.value] = {c for c in called if c}
        return out
    return {}


def test_the_footprint_assertion_cannot_see_the_defect():
    """DEMONSTRATION, not coverage. It PASSES on the broken tree, on purpose.

    The obvious way to test an orientation is to assert on the footprint. This
    writes that assertion out and shows it agreeing under BOTH the half turn we
    ship and the mirror upstream uses, because a rectangular master occupies
    the same bounding box either way. It is here so the next author does not
    write this assertion, watch it pass, and conclude the question is covered.

    Restored 2026-08-22: the README documented this test at length while the
    rewrite that made the sibling satisfiable had dropped it, so the file's
    stated protection did not exist. Measured, not argued — see below.
    """
    sys.path.insert(0, str(_PROGRAMS))
    import _pad_ring as PR

    master = (75.0, 350.0)   # the pad cell: 75 um along the row, 350 um deep
    units = 1000
    ours = PR.rotate_cw("S", 2)          # how this step derives north
    upstream = _FLIP_X["S"]              # how the tool derives north

    assert ours != upstream, (
        "the two derivations agree — this demonstration is stale, because it "
        "only means anything while they differ")
    assert PR.footprint(master, ours, units) == PR.footprint(
        master, upstream, units), (
        "the footprints differ, so a footprint assertion WOULD have caught "
        "this — update the sibling test's rationale, it is no longer true")


def test_the_opposite_side_is_derived_by_MIRRORING_as_upstream_does():
    calls = _opposite_side_calls(
        (_PROGRAMS / "pad_ring_gen.py").read_text(errors="replace"))
    assert calls, "could not read `side_orient` — the test is stale, not the code"
    failures = []
    for side in _DERIVED_SIDES:
        used = calls.get(side, set())
        if used & _ROTATING:
            failures.append(
                f"side {side}: derived with {sorted(used & _ROTATING)} (a ROTATION); "
                f"upstream mirrors — north = south.flipX(), east = west.flipY()")
        elif not (used & _MIRRORING):
            failures.append(
                f"side {side}: derived with {sorted(used) or '(no call)'}, which is "
                f"neither a known mirror nor a known rotation — if this is a new "
                f"mirror helper, add its name to _MIRRORING")
    assert not failures, (
        "the opposite side must be derived by upstream's MIRROR, not a half "
        "turn:\n  " + "\n  ".join(failures))


if __name__ == "__main__":
    try:
        test_the_opposite_side_is_derived_by_MIRRORING_as_upstream_does()
        print("PASS"); sys.exit(0)
    except AssertionError as e:
        print("FAIL\n      " + str(e).replace("\n", "\n      ")); sys.exit(1)
