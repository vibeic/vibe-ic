"""Chip preparation uses elaborated interfaces and native library geometry."""
import json
import os
from pathlib import Path

import pytest

import flow_chip_inputs as chip


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
    assert "output wire result" in wrapper
    assert "wire [5:2] _core_port_2;" in wrapper
    assert ".PAD(data[5])" in wrapper
    assert ".Y(_core_port_2[5])" in wrapper
    assert "fixture_tie_hi" in wrapper
    assert ".A(_core_port_3)" in wrapper
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


def test_native_timing_environment_and_pad_edge_bracket_reach_sdc(inputs):
    project, config, native, _, _ = inputs
    native.update(CLOCK_UNCERTAINTY_CONSTRAINT=0.25, CLOCK_TRANSITION_CONSTRAINT=0.15,
                  TIME_DERATING_CONSTRAINT=5, MAX_FANOUT_CONSTRAINT=4,
                  MAX_TRANSITION_CONSTRAINT=3, MAX_CAPACITANCE_CONSTRAINT=0.2, OUTPUT_CAP_LOAD=10)
    result = chip.prepare(project, config)
    text = Path(result["PNR_SDC_FILE"]).read_text()
    assert "set_timing_derate -late 1.05" in text
    assert "set_timing_derate -early 0.949999" in text
    assert "set_clock_uncertainty 0.25" in text
    assert "set_clock_transition 0.15" in text
    assert "set_max_transition 3 [current_design]" in text
    assert "set_max_capacitance 0.2 [current_design]" in text
    assert "set_load 0.01" in text
    assert "set _chip_pad_max 1" in text
    assert "set _chip_pad_min 0.08" in text


@pytest.mark.parametrize("linked, maximum, minimum", [("fast_view", "0.8", "0.04"),
                                                       ("slow_view", "1.3", "0.1")])
def test_pad_edges_follow_the_native_linked_corner(inputs, tmp_path, linked, maximum, minimum):
    import shutil
    import subprocess

    interpreter = shutil.which("tclsh")
    command = [interpreter] if interpreter else [shutil.which("openroad"), "-no_init", "-no_splash", "-exit"]
    if command[0] is None:
        pytest.skip("A native Tcl interpreter is required")
    project, config, native, _, _ = inputs
    original = Path(native["PAD_LIBS"]["*"][0]).read_text()
    paths = []
    for name, bounds in (("fast_view", "0.04, 0.8"), ("slow_view", "0.10, 1.3")):
        path = tmp_path / (name + ".lib")
        text = original.replace("library (fixture)", f"library ({name})")
        text = text.replace("0.08, 1.0", bounds).replace("default_max_transition : 1;", "default_max_transition : 2;")
        path.write_text(text)
        paths.append(str(path))
    native["PAD_LIBS"] = {"*": paths}
    result = chip.prepare(project, config)
    script = tmp_path / "read.sdc.tcl"
    script.write_text('''proc get_ports args {return PORTS}
proc get_clocks args {return CLOCKS}
proc create_clock args {}
proc set_units args {}
proc set_input_delay args {}
proc set_output_delay args {}
proc set_input_transition args {puts "EDGE $args"}
proc get_libs args {
    if {[lindex $args end] eq $::linked} {return LIB}
    return {}
}
''' + f"set ::linked {linked}\nsource {{{result['PNR_SDC_FILE']}}}\n")
    completed = subprocess.run([*command, str(script)], capture_output=True, text=True, check=True)
    assert f"EDGE -max {maximum} PORTS" in completed.stdout
    assert f"EDGE -min {minimum} PORTS" in completed.stdout


def test_input_pad_edge_coverage_cannot_omit_a_selected_master(inputs):
    project, config, native, ports, _ = inputs
    with pytest.raises(FileNotFoundError, match="characterized off-chip"):
        chip._sdc(project, {**native, **config}, ports, {"fixture_io__input", "missing_receiver"})


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
    assert "set_false_path -from [get_ports -regexp" in sdc
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
