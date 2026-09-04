#!/usr/bin/env python3
"""A router residual whose marker is smaller than the layer's own MINWIDTH
blocked the whole run, and nothing ever asked whether it described geometry.

MEASURED twice on this repo's own trees:

  * spm x gf180mcuD, 2026-08-30 -- eleven `NS Metal` markers on Metal1, each
    0.0400 x 0.0550 um against that layer's `MINWIDTH 0.230`, while the
    connected Metal1 polygon present there is 1.4533 um^2 = 10.1x the
    `AREA 0.1444` rule.
  * subservient x gf180mcuD, 2026-09-02 -- `NS Metal` on Metal2, net
    `__uuf__._1246_`, bbox (353.7795,159.7395)-(353.7805,159.7405): a marker
    0.001 x 0.001 um against Metal2's `MINWIDTH 0.280`.

`pnr` returned FAIL on the COUNT, so no GDS was streamed, so the sign-off DRC
deck -- the arbiter this flow declares for drawn geometry, and the only reader
that evaluates MERGED polygons -- was never given an input. Four sessions
recorded `drc = SKIP: GDS missing`, i.e. NOT MEASURED presented as unreached.

These tests pin the classifier and, critically, its NEGATIVE side: a marker
that CAN be a drawn object, and a rule that is a distance between two
independently routed shapes, must both keep the FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

# The router's own report grammar, verbatim from the two runs above.
_RPT_TINY = (
    "  violation type: NS Metal\n"
    "\tsrcs: net:__uuf__._1246_\n"
    "\tbbox = (353.7795, 159.7395) - (353.7805, 159.7405) on Layer Metal2\n"
)
_RPT_REAL = (
    "  violation type: NS Metal\n"
    "\tsrcs: net:__uuf__._0114_\n"
    "\tbbox = (397.7500, 177.3900) - (398.2500, 177.7900) on Layer Metal2\n"
)
_RPT_SPACING = (
    "  violation type: Metal Spacing\n"
    "\tsrcs: net:a\n"
    "\tsrcs: net:b\n"
    "\tbbox = (10.0000, 10.0000) - (10.0010, 10.0010) on Layer Metal2\n"
)
# One routing layer of a tech LEF, in the shipped grammar.
_TLEF = (
    "LAYER Metal2\n"
    "    TYPE ROUTING ;\n"
    "    DIRECTION VERTICAL ;\n"
    "    PITCH 0.56 ;\n"
    "    MINWIDTH 0.280 ;\n"
    "    WIDTH 0.280 ;\n"
    "    SPACING 0.280 ;\n"
    "    AREA 0.1444 ;\n"
    "END Metal2\n"
)
_MW = {"Metal2": 0.280}


def _records(tmp_path: Path, text: str):
    (tmp_path / R.ROUTER_DRC_REPORT_NAME).write_text(text)
    return R._router_drc_report_records(tmp_path)


def test_the_report_record_carries_the_marker_extent(tmp_path):
    """Without the bbox there is nothing to compare against MINWIDTH -- the
    parser used to drop the only per-violation geometry the router publishes."""
    rec = _records(tmp_path, _RPT_TINY)[0]
    assert rec["bbox_um"] == [353.7795, 159.7395, 353.7805, 159.7405]
    assert rec["marker_w_um"] == 0.001
    assert rec["marker_h_um"] == 0.001
    assert rec["layer"] == "Metal2"
    assert rec["nets"] == ["__uuf__._1246_"]


def test_a_marker_below_minwidth_in_both_dimensions_is_not_an_object(tmp_path):
    rec = _records(tmp_path, _RPT_TINY)[0]
    assert R._marker_cannot_be_a_drawn_object(rec, _MW) is True


def test_a_marker_that_could_be_drawn_keeps_the_finding(tmp_path):
    """NEGATIVE CONTROL. 0.5 x 0.4 um on a MINWIDTH 0.280 layer is a shape that
    can legally exist, so the residual is the design's, not the checker's."""
    rec = _records(tmp_path, _RPT_REAL)[0]
    assert R._marker_cannot_be_a_drawn_object(rec, _MW) is False
    assert R._route_residual_tool_artefact([rec], _MW) is None


def test_an_unknown_layer_is_undecidable_not_clean(tmp_path):
    """A missing MINWIDTH must return None, and None must not license a
    waiver -- otherwise a PDK whose tech LEF this run cannot read would waive
    every residual it has."""
    rec = _records(tmp_path, _RPT_TINY)[0]
    assert R._marker_cannot_be_a_drawn_object(rec, {}) is None
    assert R._route_residual_tool_artefact([rec], {}) is None


def test_a_distance_rule_is_never_waived_however_small_its_marker(tmp_path):
    """NEGATIVE CONTROL. `Metal Spacing` is a distance between two
    independently routed shapes: its marker is the overlap region and may
    legitimately be far below MINWIDTH. Only SINGLE-SHAPE rules qualify."""
    rec = _records(tmp_path, _RPT_SPACING)[0]
    assert R._marker_cannot_be_a_drawn_object(rec, _MW) is True
    assert R._route_residual_tool_artefact([rec], _MW) is None


def test_one_real_marker_among_many_tiny_ones_blocks_the_whole_waiver(tmp_path):
    recs = _records(tmp_path, _RPT_TINY + _RPT_TINY + _RPT_REAL)
    assert len(recs) == 3
    assert R._route_residual_tool_artefact(recs, _MW) is None
    assert R._route_residual_tool_artefact(recs[:2], _MW) is not None


def test_the_waiver_evidence_names_the_rule_it_was_measured_against(tmp_path):
    ev = R._route_residual_tool_artefact(_records(tmp_path, _RPT_TINY), _MW)
    assert ev is not None and len(ev) == 1
    assert ev[0]["layer_min_width_um"] == 0.280
    assert ev[0]["marker_w_um"] == 0.001
    assert ev[0]["nets"] == ["__uuf__._1246_"]


def test_min_widths_come_from_the_tech_lef_staged_beside_the_route(tmp_path):
    """`pdk.tech_lef` is a CONTAINER path; on a host-side read the staged copy
    the pnr step writes next to its own outputs is what exists."""
    (tmp_path / "active_via_legalized.tlef").write_text(_TLEF)

    class _P:
        tech_lef = "/foss/pdks/does-not-exist-on-this-host.tlef"
        tech_lef_source = None

    assert R._tech_lef_min_widths(_P(), tmp_path) == {"Metal2": 0.280}


def test_no_tech_lef_is_an_empty_map_not_a_guess(tmp_path):
    class _P:
        tech_lef = "/nope.tlef"
        tech_lef_source = None

    assert R._tech_lef_min_widths(_P(), tmp_path) == {}
