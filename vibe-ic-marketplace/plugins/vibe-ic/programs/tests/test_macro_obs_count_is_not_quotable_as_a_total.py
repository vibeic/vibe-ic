#!/usr/bin/env python3
"""The crossing count must not be quotable as a total when the read was partial.

`len(findings)` is the number of crossings this comparison FOUND. It is the
number that EXIST only when the comparison saw all of its own inputs. Three
already-measured conditions break that: an abandoned path (supply metal whose
layer is unknown, so it was never intersected), discarded OBS evidence, and a
placed master with no LEF.

The program already conceded this — in prose, at the BOTTOM of a FAIL report,
below the finding list. Two things follow from where it was said:

  * the headline, which is the line a person quotes, stated the floor as a
    total; and
  * the JSON report, which is what a machine quotes, said nothing at all, so
    `len(rep["findings"])` was quotable with no way to learn it was a floor.

A caveat kept in a different place from the number it qualifies is a caveat
that gets separated from it.

ALSO ASSERTED: the per-layer split, and the layers the gate is SILENT about. A
crossing can only be found where BOTH an obstruction rect and a supply segment
exist, so a layer whose metal was never read drops out of the comparison while
the total still reads as if it covered everything. That is disclosed — but only
in the presence of truncation, because a macro may legitimately declare an
obstruction on a layer the design carries no supply metal on, and calling THAT
a gap would be the gate crying wolf. The conjunction is the condition, and both
halves of it are tested.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
_GATE = os.path.join(_PROGRAMS, "macro_obs_geometry_intersect_check.py")


def _gate():
    spec = importlib.util.spec_from_file_location("_macro_obs_count", _GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_macro_obs_count"] = mod
    spec.loader.exec_module(mod)
    return mod


# Macro 100.0 x 60.0 with obstructions on two layers, placed at
# ( 100000 100000 ), UNITS 1000 -> x[100000,200000] y[100000,160000].
LEF = """
MACRO block_a
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
    LAYER MET5 ;
      RECT 0 0 100.0 60.0 ;
  END
END block_a
"""

_HEAD = """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 1 ;
- u_blk block_a + FIXED ( 100000 100000 ) N ;
END COMPONENTS
"""


def _design(nets: str) -> str:
    return (_HEAD + "SPECIALNETS 1 ;\n" + nets + "END SPECIALNETS\nEND DESIGN\n")


# COMPLETE read: one MET1 follow-pin spanning the macro. Nothing truncated.
# The macro also declares MET5, and the design genuinely carries no MET5
# supply metal — a TRUE clearance on that layer.
COMPLETE = _design(
    "- VDD ( * VPWR )\n"
    "  + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 0 130000 ) ( 300000 * )\n"
    "  + USE POWER\n"
    " ;\n")

# TRUNCATED read: the same MET1 crossing, plus a MET5 path that is abandoned
# at an unresolvable via with real metal after it. MET5 metal exists and was
# NOT read, so the MET5 obstruction was never compared against anything.
TRUNCATED = _design(
    "- VDD ( * VPWR )\n"
    "  + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 0 130000 ) ( 300000 * )\n"
    "    NEW MET4 1600 + SHAPE STRIPE ( 150000 0 ) M4M5_TECHVIA "
    "( 150000 300000 ) ( 280000 300000 )\n"
    "  + USE POWER\n"
    " ;\n")


def test_a_complete_read_publishes_a_total():
    """OVER-REACH CONTROL. A complete read must NOT be hedged — otherwise the
    hedge is on every report and means nothing."""
    M = _gate()
    rep = M.audit(COMPLETE, [LEF], ["synthetic.lef"])
    assert rep["findings_count"] == 1
    assert rep["count_is_floor"] is False, rep["count_floor_reasons"]
    assert rep["count_floor_reasons"] == []


def test_a_truncated_read_marks_the_count_a_floor():
    """REGRESSION. The unfixed report carries no such field at all."""
    M = _gate()
    rep = M.audit(TRUNCATED, [LEF], ["synthetic.lef"])
    assert rep["count_is_floor"] is True
    assert rep["count_floor_reasons"], "a floor must say why it is one"
    assert any("abandoned" in r for r in rep["count_floor_reasons"])


def test_the_per_layer_split_is_published_by_the_gate():
    """REGRESSION. A consumer deriving this from `findings` cannot see a layer
    that produced none, which is the layer that matters."""
    M = _gate()
    rep = M.audit(COMPLETE, [LEF], ["synthetic.lef"])
    assert rep["findings_by_layer"] == {"met1": 1}
    assert rep["obs_layers_compared"] == ["met1", "met5"]


def test_a_layer_with_no_metal_read_is_named():
    """REGRESSION. The obstruction on MET5 was never compared against anything
    because no MET5 segment was read."""
    M = _gate()
    for d in (COMPLETE, TRUNCATED):
        rep = M.audit(d, [LEF], ["synthetic.lef"])
        assert rep["obs_layers_with_no_supply_segment_read"] == ["met5"], d


def test_no_metal_on_a_layer_is_a_floor_ONLY_when_the_read_was_truncated():
    """OVER-REACH CONTROL, and the sharpest one here.

    A macro may declare an obstruction on a layer the design carries no supply
    metal on. 0 findings there is then a TRUE clearance, and calling it a gap
    would be this gate crying wolf on every design with an unused upper layer.
    It is a gap only in conjunction with truncation."""
    M = _gate()
    clean = M.audit(COMPLETE, [LEF], ["synthetic.lef"])
    assert clean["obs_layers_with_no_supply_segment_read"] == ["met5"]
    assert clean["count_is_floor"] is False, (
        "an unused layer alone must not hedge the count")

    trunc = M.audit(TRUNCATED, [LEF], ["synthetic.lef"])
    assert trunc["count_is_floor"] is True
    assert any("silence, not a clearance" in r
               for r in trunc["count_floor_reasons"]), \
        trunc["count_floor_reasons"]


# ------------------------------------------------------------------ end to end
def _run(tmp_path, def_text):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(def_text)
    (tmp_path / "macro.lef").write_text(LEF)
    out = tmp_path / "rep.json"
    r = subprocess.run(
        [sys.executable, _GATE, str(tmp_path), "--json", str(out)],
        capture_output=True, text=True)
    return r, json.loads(out.read_text())


def test_headline_says_at_least_when_the_read_was_partial(tmp_path):
    """REGRESSION, on the line a person actually quotes."""
    r, rep = _run(tmp_path, TRUNCATED)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "at least 1 supply segment(s) SPAN" in r.stdout, r.stdout
    assert "THIS COUNT IS A FLOOR, NOT A TOTAL" in r.stdout, r.stdout
    assert rep["count_is_floor"] is True


def test_headline_states_a_total_when_the_read_was_complete(tmp_path):
    """OVER-REACH CONTROL on the same line — asserted on stdout ALONE so that
    it passes in BOTH states. A hedge printed on every report is a hedge that
    means nothing, and only a control that the unfixed tree also satisfies can
    catch a fix that adds one."""
    r, _rep = _run(tmp_path, COMPLETE)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "1 supply segment(s) SPAN" in r.stdout
    assert "at least" not in r.stdout, r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
