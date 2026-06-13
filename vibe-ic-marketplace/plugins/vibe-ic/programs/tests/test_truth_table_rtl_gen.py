"""Unit tests for truth_table_rtl_gen.py — deterministic truth-table → RTL.

Driven by the VerilogEval-v2 run: Prob069 (truthtable1) hands a fully-specified
3-input truth table, for which the combinational logic is mechanically derivable.
This proves the generator emits correct, synthesizable, deterministic RTL.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "truth_table_rtl_gen.py"
assert SCRIPT.exists()

PROB069 = {
    "module": "TopModule",
    "inputs": [{"name": "x3"}, {"name": "x2"}, {"name": "x1"}],
    "outputs": [{"name": "f"}],
    "rows": [{"in": "000", "out": "0"}, {"in": "001", "out": "0"},
             {"in": "010", "out": "1"}, {"in": "011", "out": "1"},
             {"in": "100", "out": "0"}, {"in": "101", "out": "1"},
             {"in": "110", "out": "0"}, {"in": "111", "out": "1"}],
    "default": "0",
}


def _gen(tmp_path, spec):
    p = tmp_path / "tt.json"
    p.write_text(json.dumps(spec))
    out = tmp_path / "out.sv"
    r = subprocess.run([sys.executable, str(SCRIPT), str(p), "-o", str(out)],
                       capture_output=True, text=True)
    return r, (out.read_text() if out.exists() else "")


def _iverilog_ok(tmp_path, rtl):
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not installed")
    sv = tmp_path / "m.sv"
    sv.write_text(rtl)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "b"), str(sv)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def test_single_output_table(tmp_path):
    r, rtl = _gen(tmp_path, PROB069)
    assert r.returncode == 0, r.stderr
    assert "case ({x3, x2, x1})" in rtl
    assert "3'b010: f = 1'b1;" in rtl
    assert "3'b110: f = 1'b0;" in rtl
    assert "output reg f" in rtl
    ok, err = _iverilog_ok(tmp_path, rtl)
    assert ok, err


def test_deterministic(tmp_path):
    _, a = _gen(tmp_path, PROB069)
    _, b = _gen(tmp_path, PROB069)
    assert a == b and a


def test_partial_table_uses_default(tmp_path):
    spec = {"module": "TopModule",
            "inputs": [{"name": "a"}, {"name": "b"}],
            "outputs": [{"name": "y"}],
            "rows": [{"in": "11", "out": "1"}],  # only one combo listed
            "default": "0"}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "2'b11: y = 1'b1;" in rtl
    assert "default: y = 1'b0;" in rtl
    ok, err = _iverilog_ok(tmp_path, rtl)
    assert ok, err


def test_multibit_and_multi_output(tmp_path):
    # 2-bit input sel + 1-bit g; two outputs hi(1b), lo(1b) → concat width 2
    spec = {"module": "TopModule",
            "inputs": [{"name": "sel", "width": 2}, {"name": "g"}],
            "outputs": [{"name": "hi"}, {"name": "lo"}],
            "rows": [{"in": "000", "out": "00"}, {"in": "111", "out": "11"},
                     {"in": "010", "out": "10"}],
            "default": "00"}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "case ({sel, g})" in rtl
    assert "3'b111: _tt_o = 2'b11;" in rtl
    assert "assign hi = _tt_o[1];" in rtl
    assert "assign lo = _tt_o[0];" in rtl
    ok, err = _iverilog_ok(tmp_path, rtl)
    assert ok, err


def test_width_mismatch_rejected(tmp_path):
    bad = dict(PROB069)
    bad["rows"] = [{"in": "0000", "out": "0"}]  # 4 bits for a 3-input table
    r, _ = _gen(tmp_path, bad)
    assert r.returncode == 1
    assert "width" in r.stderr


def test_duplicate_row_rejected(tmp_path):
    bad = dict(PROB069)
    bad["rows"] = [{"in": "000", "out": "0"}, {"in": "000", "out": "1"}]
    r, _ = _gen(tmp_path, bad)
    assert r.returncode == 1
    assert "duplicate" in r.stderr


def test_non_binary_rejected(tmp_path):
    bad = dict(PROB069)
    bad["rows"] = [{"in": "0x0", "out": "0"}]
    r, _ = _gen(tmp_path, bad)
    assert r.returncode == 1
