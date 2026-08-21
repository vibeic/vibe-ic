"""Unit tests for arith_ss_corner_risk_check.py.

The advisor predicts the slow-corner re-architecture that the spm and sha256
benchmark ICs needed. It must: fire on undocumented wide ripple chains, stay
quiet on documented carry-save / structured / narrow designs, and ignore
loop-counter / index-math / parameter false positives.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'arith_ss_corner_risk_check.py'
assert SCRIPT.exists()


def run(tmp_path, sv, *extra):
    f = tmp_path / 'dut.v'
    f.write_text(sv)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json', str(jf), *extra, str(f)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, findings


WIDE_RIPPLE = """
module acc(input clk, input rst_n, input [31:0] a, input [31:0] b,
           output reg [31:0] sum);
  always @(posedge clk) if(!rst_n) sum <= 0; else sum <= a + b + sum;
endmodule
"""


def test_wide_ripple_is_high_and_advisory(tmp_path):
    res, f = run(tmp_path, WIDE_RIPPLE)
    assert res.returncode == 0                       # advisory default
    assert any(x['risk'] == 'HIGH' for x in f)
    # advisory mode must not print the FAIL token (MCP PASS contract)
    assert 'FAIL' not in subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / 'dut.v')],
        capture_output=True, text=True).stdout


def test_strict_fails_on_high(tmp_path):
    res, _ = run(tmp_path, WIDE_RIPPLE, '--strict')
    assert res.returncode == 1


def test_documented_carry_save_is_quiet(tmp_path):
    sv = """
module core(input clk, input rst_n, output reg [31:0] sum);
  // carry-save adder (3:2 compressor) tree — only one final CPA per result
  wire [31:0] csa_s, csa_c;
  always @(posedge clk) if(!rst_n) sum <= 0; else sum <= csa_s;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0
    assert len(f) == 0


def test_for_loop_counter_ignored(tmp_path):
    sv = """
module m(input clk, output reg [31:0] mem [0:15]);
  integer j;
  always @(posedge clk) for (j=0;j<16;j=j+1) mem[j] <= 32'b0;
endmodule
"""
    _, f = run(tmp_path, sv)
    assert len(f) == 0


def test_index_math_ignored(tmp_path):
    sv = """
module m(input [2:0] addr, input [255:0] digest, output reg [31:0] q);
  always @(*) q = digest[(7-(addr[2:0]))*32 +: 32];
endmodule
"""
    _, f = run(tmp_path, sv)
    assert len(f) == 0


def test_parameter_default_ignored(tmp_path):
    sv = """
module m #(parameter [0:0] MDU = 0, parameter RESET = "MINI")
          (input clk, output reg q);
  always @(posedge clk) q <= 1'b0;
endmodule
"""
    _, f = run(tmp_path, sv)
    assert len(f) == 0


def test_narrow_add_not_flagged(tmp_path):
    sv = """
module m(input clk, input [7:0] a, input [7:0] b, output reg [8:0] y);
  always @(posedge clk) y <= a[7:0] + b[7:0];
endmodule
"""
    _, f = run(tmp_path, sv)
    assert len(f) == 0


def test_wide_multiply_is_high(tmp_path):
    sv = """
module m(input clk, input [17:0] a, input [17:0] b, output reg [35:0] p);
  always @(posedge clk) p <= a * b;
endmodule
"""
    _, f = run(tmp_path, sv)
    assert any(x['rule'] == 'wide-mult-comb' and x['risk'] == 'HIGH' for x in f)


# ─────────────────────────────────────────────────────────────────────────
# FALSE POSITIVES measured on REAL published RTL when this advisory was
# wired into the flow. Each fixture is the offending construct copied from
# the run that produced it, so the regression is pinned to the shape that
# actually occurred rather than to one an author imagined.
# ─────────────────────────────────────────────────────────────────────────

# A `<=` inside an assertion MACRO argument is a COMPARISON, and the macro
# call carries no terminating `;` — so `([^;]*);` swallowed every following
# line and reported a 168-bit "add/compare chain feeding 'LfsrDw'", for a
# PARAMETER, in an assertion, which is not a datapath at all.
ASSERT_MACRO_COMPARISON = """
module prim_lfsr #(parameter int LfsrDw = 32) (input clk_i, input rst_ni,
                   output logic [LfsrDw-1:0] state_o);
  logic [LfsrDw-1:0] coeffs;
  logic [LfsrDw-1:0] lfsr_q;
  `ASSERT_INIT(MaxLfsrWidth_A, LfsrDw <= $high(LFSR_COEFFS)+LUT_OFF)
  assign state_o = lfsr_q ^ coeffs;
endmodule
"""


def test_assertion_macro_comparison_is_not_an_assignment(tmp_path):
    res, f = run(tmp_path, ASSERT_MACRO_COMPARISON, '--strict')
    assert res.returncode == 0, res.stdout
    assert not any(x['symbol'] == 'LfsrDw' for x in f), f


# The same class in ordinary RTL: an `else if (addr <= (BASE + 8'd7))`
# comparison, not a registered assignment.
IF_COMPARISON = """
module regfile(input clk, input [7:0] address, output reg [31:0] read_data);
  always @(posedge clk)
    if (address >= 8'h10 && address <= (8'h10 + 8'd7))
      read_data <= 32'h0;
endmodule
"""


def test_if_condition_comparison_is_not_an_assignment(tmp_path):
    res, f = run(tmp_path, IF_COMPARISON, '--strict')
    assert res.returncode == 0, res.stdout
    assert not any(x['symbol'] == 'address' for x in f), f


# Arithmetic that only computes a SHIFT DISTANCE is at most log2(width)
# bits wide. A rotate helper was reported as a "32-bit add/compare chain".
SHIFT_AMOUNT_MATH = """
module hashcore(input clk, input [31:0] x, output reg [31:0] y);
  function [31:0] rotr; input [31:0] x; input [4:0] n;
      begin rotr = (x >> n) | (x << (6'd32 - n)); end
  endfunction
  always @(posedge clk) y <= rotr(x, 5'd7);
endmodule
"""


def test_shift_amount_math_is_not_a_carry_chain(tmp_path):
    res, f = run(tmp_path, SHIFT_AMOUNT_MATH, '--strict')
    assert res.returncode == 0, res.stdout
    assert not any(x['symbol'] == 'rotr' for x in f), f


def test_the_real_wide_adder_still_fires_under_strict(tmp_path):
    """The two repairs above must not silence the thing the gate is for."""
    res, f = run(tmp_path, WIDE_RIPPLE, '--strict')
    assert res.returncode == 1, res.stdout
    assert any(x['risk'] == 'HIGH' for x in f)
    assert 'wide-ripple-add' in res.stdout


def test_the_finding_does_not_claim_the_case_it_cannot_reproduce(tmp_path):
    """The message shipped on EVERY HIGH finding used to end "(This is the
    spm/sha256 re-architecture pattern.)" — while this program's own measured
    CORRECTION records that only the sha256 half reproduces: on the other
    design it finds nothing even with every mitigation marker stripped,
    because that datapath is a carry-save array with no `+`, `-` or `*` in it.
    A user-facing message must not carry a claim the program has retracted."""
    _res, f = run(tmp_path, WIDE_RIPPLE, '--strict')
    msgs = [x['message'] for x in f if x['risk'] == 'HIGH']
    assert msgs
    for m in msgs:
        assert 're-architecture pattern' not in m, m
        # and it still says what the finding IS, and that it is a prediction
        assert 'slow-corner (SS) timing risk' in m
        assert 'not measured' in m


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
