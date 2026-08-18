"""Unit tests for gate_netlist_rtl_gen.py — deterministic gate-netlist → RTL.

Proof case: Prob065 7420 (two 4-input NAND gates), whose generated RTL passes the
official VerilogEval testbench.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "gate_netlist_rtl_gen.py"
assert SCRIPT.exists()

PROB065 = {
    "module": "TopModule",
    "inputs": ["p1a", "p1b", "p1c", "p1d", "p2a", "p2b", "p2c", "p2d"],
    "outputs": ["p1y", "p2y"],
    "gates": [{"op": "nand", "out": "p1y", "in": ["p1a", "p1b", "p1c", "p1d"]},
              {"op": "nand", "out": "p2y", "in": ["p2a", "p2b", "p2c", "p2d"]}],
}


def _gen(tmp_path, spec):
    p = tmp_path / "g.json"
    p.write_text(json.dumps(spec))
    out = tmp_path / "out.sv"
    r = subprocess.run([sys.executable, str(SCRIPT), str(p), "-o", str(out)],
                       capture_output=True, text=True)
    return r, (out.read_text() if out.exists() else "")


def _iv(tmp_path, rtl):
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not installed")
    sv = tmp_path / "m.sv"; sv.write_text(rtl)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "b"), str(sv)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr


def test_nand_netlist(tmp_path):
    r, rtl = _gen(tmp_path, PROB065)
    assert r.returncode == 0, r.stderr
    assert "assign p1y = ~(p1a & p1b & p1c & p1d);" in rtl
    assert "assign p2y = ~(p2a & p2b & p2c & p2d);" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_all_ops(tmp_path):
    spec = {"module": "TopModule",
            "inputs": ["a", "b", "c"], "outputs": ["o_and", "o_or", "o_xor", "o_nor", "o_xnor", "o_not", "o_buf"],
            "gates": [{"op": "and", "out": "o_and", "in": ["a", "b", "c"]},
                      {"op": "or", "out": "o_or", "in": ["a", "b"]},
                      {"op": "xor", "out": "o_xor", "in": ["a", "b"]},
                      {"op": "nor", "out": "o_nor", "in": ["a", "b"]},
                      {"op": "xnor", "out": "o_xnor", "in": ["a", "b"]},
                      {"op": "not", "out": "o_not", "in": ["a"]},
                      {"op": "buf", "out": "o_buf", "in": ["c"]}]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "assign o_and = a & b & c;" in rtl
    assert "assign o_or = a | b;" in rtl
    assert "assign o_xor = a ^ b;" in rtl
    assert "assign o_nor = ~(a | b);" in rtl
    assert "assign o_xnor = ~(a ^ b);" in rtl
    assert "assign o_not = ~a;" in rtl
    assert "assign o_buf = c;" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_internal_wires(tmp_path):
    spec = {"module": "TopModule", "inputs": ["a", "b", "c"], "outputs": ["y"],
            "wires": ["w1"],
            "gates": [{"op": "and", "out": "w1", "in": ["a", "b"]},
                      {"op": "or", "out": "y", "in": ["w1", "c"]}]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "wire w1;" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_deterministic(tmp_path):
    _, a = _gen(tmp_path, PROB065)
    _, b = _gen(tmp_path, PROB065)
    assert a == b and a


def test_undriven_output_rejected(tmp_path):
    bad = {"module": "TopModule", "inputs": ["a"], "outputs": ["y", "z"],
           "gates": [{"op": "buf", "out": "y", "in": ["a"]}]}  # z undriven
    r, _ = _gen(tmp_path, bad)
    assert r.returncode == 1
    assert "not driven" in r.stderr


def test_double_driven_rejected(tmp_path):
    bad = {"module": "TopModule", "inputs": ["a", "b"], "outputs": ["y"],
           "gates": [{"op": "buf", "out": "y", "in": ["a"]},
                     {"op": "buf", "out": "y", "in": ["b"]}]}
    r, _ = _gen(tmp_path, bad)
    assert r.returncode == 1
    assert "more than one" in r.stderr


def test_unknown_op_rejected(tmp_path):
    bad = {"module": "TopModule", "inputs": ["a"], "outputs": ["y"],
           "gates": [{"op": "frobnicate", "out": "y", "in": ["a"]}]}
    r, _ = _gen(tmp_path, bad)
    assert r.returncode == 1
