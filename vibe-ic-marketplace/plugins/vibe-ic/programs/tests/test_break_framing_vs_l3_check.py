#!/usr/bin/env python3
"""Tests for break_framing_vs_l3_check.py — break-to-break framing gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "break_framing_vs_l3_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _write_l3_break(tmp_path: Path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "frame_format": {"delimiter": "break", "crc": {"poly": "0x31"}},
    }))


def _write_l3_no_break(tmp_path: Path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "frame_format": {"delimiter": "length_prefix", "crc": {"poly": "0x31"}},
    }))


# -- Test: PASS with break-to-break framing --

def test_pass_break_framing(tmp_path):
    _write_l3_break(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "rx_cmd.v").write_text("""\
module rx_cmd(input clk, input rx_break, input rx_byte_valid, input [7:0] rx_byte,
              output reg cmd_valid, output reg [7:0] cmd_opcode);
  reg state;
  always @(posedge clk) begin
    case (state)
      0: if (rx_break) state <= 1;
      1: begin
           if (rx_break) begin
             cmd_valid <= 1;
           end else if (rx_byte_valid) begin
             cmd_opcode <= rx_byte;
           end
         end
    endcase
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True


# -- Test: FAIL with expected-length framing --

def test_fail_expected_len(tmp_path):
    _write_l3_break(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "rx_cmd.v").write_text("""\
module rx_cmd(input clk, input rx_break, input rx_byte_valid, input [7:0] rx_byte,
              output reg cmd_valid, output reg [7:0] cmd_opcode);
  reg [3:0] expected_len;
  reg [3:0] byte_count;
  always @(posedge clk) begin
    case (cmd_opcode)
      8'h70: expected_len = 4;
      8'h74: expected_len = 4;
      default: expected_len = 2;
    endcase
    if (byte_count == expected_len) cmd_valid <= 1;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert len(errors) >= 1


# -- Test: self-skip when no L3 JSON is VACUOUS (rc 2), not a PASS (#515) --

def test_skip_no_l3(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "rx_cmd.v").write_text("module rx_cmd(input clk); endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True


# -- Test: an L3 that is not break-delimited is VACUOUS (rc 2), not a PASS --

def test_vacuous_non_break_protocol(tmp_path):
    _write_l3_no_break(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "rx_cmd.v").write_text("""\
module rx_cmd(input clk, output reg cmd_valid, output reg [7:0] cmd_opcode);
  reg [3:0] expected_len;
  always @(posedge clk) begin
    expected_len = 4;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "not_break_protocol"


# -- #515 — the silent branch: no RTL directory at all --
#
# This one emitted NO finding and NO skip word, so the gate's entire output
# was `0 error(s); verdict: PASS` — the most common outcome in the tracked
# corpus (288 of 327 project roots) and the least visible.

def test_vacuous_when_no_rtl_dir(tmp_path):
    _write_l3_break(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rpt = _load_report(tmp_path)
    assert rpt["summary"] == {"skipped": True, "reason": "no_rtl_dir"}
    assert any(f["rule"] == "SKIP" for f in rpt["findings"]), (
        "the no-RTL branch must SAY it skipped, not stay silent")


# -- #515 — the skip findings' (rule, severity) were transposed --

def test_skip_findings_use_rule_severity_order(tmp_path):
    _write_l3_no_break(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "rx_cmd.v").write_text("module rx_cmd(input clk); endmodule\n")
    _run(tmp_path)
    rpt = _load_report(tmp_path)
    skips = [f for f in rpt["findings"] if f["rule"] == "SKIP"]
    assert skips, rpt["findings"]
    assert all(f["severity"] == "INFO" for f in skips), (
        "severity must be the severity, not the rule name")
