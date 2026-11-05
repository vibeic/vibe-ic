from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flow_config import build_config, resolve_rtl_inputs, write_config


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


def test_generated_lowercase_pdk_keeps_installed_registry_spelling(project):
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    path.write_text(json.dumps({"fields": {"pdk_target": "sky130a"}}))
    assert build_config(project)["PDK"] == "sky130A"


def test_explicit_pdk_does_not_require_rewriting_generated_documents(project):
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    path.write_text(json.dumps({"fields": {}}))
    before = path.read_bytes()
    assert build_config(project, pdk="sky130A")["PDK"] == "sky130A"
    assert path.read_bytes() == before


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
    assert config["PDN_VOFFSET"] == 6.5
    assert config["PDN_HOFFSET"] == 7
    assert config["PDN_SKIPTRIM"] is True
    assert config["PDN_CORE_RING_HWIDTH"] == 2
    assert config["PDN_CORE_RING_VOFFSET"] == 6
    assert config["PDN_CORE_RING_CONNECT_TO_PADS"] is True
    assert Path(config["PDN_CFG"]).read_text() == (
        "source $::env(SCRIPTS_DIR)/openroad/common/pdn_cfg.tcl\n"
        "add_pdn_connect -grid stdcell_grid -layers {pad horizontal}\n")


@pytest.mark.parametrize("route", ["ic", "DIE"])
@pytest.mark.parametrize("ring", [{}, {"widths": [1, 2]}])
def test_ic_pdn_connects_pads_without_optional_registry_layers(project, monkeypatch, route, ring):
    import flow_config

    registry = project / "registry"
    registry.mkdir()
    target = json.loads((project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json")
                        .read_text())["fields"]["pdk_target"]
    (registry / "pdk_registry.json").write_text(json.dumps({"pdks": [{
        "name": target, "pdn_ring": ring}]}))
    monkeypatch.setattr(flow_config, "PROGRAMS", registry)
    config = build_config(project, route=route)
    assert {key: config.get(key) for key in ("PDN_CORE_RING", "PDN_CORE_RING_CONNECT_TO_PADS")} == {
        "PDN_CORE_RING": True, "PDN_CORE_RING_CONNECT_TO_PADS": True}
    assert Path(config["PDN_CFG"]).read_text() == (
        "source $::env(SCRIPTS_DIR)/openroad/common/pdn_cfg.tcl\n")


def test_declared_pdn_construction_overrides_ic_defaults(project):
    declarations(project, [
        {"kind": "flow_setting", "token": "PDN_CORE_RING", "value": "false"},
        {"kind": "flow_setting", "token": "PDN_CORE_RING_CONNECT_TO_PADS", "value": "false"},
    ])
    config = build_config(project, route="ic")
    assert config["PDN_CORE_RING"] is False
    assert config["PDN_CORE_RING_CONNECT_TO_PADS"] is False


@pytest.mark.parametrize("route", [None, "ip", "HARDMACRO"])
def test_non_ic_routes_leave_native_pdn_construction_defaults(project, route):
    config = build_config(project, route=route)
    assert {key for key in ("PDN_CORE_RING", "PDN_CORE_RING_CONNECT_TO_PADS", "PDN_CFG")
            if key in config} == set()


def test_config_cli_output_is_the_config_the_caller_receives(project):
    output = write_config(project, route="HARDMACRO")
    assert json.loads(output.read_text()) == build_config(project, route="HARDMACRO")


def test_cli_records_implementation_choices_and_preserves_source_constraints(project):
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text('{"author_choice": "retained"}')
    command = [sys.executable, str(Path(__file__).parents[1] / "flow_config.py"),
               "--project", str(project), "--route", "ip", "--set", "FP_CORE_UTIL=35",
               "--set", 'CTS_CLK_BUFFERS=["native_buf_2","native_buf_4"]']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    choices = json.loads(declaration.read_text())
    assert choices["author_choice"] == "retained"
    config = json.loads(Path(result.stdout.strip()).read_text())
    assert config["FP_CORE_UTIL"] == 35
    assert config["CTS_CLK_BUFFERS"] == ["native_buf_2", "native_buf_4"]
    assert config["CLOCK_PERIOD"] == 17.5
    assert config["PDK"] == "sky130A"
    declarations(project, [{"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "45"}])
    assert build_config(project, route="ip")["FP_CORE_UTIL"] == 45


@pytest.mark.parametrize("missing_rtl", [False, True])
def test_failed_config_command_preserves_existing_declaration(project, missing_rtl):
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    original = '{"author_choice":"retained"}\n'
    declaration.write_text(original)
    if missing_rtl:
        (project / "phase2/stage1/rtl/unit.v").unlink()
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "flow_config.py"),
        "--project", str(project), "--set", "FP_CORE_UTIL=35", "--output", str(project)],
        capture_output=True, text=True)
    assert result.returncode != 0
    assert declaration.read_text() == original


def test_declared_grid_offsets_override_derived_ring_offsets(project):
    declarations(project, [
        {"kind": "flow_setting", "token": "FP_PDN_VOFFSET", "value": "9"},
        {"kind": "flow_setting", "token": "FP_PDN_HOFFSET", "value": "11"},
    ])
    config = build_config(project, route="ic")
    assert config["PDN_VOFFSET"] == 9
    assert config["PDN_HOFFSET"] == 11


def test_implementation_pdn_widths_reach_native_configuration(project):
    output = project / "plugin_output"
    output.mkdir()
    (output / "declaration.json").write_text(json.dumps({
        "PDN_VWIDTH": 3.2, "PDN_HWIDTH": 3.2,
    }))
    config = build_config(project, route="ic")
    assert config["PDN_VWIDTH"] == 3.2
    assert config["PDN_HWIDTH"] == 3.2
    assert "PDN_VPITCH" not in config
    assert config["CLOCK_PERIOD"] == 17.5


@pytest.mark.parametrize(("key", "value"), [
    ("PDN_VWIDTH", 2.4), ("RUN_POST_GRT_DESIGN_REPAIR", True),
])
def test_cli_records_supported_implementation_choice(project, key, value):
    output = project / "config.json"
    result = subprocess.run([
        sys.executable, str(Path(__file__).resolve().parents[1] / "flow_config.py"),
        "--project", str(project), "--set", f"{key}={json.dumps(value)}", "--output", str(output),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())[key] == value
    assert json.loads((project / "plugin_output/declaration.json").read_text()) == {
        key: value}


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


def test_root_module_precedes_nested_copy_and_needed_nested_module_survives(project):
    rtl = project / "phase2/stage1/rtl"
    nested = rtl / "syn/rtl"
    nested.mkdir(parents=True)
    (nested / "unit.v").write_text("module unit; endmodule\n")
    leaf = nested / "leaf.v"
    leaf.write_text("module leaf; endmodule\n")
    files, top = resolve_rtl_inputs(project)
    assert top == "unit"
    assert files == [rtl / "unit.v", leaf]
    assert not (project / "work").exists()
    assert build_config(project)["VERILOG_FILES"] == [str(path) for path in files]


def test_nested_file_with_overlapping_and_unique_modules_is_not_silently_dropped(project):
    rtl = project / "phase2/stage1/rtl"
    nested = rtl / "syn"
    nested.mkdir()
    mixed = nested / "mixed.v"
    mixed.write_text("module unit; endmodule\nmodule leaf; endmodule\n")
    files, _ = resolve_rtl_inputs(project)
    assert mixed in files


def test_shared_input_resolver_recovers_declared_top_without_config_side_effects(project):
    (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        '{"top_module":"missing"}')
    (project / "input").mkdir()
    (project / "input/phase1_prompt.md").write_text("- Top module: `unit`.\n")
    files, top = resolve_rtl_inputs(project)
    assert top == "unit"
    assert files == [project / "phase2/stage1/rtl/unit.v"]
    assert not (project / "work").exists()
