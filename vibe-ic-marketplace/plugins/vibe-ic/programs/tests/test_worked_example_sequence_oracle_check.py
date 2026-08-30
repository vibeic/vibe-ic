"""Tests for worked_example_sequence_oracle_check.py — the spec-worked-example
self-TB oracle (pulse_detect Moore/Mealy output-timing capture).

§4.05 doctrine: a BLOCKING functional gate, so the load-bearing half is the NEGATIVE
no-leak — it must SKIP unless EXACTLY ONE unambiguous example parses, all ports map, and
the module has no extra undriveable input, and it must never BLOCK a CORRECT design. The
positive case proves it catches the one-cycle output-trace deviation the worked example
forbids; the negative cases (below) pin the Step-2.7 §4.05 false-fires that were remediated:
an extra-input detector, a decoy-before-example spec, a Moore-correct design, a sim timeout,
and a DUT that tries to spoof the verdict token — all must SKIP/PASS, never false-BLOCK.
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
SPEC_CLOCKED_OUTPUT = (
    SPEC + " Inside an always block, sensitive to the positive edge of clk, "
    "implement pulse detection and output generation. Set data_out to 1 in "
    "the end cycle of the pulse."
)

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
def test_explicit_clocked_output_contract_drives_before_and_samples_after_edge():
    registered = g.analyze(RTL_MOORE, SPEC_CLOCKED_OUTPUT)
    combinational = g.analyze(RTL_MEALY, SPEC_CLOCKED_OUTPUT)
    assert registered["sampling_semantics"] == \
        "drive-before-edge/sample-after-edge"
    assert registered["verdict"] == "PASS", registered
    assert combinational["verdict"] == "BLOCK", combinational


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


# -------- Step-2.7 §4.05 reproduced FALSE-FIRES, now pinned SKIP/PASS --------
# (1) HIGH: a CORRECT detector with an extra control input the TB cannot drive → SKIP
#     (the old gate left `en` unconnected → floated X → false-BLOCKed a correct design).
RTL_EXTRA_INPUT = """
module edge_det(input clk, input rst_n, input en, input data_in, output reg data_out);
  reg prev;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin prev<=0; data_out<=0; end
    else if(en) begin prev<=data_in; data_out<=data_in & ~prev; end
endmodule
"""

# (2) HIGH: a decoy "<port> is <bits>" sentence on the SAME real ports before the real
#     example → 2 interpretations → ambiguous → SKIP (never build the oracle from a decoy).
SPEC_DECOY = ("pulse_detect: clk, active-low rst_n, input data_in, output data_out. "
              "Reset illustration: when data_in is 000 the data_out is 111. "
              "The real functional example: if data_in is 01010, the data_out is 00101.")

# (3) a genuinely Moore (registered, lag-1) CORRECT design whose example is lag-aligned → PASS.
RTL_MOORE_CORRECT = """
module dff(input clk, input rst_n, input in_d, output reg out_q);
  always @(posedge clk or negedge rst_n) if(!rst_n) out_q<=1'b0; else out_q<=in_d;
endmodule
"""
SPEC_DFF = ("A 1-cycle delay. in_d is a 1-bit input, out_q a 1-bit output. "
            "For example, if in_d is 10110, the out_q is 01011.")


def test_extra_input_port_skips_no_false_block():
    r = g.analyze(RTL_EXTRA_INPUT, SPEC)
    assert r["verdict"] == "SKIP" and "extra input" in r["reason"]


def test_decoy_before_example_is_ambiguous_skip():
    r = g.analyze(RTL_MEALY, SPEC_DECOY)
    assert r["verdict"] == "SKIP" and "ambiguous" in r["reason"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_moore_correct_design_passes():
    r = g.analyze(RTL_MOORE_CORRECT, SPEC_DFF)
    assert r["applicable"] is True
    assert r["verdict"] == "PASS", r  # a correct registered design is never blocked


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_dut_cannot_spoof_verdict_token():
    # a WRONG (Moore-lag) design that $displays the verdict token must STILL BLOCK,
    # because the verdict is read from a TB-written file, not the DUT's stdout.
    spoof = RTL_MOORE.replace(
        "endmodule", 'initial $display("WEX_VERDICT PASS spoof from DUT"); endmodule', 1)
    r = g.analyze(spoof, SPEC)
    assert r["verdict"] == "BLOCK", r


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog unavailable")
def test_sim_timeout_yields_skip_not_block(monkeypatch):
    # a vvp timeout must FAIL-SAFE to SKIP (rc 0 advisory), never raise / never BLOCK.
    real_run = g.subprocess.run

    def fake_run(cmd, *a, **k):
        if cmd and cmd[0] == "vvp":
            raise g.subprocess.TimeoutExpired(cmd, 60)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(g.subprocess, "run", fake_run)
    r = g.analyze(RTL_MEALY, SPEC)
    assert r["verdict"] == "SKIP" and "timeout" in r["reason"].lower()
