#!/usr/bin/env python3
"""A special net's SHAPE is a property of the PATH, not of the net.

DEF states shape per wiring path (`+ ROUTED <layer> <w> + SHAPE FOLLOWPIN`),
and one supply net carries many paths of different shapes. That is what a power
grid IS: follow-pins on the lowest layer, STRIPEs above them, all on net VDD.

The reader derived the flag from `"FOLLOWPIN" in entry` — a substring test over
the WHOLE net entry — so every strap of a net that has a follow-pin anywhere
was labelled a follow-pin.

WHY IT MATTERS ON THIS GATE SPECIFICALLY. The error is one-directional: it can
only ever ADD the label, never remove it. So a report in which every finding
agrees on the shape does not read as a broken flag; it reads as a coherent
story about cell rows, and it is the story a person acts on. A gate that blocks
must not mislabel the metal it blocks for.

The fixture below is a single net whose three paths declare three different
shapes, all crossing the same obstruction. Correct output distinguishes them.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
_GATE = os.path.join(_PROGRAMS, "macro_obs_geometry_intersect_check.py")


def _gate():
    spec = importlib.util.spec_from_file_location("_macro_obs_shape", _GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_macro_obs_shape"] = mod
    spec.loader.exec_module(mod)
    return mod


# One macro, 100.0 x 60.0, full-footprint obstruction on three layers. Placed
# at ( 100000 100000 ) with UNITS 1000 -> x[100000,200000] y[100000,160000].
LEF = """
MACRO block_a
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
    LAYER MET4 ;
      RECT 0 0 100.0 60.0 ;
    LAYER MET5 ;
      RECT 0 0 100.0 60.0 ;
  END
END block_a
"""

# ONE net. Three paths. Three different declared shapes. Each spans the macro:
#   MET1 horizontal across x, at y inside the macro   -> SHAPE FOLLOWPIN
#   MET4 vertical across y, at x inside the macro     -> SHAPE STRIPE
#   MET5 vertical across y, at x inside the macro     -> no SHAPE declared
DEF = """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 1 ;
- u_blk block_a + FIXED ( 100000 100000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
- VDD ( * VPWR )
  + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 0 130000 ) ( 300000 * )
    NEW MET4 1600 + SHAPE STRIPE ( 150000 0 ) ( * 300000 )
    NEW MET5 1600 ( 170000 0 ) ( * 300000 )
  + USE POWER
 ;
END SPECIALNETS
END DESIGN
"""


def _by_layer(records):
    return {r["layer"]: r for r in records}


def test_each_path_carries_its_own_shape():
    """REGRESSION. On the unfixed reader all three report FOLLOWPIN."""
    M = _gate()
    segs, _gaps = M.parse_routed_segments_with_gaps(DEF)
    by = _by_layer(segs)
    assert set(by) == {"MET1", "MET4", "MET5"}, sorted(by)
    assert by["MET1"]["shape"] == "FOLLOWPIN"
    assert by["MET4"]["shape"] == "STRIPE"
    assert by["MET5"]["shape"] is None, "a path that declares no shape has none"


def test_followpin_flag_is_not_inherited_from_a_sibling_path():
    """REGRESSION, stated as the flag the report prints."""
    M = _gate()
    segs, _gaps = M.parse_routed_segments_with_gaps(DEF)
    by = _by_layer(segs)
    assert by["MET1"]["followpin"] is True
    assert by["MET4"]["followpin"] is False
    assert by["MET5"]["followpin"] is False


def test_findings_carry_the_path_shape():
    """The verdict records the same attribution the parser made."""
    M = _gate()
    rep = M.audit(DEF, [LEF], ["synthetic.lef"])
    by = _by_layer(rep["findings"])
    assert len(rep["findings"]) == 3, rep["findings"]
    assert by["MET1"]["followpin"] is True
    assert by["MET4"]["followpin"] is False
    assert by["MET4"]["shape"] == "STRIPE"
    assert by["MET5"]["shape"] is None


def test_a_genuinely_all_followpin_net_is_unchanged():
    """OVER-REACH CONTROL — and it is a control precisely because it passes in
    BOTH states. When every path really does declare FOLLOWPIN the flag must
    still be set on every one of them: the fix removes an INHERITANCE, not the
    label. Asserted on `followpin` alone, which both the old and the new reader
    emit; asserting the new `shape` key here would make this fail on the
    unfixed tree for the wrong reason and stop being a control at all."""
    M = _gate()
    d = DEF.replace("NEW MET4 1600 + SHAPE STRIPE",
                    "NEW MET4 1600 + SHAPE FOLLOWPIN").replace(
                        "NEW MET5 1600 (", "NEW MET5 1600 + SHAPE FOLLOWPIN (")
    segs, _gaps = M.parse_routed_segments_with_gaps(d)
    assert len(segs) == 3
    assert all(s["followpin"] for s in segs), segs


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
