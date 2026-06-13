"""Unit tests for reset_discipline_check.py.

Covers the reset-semantics failure family behind VerilogEval-v2 DFF/FSM cases:
sync-vs-async reset, reset polarity, and incomplete (partial) reset of state.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'reset_discipline_check.py'
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


def rules(findings):
    return {f['rule'] for f in findings}


def test_polarity_and_mode_mismatch_is_error(tmp_path):
    sv = """
module m(input clk, input rst, input d, output reg q1, output reg q2);
  always @(posedge clk or posedge rst) if (rst) q1 <= 0; else q1 <= d;
  always @(posedge clk)                if (!rst) q2 <= 0; else q2 <= d;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 1                       # ERROR → FAIL
    assert 'reset-polarity-mismatch' in rules(f)
    assert 'reset-mode-mismatch' in rules(f)


def test_clean_async_active_low_is_pass(tmp_path):
    sv = """
module m(input clk, input rst_n, input d, output reg q);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= 1'b0; else q <= d;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0
    assert not any(x['severity'] == 'ERROR' for x in f)


def test_clean_sync_active_high_is_pass(tmp_path):
    sv = """
module m(input clk, input reset, input d, output reg q);
  always @(posedge clk) if (reset) q <= 1'b0; else q <= d;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0
    assert not any(x['severity'] == 'ERROR' for x in f)


def test_incomplete_reset_is_warn_not_fail(tmp_path):
    sv = """
module m(input clk, input rst_n, input d, output reg a, output reg b);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) a <= 1'b0;        // b missing from reset branch
    else begin a <= d; b <= a; end
  end
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0                       # WARN does not fail
    inc = [x for x in f if x['rule'] == 'incomplete-reset']
    assert any(x['symbol'] == 'b' for x in inc)
    assert not any(x['symbol'] == 'a' for x in inc)


def test_incomplete_reset_strict_fails(tmp_path):
    sv = """
module m(input clk, input rst_n, input d, output reg a, output reg b);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) a <= 1'b0; else begin a <= d; b <= a; end
  end
endmodule
"""
    res, _ = run(tmp_path, sv, '--strict')
    assert res.returncode == 1


def test_flop_without_reset_is_warn(tmp_path):
    sv = """
module m(input clk, input d, output reg q);
  always @(posedge clk) q <= d;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0
    assert 'flop-without-reset' in rules(f)


def test_enable_not_mistaken_for_reset(tmp_path):
    """`if(en)` / `if(!en)` are enables, not resets — must not raise a
    spurious polarity mismatch (would otherwise break the gate)."""
    sv = """
module m(input clk, input en, input d, output reg q1, output reg q2);
  always @(posedge clk) if (en)  q1 <= d;
  always @(posedge clk) if (!en) q2 <= d;
endmodule
"""
    res, f = run(tmp_path, sv)
    assert res.returncode == 0
    assert 'reset-polarity-mismatch' not in rules(f)


def test_rtl_dir_interface(tmp_path):
    (tmp_path / 'a.v').write_text(
        "module a(input clk,input rst_n,input d,output reg q);"
        "always @(posedge clk or negedge rst_n) if(!rst_n) q<=0; else q<=d;"
        "endmodule")
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--rtl-dir', str(tmp_path)],
        capture_output=True, text=True)
    assert res.returncode == 0
    assert 'reset_discipline_check' in res.stdout


def test_no_rtl_returns_two(tmp_path):
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--rtl-dir', str(tmp_path)],
        capture_output=True, text=True)
    assert res.returncode == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
