#!/usr/bin/env python3
"""LVS ROOT FIX (extraction side) — power-aware Magic DEF-extraction TCL emitter.

Proves the emitter turns the plain Magic DEF-extraction recipe (which COLLAPSES
the sky130 power nets onto ~2 mis-named nodes — the ground rail into the
substrate node `VSUBS`, the power rail into a leaf-port name like `_567_/VPB`)
into a POWER-AWARE recipe that:

  * names the substrate/ground node the true ground rail (`set SUB VGND`), and
  * seeds the power-rail name onto its DEF stripe geometry
    (`box <..>um ...; label VPWR c <layer>`),

so the extracted rails keep their true names and netgen can verify the power
network. The transform must be PDK-GATED (unchanged for a non-sky130/gf180 PDK),
DEF-DERIVED (chip-AGNOSTIC — rails from the PDK model, geometry from the DEF),
and STRICT FALL-THROUGH (unchanged recipe when the DEF exposes no usable power
SPECIALNET geometry). The genuine-match behaviour itself is validated LIVE
against real Magic + netgen on spm in the run report; here we lock the
deterministic emission.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lvs_power_aware_extract_tcl as E  # noqa: E402


# The base recipe the runner passes in (kept byte-identical to
# phase3_one_shot_runner._MAGIC_EXT2SPICE_TCL by contract).
_BASE_TCL = E._DEFAULT_BASE_TCL


# A minimal but realistic routed sky130 DEF: 2 SPECIALNETS (VGND USE GROUND with
# VNB taps; VPWR USE POWER with VPB taps), each with a met5 stripe, plus a
# COMPONENTS/PINS shell. Coordinates in nm (UNITS 1000/micron).
_SKY_DEF = """\
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200000 200000 ) ;
COMPONENTS 2 ;
    - _1_ sky130_fd_sc_hd__inv_1 + PLACED ( 1000 1000 ) N ;
    - _2_ sky130_fd_sc_hd__nand2_1 + PLACED ( 2000 1000 ) N ;
END COMPONENTS
SPECIALNETS 2 ;
    - VGND ( _1_ VNB ) ( _2_ VNB ) ( _1_ VGND ) ( _2_ VGND ) + USE GROUND
      + ROUTED met5 1600 + SHAPE STRIPE ( 17320 178880 ) ( 178920 178880 )
      NEW met5 1600 + SHAPE STRIPE ( 17320 138880 ) ( 178920 138880 ) ;
    - VPWR ( _1_ VPB ) ( _2_ VPB ) ( _1_ VPWR ) ( _2_ VPWR ) + USE POWER
      + ROUTED met5 1600 + SHAPE STRIPE ( 37320 158880 ) ( 158920 158880 )
      NEW met5 1600 + SHAPE STRIPE ( 37320 118880 ) ( 158920 118880 ) ;
END SPECIALNETS
END DESIGN
"""

# A gf180 DEF: rails named VDD/VSS (the gf180 power model), one met5 stripe each.
_GF_DEF = """\
DESIGN top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 100000 ) ;
SPECIALNETS 2 ;
    - VSS ( _1_ VPW ) + USE GROUND
      + ROUTED Metal5 800 + SHAPE STRIPE ( 10000 50000 ) ( 90000 50000 ) ;
    - VDD ( _1_ VNW ) + USE POWER
      + ROUTED Metal5 800 + SHAPE STRIPE ( 10000 60000 ) ( 90000 60000 ) ;
END SPECIALNETS
END DESIGN
"""


def _emit(def_text=_SKY_DEF, pdk="sky130A", base=None, top="chip_top"):
    return E.build_power_aware_extraction_tcl(
        base if base is not None else _BASE_TCL, pdk, def_text, top=top)


# ── core transform (sky130) ────────────────────────────────────────────────
def test_sky130_power_aware_applied():
    tcl, stats = _emit()
    assert stats["power_aware"] is True
    assert stats["pdk"] == "sky130A"
    assert stats["ground_rail"] == "VGND"
    assert stats["power_rail"] == "VPWR"
    assert stats["substrate_override"] == "VGND"
    assert stats["skipped_reason"] == ""


def test_sky130_substrate_override_present():
    # Lever 1: name the collapsed substrate/ground node the true ground rail.
    tcl, _ = _emit()
    assert re.search(r"^\s*set SUB VGND\s*$", tcl, re.M)


def test_sky130_power_label_directives_present():
    # Lever 2: paint the power-rail name onto its DEF stripe geometry.
    tcl, stats = _emit()
    # one box + one label per seeded point (default cap 3 → here 2 stripes).
    labels = re.findall(r"^\s*label VPWR c met5\s*$", tcl, re.M)
    boxes = re.findall(r"^\s*box [\d.]+um [\d.]+um [\d.]+um [\d.]+um\s*$", tcl, re.M)
    assert len(labels) >= 1
    assert len(labels) == len(boxes)
    assert len(labels) == len(stats["power_label_points"])
    # the DEF-derived layer is carried through (chip-AGNOSTIC — from the DEF).
    for pt in stats["power_label_points"]:
        assert pt["layer"] == "met5"
        assert len(pt["box_um"]) == 4


def test_sky130_label_box_lands_inside_the_stripe():
    # The seeded box must sit INSIDE the VPWR met5 stripe (37.32..158.92 um in x,
    # 158.88 um centre-line, width 1.6 um) so the label attaches to metal.
    _, stats = _emit()
    x1, y1, x2, y2 = stats["power_label_points"][0]["box_um"]
    assert 37.32 <= x1 < x2 <= 158.92          # within stripe length
    assert 158.08 <= y1 < y2 <= 159.68          # within stripe width (centre ±0.8)


def test_directives_injected_before_extract():
    # The power-aware block must precede the first `extract` command.
    tcl, _ = _emit()
    i_dir = tcl.index("PA_EXTRACT_APPLIED")
    i_ext = tcl.index("extract no all")
    assert i_dir < i_ext
    # snap must precede the box/label commands.
    assert tcl.index("snap internal") < tcl.index("label VPWR")


def test_base_recipe_body_preserved():
    # §4.05: every original recipe line survives (additive-only injection).
    tcl, _ = _emit()
    for line in ("crashbackups stop", "def read $env(DEF)", "port makeall",
                 "extract no all", "extract do local", "extract all",
                 "ext2spice lvs", "ext2spice -o $env(SPICE_OUT)",
                 "quit -noprompt"):
        assert line in tcl


# ── gf180 (second PDK) ─────────────────────────────────────────────────────
def test_gf180_uses_its_own_rails():
    tcl, stats = _emit(def_text=_GF_DEF, pdk="gf180mcuC", top="top")
    assert stats["power_aware"] is True
    assert stats["ground_rail"] == "VSS"
    assert stats["power_rail"] == "VDD"
    assert re.search(r"^\s*set SUB VSS\s*$", tcl, re.M)
    assert re.search(r"^\s*label VDD c Metal5\s*$", tcl, re.M)


# ── PDK gating + strict fall-through (§4.05 no-regression) ──────────────────
def test_unknown_pdk_returns_unchanged_recipe():
    tcl, stats = _emit(pdk="tsmc65")
    assert stats["power_aware"] is False
    assert "unrecognised PDK" in stats["skipped_reason"]
    assert tcl == _BASE_TCL                      # byte-identical fall-through


def test_no_specialnets_returns_unchanged_recipe():
    def_no_sn = "DESIGN d ;\nUNITS DISTANCE MICRONS 1000 ;\nEND DESIGN\n"
    tcl, stats = _emit(def_text=def_no_sn)
    assert stats["power_aware"] is False
    assert "SPECIALNETS" in stats["skipped_reason"]
    assert tcl == _BASE_TCL


def test_missing_power_rail_returns_unchanged_recipe():
    # A DEF with only a ground rail (no power SPECIALNET) must fall through.
    def_only_gnd = (
        "DESIGN d ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "SPECIALNETS 1 ;\n"
        "    - VGND ( _1_ VNB ) + USE GROUND\n"
        "      + ROUTED met5 1600 + SHAPE STRIPE ( 100 100 ) ( 900 100 ) ;\n"
        "END SPECIALNETS\nEND DESIGN\n")
    tcl, stats = _emit(def_text=def_only_gnd)
    assert stats["power_aware"] is False
    assert tcl == _BASE_TCL


def test_power_rail_without_stripe_geometry_falls_through():
    # Power SPECIALNET present but with no fully-numeric stripe (only vias) →
    # no usable label point → unchanged recipe (no half-applied state).
    def_novia = (
        "DESIGN d ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "SPECIALNETS 2 ;\n"
        "    - VGND ( _1_ VNB ) + USE GROUND\n"
        "      + ROUTED met5 1600 + SHAPE STRIPE ( 100 100 ) ( 900 100 ) ;\n"
        "    - VPWR ( _1_ VPB ) + USE POWER\n"
        "      + ROUTED met4 met5 ( 500 500 ) ;\n"   # via only, no 2 coords
        "END SPECIALNETS\nEND DESIGN\n")
    tcl, stats = _emit(def_text=def_novia)
    assert stats["power_aware"] is False
    assert tcl == _BASE_TCL


def test_rail_matched_by_use_when_name_differs():
    # The rail net may be named differently (e.g. vccd1/vssd1) — match on the
    # `+ USE POWER|GROUND` marker so the fix still applies. Still labels with the
    # PDK rail NAME (VPWR/VGND) so it aligns with the power-aware netlist globals.
    def_named = _SKY_DEF.replace("- VGND (", "- vssd1 (").replace(
        "- VPWR (", "- vccd1 (")
    tcl, stats = _emit(def_text=def_named)
    assert stats["power_aware"] is True
    assert re.search(r"^\s*set SUB VGND\s*$", tcl, re.M)
    assert re.search(r"^\s*label VPWR c met5\s*$", tcl, re.M)


def test_units_scale_respected():
    # A DEF with a different UNITS scale must convert coordinates correctly.
    def_2000 = _SKY_DEF.replace("MICRONS 1000", "MICRONS 2000")
    _, stats = _emit(def_text=def_2000)
    # VPWR stripe midpoint x = (37320+158920)/2 = 98120 dbu; at 2000/um → 49.06 um
    x1, _, x2, _ = stats["power_label_points"][0]["box_um"]
    mid = (x1 + x2) / 2
    assert abs(mid - 49.06) < 0.01


def test_vertical_stripe_box_orientation():
    # A vertical power stripe must yield a box narrow in x, tall in y.
    def_vert = (
        "DESIGN d ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "SPECIALNETS 2 ;\n"
        "    - VGND ( _1_ VNB ) + USE GROUND\n"
        "      + ROUTED met5 1600 + SHAPE STRIPE ( 100 100 ) ( 100 9000 ) ;\n"
        "    - VPWR ( _1_ VPB ) + USE POWER\n"
        "      + ROUTED met4 1600 + SHAPE STRIPE ( 5000 1000 ) ( 5000 9000 ) ;\n"
        "END SPECIALNETS\nEND DESIGN\n")
    _, stats = _emit(def_text=def_vert)
    x1, y1, x2, y2 = stats["power_label_points"][0]["box_um"]
    assert (x2 - x1) < (y2 - y1)                 # tall, narrow → vertical wire
    assert stats["power_label_points"][0]["layer"] == "met4"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
