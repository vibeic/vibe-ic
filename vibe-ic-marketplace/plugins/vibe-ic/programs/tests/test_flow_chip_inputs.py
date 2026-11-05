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
 cell (fixture_io__input) {
  pin (PAD) {
   direction : input;
   is_pad : true;
  }
  pin (Y) {
   direction : output;
   function : "PAD";
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
    assert "inout wire [5:2] data" in wrapper
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


def test_missing_document_io_delay_is_named(inputs):
    project, config, _, ports, _ = inputs
    (project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text("{}")
    with pytest.raises(FileNotFoundError, match="L19.constraints.io_delay"):
        chip._sdc(project, config, ports)


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
    assert "inout wire [5:2] \\data.value " in wrapper
    assert ".\\data.value (_core_port_2)" in wrapper
    assert ".PAD(\\data.value [5])" in wrapper
