"""ORGANIC #770 round-3 — the 3 residual prose-FPs that still hard-blocked on
v1.0.87 (the r2 provenance completion cleared 6 of 9; these 3 needed wider
detectors). Each is a genuine FP: the RTL is correct + spec-faithful.

  1. spec_coverage handshake — a valid/ready DUT port DRIVEN by a stall-loop /
     expression (`m_tready = (i % 3 != 0)`), not literal 0/1, now counts as
     exercising the handshake (axis_joiner_0001).
  2. spec_coverage enum_set — a single-signal packed CONCATENATION
     `name = {fields}` (incl. an indented / prose-prefixed assignment) is
     downgraded to advisory; only STRONG membership vocabulary ('any other value
     is reserved', 'one of the following', 'accepts only') keeps a value-set
     blocking (configurable_digital_low_pass_filter_0001).
  3. rtl_hygiene case-no-default — a symbolic-localparam FSM declared on ONE
     comma-separated line (`localparam IDLE=2'd0, LOAD=2'd1, ...`) now resolves
     to its values and is recognised exhaustive (binary_search_tree_sorting_0001).

§4.05 NO-LEAK (each must continue to hold): a handshake the TB never drives at
all / drives only a decoy non-DUT reg; a true value-enum set left uncovered; a
non-exhaustive case with no default — ALL still hard-BLOCK.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as SC  # noqa: E402
import rtl_hygiene_lint as RH  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"
_HYGIENE = _PROGRAMS / "rtl_hygiene_lint.py"

_AJ_SPEC = ("# AXIS joiner\nThe joiner uses a standard valid/ready handshake "
            "with backpressure on the master stream.\n")
_AJ_RTL = ("module axis_joiner(input clk, input s_tvalid, output s_tready, "
           "output reg m_tvalid, input m_tready, output [7:0] m_tdata);\n"
           "endmodule\n")


def _speccov(tmp_path, spec, tb, rtl):
    (tmp_path / "s.md").write_text(spec)
    (tmp_path / "tb.sv").write_text(tb)
    (tmp_path / "r.sv").write_text(rtl)
    return subprocess.run(
        [sys.executable, str(_SPEC_COV), "--spec", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)


# ── FP1: loop/expression-driven handshake ────────────────────────────────────
def test_770r3_fp_loop_driven_handshake_covered(tmp_path):
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready; integer i;\n"
          "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), "
          ".m_tvalid(), .m_tready(m_tready), .m_tdata());\n"
          "initial begin s_tvalid=1; for(i=0;i<8;i=i+1) begin "
          "m_tready=(i%3!=0); #5; end $finish; end endmodule\n")
    r = _speccov(tmp_path, _AJ_SPEC, tb, _AJ_RTL)
    assert r.returncode == 0, r.stdout


def test_770r3_noleak_decoy_nonport_toggle_still_blocks(tmp_path):
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready; reg internal_req; "
          "integer i;\n"
          "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), "
          ".m_tvalid(), .m_tready(m_tready), .m_tdata());\n"
          "initial begin m_tready=1; s_tvalid=1; for(i=0;i<4;i=i+1) begin "
          "internal_req=(i%2); #5; end $finish; end endmodule\n")
    r = _speccov(tmp_path, _AJ_SPEC, tb, _AJ_RTL)
    assert r.returncode == 1, r.stdout


def test_770r3_noleak_handshake_never_driven_still_blocks(tmp_path):
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
          "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), "
          ".m_tvalid(), .m_tready(m_tready), .m_tdata());\n"
          "initial begin m_tready=1; s_tvalid=1; #20; $finish; end endmodule\n")
    r = _speccov(tmp_path, _AJ_SPEC, tb, _AJ_RTL)
    assert r.returncode == 1, r.stdout


# ── FP2: single-signal packed concatenation downgrade ────────────────────────
_LPF_RTL = ("module lpf(input clk, input [23:0] data_in, output reg [15:0] y); "
            "always @(posedge clk) y <= data_in[15:0]; endmodule\n")
_LPF_TB = ("module tb; reg clk=0; reg [23:0] data_in; wire [15:0] y; "
           "lpf u(clk,data_in,y); initial begin data_in=24'hABCDEF; #5; "
           "$finish; end endmodule\n")


def test_770r3_fp_single_signal_concat_is_advisory(tmp_path):
    spec = ("# Configurable digital low-pass filter\n\nThe filter supports "
            "configurable coefficient banks. Each tap value is one of the "
            "calibrated levels. The coefficient register is assembled as:\n"
            "  coeffs = {4'b1100, 4'b0011, 4'b1010, 4'b0101}\n"
            "and the input sample shift register is "
            "data_in = {6'b001100, 6'b110011, 6'b010101}.\n")
    r = _speccov(tmp_path, spec, _LPF_TB, _LPF_RTL)
    assert r.returncode == 0, r.stdout


def test_770r3_concat_helper_handles_indented_and_prose_prefixed():
    import re
    txt = ("  coeffs = {4'b1100, 4'b0011}\n"
           "the input register is data_in = {6'b001100, 6'b110011}\n")
    ms = list(re.finditer(SC._ENUM_SET_RE, txt))
    assert all(SC._is_single_signal_concat_assignment(txt, m) for m in ms)


def test_770r3_noleak_value_set_with_strong_vocab_still_blocks(tmp_path):
    spec = ("# Cfg\nThe gain field accepts only the following discrete "
            "calibrated levels; any other value is reserved. "
            "GAIN_LEVELS = {8'h10, 8'h20, 8'h40, 8'h80}.\n")
    r = _speccov(tmp_path, spec, _LPF_TB, _LPF_RTL)
    assert r.returncode == 1, r.stdout


def test_770r3_noleak_membership_set_still_blocks(tmp_path):
    spec = ("# Decoder\nThe opcode is one of the following: "
            "{8'h01, 8'h02, 8'h03}. Any other value is reserved.\n")
    r = _speccov(tmp_path, spec, _LPF_TB, _LPF_RTL)
    assert r.returncode == 1, r.stdout


# ── FP3: comma-declared symbolic-localparam FSM exhaustiveness ────────────────
def test_770r3_fp_symbolic_localparam_fsm_exhaustive(tmp_path):
    rtl = ("module bst(input clk, input [1:0] sel, output reg [3:0] o);\n"
           " localparam IDLE=2'd0, LOAD=2'd1, RUN=2'd2, DONE=2'd3;\n"
           " reg [1:0] top_state;\n"
           " always @(*) begin case (top_state)\n"
           "   IDLE: o=0; LOAD: o=1; RUN: o=2; DONE: o=3;\n"
           " endcase end\nendmodule\n")
    (tmp_path / "bst.sv").write_text(rtl)
    r = subprocess.run(
        [sys.executable, str(_HYGIENE), "--severity", "WARN",
         str(tmp_path / "bst.sv")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert "case-no-default" not in r.stdout


def test_770r3_localparam_values_split_comma_declaration():
    src = "localparam IDLE=2'd0, LOAD=2'd1, RUN=2'd2, DONE=2'd3;"
    assert RH._localparam_int_values(src) == {
        "IDLE": 0, "LOAD": 1, "RUN": 2, "DONE": 3}


def test_770r3_noleak_partial_fsm_still_warns(tmp_path):
    rtl = ("module bst(input clk, output reg [3:0] o);\n"
           " localparam IDLE=2'd0, LOAD=2'd1, RUN=2'd2, DONE=2'd3;\n"
           " reg [1:0] st;\n"
           " always @(*) begin case (st) IDLE: o=0; LOAD: o=1; RUN: o=2;"
           " endcase end\nendmodule\n")
    (tmp_path / "p.sv").write_text(rtl)
    r = subprocess.run(
        [sys.executable, str(_HYGIENE), "--severity", "WARN",
         str(tmp_path / "p.sv")], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "case-no-default" in r.stdout


# ── r3 Step-2.7 remediation: constant-value handshake drives must NOT cover ──
@pytest.mark.parametrize("decl,drive", [
    ("parameter BP=1;", "m_tready = BP;"),       # named constant
    ("", "m_tready = 2 - 1;"),                    # constant expression
    ("", "m_tready = 1'b1;"),                     # sized literal hold
])
def test_770r3_review_noleak_constant_handshake_drive_blocks(tmp_path, decl, drive):
    """r3 Step-2.7: a single drive of a CONSTANT value (named constant / const
    expression / sized literal) merely HOLDS the line — it does NOT exercise the
    handshake and must STILL block (the 'non-literal ⇒ non-constant' conflation
    leaked 4 HIGH FPs)."""
    tb = (f"{decl}\nmodule tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
          "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), "
          ".m_tvalid(), .m_tready(m_tready), .m_tdata());\n"
          f"initial begin s_tvalid=1; {drive} #20; $finish; end endmodule\n")
    r = _speccov(tmp_path, _AJ_SPEC, tb, _AJ_RTL)
    assert r.returncode == 1, r.stdout


def test_770r3_review_two_distinct_literal_drives_cover(tmp_path):
    """A real toggle (≥2 distinct drives of the valid/ready DUT port) still
    counts as exercising the handshake."""
    tb = ("module tb; reg clk=0; reg s_tvalid; reg m_tready;\n"
          "axis_joiner u(.clk(clk), .s_tvalid(s_tvalid), .s_tready(), "
          ".m_tvalid(), .m_tready(m_tready), .m_tdata());\n"
          "initial begin s_tvalid=1; m_tready=1; #5; m_tready=0; #5; "
          "m_tready=1; #5; $finish; end endmodule\n")
    r = _speccov(tmp_path, _AJ_SPEC, tb, _AJ_RTL)
    assert r.returncode == 0, r.stdout


# ── r3 Step-2.7 remediation: broadened "must be handled" membership vocab ─────
@pytest.mark.parametrize("vocab", [
    "All of these states must be handled:",
    "These modes must be handled:",
    "Each of these values must be handled:",
])
def test_770r3_review_noleak_must_be_handled_value_set_blocks(tmp_path, vocab):
    """r3 Step-2.7: the narrowed vocab gate dropped 'each' so 'All/These … must
    be handled' value-sets wrongly downgraded — a genuine uncovered enumeration
    must STILL block."""
    # members chosen so they cannot coincidentally substring-match a numeric TB.
    spec = f"# Set\n{vocab} VS = {{8'hA1, 8'hB2, 8'hC3}}.\n"
    # a TB that references NONE of the members.
    tb = ("module t; lpf u(.clk(1'b0), .data_in(24'h0), .y());\n"
          "initial begin #1; $finish; end endmodule\n")
    r = _speccov(tmp_path, spec, tb, _LPF_RTL)
    assert r.returncode == 1, r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
