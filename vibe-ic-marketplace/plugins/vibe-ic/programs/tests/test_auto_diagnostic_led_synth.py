#!/usr/bin/env python3
"""Tests for auto_diagnostic_led_synth.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "auto_diagnostic_led_synth.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_no_fpga_wrapper(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_with_fsm_and_leds(tmp_path):
    rtl = tmp_path / "chip_fpga_top.v"
    rtl.write_text("module chip_fpga_top(\n    input MAX10_CLK1_50,\n    output [9:0] LEDR\n);\n    reg [3:0] state;\n    localparam S_IDLE = 4'd0, S_RUN = 4'd1, S_DONE = 4'd2;\n    always @(posedge MAX10_CLK1_50) begin\n        case (state)\n            S_IDLE: state <= S_RUN;\n            S_RUN:  state <= S_DONE;\n            S_DONE: state <= S_IDLE;\n        endcase\n    end\n    assign LEDR[0] = 1'b0;\nendmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0
