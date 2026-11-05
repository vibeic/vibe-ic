#!/usr/bin/env python3
"""#1215-PDN — DERIVED (never tuned) EM strap sizing + real-width screening.

Two halves, one discipline: the strap width is COMPUTED from the PDK's own
Jmax and the design's measured supply current, and the gate then confirms
independently against the width the router actually drew. No width is ever
tried-until-green, the Jmax rule/margin/gate are untouched, and a first pass
with no measurement keeps the PDN byte-identical.

(A) `em_current_density_check.discover_def_pg_min_widths` retains a DEF
    layer-width inventory for planning. The Jmax gate now requires local
    same-net conductor geometry for each PSM edge; neither that inventory
    nor the LEF layer default proves an individual edge width.

(B) `phase3_one_shot_runner._pdn_em_width_floor` — the conservation bound:
    no PDN segment can carry more than the injected I_total = P/V, so

        w_em(layer) = I_total / (jmax_per_width(layer) * (1 - margin))

    guarantees no strap can exceed the margined Jmax under ANY current
    distribution. One-shot derivation, nothing to iterate. Applied as a
    FLOOR (max) on strap layers only; follow-pin rails are the cell
    architecture's and are judged (not sized) at their DEF-stated width.

chip-AGNOSTIC: LEF/DEF grammar and arithmetic only; layer names below are
arbitrary tokens.
"""
import sys
import tempfile
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import em_current_density_check as EMC  # noqa: E402

# mkdtemp, not tmp_path (containerised-suite tmp_path newline hazard).

_TLEF = """LAYER MetalA
  TYPE ROUTING ;
  WIDTH 0.28 ;
  THICKNESS 0.54 ;
  DCCURRENTDENSITY AVERAGE 0.67 ;
END MetalA
LAYER MetalB
  TYPE ROUTING ;
  WIDTH 0.44 ;
  THICKNESS 1.19 ;
  DCCURRENTDENSITY AVERAGE 1.5 ;
END MetalB
"""

_DEF = """VERSION 5.8 ;
DESIGN unit ;
UNITS DISTANCE MICRONS 2000 ;
SPECIALNETS 2 ;
    - VDD ( * VDD ) + USE POWER
      + ROUTED MetalA 3200 + SHAPE STRIPE ( 0 0 ) ( 100000 0 )
        NEW MetalA 0 ( 0 0 ) viaX
        NEW MetalB 1200 + SHAPE STRIPE ( 0 0 ) ( 0 100000 ) ;
    - VSS ( * VSS ) + USE GROUND
      + ROUTED MetalA 3200 + SHAPE STRIPE ( 0 4000 ) ( 100000 4000 ) ;
END SPECIALNETS
END DESIGN
"""


# ---------------------------------------------------------------- (A) ----
def test_def_pg_min_widths_parses_specialnets_and_skips_via_points():
    d = Path(tempfile.mkdtemp(prefix="i1215d_"))
    f = d / "unit.def"
    f.write_text(_DEF)
    w = EMC.discover_def_pg_min_widths(f)
    # 3200 dbu / 2000 = 1.6 um; 1200/2000 = 0.6; the `NEW MetalA 0` via
    # point must NOT drag MetalA's bound to zero.
    assert w == {"metala": 1.6, "metalb": 0.6}
    # project-dir form resolves the canonical PnR DEF path.
    proj = Path(tempfile.mkdtemp(prefix="i1215p_"))
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "unit.def").write_text(_DEF)
    assert EMC.discover_def_pg_min_widths(proj) == {"metala": 1.6,
                                                    "metalb": 0.6}
    # absence degrades to {} (the LEF fallback), never an error.
    assert EMC.discover_def_pg_min_widths(Path(tempfile.mkdtemp())) == {}


def _screen(cur_a, def_widths):
    table = EMC.parse_lef_jmax(_TLEF)
    seg = {"layer0": "MetalA", "layer1": "MetalA", "net": "VDD",
           "current_A": cur_a, "width_um": None}
    return EMC._screen_segment(seg, table, 0.10, 2.0, def_widths)


def test_def_width_bound_judges_the_wire_the_router_drew():
    """Layer-level widths cannot claim an edge's actual cross section."""
    r_lef = _screen(2.0e-3, None)
    assert r_lef["status"] == "unscreened"
    assert r_lef["reason"] == "segment_conductor_geometry_unproven"
    r_def = _screen(2.0e-3, {"metala": 1.6})
    assert r_def["status"] == "unscreened"
    assert r_def["reason"] == "segment_conductor_geometry_unproven"


def test_measured_segment_width_still_controls_numeric_screen():
    table = EMC.parse_lef_jmax(_TLEF)
    seg = {"layer0": "MetalA", "layer1": "MetalA", "net": "VDD",
           "current_A": 2.0e-3, "width_um": 0.30,
           "width_source": "same_net_geometry"}
    r = EMC._screen_segment(seg, table, 0.10, 2.0, {"metala": 1.6})
    assert r["width_source"] == "same_net_geometry" and r["width_um"] == 0.30


# ---------------------------------------------------------------- (B) ----
















if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_def_discovery_is_newest_first_and_skips_specialnets_free_defs():
    """The wrong-subject incident: alphabetical [0] picked a stale
    PDN-failed filled.def with zero SPECIALNETS and the gate judged LEF
    widths while the fresh routed DEF carried the sized straps. Newest
    non-empty wins; a newer SPECIALNETS-free DEF (floorplan-shaped) must
    not blank the whole project."""
    import os
    proj = Path(tempfile.mkdtemp(prefix="i1215o_"))
    pnr = proj / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    old = pnr / "a_routed.def"
    old.write_text(_DEF)                       # has SPECIALNETS (1.6 / 0.6)
    os.utime(old, (1000, 1000))
    new_empty = pnr / "b_floorplan.def"        # newer, no SPECIALNETS
    new_empty.write_text("VERSION 5.8 ;\nUNITS DISTANCE MICRONS 2000 ;\n"
                         "END DESIGN\n")
    os.utime(new_empty, (2000, 2000))
    assert EMC.discover_def_pg_min_widths(proj) == {"metala": 1.6,
                                                    "metalb": 0.6}
    newest = pnr / "c_final.def"               # newest, different widths
    newest.write_text(_DEF.replace("3200", "14480"))
    os.utime(newest, (3000, 3000))
    assert EMC.discover_def_pg_min_widths(proj) == {"metala": 7.24,
                                                    "metalb": 0.6}
