#!/usr/bin/env python3
"""Tests for crc_completeness_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "crc_completeness_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json"],
        capture_output=True, text=True,
    )


def test_pass_crc_fed_every_tx(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "tx_cmd.v").write_text("""\
module tx_cmd(input clk, output reg tx_byte_valid, output reg crc_calc);
  always @(posedge clk) begin
    tx_byte_valid <= 1'b1;
    crc_calc <= 1'b1;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads(r.stdout)
    assert rpt["passed"] is True


def test_fail_tx_without_crc_feed(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "tx_cmd.v").write_text("""\
module tx_cmd(input clk, output reg tx_byte_valid, output reg crc_calc);
  always @(posedge clk) begin
    case (state)
      S_OPCODE: begin
        tx_byte_valid <= 1'b1;
        crc_calc <= 1'b1;
      end
      S_PAYLOAD: begin
        tx_byte_valid <= 1'b1;
      end
    endcase
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads(r.stdout)
    assert rpt["passed"] is False


def test_skip_no_crc_module(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "simple.v").write_text("module simple(input clk); endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0
