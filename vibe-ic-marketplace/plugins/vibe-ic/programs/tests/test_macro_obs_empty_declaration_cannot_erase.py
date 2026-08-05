#!/usr/bin/env python3
"""A LEF that describes no obstructions must not erase one that does.

`audit` merged per-file `parse_macro_obs` results with `dict.update`, which is
last-wins, and default discovery is `sorted()`. So when several LEFs declare the
same macro, the winner was decided by filename.

That is harmless while every declaration carries the same geometry. It is not
harmless when one carries none: *"this file does not describe obstructions"* and
*"this macro has no obstructions"* are different facts, and last-wins collapses
the first onto the second.

Measured on a real post-route project — six LEFs in one IP directory declare the
same macro, five metal-stack variants with 61-65 OBS rects and one antenna-data
file with zero. `sorted()` puts the antenna file last (`a` follows `M`):

    LEF order                     merged OBS rects   crossings   verdict
    sorted()    (antenna last)                   0           0   PASS
    reversed    (antenna first)                 61          28   FAIL
    antenna excluded                            65          45   FAIL

The gate printed `[PASS] ... All N placed master(s) resolved to a LEF` — a
completeness claim that is true and does not mean what it reads as. The master
resolved; its obstructions did not load.

The tests below are written against the observable property — *the answer may
not depend on the order the files are supplied in* — not against the merge
implementation, so a different correct merge also passes them.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)


def _gate():
    p = os.path.join(_PROGRAMS, "macro_obs_geometry_intersect_check.py")
    spec = importlib.util.spec_from_file_location("_macro_obs_merge_gate", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_macro_obs_merge_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


MASTER = "big_ip"

# The real macro, as a vendor's metal-stack variant ships it.
LEF_WITH_OBS = f"""
MACRO {MASTER}
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
  END
END {MASTER}
"""

# The same macro in a file that carries antenna data and nothing else — a real
# and ordinary shape. It declares the macro; it describes no obstruction.
LEF_NO_OBS = f"""
MACRO {MASTER}
  SIZE 100.0 BY 60.0 ;
END {MASTER}
"""

# A second variant with MORE obstruction than the first: a genuine disagreement
# between two non-empty declarations, which is a different case from an empty one.
LEF_OTHER_OBS = f"""
MACRO {MASTER}
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
    LAYER MET2 ;
      RECT 0 0 100.0 60.0 ;
  END
END {MASTER}
"""

N_THROUGH, N_CLEAR = 6, 4
_X1, _X2 = 0, 300000
_YS_THROUGH = [102000 + i * 2000 for i in range(N_THROUGH)]
_YS_CLEAR = [300000 + i * 2000 for i in range(N_CLEAR)]


def _def(ys) -> str:
    paths = [f"  + ROUTED MET1 480 + SHAPE FOLLOWPIN ( {_X1} {ys[0]} ) ( {_X2} * )"]
    paths += [f"    NEW MET1 480 + SHAPE FOLLOWPIN ( {_X1} {y} ) ( {_X2} * )"
              for y in ys[1:]]
    return f"""VERSION 5.8 ;
DESIGN t ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 400000 400000 ) ;
COMPONENTS 1 ;
- u_ip {MASTER} + PLACED ( 100000 100000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
- VDD ( * VDD )
{chr(10).join(paths)}
  + USE POWER ;
END SPECIALNETS
END DESIGN
"""


ALL_YS = _YS_THROUGH + _YS_CLEAR


def _crossings(lefs) -> int:
    return len(_gate().audit(_def(ALL_YS), lefs)["findings"])


# ------------------------------------------------------------------ the defect
@pytest.mark.parametrize("order,label", [
    ([LEF_WITH_OBS, LEF_NO_OBS], "obstruction file first, empty file last"),
    ([LEF_NO_OBS, LEF_WITH_OBS], "empty file first, obstruction file last"),
])
def test_an_empty_declaration_cannot_erase_a_real_one(order, label):
    """THE DEFECT. Under last-wins the first ordering reported 0 crossings —
    the ordering `sorted()` actually produces for the real filenames."""
    assert _crossings(order) == N_THROUGH, label


def test_the_answer_does_not_depend_on_file_order():
    """The property, stated directly: which files were supplied is a fact about
    the design; the ORDER they were supplied in is not."""
    answers = {
        "with,empty": _crossings([LEF_WITH_OBS, LEF_NO_OBS]),
        "empty,with": _crossings([LEF_NO_OBS, LEF_WITH_OBS]),
        "with only": _crossings([LEF_WITH_OBS]),
    }
    assert set(answers.values()) == {N_THROUGH}, answers


def test_the_merge_keeps_the_geometry_not_the_last_file():
    g = _gate()
    merged, _ = g.merge_macro_obs(
        [g.parse_macro_obs(LEF_WITH_OBS), g.parse_macro_obs(LEF_NO_OBS)])
    assert len(merged[MASTER]["obs"]) == 1


# --------------------------------------------- a real disagreement is disclosed
def test_two_different_non_empty_declarations_are_reported_not_silently_picked():
    """An empty file is unambiguous — it says nothing. Two files that BOTH
    describe obstructions, differently, is a real ambiguity this gate cannot
    settle from LEF alone. It must surface it rather than quietly prefer one."""
    g = _gate()
    rep = g.audit(_def(ALL_YS), [LEF_WITH_OBS, LEF_OTHER_OBS])
    conflicts = rep["obs_declaration_conflicts"]
    assert len(conflicts) == 1, conflicts
    assert conflicts[0]["master"] == MASTER


def test_an_empty_declaration_is_not_reported_as_a_conflict():
    """REVERSE CASE. A file that describes nothing is not a disagreement, and
    reporting it as one would make this noisy on every project that ships an
    antenna LEF — which is most of them."""
    g = _gate()
    rep = g.audit(_def(ALL_YS), [LEF_WITH_OBS, LEF_NO_OBS])
    assert rep["obs_declaration_conflicts"] == []


def test_identical_declarations_are_not_a_conflict():
    """REVERSE CASE. The same macro shipped twice, byte-identical, is ordinary."""
    g = _gate()
    rep = g.audit(_def(ALL_YS), [LEF_WITH_OBS, LEF_WITH_OBS])
    assert rep["obs_declaration_conflicts"] == []


# ------------------------------------------------------- over-reach controls
@pytest.mark.parametrize("order", [
    [LEF_WITH_OBS, LEF_NO_OBS],
    [LEF_NO_OBS, LEF_WITH_OBS],
    [LEF_WITH_OBS],
])
def test_metal_that_clears_the_macro_is_still_not_a_crossing(order):
    """The control that matters most: a merge that recovered its count by
    keeping MORE geometry would pass everything above and be worse than the
    defect. Nothing here goes near the obstruction; the answer is 0 in every
    ordering."""
    assert len(_gate().audit(_def(_YS_CLEAR), order)["findings"]) == 0


def test_a_master_only_ever_declared_empty_stays_empty():
    """REVERSE CASE. If no file describes an obstruction, the macro genuinely
    has none, and inventing one would be a fabricated finding on a blocking
    gate."""
    assert _crossings([LEF_NO_OBS, LEF_NO_OBS]) == 0


# ------------------------------- the disagreement rule is stated, not incidental
def test_the_smallest_obstruction_set_wins_a_disagreement():
    """Two non-empty declarations disagreeing is a vendor shipping metal-stack
    variants. The gate cannot know which one the run loaded, so it takes the
    FLOOR — the only choice that cannot manufacture a finding out of an
    ambiguity, on a gate that blocks."""
    g = _gate()
    merged, conflicts = g.merge_macro_obs(
        [g.parse_macro_obs(LEF_OTHER_OBS), g.parse_macro_obs(LEF_WITH_OBS)])
    assert len(merged[MASTER]["obs"]) == 1        # the smaller of 1 and 2
    assert conflicts and conflicts[0]["kept_rect_count"] == 1
    assert conflicts[0]["other_rect_count"] == 2


@pytest.mark.parametrize("order", [
    [LEF_WITH_OBS, LEF_OTHER_OBS],
    [LEF_OTHER_OBS, LEF_WITH_OBS],
    [LEF_OTHER_OBS, LEF_NO_OBS, LEF_WITH_OBS],
    [LEF_NO_OBS, LEF_OTHER_OBS, LEF_WITH_OBS],
])
def test_a_disagreement_resolves_the_same_way_in_any_order(order):
    """The property. `sorted()` decided the answer before; nothing about file
    order may decide it now."""
    g = _gate()
    merged, _ = g.merge_macro_obs([g.parse_macro_obs(t) for t in order])
    assert len(merged[MASTER]["obs"]) == 1

