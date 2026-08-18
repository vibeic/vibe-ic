#!/usr/bin/env python3
"""Tests for bus_turnaround_consumes_spec_constant_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "bus_turnaround_consumes_spec_constant_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_no_turnaround(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; wire a; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_detect_turnaround_ref(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "ctrl.v").write_text("module ctrl;\n    localparam T_SRS = 100;\n    reg [15:0] response_delay;\n    always @(*) response_delay = T_SRS;\nendmodule\n")
    r = _run([str(tmp_path), "--json"])
    assert r.returncode == 0


def test_wave35_min_consumed_max_unused_pass(tmp_path):
    """Wave 35: when MIN turnaround constant is consumed but sibling MAX
    is declared-but-unused, gate must PASS (the FSM only needs MIN to
    enforce the minimum gap; MAX is documentation upper-bound).
    """
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "pkg.sv").write_text(
        "package pkg;\n"
        "  parameter int T_SRS_MIN_CYC = 113;\n"
        "  parameter int T_SRS_MAX_CYC = 1500;  // upper bound, not wired\n"
        "endpackage\n"
    )
    (tmp_path / "phase2" / "stage1" / "rtl" / "fsm.sv").write_text(
        "module fsm import pkg::*; (input clk, output reg busy);\n"
        "  reg [15:0] cnt;\n"
        "  always @(posedge clk) if (cnt + 1 >= T_SRS_MIN_CYC) busy <= 1;\n"
        "endmodule\n"
    )
    r = _run([str(tmp_path)])
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_wave35_no_constant_consumed_fail(tmp_path):
    """Wave 35: when ALL turnaround constants are dead, still FAIL."""
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "pkg.sv").write_text(
        "package pkg;\n"
        "  parameter int T_SRS_MIN_CYC = 113;\n"
        "  parameter int T_SRS_MAX_CYC = 1500;\n"
        "endpackage\n"
    )
    (tmp_path / "phase2" / "stage1" / "rtl" / "core.sv").write_text(
        "module core(input clk, output reg out); always @(posedge clk) out <= 1; endmodule\n"
    )
    r = _run([str(tmp_path)])
    assert r.returncode == 1, r.stdout
    assert "DEAD_TURNAROUND_CONSTANT" in r.stdout
