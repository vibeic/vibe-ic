"""Unit tests for spec_rtl_port_fidelity_check.py.

Covers the prompt/spec port-fidelity gap behind VerilogEval-v2 Prob099
(garbled spec → wrong ports) and the L9↔RTL exact-match contract.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'spec_rtl_port_fidelity_check.py'
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


def rules(f):
    return {x['rule'] for x in f}


def test_index_gap_is_warn(tmp_path):
    sv = """
module top(input a, input b, output Y1, output Y3);
  assign Y1 = a & b; assign Y3 = a | b;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0
    gap = [x for x in f if x['rule'] == 'port-index-gap']
    assert gap and gap[0]['symbol'] == 'Y'


def test_contiguous_indices_clean(tmp_path):
    sv = """
module top(input a, output Y1, output Y2, output Y3);
  assign Y1=a; assign Y2=a; assign Y3=a;
endmodule
"""
    _, f = run(tmp_path, sv)
    assert 'port-index-gap' not in rules(f)


def test_duplicate_port_is_warn(tmp_path):
    sv = "module top(input a, input a, output y); assign y=a; endmodule\n"
    _, f = run(tmp_path, sv)
    assert 'duplicate-port' in rules(f)


def test_spec_compare_missing_and_extra_error(tmp_path):
    sv = """
module top(input a, input b, output Y1, output Y3);
  assign Y1=a; assign Y3=b;
endmodule
"""
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps([
        {"name": "a", "direction": "input", "width": 1},
        {"name": "b", "direction": "input", "width": 1},
        {"name": "Y1", "direction": "output", "width": 1},
        {"name": "Y2", "direction": "output", "width": 1},
    ]))
    res, f = run(tmp_path, sv, '--spec', str(spec))
    assert res.returncode == 1
    assert 'port-missing' in rules(f)     # spec Y2 absent in RTL
    assert 'port-extra' in rules(f)       # RTL Y3 absent in spec


def test_spec_compare_exact_match_pass(tmp_path):
    sv = """
module top(input clk, input [7:0] d, output [7:0] q);
  assign q = d;
endmodule
"""
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps([
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "d", "direction": "input", "width": 8},
        {"name": "q", "direction": "output", "width": 8},
    ]))
    res, f = run(tmp_path, sv, '--spec', str(spec))
    assert res.returncode == 0
    assert not any(x['severity'] == 'ERROR' for x in f)


def test_width_and_direction_mismatch_error(tmp_path):
    sv = """
module top(input clk, input [3:0] d, output [7:0] q);
  assign q = d;
endmodule
"""
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps([
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "d", "direction": "input", "width": 8},   # RTL is 4
        {"name": "q", "direction": "input", "width": 8},   # RTL is output
    ]))
    res, f = run(tmp_path, sv, '--spec', str(spec))
    assert res.returncode == 1
    assert 'port-width-mismatch' in rules(f)
    assert 'port-direction-mismatch' in rules(f)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
