from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flow_config import build_config, write_config


@pytest.fixture
def project(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "unit.v").write_text("module unit(input clk, output q); assign q=clk; endmodule\n")
    for name, data in {
        "L9_INTEGRATION_SPEC.json": {"top_module": "unit"},
        "L8_TIMING_WAVEFORM.json": {"clock_domains": [
            {"domain_kind": "primary", "source_pin": "clk", "period_ns": 17.5}]},
        "L19_CONSTRAINTS_PDK.json": {"fields": {"pdk_target": "sky130A"}},
    }.items():
        (docs / name).write_text(json.dumps(data))
    return tmp_path


def declarations(project, rows):
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    data = json.loads(path.read_text())
    data["fields"]["constraint_declarations"] = rows
    path.write_text(json.dumps(data))


def test_config_uses_documents_and_leaves_pdk_defaults(project):
    config = build_config(project, route="ip")
    assert config["DESIGN_NAME"] == "unit"
    assert config["CLOCK_PORT"] == "clk"
    assert config["CLOCK_PERIOD"] == 17.5
    assert config["PDK"] == "sky130A"
    assert config["VERILOG_FILES"] == [str(project / "phase2/stage1/rtl/unit.v")]
    assert "PDN_CFG" not in config
    assert "FP_CORE_UTIL" not in config


def test_declaration_values_keep_native_units_and_pdk_scope(project):
    declarations(project, [
        {"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "20%"},
        {"kind": "flow_setting", "token": "PL_TARGET_DENSITY", "value": "0.25"},
        {"kind": "flow_setting", "token": "SYNTH_MAX_FANOUT", "value": "8"},
        {"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "55", "scope": "other*"},
    ])
    config = build_config(project)
    assert config["FP_CORE_UTIL"] == 20
    assert config["PL_TARGET_DENSITY_PCT"] == 25
    assert config["MAX_FANOUT_CONSTRAINT"] == 8
    assert "CTS_SINK_CLUSTERING_SIZE" not in config


def test_conflicting_limits_are_not_silently_selected(project):
    declarations(project, [
        {"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "20"},
        {"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "30"},
    ])
    with pytest.raises(ValueError, match="Conflicting L19"):
        build_config(project)


def test_missing_rtl_is_missing_input(project):
    (project / "phase2/stage1/rtl/unit.v").unlink()
    with pytest.raises(FileNotFoundError, match="No produced RTL"):
        build_config(project)


def test_chip_pdn_uses_native_script_and_registry_connections(project, monkeypatch):
    import flow_config

    registry = project / "registry"
    registry.mkdir()
    (registry / "pdk_registry.json").write_text(json.dumps({"pdks": [{
        "name": "sky130A", "pdn_ring": {
            "layers": ["vertical", "horizontal"], "widths": [1, 2],
            "spacings": [3, 4], "core_offset_um": 6,
            "connect_to_pad_layers": ["pad"], "connects": [["pad", "horizontal"]],
        }}]}))
    monkeypatch.setattr(flow_config, "PROGRAMS", registry)
    config = build_config(project, route="ic")
    assert config["PDN_VOFFSET"] == config["PDN_HOFFSET"] == 7
    assert config["PDN_SKIPTRIM"] is True
    assert config["PDN_CORE_RING_HWIDTH"] == 2
    assert config["PDN_CORE_RING_VOFFSET"] == 6
    assert config["PDN_CORE_RING_CONNECT_TO_PADS"] is True
    assert Path(config["PDN_CFG"]).read_text() == (
        "source $::env(SCRIPTS_DIR)/openroad/common/pdn_cfg.tcl\n"
        "add_pdn_connect -grid stdcell_grid -layers {pad horizontal}\n")


def test_config_cli_output_is_the_config_the_caller_receives(project):
    output = write_config(project, route="HARDMACRO")
    assert json.loads(output.read_text()) == build_config(project, route="HARDMACRO")


def test_original_prompt_recovers_lost_pdk_and_invalid_top(project):
    (project / "input").mkdir()
    (project / "input/phase1_prompt.md").write_text(
        "Implement on sky130A.\n- Top module: `unit`.\n")
    docs = project / "phase1/generated_docs"
    (docs / "L9_INTEGRATION_SPEC.json").write_text('{"top_module": "missing"}')
    (docs / "L19_CONSTRAINTS_PDK.json").write_text('{"fields":{"pdk_target":null}}')
    config = build_config(project)
    assert config["PDK"] == "sky130A"
    assert config["DESIGN_NAME"] == "unit"
    assert config["CLOCK_PERIOD"] == 17.5
    assert json.loads((project / "work/flow/config_sources.json").read_text())["sources"] == {
        "PDK": "input/phase1_prompt.md", "DESIGN_NAME": "input/phase1_prompt.md"}


def test_primary_clock_without_period_keeps_native_default_and_records_assumption(project):
    (project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json").write_text("{}")
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "interfaces.md").write_text(
        "- Primary Clock: **`clk`**\n- Other Clocks: **`entropy_clk`**\n"
        "Entropy is supplied at 100 MHz.\n")
    config = build_config(project)
    assert config["CLOCK_PORT"] == "clk"
    assert "CLOCK_PERIOD" not in config
    notes = json.loads((project / "work/flow/config_sources.json").read_text())
    assert notes["sources"]["CLOCK_PORT"] == "input/docs/interfaces.md"
    assert "not a design timing target" in notes["assumptions"][0]


def test_nested_generated_modules_and_headers_are_native_inputs(project):
    rtl = project / "phase2/stage1/rtl"
    nested = rtl / "cells"
    nested.mkdir()
    (nested / "cell.v").write_text("module cell; endmodule\n")
    (nested / "types.svh").write_text("`define WIDTH 8\n")
    (rtl / "types_pkg.sv").write_text("package types_pkg; parameter N=8; endpackage\n")
    config = build_config(project)
    assert str(nested / "cell.v") in config["VERILOG_FILES"]
    assert str(nested) in config["VERILOG_INCLUDE_DIRS"]
    assert config["USE_SLANG"] is True


def test_missing_declared_top_is_not_replaced_by_an_unrelated_module(project):
    (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        '{"top_module":"missing"}')
    with pytest.raises(FileNotFoundError, match="Declared top module missing"):
        build_config(project)
