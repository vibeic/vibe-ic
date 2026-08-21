#!/usr/bin/env python3
"""G-FIXED-DIE-1 — a design-PROVIDED MANDATED fixed-floorplan contract lands in
L19 and is honored by phase3 die-sizing.

Pre-fix, phase1 dropped a design's fixed floorplan: even when the design
shipped an OpenLane ``config.json`` (``FP_SIZING:"absolute"`` +
``DIE_AREA:[x0,y0,x1,y1]`` + ``FP_DEF_TEMPLATE``) AND an L9 prose
``DIE_AREA = [x0,y0,x1,y1] µm``, L19 emitted
``die_area_budget_um:null / floorplan_hints:[] / constraints_present:false``,
so phase3 auto-sized a die the design had already fixed.

These tests use SYNTHETIC configs/docs with numbers and paths DIFFERENT from
any real chip (1234x5678, 800x600, 640x480, "myblk", "top_wrap", "chip_top")
to prove the mechanism reads the input and hardcodes NOTHING. Both the
OpenLane-json path and the prose path are covered, plus the no-contract
(stays null) case and the phase3 L19→sizer consumption.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import floorplan_contract as FPC          # noqa: E402
import phase1_doc_one_shot_runner as P1   # noqa: E402
import phase3_one_shot_runner as P3       # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _openlane_config(design: str, die, sizing="absolute",
                     def_template=None, pin_order=None) -> str:
    cfg = {
        "DESIGN_NAME": design,
        "VERILOG_FILES": [f"dir::rtl/{design}.v"],
        "FP_SIZING": sizing,
        "DIE_AREA": die,
    }
    if def_template:
        cfg["FP_DEF_TEMPLATE"] = def_template
    if pin_order:
        cfg["FP_PIN_ORDER_CFG"] = pin_order
    return json.dumps(cfg, indent=2)


# ===========================================================================
# 1. floorplan_contract module — OpenLane-json path
# ===========================================================================
def test_openlane_json_die_area_extracted(tmp_path):
    proj = tmp_path / "p"
    _write(proj / "input" / "design_src" / "openlane" / "myblk"
           / "config.json",
           _openlane_config("myblk", [0, 0, 1234, 5678],
                            def_template="dir::fixed/myblk.def",
                            pin_order="dir::pins/myblk_pins.cfg"))
    c = FPC.extract_floorplan_contract(proj)
    assert c["constraints_present"] is True
    assert c["die_area_budget_um"] == "1234x5678"       # 1234-0 x 5678-0
    kinds = {h["kind"]: h["value"] for h in c["floorplan_hints"]}
    assert kinds["fp_sizing"] == "absolute"
    assert kinds["die_area"] == "1234x5678"
    assert kinds["def_template"] == "fixed/myblk.def"    # dir:: stripped
    assert kinds["pin_order"] == "pins/myblk_pins.cfg"


def test_openlane_json_die_area_nonzero_origin(tmp_path):
    # W = urx-llx, H = ury-lly (origin need not be 0,0).
    proj = tmp_path / "p"
    _write(proj / "input" / "openlane" / "chip_top" / "config.json",
           _openlane_config("chip_top", [10, 20, 810, 620]))
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] == "800x600"


def test_openlane_die_area_as_string(tmp_path):
    # OpenLane also accepts a whitespace string DIE_AREA.
    proj = tmp_path / "p"
    _write(proj / "input" / "openlane" / "s" / "config.json",
           _openlane_config("s", "0 0 4321 8765"))
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] == "4321x8765"


def test_classic_tcl_config(tmp_path):
    proj = tmp_path / "p"
    _write(proj / "input" / "openlane" / "t" / "config.tcl",
           'set ::env(DESIGN_NAME) "t"\n'
           'set ::env(FP_SIZING) "absolute"\n'
           'set ::env(DIE_AREA) "0 0 555 777"\n'
           'set ::env(FP_DEF_TEMPLATE) "dir::fixed/t.def"\n')
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] == "555x777"
    kinds = {h["kind"]: h["value"] for h in c["floorplan_hints"]}
    assert kinds["fp_sizing"] == "absolute"
    assert kinds["def_template"] == "fixed/t.def"


# ===========================================================================
# 2. floorplan_contract module — prose path
# ===========================================================================
def test_prose_die_area_extracted(tmp_path):
    proj = tmp_path / "p"
    _write(proj / "input" / "docs" / "L9_constraints_floorplan.md",
           "# L9 — Constraints & Floorplan\n"
           "- `FP_SIZING = absolute`, `DIE_AREA = [0, 0, 640, 480]` µm.\n")
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] == "640x480"
    assert c["constraints_present"] is True
    kinds = {h["kind"] for h in c["floorplan_hints"]}
    assert "fp_sizing" in kinds


def test_prose_die_width_height_pair(tmp_path):
    proj = tmp_path / "p"
    _write(proj / "phase1" / "input_doc" / "L9_floorplan.txt",
           "DIE_WIDTH = 900 µm\nDIE_HEIGHT = 1100 µm\n")
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] == "900x1100"


def test_prose_wins_over_configs(tmp_path):
    # Prose is the authoritative design statement; when present it resolves
    # the die even if configs disagree.
    proj = tmp_path / "p"
    _write(proj / "input" / "docs" / "L9_floorplan.md",
           "`DIE_AREA = [0, 0, 2000, 3000]` µm is the fixed wrapper die.\n")
    _write(proj / "input" / "openlane" / "sub" / "config.json",
           _openlane_config("sub", [0, 0, 111, 222]))
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] == "2000x3000"


# ===========================================================================
# 3. no-contract → stays null
# ===========================================================================
def test_no_contract_stays_null(tmp_path):
    proj = tmp_path / "p"
    _write(proj / "input" / "docs" / "README.md",
           "# Adder\nA 16-bit ripple-carry adder. No floorplan here.\n")
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] is None
    assert c["floorplan_hints"] == []
    assert c["constraints_present"] is False


def test_reference_flow_config_is_off_limits(tmp_path):
    # §4.05 — a DIE_AREA that lives ONLY in a golden/reference-flow tree must
    # NOT be read (it is the oracle, not the design's own statement).
    proj = tmp_path / "p"
    _write(proj / "input" / "reference_flow" / "openlane" / "g"
           / "config.json",
           _openlane_config("g", [0, 0, 7777, 8888]))
    _write(proj / "input" / "golden" / "config.json",
           _openlane_config("g2", [0, 0, 6666, 5555]))
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] is None
    assert c["constraints_present"] is False


def test_relative_sizing_no_die_stays_null(tmp_path):
    # FP_SIZING relative + no DIE_AREA → no mandated die (but sizing captured
    # as a hint so constraints_present reflects the partial contract).
    proj = tmp_path / "p"
    _write(proj / "input" / "openlane" / "r" / "config.json",
           json.dumps({"DESIGN_NAME": "r", "FP_SIZING": "relative",
                       "FP_CORE_UTIL": 45}))
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] is None


# ===========================================================================
# 4. multi-config disambiguation + aux files (pin_order + vsrc/*.loc)
# ===========================================================================
def test_multi_config_top_module_hint(tmp_path):
    proj = tmp_path / "p"
    _write(proj / "input" / "openlane" / "top_wrap" / "config.json",
           _openlane_config("top_wrap", [0, 0, 3000, 4000]))
    _write(proj / "input" / "openlane" / "leaf" / "config.json",
           _openlane_config("leaf", [0, 0, 900, 500]))
    c = FPC.extract_floorplan_contract(proj, top_module="top_wrap")
    assert c["die_area_budget_um"] == "3000x4000"


def test_multi_config_design_name_frequency(tmp_path):
    # No top_module hint, no prose rect: the more-referenced DESIGN_NAME wins.
    proj = tmp_path / "p"
    _write(proj / "input" / "openlane" / "top_wrap" / "config.json",
           _openlane_config("top_wrap", [0, 0, 3000, 4000]))
    _write(proj / "input" / "openlane" / "leaf" / "config.json",
           _openlane_config("leaf", [0, 0, 900, 500]))
    _write(proj / "input" / "docs" / "overview.md",
           "The top_wrap integrates leaf. top_wrap is the tapeout top; "
           "top_wrap owns the pad ring.\n")
    c = FPC.extract_floorplan_contract(proj)
    assert c["die_area_budget_um"] == "3000x4000"


def test_power_source_and_pin_order_aux_files(tmp_path):
    proj = tmp_path / "p"
    ol = proj / "input" / "openlane" / "w"
    _write(ol / "config.json", _openlane_config("w", [0, 0, 1000, 2000]))
    _write(ol / "pin_order.cfg", "#BUS_SORT\nclk\nrst\n")
    _write(ol / "vsrc" / "w_vccd_vsrc.loc", "500,600,24,1.8\n")
    _write(ol / "vsrc" / "w_vssd_vsrc.loc", "500,650,24,1.8\n")
    c = FPC.extract_floorplan_contract(proj)
    kinds = [h["kind"] for h in c["floorplan_hints"]]
    assert kinds.count("power_source_location") == 2
    assert "pin_order" in kinds


# ===========================================================================
# 5. phase1 integration — _post_emit_floorplan_contract populates L19 on disk
# ===========================================================================
def _seed_l19(proj: Path) -> Path:
    gd = proj / "phase1" / "generated_docs"
    l19 = gd / "L19_CONSTRAINTS_PDK.json"
    _write(l19, json.dumps({
        "doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
        "applicability": "APPLICABLE", "ic_class": "unknown",
        "fields": {
            "pdk_target": "sky130a", "die_area_budget_um": None,
            "power_budget_uw": None, "sdc_constraints_path": None,
            "floorplan_hints": [], "constraints_present": False,
        },
        "extraction_status": "PARTIALLY_EXTRACTED",
    }, indent=2))
    return l19


def test_phase1_hook_populates_l19_from_json_config(tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_l19(proj)
    _write(proj / "input" / "design_src" / "openlane" / "myblk"
           / "config.json",
           _openlane_config("myblk", [0, 0, 1234, 5678],
                            def_template="dir::fixed/myblk.def"))
    P1._post_emit_floorplan_contract(proj)
    doc = json.loads(l19.read_text())
    f = doc["fields"]
    assert f["die_area_budget_um"] == "1234x5678"
    assert f["constraints_present"] is True
    assert any(h["kind"] == "def_template" for h in f["floorplan_hints"])
    # provenance recorded
    assert "extraction_evidence" in doc


def test_phase1_hook_populates_l19_from_prose(tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_l19(proj)
    _write(proj / "input" / "docs" / "L9_floorplan.md",
           "`FP_SIZING = absolute`, `DIE_AREA = [0, 0, 640, 480]` µm.\n")
    P1._post_emit_floorplan_contract(proj)
    f = json.loads(l19.read_text())["fields"]
    assert f["die_area_budget_um"] == "640x480"
    assert f["constraints_present"] is True


def test_phase1_hook_noop_without_contract(tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_l19(proj)
    _write(proj / "input" / "docs" / "README.md", "Plain adder, no floorplan.\n")
    P1._post_emit_floorplan_contract(proj)
    f = json.loads(l19.read_text())["fields"]
    assert f["die_area_budget_um"] is None
    assert f["constraints_present"] is False
    assert f["floorplan_hints"] == []


def test_phase1_hook_does_not_clobber_existing_die(tmp_path):
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    l19 = gd / "L19_CONSTRAINTS_PDK.json"
    _write(l19, json.dumps({
        "fields": {"die_area_budget_um": "111x222",
                   "floorplan_hints": [], "constraints_present": True},
    }))
    _write(proj / "input" / "openlane" / "x" / "config.json",
           _openlane_config("x", [0, 0, 999, 888]))
    P1._post_emit_floorplan_contract(proj)
    f = json.loads(l19.read_text())["fields"]
    assert f["die_area_budget_um"] == "111x222"    # not clobbered


# ===========================================================================
# 6. phase3 consumption — L19.die_area_budget_um honored by die-sizing
# ===========================================================================
def _mk_proj_with_l19_die(tmp_path, wxh) -> Path:
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    _write(gd / "L19_CONSTRAINTS_PDK.json", json.dumps({
        "fields": {"die_area_budget_um": wxh}}))
    return proj


def test_phase3_l19_die_area_reader(tmp_path):
    proj = _mk_proj_with_l19_die(tmp_path, "1234x5678")
    assert P3._l19_declared_die_area(proj) == "1234x5678"


def test_phase3_l19_die_area_reader_rejects_garbage(tmp_path):
    for bad in (None, "", "auto", "0x100", "abc"):
        proj = tmp_path / f"p_{bad}"
        gd = proj / "phase1" / "generated_docs"
        _write(gd / "L19_CONSTRAINTS_PDK.json",
               json.dumps({"fields": {"die_area_budget_um": bad}}))
        assert P3._l19_declared_die_area(proj) is None


def test_phase3_effective_die_honors_l19(tmp_path):
    # die-um=auto + no L9 prose → L19.die_area_budget_um is honored.
    proj = _mk_proj_with_l19_die(tmp_path, "800x600")
    eff, note = P3._effective_die_um("auto", proj)
    assert eff == "800x600"
    assert note and "L19" in note


def test_phase3_explicit_flag_beats_l19(tmp_path):
    # An explicit --die-um WxH ALWAYS wins over any mandated die.
    proj = _mk_proj_with_l19_die(tmp_path, "800x600")
    eff, note = P3._effective_die_um("400x400", proj)
    assert eff == "400x400"
    assert note is None


def test_phase3_l9_prose_beats_l19(tmp_path):
    # L9 prose rect outranks L19 (precedence: flag > L9 prose > L19 > auto).
    proj = _mk_proj_with_l19_die(tmp_path, "800x600")
    _write(proj / "input" / "docs" / "L9_floorplan.md",
           "`DIE_AREA = [0, 0, 1500, 1500]` µm fixed.\n")
    eff, _note = P3._effective_die_um("auto", proj)
    assert eff == "1500x1500"


def test_phase3_no_mandate_passes_auto_through(tmp_path):
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    eff, note = P3._effective_die_um("auto", proj)
    assert eff == "auto"
    assert note is None
