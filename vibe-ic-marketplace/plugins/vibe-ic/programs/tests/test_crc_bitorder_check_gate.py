#!/usr/bin/env python3
"""Tests for crc_bitorder_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "crc_bitorder_check.py"


def _run(tmp_path: Path, rtl_files: list, crc_signal: str = "crc8_result") -> subprocess.CompletedProcess:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(PROG),
           "--rtl-files"] + rtl_files + [
           "--crc-signal", crc_signal,
           "--out-dir", str(out_dir)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_pass_direct_assignment(tmp_path):
    rtl = tmp_path / "tx_phy.v"
    rtl.write_text("""\
module tx_phy(input clk, input [7:0] crc8_result, output reg [7:0] tx_data);
  always @(posedge clk) tx_data <= crc8_result;
endmodule
""")
    r = _run(tmp_path, [str(rtl)])
    assert r.returncode == 0


def test_pass_reversed_assignment(tmp_path):
    rtl = tmp_path / "tx_phy.v"
    rtl.write_text("""\
module tx_phy(input clk, input [7:0] crc8_result, output reg [7:0] tx_data);
  always @(posedge clk)
    tx_data <= {crc8_result[0], crc8_result[1], crc8_result[2], crc8_result[3],
                crc8_result[4], crc8_result[5], crc8_result[6], crc8_result[7]};
endmodule
""")
    r = _run(tmp_path, [str(rtl)])
    assert r.returncode == 0


def test_info_no_crc_signal(tmp_path):
    rtl = tmp_path / "tx_phy.v"
    rtl.write_text("""\
module tx_phy(input clk, output reg tx_out);
  always @(posedge clk) tx_out <= 1'b0;
endmodule
""")
    r = _run(tmp_path, [str(rtl)], crc_signal="nonexistent_crc")
    assert r.returncode == 0
