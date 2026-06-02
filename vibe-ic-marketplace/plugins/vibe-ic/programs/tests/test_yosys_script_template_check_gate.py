#!/usr/bin/env python3
"""Tests for yosys_script_template_check.py."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "yosys_script_template_check.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_pass_complete_script(tmp_path):
    ys = tmp_path / "synth.ys"
    ys.write_text("read_verilog -sv top.v\nsynth -top top -flatten\ntechmap\nhilomap -hicell VDD V -locell GND V\nwrite_verilog netlist.v\n")
    r = _run("--ys-file", str(ys))
    assert r.returncode == 0

def test_fail_no_sv_flag(tmp_path):
    ys = tmp_path / "synth.ys"
    ys.write_text("read_verilog top.v\nsynth -top top -flatten\ntechmap\nhilomap -hicell VDD V\nwrite_verilog netlist.v\n")
    r = _run("--ys-file", str(ys))
    assert r.returncode == 1

def test_fail_no_flatten(tmp_path):
    ys = tmp_path / "synth.ys"
    ys.write_text("read_verilog -sv top.v\nsynth -top top\ntechmap\nhilomap -hicell VDD V\nwrite_verilog netlist.v\n")
    r = _run("--ys-file", str(ys))
    assert r.returncode == 1
