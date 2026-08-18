"""Unit tests for vector_op_rtl_gen.py — deterministic vector-op → RTL.

Proof case: Prob004 vector2 (32-bit byte reverse), whose generated RTL passes the
official VerilogEval testbench.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "vector_op_rtl_gen.py"
assert SCRIPT.exists()


def _gen(tmp_path, spec):
    p = tmp_path / "v.json"
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


def test_byte_reverse(tmp_path):
    spec = {"module": "TopModule", "op": "reverse", "chunk": 8,
            "inputs": [{"name": "in", "width": 32}],
            "outputs": [{"name": "out", "width": 32}]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "assign out = {in[7:0], in[15:8], in[23:16], in[31:24]};" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_bit_reverse(tmp_path):
    spec = {"module": "TopModule", "op": "reverse", "chunk": 1,
            "inputs": [{"name": "in", "width": 8}],
            "outputs": [{"name": "out", "width": 8}]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "assign out = {in[0], in[1], in[2], in[3], in[4], in[5], in[6], in[7]};" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_split(tmp_path):
    spec = {"module": "TopModule", "op": "split",
            "inputs": [{"name": "in", "width": 16}],
            "outputs": [{"name": "out_hi", "width": 8}, {"name": "out_lo", "width": 8}]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "assign out_hi = in[15:8];" in rtl
    assert "assign out_lo = in[7:0];" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_concat(tmp_path):
    spec = {"module": "TopModule", "op": "concat",
            "inputs": [{"name": "a", "width": 4}, {"name": "b", "width": 4}],
            "outputs": [{"name": "out", "width": 10}],
            "parts": ["a", "b", "2'b11"]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "assign out = {a, b, 2'b11};" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_sign_extend(tmp_path):
    spec = {"module": "TopModule", "op": "sign_extend",
            "inputs": [{"name": "in", "width": 8}],
            "outputs": [{"name": "out", "width": 32}]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "assign out = {{24{in[7]}}, in};" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_zero_extend(tmp_path):
    spec = {"module": "TopModule", "op": "zero_extend",
            "inputs": [{"name": "in", "width": 4}],
            "outputs": [{"name": "out", "width": 8}]}
    r, rtl = _gen(tmp_path, spec)
    assert r.returncode == 0, r.stderr
    assert "assign out = {{4{1'b0}}, in};" in rtl
    ok, err = _iv(tmp_path, rtl)
    assert ok, err


def test_deterministic(tmp_path):
    spec = {"module": "TopModule", "op": "reverse", "chunk": 8,
            "inputs": [{"name": "in", "width": 32}],
            "outputs": [{"name": "out", "width": 32}]}
    _, a = _gen(tmp_path, spec)
    _, b = _gen(tmp_path, spec)
    assert a == b and a


def test_reverse_bad_chunk_rejected(tmp_path):
    spec = {"module": "TopModule", "op": "reverse", "chunk": 3,
            "inputs": [{"name": "in", "width": 8}],
            "outputs": [{"name": "out", "width": 8}]}
    r, _ = _gen(tmp_path, spec)
    assert r.returncode == 1
    assert "divisible" in r.stderr


def test_split_width_mismatch_rejected(tmp_path):
    spec = {"module": "TopModule", "op": "split",
            "inputs": [{"name": "in", "width": 16}],
            "outputs": [{"name": "out_hi", "width": 8}, {"name": "out_lo", "width": 4}]}
    r, _ = _gen(tmp_path, spec)
    assert r.returncode == 1
