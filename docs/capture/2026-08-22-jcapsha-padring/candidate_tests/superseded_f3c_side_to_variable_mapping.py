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
# WHY IT WAS NOT REPAIRED INSTEAD: ITS SUBJECT NO LONGER EXISTS.
# This pinned which SIDES each `PAD_ROTATION_*` variable drives. No rotation
# variable drives any side any more. `pad_ring_gen.py:927-946` REFUSES a run
# that declares a non-default value on any of the three (SKIP / NOT DETERMINED,
# naming the variable), and at the default every side takes the placer's own
# measured orientation from `_pad_ring.SIDE_ORIENT`. There is no side-to-
# variable mapping left to read out of the source, so there is nothing here to
# repair — only a different test to write, which `programs/tests/test_pad_ring.py`
# has already written against the tool itself.

"""CANDIDATE test pinning F3c. RED on the current tree, by design.

Same reason as its sibling for living here rather than in `programs/tests/`: it
fails on `main` today.

WHAT IT PINS. Which SIDES each of the two rotation variables applies to.

  the tool, from its own command reference at the pinned commit:
      -rotation_horizontal   applies to the horizontal PADS -- east and west
      -rotation_vertical     applies to the vertical PADS   -- north and south

  the flow layer we re-implement passes them straight through, describing them
  in the tool's own words ("the horizontal sites") and redefining nothing.

  ours, from `pad_ring_gen._place`:
      PAD_ROTATION_HORIZONTAL -> south and north
      PAD_ROTATION_VERTICAL   -> west  and east

Inverted on both axes, and invisible at the default because both variables
carry R0 there -- which is why nothing caught it.

The check is a comparison of two four-entry mappings, exactly as the capture
record says. It reads OUR mapping out of the source rather than restating it,
so the test cannot drift into agreeing with a copy of itself.
"""
import ast
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[2] / "vibe-ic-marketplace/plugins/vibe-ic/programs"

#: The tool's contract, transcribed from its command reference. The one hand-
#: written half of this test, and it is four entries so it can be checked by eye
#: against the quoted documentation above.
UPSTREAM_SIDE_OF = {
    "PAD_ROTATION_HORIZONTAL": {"E", "W"},
    "PAD_ROTATION_VERTICAL": {"N", "S"},
}


def ours_side_of() -> dict:
    """Which variable our `_place` applies to which side, READ FROM THE SOURCE.

    Parsed rather than restated: a test that hard-codes what it expects our code
    to say stops testing our code the moment somebody edits it.
    """
    src = (_PROGRAMS / "pad_ring_gen.py").read_text(errors="replace")
    tree = ast.parse(src)
    out: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", "") == "side_orient" for t in node.targets):
            continue
        for key, val in zip(node.value.keys, node.value.values):
            side = key.value
            names = {n.value for n in ast.walk(val)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and n.value.startswith("PAD_ROTATION_")}
            for var in names:
                out.setdefault(var, set()).add(side)
    return out


def test_each_rotation_variable_drives_the_sides_upstream_says_it_does():
    ours = ours_side_of()
    assert ours, ("could not read `side_orient` out of the producer -- the test "
                  "is stale, not the code")
    failures = []
    for var, upstream_sides in UPSTREAM_SIDE_OF.items():
        got = ours.get(var, set())
        if got != upstream_sides:
            failures.append(
                f"{var}: ours drives {sorted(got) or '(nothing)'}, "
                f"upstream defines it for {sorted(upstream_sides)}")
    assert not failures, (
        "each rotation variable must drive the sides its upstream defines it "
        "for:\n  " + "\n  ".join(failures))


if __name__ == "__main__":
    try:
        test_each_rotation_variable_drives_the_sides_upstream_says_it_does()
        print("PASS  test_each_rotation_variable_drives_the_sides_upstream_says_it_does")
        sys.exit(0)
    except AssertionError as e:
        print("FAIL  test_each_rotation_variable_drives_the_sides_upstream_says_it_does")
        print("      " + str(e).replace("\n", "\n      "))
        sys.exit(1)
