#!/usr/bin/env python3
"""A via-only special-wire entry is not an abandoned path.

DEF spells a bare via drop inside a special net as a path whose last token is a
via name and whose width is 0:

    NEW <layer> 0 + SHAPE STRIPE ( x y ) <viaName>

That is ordinary. A power grid's layer-to-layer stack is written exactly that
way, and the via usually comes from the TECH LEF, which this gate does not read
— so its two routing layers are unresolvable here.

The reader treated any unresolvable via as an ABANDONED PATH. For a via-only
entry that is a gap over nothing: the via is the last token, so no metal
follows whose layer could be unknown, and a via is a point, which cannot SPAN
an obstruction under any reading. The measured signature is a recorded
abandonment carrying `points_unread == 0` — the reader's own arithmetic saying
nothing was left to read.

Because ANY recorded gap forces the whole program to rc=2 CANNOT DETERMINE,
one via-only entry withheld the verdict on an entire design.

WHAT MUST NOT MOVE. A via that is genuinely followed by more coordinates still
abandons the path and still reports the gap: that metal's layer really is
unknown, and this gate must not guess a layer on a verdict that blocks. Both
directions are asserted below.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)
_GATE = os.path.join(_PROGRAMS, "macro_obs_geometry_intersect_check.py")


def _gate():
    spec = importlib.util.spec_from_file_location("_macro_obs_via_only", _GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_macro_obs_via_only"] = mod
    spec.loader.exec_module(mod)
    return mod


# One macro, 100.0 x 60.0, full-footprint obstruction. Placed at
# ( 100000 100000 ) with UNITS 1000, so it occupies DEF units
# x[100000, 200000] y[100000, 160000].
LEF = """
MACRO block_a
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
  END
END block_a
"""

_HEAD = """VERSION 5.8 ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 1 ;
- u_blk block_a + FIXED ( 100000 100000 ) N ;
END COMPONENTS
VIAS 1 ;
- defvia_a_b + LAYERS MET1 CUTAB MET2 + RECT CUTAB ( -35 -35 ) ( 35 35 ) ;
END VIAS
"""

_TAIL = "END DESIGN\n"


def _design(specialnets: str) -> str:
    return _HEAD + "SPECIALNETS 1 ;\n" + specialnets + "END SPECIALNETS\n" + _TAIL


# A clean layout: one follow-pin BELOW the macro (y=50000, outside it), plus a
# via-only entry whose via is declared only in the tech LEF. Nothing spans the
# obstruction, and nothing is left unread.
VIA_ONLY = _design(
    "- VDD ( * VPWR )\n"
    "  + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 0 50000 ) ( 300000 * )\n"
    "    NEW MET2 0 + SHAPE STRIPE ( 160000 130000 ) M2M3_TECHVIA\n"
    "  + USE POWER\n"
    " ;\n")

# The same design except the via really is followed by more metal. The layer of
# that metal is unknown, so the path IS abandoned and the gap IS real.
VIA_THEN_METAL = _design(
    "- VDD ( * VPWR )\n"
    "  + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 0 50000 ) ( 300000 * )\n"
    "    NEW MET2 1600 + SHAPE STRIPE ( 160000 130000 ) M2M3_TECHVIA "
    "( 160000 250000 ) ( 280000 250000 )\n"
    "  + USE POWER\n"
    " ;\n")


def test_via_only_entry_records_no_abandonment():
    """REGRESSION. Fails on the unfixed reader, which records one gap here."""
    M = _gate()
    _segs, gaps = M.parse_routed_segments_with_gaps(VIA_ONLY)
    assert gaps == [], (
        "a via-only entry left nothing unread, so it is not an abandoned "
        f"path; got {gaps}")


def test_via_only_entry_reaches_a_verdict():
    """The whole point: rc must not be 2 merely because a via-only entry
    exists. This layout is clean, so the verdict is 0."""
    M = _gate()
    rep = M.audit(VIA_ONLY, [LEF], ["synthetic.lef"])
    assert rep["truncated_paths"] == [], rep["truncated_paths"]
    assert rep["unread_points"] == 0
    assert rep["findings"] == []


def test_metal_after_an_unresolvable_via_is_still_abandoned():
    """OVER-REACH CONTROL. The fix must not silence a real gap."""
    M = _gate()
    _segs, gaps = M.parse_routed_segments_with_gaps(VIA_THEN_METAL)
    assert len(gaps) == 1, gaps
    assert gaps[0]["via"] == "M2M3_TECHVIA"
    assert gaps[0]["points_unread"] == 2, gaps[0]


def _run(tmp_path, def_text):
    proj = tmp_path
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(def_text)
    (proj / "macro.lef").write_text(LEF)
    return subprocess.run([sys.executable, _GATE, str(proj)],
                          capture_output=True, text=True)


def test_cli_via_only_exits_zero_not_two(tmp_path):
    """END TO END. On the unfixed program this exits 2 CANNOT DETERMINE."""
    r = _run(tmp_path, VIA_ONLY)
    assert r.returncode == 0, (
        f"rc={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")


def test_cli_metal_after_via_still_refuses(tmp_path):
    """OVER-REACH CONTROL, end to end: a real truncation still withholds the
    verdict."""
    r = _run(tmp_path, VIA_THEN_METAL)
    assert r.returncode == 2, (
        f"rc={r.returncode}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
    assert "INCOMPLETE" in (r.stdout + r.stderr)


if __name__ == "__main__":
    sys.exit(pytest.main([os.path.abspath(__file__), "-v"]))
