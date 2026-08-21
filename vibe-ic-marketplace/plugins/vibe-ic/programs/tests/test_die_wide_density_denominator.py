#!/usr/bin/env python3
"""The per-layer density measurement, over the DIE and counting the FILL.

TWO DEFECTS, MEASURED TOGETHER, ON THE SAME REPORT
===================================================
`reports/phase3/metal_density.json` for a landed gf180mcuD 0.5x0.5-slot run
(spm, 2026-08) said this about the flow's own streamed GDS:

    "die_area_um2": 1732693.41
    "metal2": 0.003636
    "layers_datatype_delta": {"metal2": 0.0}
    "layer_gds_specs": {"metal1": [[34,0],[34,10]], ...}
    "datatype_discovery": {"specs_from_layermap": 10, "specs_from_deck": 0,
                           "deck_files_read": 40}

Both statements were false about the die, and each for its own reason.

1. THE DENOMINATOR WAS THE CORE. `die_area_um2` was the bounding box of the
   streamed geometry, which on a slot submission is the routed CORE — measured,
   1052 x 1647 um, 35.4 % of the 1936 x 2531 um die. The PDK's own density deck
   divides by `extent.sized(0.0).area`, the whole die. A number arithmetically
   correct over the core is simply not an answer to a rule written over the die.

2. THE FILL WAS NOT COUNTED AT ALL. Measured on that same GDS, per (layer,
   datatype): metal2 routing 6299.9 um2, metal2 DUMMY 744035.9 um2. The report
   published 0.003636 — the routing alone — and `layers_datatype_delta: 0.0`,
   i.e. "this layout has no dummy fill", about a layout the same flow had just
   filled. #990 taught the discovery to read the PDK's deck, but only in the
   `NAME = input(L, D)` binding form. gf180mcuD's deck registers its layers
   through a helper instead — `extract_single_layer_from_design.call(
   :metal1_dummy, 34, 4)` — so 40 deck files yielded `specs_from_deck: 0`.

The two errors pointed the same way and hid each other: a numerator ~12x too
small over a denominator ~2.8x too small still looks like a plausible density,
and both lived in the same file, so no consumer could reconcile them. The
external checker was the only thing that ever contradicted it: the operator's
precheck failed the same GDS on M2.4 at 18.2 % over the die.

Every test below breaks one of those and requires the failure.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_FIXTURE_DIR = _PROGRAMS / "tests" / "fixtures" / "density_fill"
for _p in (str(_PROGRAMS), str(_FIXTURE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase3_one_shot_runner as R                            # noqa: E402
import gds_fixture as F                                       # noqa: E402


def _metal_re():
    return re.compile(R._METAL_DENSITY_LAYER_RE, re.IGNORECASE)


def _run_recipe(tmp_path, gds, layermap, deck, die=None):
    """Execute the recipe the runner ACTUALLY emits, and return its report."""
    out = tmp_path / "metal_density.json"
    pya = types.ModuleType("pya")
    pya.Layout, pya.Region = F.PyaStub.Layout, F.PyaStub.Region
    prev = sys.modules.get("pya")
    sys.modules["pya"] = pya
    try:
        g = {"gds": str(gds), "map": str(layermap), "deck": str(deck),
             "pdk": "fixture", "out": str(out)}
        if die is not None:
            g["die"] = die
        exec(compile(R._metal_density_recipe(), "<density recipe>", "exec"), g)
    finally:
        if prev is None:
            sys.modules.pop("pya", None)
        else:
            sys.modules["pya"] = prev
    return json.loads(out.read_text())


# ── 1. the denominator ──────────────────────────────────────────────────────

def test_with_no_declared_die_the_bbox_is_used_and_the_report_says_so(tmp_path):
    """The historical behaviour, kept intact for every design that targets no
    slot — but no longer silent about which rectangle it measured."""
    rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, F.DECK)
    assert rep["die_area_um2"] == pytest.approx(F.DIE_AREA_UM2)
    assert rep["bbox_area_um2"] == pytest.approx(F.DIE_AREA_UM2)
    assert rep["bbox_area_over_die_area"] == pytest.approx(1.0)
    assert "bounding box" in rep["die_area_source"]


def test_a_declared_die_larger_than_the_layout_is_the_denominator(tmp_path):
    """THE DEFECT. The fixture's geometry occupies a 100 x 100 um bounding box.
    Declare a die twice that on each side — the shape of a routed core sitting
    inside a shuttle slot — and every coverage number must fall by 4x, because
    that is what the foundry rule asks. Before this change the report divided by
    the bounding box and called the answer `die_area_um2`."""
    side = F.DIE_UM * 2
    rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, F.DECK,
                      die=f"0,0,{side},{side}")
    assert rep["die_area_um2"] == pytest.approx(F.DIE_AREA_UM2 * 4)
    assert rep["bbox_area_um2"] == pytest.approx(F.DIE_AREA_UM2)
    assert rep["bbox_area_over_die_area"] == pytest.approx(0.25)
    assert "declared slot DIE_AREA" in rep["die_area_source"]

    bbox_rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, F.DECK)
    for layer, over_die in rep["layers"].items():
        assert over_die == pytest.approx(bbox_rep["layers"][layer] / 4,
                                         abs=1e-6), layer
        assert over_die < bbox_rep["layers"][layer], (
            "a die-wide denominator must LOWER a sparse die's coverage; if it "
            "does not, the wrong rectangle is still being divided by")


def test_an_unparseable_die_falls_back_loudly_rather_than_measuring_nothing(tmp_path):
    rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, F.DECK, die="not,a,rect")
    assert rep["die_area_um2"] == pytest.approx(F.DIE_AREA_UM2)
    assert "could not be parsed" in rep["die_area_source"]
    assert rep["layers"], "a bad die argument must not silence the measurement"


def test_the_disclosure_names_the_rectangle_it_divided_by(tmp_path):
    for die, expect in ((None, "bounding box"),
                        (f"0,0,{F.DIE_UM * 2},{F.DIE_UM * 2}",
                         "declared slot DIE_AREA")):
        rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, F.DECK, die=die)
        assert expect in rep["disclosure"], rep["disclosure"]


# ── 2. the deck binding form the discovery could not read ───────────────────

_HELPER_DECK = f"""\
# A deck that registers its layers through a helper, as a deck split across
# many files does — the form gf180mcuD uses. NO `NAME = input(L, D)` anywhere.
module GF180DRC
  module GenericLayers
    def self.compute(ctx)
      extract_single_layer_from_design.call(:met1_drawn, {F.METAL_GDS_LAYER}, {F.ROUTING_DATATYPE})
      extract_single_layer_from_design.call(:met1_dummy, {F.METAL_GDS_LAYER}, {F.FILL_DATATYPE})
      extract_single_layer_from_design.call(:met1_slot,  {F.METAL_GDS_LAYER}, 3)
      extract_single_layer_from_design.call(:met1_blk,   {F.METAL_GDS_LAYER}, 7)
      extract_single_layer_from_design.call(:met1_via,   {F.METAL_GDS_LAYER}, 44)
      extract_single_layer_from_design.call(:unrelated,  9999, 1)
    end
  end
end
"""

_ROUTING_ONLY_MAP = (
    f"met1     LEFPIN,NET,SPNET,PIN       {F.METAL_GDS_LAYER} "
    f"{F.ROUTING_DATATYPE}\n")


def test_the_helper_binding_form_reveals_the_dummy_purpose(tmp_path):
    """THE DEFECT, isolated: a layermap that names only the routing row, and a
    deck written in the helper form. Before this change `specs_from_deck` was 0
    and the fill datatype was invisible."""
    counted, routing, prov = R.density_counted_specs(
        _ROUTING_ONLY_MAP, [_HELPER_DECK], _metal_re())
    assert prov["specs_from_deck"] > 0, prov
    assert (F.METAL_GDS_LAYER, F.FILL_DATATYPE) in counted["met1"], counted
    assert routing["met1"] == (F.METAL_GDS_LAYER, F.ROUTING_DATATYPE)


def test_the_helper_form_does_not_count_purposes_that_carry_no_metal(tmp_path):
    """Over-counting density is the dangerous direction — it is what lets a
    sparse die read as dense. A slot is a HOLE in the metal, a blk is a routing
    blockage and a via is not metal area, so none of the three may be added."""
    counted, _routing, _prov = R.density_counted_specs(
        _ROUTING_ONLY_MAP, [_HELPER_DECK], _metal_re())
    got = set(counted["met1"])
    assert (F.METAL_GDS_LAYER, 3) not in got, "slot counted as metal area"
    assert (F.METAL_GDS_LAYER, 7) not in got, "blockage counted as metal area"
    assert (F.METAL_GDS_LAYER, 44) not in got, "via counted as metal area"


def test_a_helper_call_about_another_layer_contributes_nothing(tmp_path):
    """The safety is not in the pattern — it is in the gate after it: a spec is
    kept only when its GDS LAYER NUMBER is one the layermap already established
    as a metal layer."""
    counted, _routing, _prov = R.density_counted_specs(
        _ROUTING_ONLY_MAP, [_HELPER_DECK], _metal_re())
    assert all(gl == F.METAL_GDS_LAYER
               for specs in counted.values() for gl, _ in specs), counted


def test_the_direct_binding_form_still_works(tmp_path):
    """#990's own corpus must not regress: the fixture deck is written in the
    direct form and its fill datatype must still be discovered."""
    counted, _routing, prov = R.density_counted_specs(
        _ROUTING_ONLY_MAP, [F.DECK.read_text()], _metal_re())
    assert (F.METAL_GDS_LAYER, F.FILL_DATATYPE) in counted["met1"]
    assert prov["specs_from_deck"] > 0


# ── 3. the wiring: the declared die must reach the recipe ───────────────────

def test_the_runner_passes_the_declared_die_and_omits_it_otherwise():
    src = _PROGRAMS.joinpath("phase3_one_shot_runner.py").read_text()
    assert "_dens_slot = _slot_geometry(project)" in src
    assert "-rd die={_dens_slot['die_rect'][0]}" in src
    # OMITTED, not passed empty: `-rd die=` with nothing after it is a
    # malformed KLayout argument, and the recipe already treats an absent `die`
    # global as "measure the bounding box".
    assert 'if _dens_slot else ""' in src


def test_no_datatype_number_is_written_into_the_producer():
    """Re-asserted here because this change ADDS a second discovery path, and a
    second path is a second chance to hard-code the answer it was meant to
    discover. Same bar as #990's."""
    import inspect
    src = R._metal_density_recipe() + "\n" + inspect.getsource(
        R.density_counted_specs)
    for number in (F.FILL_DATATYPE, F.ROUTING_DATATYPE, F.METAL_GDS_LAYER):
        assert re.search(rf"\b{number}\b", src) is None, number
