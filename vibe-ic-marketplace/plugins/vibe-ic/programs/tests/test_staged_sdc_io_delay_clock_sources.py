"""Native staged-SDC parity: preserve data delay while excluding clock sources."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys

import pytest

PROG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as p3
import librelane_prelayout as prelayout

pytestmark = pytest.mark.skipif(not shutil.which("sta"), reason="native OpenSTA required")

LIBERTY = """library(neutral) {
  delay_model : table_lookup;
  time_unit : "1ns";
  voltage_unit : "1V";
  current_unit : "1mA";
  capacitive_load_unit (1, pf);
  nom_process : 1; nom_voltage : 1; nom_temperature : 25;
  cell(neutral_buf) {
    area : 1;
    pin(A) { direction : input; capacitance : 0.01; }
    pin(Z) { direction : output; function : "A";
      timing() { related_pin : "A"; timing_sense : positive_unate;
        cell_rise(scalar) { values("0.1"); }
        cell_fall(scalar) { values("0.1"); }
        rise_transition(scalar) { values("0.01"); }
        fall_transition(scalar) { values("0.01"); }
      }
    }
  }
}
"""


def staged(two=True):
    text = "create_clock -name core_launch -period 16 [get_ports clock_a_i]\n"
    if two:
        text += "create_clock -name aux_capture -period 31 [get_ports clock_b_i]\n"
    return text


def emit(project, text):
    source = project / "input/constraints/implementation.sdc"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text)
    emitted, info = p3._ensure_staged_sdc_io_delay(text, project)
    deck = project / "produced.sdc"
    deck.write_text(emitted)
    return deck, info


def native(project, deck, two=True):
    lib = project / "neutral.lib"
    lib.write_text(LIBERTY)
    rtl = project / "neutral.v"
    rtl.write_text("module neutral_boundary(input clock_a_i, "
        + ("input clock_b_i, " if two else "")
        + "input data_i, output data_o);\n"
          "neutral_buf u_buf(.A(data_i), .Z(data_o));\nendmodule\n")
    script = project / "native.tcl"
    script.write_text(f"read_liberty {{{lib}}}\nread_verilog {{{rtl}}}\n"
        f"link_design neutral_boundary\nread_sdc {{{deck}}}\n"
        'puts "DATA_INPUTS [get_full_name [all_inputs -no_clocks]]"\n'
        'puts "CORE_PERIOD [get_property [get_clocks core_launch] period]"\n'
        + ('puts "AUX_PERIOD [get_property [get_clocks aux_capture] period]"\n' if two else "")
        + "report_checks -from [get_ports data_i] -to [get_ports data_o] -format full_clock_expanded\nexit\n")
    argv = [shutil.which("sta"), "-no_init", "-exit", str(script)]
    done = subprocess.run(argv, capture_output=True, text=True)
    log = done.stdout + done.stderr
    (project / "native.log").write_text(log)
    (project / "execution.json").write_text(json.dumps({"argv": argv,
        "natural_rc": done.returncode, "stdout": done.stdout, "stderr": done.stderr}, indent=2))
    assert done.returncode == 0, log
    assert not re.search(r"^Error(?: \d+)?:", log, re.M), log
    assert "Creating black box" not in log, log
    assert re.search(r"^DATA_INPUTS data_i$", log, re.M), log
    assert float(re.search(r"^CORE_PERIOD (\S+)$", log, re.M)[1]) == 16, log
    if two:
        assert float(re.search(r"^AUX_PERIOD (\S+)$", log, re.M)[1]) == 31, log
    assert "2.00" in next(line for line in log.splitlines() if "input external delay" in line), log
    return prelayout.sdc_diagnostics(log, deck), log


@pytest.mark.parametrize("two", [False, True], ids=["one-clock", "two-clocks"])
def test_added_io_delay_excludes_clock_sources_but_times_data(tmp_path, two):
    source = staged(two)
    deck, info = emit(tmp_path, source)
    assert deck.read_text().startswith(source)
    assert (info["added_input_delay"], info["added_output_delay"]) == ("2", "2")
    assert "set_output_delay 2 -clock core_launch [all_outputs]" in deck.read_text()
    diagnostics, log = native(tmp_path, deck, two)
    assert len(diagnostics) == 0, {"actual_native_diagnostics": diagnostics, "log": log}


def test_design_declared_good_delays_are_byte_identical(tmp_path):
    source = staged() + "set_input_delay 2 -clock core_launch [all_inputs -no_clocks]\n" \
        + "set_output_delay 2 -clock core_launch [all_outputs]\n"
    deck, info = emit(tmp_path, source)
    assert deck.read_text() == source
    assert info["added_input_delay"] is None and info["added_output_delay"] is None
    diagnostics, log = native(tmp_path, deck)
    assert diagnostics == [], log


def test_declared_bad_clock_delay_is_preserved_and_native_still_refuses(tmp_path):
    source = staged() + "set_input_delay 2 -clock core_launch [all_inputs]\n" \
        + "set_output_delay 2 -clock core_launch [all_outputs]\n"
    deck, info = emit(tmp_path, source)
    assert deck.read_text() == source
    diagnostics, log = native(tmp_path, deck)
    assert [row["id"] for row in diagnostics] == [441], log
