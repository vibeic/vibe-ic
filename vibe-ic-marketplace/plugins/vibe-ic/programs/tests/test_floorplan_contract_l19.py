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

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import floorplan_contract as FPC          # noqa: E402
import librelane_contract as LLC          # noqa: E402
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


@pytest.mark.parametrize("mode", ["json", "tcl", "prose"])
def test_exact_rectangle_preserves_fractional_nonzero_origin(tmp_path, mode):
    proj = tmp_path / "p"
    rect = [12.25, -7.5, 812.875, 592.75]
    if mode == "json":
        _write(proj / "input/config.json", _openlane_config("neutral_top", rect))
    elif mode == "tcl":
        _write(proj / "input/config.tcl",
               'set ::env(FP_SIZING) "absolute"\n'
               'set ::env(DIE_AREA) "12.25 -7.5 812.875 592.75"\n')
    else:
        _write(proj / "input/docs/L9_floorplan.md",
               "`FP_SIZING = absolute`, "
               "`DIE_AREA = [12.25, -7.5, 812.875, 592.75]` um.\n")

    contract = FPC.extract_floorplan_contract(proj)

    assert contract["die_area_budget_um"] == "801x600"
    assert contract.get("die_area_um") == rect


def test_exact_rectangle_uses_selected_top_config(tmp_path):
    proj = tmp_path / "p"
    rect = [10.25, 20.5, 310.75, 420.875]
    for name, area in (("neutral_top", rect), ("neutral_leaf", [0, 0, 80, 90])):
        _write(proj / f"input/{name}/config.json", _openlane_config(name, area))

    assert FPC.extract_floorplan_contract(proj, "neutral_top").get("die_area_um") == rect
    assert FPC.extract_floorplan_contract(proj, "neutral_leaf").get("die_area_um") == [0, 0, 80, 90]


def test_budget_prose_does_not_adopt_config_rectangle(tmp_path):
    proj = tmp_path / "p"
    _write(proj / "input/docs/L9_floorplan.md", "Die area budget: 1200 x 1400 um.\n")
    _write(proj / "input/config.json",
           _openlane_config("neutral_top", [20, 30, 1220, 1430]))

    contract = FPC.extract_floorplan_contract(proj, "neutral_top")

    assert contract["die_area_budget_um"] == "1200x1400"
    assert contract.get("die_area_um") is None


def test_shared_dimensions_do_not_resolve_distinct_origins(tmp_path):
    proj = tmp_path / "p"
    for name, area in (("neutral_a", [0, 0, 800, 600]),
                       ("neutral_b", [10, 20, 810, 620])):
        _write(proj / f"input/{name}/config.json", _openlane_config(name, area))

    contract = FPC.extract_floorplan_contract(proj)

    assert contract["die_area_budget_um"] == "800x600"
    assert contract.get("die_area_um") is None


@pytest.mark.parametrize("other_rect,other_mode", [
    ([10, 20, 810, 620], "absolute"),
    ([0, 0, 800, 600], "relative"),
])
def test_matching_top_configs_do_not_resolve_distinct_rectangles_or_modes(
        tmp_path, other_rect, other_mode):
    proj = tmp_path / "p"
    _write(proj / "input/a/config.json",
           _openlane_config("neutral_top", [0, 0, 800, 600]))
    _write(proj / "input/b/config.json",
           _openlane_config("neutral_top", other_rect, sizing=other_mode))

    contract = FPC.extract_floorplan_contract(proj, "neutral_top")

    assert contract["die_area_budget_um"] == "800x600"
    assert contract.get("die_area_um") is None


def test_equivalent_matching_top_configs_keep_exact_rectangle(tmp_path):
    proj = tmp_path / "p"
    rect = [10, 20, 810, 620]
    for name in ("a", "b"):
        _write(proj / f"input/{name}/config.json", _openlane_config("neutral_top", rect))

    assert FPC.extract_floorplan_contract(proj, "neutral_top").get("die_area_um") == rect


@pytest.mark.parametrize("sizing", ["", "`FP_SIZING = absolute`, "])
def test_prose_rectangle_does_not_adopt_unrelated_relative_mode(tmp_path, sizing):
    proj = tmp_path / "p"
    _write(proj / "input/docs/L9_floorplan.md",
           sizing + "`DIE_AREA = [10, 20, 810, 620]` um is the fixed die.\n")
    _write(proj / "input/docs/unrelated.md", "`FP_SIZING = relative`.\n")

    assert FPC.extract_floorplan_contract(proj).get("die_area_um") == [10, 20, 810, 620]


@pytest.mark.parametrize("mode", ["json", "tcl", "prose"])
def test_relative_sizing_does_not_turn_dormant_rectangle_into_exact_extent(
        tmp_path, mode):
    proj = tmp_path / "p"
    if mode == "json":
        _write(proj / "input/config.json",
               _openlane_config("neutral_top", [0, 0, 800, 600], sizing="relative"))
    elif mode == "tcl":
        _write(proj / "input/config.tcl",
               'set ::env(DESIGN_NAME) "neutral_top"\n'
               'set ::env(FP_SIZING) "relative"\n'
               'set ::env(DIE_AREA) "0 0 800 600"\n')
    else:
        _write(proj / "input/docs/L9_floorplan.md",
               "`FP_SIZING = relative`, `DIE_AREA = [0, 0, 800, 600]` um.\n")

    contract = FPC.extract_floorplan_contract(proj, "neutral_top")

    assert contract["die_area_budget_um"] == "800x600"
    assert contract.get("die_area_um") is None
    assert any(h["kind"] == "fp_sizing" and h["value"] == "relative"
               for h in contract["floorplan_hints"])


@pytest.mark.parametrize("mode", ["json", "tcl"])
def test_default_relative_sizing_does_not_publish_config_rectangle(tmp_path, mode):
    proj = tmp_path / "p"
    if mode == "json":
        _write(proj / "input/config.json", json.dumps({
            "DESIGN_NAME": "neutral_top", "DIE_AREA": [0, 0, 800, 600]}))
    else:
        _write(proj / "input/config.tcl",
               'set ::env(DESIGN_NAME) "neutral_top"\n'
               'set ::env(DIE_AREA) "0 0 800 600"\n')

    contract = FPC.extract_floorplan_contract(proj, "neutral_top")

    assert contract["die_area_budget_um"] == "800x600"
    assert contract.get("die_area_um") is None


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
    doc = json.loads(l19.read_text())
    f = doc["fields"]
    assert f["die_area_budget_um"] == "640x480"
    assert f["constraints_present"] is True
    evidence = doc["extraction_evidence"][
        "input/docs/L9_floorplan.md"][0]["literal"]
    assert evidence == (
        "`FP_SIZING = absolute`, `DIE_AREA = [0, 0, 640, 480]` µm.")


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


def _seed_librelane_contract_inputs(proj: Path) -> Path:
    l19 = _seed_l19(proj)
    doc = json.loads(l19.read_text())
    doc['fields']['pdk_target'] = 'processA'
    _write(l19, json.dumps(doc))
    _write(proj / "phase1/generated_docs/L8_TIMING_WAVEFORM.json",
           json.dumps({"clock_domains": [{
               "role": "primary", "pdk_scoped_target": "processA",
               "period_ns": 8, "source_pin": "clk"}]}))
    _write(proj / "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
           json.dumps({"top_module": "neutral_top"}))
    return l19


def _seed_librelane_declaration(proj: Path) -> None:
    _write(proj / "input/submission_template/tapeout_declaration.json",
           json.dumps({"answers": {
               "top_cell": "neutral_top",
               "die_area_um": [0, 0, 120, 140],
               "core_area_um": [10, 10, 110, 130]}}))


def test_exact_prose_rectangle_reaches_native_config(tmp_path):
    from flow_config import build_config

    proj = tmp_path / "p"
    l19 = _seed_librelane_contract_inputs(proj)
    _write(proj / "input/docs/L9_floorplan.md",
           "`FP_SIZING = absolute`, "
           "`DIE_AREA = [12.25, -7.5, 812.875, 592.75]` um.\n")
    _write(proj / "phase2/stage1/rtl/neutral_top.v",
           "module neutral_top(input clk); endmodule\n")

    P1._post_emit_floorplan_contract(proj)
    config = build_config(proj, route="ip")

    assert json.loads(l19.read_text())["fields"].get("die_area_um") == [12.25, -7.5, 812.875, 592.75]
    assert config.get("DIE_AREA") == [12.25, -7.5, 812.875, 592.75]
    assert config.get("FP_SIZING") == "absolute"


def test_selected_top_config_rectangle_reaches_l19(tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_librelane_contract_inputs(proj)
    rect = [10.25, 20.5, 310.75, 420.875]
    for name, area in (("neutral_top", rect), ("neutral_leaf", [0, 0, 80, 90])):
        _write(proj / f"input/{name}/config.json", _openlane_config(name, area))

    P1._post_emit_floorplan_contract(proj)

    assert json.loads(l19.read_text())["fields"].get("die_area_um") == rect


def test_budget_only_does_not_emit_native_rectangle(tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_l19(proj)
    _write(proj / "input/docs/L9_floorplan.md", "Die area budget: 1200 x 1400 um.\n")

    P1._post_emit_floorplan_contract(proj)

    fields = json.loads(l19.read_text())["fields"]
    assert fields["die_area_budget_um"] == "1200x1400"
    assert fields.get("die_area_um") is None


def test_existing_typed_rectangle_is_not_overwritten(tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_l19(proj)
    original = [1.25, 2.5, 101.75, 202.875]
    doc = json.loads(l19.read_text())
    doc["fields"]["die_area_um"] = original
    _write(l19, json.dumps(doc))
    _write(proj / "input/config.json",
           _openlane_config("neutral_top", [0, 0, 800, 600]))

    P1._post_emit_floorplan_contract(proj)

    assert json.loads(l19.read_text())["fields"]["die_area_um"] == original


def test_structured_core_util_reaches_l19_and_actual_librelane_consumer(
        tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_librelane_contract_inputs(proj)
    config = proj / "input/config.json"
    _write(config, json.dumps({
        "DESIGN_NAME": "neutral_top",
        "FP_SIZING": "absolute",
        "DIE_AREA": [0, 0, 120, 140],
        "FP_CORE_UTIL": 25,
    }, indent=2))

    P1._post_emit_floorplan_contract(proj)
    fields = json.loads(l19.read_text())["fields"]
    rows = [row for row in fields.get("constraint_declarations", [])
            if row.get("token") == "FP_CORE_UTIL"]
    assert rows == [{
        "token": "FP_CORE_UTIL", "value": 25, "scope": None,
        "source": "input/config.json", "line": 10}]
    assert fields["die_area_budget_um"] == "120x140"
    assert {row["kind"] for row in fields["floorplan_hints"]} >= {
        "die_area", "fp_sizing"}

    _seed_librelane_declaration(proj)
    output = proj / "phase3/librelane/config.json"
    emitted = LLC.emit_config(proj, "processA", output)
    assert emitted["FP_CORE_UTIL"] == 25
    provenance = json.loads(
        output.with_suffix(".provenance.json").read_text())
    assert "input/config.json" in provenance["FP_CORE_UTIL"]


@pytest.mark.parametrize("value", [
    0, -1, 100.01, "25", "not-a-number", None, True, float("nan")])
def test_structured_core_util_refuses_invalid_or_out_of_range(tmp_path, value):
    proj = tmp_path / "p"
    _write(proj / "input/config.json", json.dumps({
        "DESIGN_NAME": "neutral_top", "FP_CORE_UTIL": value}))
    with pytest.raises(
            FPC.FloorplanContractRefusal,
            match=r"FP_CORE_UTIL_(?:INVALID|RANGE)"):
        FPC.extract_floorplan_contract(proj)


def test_structured_core_util_refuses_multiple_config_authorities(tmp_path):
    proj = tmp_path / "p"
    for name, value in (("a", 25), ("b", 35)):
        _write(proj / f"input/{name}/config.json", json.dumps({
            "DESIGN_NAME": name, "FP_CORE_UTIL": value}))
    with pytest.raises(
            FPC.FloorplanContractRefusal,
            match="FP_CORE_UTIL_AUTHORITY_CONFLICT"):
        FPC.extract_floorplan_contract(proj)


def test_structured_core_util_refuses_existing_l19_authority(tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_l19(proj)
    doc = json.loads(l19.read_text())
    doc["fields"]["constraint_declarations"] = [{
        "token": "FP_CORE_UTIL", "value": 35, "scope": None,
        "source": "input/docs/floorplan.md", "line": 4}]
    _write(l19, json.dumps(doc))
    _write(proj / "input/config.json", json.dumps({
        "DESIGN_NAME": "neutral_top", "FP_CORE_UTIL": 25}))
    with pytest.raises(
            FPC.FloorplanContractRefusal,
            match="FP_CORE_UTIL_AUTHORITY_CONFLICT"):
        P1._post_emit_floorplan_contract(proj)


def test_absent_structured_core_util_stays_absent_from_actual_consumer(
        tmp_path):
    proj = tmp_path / "p"
    l19 = _seed_librelane_contract_inputs(proj)
    _write(proj / "input/config.json", json.dumps({
        "DESIGN_NAME": "neutral_top",
        "FP_SIZING": "absolute",
        "DIE_AREA": [0, 0, 120, 140]}))
    P1._post_emit_floorplan_contract(proj)
    fields = json.loads(l19.read_text())["fields"]
    assert not any(row.get("token") == "FP_CORE_UTIL"
                   for row in fields.get("constraint_declarations", []))
    _seed_librelane_declaration(proj)
    emitted = LLC.emit_config(
        proj, "processA", proj / "phase3/librelane/config.json")
    assert "FP_CORE_UTIL" not in emitted


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










# ── polarity for FP_SIZING, the sibling of the guarded DIE_AREA path (#712) ──
#
# Found by prose_polarity_census. This file guards its die figure with
# `_die_statement_negated` and did not guard the sizing beside it, so a document
# retiring a sizing recorded it as a mandated hint. Two readers of one document
# disagreeing about a denial is #711 itself.

def _fp(doc, tmp_path):
    import floorplan_contract as M
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "input" / "constraints.md").write_text(doc, encoding="utf-8")
    return [h["value"] for h in
            M.extract_floorplan_contract(tmp_path)["floorplan_hints"]
            if h["kind"] == "fp_sizing"]


def test_a_retired_sizing_is_not_a_mandated_hint(tmp_path):
    assert _fp("FP_SIZING absolute is no longer used for this block.\n",
               tmp_path) == []


def test_an_explicitly_negated_sizing_is_not_recorded(tmp_path):
    assert _fp("This block does not use FP_SIZING absolute.\n", tmp_path) == []


def test_a_plainly_stated_sizing_is_still_recorded(tmp_path):
    """The control arm: a fix that recorded nothing would pass the rest."""
    assert _fp("The floorplan uses FP_SIZING absolute for this block.\n",
               tmp_path) == ["absolute"]


def test_a_denial_does_not_end_the_search(tmp_path):
    """`finditer`, not `search`. A document that retires one sizing and then
    states another in a later PARAGRAPH must yield the live one -- the scope
    this file uses for prose is the paragraph, inherited here deliberately so
    the two readers of one document agree."""
    assert _fp("FP_SIZING absolute is no longer used.\n\n"
               "The floorplan uses FP_SIZING relative.\n", tmp_path) == ["relative"]


def test_a_denied_TABLE_row_does_not_veto_the_row_beneath(tmp_path):
    """A markdown row is a self-contained record and this file already scopes it
    to its own line. That semantic is inherited too, not re-invented."""
    assert _fp("| setting | value |\n|---|---|\n"
               "| FP_SIZING absolute | no longer used |\n"
               "| FP_SIZING relative | the target |\n", tmp_path) == ["relative"]
