#!/usr/bin/env python3
"""N4 — `--die-um auto` sizes the CORE from the cells the netlist HAS.

MEASURED DEFECT (lane cmpb, 2026-09-28, image 0.3.83; spm x gf180mcuD as a
HARDMACRO, the same RTL fed to LibreLane and ORFS):

    die-um=auto -> 85x85 (cells=273, avg_cell=13.17um2 [site-LEF], target_util=0.5)
    [INFO IFP-0104] Effective utilization: 2.193
    [ERROR PDN-0185] Insufficient width (64.40 um) to add straps on layer Metal4
    PDN_GRID_EMPTY -> pnr rc=1, no layout

Three faults, one per test group below:
  1. the mean cell was `site area x 6.0` — a sky130-hd width in sites, a PDK
     constant in chip-agnostic code. gf180 7t: 0.56 x 3.92 x 6 = 13.17 um^2;
     this netlist's own synthesis stat: 8857.632 um^2 / 273 = 32.4 um^2.
  2. that area sized the DIE and the 10 um inset was then cut out of it, so the
     core carried 2.19x its cells.
  3. nothing checked that the core holds one period of the PDK's power straps
     (Metal4 pitch 153.6 um), so pdngen built no grid.

The rule now: the area is READ (the synthesis stat bound to this netlist's
sha256, else every instance's own LEF SIZE); the CORE is sized from it at the
target utilisation; the die is the core plus the inset; the core is grown to
the strap floor when auto, and a pinned core below it is REFUSED with numbers.

chip-, PDK- and vendor-AGNOSTIC: every fixture below is synthetic.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROG))

import phase3_one_shot_runner as R  # noqa: E402
from _ppa import power as PP  # noqa: E402

# A 7-track-shaped library: row site 0.56 x 3.92 (2.1952 um^2). The site x 6.0
# guess gives 13.17 um^2/cell; the masters below are all wider than that.
_SITE_W, _SITE_H = 0.56, 3.92
_MASTERS = {  # name: (width, count)
    "lib__dffrnq_1": (18.48, 64),
    "lib__nand2_1": (2.24, 120),
    "lib__xor2_1": (5.60, 89),
}












# ── 1+2: the area is READ and it sizes the CORE ─────────────────────────────







def test_no_per_pdk_average_cell_constant_is_left_in_the_flow():
    assert not hasattr(R, "_AUTO_DIE_AVG_SITES_PER_CELL")
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    assert "site_area * " not in src.split("def _resolve_auto_die_um", 1)[1][:9000]




# ── 3: the core holds one strap period, or the run says why not ────────────

_GF_STRAPS = [{"layer": "Metal4", "width": 1.6, "pitch": 153.6, "offset": 16.32},
              {"layer": "Metal5", "width": 1.6, "pitch": 153.18, "offset": 16.65}]


def test_the_strap_floor_matches_the_measured_pdngen_boundary():
    """CALIBRATED in image 0.3.83 (OpenROAD 26Q3-3002) with these two stripes:
    row extent 94.64 refused (Metal4 needs 94.72), 94.08 refused (Metal5 needs
    94.84), 99.68 x 98.0 built. This is the GROWTH floor -- a padded UPPER
    bound for a core the flow owns: it must sit above every refused core, and
    it may sit above a core that builds (102 > 100). It is never the refusal
    threshold for a pinned core; that is `pdn_strap_core_misfit`, pinned to
    the same eight measurements in the next test."""
    side, basis = PP.pdn_strap_min_core_span_um(_GF_STRAPS, nets=2,
                                                site_dims_um=(_SITE_W, _SITE_H))
    assert "94.84" in basis and "Metal5" in basis, basis
    for refused_core in (65, 80, 90, 94, 95, 96, 97):
        assert side > refused_core
    # snapped to whole rows/sites the floor core clears both needs
    assert math.floor(side / _SITE_H) * _SITE_H - _SITE_H >= 94.84
    assert math.floor(side / _SITE_W) * _SITE_W - _SITE_W >= 94.72
    assert side == 102


def test_no_strap_is_no_floor():
    assert PP.pdn_strap_min_core_span_um([], nets=2)[0] is None
    assert PP.pdn_strap_min_core_span_um([{"layer": "m", "width": 0}])[0] is None








_GF_DIRS = {"Metal4": "VERTICAL", "Metal5": "HORIZONTAL"}
#: core side -> the layers pdngen refused, MEASURED in image 0.3.83
_MEASURED = {65: {"Metal4", "Metal5"}, 80: {"Metal4", "Metal5"},
             90: {"Metal4", "Metal5"}, 94: {"Metal4", "Metal5"},
             95: {"Metal4", "Metal5"}, 96: {"Metal5"}, 97: {"Metal5"},
             100: set()}


def test_the_pinned_check_reproduces_every_measured_pdngen_outcome():
    """RED on main (no exact check). pdngen reported Metal4 first for 65-95
    and Metal5 for 96/97, and built at 100; the exact per-axis check must
    refuse exactly those layers and accept 100 x 100 (rows 99.68 x 98.0)."""
    for core, layers in _MEASURED.items():
        mis = PP.pdn_strap_core_misfit(_GF_STRAPS, core, core, nets=2,
                                       site_dims_um=(_SITE_W, _SITE_H),
                                       directions=_GF_DIRS)
        assert {m["layer"] for m in mis} == layers, (core, mis)
    ok = PP.pdn_strap_core_misfit(_GF_STRAPS, 100, 100, nets=2,
                                  site_dims_um=(_SITE_W, _SITE_H),
                                  directions=_GF_DIRS)
    assert ok == []
    growth, _ = PP.pdn_strap_min_core_span_um(_GF_STRAPS, nets=2,
                                              site_dims_um=(_SITE_W, _SITE_H))
    assert growth >= 100  # the padded growth floor is not the refusal bound


def test_the_pinned_check_judges_each_layer_on_its_own_axis():
    """A narrow tall core fits the HORIZONTAL straps and not the VERTICAL
    ones; the square floor would call both wrong."""
    mis = PP.pdn_strap_core_misfit(_GF_STRAPS, 60, 200, nets=2,
                                   site_dims_um=(_SITE_W, _SITE_H),
                                   directions=_GF_DIRS)
    assert [m["layer"] for m in mis] == ["Metal4"] and mis[0]["axis"] == "width"
    # direction unknown: judged on the larger extent, so it refuses LESS
    assert PP.pdn_strap_core_misfit(_GF_STRAPS, 60, 200, nets=2,
                                    site_dims_um=(_SITE_W, _SITE_H)) == []
