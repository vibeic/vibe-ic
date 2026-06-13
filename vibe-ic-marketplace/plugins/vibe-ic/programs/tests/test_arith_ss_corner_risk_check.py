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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
