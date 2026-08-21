#!/usr/bin/env python3
"""Tests for handshake_check.py — pulse-vs-countdown race detection."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "handshake_check.py"

def _run(tmp_path, *extra):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json"] + list(extra),
        capture_output=True, text=True,
    )

def test_pass_no_pulse_signals(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; wire a; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0

def test_pass_pulse_no_countdown(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "tx.v").write_text("""\
module tx(input clk);
  reg cmd_valid;
  always @(posedge clk) begin
    cmd_valid <= 1'b0;
    if (go) cmd_valid <= 1'b1;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0

def test_fail_pulse_read_in_countdown(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "rx.v").write_text("""\
module rx(input clk);
  reg cmd_valid;
  reg [7:0] timer;
  always @(posedge clk) begin
    cmd_valid <= 1'b0;
    if (start) cmd_valid <= 1'b1;
  end
  always @(posedge clk) begin
    if (timer == 0) begin
      if (cmd_valid) process_cmd;
    end
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1

def test_skip_no_rtl(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
