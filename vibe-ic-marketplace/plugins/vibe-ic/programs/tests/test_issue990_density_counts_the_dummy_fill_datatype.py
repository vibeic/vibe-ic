#!/usr/bin/env python3
"""vibe-ic#990 — the density producer could not see dummy fill.

THE DEFECT
==========
`_METAL_DENSITY_KLAYOUT_RECIPE` kept ONE (gds_layer, datatype) per metal layer:

    if metal_re.match(name) and "NET" in purpose.upper():
        metal_layers.setdefault(name.lower(), (gl, gd))

— the first routing/NET row of the LEF/DEF layermap. The PDK's own KLayout
density deck counts routing PLUS a separate dummy-fill datatype. #988 measured
both paths on the published run's own GDS against that run's own deck:

    layer     gate      PDK's own deck   delta
    li1       0.511625  0.511625         0.00e+00
    met1..5   …         …                0.00e+00

Agreement on all six layers — and #988 recorded why it proves nothing:

    measured 0 shapes on 36/28, 41/28, 34/28, 51/28 and 68..72/99

That layout carries no fill, so the two paths CANNOT disagree on this corpus,
and any fix here is unfalsifiable without a layout that has some. On a filled
run the producer under-counts by exactly the fill area — the area inserted to
SATISFY the rule — and in the direction that pushes a result toward the
disputed 0.35 floor.

WHAT MAKES THIS FALSIFIABLE
===========================
`tests/fixtures/density_fill/filled.gds` is a real GDSII stream carrying fill
shapes on a datatype the routing row does not name:

    die bbox            100 x 100 um   = 10000.0 um2
    routing (68/20)     200 + 200      =   400.0 um2   -> density 0.04
    dummy fill (68/36)  500 + 300      =   800.0 um2   -> delta    0.08
                                                   counted total   0.12

Every number a test below asserts is that arithmetic. The RECIPE THE RUNNER
EMITS is executed verbatim against that stream (`pya` supplied by the fixture's
narrow stand-in — no klayout, no container and no PDK tree exists on the host
this was written on; see the fixture module for what that costs).

WHAT IS NOT TOUCHED
===================
No density BOUND moves. #988 left step 34 ORACLE-DISPUTED deliberately and this
change does not adjudicate it: `layers_routing_only` publishes the pre-fix
number beside the new one so an earlier run stays reconcilable, and the gate's
windows, the registry and `metal_layer_density_check` are untouched.
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

import phase3_one_shot_runner as R  # noqa: E402
import gds_fixture as F  # noqa: E402

#: The map this runner SYNTHESIZES when a PDK ships no streamout layermap —
#: one row bundling every purpose onto the routing datatype. It is the shape
#: the measured run used, and the case where ONLY the deck can reveal fill.
_SYNTH_MAP = (
    "met1     LEFPIN,NET,SPNET,PIN,VIA,BLOCKAGE,FILL   "
    f"{F.METAL_GDS_LAYER} {F.ROUTING_DATATYPE}\n"
    f"met1     LEFOBS                                  "
    f"{F.METAL_GDS_LAYER} {F.ROUTING_DATATYPE}\n"
)


def _metal_re():
    return re.compile(R._METAL_DENSITY_LAYER_RE, re.IGNORECASE)


def _run_recipe(tmp_path, gds, layermap, deck):
    """Execute the recipe the runner ACTUALLY emits, and return its report.

    `pya` is injected into `sys.modules` around the call and removed after, so
    a later test in the same session cannot pick up a stub for the real thing.
    """
    out = tmp_path / "metal_density.json"
    pya = types.ModuleType("pya")
    pya.Layout, pya.Region = F.PyaStub.Layout, F.PyaStub.Region
    prev = sys.modules.get("pya")
    sys.modules["pya"] = pya
    try:
        g = {"gds": str(gds), "map": str(layermap), "deck": str(deck),
             "pdk": "fixture", "out": str(out)}
        exec(compile(R._metal_density_recipe(), "<density recipe>", "exec"), g)
    finally:
        if prev is None:
            sys.modules.pop("pya", None)
        else:
            sys.modules["pya"] = prev
    return json.loads(out.read_text())


# ── the fixture is what it says it is ───────────────────────────────────────

def test_the_committed_stream_still_matches_its_generator():
    """A binary fixture nobody can regenerate is a fixture that rots into a
    number people trust. The bytes on disk are the generator's output."""
    assert F.GDS.read_bytes() == F.build_gds(), (
        f"{F.GDS} no longer matches gds_fixture.build_gds(); re-run "
        f"`python3 {F.HERE}/gds_fixture.py`")


def test_the_fixture_really_carries_fill_shapes_on_their_own_datatype():
    """The load-bearing property. Without shapes on a SECOND datatype the two
    selections agree by construction and every test below is vacuous — which is
    exactly the state of the measured corpus (#988: 0 fill shapes)."""
    shapes, dbu, _cell = F.read_gds(F.GDS)
    routing = (F.METAL_GDS_LAYER, F.ROUTING_DATATYPE)
    fill = (F.METAL_GDS_LAYER, F.FILL_DATATYPE)
    assert routing in shapes and fill in shapes, sorted(shapes)
    assert routing != fill
    scale = dbu * dbu
    assert F.union_area_dbu(shapes[routing]) * scale == pytest.approx(
        F.ROUTING_AREA_UM2)
    assert F.union_area_dbu(shapes[fill]) * scale == pytest.approx(
        F.FILL_AREA_UM2)
    assert F.FILL_AREA_UM2 > 0


# ── the two paths, and their disagreement ───────────────────────────────────

def test_the_two_paths_disagree_by_exactly_the_fill_area(tmp_path):
    """The measurement the corpus could not make.

    `layers` counts the discovered datatype set; `layers_routing_only` is the
    pre-#990 selection. The difference is the inserted fill, to the last digit.
    """
    rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, F.DECK)
    assert rep["die_area_um2"] == pytest.approx(F.DIE_AREA_UM2)

    expect_routing = F.ROUTING_AREA_UM2 / F.DIE_AREA_UM2          # 0.04
    expect_counted = ((F.ROUTING_AREA_UM2 + F.FILL_AREA_UM2)
                      / F.DIE_AREA_UM2)                           # 0.12

    assert rep["layers_routing_only"]["met1"] == pytest.approx(expect_routing)
    assert rep["layers"]["met1"] == pytest.approx(expect_counted), (
        f"the producer still measures the routing datatype alone: "
        f"{rep['layers']} — it cannot see the {F.FILL_AREA_UM2} um2 of dummy "
        f"fill this stream carries, which is the area inserted to satisfy the "
        f"very rule this gate reports on (vibe-ic#990)")
    assert rep["layers_datatype_delta"]["met1"] == pytest.approx(
        F.FILL_AREA_UM2 / F.DIE_AREA_UM2)
    assert rep["layers"]["met1"] > rep["layers_routing_only"]["met1"], (
        "under-counting fill pushes the result toward the disputed floor; the "
        "fix must move it the other way or it is not the fix")


def test_the_fill_datatype_is_discovered_from_the_deck_not_from_the_layermap(
        tmp_path):
    """The case the measured run is actually in.

    That run's PDK ships no streamout layermap, so this runner SYNTHESISES one
    — a single row bundling every purpose onto the routing datatype. The
    layermap therefore cannot name the fill datatype at all, and the deck is
    the only source there is. A fix that read the map alone would pass the test
    above and change nothing on the run the issue is about.
    """
    smap = tmp_path / "synth.map"
    smap.write_text(_SYNTH_MAP, encoding="utf-8")
    rep = _run_recipe(tmp_path, F.GDS, smap, F.DECK)
    assert rep["datatype_discovery"]["specs_from_deck"] >= 1, (
        f"nothing was discovered from the PDK's own deck: "
        f"{rep['datatype_discovery']}")
    assert [F.METAL_GDS_LAYER, F.FILL_DATATYPE] in rep["layer_gds_specs"]["met1"]
    assert rep["layers"]["met1"] == pytest.approx(
        (F.ROUTING_AREA_UM2 + F.FILL_AREA_UM2) / F.DIE_AREA_UM2)


def test_no_datatype_number_is_written_into_the_producer():
    """DISCOVERED, not typed. A hardcoded datatype list is a promise no PDK
    will name one differently, and #988 established that the PDKs in this
    registry already disagree about density SCOPE — so assuming they agree
    about datatypes is unwarranted.

    Asserted against the fixture's own numbers rather than against "any digit":
    the producer legitimately contains other integers (rounding precision, the
    deck sweep bound), and a test that banned all of them would be satisfied by
    renaming rather than by discovering.
    """
    src = R._metal_density_recipe() + "\n" + inspect_source()
    for number in (F.FILL_DATATYPE, F.ROUTING_DATATYPE, F.METAL_GDS_LAYER):
        assert re.search(rf"\b{number}\b", src) is None, (
            f"the producer names GDS number {number} literally; the datatype "
            f"set must come from the PDK's own layermap and deck")


def inspect_source() -> str:
    import inspect
    return inspect.getsource(R.density_counted_specs)


def test_a_via_or_text_purpose_is_not_counted_as_metal_area():
    """#988 read the PDK deck as counting "all datatypes on the metal layer
    EXCEPT text and via". A discovery that swept the layer NUMBER blindly would
    over-count, which flatters the fix in the one direction nobody questions.

    Both fixture files carry a via and a text binding on the metal layer's own
    GDS number for exactly this reason.
    """
    counted, _routing, _prov = R.density_counted_specs(
        F.LAYERMAP.read_text(), [F.DECK.read_text()], _metal_re())
    specs = set(counted["met1"])
    assert (F.METAL_GDS_LAYER, F.ROUTING_DATATYPE) in specs
    assert (F.METAL_GDS_LAYER, F.FILL_DATATYPE) in specs
    assert (F.METAL_GDS_LAYER, 44) not in specs, (
        f"a via binding was counted as metal area: {sorted(specs)}")
    assert (F.METAL_GDS_LAYER, 5) not in specs, (
        f"a text binding was counted as metal area: {sorted(specs)}")


def test_a_bundled_purpose_row_is_kept_not_dropped():
    """The synthesized map writes VIA on the SAME row as NET and FILL. An
    exclusion that matched the row as a substring would have dropped the whole
    layer and shipped an empty measurement — the #453 defect, re-created by the
    fix for this one. Measured on this runner's own synthesized output."""
    counted, routing, _prov = R.density_counted_specs(
        _SYNTH_MAP, [], _metal_re())
    assert routing["met1"] == (F.METAL_GDS_LAYER, F.ROUTING_DATATYPE)
    assert counted["met1"] == [(F.METAL_GDS_LAYER, F.ROUTING_DATATYPE)], counted


# ── it must not move anything on the corpus that HAS no fill ────────────────

def test_a_layout_with_no_fill_reports_a_zero_delta_on_every_layer(tmp_path):
    """The regression direction, and the reason the measured run is safe.

    #988's six layers agreed to 0.00e+00 because that GDS has zero fill. This
    change must keep that true — a fix that moved a number on a fill-free
    layout would be adjudicating step 34's disputed floor by accident, which
    #988 explicitly declined to do.
    """
    unfilled = tmp_path / "unfilled.gds"
    filled_rects = F.FILL_RECTS_UM
    try:
        F.FILL_RECTS_UM = ()
        unfilled.write_bytes(F.build_gds())
    finally:
        F.FILL_RECTS_UM = filled_rects

    rep = _run_recipe(tmp_path, unfilled, F.LAYERMAP, F.DECK)
    assert rep["layers"] == rep["layers_routing_only"], (
        f"a layout with NO fill measured differently under the two selections: "
        f"{rep['layers']} vs {rep['layers_routing_only']}")
    assert set(rep["layers_datatype_delta"].values()) == {0.0}, (
        rep["layers_datatype_delta"])
    assert rep["layers"]["met1"] == pytest.approx(
        F.ROUTING_AREA_UM2 / F.DIE_AREA_UM2)


def test_an_unreadable_deck_degrades_loudly_and_still_measures(tmp_path):
    """A PDK with no deck must not silently become a routing-only measurement
    that reads like a full one. The layermap half still answers, the deck's
    absence is a published count, and nothing pretends otherwise."""
    rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, tmp_path / "no-such-deck")
    prov = rep["datatype_discovery"]
    assert prov["specs_from_deck"] == 0
    assert prov["deck_files_unreadable"], prov
    assert rep["layers"], "the measurement went empty when the deck went away"


def test_the_report_still_carries_what_its_consumers_read(tmp_path):
    """`metal_layer_density_check` judges `layers`; other readers key on
    `layer_gds_map` and `die_area_um2`. New keys are additive; none of the old
    ones may leave, or this fix breaks a gate while fixing a producer."""
    rep = _run_recipe(tmp_path, F.GDS, F.LAYERMAP, F.DECK)
    for key in ("tool", "measurement", "pdk", "gds", "die_area_um2", "layers",
                "layers_absent_in_gds", "layer_gds_map", "disclosure"):
        assert key in rep, f"consumer key {key!r} no longer emitted"
    assert rep["layer_gds_map"]["met1"] == [F.METAL_GDS_LAYER,
                                           F.ROUTING_DATATYPE]
    import metal_layer_density_check as MLD
    assert MLD._METAL_RE.match("met1"), "fixture layer is not a consumer layer"


def test_the_discovery_is_injected_by_source_not_restated():
    """One authority. A hand-copied duplicate passes on the day it is written
    and rots afterwards — the same argument `_METAL_DENSITY_LAYER_RE` already
    makes about the layer-name regex, applied to the datatype selector."""
    import inspect
    recipe = R._metal_density_recipe()
    assert inspect.getsource(R.density_counted_specs) in recipe, (
        "the recipe carries a SECOND copy of the datatype discovery; the "
        "function these tests exercise is then not the one that runs")
