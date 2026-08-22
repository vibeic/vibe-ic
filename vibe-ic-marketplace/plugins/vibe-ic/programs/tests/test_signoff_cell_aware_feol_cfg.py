#!/usr/bin/env python3
"""Tests for signoff_cell_aware_feol_cfg.py (BUILD the --cell-aware-feol cfg for
the native svrfdrc engine).

Hermetic: no docker / no svrfdrc / no pya. The standalone svrfdrc runs are injected
as a fake callable returning report TEXT, so the gate + qualification + cfg-render
logic is fully exercised deterministically. It hardcodes no chip/vendor/cell/layer
literal — all names are synthetic.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import signoff_cell_aware_feol_cfg as C  # noqa: E402


# ── DEF placed-master parse (robust to + SOURCE / + EEQMASTER) ────────────────
def test_parse_placed_masters_source_clause():
    deftxt = (
        "VERSION 5.8 ;\nDESIGN d ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "COMPONENTS 5 ;\n"
        "- f0 FILLA + SOURCE DIST + PLACED ( 10 0 ) N ;\n"
        "- f1 FILLA + SOURCE DIST + PLACED ( 20 0 ) FS ;\n"
        "- d0 DECAPZ + SOURCE DIST + FIXED ( 30 0 ) S ;\n"
        "- u0 CELLQ + EEQMASTER CELLQX + SOURCE NETLIST + PLACED ( 40 0 ) N ;\n"
        "- u1 CELLQ + PLACED ( 50 0 ) N ;\n"
        "END COMPONENTS\n")
    m = C.parse_placed_masters(deftxt)
    assert m == {"FILLA": 2, "DECAPZ": 1, "CELLQ": 2}


def test_parse_placed_masters_scoped_to_components():
    # a PINS `- name + NET ...` line must never be parsed as a placement
    deftxt = (
        "COMPONENTS 1 ;\n- u0 CELLQ + PLACED ( 0 0 ) N ;\nEND COMPONENTS\n"
        "PINS 1 ;\n- pinA + NET n0 + PLACED ( 5 5 ) N ;\nEND PINS\n")
    assert C.parse_placed_masters(deftxt) == {"CELLQ": 1}


# ── deck rule-name enumeration by prefix ──────────────────────────────────────
def test_enumerate_feol_rules_prefix_and_boundary():
    deck = (
        "L1=NOT A B\n"
        "PO.S.2 {\n    EXTERNAL L1 <0.25 REGION SINGULAR ABUT<90\n}\n"
        "PO.S.1.3 {\n    EXTERNAL L2 <0.375\n}\n"
        "NW.S.1.1 {\n    EXTERNAL L3 <0.6\n}\n"
        "PO.W.4.1 {\n    INTERNAL L4 <0.18\n}\n"       # width, not space -> excluded
        "POSX.1 {\n    EXTERNAL L5 <0.1\n}\n")          # shares 'PO.S'? no: 'POSX'
    rules = C.enumerate_feol_rules(deck, ["PO.S", "NW.S"])
    assert rules == ["NW.S.1.1", "PO.S.1.3", "PO.S.2"]
    # exact-name prefix matches only itself
    assert C.enumerate_feol_rules(deck, ["NW.S.1.1"]) == ["NW.S.1.1"]
    assert C.enumerate_feol_rules(deck, []) == []


# ── standalone qualification classifier ───────────────────────────────────────
_DENSITY_ONLY = (
    "# header\n"
    "FAIL  PDF.D.3.2   DENSITY POLY_DUD < 0.14 [metrics=euclidian] -> 1\n"
    "FAIL  PDF.D.6.1   DENSITY MET2_DUD < 0.3 [metrics=euclidian] -> 1\n"
    "PASS  NW.S.1.1    EXTERNAL foo < 0.6 -> 0\n"
    "# tally: {'PASS': 4528, 'FAIL': 2}\n")

_HAS_GEOMETRY = (
    "FAIL  PDF.D.6.1   DENSITY MET2_DUD < 0.3 -> 1\n"
    "FAIL  PO.S.2      EXTERNAL L1 < 0.25 -> 3\n"       # a real space fail
    "# tally: {'PASS': 10, 'FAIL': 2}\n")


def test_standalone_qualified_density_only_passes():
    assert C.standalone_nondensity_fails(_DENSITY_ONLY) == []
    assert C.standalone_qualified(_DENSITY_ONLY) is True


def test_standalone_disqualified_on_geometry_fail():
    assert C.standalone_nondensity_fails(_HAS_GEOMETRY) == ["PO.S.2"]
    assert C.standalone_qualified(_HAS_GEOMETRY) is False


def test_standalone_empty_or_missing_report_never_qualifies():
    assert C.standalone_qualified("") is False
    assert C.standalone_qualified("garbage no tally") is False
    assert C.standalone_qualified("# tally: {'PASS': 1}\n") is True  # 0 fails


# ── feol_gds parse ────────────────────────────────────────────────────────────
def test_parse_feol_gds_forms():
    assert C.parse_feol_gds(["2/0,3/0,4"]) == [(2, 0), (3, 0), (4, 0)]
    assert C.parse_feol_gds(["5/2", "6"]) == [(5, 2), (6, 0)]
    assert C.parse_feol_gds([]) == []


def test_feol_gds_from_config_list_and_dict():
    assert C.feol_gds_from_config({"feol_gds": ["2/0", "3/0"]}) == [(2, 0), (3, 0)]
    # a name->L/D dict (tap-style): values only, names ignored
    assert C.feol_gds_from_config(
        {"feol_gds": {"nwell": "2/0", "poly": "3/0"}}) == [(2, 0), (3, 0)]
    assert C.feol_gds_from_config({}) == []


# ── cfg render ────────────────────────────────────────────────────────────────
def test_render_cfg_shape():
    txt = C.render_cfg("/c/lib.gds", "/c/p.def", ["Q", "A"],
                       ["PO.S.2", "NW.S.1.1"], [(4, 0), (3, 0)], strict_dbu=1)
    lines = {ln.split(None, 1)[0]: ln for ln in txt.splitlines()
             if ln and not ln.startswith("#")}
    assert lines["lib"].strip() == "lib /c/lib.gds"
    assert lines["def"].strip() == "def /c/p.def"
    assert lines["qualified"].strip() == "qualified A Q"          # sorted
    assert lines["feol_rule"].strip() == "feol_rule NW.S.1.1 PO.S.2"
    assert lines["feol_gds"].strip() == "feol_gds 4/0 3/0"
    assert lines["strict_dbu"].strip() == "strict_dbu 1"


# ── build_cfg orchestration (gate + qualification), fake svrfdrc runner ───────
_DECK = (
    "PO.S.2 {\n    EXTERNAL L1 <0.25 REGION SINGULAR ABUT<90\n}\n"
    "NP.S.1 {\n    EXTERNAL L2 <0.26\n}\n")

_DEF = (
    "COMPONENTS 3 ;\n"
    "- u0 CLEANQ + SOURCE DIST + PLACED ( 0 0 ) N ;\n"
    "- u1 DIRTYD + PLACED ( 100 0 ) N ;\n"
    "- u2 CLEANQ + PLACED ( 200 0 ) N ;\n"
    "END COMPONENTS\n")


def _fake_runner(clean_masters):
    def _run(master):
        return _DENSITY_ONLY if master in clean_masters else _HAS_GEOMETRY
    return _run


def test_build_cfg_positive_only_qualified_masters(tmp_path):
    out = tmp_path / "caf.cfg"
    res = C.build_cfg(
        deck_text=_DECK, def_text=_DEF, lib_container="/c/lib.gds",
        def_container="/c/p.def", feol_gds=[(4, 0), (5, 0)],
        feol_rule_prefixes=["PO.S", "NP.S"],
        run_standalone=_fake_runner({"CLEANQ"}), cfg_out=out, strict_dbu=1)
    assert res.written is True
    assert res.qualified == ["CLEANQ"]                 # DIRTYD disqualified
    assert set(res.placed_masters) == {"CLEANQ", "DIRTYD"}
    assert res.feol_rules == ["NP.S.1", "PO.S.2"]
    body = out.read_text()
    assert "qualified CLEANQ\n" in body
    assert "DIRTYD" not in body
    assert "feol_gds 4/0 5/0\n" in body


def test_build_cfg_no_qualified_master_writes_nothing(tmp_path):
    out = tmp_path / "caf.cfg"
    res = C.build_cfg(
        deck_text=_DECK, def_text=_DEF, lib_container="/c/lib.gds",
        def_container="/c/p.def", feol_gds=[(4, 0)],
        feol_rule_prefixes=["PO.S"],
        run_standalone=_fake_runner(set()), cfg_out=out, strict_dbu=1)
    assert res.written is False
    assert res.qualified == []
    assert not out.exists()


def test_build_cfg_gate_missing_feol_gds(tmp_path):
    out = tmp_path / "caf.cfg"
    res = C.build_cfg(
        deck_text=_DECK, def_text=_DEF, lib_container="/c/lib.gds",
        def_container="/c/p.def", feol_gds=[],
        feol_rule_prefixes=["PO.S"],
        run_standalone=_fake_runner({"CLEANQ"}), cfg_out=out, strict_dbu=1)
    assert res.written is False
    assert "feol_gds" in res.reason
    assert not out.exists()


def test_build_cfg_gate_no_matching_rule(tmp_path):
    out = tmp_path / "caf.cfg"
    res = C.build_cfg(
        deck_text=_DECK, def_text=_DEF, lib_container="/c/lib.gds",
        def_container="/c/p.def", feol_gds=[(4, 0)],
        feol_rule_prefixes=["ZZ.S"],                   # matches no deck rule
        run_standalone=_fake_runner({"CLEANQ"}), cfg_out=out, strict_dbu=1)
    assert res.written is False
    assert not out.exists()
