#!/usr/bin/env python3
"""Tests for derived_clock_sdc_required_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "derived_clock_sdc_required_check.py"

def _run(tmp_path: Path, rtl_path: str, sdc_path: str = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), rtl_path, "--json", str(tmp_path / "report.json")]
    if sdc_path:
        cmd.extend(["--sdc", sdc_path])
    return subprocess.run(cmd, capture_output=True, text=True)

def _load(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_pass_no_derived_clocks(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk, input rst); reg q; always @(posedge clk) q <= 1; endmodule\n")
    r = _run(tmp_path, str(rtl))
    assert r.returncode == 0
    rpt = _load(tmp_path)
    assert rpt["verdict"] == "PASS"


def test_fail_derived_clock_no_sdc(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("""\
module top(input clk, input rst);
  reg div_clk;
  always @(posedge clk) div_clk <= ~div_clk;
  reg q;
  always @(posedge div_clk) q <= 1;
endmodule
""")
    r = _run(tmp_path, str(rtl))
    rpt = _load(tmp_path)
    errs = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert len(errs) >= 1


def test_pass_derived_clock_with_sdc(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("""\
module top(input clk, input rst);
  reg div_clk;
  always @(posedge clk) div_clk <= ~div_clk;
  reg q;
  always @(posedge div_clk) q <= 1;
endmodule
""")
    sdc = tmp_path / "top.sdc"
    sdc.write_text("create_generated_clock -name div_clk -source clk -divide_by 2 [get_pins div_clk]\n")
    r = _run(tmp_path, str(rtl), str(sdc))
    rpt = _load(tmp_path)
    assert rpt["verdict"] == "PASS"
