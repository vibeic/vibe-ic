#!/usr/bin/env python3
"""Tests for fetch_round_trip_sentinel_check.py (P0.1 gate)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "fetch_round_trip_sentinel_check.py"


def _run(tmp_path: Path, *extra_args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", "-", *extra_args],
        capture_output=True, text=True,
    )


# -- Fixtures: inline RTL -----------------------------------------------

DISPATCHER_WITH_WAIT = """\
module cmd_dispatch(input clk, input rst_n);
  localparam S_IDLE = 0, S_FETCH_REQ = 1, S_FETCH_WAIT = 2, S_FETCH_CAP = 3;
  reg [2:0] state;
  reg [6:0] addr;
  reg [7:0] rdata;
  reg [7:0] mem [0:127];
  always @(posedge clk) rdata <= mem[addr];

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) state <= S_IDLE;
    else case (state)
      S_IDLE:      if (cmd_valid) state <= S_FETCH_REQ;
      S_FETCH_REQ: begin addr <= fetch_base; state <= S_FETCH_WAIT; end
      S_FETCH_WAIT: state <= S_FETCH_CAP;
      S_FETCH_CAP: begin resp_byte <= rdata; state <= S_IDLE; end
    endcase
  end

  // dispatcher opcode case
  always @(*) begin
    unique case (cmd_op)
      8'h74: begin /* GET_ID */ end
    endcase
  end
endmodule
"""

DISPATCHER_NO_WAIT = """\
module cmd_dispatch(input clk, input rst_n);
  localparam S_IDLE = 0, S_FETCH_REQ = 1, S_FETCH_CAP = 2;
  reg [2:0] state;
  reg [6:0] addr;
  reg [7:0] rdata;
  reg [7:0] mem [0:127];
  always @(posedge clk) rdata <= mem[addr];

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) state <= S_IDLE;
    else case (state)
      S_IDLE:      if (cmd_valid) state <= S_FETCH_REQ;
      S_FETCH_REQ: begin addr <= fetch_base; state <= S_FETCH_CAP; end
      S_FETCH_CAP: begin resp_byte <= rdata; state <= S_IDLE; end
    endcase
  end

  always @(*) begin
    unique case (cmd_op)
      8'h74: begin /* GET_ID */ end
    endcase
  end
endmodule
"""

NO_FETCH_DISPATCHER = """\
module cmd_dispatch(input clk, input rst_n);
  reg [7:0] resp;
  always @(*) begin
    case (cmd_op)
      8'h74: resp = 8'hFF;
      default: resp = 8'h00;
    endcase
  end
endmodule
"""

COMBINATIONAL_ROM = """\
module cmd_dispatch(input clk, input rst_n);
  reg [7:0] mem [0:127];
  reg [6:0] addr;
  wire [7:0] rdata;
  assign rdata = mem[addr];

  always @(posedge clk) begin
    case (state)
      S_FETCH_REQ: begin addr <= fetch_base; state <= S_FETCH_CAP; end
      S_FETCH_CAP: begin resp_byte <= rdata; state <= S_IDLE; end
    endcase
  end

  always @(*) begin
    unique case (cmd_byte)
      8'h74: begin end
    endcase
  end
endmodule
"""


def _write_rtl(tmp_path: Path, content: str) -> None:
    rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "cmd_dispatch.v").write_text(content)


# -- Tests ---------------------------------------------------------------

def test_pass_with_wait_state(tmp_path):
    _write_rtl(tmp_path, DISPATCHER_WITH_WAIT)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "FETCH_LATENCY_MISSING" not in rules


def test_fail_no_wait(tmp_path):
    _write_rtl(tmp_path, DISPATCHER_NO_WAIT)
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["passed"] is False
    rules = [f["rule"] for f in j["findings"]]
    assert "FETCH_LATENCY_MISSING" in rules


def test_skip_no_fetch(tmp_path):
    _write_rtl(tmp_path, NO_FETCH_DISPATCHER)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_FETCH" in rules


def test_pass_combinational_rom(tmp_path):
    _write_rtl(tmp_path, COMBINATIONAL_ROM)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "COMBINATIONAL_MEM_OK" in rules


def test_exit2_missing_dir():
    r = subprocess.run(
        [sys.executable, str(PROG), "/nonexistent/path/xyz"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_help():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "fetch_round_trip_sentinel_check" in r.stdout
