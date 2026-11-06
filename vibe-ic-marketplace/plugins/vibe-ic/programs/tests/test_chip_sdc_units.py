import json
import re
import shutil
import subprocess

import pytest

import flow_chip_inputs as chip


@pytest.mark.parametrize("time_unit,cap_unit,scale", [("ns", "pf", 1), ("ps", "ff", 1000)])
def test_generated_sdc_preserves_physical_clock_io_and_environment(tmp_path, time_unit, cap_unit, scale):
    sta = shutil.which("sta")
    if sta is None:
        pytest.skip("Native OpenSTA required for generated SDC physical units")
    library = tmp_path / "cells.lib"
    library.write_text(f'''library (linked) {{
      delay_model : table_lookup;
      time_unit : "1{time_unit}";
      voltage_unit : "1V"; current_unit : "1mA";
      capacitive_load_unit (1,{cap_unit});
      nom_voltage : 1; nom_temperature : 25; nom_process : 1;
      lu_table_template (edge) {{
        variable_1 : input_net_transition;
        index_1 ("{.1 * scale}, {1.3 * scale}");
      }}
      cell (receiver) {{
        pin (A) {{ direction : input; is_pad : true; max_transition : {2 * scale}; }}
        pin (Z) {{ direction : output; function : "A";
          timing () {{ related_pin : "A"; timing_sense : positive_unate;
            cell_rise (edge) {{ values ("{.1 * scale}, {.2 * scale}"); }}
            cell_fall (edge) {{ values ("{.1 * scale}, {.2 * scale}"); }}
          }}
        }}
      }}
    }}''')
    unlinked = tmp_path / "unlinked.lib"
    unlinked.write_text(library.read_text().replace("library (linked)", "library (unlinked)")
                        .replace(f'{.1 * scale}, {1.3 * scale}', f'{.04 * scale}, {.8 * scale}'))
    netlist = tmp_path / "chip.v"
    netlist.write_text('''module chip(input [1:1] clk, input aux_clk,
      input [5:4] data, output [8:7] result);
      receiver u1(.A(data[5]), .Z(result[8]));
      receiver u2(.A(data[4]), .Z(result[7]));
    endmodule''')
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"domain_kind": "primary", "source_pin": "clk[1]", "period_ns": 24},
        {"domain_kind": "primary", "source_pin": "aux_clk", "period_ns": 40}]}))
    config = {"PDK": "neutral", "CLOCK_PORT": ["clk[1]", "aux_clk"], "CLOCK_PERIOD": 24, "IO_DELAY_CONSTRAINT": 20,
              "CLOCK_UNCERTAINTY_CONSTRAINT": .25, "CLOCK_TRANSITION_CONSTRAINT": .15,
              "MAX_TRANSITION_CONSTRAINT": 3, "MAX_FANOUT_CONSTRAINT": 4,
              "TIME_DERATING_CONSTRAINT": 5, "OUTPUT_CAP_LOAD": 3530,
              "PAD_LIBS": {"*": [str(library), str(unlinked)]}}
    ports = [{"name": "clk", "direction": "input", "indexed": True, "msb": 1, "lsb": 1},
             {"name": "aux_clk", "direction": "input", "indexed": False},
             {"name": "data", "direction": "input", "indexed": True, "msb": 5, "lsb": 4},
             {"name": "result", "direction": "output", "indexed": True, "msb": 8, "lsb": 7}]
    generated = tmp_path / "generated.sdc"
    generated.write_text(chip._sdc(tmp_path, config, ports, {"receiver"}))
    effective = tmp_path / "effective.sdc"
    script = tmp_path / "check.tcl"
    script.write_text(f'''read_liberty {{{library}}}
read_verilog {{{netlist}}}
link_design chip
read_sdc {{{generated}}}
puts "TIME_SCALE [sta::unit_scale time]"
puts "CAP_SCALE [sta::unit_scale capacitance]"
write_sdc -digits 9 {{{effective}}}
exit
''')
    run = subprocess.run([sta, "-no_init", "-no_splash", "-exit", str(script)],
                         capture_output=True, text=True, check=True)
    assert "Error" not in run.stdout + run.stderr, run.stdout + run.stderr
    time_scale = float(re.search(r"TIME_SCALE (\S+)", run.stdout)[1])
    cap_scale = float(re.search(r"CAP_SCALE (\S+)", run.stdout)[1])
    text = effective.read_text()
    clocks = re.findall(r"create_clock -name (\S+) -period ([\d.eE+-]+).*", text)
    assert [(name, float(value) * time_scale) for name, value in clocks] == [
        ("core_clock_0", pytest.approx(24e-9, rel=1e-6, abs=1e-18)),
        ("core_clock_1", pytest.approx(40e-9, rel=1e-6, abs=1e-18))], text
    assert re.findall(r"create_clock -name (\S+).*\[get_ports \{([^}]+)\}\]", text) == [
        ("core_clock_0", "clk[1]"), ("core_clock_1", "aux_clk")], text
    for command, expected in (("set_clock_uncertainty", .25e-9), ("set_clock_transition", .15e-9)):
        values = re.findall(r"^" + command + r" ([\d.eE+-]+)", text, re.M)
        assert len(values) == 2, text
        assert [float(value) * time_scale for value in values] == pytest.approx(
            [expected, expected], rel=1e-6, abs=1e-18), text
    for command, names in (("set_input_delay", ["data[4]", "data[5]"]),
                           ("set_output_delay", ["result[7]", "result[8]"])):
        delays = re.findall(r"^" + command + r" ([\d.eE+-]+) -clock \[get_clocks \{(\S+)\}\].*"
                            r"\[get_ports \{([^}]+)\}\]", text, re.M)
        assert len(delays) == 4, text
        assert {(clock, port): float(value) * time_scale for value, clock, port in delays} == pytest.approx(
            {(clock, port): delay for clock, delay in (("core_clock_0", 4.8e-9), ("core_clock_1", 8e-9))
             for port in names}, rel=1e-6, abs=1e-18), text
    loads = re.findall(r"^set_load -pin_load ([\d.eE+-]+) \[get_ports \{([^}]+)\}\]", text, re.M)
    assert len(loads) == 2, text
    assert {port: float(value) * cap_scale for value, port in loads} == pytest.approx(
        {"result[7]": 3530e-15, "result[8]": 3530e-15}, rel=1e-6, abs=1e-21), text
    edges = re.findall(r"^set_input_transition -(min|max) ([\d.eE+-]+) \[get_ports \{([^}]+)\}\]", text, re.M)
    assert len(edges) == 8, text
    assert {(limit, port): float(value) * time_scale for limit, value, port in edges} == pytest.approx(
        {(limit, port): edge for limit, edge in (("min", .1e-9), ("max", 1.3e-9))
         for port in ("clk[1]", "aux_clk", "data[5]", "data[4]")}, rel=1e-6, abs=1e-18), text
    assert float(re.search(r"set_max_transition (\S+) \[current_design\]", text)[1]) * time_scale == pytest.approx(3e-9, rel=1e-6, abs=1e-18)
    assert float(re.search(r"set_max_fanout (\S+) \[current_design\]", text)[1]) == 4
    for limit, expected in (("early", .95), ("late", 1.05)):
        assert float(re.search(r"set_timing_derate -" + limit + r" (\S+)", text)[1]) == pytest.approx(expected)
    original = tmp_path / "original.sdc"
    original.write_text(text + "set_clock_groups -asynchronous -group core_clock_0 -group core_clock_1\n")
    before = original.read_bytes()
    config["PNR_SDC_FILE"] = str(original)
    assert chip._sdc(tmp_path, config, ports, {"receiver"}) == before.decode()
    assert original.read_bytes() == before
