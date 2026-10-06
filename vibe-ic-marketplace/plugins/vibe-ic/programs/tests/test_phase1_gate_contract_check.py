#!/usr/bin/env python3
"""Tests for phase1_gate_contract_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

from phase1_gate_contract_check import _syntax_error
import pytest
PROG = Path(__file__).resolve().parent.parent / "phase1_gate_contract_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0


def test_syntax_check_is_read_only(tmp_path):
    gate = tmp_path / "gate.py"
    gate.write_text("VALUE = 1\n")
    assert _syntax_error(gate) is None
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == ["gate.py"]


def test_syntax_check_reports_invalid_source_without_cache(tmp_path):
    gate = tmp_path / "broken_gate.py"
    gate.write_text("def broken(:\n")
    assert _syntax_error(gate)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == ["broken_gate.py"]


def test_syntax_check_rejects_invalid_encoding_without_cache(tmp_path):
    gate = tmp_path / "invalid_encoding.py"
    gate.write_bytes(b"value = '" + bytes([0xff]) + b"'\n")
    assert _syntax_error(gate)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == ["invalid_encoding.py"]


def test_syntax_check_reports_embedded_nul_without_cache(tmp_path):
    gate = tmp_path / "embedded_nul.py"
    gate.write_bytes(b"value = 1\x00\n")
    assert _syntax_error(gate)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == ["embedded_nul.py"]
