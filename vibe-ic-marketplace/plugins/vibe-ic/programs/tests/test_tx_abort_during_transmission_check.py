#!/usr/bin/env python3
"""Tests for tx_abort_during_transmission_check.py — TX abort protection gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "tx_abort_during_transmission_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(PROG), str(rtl), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


# -- Test: PASS — TX module ignores break during active transmission --

def test_pass_guarded_tx(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "tx_cmd.v").write_text("""\
module tx_cmd(input clk, input tx_start, input rx_break,
              output reg tx_done, output reg [3:0] state);
  localparam S_IDLE = 0, S_TX_DATA = 1, S_TX_BIT = 2;
  always @(posedge clk) begin
    case (state)
      S_IDLE: begin
        if (rx_break) state <= S_IDLE;
        if (tx_start) state <= S_TX_DATA;
      end
      S_TX_DATA: begin
        state <= S_TX_BIT;
      end
      S_TX_BIT: begin
        tx_done <= 1;
        state <= S_IDLE;
      end
    endcase
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True


# -- Test: FAIL — break handler fires during TX_DATA --

def test_fail_break_during_tx(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "tx_cmd.v").write_text("""\
module tx_cmd(input clk, input tx_start, input rx_break,
              output reg tx_done, output reg [3:0] state);
  localparam S_IDLE = 0, S_TX_DATA = 1, S_TX_BIT = 2;
  always @(posedge clk) begin
    case (state)
      S_IDLE: begin
        if (tx_start) state <= S_TX_DATA;
      end
      S_TX_DATA: begin
        if (rx_break) state <= S_IDLE;
        else state <= S_TX_BIT;
      end
      S_TX_BIT: begin
        tx_done <= 1;
        state <= S_IDLE;
      end
    endcase
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert len(errors) >= 1


# -- Test: FAIL — global break handler outside case in TX module --

def test_fail_global_break_in_tx_module(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "tx_resp.v").write_text("""\
module tx_resp(input clk, input tx_start, input rx_break,
               output reg tx_done, output reg [3:0] state);
  localparam S_IDLE = 0, S_TX_BIT = 1, S_TX_CRC = 2;
  always @(posedge clk) begin
    if (rx_break) state <= S_IDLE;
    case (state)
      S_IDLE: if (tx_start) state <= S_TX_BIT;
      S_TX_BIT: state <= S_TX_CRC;
      S_TX_CRC: begin tx_done <= 1; state <= S_IDLE; end
    endcase
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False


# -- Test: no TX module is VACUOUS (rc 2), not a PASS (#515) --

def test_skip_no_tx_modules(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac.v").write_text("""\
module mac(input clk, output reg [3:0] state);
  always @(posedge clk) state <= 0;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_tx_modules"
    assert "VACUOUS_PASS:" in r.stderr, r.stderr
