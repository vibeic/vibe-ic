#!/usr/bin/env python3
"""Coverage must be attributed to a testbench with functional stimulus.

These generic fixtures reproduce the observed failure shapes without embedding
a design, PDK or vendor identity.  A checked-in activity testbench supplies the
real-artefact reverse control.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import verilator_coverage_measure as V   # noqa: E402
from _hostpaths import require_repo  # noqa: E402

_INERT_TB = """\
// A connectivity-only harness.
module tb_top_full;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  reg [31:0] wdata_i = 32'h0;
  wire [31:0] rdata_o;
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .wdata_i(wdata_i),
             .rdata_o(rdata_o));
  initial begin rst_ni <= 1'b1; #100 $finish; end
endmodule
"""

_DRIVING_TB = """\
module tb_vec;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  bus_pkg::req_t bus_raw;
  bus_pkg::req_t bus_i;
  intg_gen u_intg (.bus_i(bus_raw), .bus_o(bus_i));
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .bus_i(bus_i));
  initial begin
    rst_ni <= 1'b1;
    bus_raw.valid <= 1'b1;
    bus_raw.addr  <= 32'h10;
    #100 $finish;
  end
endmodule
"""

_OUTPUT_TO_MONITOR_TB = """\
module tb_monitor;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  reg [7:0] cmd_i = 8'h00;
  wire [7:0] status_o;
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .cmd_i(cmd_i),
             .status_o(status_o));
  monitor u_monitor (.sample_i(status_o));
  initial begin rst_ni <= 1'b1; #100 $finish; end
endmodule
"""


def test_a_direction_suffixed_clock_and_reset_are_infrastructure():
    for name in ("clk_i", "rst_ni", "clk", "rst_n", "sclk_i"):
        assert V._cov_is_clock_or_reset(name), name
    for name in ("wdata_i", "data_o", "addr_i", "bus_i",
                 "clk_enable_i", "reset_value_i"):
        assert not V._cov_is_clock_or_reset(name), name


def test_a_connectivity_only_testbench_drives_nothing(tmp_path):
    tb = tmp_path / "tb_top_full.v"
    tb.write_text(_INERT_TB)
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    assert a["driven"] == [], a
    assert set(a["clock_reset"]) >= {"clk_i", "rst_ni"}
    assert "wdata_i" in a["inert"]


def test_a_struct_field_assignment_is_functional_stimulus(tmp_path):
    tb = tmp_path / "tb_vec.v"
    tb.write_text(_DRIVING_TB)
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    # Only an observed assignment produces the vocabulary. Merely sharing a
    # signal between instances does not establish which instance drives it.
    assert "bus_raw" in a["driven"], a
    assert "bus_i" not in a["driven"], a


def test_a_dut_output_shared_with_a_monitor_is_not_invented_as_stimulus(
        tmp_path):
    tb = tmp_path / "tb_monitor.v"
    tb.write_text(_OUTPUT_TO_MONITOR_TB)
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    assert a["driven"] == [], a
    assert "cmd_i" in a["inert"], a
    assert "status_o" not in a["driven"], a


def test_discovery_prefers_the_testbench_that_drives(tmp_path):
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True)
    (tmp_path / "phase2/stage1/rtl/dut.sv").write_text(
        "module dut(input clk_i); endmodule\n")
    fs = tmp_path / "phase2/stage1/sim_full_stack"
    fs.mkdir(parents=True)
    (fs / "tb_top_full.v").write_text(_INERT_TB)
    unit = tmp_path / "phase2/stage1/sim/tb"
    unit.mkdir(parents=True)
    (unit / "tb_vec.v").write_text(_DRIVING_TB)
    _rtl, tb = V.discover_measure_inputs(tmp_path)
    assert tb and Path(tb).name == "tb_vec.v", tb


def test_discovery_keeps_the_old_first_hit_when_nothing_drives(tmp_path):
    fs = tmp_path / "phase2/stage1/sim_full_stack"
    fs.mkdir(parents=True)
    (fs / "tb_top_full.v").write_text(_INERT_TB)
    _rtl, tb = V.discover_measure_inputs(tmp_path)
    assert tb and Path(tb).name == "tb_top_full.v"


def test_a_helper_module_is_resolved_from_the_design_input_only(tmp_path):
    (tmp_path / "input/vendor_rtl").mkdir(parents=True)
    (tmp_path / "input/vendor_rtl/intg_gen.sv").write_text(
        "module intg_gen(input a); endmodule\n")
    (tmp_path / "input/golden").mkdir(parents=True)
    (tmp_path / "input/golden/dut.sv").write_text(
        "module dut(input a); endmodule\n")
    tb = tmp_path / "tb_vec.v"
    tb.write_text(_DRIVING_TB)
    got = V._cov_sources_for_tb(tmp_path, tb, [])
    assert [Path(g).name for g in got] == ["intg_gen.sv"], got


def test_checked_in_activity_testbench_remains_functional():
    tb = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "ppa", "power", "activity_basis_pair", "tb.v")
    a = V.functional_stimulus_audit(tb)
    assert a["decidable"]
    assert set(a["clock_reset"]) == {"clk", "rst"}, a
    assert set(a["driven"]) == {"x", "y"}, a


def test_check_refuses_to_grade_a_connectivity_only_measurement(tmp_path,
                                                                capsys):
    import argparse
    import json
    tb = tmp_path / "tb_top_full.v"
    tb.write_text(_INERT_TB)
    cov = tmp_path / "coverage_verilator.json"
    cov.write_text(json.dumps({
        "tool": "verilator", "measurement_mode": "measure-tb",
        "testbench": str(tb), "rtl_sources": [], "scope_files": [],
        "per_file": {}, "format_detected": "v5",
        "totals": {"line": {"covered": 340, "total": 547, "pct": 62.16},
                   "toggle": {"covered": 10835, "total": 64382, "pct": 16.83},
                   "branch": {"covered": 325, "total": 940, "pct": 34.57}}}))
    args = argparse.Namespace(coverage_json=str(cov), min_line=70.0,
                              min_toggle=60.0, min_branch=70.0,
                              verilator_bin="verilator")
    rc = V.cmd_check(args)
    out = capsys.readouterr().out
    assert rc == 1
    assert "NO FUNCTIONAL STIMULUS IN THE COVERAGE BUILD" in out
    assert "62.16" in out and "NOT graded here" in out
