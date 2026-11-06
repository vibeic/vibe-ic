"""Chip preparation uses elaborated interfaces and native library geometry."""
import json
import os
from pathlib import Path

import pytest

import flow_chip_inputs as chip


@pytest.fixture
def native_inputs(tmp_path):
    pytest.importorskip("librelane")
    pdk_root = os.environ.get("PDK_ROOT")
    if not pdk_root or not (Path(pdk_root) / "sky130A").is_dir():
        pytest.skip("native Chip preparation requires the installed sky130A PDK")
    rtl = _write(tmp_path / "broken.v", "module unit(input clk); invalid syntax; endmodule\n")
    return {"DESIGN_NAME": "unit", "PDK": "sky130A", "VERILOG_FILES": [str(rtl)],
            "CLOCK_PORT": "clk", "CLOCK_PERIOD": 10, "SYNTH_STRATEGY": "AREA 0"}


def test_native_sizing_reports_failed_yosys_run_to_observer(tmp_path, native_inputs):
    from librelane.steps import StepError

    runs = []
    cwd = Path.cwd()

    with pytest.raises(StepError) as caught:
        chip.prepare(tmp_path, native_inputs, on_tool_run=runs.append)

    assert Path.cwd() == cwd
    assert len(runs) == 1
    run = runs[0]
    assert run["name"] == "Yosys.JsonHeader"
    assert run["ran"] is True
    assert run["status"] == "FAIL"
    assert run["exit_code"] == caught.value.underlying_error.returncode
    assert run["exit_code"] != 0
    assert run["tool_seconds"] > 0
    assert Path(run["reports"]).is_dir()
    assert any(Path(run["reports"]).glob("*.log"))
    sizing = json.loads((tmp_path / "work/flow/chip/sizing.json").read_text())
    assert sizing == {"runs": [{"name": run["name"], "tool_seconds": run["tool_seconds"]}],
                      "top": "unit", "state_out": str(Path(run["reports"]).parent / "yosys_synthesis/state_out.json"),
                      "tool_seconds": run["tool_seconds"]}


def test_native_sizing_records_the_core_state_for_activity(tmp_path, native_inputs):
    Path(native_inputs["VERILOG_FILES"][0]).write_text(
        "module unit(input clk, output reg q); always @(posedge clk) q <= ~q; endmodule\n")
    destination = tmp_path / "sizing"
    destination.mkdir()

    chip._native_core(tmp_path, native_inputs, destination)

    sizing = json.loads((destination / "sizing.json").read_text())
    state = json.loads(Path(sizing["state_out"]).read_text())
    assert sizing["top"] == "unit"
    assert Path(state["nl"]).is_file()


def test_native_chip_pdn_connects_both_supplies_from_pad_access_layers(
        tmp_path, native_inputs, monkeypatch):
    from flow_config import _chip_pdn
    from librelane.flows import Flow

    monkeypatch.chdir(tmp_path)
    Path(native_inputs["VERILOG_FILES"][0]).write_text(
        "module unit(input clk, input [3:0] data, output reg q);\n"
        "always @(posedge clk) q <= data[3]; endmodule\n")
    config = {**native_inputs, **_chip_pdn(tmp_path, native_inputs["PDK"])}
    prepared = chip.prepare(tmp_path, config)
    owner = Flow.factory.get("Chip")(prepared, design_dir=str(tmp_path),
                                     pdk_root=os.environ["PDK_ROOT"])
    state = owner.start(frm="Yosys.JsonHeader", to="OpenROAD.GeneratePDN",
                        _force_run_dir=str(tmp_path / "native"))
    for net in prepared["VDD_NETS"] + prepared["GND_NETS"]:
        assert state.metrics[f"design__power_grid_violation__count__net:{net}"] == 0


def test_core_sizing_uses_configured_or_native_default_strategy_once(tmp_path, native_inputs):
    Path(native_inputs["VERILOG_FILES"][0]).write_text(
        "module unit(input clk, reset_n, output reg [15:0] q);\n"
        "always @(posedge clk) if (!reset_n) q <= 0; else q <= q + 1; endmodule\n")
    native_inputs["CLOCK_PERIOD"] = 20
    baseline, automatic = tmp_path / "baseline", tmp_path / "automatic"
    baseline.mkdir()
    automatic.mkdir()
    _, _, original_area, _ = chip._native_core(tmp_path, native_inputs, baseline)
    config = {key: value for key, value in native_inputs.items() if key != "SYNTH_STRATEGY"}

    cwd = Path.cwd()
    native, _, area, runs = chip._native_core(tmp_path, config, automatic)

    assert Path.cwd() == cwd
    assert area == original_area
    assert native["SYNTH_STRATEGY"] == native_inputs["SYNTH_STRATEGY"]
    assert native["CLOCK_PERIOD"] == 20
    assert [run["name"] for run in runs] == [
        "Yosys.JsonHeader", "Yosys.Synthesis", "OpenROAD.ReportDesignArea"]
    assert not list(automatic.glob("core_*/synthesis_exploration"))
    assert not list(baseline.glob("core_*/synthesis_exploration"))


@pytest.mark.parametrize("failure", [None, "missing_input", "tool_failure"])
def test_native_sizing_observer_keeps_completed_runs_on_later_failure(
        tmp_path, native_inputs, monkeypatch, failure):
    import subprocess
    from librelane.state import DesignFormat, State
    from librelane.steps import Step, StepError, StepException

    header = _write(tmp_path / "header.json", json.dumps({"modules": {"unit": {"ports": {}}}}))
    error = (StepException("missing required input") if failure == "missing_input" else
             StepError("native tool failed", underlying_error=subprocess.CalledProcessError(7, "yosys")))

    def start(self, **kwargs):
        if self.id == "Yosys.Synthesis" and failure:
            raise error
        if self.id == "OpenROAD.Floorplan":
            (Path(kwargs["step_dir"]) / "or_metrics_out.json").write_text(
                json.dumps({"design__instance__area": 1}))
        return State({DesignFormat.JSON_HEADER: str(header)},
                     metrics={"design__instance__area": 1})

    monkeypatch.setattr(Step, "start", start)
    destination = tmp_path / "sizing"
    destination.mkdir()
    runs = []
    cwd = Path.cwd()
    if failure:
        with pytest.raises(type(error)) as caught:
            chip._native_core(tmp_path, native_inputs, destination, on_tool_run=runs.append)
        assert caught.value is error
    else:
        _, ports, area, sizing_runs = chip._native_core(
            tmp_path, native_inputs, destination, on_tool_run=runs.append)
        assert ports == []
        assert area == 1
        assert sizing_runs == [{"name": run["name"], "tool_seconds": run["tool_seconds"]}
                               for run in runs]

    assert Path.cwd() == cwd
    assert [run["name"] for run in runs] == ["Yosys.JsonHeader", "Yosys.Synthesis"] + (
        ["OpenROAD.ReportDesignArea"] if failure is None else [])
    assert runs[0]["status"] == "PASS"
    assert runs[0]["exit_code"] == 0
    assert runs[0]["ran"] is True
    assert runs[1]["status"] == {None: "PASS", "missing_input": "NOT_MEASURED",
                                  "tool_failure": "FAIL"}[failure]
    assert runs[1]["exit_code"] == {None: 0, "missing_input": None, "tool_failure": 7}[failure]
    assert runs[1]["ran"] is (failure != "missing_input")


def test_missing_native_area_does_not_reuse_a_yosys_number(tmp_path, native_inputs, monkeypatch):
    from librelane.common import Toolbox
    from librelane.flows import Flow
    from librelane.state import State
    from librelane.steps import Step

    owner = Flow.factory.get("Classic")(native_inputs, design_dir=str(tmp_path),
        pdk_root=os.environ["PDK_ROOT"])
    stale = State(metrics={"design__instance__area": 999})
    def no_area(self, **kwargs):
        (Path(kwargs["step_dir"]) / "or_metrics_out.json").write_text("{}")
        return stale
    monkeypatch.setattr(Step, "start", no_area)
    assert chip.netlist_area(owner.config, stale, Toolbox(str(tmp_path / "tools")), tmp_path / "area") is None


def test_native_pathlike_config_values_are_single_paths():
    class NativePath(os.PathLike):
        def __fspath__(self):
            return "/native/technology.lef"

        def __str__(self):
            return self.__fspath__()

    assert chip._paths({"nominal": NativePath()}) == [Path("/native/technology.lef")]


@pytest.fixture
def receiver_ring(tmp_path, monkeypatch):
    rails = {"CORE": ("POWER", 1.8), "RETURN": ("GROUND", 0),
             "QUIET": ("POWER", 1.8), "IO": ("POWER", 3.3)}
    feeds = {f"neutral__{rail.lower()}_feed": (f"BOND_{rail}", rail)
             for rail in ("CORE", "RETURN", "IO")}
    receiver, bridge = "neutral__receiver", "neutral__quiet_bridge"
    classes = {master: "PAD POWER" for master in feeds}
    classes.update({receiver: "PAD INPUT", bridge: "PAD AREAIO"})
    roles = {master: {rail: ("INOUT", use) for rail, (use, _) in rails.items()}
             for master in classes}
    for master, (bond, rail) in feeds.items():
        roles[master][bond] = ("INOUT", rails[rail][0])
    roles[receiver]["BOND"] = ("INPUT", "SIGNAL")
    lines = ["library (neutral) {"]
    lines += [f' voltage_map ("{rail}", {volts});'
              for rail, (_, volts) in rails.items()]
    for master, (bond, _) in feeds.items():
        lines.append(f" cell ({master}) {{")
        for rail, (use, _) in rails.items():
            lines += [f"  pg_pin ({rail}) {{",
                      f"   pg_type : primary_{use.lower()};",
                      f"   voltage_name : {rail};", "  }"]
        lines += [f"  pin ({bond}) {{", "   direction : inout;",
                  "   is_pad : true;", "  }", " }"]
    lines += [f" cell ({receiver}) {{"]
    for pin, attrs in {
        "BOND": {"direction": "inout", "is_pad": "true",
                 "function": "DRIVER", "three_state": "OE"},
        "DRIVER": {"direction": "input", "related_power_pin": "CORE",
                   "related_ground_pin": "RETURN"},
        "DISABLE": {"direction": "input"}, "OE": {"direction": "input"},
        "IN_CORE": {"direction": "output", "function": "BOND & !DISABLE",
                    "related_power_pin": "QUIET"},
        "IN_IO": {"direction": "output", "function": "BOND & !DISABLE",
                  "related_power_pin": "IO"},
    }.items():
        lines += [f"  pin ({pin}) {{"]
        lines += [f'   {key} : "{value}";' for key, value in attrs.items()]
        lines.append("  }")
    lines += [" }", "}"]
    liberty = _write(tmp_path / "pads.lib", "\n".join(lines))
    core = _write(tmp_path / "core.lib", "library (core) {\n nom_voltage : 1.8;\n}\n")
    spice = _write(tmp_path / "pads.spice", "\n".join(
        f".subckt {master} {bond} {' '.join(rails)}\nR0 {bond} {rail} 1\n.ends"
        for master, (bond, rail) in feeds.items()))
    model = (f"module {bridge}(QUIET, CORE);\ninout QUIET, CORE;\n"
             "assign QUIET = CORE;\nendmodule\n")
    library = {"classes": classes, "sizes": {master: (10, 20) for master in classes},
               "roles": roles, "prefix": "neutral__", "sources": {},
               "terminals": {receiver: "BOND", **{master: bond
                             for master, (bond, _) in feeds.items()}},
               "libs": [liberty], "root": str(tmp_path), "pdk": "neutral",
               "verilog": [model], "conflicts": {},
               "cells": chip.pads.parse_liberty_pad_cells(liberty.read_text())}
    native = {"VDD_PIN": "VDD", "GND_PIN": "VSS", "LIB": {"*": [str(core)]}}
    ports = [{"name": "din", "direction": "input", "width": 1, "indexed": False}]
    monkeypatch.setattr(chip.pads, "discover_io_netlists", lambda *args: [spice])
    monkeypatch.setattr(chip, "_side_ports", lambda *args: (
        {"N": ["din"], "E": [], "S": [], "W": []}, None, []))
    return tmp_path, native, ports, library


def test_ring_connects_the_receiver_supply_through_a_passive_library_connector(receiver_ring):
    try:
        chosen, _, _, _, _, _ = chip._ring(*receiver_ring)
        signal = next(entry for entry in chosen.values() if entry["port"] == "din")
        observed = (signal["core_pin"], signal["power_connections"]["QUIET"],
                    sorted(entry["master"] for entry in chosen.values()
                           if entry.get("is_ring_connector")))
    except (ValueError, chip.electrical.Refusal) as exc:
        observed = (str(exc), None, [])
    assert observed == ("IN_CORE", "VDD", ["neutral__quiet_bridge"])


def test_unavailable_passive_connector_keeps_the_receiver_refusal(receiver_ring):
    receiver_ring[-1]["verilog"] = []
    with pytest.raises(ValueError, match="0 output pin.*core face"):
        chip._ring(*receiver_ring)


def test_incompatible_connector_supply_voltages_are_refused(receiver_ring):
    liberty = receiver_ring[-1]["libs"][0]
    liberty.write_text(liberty.read_text().replace('voltage_map ("QUIET", 1.8)',
                                                 'voltage_map ("QUIET", 2.0)'))
    with pytest.raises(chip.electrical.Refusal, match="compatible supply rails"):
        chip._ring(*receiver_ring)


def test_unpowered_synthesis_preserves_the_physical_ring_connector(tmp_path):
    import shutil
    import subprocess

    yosys = shutil.which("yosys")
    if yosys is None:
        pytest.skip("native Yosys is required to measure generated connector retention")
    master, instance = "neutral_bridge", "u_connector"
    chosen = {instance: {"master": master, "is_ring_connector": True,
                         "supply_connections": {"CORE": "power", "QUIET": "power"}}}
    native = {"SYNTH_TIEHI_CELL": "neutral_hi/Y", "SYNTH_TIELO_CELL": "neutral_lo/Y"}
    library = {"verilog": [], "pg_pins": {master: {"CORE", "QUIET"}}}
    wrapper = chip._wrapper("neutral_core", "neutral_chip", [], chosen,
                            {"N": [instance]}, ["power"], native, library)
    (tmp_path / "models.v").write_text("""(* blackbox *) module neutral_bridge (
`ifdef USE_POWER_PINS
    inout CORE, QUIET
`endif
); endmodule
""")
    (tmp_path / "design.v").write_text(wrapper + "module neutral_core; endmodule\n")
    run = subprocess.run([yosys, "-Q", "-T", "-p",
        "read_verilog -lib models.v; read_verilog design.v; "
        "synth -top neutral_chip; write_json synthesized.json"],
        cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    cells = json.loads((tmp_path / "synthesized.json").read_text())["modules"]["neutral_chip"]["cells"]
    assert {name: cell["type"] for name, cell in cells.items()} == {instance: master}


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    doc = _write(project / "input/docs/L9_floorplan.md", """# Physical Pad Placement
| Side | Signal |
|---|---|
| North | `data[5:2]` |
| East | `clk` |
| South | `reset` |
| West | `result` |
""")
    _write(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
           json.dumps({"constraints": {"io_delay": {"default_fraction_percent": 20}}}))
    rtl = _write(project / "phase2/stage1/rtl/logic.v", "module logic; endmodule\n")
    config = {"DESIGN_NAME": "logic", "PDK": "fixture", "VERILOG_FILES": [str(rtl)],
              "CLOCK_PORT": "clk", "CLOCK_PERIOD": 24, "FP_CORE_UTIL": 40,
              "PDN_VOFFSET": 9, "PDN_HOFFSET": 11, "PDN_SKIPTRIM": True,
              "PDN_CFG": "retained.tcl"}
    header = {"modules": {"logic": {"ports": {
        "clk": {"direction": "input", "bits": [2]},
        "reset": {"direction": "input", "bits": [3]},
        "data": {"direction": "input", "bits": [4, 5, 6, 7], "offset": 2},
        "result": {"direction": "output", "bits": [8]},
    }}}}
    ports = chip._ports(header, "logic")
    roles = {"VDD": "POWER", "VSS": "GROUND", "DVDD": "POWER", "DVSS": "GROUND"}
    macros = []
    for master, cls, width, height, pins in (
        ("fixture_io__input", "PAD INPUT", 10, 20, ["PAD", "Y", *roles]),
        ("fixture_io__output", "PAD INOUT", 10, 20, ["PAD", "A", "OE", *roles]),
        ("fixture_io__power", "PAD POWER", 10, 20, ["DVDD", "DVSS", "VSS"]),
        ("fixture_io__ground", "PAD POWER", 10, 20, ["DVSS", "DVDD", "VDD"]),
        ("fixture_io__corner", "ENDCAP", 20, 20, []),
        ("fixture_io__fill", "PAD SPACER", 1, 20, []),
    ):
        macro = [f"MACRO {master}", f" CLASS {cls} ;", f" SIZE {width} BY {height} ;"]
        for pin in pins:
            macro += [f" PIN {pin}", "  DIRECTION INOUT ;",
                      f"  USE {roles.get(pin, 'SIGNAL')} ;", f" END {pin}"]
        macro.append(f"END {master}")
        macros.append("\n".join(macro))
    lef = _write(tmp_path / "pads.lef", "\n".join(macros) + """
SITE IO_SITE
 CLASS PAD ;
 SIZE 1 BY 20 ;
END IO_SITE
""")
    lib = _write(tmp_path / "pads.lib", """library (fixture) {
 time_unit : "1ns";
 default_max_transition : 1;
 lu_table_template (input_edge) {
  variable_1 : input_net_transition;
  index_1 ("0.08, 1.0");
 }
 cell (fixture_io__input) {
  pin (PAD) {
   direction : input;
   is_pad : true;
  }
  pin (Y) {
   direction : output;
   function : "PAD";
   timing () {
    related_pin : "PAD";
    cell_rise (input_edge) {
     values ("0.1, 0.2");
    }
   }
  }
 }
 cell (fixture_io__output) {
  pin (PAD) {
   direction : inout;
   is_pad : true;
   function : "A";
   three_state : "!OE";
  }
  pin (A) {
   direction : input;
  }
  pin (OE) {
   direction : input;
  }
 }
}
""")
    tech = _write(tmp_path / "tech.lef", "UNITS\n DATABASE MICRONS 1000 ;\nEND UNITS\nMANUFACTURINGGRID 0.005 ;\n")
    pdk = _write(tmp_path / "config.tcl", """set ::env(PAD_PLACE_IO_TERMINALS) {
 {fixture_io__input PAD}
 {fixture_io__output PAD}
}
""")
    native = {**config, "PDK_ROOT": str(tmp_path), "PAD_LEFS": [str(lef)],
              "PAD_LIBS": {"*": [str(lib)]}, "LIB": {"*": [str(lib)]},
              "TECH_LEFS": {"*": str(tech)}, "PAD_CORNER": ["fixture_io__corner"],
              "PAD_FILLERS": ["fixture_io__fill"], "PAD_EDGE_SPACING": 2,
              "PAD_SITE_NAME": "IO_SITE", "VDD_PIN": "VDD", "GND_PIN": "VSS",
              "SYNTH_TIEHI_CELL": "fixture_tie_hi/Y", "SYNTH_TIELO_CELL": "fixture_tie_lo/Y",
              "FP_ASPECT_RATIO": 1, "PDN_CORE_RING": False}
    monkeypatch.setattr(chip.pads, "discover_io_library_configs", lambda *args: [pdk])
    monkeypatch.setattr(chip.pads, "discover_io_site_declarations", lambda *args: [])
    monkeypatch.setattr(chip.pads, "discover_io_verilog", lambda *args: [])
    monkeypatch.setattr(chip, "_native_core", lambda *args: (
        native, ports, 40.0, [{"name": "Yosys.Synthesis", "tool_seconds": 0.0}]))
    return project, config, native, ports, doc


def test_prepare_writes_usable_chip_inputs_and_preserves_pdn(inputs):
    project, config, native, ports, _ = inputs
    result = chip.prepare(project, config)
    assert result["DESIGN_NAME"] == "logic_chip"
    assert result["PDN_ENABLE_PINS"] is False
    assert result["MAGIC_EXT_USE_GDS"] is True
    assert len(result["PAD_NORTH"]) == 4
    assert len(result["PAD_EAST"]) == 3
    assert len(result["PAD_SOUTH"]) == 1
    assert len(result["PAD_WEST"]) == 1
    for key in ("PDN_CFG", "PDN_VOFFSET", "PDN_HOFFSET", "PDN_SKIPTRIM"):
        assert result[key] == config[key]
    wrapper = Path(result["VERILOG_FILES"][-1]).read_text()
    assert "input wire [5:2] data" in wrapper
    assert "inout wire result" in wrapper
    assert "wire [5:2] _core_port_2;" in wrapper
    assert ".PAD(data[5])" in wrapper
    assert ".Y(_core_port_2[5])" in wrapper
    assert "fixture_tie_hi" in wrapper
    assert ".A(_core_port_3)" in wrapper
    assert result["FALLBACK_SDC"] == result["PNR_SDC_FILE"] == result["SIGNOFF_SDC_FILE"]
    sdc = Path(result["PNR_SDC_FILE"]).read_text()
    assert "-period 24" in sdc
    assert "set_input_delay 4.8" in sdc
    assert "set_output_delay 4.8" in sdc
    assert "all_inputs" not in sdc and "all_outputs" not in sdc
    assert r"data\[5\]" in sdc
    report = json.loads((project / "work/flow/chip/preparation.json").read_text())
    assert report["geometry"]["mapped_cell_area_um2"] == 40
    assert report["geometry"]["core_utilization_percent"] == 40
    assert report["tool_seconds"] == 0
    assert report["assumptions"]
    assert result["DIE_AREA"][2] >= 84
    assert result["CORE_AREA"][0] == 22


@pytest.mark.parametrize("constant", [False, True])
def test_native_pad_sdc_models_dc_bonds_and_preserves_dynamic_outputs(inputs, constant):
    import shutil
    import subprocess

    sta = shutil.which("sta")
    if sta is None:
        pytest.skip("Native OpenSTA required")
    project, config, native, _, _ = inputs
    prepared = chip.prepare(project, config)
    report = json.loads((project / "work/flow/chip/preparation.json").read_text())
    instance, output = next((name, entry) for name, entry in report["pads"].items()
                            if entry.get("direction") == "output")
    supplies = [entry["port"] for entry in report["pads"].values() if entry.get("is_supply_pad")]
    netlist = project / "mapped.v"
    drive = "1'b0" if constant else "data[2]"
    netlist.write_text(f"""module logic_chip(input clk, reset, input [5:2] data,
      inout result, {', '.join(supplies)});
      {output['master']} {instance} (.PAD(result), .A({drive}), .OE(1'b1));
    endmodule
    """)
    script = project / "check_static.tcl"
    script.write_text(f"""read_liberty {{{native['PAD_LIBS']['*'][0]}}}
read_verilog {{{netlist}}}
link_design logic_chip
read_sdc {{{prepared['PNR_SDC_FILE']}}}
puts "RESULT_CASE [sta::pin_case_logic_value [sta::get_port_pin [get_ports result]]]"
foreach supply [get_ports {{{' '.join(supplies)}}}] {{
  puts "SUPPLY_CASE [get_name $supply] [sta::pin_case_logic_value [sta::get_port_pin $supply]]"
}}
exit
""")
    run = subprocess.run([sta, "-no_init", "-no_splash", "-exit", str(script)],
                         cwd=project, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Error" not in run.stdout + run.stderr
    assert f"RESULT_CASE {'0' if constant else 'X'}" in run.stdout
    library = chip._library(native)
    for entry in report["pads"].values():
        if entry.get("is_supply_pad"):
            use = library["roles"][entry["master"]][entry["terminal"]][1]
            assert f"SUPPLY_CASE {entry['port']} {int(use == 'POWER')}" in run.stdout


def test_bidirectional_pad_terminal_does_not_change_the_logical_input_budget(inputs):
    project, config, native, ports, _ = inputs
    liberty = Path(native["PAD_LIBS"]["*"][0])
    liberty.write_text(liberty.read_text().replace(
        "direction : input;\n   is_pad : true;", "direction : inout;\n   is_pad : true;"))
    result = chip.prepare(project, config)
    wrapper = Path(result["VERILOG_FILES"][-1]).read_text()
    assert "inout wire [5:2] data" in wrapper
    assert "inout wire clk" in wrapper
    assert next(port for port in ports if port["name"] == "data")["direction"] == "input"
    report = json.loads((project / "work/flow/chip/preparation.json").read_text())
    assert next(port for port in report["ports"] if port["name"] == "data")["direction"] == "input"
    sdc = Path(result["PNR_SDC_FILE"]).read_text()
    assert "set_input_delay 4.8" in sdc and r"data\[5\]" in sdc
    assert "set_output_delay 4.8" in sdc


def test_native_bidirectional_receivers_pass_the_normal_verilator_step(tmp_path, native_inputs):
    from librelane.common import Toolbox
    from librelane.flows import Flow
    from librelane.state import State
    from librelane.steps import Step

    core = Path(native_inputs["VERILOG_FILES"][0])
    core.write_text("module unit(input clk, input [3:1] data, output reg q);\n"
                    "always @(posedge clk) q <= ^data; endmodule\n")
    owner = Flow.factory.get("Chip")(native_inputs, design_dir=str(tmp_path),
                                    pdk_root=os.environ["PDK_ROOT"])
    native = owner.config.to_raw_dict()
    library = chip._library(native)
    ports = chip._ports({"modules": {"unit": {"ports": {
        "clk": {"direction": "input", "bits": [2]},
        "data": {"direction": "input", "bits": [3, 4, 5], "offset": 1},
        "q": {"direction": "output", "bits": [6]},
    }}}}, "unit")
    chosen, ordered, supplies, *_ = chip._ring(tmp_path, native, ports, library)
    wrapper = _write(tmp_path / "wrapper.v", chip._wrapper(
        "unit", "unit_chip", ports, chosen, ordered, supplies, native, library))
    config = owner.config.copy(DESIGN_NAME="unit_chip", VERILOG_FILES=[str(core), str(wrapper)])
    result = Step.factory.get("Verilator.Lint")(config, State()).start(
        toolbox=Toolbox(str(tmp_path / "tools")), step_dir=str(tmp_path / "lint"))
    assert result.metrics["design__lint_error__count"] == 0
    assert "inout wire [3:1] data" in wrapper.read_text()


@pytest.mark.parametrize("direction", ["input", "output"])
def test_unidirectional_pad_terminals_keep_their_native_direction(direction):
    port = {"name": "signal", "direction": direction, "width": 1, "indexed": False}
    chosen = {"u_pad": {"port": "signal", "master": "neutral_pad", "terminal": "BOND",
                         "direction": direction, "core_pin": "CORE"}}
    library = {"cells": {"neutral_pad": {"BOND": {"direction": direction}}},
               "pg_pins": {}, "verilog": []}
    native = {"SYNTH_TIEHI_CELL": "neutral_hi/Y", "SYNTH_TIELO_CELL": "neutral_lo/Y"}
    wrapper = chip._wrapper("neutral_core", "neutral_chip", [port], chosen,
                            {"N": ["u_pad"]}, [], native, library)
    assert f"{direction} wire signal" in wrapper
    assert "inout wire signal" not in wrapper


@pytest.mark.parametrize("wide_side", ["N", "E"])
def test_unbalanced_pad_sides_size_each_die_dimension(inputs, monkeypatch, wide_side):
    project, config, native, ports, doc = inputs
    ports = [{**port, "width": 32, "msb": 33} if port["name"] == "data" else port
             for port in ports]
    other = "E" if wide_side == "N" else "N"
    doc.write_text("# Physical Pad Placement\n| Side | Signal |\n|---|---|\n"
        f"| {chip.SIDES[wide_side]} | `data[33:2]` |\n"
        f"| {chip.SIDES[other]} | `clk` |\n| South | `reset` |\n| West | `result` |\n")
    monkeypatch.setattr(chip, "_native_core", lambda *args: (native, ports, 40.0, []))

    result = chip.prepare(project, config)

    die, core = result["DIE_AREA"], result["CORE_AREA"]
    dimensions = [die[2] - die[0], die[3] - die[1]]
    wide_axis = 0 if wide_side == "N" else 1
    assert dimensions[wide_axis] > 2 * dimensions[1 - wide_axis]
    assert len(result["PAD_" + chip.SIDES[wide_side]]) >= 32
    assert (core[2] - core[0]) * (core[3] - core[1]) >= 40 / .4
    assert native["FP_CORE_UTIL"] == config["FP_CORE_UTIL"] == 40
    (project / "aspect_observation.json").write_text(json.dumps({
        "die": die, "core": core, "die_area_um2": dimensions[0] * dimensions[1],
        "pad_sides": {side: result["PAD_" + side] for side in chip.SIDES.values()}}))


def test_current_geometry_reaches_floorplan_and_reserves_both_ring_rails(inputs, monkeypatch):
    import flow_pdn_current
    project, config, native, _, _ = inputs
    native.update(PDN_CORE_RING=True, PDN_CORE_RING_CONNECT_TO_PADS=False,
                  PDN_CORE_RING_VOFFSET=1, PDN_CORE_RING_HOFFSET=1,
                  PDN_CORE_RING_VWIDTH=1, PDN_CORE_RING_HWIDTH=1,
                  PDN_CORE_RING_VSPACING=1, PDN_CORE_RING_HSPACING=1)
    monkeypatch.setattr(flow_pdn_current, "current_settings", lambda *args: {
        "PDN_VWIDTH": 3.2, "PDN_CORE_RING_VWIDTH": 3.2,
        "PDN_HWIDTH": 2.4, "PDN_CORE_RING_HWIDTH": 2.4})
    result = chip.prepare(project, config)
    assert result["PDN_VWIDTH"] == 3.2
    geometry = json.loads((project / "work/flow/chip/preparation.json").read_text())["geometry"]
    assert geometry["pdn_envelope_um"] == pytest.approx(8.4)
    assert geometry["core_inset_um"] >= 8.4 + geometry["pad_depth_um"]


def test_floorplan_row_reserves_the_ring_sized_after_initial_preparation(inputs, monkeypatch):
    pytest.importorskip("librelane")
    from types import SimpleNamespace
    from librelane.config import Config
    import flow_engine
    import flow_pdn_current

    project, config, native, _, _ = inputs
    native.update(PDN_CORE_RING=True, PDN_CORE_RING_CONNECT_TO_PADS=False,
                  PDN_CORE_RING_VOFFSET=1, PDN_CORE_RING_HOFFSET=1,
                  PDN_CORE_RING_VWIDTH=1, PDN_CORE_RING_HWIDTH=1,
                  PDN_CORE_RING_VSPACING=1, PDN_CORE_RING_HSPACING=1)
    generated = chip.prepare(project, config)
    initial_inset = generated["CORE_AREA"][0] - generated["DIE_AREA"][0]
    power = project / "steps/pre_layout_timing/result.json"
    _write(power, json.dumps({"native_metrics": {"power__total__corner:nominal": 0.02}}))
    monkeypatch.setattr(flow_pdn_current, "current_settings", lambda *args, **kwargs: {
        "PDN_CORE_RING_VWIDTH": 12, "PDN_CORE_RING_HWIDTH": 12})
    monkeypatch.setattr(chip, "_native_core", lambda *args: pytest.fail("second synthesis"))
    monkeypatch.setattr(chip, "netlist_area", lambda *args: 40)
    chain = flow_engine.NativeChain(project, {"delivery_target": "gds"})
    chain.owner = SimpleNamespace(config=Config({**native, **generated}))
    chain.config = chain.owner.config.to_raw_dict()

    assert chain.prepare(floorplan=True, directory=project / "floorplan") is None

    die, core = chain.config["DIE_AREA"], chain.config["CORE_AREA"]
    inset = min(core[0] - die[0], core[1] - die[1], die[2] - core[2], die[3] - core[3])
    assert inset > initial_inset
    assert inset >= 2 + 20 + 1 + 2 * 12 + 1
    assert (core[2] - core[0]) * (core[3] - core[1]) >= 40 / 0.4
    declaration = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    docs = json.loads(declaration.read_text())
    docs["fields"] = {"die_area_um": generated["DIE_AREA"], "core_area_um": generated["CORE_AREA"]}
    declaration.write_text(json.dumps(docs))
    error = chain.prepare(floorplan=True, directory=project / "floorplan")
    assert isinstance(error, ValueError)
    assert "cannot fit" in str(error)


def test_generated_pad_access_profile_applies_native_current_sizing_at_floorplan(inputs, monkeypatch):
    pytest.importorskip("odb")
    pytest.importorskip("librelane")
    from decimal import Decimal
    from types import SimpleNamespace
    from librelane.config import Config
    from flow_config import _chip_pdn
    from flow_engine import NativeChain

    project, config, native, _, _ = inputs
    config.update(_chip_pdn(project, config["PDK"]))
    native.update(config, DEFAULT_CORNER="nominal", PDN_VERTICAL_LAYER="upper_vertical",
        PDN_HORIZONTAL_LAYER="upper_horizontal", PDN_VWIDTH=1.6, PDN_HWIDTH=1.6,
        PDN_CORE_RING_VWIDTH=1.6, PDN_CORE_RING_HWIDTH=1.6,
        PDN_CORE_RING_VOFFSET=1, PDN_CORE_RING_HOFFSET=1,
        PDN_CORE_RING_VSPACING=1.7, PDN_CORE_RING_HSPACING=1.7,
        PDN_VSPACING=1.7, PDN_HSPACING=1.7, PDN_VPITCH=20, PDN_HPITCH=20)
    tech = Path(native["TECH_LEFS"]["*"])
    text = "VERSION 5.8 ;\n" + tech.read_text()
    for layer, direction in (("upper_vertical", "VERTICAL"), ("upper_horizontal", "HORIZONTAL")):
        text += f"LAYER {layer}\n TYPE ROUTING ;\n DIRECTION {direction} ;\n PITCH 1 ;\n" \
            " WIDTH 0.28 ;\n SPACING 0.28 ;\n THICKNESS 0.54 ;\n" \
            f" DCCURRENTDENSITY AVERAGE 0.67 ;\nEND {layer}\n"
    tech.write_text(text + "END LIBRARY\n")
    lib = Path(native["LIB"]["*"][0])
    lib.write_text(lib.read_text().replace("library (fixture) {", "library (fixture) {\n nom_voltage : 5;"))
    lef = Path(native["PAD_LEFS"][0])
    lef.write_text(lef.read_text().replace("  USE GROUND ;", "  USE GROUND ;\n"
        "  PORT\n   LAYER pad_access ;\n   RECT 0 0 10 1 ;\n  END"))
    generated = chip.prepare(project, config)
    assert "pad_access upper_vertical" in Path(generated["PDN_CFG"]).read_text()
    _write(project / "steps/pre_layout_timing/result.json", json.dumps({
        "native_metrics": {"power__total__corner:nominal": .02}}))
    monkeypatch.setattr(chip, "netlist_area", lambda *args: 40)
    chain = NativeChain(project, {"delivery_target": "gds"})
    chain.owner = SimpleNamespace(config=Config({**native, **generated}))
    chain.config = chain.owner.config.to_raw_dict()

    assert chain.prepare(floorplan=True, directory=project / "floorplan") is None

    assert chain.config["PDN_VWIDTH"] == Decimal("5.98")
    assert chain.config["PDN_CORE_RING_VWIDTH"] == Decimal("5.98")
    core, die = chain.config["CORE_AREA"], chain.config["DIE_AREA"]
    assert core[0] - die[0] >= 2 + 20 + 1 + 2 * 5.98 + 1.7


@pytest.mark.parametrize("route", ["ic", "ip"])
def test_current_scan_netlist_fits_despite_undercounted_yosys_area(inputs, native_inputs, route, monkeypatch):
    from librelane.common import Path as NativePath, Toolbox
    from librelane.flows import Flow
    from librelane.state import State, DesignFormat
    from librelane.steps import Step
    import flow_engine

    project, config, native, _, _ = inputs
    generated = chip.prepare(project, config)
    pad_lef = Path(native["PAD_LEFS"][0])
    pad_lef.write_text(pad_lef.read_text().replace("CLASS ENDCAP ;", "CLASS ENDCAP TOPLEFT ;"))
    netlist = project / "scan.v"
    netlist.write_text("module unit(input clk, si, se, output so); wire [128:0] chain;\n"
        "assign chain[0]=si; sky130_fd_sc_hd__inv_1 output_inv(.A(chain[128]),.Y(so));\n" + "\n".join(
        f"sky130_fd_sc_hd__sdfxtp_1 scan{i}(.CLK(clk),.D(chain[{i}]),.SCD(chain[{i}]),.SCE(se),.Q(chain[{i+1}]));"
        for i in range(128)) + "\nendmodule\n")
    owner = Flow.factory.get("Classic")({**native_inputs, "VERILOG_FILES": [str(netlist)]},
        design_dir=str(project), pdk_root=os.environ["PDK_ROOT"])
    owner.config = owner.config.copy(**{key: native[key] for key in (
        "PAD_LEFS", "PAD_LIBS", "PAD_CORNER", "PAD_FILLERS", "PAD_EDGE_SPACING", "PAD_SITE_NAME",
        "FP_CORE_UTIL", "FP_ASPECT_RATIO", "PDN_CORE_RING")},
        FP_SIZING="absolute" if route == "ic" else "relative",
        DIE_AREA=generated["DIE_AREA"] if route == "ic" else None,
        CORE_AREA=generated["CORE_AREA"] if route == "ic" else None,
        VDD_NETS=generated["VDD_NETS"], GND_NETS=generated["GND_NETS"])
    toolbox = Toolbox(str(project / "tool_tmp"))
    initial = State({DesignFormat.NETLIST: NativePath(str(netlist))})
    monkeypatch.chdir(project)
    state = Step.factory.get("Yosys.Resynthesis")(owner.config, initial).start(
        toolbox=toolbox, step_dir=str(project / "resynthesis"))
    initial_core = generated["CORE_AREA"]
    initial_core_area = (initial_core[2] - initial_core[0]) * (initial_core[3] - initial_core[1])
    assert float(state.metrics["design__instance__area"]) < initial_core_area
    chain = flow_engine.NativeChain(project, {"delivery_target": "gds" if route == "ic" else "ip_hardmacro"})
    chain.owner, chain.config, chain.state, chain.toolbox = owner, owner.config.to_raw_dict(), state, toolbox
    result = chain.execute(project / "floorplan", {"steps": ["OpenROAD.Floorplan"]})

    assert flow_engine.evaluate(result, []) == "PASS", result
    actual = float(chain.state.metrics["design__instance__area"])
    assert actual > initial_core_area
    assert float(chain.state.metrics["design__core__area"]) >= actual
    assert chain.config["FP_CORE_UTIL"] == native["FP_CORE_UTIL"]
    if route == "ic":
        measured = json.loads((project / "work/flow/chip/preparation.json").read_text())
        assert measured["geometry"]["mapped_cell_area_um2"] == pytest.approx(actual)
        bounds = {key: [float(value) for value in chain.state.metrics[metric].split()]
            for metric, key in (("design__die__bbox", "DIE_AREA"), ("design__core__bbox", "CORE_AREA"))}
        chain.owner.config = chain.owner.config.copy(
            DIE_AREA=generated["DIE_AREA"], CORE_AREA=generated["CORE_AREA"])
        chain.config = chain.owner.config.to_raw_dict()
        chain.restore(project / "floorplan")
        assert chain.config["DIE_AREA"] == bounds["DIE_AREA"]
        assert chain.config["CORE_AREA"] == bounds["CORE_AREA"]


def test_current_sizing_uses_initial_die_before_final_floorplan(inputs, monkeypatch):
    import flow_pdn_current
    project, config, native, _, _ = inputs
    floorplan = chip._floorplan
    events, plans = [], []

    def observed_floorplan(*args):
        events.append(("floorplan", dict(args[0]), args[6] if len(args) > 6 else None))
        result = floorplan(*args)
        plans.append(result)
        return result

    def settings(root, resolved, parallel_length_um=0):
        events.append(("pdn", root, parallel_length_um))
        return {"PDN_VWIDTH": 3.2}

    monkeypatch.setattr(chip, "_floorplan", observed_floorplan)
    monkeypatch.setattr(flow_pdn_current, "current_settings", settings)
    initial_width = native.get("PDN_VWIDTH")
    result = chip.prepare(project, config)
    assert [event[0] for event in events] == ["floorplan", "pdn", "floorplan"]
    first_die = plans[0][0]
    assert events[1] == ("pdn", project, max(first_die[2] - first_die[0], first_die[3] - first_die[1]))
    assert events[0][1].get("PDN_VWIDTH") == initial_width
    assert events[0][2] is None
    assert events[2][1]["PDN_VWIDTH"] == 3.2
    assert events[2][2] == {"PDN_VWIDTH": 3.2}
    assert result["PDN_VWIDTH"] == 3.2
    assert result["DIE_AREA"] == plans[1][0]
    assert result["CORE_AREA"] == plans[1][1]


def test_chip_forwards_generated_clock_wire_budget(inputs, monkeypatch):
    import flow_clock_geometry
    project, config, native, _, _ = inputs
    observed = []

    def settings(resolved):
        observed.append(resolved)
        return {"CTS_CLK_MAX_WIRE_LENGTH": 120}

    monkeypatch.setattr(flow_clock_geometry, "clock_settings", settings)
    result = chip.prepare(project, config)
    assert observed == [native]
    assert result["CTS_CLK_MAX_WIRE_LENGTH"] == 120


def test_native_timing_environment_and_driving_cells_reach_sdc(inputs):
    project, config, native, _, _ = inputs
    native.update(CLOCK_UNCERTAINTY_CONSTRAINT=0.25, CLOCK_TRANSITION_CONSTRAINT=0.15,
                  TIME_DERATING_CONSTRAINT=5, MAX_FANOUT_CONSTRAINT=4,
                  MAX_TRANSITION_CONSTRAINT=3, MAX_CAPACITANCE_CONSTRAINT=0.2, OUTPUT_CAP_LOAD=10,
                  SYNTH_DRIVING_CELL="data_driver/Y", SYNTH_CLK_DRIVING_CELL="clock_driver/Z")
    result = chip.prepare(project, config)
    text = Path(result["PNR_SDC_FILE"]).read_text()
    assert "set_timing_derate -late 1.05" in text
    assert "set_timing_derate -early 0.949999" in text
    assert "set_clock_uncertainty 0.25" in text
    assert "set_clock_transition 0.15" in text
    assert "set_max_transition 3 [current_design]" in text
    assert "set_max_capacitance 0.2 $_chip_core_pins" in text
    assert "set_max_capacitance 0.2 [current_design]" not in text
    assert "set_load 0.01" in text
    assert "set_driving_cell -lib_cell data_driver -pin Y" in text
    assert "set_driving_cell -lib_cell clock_driver -pin Z" in text
    assert "_chip_pad_max" not in text and "_chip_pad_min" not in text


@pytest.mark.parametrize("hierarchical", [False, True])
def test_native_core_cap_limit_and_pad_liberty_limit_both_remain(tmp_path, hierarchical):
    import shutil
    import subprocess

    sta = shutil.which("sta")
    if sta is None:
        pytest.skip("Native OpenSTA required for capacitance limit checks")
    library = tmp_path / "cells.lib"
    library.write_text('''library (cells) {
      delay_model : table_lookup;
      time_unit : "1ns";
      voltage_unit : "1V";
      current_unit : "1mA";
      capacitive_load_unit (1,pf);
      nom_voltage : 5;
      nom_temperature : 25;
      nom_process : 1;
      cell (receiver) {
        pin (PAD) { direction : input; capacitance : 3.12; }
        pin (Y) { direction : output; function : "PAD"; max_capacitance : 1; }
      }
      cell (buffer) {
        pin (A) { direction : input; capacitance : 0.01; }
        pin (Z) { direction : output; function : "A"; max_capacitance : 1; }
      }
      cell (driver) {
        pin (A) { direction : input; capacitance : 0.28; }
        pin (PAD) { direction : output; function : "A"; max_capacitance : 4; }
      }
    }''')
    netlist = tmp_path / "chip.v"
    design = '''module chip(input bond_in, output bond_out);
      wire a, b;
      receiver pad_in(.PAD(bond_in), .Y(a));
      buffer core_buf(.A(a), .Z(b));
      driver pad_out(.A(b), .PAD(bond_out));
    endmodule'''
    if hierarchical:
        design = design.replace("driver pad_out", "pad_shell pad_out")
        design += '''\nmodule pad_shell(input A, output PAD);
          driver io_inst(.A(A), .PAD(PAD));
        endmodule'''
    netlist.write_text(design)
    pad_pin = "pad_out/io_inst/PAD" if hierarchical else "pad_out/PAD"
    ports = [{"name": name, "direction": direction, "indexed": False}
             for name, direction in (("bond_in", "input"), ("bond_out", "output"))]
    config = {"PDK": "gf180mcuD", "CLOCK_PORT": ["bond_in"], "CLOCK_PERIOD": 24, "IO_DELAY_CONSTRAINT": 20,
              "MAX_CAPACITANCE_CONSTRAINT": .2, "OUTPUT_CAP_LOAD": 3530}
    sdc = tmp_path / "constraints.sdc"
    sdc.write_text(chip._sdc(tmp_path, config, ports))
    script = tmp_path / "check.tcl"
    script.write_text(f'''read_liberty {{{library}}}
read_verilog {{{netlist}}}
link_design chip
read_sdc {{{sdc}}}
puts CORE_AND_PAD_LIMITS
report_check_types -max_capacitance
set_load 4.5 [get_ports bond_out]
puts PAD_OWN_LIMIT_VIOLATION
report_check_types -max_capacitance -violators
exit
''')
    process = subprocess.run([sta, "-no_init", "-no_splash", "-exit", script],
                             capture_output=True, text=True, check=True)
    first, second = process.stdout.split("PAD_OWN_LIMIT_VIOLATION")
    assert "Error" not in process.stdout + process.stderr
    assert any("core_buf/Z" in line and "0.20" in line and "VIOLATED" in line
               for line in first.splitlines()), process.stdout
    assert not any(pad_pin in line and "VIOLATED" in line for line in first.splitlines()), process.stdout
    assert any(pad_pin in line and "4.00" in line and "VIOLATED" in line
               for line in second.splitlines()), process.stdout


@pytest.mark.parametrize("declared", [None, "0.23"])
def test_pad_table_coverage_does_not_supply_external_edges(inputs, tmp_path, declared):
    import shutil
    import subprocess

    interpreter = shutil.which("tclsh")
    command = [interpreter] if interpreter else [shutil.which("openroad"), "-no_init", "-no_splash", "-exit"]
    if command[0] is None:
        pytest.skip("A native Tcl interpreter is required")
    project, config, native, _, _ = inputs
    original = Path(native["PAD_LIBS"]["*"][0]).read_text()
    paths = []
    for name, bounds in (("fast_view", "0.01, 25"), ("slow_view", "0.10, 1.3")):
        path = tmp_path / (name + ".lib")
        text = original.replace("library (fixture)", f"library ({name})")
        text = text.replace("0.08, 1.0", bounds).replace("default_max_transition : 1;", "default_max_transition : 2;")
        path.write_text(text)
        paths.append(str(path))
    native["PAD_LIBS"] = {"*": paths}
    native.update(SYNTH_DRIVING_CELL="data_driver/Y", SYNTH_CLK_DRIVING_CELL="clock_driver/Z")
    if declared:
        _write(project / "input/docs/L9_edges.md", f"| set_input_transition | {declared} |\n")
    result = chip.prepare(project, config)
    script = tmp_path / "read.sdc.tcl"
    script.write_text('''namespace eval sta {
proc top_instance {} {return INSTANCE}
proc find_pin {name} {return PIN}
proc pin_sim_logic_value {pin} {return X}
}
proc INSTANCE method {return CELL}
proc CELL {method name} {return PORT}
proc get_ports args {return PORTS}
proc get_clocks args {return CLOCKS}
proc create_clock args {}
proc set_units args {}
proc set_input_delay args {}
proc set_output_delay args {}
proc set_case_analysis args {}
proc set_input_transition args {puts "EDGE $args"}
proc set_driving_cell args {puts "DRIVER $args"}
proc get_libs args {
    if {[lindex $args end] eq $::linked} {return LIB}
    return {}
}
''' + f"set ::linked fast_view\nsource {{{result['PNR_SDC_FILE']}}}\n")
    completed = subprocess.run([*command, str(script)], capture_output=True, text=True, check=True)
    assert "DRIVER -lib_cell data_driver -pin Y PORTS" in completed.stdout
    assert "DRIVER -lib_cell clock_driver -pin Z PORTS" in completed.stdout
    assert ([line for line in completed.stdout.splitlines() if line.startswith("EDGE ")]
            == ([f"EDGE {declared} PORTS"] if declared else []))


def test_undeclared_edge_does_not_require_pad_characterization_coverage(inputs):
    project, config, native, ports, _ = inputs
    native.pop("PAD_LIBS")
    text = chip._sdc(project, {**native, **config}, ports)
    assert "set_input_transition" not in text


@pytest.mark.parametrize("clock_driver", [None, "clock_driver/Z"])
def test_native_sta_consumes_resolved_clock_and_data_drivers(inputs, tmp_path, clock_driver):
    import shutil
    import subprocess

    sta = shutil.which("sta")
    if sta is None:
        pytest.skip("Native OpenSTA required for input-driver checks")
    project, config, native, ports, _ = inputs
    native.update(SYNTH_DRIVING_CELL="data_driver/Y", SYNTH_CLK_DRIVING_CELL=clock_driver,
                  CLOCK_TRANSITION_CONSTRAINT=0.15)
    models = []
    for master, pin in (("data_driver", "Y"), ("clock_driver", "Z")):
        models.append(f'''cell ({master}) {{
          pin (A) {{ direction : input; capacitance : 0.01; }}
          pin ({pin}) {{ direction : output; function : "A";
            timing () {{ related_pin : "A"; timing_sense : positive_unate;
              cell_rise (scalar) {{ values ("0.1"); }}
              cell_fall (scalar) {{ values ("0.1"); }}
              rise_transition (scalar) {{ values ("0.1"); }}
              fall_transition (scalar) {{ values ("0.1"); }}
            }}
          }}
        }}''')
    library = _write(tmp_path / "drivers.lib", '''library (drivers) {
      delay_model : table_lookup; time_unit : "1ns";
      capacitive_load_unit (1, pf);
      input_threshold_pct_rise : 50; input_threshold_pct_fall : 50;
      output_threshold_pct_rise : 50; output_threshold_pct_fall : 50;
      slew_lower_threshold_pct_rise : 20; slew_lower_threshold_pct_fall : 20;
      slew_upper_threshold_pct_rise : 80; slew_upper_threshold_pct_fall : 80;
      nom_process : 1; nom_voltage : 1.8; nom_temperature : 25;
    ''' + "\n".join(models) + "\n}\n")
    design = _write(tmp_path / "netlist.v", "module logic(input clk, reset, input [5:2] data, "
                    "output result); assign result=reset; endmodule\n")
    sdc = _write(tmp_path / "inputs.sdc", chip._sdc(project, {**native, **config}, ports))
    output = tmp_path / "native.sdc"
    script = _write(tmp_path / "inputs.tcl", f'''read_liberty {{{library}}}
read_verilog {{{design}}}
link_design logic
read_sdc {{{sdc}}}
write_sdc {{{output}}}
exit
''')
    completed = subprocess.run([sta, "-no_init", "-no_splash", "-exit", str(script)],
                               capture_output=True, text=True, check=True)
    assert "Error" not in completed.stdout + completed.stderr
    written = output.read_text()
    drivers = [line for line in written.splitlines() if line.startswith("set_driving_cell ")]
    assert any("-lib_cell data_driver" in line and "reset" in line for line in drivers), written
    selected = "clock_driver" if clock_driver else "data_driver"
    assert any(f"-lib_cell {selected}" in line and "clk" in line for line in drivers), written
    assert "set_clock_transition" in written and "0.15" in written
    assert "set_input_transition" not in written


def test_bus_order_offset_and_single_index_are_preserved():
    header = {"modules": {"core": {"ports": {
        "ascending": {"direction": "input", "offset": 4, "upto": 1, "bits": [2, 3, 4]},
        "single": {"direction": "output", "offset": 7, "bits": [5]},
    }}}}
    ports = chip._ports(header, "core")
    assert chip._bits(ports[0]) == ["ascending[4]", "ascending[5]", "ascending[6]"]
    assert chip._bits(ports[1]) == ["single[7]"]


def test_ring_layers_equal_to_mesh_layers_use_native_connection_once(inputs):
    project, config, native, _, _ = inputs
    for axis, layer in (("VERTICAL", "upper_vertical"), ("HORIZONTAL", "upper_horizontal")):
        native[f"PDN_{axis}_LAYER"] = layer
        config[f"PDN_CORE_{axis}_LAYER"] = layer
    result = chip.prepare(project, config)
    assert "PDN_CORE_VERTICAL_LAYER" not in result
    assert "PDN_CORE_HORIZONTAL_LAYER" not in result


@pytest.mark.parametrize("access,vertical,horizontal,ring", [
    ("pad_access", "mesh_vertical", "mesh_horizontal", None),
    ("lower_contact", "outer_vertical", "outer_horizontal", "ring_vertical"),
])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("owned", [False, True])
def test_prepare_connects_core_supply_pad_access_layers(inputs, access, vertical, horizontal, ring, existing, owned):
    project, config, native, _, _ = inputs
    native.update(PDN_CORE_RING=True, PDN_CORE_RING_CONNECT_TO_PADS=True,
                  PDN_VERTICAL_LAYER=vertical, PDN_HORIZONTAL_LAYER=horizontal,
                  PDN_CORE_RING_VOFFSET=1, PDN_CORE_RING_HOFFSET=1,
                  PDN_CORE_RING_VWIDTH=1, PDN_CORE_RING_HWIDTH=1,
                  PDN_CORE_RING_VSPACING=1, PDN_CORE_RING_HSPACING=1)
    if ring:
        native["PDN_CORE_VERTICAL_LAYER"] = ring
    target = ring or vertical
    lef = Path(native["PAD_LEFS"][0])
    text = lef.read_text()
    for pin, use, layer in (("VSS", "GROUND", access), ("VDD", "POWER", vertical),
                            ("PAD", "SIGNAL", "signal_access")):
        declaration = f" PIN {pin}\n  DIRECTION INOUT ;\n  USE {use} ;"
        text = text.replace(declaration, declaration + f"\n  PORT\n   LAYER {layer} ;"
                            "\n   RECT 0 0 10 1 ;\n  END")
    lef.write_text(text)
    original = "source $::env(SCRIPTS_DIR)/openroad/common/pdn_cfg.tcl\n"
    reverse = f"add_pdn_connect -grid stdcell_grid -layers {{{target} {access}}}"
    if existing:
        original += reverse + "\n"
    pdn = _write(project / ("work/flow/pdn_cfg.tcl" if owned else "input/pdn.tcl"), original)
    config["PDN_CFG"] = native["PDN_CFG"] = str(pdn)
    result = chip.prepare(project, config)
    generated = Path(result["PDN_CFG"]).read_text()
    command = f"add_pdn_connect -grid stdcell_grid -layers {{{access} {target}}}"
    assert generated.count(command) + generated.count(reverse) == 1
    for ring_layer in {target, horizontal}:
        command = f"add_pdn_connect -grid stdcell_grid -layers {{{access} {ring_layer}}}"
        reverse = f"add_pdn_connect -grid stdcell_grid -layers {{{ring_layer} {access}}}"
        assert generated.count(command) + generated.count(reverse) == 1
    assert "signal_access" not in generated
    assert f"-layers {{{vertical} {vertical}}}" not in generated
    assert generated.startswith(original)
    assert pdn.read_text() == original


def test_dynamic_inout_is_refused():
    with pytest.raises(ValueError, match="inout.*output-enable"):
        chip._ports({"modules": {"core": {"ports": {
            "data": {"direction": "inout", "bits": [2]}}}}}, "core")


def test_placement_conflict_is_refused(inputs):
    project, _, _, ports, doc = inputs
    doc.write_text(doc.read_text().replace("`reset`", "`clk`"))
    with pytest.raises(ValueError, match="Conflicting pad placement"):
        chip._side_ports(project, ports)


def test_unresolved_placement_is_refused(inputs):
    project, _, _, ports, doc = inputs
    doc.write_text(doc.read_text().replace("data[5:2]", "data[UNKNOWN-1:0]"))
    with pytest.raises(ValueError, match="Unresolved pad placement"):
        chip._side_ports(project, ports)


def test_unassigned_signals_are_placed_without_changing_declared_sides(inputs):
    project, _, _, ports, doc = inputs
    doc.write_text(doc.read_text().replace("| South | `reset` |", ""))
    sides, _, _ = chip._side_ports(project, ports)
    assert sides["N"] == ["data[5]", "data[4]", "data[3]", "data[2]"]
    assert sides["S"] == ["reset"]


@pytest.mark.parametrize("missing_document", [False, True])
def test_undeclared_io_delay_uses_resolved_native_default(inputs, missing_document):
    project, config, native, _, _ = inputs
    path = project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    if missing_document:
        path.unlink()
    else:
        path.write_text("{}")
    native["IO_DELAY_CONSTRAINT"] = 30
    result = chip.prepare(project, config)
    text = Path(result["PNR_SDC_FILE"]).read_text()
    assert "set_input_delay 7.2" in text
    assert "set_output_delay 7.2" in text


def test_existing_sdc_keeps_clock_names_exceptions_and_budgets(inputs):
    project, config, _, ports, _ = inputs
    original = project / "input/timing.sdc"
    original.write_text("create_clock -name declared_clock -period 24 [get_ports clk]\n"
        "set_clock_uncertainty 0.2 [get_clocks declared_clock]\n"
        "set_input_delay 3 -clock declared_clock [all_inputs -no_clocks]\n"
        "set_output_delay 5 -clock declared_clock [all_outputs]\n")
    config["PNR_SDC_FILE"] = str(original)
    text = chip._sdc(project, config, ports)
    assert "create_clock -name declared_clock -period 24" in text
    assert "[get_clocks declared_clock]" in text
    assert "set_input_delay 3 -clock declared_clock" in text
    assert "set_output_delay 5 -clock declared_clock" in text
    assert "core_clock_0" not in text
    assert "all_inputs" not in text and "all_outputs" not in text


def test_multiple_clock_delays_are_additive(inputs):
    project, config, _, ports, _ = inputs
    config["CLOCK_PORT"] = ["clk", "other_clock"]
    ports = [*ports, {"name": "other_clock", "direction": "input", "width": 1,
                     "indexed": False, "msb": 0, "lsb": 0}]
    text = chip._sdc(project, config, ports)
    assert "-clock core_clock_0 -add_delay" not in text
    assert "set_input_delay 4.8 -clock core_clock_1 -add_delay" in text
    assert "set_output_delay 4.8 -clock core_clock_1 -add_delay" in text


@pytest.mark.parametrize("existing_sdc", [False, True])
@pytest.mark.parametrize("clock", ["clk", "-quiet", "wild*", "wild?"])
def test_native_sta_constrains_literal_bus_ports(inputs, tmp_path, existing_sdc, clock):
    import shutil
    import subprocess

    sta = shutil.which("sta")
    if not sta:
        pytest.skip("Native OpenSTA is required")
    project, config, _, ports, _ = inputs
    config["CLOCK_PORT"] = clock
    ports = [{**ports[0], "name": clock}, *ports[1:-1],
             {**ports[-1], "width": 2, "msb": 1, "indexed": True}]
    netlist = _write(tmp_path / "ports.v", "module ports(clk,\\-quiet ,\\wild* ,\\wild? ,wild_one,wild_two,reset,data,result,spare_data);\n"
        "input clk,\\-quiet ,\\wild* ,\\wild? ,wild_one,wild_two,reset; input [5:2] data,spare_data; output [1:0] result;\n"
        "assign result = data[3:2]; endmodule\n")
    if existing_sdc:
        import re

        config["PNR_SDC_FILE"] = str(_write(tmp_path / "original.sdc",
            "create_clock -name core_clock_0 -period 24 [get_ports -regexp {^" + re.escape(clock) + "$}]\n"
            "set_input_delay 4.8 -clock core_clock_0 [all_inputs -no_clocks]\n"
            "set_output_delay 4.8 -clock core_clock_0 [all_outputs]\n"))
    sdc = chip._sdc(project, config, ports)
    queries = [line[line.index("[get_ports"):] for line in sdc.splitlines()
               if "[get_ports" in line]
    script = _write(tmp_path / "ports.tcl", f"read_verilog {{{netlist}}}\nlink_design ports\n"
        + "\n".join(f'foreach port {query} {{puts "COLLECTED=[get_full_name $port]"}}'
                    for query in queries) + "\nexit\n")
    result = subprocess.run([sta, "-exit", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    selected = {line.removeprefix("COLLECTED=") for line in result.stdout.splitlines()
                if line.startswith("COLLECTED=")}
    assert selected == {clock, "reset", "data[5]", "data[4]", "data[3]", "data[2]",
                        "result[1]", "result[0]"}, result.stdout + result.stderr


def test_impossible_declared_geometry_is_refused(inputs):
    project, config, native, _, _ = inputs
    native["DIE_AREA"] = [0, 0, 50, 50]
    with pytest.raises(ValueError, match="Declared DIE_AREA"):
        chip.prepare(project, config)


def test_explicit_legal_geometry_is_retained(inputs):
    project, config, native, _, _ = inputs
    native.update(DIE_AREA=[0, 0, 100, 100], CORE_AREA=[22, 22, 78, 78])
    result = chip.prepare(project, config)
    assert result["DIE_AREA"] == native["DIE_AREA"]
    assert result["CORE_AREA"] == native["CORE_AREA"]


@pytest.mark.parametrize("ingested", [False, True])
def test_selected_operator_slot_controls_die_core_and_pad_order(inputs, ingested):
    import submission_template_ingest as ingest

    project, config, native, _, _ = inputs
    generated = chip.prepare(project, config)
    sides = {side: generated["PAD_" + side][:] for side in chip.SIDES.values()}
    sides["NORTH"], sides["EAST"] = sides["EAST"], sides["NORTH"]
    sides["SOUTH"].reverse()
    die, core = [0.125, 0.25, 100.125, 100.25], [22.125, 22.25, 78.125, 78.25]
    source = project / ("operator" if ingested else "input/submission_template/slots")
    slot = {"SLOT": "neutral_slot", "DIE_AREA": die, "CORE_AREA": core,
            **{"PAD_" + side: values for side, values in sides.items()}}
    _write(source / "neutral_slot.yaml", json.dumps(slot))
    _write(project / "input/step_0_5ic_answers.json",
           json.dumps({"operator_template": {"slot": "neutral_slot"}}))
    if ingested:
        assert ingest.main([str(project), "--template", str(source), "--slot", "neutral_slot"]) == 0
    native.update(DIE_AREA=[0, 0, 80, 80], CORE_AREA=[22, 22, 58, 58])

    result = chip.prepare(project, config)

    assert result["DIE_AREA"] == die
    assert result["CORE_AREA"] == core
    assert {side: result["PAD_" + side] for side in sides} == sides
    report = json.loads((project / "work/flow/chip/preparation.json").read_text())
    assert report["operator_slot"] == "neutral_slot"
    wrapper = Path(result["VERILOG_FILES"][-1]).read_text()
    assert all(f" {instance} (" in wrapper for names in sides.values() for instance in names)


@pytest.mark.parametrize("selected", [None, "unavailable_slot"])
def test_supplied_operator_slot_never_defaults_to_another_geometry(inputs, selected):
    project, config, _, _, _ = inputs
    _write(project / "input/submission_template/slots/neutral_slot.yaml", json.dumps({
        "SLOT": "neutral_slot", "DIE_AREA": [0, 0, 100, 100]}))
    if selected:
        _write(project / "input/step_0_5ic_answers.json",
               json.dumps({"operator_template": {"slot": selected}}))
    with pytest.raises(ValueError, match="no slot is selected|0 matching records"):
        chip.prepare(project, config)


def test_operator_slot_pad_names_must_resolve_to_wrapper_pads(inputs):
    project, config, _, _, _ = inputs
    _write(project / "input/submission_template/slots/neutral_slot.yaml", json.dumps({
        "SLOT": "neutral_slot", "DIE_AREA": [0, 0, 100, 100],
        "PAD_NORTH": ["unknown_pad"]}))
    _write(project / "input/step_0_5ic_answers.json",
           json.dumps({"operator_template": {"slot": "neutral_slot"}}))
    with pytest.raises(ValueError, match="does not resolve to one unused wrapper pad"):
        chip.prepare(project, config)


def test_missing_native_fact_is_named(inputs):
    project, config, native, _, _ = inputs
    del native["PAD_FILLERS"]
    with pytest.raises(FileNotFoundError, match="PAD_FILLERS"):
        chip.prepare(project, config)


def test_existing_timing_commands_keep_explicit_collections(inputs):
    project, config, _, ports, _ = inputs
    source = _write(project / "constraints.sdc", """set_units -time ns
create_clock -period 99 [get_ports clk]
set_input_delay 99 -clock clk [all_inputs]
set_clock_uncertainty 0.25 [get_clocks *]
set_false_path -from [all_inputs -no_clocks] -to [all_outputs]
""")
    config["PNR_SDC_FILE"] = str(source)
    sdc = chip._sdc(project, config, ports)
    assert "create_clock -period 99 [get_ports clk]" in sdc
    assert "set_input_delay 99 -clock clk" in sdc
    assert "set_clock_uncertainty 0.25" in sdc
    assert "set_false_path -from [get_ports [list" in sdc
    assert "all_inputs" not in sdc and "all_outputs" not in sdc


def test_escaped_core_identifiers_have_legal_verilog_names(inputs):
    project, config, _, ports, doc = inputs
    doc.unlink()
    ports[2]["name"] = "data.value"
    result = chip.prepare(project, config)
    wrapper = Path(result["VERILOG_FILES"][-1]).read_text()
    assert "input wire [5:2] \\data.value " in wrapper
    assert ".\\data.value (_core_port_2)" in wrapper
    assert ".PAD(\\data.value [5])" in wrapper


@pytest.mark.parametrize("override", [None, 12])
@pytest.mark.parametrize("period_field", ["period_ns", "freq_mhz"])
@pytest.mark.parametrize("clock_count", [1, 2])
def test_each_primary_clock_keeps_its_declared_period_and_io_budget(inputs, override, period_field, clock_count):
    from sdc_constraints import create_clocks_in_text

    project, config, _, ports, _ = inputs
    config["CLOCK_PORT"] = ["clk", "other_clock"][:clock_count]
    ports = [*ports, {"name": "other_clock", "direction": "input", "width": 1,
                     "indexed": False, "msb": 0, "lsb": 0}]
    docs = project / "phase1/generated_docs"
    clocks = [
        {"domain_kind": "primary", "source_pin": "clk", "period_ns": 20},
        {"domain_kind": "primary", "source_pin": "other_clock", period_field: 50 if period_field == "period_ns" else 20}]
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        *clocks[:clock_count], {"domain_kind": "generated", "source_pin": "derived_clock", "period_ns": 2}]}))
    if override is not None:
        path = docs / "L19_CONSTRAINTS_PDK.json"
        document = json.loads(path.read_text())
        document.setdefault("fields", {})["clock_target"] = {"period_ns": override}
        path.write_text(json.dumps(document))
    text = chip._sdc(project, config, ports)
    periods = [clock["period_ns"] for clock in create_clocks_in_text(text)]
    assert periods == ([override or 20] if clock_count == 1 else [20, 50])
    budget = ((override or 20) if clock_count == 1 else 50) * 0.2
    clock = f"core_clock_{clock_count - 1}" + (" -add_delay" if clock_count == 2 else "")
    assert f"set_input_delay {budget:g} -clock {clock}" in text
    assert f"set_output_delay {budget:g} -clock {clock}" in text


@pytest.mark.parametrize("core_overlap", [False, True])
def test_native_pad_extraction_keeps_full_core_geometry(inputs, tmp_path, core_overlap):
    import shutil
    import subprocess
    from librelane.common import Path as NativePath, Toolbox
    from librelane.flows import Flow
    from librelane.state import DesignFormat, State
    from librelane.steps import Step, StepError

    root = os.environ.get("PDK_ROOT")
    rc = Path(root or "/missing") / "sky130A/libs.tech/magic/sky130A.magicrc"
    if not shutil.which("magic") or not rc.is_file():
        pytest.skip("native Magic and installed PDK required")
    project, config, native, _, _ = inputs
    native["MAGICRC"] = str(rc)
    prepared = chip.prepare(project, config)
    layout = tmp_path / "layout"
    layout.mkdir()
    script = layout / "generate.tcl"
    core = "box 0 0 0 0\ngetcell bad_poly\ngetcell bad_res\n" if core_overlap else ""
    script.write_text('''drc off
crashbackups disable
locking disable
load bad_poly -silent
box 0 0 2um 2um
paint poly
load bad_res -silent
box 0 0 2um 2um
paint npolyres
load neutral_pad -silent
box 0 0 0 0
getcell bad_poly
getcell bad_res
load neutral_core -silent
box 0 0 2um 2um
paint metal1
''' + core + '''load neutral_chip -silent
box 0 0 0 0
getcell neutral_pad
box 10um 0 10um 0
getcell neutral_core
gds write fixture.gds
quit -noprompt
''')
    generated = subprocess.run(["magic", "-dnull", "-noconsole", "-rcfile", str(rc), str(script)],
                               cwd=layout, capture_output=True, text=True)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    lef = _write(tmp_path / "pads.lef", '''VERSION 5.8 ;
MACRO neutral_pad
 CLASS PAD INOUT ;
 ORIGIN 0 0 ;
 SIZE 2 BY 2 ;
 PIN PAD
  DIRECTION INOUT ;
  USE SIGNAL ;
  PORT
   LAYER met1 ;
   RECT 0 0 1 1 ;
  END
 END PAD
END neutral_pad
END LIBRARY
''')
    definition = _write(tmp_path / "fixture.def", '''VERSION 5.8 ;
DESIGN neutral_chip ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 20000 20000 ) ;
END DESIGN
''')
    rtl = _write(tmp_path / "neutral_chip.v", "module neutral_chip(); endmodule\n")
    owner = Flow.factory.get("Classic")({"DESIGN_NAME": "neutral_chip", "PDK": "sky130A",
        "VERILOG_FILES": [str(rtl)], "CLOCK_PORT": None, "CLOCK_PERIOD": 10,
        "MAGIC_EXT_USE_GDS": prepared["MAGIC_EXT_USE_GDS"],
        "MAGICRC": prepared.get("MAGICRC", str(rc))}, design_dir=str(tmp_path), pdk_root=root)
    native_config = owner.config.copy(PAD_LEFS=[NativePath(str(lef))])
    state = State({DesignFormat.GDS: NativePath(str(layout / "fixture.gds")),
                   DesignFormat.DEF: NativePath(str(definition))})
    toolbox = Toolbox(str(tmp_path / "tools"))
    extracted = Step.factory.get("Magic.SpiceExtraction")(native_config, state_in=state).start(
        toolbox=toolbox, step_dir=str(tmp_path / "extract"))
    assert extracted.metrics["magic__illegal_overlap__count"] == int(core_overlap)
    spice = Path(extracted[DesignFormat.SPICE]).read_text()
    assert ".subckt neutral_pad PAD" in spice and "Xneutral_pad" in spice
    checker = Step.factory.get("Checker.IllegalOverlap")(native_config, state_in=extracted)
    if core_overlap:
        with pytest.raises(StepError):
            checker.start(toolbox=toolbox, step_dir=str(tmp_path / "check"))
    else:
        checker.start(toolbox=toolbox, step_dir=str(tmp_path / "check"))
        original = native_config.copy(MAGICRC=NativePath(str(rc)))
        full = Step.factory.get("Magic.DRC")(original, state_in=state).start(
            toolbox=toolbox, step_dir=str(tmp_path / "drc-original"))
        unchanged = Step.factory.get("Magic.DRC")(native_config, state_in=state).start(
            toolbox=toolbox, step_dir=str(tmp_path / "drc-prepared"))
        assert full.metrics["magic__drc_error__count"] > 0
        assert unchanged.metrics["magic__drc_error__count"] == full.metrics["magic__drc_error__count"]
