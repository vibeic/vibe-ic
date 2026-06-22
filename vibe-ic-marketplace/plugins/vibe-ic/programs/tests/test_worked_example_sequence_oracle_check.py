"""Tests for worked_example_sequence_oracle_check.py — the spec-worked-example
self-TB oracle (pulse_detect Moore/Mealy output-timing capture).

§4.05 doctrine: a BLOCKING functional gate, so the load-bearing half is the NEGATIVE
no-leak — it must SKIP unless a complete, unambiguous example parses AND all ports map,
and it must never BLOCK a CORRECT design. The positive case proves it catches the
registered-output (Moore) one-cycle-lag error the worked example forbids.

Validated on the real pulse_detect: the gate AGREES with the host scorer on all 6 blind
attempts (1 correct Mealy PASS, 5 Moore BLOCK) and false-fires on 0/362 corpus goldens.
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import worked_example_sequence_oracle_check as g  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

# A spec disclosing a cycle-by-cycle worked example (same shape as pulse_detect).
SPEC = ("Implement a pulse detector. data_in is a 1-bit input. data_out is 1 the cycle the "
        "pulse completes. For example, if data_in is 01010, the data_out is 00101.")

# CORRECT Mealy form: output is combinational on (state, current input) — same-cycle.
RTL_MEALY = """
module pulse_detect(input clk, input rst_n, input data_in, output data_out);
  localparam IDLE=2'd0, GOT1=2'd1;
  reg [1:0] state;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) state<=IDLE;
    else case(state)
      IDLE: state <= data_in ? GOT1 : IDLE;
      GOT1: state <= data_in ? GOT1 : IDLE;
      default: state <= IDLE;
    endcase
  assign data_out = (state==GOT1) & ~data_in;   // Mealy: same-cycle on the trailing 0
endmodule
"""

# WRONG Moore form: output registered → lags one cycle.
RTL_MOORE = """
module pulse_detect(input clk, input rst_n, input data_in, output reg data_out);
  localparam IDLE=2'd0, GOT1=2'd1;
  reg [1:0] state;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin state<=IDLE; data_out<=1'b0; end
    else case(state)
      IDLE: begin state <= data_in ? GOT1 : IDLE; data_out<=1'b0; end
      GOT1: begin state <= data_in ? GOT1 : IDLE; data_out <= ~data_in; end
      default: begin state<=IDLE; data_out<=1'b0; end
    endcase
endmodule
"""


# -------- parse --------
def test_parse_example_extracts_ports_and_bits():
    assert g.parse_example(SPEC) == ("data_in", "data_out", "01010", "00101")


def test_parse_example_none_when_no_example():
    assert g.parse_example("A plain spec with no bitstring example at all.") is None


def test_ports_and_clk_reset_detection():
    name, ports = g._ports(RTL_MEALY)
    assert name == "pulse_detect"
    assert ports.get("data_in") == ("input", True)
    assert ports.get("data_out") == ("output", True)
    assert g._find_clk_reset(ports) == ("clk", "rst_n", "low")


# -------- SKIP no-leak (no iverilog needed) --------
def test_skip_when_no_worked_example():
    r = g.analyze(RTL_MEALY, "no example here")
    assert r["verdict"] == "SKIP" and r["applicable"] is False


def test_skip_when_ports_not_1bit_io():
    rtl = "module m(input clk, input rst_n, input [7:0] data_in, output [7:0] data_out); endmodule"
    r = g.analyze(rtl, SPEC)
    assert r["verdict"] == "SKIP"


# -------- functional verdict (needs iverilog) --------
@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_correct_mealy_design_passes():
    r = g.analyze(RTL_MEALY, SPEC)
    assert r["applicable"] is True
    assert r["verdict"] == "PASS", r  # §4.05: a correct design is never blocked


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_registered_moore_design_is_blocked():
    r = g.analyze(RTL_MOORE, SPEC)
    assert r["applicable"] is True
    assert r["verdict"] == "BLOCK", r  # the one-cycle-lag error the example forbids


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_cli_block_returns_1(tmp_path, capsys):
    rtl = tmp_path / "d.v"; rtl.write_text(RTL_MOORE)
    spec = tmp_path / "s.txt"; spec.write_text(SPEC)
    rc = g.main(["--rtl", str(rtl), "--spec", str(spec)])
    assert rc == 1
    assert "BLOCK" in capsys.readouterr().out


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_cli_pass_returns_0(tmp_path):
    rtl = tmp_path / "d.v"; rtl.write_text(RTL_MEALY)
    spec = tmp_path / "s.txt"; spec.write_text(SPEC)
    assert g.main(["--rtl", str(rtl), "--spec", str(spec)]) == 0


def test_cli_missing_files_arg_error(tmp_path):
    assert g.main(["--rtl", str(tmp_path / "no.v"), "--spec", str(tmp_path / "no.txt")]) == 2


# -------- WIRED into the Shape-B emit guard --------
@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_shape_b_guard_blocks_moore_via_worked_example(tmp_path):
    import shape_b_sample_export as sb
    p = tmp_path / "pulse_detect.v"; p.write_text(RTL_MOORE)
    ok, problems = sb.guard_export(p, SPEC)
    assert ok is False
    assert any("worked-example oracle" in s for s in problems), problems


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_shape_b_guard_passes_correct_mealy(tmp_path):
    import shape_b_sample_export as sb
    p = tmp_path / "pulse_detect.v"; p.write_text(RTL_MEALY)
    _ok, problems = sb.guard_export(p, SPEC)
    assert not any("worked-example oracle" in s for s in problems), problems


def test_shape_b_guard_no_prompt_skips_oracle(tmp_path):
    """No prompt text → the oracle stays disarmed (fail-safe), no false problem."""
    import shape_b_sample_export as sb
    p = tmp_path / "pulse_detect.v"; p.write_text(RTL_MOORE)
    _ok, problems = sb.guard_export(p, "")  # empty prompt
    assert not any("worked-example oracle" in s for s in problems), problems
