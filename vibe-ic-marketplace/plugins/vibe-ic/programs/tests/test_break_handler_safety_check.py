#!/usr/bin/env python3
"""Tests for break_handler_safety_check.py — FSM break-handler safety gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "break_handler_safety_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(PROG), str(rtl), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


# -- Test: PASS — break handler only in IDLE state --

def test_pass_break_in_idle_only(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac.v").write_text("""\
module mac(input clk, input rx_break, output reg [3:0] state);
  localparam MS_IDLE = 0, MS_CMD_PROC = 1, MS_TX = 2;
  always @(posedge clk) begin
    case (state)
      MS_IDLE: begin
        if (rx_break) state <= MS_IDLE;
      end
      MS_CMD_PROC: begin
        state <= MS_TX;
      end
      MS_TX: begin
        state <= MS_IDLE;
      end
    endcase
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True


# -- Test: FAIL — break handler in default clause --

def test_fail_default_break_handler(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac.v").write_text("""\
module mac(input clk, input rx_break, output reg [3:0] state);
  localparam MS_IDLE = 0, MS_CMD_PROC = 1, MS_TX = 2;
  always @(posedge clk) begin
    case (state)
      MS_IDLE: begin
        state <= MS_CMD_PROC;
      end
      MS_CMD_PROC: begin
        state <= MS_TX;
      end
      default: begin
        if (rx_break) state <= MS_IDLE;
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
    assert any("default" in e["rule"].lower() for e in errors)


# -- Test: FAIL — break handler in active state --

def test_fail_break_in_active_state(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac.v").write_text("""\
module mac(input clk, input rx_break, output reg [3:0] state);
  localparam MS_IDLE = 0, MS_CMD_PROC = 1, MS_TX = 2;
  always @(posedge clk) begin
    case (state)
      MS_IDLE: begin
        state <= MS_CMD_PROC;
      end
      MS_CMD_PROC: begin
        if (rx_break) state <= MS_IDLE;
      end
      MS_TX: begin
        state <= MS_IDLE;
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


# -- Test: no break signals is VACUOUS (rc 2), not a PASS (#515) --

def test_skip_no_break_signals(tmp_path):
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
    assert rpt["summary"]["reason"] == "no_break_signals"


# -- #515 — the silent branch: a project with no RTL file at all --

def test_vacuous_when_no_rtl_files(tmp_path):
    (tmp_path / "docs").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert rpt["summary"] == {"skipped": True, "reason": "no_rtl_files"}


# -- #515 — the disclosure is emitted even under --json (stdout is the
#    report document there, so the sentinel goes to stderr).

def test_vacuous_sentinel_on_stderr_under_json(tmp_path):
    (tmp_path / "docs").mkdir()
    r = _run(tmp_path)
    assert "VACUOUS_PASS:" in r.stderr, r.stderr
    assert "VACUOUS_PASS:" not in r.stdout, r.stdout
