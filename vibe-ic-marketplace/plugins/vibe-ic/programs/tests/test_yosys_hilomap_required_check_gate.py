#!/usr/bin/env python3
"""Tests for yosys_hilomap_required_check.py."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "yosys_hilomap_required_check.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_pass_correct_order(tmp_path):
    ys = tmp_path / "synth.ys"
    ys.write_text("read_verilog top.v\nsynth -top top\ntechmap\nhilomap -hicell VDD V -locell GND V\nwrite_verilog netlist.v\n")
    r = _run("--ys-file", str(ys))
    assert r.returncode == 0

def test_fail_missing_hilomap(tmp_path):
    ys = tmp_path / "synth.ys"
    ys.write_text("read_verilog top.v\nsynth -top top\ntechmap\nwrite_verilog netlist.v\n")
    r = _run("--ys-file", str(ys))
    assert r.returncode == 1

def test_fail_no_techmap(tmp_path):
    ys = tmp_path / "synth.ys"
    ys.write_text("read_verilog top.v\nsynth -top top\nhilomap -hicell VDD V\nwrite_verilog netlist.v\n")
    r = _run("--ys-file", str(ys))
    assert r.returncode == 1
