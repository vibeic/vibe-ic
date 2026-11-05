from __future__ import annotations

import json
import sys
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flow_config import build_config, declared_power_checks, resolve_rtl_inputs, write_config


def test_native_delay_defaults_preserve_buffers_and_user_exclusions(tmp_path):
    pytest.importorskip("librelane")
    from librelane.common import Toolbox
    from librelane.config import Config
    from flow_config import native_defaults

    cells = ["neutral__dlya_1", "sg13g2_dlygate4sd3_1", "delayx1",
             "neutral__buf_1", "neutral__buf_4"]
    text = "library (neutral) {\n" + "".join(
        f' cell ("{cell}") {{\n  area : 1;\n }}\n' for cell in cells) + "}\n"
    liberty = tmp_path / "neutral.lib"
    liberty.write_text(text)
    config = Config({"DEFAULT_CORNER": "nominal", "LIB": {"nom*": [str(liberty)]},
                     "EXTRA_EXCLUDED_CELLS": ["user_choice*"]})
    toolbox = Toolbox(str(tmp_path / "tool_tmp"))

    updated = native_defaults(config)

    assert updated["EXTRA_EXCLUDED_CELLS"] == ["user_choice*", "*dly*", "*delay*"]
    assert config["EXTRA_EXCLUDED_CELLS"] == ["user_choice*"]
    assert native_defaults(updated)["EXTRA_EXCLUDED_CELLS"] == updated["EXTRA_EXCLUDED_CELLS"]
    filtered, = toolbox.remove_cells_from_lib(
        frozenset([str(liberty)]), frozenset(updated["EXTRA_EXCLUDED_CELLS"]))
    result = Path(filtered).read_text()
    for cell in cells[:3]:
        assert f'cell ("{cell}")' not in result
    for cell in cells[3:]:
        assert f'cell ("{cell}")' in result


@pytest.mark.parametrize("existing", [None, ["*dly*", "user_choice*"]])
def test_native_delay_defaults_need_no_library_scan(existing):
    pytest.importorskip("librelane")
    from librelane.config import Config
    from flow_config import native_defaults

    config = Config({"EXTRA_EXCLUDED_CELLS": existing})

    expected = list(dict.fromkeys([*(existing or []), "*dly*", "*delay*"]))
    assert native_defaults(config)["EXTRA_EXCLUDED_CELLS"] == expected
    assert config["EXTRA_EXCLUDED_CELLS"] == existing


@pytest.mark.parametrize("pdk,gf180", [("gf180mcuD", True), ("GF180MCUA", True),
                                      ("sky130A", False), (None, False)])
def test_native_platform_defaults_exclude_weak_cells_only_for_gf180(tmp_path, pdk, gf180):
    pytest.importorskip("librelane")
    from librelane.common import Toolbox
    from librelane.config import Config
    from flow_config import native_defaults

    weak = ["neutral__buf_1", "neutral__and2_1", "neutral__dff_1"]
    strong = ["neutral__buf_2", "neutral__and2_2", "neutral__dff_2"]
    liberty = tmp_path / "neutral.lib"
    liberty.write_text("library (neutral) {\n" + "".join(
        f' cell ("{cell}") {{\n  area : 1;\n }}\n' for cell in weak + strong) + "}\n")
    config = Config({"PDK": pdk, "EXTRA_EXCLUDED_CELLS": ["user_choice*"]})

    updated = native_defaults(config)

    expected = ["user_choice*", "*dly*", "*delay*", *(["*_1"] if gf180 else [])]
    assert updated["EXTRA_EXCLUDED_CELLS"] == expected
    assert native_defaults(updated)["EXTRA_EXCLUDED_CELLS"] == expected
    assert config["EXTRA_EXCLUDED_CELLS"] == ["user_choice*"]
    filtered, = Toolbox(str(tmp_path / "tool_tmp")).remove_cells_from_lib(
        frozenset([str(liberty)]), frozenset(expected))
    result = Path(filtered).read_text()
    for cell in weak:
        assert (f'cell ("{cell}")' not in result) == gf180
    for cell in strong:
        assert f'cell ("{cell}")' in result


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


def power_document(project, text):
    path = project / "input/docs/verification_plan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_power_baseline_and_scoped_limit_follow_actual_run_conditions(project):
    power_document(project, "## Quality metrics\n"
                   "> `sky130A` / `sky130_fd_sc_hd` / TT corner / 10 ns\n"
                   "### Measured baseline\n| total power | **1.31 mW** |\n"
                   "### Acceptance range\n| total power(TT) | <= 1.70 mW | sign-off |\n")
    config = {"PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd", "CLOCK_PERIOD": 10,
              "STA_CORNERS": ["nom_tt_025C_1v80"]}
    metrics = {"power__total__corner:nom_tt_025C_1v80": 0.0017}
    baseline, check = declared_power_checks(project, config=config, metrics=metrics)
    assert baseline["applicable"] is False
    assert baseline["limit"] == {}
    assert baseline["value"] == [Decimal("0.00131")]
    assert "no comparator" in baseline["reason"]
    assert check.get("applicable", True)
    assert check["limit"] == {"max": Decimal("0.00170")}
    assert check["source"]["line"] == 6
    assert check["source"]["text"] == "| total power(TT) | <= 1.70 mW | sign-off |"
    for changed in ({"PDK": "gf180mcuD"}, {"STD_CELL_LIBRARY": "other_cells"},
                    {"CLOCK_PERIOD": 24}, {"STA_CORNERS": ["nom_ff_025C_1v80"]}):
        mismatch_metrics = {} if "STA_CORNERS" in changed else metrics
        unmatched = declared_power_checks(project, config={**config, **changed}, metrics=mismatch_metrics)
        assert all(entry["applicable"] is False for entry in unmatched)
        assert "conditions" in unmatched[-1]["reason"]
    assert all(entry["applicable"] is False for entry in declared_power_checks(project))


@pytest.mark.parametrize("bound", ["41.6 mW", "41600 uW", "0.0416 W"])
def test_matching_strict_power_ceiling_preserves_decimal_equality(project, bound):
    power_document(project, f"Total power (including core power and pads) < {bound} at TT.\n")
    check, = declared_power_checks(project, metrics={"power__total__corner:nom_tt_025C_1v80": 0.0416})
    assert check.get("applicable", True)
    assert check["metric"] == "power__total__corner:*tt*"
    assert check["limit"] == {"max": Decimal("0.0416"), "max_exclusive": True}
    assert not Decimal(str(0.0416)) < check["limit"]["max"]
    assert "die pads" in check["scope"]


@pytest.mark.parametrize("text", ["Total power target < TBD mW.\n", "Total power target < 5.\n",
                                 "Total power < 5 mW, informational only.\n", "Core-only total power < 5 mW.\n",
                                 "Per-rail power budget < 5 mW.\n", "Total power target (core scope unclear) < 5 mW.\n"])
def test_unparsed_or_informational_power_text_is_not_a_check(project, text):
    power_document(project, text)
    assert declared_power_checks(project) == []


def test_structured_budget_is_preferred_and_retains_exact_literal_and_scope(project):
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    path.write_text('{"fields":{"power_budget_mw":{"max":41.60000000000000000000000000001,'
                    '"max_exclusive":true,"corner":"TT"},"pdk_target":"sky130A",'
                    '"clock_target":{"period_ns":10},"scope":"total netlist including core and pads"}}')
    power_document(project, "Total power < 1 mW.\n")
    check, = declared_power_checks(project, config={"PDK": "sky130A", "CLOCK_PERIOD": 10,
                                                   "STA_CORNERS": ["nom_tt_025C_1v80"]})
    assert check.get("applicable", True)
    assert check["limit"] == {"max": Decimal("0.04160000000000000000000000000001"), "max_exclusive": True}
    assert check["source"]["file"] == "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    assert check["source"]["field"] == "fields.power_budget_mw"
    assert check["source"]["bound"]["max"] == Decimal("41.60000000000000000000000000001")
    unmatched, = declared_power_checks(project, config={"PDK": "gf180mcuD", "CLOCK_PERIOD": 24,
                                                       "STA_CORNERS": ["nom_tt_025C_5v00"]})
    assert unmatched["applicable"] is False
    assert "PDK" in unmatched["reason"] and "CLOCK_PERIOD" in unmatched["reason"]


def test_power_reader_uses_original_prompt_without_tools_or_artifact_writes(project, monkeypatch):
    path = project / "input/phase1_prompt.md"
    path.parent.mkdir()
    path.write_text("Total power must be under 5 mW.\n")
    ignored = project / "input/flow109/requirements.json"
    ignored.parent.mkdir()
    ignored.write_text('{"power_budget_mw":1}')
    before = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    def unexpected_tool(*args, **kwargs):
        pytest.fail("The declared-power reader invoked a tool")
    monkeypatch.setattr(subprocess, "run", unexpected_tool)
    check, = declared_power_checks(project)
    assert check["limit"] == {"max": Decimal("0.005"), "max_exclusive": True}
    assert check["source"]["file"] == "input/phase1_prompt.md"
    after = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    assert after == before


def test_config_uses_documents_and_leaves_pdk_defaults(project):
    config = build_config(project, route="ip")
    assert config["DESIGN_NAME"] == "unit"
    assert config["CLOCK_PORT"] == "clk"
    assert config["CLOCK_PERIOD"] == 17.5
    assert config["PDK"] == "sky130A"
    assert config["VERILOG_FILES"] == [str(project / "phase2/stage1/rtl/unit.v")]
    assert "PDN_CFG" not in config
    assert "FP_CORE_UTIL" not in config


def test_authored_integration_top_and_sdc_reach_native_config(project):
    rtl = project / "phase2/stage1/rtl"
    (rtl / "wrapper.sv").write_text(
        "module wrapper(input clk, aux_clk, output q); unit u(.clk(clk),.q(q)); endmodule\n")
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({"top_module": "wrapper"}))
    sdc = project / "phase3/stage3/pnr/constraint.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text("create_clock -name main -period 12 [get_ports clk]\n"
                   "create_clock -name aux -period 24 [get_ports aux_clk]\n")
    config = build_config(project, route="ip")
    assert config["DESIGN_NAME"] == "wrapper"
    assert config["CLOCK_PORT"] == ["clk", "aux_clk"]
    assert config["CLOCK_PERIOD"] == 12
    for key in ("FALLBACK_SDC", "PNR_SDC_FILE", "SIGNOFF_SDC_FILE"):
        assert config[key] == str(sdc)


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


def test_cli_unsets_one_implementation_choice_and_keeps_the_others(project):
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({
        "PDN_VWIDTH": 2.4, "RUN_POST_GRT_DESIGN_REPAIR": True,
        "author_choice": "retained"}))
    command = [sys.executable, str(Path(__file__).parents[1] / "flow_config.py"),
               "--project", str(project), "--unset", "PDN_VWIDTH"]
    for _ in range(2):
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        config = json.loads(Path(result.stdout.strip()).read_text())
        assert "PDN_VWIDTH" not in config
        assert config["RUN_POST_GRT_DESIGN_REPAIR"] is True
        assert config["CLOCK_PERIOD"] == 17.5
        assert json.loads(declaration.read_text()) == {
            "RUN_POST_GRT_DESIGN_REPAIR": True, "author_choice": "retained"}


@pytest.mark.parametrize("missing_rtl", [False, True])
@pytest.mark.parametrize("unset", [False, True])
def test_failed_config_command_preserves_existing_declaration(project, missing_rtl, unset):
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    original = '{"author_choice":"retained","FP_CORE_UTIL":25}\n'
    declaration.write_text(original)
    if missing_rtl:
        (project / "phase2/stage1/rtl/unit.v").unlink()
    settings = ["--unset", "FP_CORE_UTIL"] if unset else ["--set", "FP_CORE_UTIL=35"]
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "flow_config.py"),
        "--project", str(project), *settings,
        "--output", str(project)],
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
    ("GRT_DESIGN_REPAIR_MAX_CAP_PCT", 30), ("GRT_DESIGN_REPAIR_MAX_SLEW_PCT", 30),
    ("EXTRA_EXCLUDED_CELLS", ["delay_weak*"]),
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


def test_explicit_pdn_actuator_overrides_documentary_starting_geometry(project):
    docs = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    docs.write_text(json.dumps({"fields": {"pdk_target": "sky130A", "constraint_declarations": [
        {"kind": "flow_setting", "token": "PDN_VPITCH", "value": "160"}]}}))
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({"PDN_VPITCH": 80}))
    assert build_config(project, route="ip")["PDN_VPITCH"] == 80


def test_hardmacro_sizes_native_defaults_after_current_estimate(project, monkeypatch):
    from flow_config import build_native_config
    import flow_pdn_current
    import types
    seen = []
    native = {"PDN_CFG": None, "PDN_RAIL_WIDTH": .6}
    class Classic:
        def __init__(self, config, **kwargs):
            self.config = types.SimpleNamespace(to_raw_dict=lambda: native)
    flows = types.ModuleType("librelane.flows")
    flows.Flow = types.SimpleNamespace(factory=types.SimpleNamespace(get=lambda kind: Classic))
    monkeypatch.setitem(sys.modules, "librelane.flows", flows)
    monkeypatch.setattr(flow_pdn_current, "current_settings", lambda root, config, parallel_length_um:
        seen.append((root, config, parallel_length_um)) or {"PDN_VWIDTH": 2.4})
    power = project / "steps/pre_layout_timing/result.json"
    power.parent.mkdir(parents=True)
    power.write_text("{}")
    result = build_native_config(project, route="ip")
    assert result["PDN_VWIDTH"] == 2.4
    assert "PDN_RAIL_WIDTH" not in result
    assert seen == [(project.resolve(), native, None)]
