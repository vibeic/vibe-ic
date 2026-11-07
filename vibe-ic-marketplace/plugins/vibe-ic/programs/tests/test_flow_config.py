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


@pytest.mark.parametrize("cap,slew,expected_cap,expected_slew", [
    (None, None, ".2", "3"),
    (".1", "1", ".1", "1"),
    (".5", "5", ".2", "3"),
    (".1", None, ".1", "3"),
    ("0", None, ".2", "3"),
    (None, "0", ".2", "3"),
    ("0", "0", ".2", "3"),
    ("-.1", None, "-.1", "3"),
    (None, "-1", ".2", "-1"),
])
def test_native_cts_characterization_respects_core_limits(cap, slew, expected_cap, expected_slew):
    pytest.importorskip("librelane")
    from librelane.config import Config
    from flow_config import native_defaults

    config = Config({"MAX_CAPACITANCE_CONSTRAINT": Decimal(".2"),
                     "MAX_TRANSITION_CONSTRAINT": Decimal("3"),
                     "CTS_MAX_CAP": Decimal(cap) if cap else None,
                     "CTS_MAX_SLEW": Decimal(slew) if slew else None})
    result = native_defaults(config)
    assert result["CTS_MAX_CAP"] == Decimal(expected_cap)
    assert result["CTS_MAX_SLEW"] == Decimal(expected_slew)
    assert native_defaults(result)["CTS_MAX_CAP"] == result["CTS_MAX_CAP"]
    assert config["CTS_MAX_CAP"] == (Decimal(cap) if cap else None)


@pytest.mark.parametrize("core_cap,core_slew,cap,slew", [
    (".2", None, None, None),
    (None, "3", "0", None),
    (".2", None, None, "0"),
    (None, None, "0", "0"),
])
def test_native_cts_characterization_does_not_invent_a_missing_axis(core_cap, core_slew, cap, slew):
    pytest.importorskip("librelane")
    from librelane.config import Config
    from flow_config import native_defaults

    config = Config({"MAX_CAPACITANCE_CONSTRAINT": Decimal(core_cap) if core_cap else None,
                     "MAX_TRANSITION_CONSTRAINT": Decimal(core_slew) if core_slew else None,
                     "CTS_MAX_CAP": Decimal(cap) if cap else None,
                     "CTS_MAX_SLEW": Decimal(slew) if slew else None})
    result = native_defaults(config)
    assert result["CTS_MAX_CAP"] == config["CTS_MAX_CAP"]
    assert result["CTS_MAX_SLEW"] == config["CTS_MAX_SLEW"]


@pytest.mark.parametrize("core_cap,core_slew", [("0", "3"), (".2", "0"), ("0", "0")])
def test_native_cts_characterization_preserves_zero_engineering_limits(core_cap, core_slew):
    pytest.importorskip("librelane")
    from librelane.config import Config
    from flow_config import native_defaults

    config = Config({"MAX_CAPACITANCE_CONSTRAINT": Decimal(core_cap),
                     "MAX_TRANSITION_CONSTRAINT": Decimal(core_slew),
                     "CTS_MAX_CAP": None, "CTS_MAX_SLEW": None})
    result = native_defaults(config)
    assert result["CTS_MAX_CAP"] == Decimal(core_cap)
    assert result["CTS_MAX_SLEW"] == Decimal(core_slew)


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


def test_plain_native_overrides_apply_to_all_steps_after_platform_defaults(tmp_path):
    pytest.importorskip("librelane")
    from librelane.config import Config
    from flow_config import native_defaults

    override = {"EXTRA_EXCLUDED_CELLS": ["custom*", "*dly*", "*delay*"]}
    path = tmp_path / "work/flow/native_overrides.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(override))
    config = Config({"PDK": "gf180mcuD", "DESIGN_DIR": str(tmp_path)})

    resolved = native_defaults(config)

    assert resolved["EXTRA_EXCLUDED_CELLS"] == override["EXTRA_EXCLUDED_CELLS"]
    assert "*_1" not in resolved["EXTRA_EXCLUDED_CELLS"]
    assert native_defaults(resolved)["EXTRA_EXCLUDED_CELLS"] == resolved["EXTRA_EXCLUDED_CELLS"]


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


def test_plain_native_overrides_reach_native_configuration(project):
    path = project / "work/flow/native_overrides.json"
    path.parent.mkdir(parents=True)
    value = {"EXTRA_EXCLUDED_CELLS": ["custom*"]}
    path.write_text(json.dumps(value))
    assert build_config(project)["EXTRA_EXCLUDED_CELLS"] == value["EXTRA_EXCLUDED_CELLS"]


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


def test_open_l9_top_is_recorded_from_single_authored_rtl_top(project):
    l9_path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text())
    l9["top_module"] = None
    l9_path.write_text(json.dumps(l9))

    try:
        files, top, _ = resolve_rtl_inputs(project)
    except FileNotFoundError as exc:
        files, top = [], str(exc)

    assert top == "unit"
    assert [path.name for path in files] == ["unit.v"]
    recorded = json.loads(l9_path.read_text())
    assert recorded["top_module"] == "unit"
    assert recorded["top_module_source"] == {
        "step": "RTL authoring",
        "artifact": "phase2/stage1/rtl",
        "method": "yosys hierarchy -auto-top",
    }


def test_open_l9_top_refuses_multiple_authored_rtl_roots(project):
    l9_path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9 = json.loads(l9_path.read_text())
    l9["top_module"] = None
    l9_path.write_text(json.dumps(l9))
    rtl = project / "phase2/stage1/rtl/unit.v"
    rtl.write_text("module alpha(input a); endmodule\nmodule beta(input b); endmodule\n")

    try:
        resolve_rtl_inputs(project)
    except FileNotFoundError as exc:
        detail = str(exc)
    else:
        detail = "top was selected"

    assert detail == ("RTL authored at step 17 has ambiguous candidate top modules: "
                     "alpha, beta")
    assert json.loads(l9_path.read_text())["top_module"] is None


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


def test_cli_explicit_clock_survives_a_conditional_virtual_clock(project, monkeypatch):
    import flow_config

    sdc = project / "conditional.sdc"
    sdc.write_text('''if {[info exists ::env(CLOCK_PORT)] && $::env(CLOCK_PORT) ne ""} {
  set clk_input $::env(CLOCK_PORT)
  create_clock -name real -period 17.5 [get_ports $clk_input]
} else {
  set clk_input __VIRTUAL_CLK__
  create_clock -name virtual -period 17.5
}
''')
    output = project / "native.json"
    monkeypatch.setattr(sys, "argv", ["flow_config.py", "--project", str(project),
        "--route", "ip", "--set", 'CLOCK_PORT="clk"', "--set", f"PNR_SDC_FILE={json.dumps(str(sdc))}",
        "--output", str(output)])
    assert flow_config.main() == 0
    config = json.loads(output.read_text())
    assert config["CLOCK_PORT"] == "clk"
    assert config["CLOCK_PERIOD"] == 17.5
    assert config["PNR_SDC_FILE"] == str(sdc)


def test_generated_lowercase_pdk_keeps_installed_registry_spelling(project):
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    path.write_text(json.dumps({"fields": {"pdk_target": "sky130a"}}))
    assert build_config(project)["PDK"] == "sky130A"


@pytest.mark.parametrize(("declared", "installed"), [
    ("sky130", "sky130A"), ("SKY130", "sky130A"),
    ("gf180mcu", "gf180mcuD"), ("ihpsg13g2", "ihpsg13g2"),
    ("sky130A-r2", "sky130A-r2"), ("gf180mcuD-r2", "gf180mcuD-r2"),
    ("sky130B", "sky130B"), ("custom_process", "custom_process"),
])
def test_generated_pdk_family_reaches_registered_distribution(project, declared, installed):
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    path.write_text(json.dumps({"fields": {"pdk_target": declared, "constraint_declarations": [
        {"kind": "flow_setting", "token": "MAX_FANOUT_CONSTRAINT", "value": 4, "scope": declared},
    ]}}))
    before = path.read_bytes()
    config = build_config(project)
    assert config["PDK"] == installed
    assert config["CLOCK_PERIOD"] == 17.5
    assert config["MAX_FANOUT_CONSTRAINT"] == 4
    assert path.read_bytes() == before


def test_family_scoped_clock_survives_native_distribution_selection(project):
    docs = project / "phase1/generated_docs"
    (docs / "L19_CONSTRAINTS_PDK.json").write_text('{"fields":{"pdk_target":"sky130"}}')
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"domain_kind": "primary", "source_pin": "clk", "period_ns": 17.5,
         "pdk_scoped_target": "sky130"},
        {"domain_kind": "primary", "source_pin": "foreign_clk", "period_ns": 24,
         "pdk_scoped_target": "gf180mcu"},
    ]}))
    config = build_config(project)
    assert config["PDK"] == "sky130A"
    assert config["CLOCK_PORT"] == "clk"
    assert config["CLOCK_PERIOD"] == 17.5


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
        {"kind": "flow_setting", "token": "SYNTH_STRATEGY", "value": "DELAY 4"},
        {"kind": "flow_setting", "token": "SYNTH_STRATEGY", "value": None},
        {"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "55", "scope": "other*"},
    ])
    config = build_config(project)
    assert config["FP_CORE_UTIL"] == 20
    assert config["PL_TARGET_DENSITY_PCT"] == 25
    assert config["MAX_FANOUT_CONSTRAINT"] == 8
    assert config["SYNTH_STRATEGY"] == "DELAY 4"
    assert "CTS_SINK_CLUSTERING_SIZE" not in config


def test_conflicting_limits_are_not_silently_selected(project):
    declarations(project, [
        {"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "20"},
        {"kind": "flow_setting", "token": "FP_CORE_UTIL", "value": "30"},
    ])
    with pytest.raises(ValueError, match="Conflicting L19"):
        build_config(project)


@pytest.mark.parametrize("feasible", [False, True])
def test_strategy_selection_rejects_smaller_area_with_failed_timing(tmp_path, monkeypatch, feasible):
    pytest.importorskip("librelane")
    from types import SimpleNamespace
    from librelane.flows import Flow
    from flow_config import explore_synthesis

    directory = tmp_path / "exploration"
    steps = [SimpleNamespace(id="sta-" + strategy, state_out=SimpleNamespace(metrics={
        "design__instance__area": area, "timing__setup__ws": slack, "timing__setup__tns": min(slack, 0)}))
        for strategy, area, slack in (("AREA 0", 1, -1), ("DELAY 0", 2, 0 if feasible else -1))]
    flow = SimpleNamespace(step_objects=steps, start=lambda **kwargs: None)
    monkeypatch.setattr(Flow.factory, "get", lambda name: lambda config: flow)

    assert explore_synthesis({"CLOCK_PERIOD": 10}, None, directory) == ("DELAY 0" if feasible else None)
    report = json.loads((directory / "selection.json").read_text())
    assert report["strategy"] == ("DELAY 0" if feasible else None)
    assert ("Minimum area" if feasible else "No timing-feasible strategy") in report["detail"]


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
    ("SYNTH_STRATEGY", "DELAY 4"),
    ("PDN_VWIDTH", 2.4), ("RUN_POST_GRT_DESIGN_REPAIR", True),
    ("GRT_DESIGN_REPAIR_MAX_CAP_PCT", 30), ("GRT_DESIGN_REPAIR_MAX_SLEW_PCT", 30),
    ("EXTRA_EXCLUDED_CELLS", ["delay_weak*"]),
    ("DECAP_CELLS", []), ("DECAP_CELLS", ["native_decap*"]),
    ("CLOCK_PORT", "clock_i"), ("CLOCK_PORT", ["clock_i", "aux_clock_i"]),
    ("FP_DEF_TEMPLATE", "frame.def"), ("FALLBACK_SDC", "fallback.sdc"),
    ("PNR_SDC_FILE", "pnr.sdc"), ("SIGNOFF_SDC_FILE", "signoff.sdc"),
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


def test_original_prompt_recovers_lost_pdk_with_authored_top(project):
    (project / "input").mkdir()
    (project / "input/phase1_prompt.md").write_text(
        "Implement on sky130A.\n- Top module: `not_the_authored_top`.\n")
    docs = project / "phase1/generated_docs"
    (docs / "L9_INTEGRATION_SPEC.json").write_text('{"top_module": "unit"}')
    (docs / "L19_CONSTRAINTS_PDK.json").write_text('{"fields":{"pdk_target":null}}')
    config = build_config(project)
    assert config["PDK"] == "sky130A"
    assert config["DESIGN_NAME"] == "unit"
    assert config["CLOCK_PERIOD"] == 17.5
    assert json.loads((project / "work/flow/config_sources.json").read_text())["sources"] == {
        "PDK": "input/phase1_prompt.md"}


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


def test_missing_declared_top_is_not_replaced_by_prompt_prose_or_an_unrelated_module(project):
    (project / "input").mkdir()
    (project / "input/phase1_prompt.md").write_text("- Top module: `unit`.\n")
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
    files, top, _ = resolve_rtl_inputs(project)
    assert top == "unit"
    assert files == [rtl / "unit.v", leaf]
    assert not (project / "work").exists()
    assert build_config(project)["VERILOG_FILES"] == [str(path) for path in files]


def test_resolve_rtl_inputs_treats_null_optional_ldoc_fields_as_absent(project):
    docs = project / "phase1/generated_docs"
    (docs / "L1_DATASHEET.json").write_text('{"tapeout_metadata": null}')
    (docs / "L9_INTEGRATION_SPEC.json").write_text('{"top_module": null}')
    (project / "input").mkdir()
    (project / "input/phase1_prompt.md").write_text("- Top module: `unit`.\n")

    files, top, _ = resolve_rtl_inputs(project)

    assert files == [project / "phase2/stage1/rtl/unit.v"]
    assert top == "unit"


def test_nested_file_with_overlapping_and_unique_modules_is_not_silently_dropped(project):
    rtl = project / "phase2/stage1/rtl"
    nested = rtl / "syn"
    nested.mkdir()
    mixed = nested / "mixed.v"
    mixed.write_text("module unit; endmodule\nmodule leaf; endmodule\n")
    files, _, _ = resolve_rtl_inputs(project)
    assert mixed in files


def test_shared_input_resolver_uses_authored_top_without_config_side_effects(project):
    l9_path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    l9_path.write_text('{"top_module":null}')
    (project / "input").mkdir()
    (project / "input/phase1_prompt.md").write_text(
        "- Top module: `not_the_authored_top`.\n")
    files, top, _ = resolve_rtl_inputs(project)
    assert top == "unit"
    assert files == [project / "phase2/stage1/rtl/unit.v"]
    assert json.loads(l9_path.read_text())["top_module_source"]["step"] == "RTL authoring"
    assert not (project / "work").exists()


def test_explicit_pdn_actuator_overrides_documentary_starting_geometry(project):
    docs = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    docs.write_text(json.dumps({"fields": {"pdk_target": "sky130A", "constraint_declarations": [
        {"kind": "flow_setting", "token": "PDN_VPITCH", "value": "160"}]}}))
    declaration = project / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({"PDN_VPITCH": 80}))
    assert build_config(project, route="ip")["PDN_VPITCH"] == 80


def test_native_config_does_not_reuse_an_existing_power_estimate(project, monkeypatch):
    from flow_config import build_native_config
    import flow_pdn_current
    def unexpected(*args, **kwargs):
        raise AssertionError("PDN sizing belongs at floorplan, after current native timing")
    monkeypatch.setattr(flow_pdn_current, "current_settings", unexpected)
    power = project / "steps/pre_layout_timing/result.json"
    power.parent.mkdir(parents=True)
    power.write_text("{}")
    assert build_native_config(project, route="ip")["PDK"] == build_config(project, route="ip")["PDK"]


@pytest.mark.parametrize("vertical,horizontal,legal", [(76.8, 76.59, True), (76.801, 76.59, False)])
def test_native_pdn_actuator_roundtrip_keeps_decimal_grid_exact(project, monkeypatch, vertical, horizontal, legal):
    pytest.importorskip("librelane")
    pytest.importorskip("odb")
    from librelane.flows import Flow
    import flow_config
    (project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": "gf180mcuD"}}))
    power = project / "steps/pre_layout_timing/result.json"
    power.parent.mkdir(parents=True)
    power.write_text("{}")
    monkeypatch.setattr(sys, "argv", ["flow_config.py", "--project", str(project), "--route", "ip",
        "--set", f"PDN_VPITCH={vertical}", "--set", f"PDN_HPITCH={horizontal}"])
    assert flow_config.main() == 0
    if not legal:
        with pytest.raises(ValueError, match="manufacturing grid"):
            from flow_pdn_current import current_settings
            config = flow_config.build_native_config(project, route="ip")
            owner = Flow.factory.get("Classic")(config, design_dir=str(project))
            current_settings(project, owner.config.to_raw_dict())
        return
    native = flow_config.build_native_config(project, route="ip")
    owner = Flow.factory.get("Classic")(native, design_dir=str(project))
    assert owner.config["PDN_VPITCH"] == Decimal(str(vertical))
    assert owner.config["PDN_HPITCH"] == Decimal(str(horizontal))


@pytest.mark.parametrize("override", [None, 8])
def test_scalar_native_clock_target_uses_the_fastest_declared_clock(project, override):
    (project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"domain_kind": "primary", "source_pin": "slow_clock", "period_ns": 50},
        {"domain_kind": "primary", "source_pin": "clk", "freq_mhz": 50}]}))
    if override is not None:
        path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
        document = json.loads(path.read_text())
        document["fields"]["clock_target"] = {"period_ns": override}
        path.write_text(json.dumps(document))
    config = build_config(project, route="ip")
    assert config["CLOCK_PORT"] == ["slow_clock", "clk"]
    assert config["CLOCK_PERIOD"] == 20
