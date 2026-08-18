#!/usr/bin/env python3
"""Tests for signoff_cell_aware_feol_attribution.py (cell-aware FEOL over-fire
attributor -- DISCLOSURE ONLY).

Establishes the two invariants the attributor MUST hold, on a SYNTHETIC layout
(no chip data, no svrfdrc needed):

  POSITIVE -- a sub-threshold implant space between two abutted QUALIFIED cell
              masters is attributed as a qualified-cell-interior CANDIDATE
              artifact.
  NEGATIVE -- a real implant space between two STRAY top-level polygons OUTSIDE
              every cell footprint is NEVER attributed as an artifact (stays
              top-level / real).

Plus: the attribution is disclosure-only (never a verdict) and the
`flat_marker_can_exempt` flag is False whenever a routed metal overlaps the
over-fire (a flat marker would carve that metal).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import signoff_cell_aware_feol_attribution as A  # noqa: E402


# ----------------------- pure-python parser tests -------------------------

def test_parse_layerlist():
    assert A.parse_layerlist("4/0,5/0") == [(4, 0), (5, 0)]
    assert A.parse_layerlist("9/0, 11/0 , 13/2") == [(9, 0), (11, 0), (13, 2)]
    assert A.parse_layerlist("7") == [(7, 0)]        # datatype defaults to 0
    assert A.parse_layerlist("") == []
    assert A.parse_layerlist("  ") == []


def test_parse_def_components(tmp_path):
    d = tmp_path / "p.def"
    d.write_text(
        "COMPONENTS 3 ;\n"
        "- inst0 CELLA + PLACED ( 0 0 ) N ;\n"
        "- inst1 CELLB + PLACED ( 600 0 ) FS ;\n"
        "- inst2 CELLA + FIXED ( 1200 0 ) S ;\n"
        "END COMPONENTS\n")
    comps = A.parse_def_components(str(d))
    assert comps == [
        ("inst0", "CELLA", 0, 0, "N"),
        ("inst1", "CELLB", 600, 0, "FS"),
        ("inst2", "CELLA", 1200, 0, "S")]


def test_parse_def_components_with_source_clause(tmp_path):
    """Regression: router-inserted fillers/decaps carry `+ SOURCE DIST` (and a
    cell may carry `+ EEQMASTER`) BEFORE the placement — the parser must not drop
    them (a dropped placed master shrinks the qualified footprint and mis-labels a
    real cell-interior candidate as top-level)."""
    d = tmp_path / "p.def"
    d.write_text(
        "COMPONENTS 4 ;\n"
        "- f0 FILL1 + SOURCE DIST + PLACED ( 10 0 ) N ;\n"
        "- d0 DECAP4 + SOURCE DIST + FIXED ( 20 0 ) FS ;\n"
        "- u0 NAND2 + EEQMASTER NAND2X + SOURCE NETLIST + PLACED ( 30 0 ) S ;\n"
        "- u1 INV + PLACED ( 40 0 ) N ;\n"
        "END COMPONENTS\n")
    comps = A.parse_def_components(str(d))
    assert comps == [
        ("f0", "FILL1", 10, 0, "N"),
        ("d0", "DECAP4", 20, 0, "FS"),
        ("u0", "NAND2", 30, 0, "S"),
        ("u1", "INV", 40, 0, "N")]


def test_load_qualified_inline_and_file(tmp_path):
    assert A._load_qualified("CELLA,CELLB CELLC") == {"CELLA", "CELLB", "CELLC"}
    f = tmp_path / "q.txt"
    f.write_text("CELLA CELLB\nCELLC\n")
    assert A._load_qualified("@" + str(f)) == {"CELLA", "CELLB", "CELLC"}


# --------------------- synthetic geometric attribution --------------------

def _build_synth(tmp_path):
    """Build a synthetic library GDS + flat design GDS + DEF.

    Two qualified masters (CELLA, CELLB) each draw a 0.4x1.0um implant rect.
    Placed abutting with a 0.2um gap (< 0.26 rule) -> ONE artifact space viol.
    A stray top-level implant pair 0.2um apart, far away, outside every cell
    footprint -> ONE real space viol. A metal rect covers ONLY the abutment
    gap (not the stray)."""
    pya = pytest.importorskip("pya")
    IMP, MET = (4, 0), (9, 0)

    lib = pya.Layout()
    lib.dbu = 0.001
    li_imp = lib.layer(pya.LayerInfo(*IMP))
    for name in ("CELLA", "CELLB"):
        c = lib.create_cell(name)
        c.shapes(li_imp).insert(pya.Box(0, 0, 400, 1000))   # 0.4 x 1.0 um
    lib_path = tmp_path / "lib.gds"
    lib.write(str(lib_path))

    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("TOP")
    di = ly.layer(pya.LayerInfo(*IMP))
    dm = ly.layer(pya.LayerInfo(*MET))
    # placed qualified-cell implant (abutment gap 400..600 = 0.2um)
    top.shapes(di).insert(pya.Box(0, 0, 400, 1000))
    top.shapes(di).insert(pya.Box(600, 0, 1000, 1000))
    # stray top-level implant pair far away (gap 5400..5600 = 0.2um)
    top.shapes(di).insert(pya.Box(5000, 0, 5400, 1000))
    top.shapes(di).insert(pya.Box(5600, 0, 6000, 1000))
    # routed metal only over the abutment gap (not the stray)
    top.shapes(dm).insert(pya.Box(300, 0, 700, 1000))
    gds_path = tmp_path / "design.gds"
    ly.write(str(gds_path))

    def_path = tmp_path / "placed.def"
    def_path.write_text(
        "COMPONENTS 2 ;\n"
        "- a CELLA + PLACED ( 0 0 ) N ;\n"
        "- b CELLB + PLACED ( 600 0 ) N ;\n"
        "END COMPONENTS\n")
    return str(gds_path), str(lib_path), str(def_path)


def test_attribute_positive_and_negative(tmp_path):
    pytest.importorskip("pya")
    gds, lib, dfp = _build_synth(tmp_path)
    res = A.attribute(
        gds, lib, dfp, "TOP",
        qualified=["CELLA", "CELLB"],
        feol_layers=[(4, 0)], space_um=0.26, overhang_um=0.2,
        metal_layers=[(9, 0)])
    t = res["totals"]
    # two space violations total: one abutment artifact, one stray real
    assert t["feol_space_violations"] == 2
    # POSITIVE: the abutment over-fire is a qualified-cell-interior candidate
    assert t["qualified_cell_interior_candidate"] == 1
    # NEGATIVE: the stray real violation is NOT exempted (stays top-level)
    assert t["top_level_or_unqualified"] == 1
    # the artifact has routed metal overlapping -> a flat marker would carve it
    assert t["metal_overlapping"] == 1
    assert res["flat_marker_can_exempt"] is False
    # never a verdict
    assert res["disclosure_only"] is True
    assert res["qualified_instances_placed"] == 2


def test_negative_never_exempts_when_no_qualified(tmp_path):
    """If NO master is declared qualified, NOTHING is exempted -- both the
    abutment and the stray stay top-level/real. Guards against a footprint
    that accidentally exempts on placement alone."""
    pytest.importorskip("pya")
    gds, lib, dfp = _build_synth(tmp_path)
    res = A.attribute(
        gds, lib, dfp, "TOP",
        qualified=[],                      # nothing qualified
        feol_layers=[(4, 0)], space_um=0.26, overhang_um=0.2,
        metal_layers=[(9, 0)])
    t = res["totals"]
    assert t["feol_space_violations"] == 2
    assert t["qualified_cell_interior_candidate"] == 0     # nothing exempted
    assert t["top_level_or_unqualified"] == 2


def test_flat_marker_flag_true_when_no_metal_overlap(tmp_path):
    """flat_marker_can_exempt is True ONLY when candidate artifacts exist AND
    none has routed metal over it (a flat marker COULD then exempt them)."""
    pytest.importorskip("pya")
    gds, lib, dfp = _build_synth(tmp_path)
    res = A.attribute(
        gds, lib, dfp, "TOP",
        qualified=["CELLA", "CELLB"],
        feol_layers=[(4, 0)], space_um=0.26, overhang_um=0.2,
        metal_layers=[])                    # ignore metal
    assert res["totals"]["qualified_cell_interior_candidate"] == 1
    assert res["totals"]["metal_overlapping"] == 0
    assert res["flat_marker_can_exempt"] is True


def test_disclosure_only_module_contract():
    """The module must document disclosure-only semantics and must NOT import
    or mutate any verdict/gate machinery."""
    src = (PROG / "signoff_cell_aware_feol_attribution.py").read_text()
    assert "DISCLOSURE" in src
    assert "never" in src.lower() and "waive" in src.lower()
    # attribution returns the disclosure_only flag hard-coded True
    assert '"disclosure_only": True' in src
