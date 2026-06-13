"""Unit tests for output_latency_advisor.py.

Surfaces the output-by-one-cycle / sampling-alignment family behind
VerilogEval-v2 Prob089 (Moore FSM output timing) and Prob104 (mux+DFF cycle).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'output_latency_advisor.py'
assert SCRIPT.exists()


def run(tmp_path, sv, *extra):
    f = tmp_path / 'dut.sv'
    f.write_text(sv)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json', str(jf), *extra, str(f)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, findings


def test_registered_output_is_info(tmp_path):
    sv = """
module m(input clk, input d, output reg q);
  always @(posedge clk) q <= d;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0                       # advisory
    assert any(x['rule'] == 'registered-output' and x['symbol'] == 'q' for x in f)


def test_combinational_output_not_flagged(tmp_path):
    sv = """
module m(input a, input b, output y);
  assign y = a & b;
endmodule
"""
    _, f = run(tmp_path, sv)
    assert not any(x['rule'] == 'registered-output' for x in f)


def test_reg_output_undriven_is_warn(tmp_path):
    sv = """
module m(input clk, output reg q);
endmodule
"""
    res, f = run(tmp_path, sv)
    assert any(x['rule'] == 'reg-output-undriven' for x in f)


def test_strict_fails_on_warn(tmp_path):
    sv = "module m(input clk, output reg q); endmodule\n"
    res, _ = run(tmp_path, sv, '--strict')
    assert res.returncode == 1


def test_multiple_registered_outputs_all_seen(tmp_path):
    sv = """
module m(input clk, input d, output reg q1, output reg q2, output reg q3);
  always @(posedge clk) begin q1 <= d; q2 <= q1; q3 <= q2; end
endmodule
"""
    _, f = run(tmp_path, sv)
    regd = {x['symbol'] for x in f if x['rule'] == 'registered-output'}
    assert {'q1', 'q2', 'q3'} <= regd


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
