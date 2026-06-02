#!/usr/bin/env python3
"""Tests for rtl_response_byte_oracle_check.py (P0.2 gate)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "rtl_response_byte_oracle_check.py"


def _run(tmp_path: Path, *extra_args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", "-", *extra_args],
        capture_output=True, text=True,
    )


# -- Inline fixtures -------------------------------------------------------

DISPATCHER_RTL = """\
module cmd_dispatch(input clk, input rst_n);
  reg [7:0] resp_len;
  reg [6:0] fetch_base;
  reg [3:0] fetch_count;

  always @(*) begin
    unique case (cmd_op)
      8'h74: begin
        resp_len   = 3;
        fetch_base = 7'h10;
        fetch_count = 3;
      end
      8'h44: begin
        resp_len   = 1;
        fetch_base = 7'h20;
        fetch_count = 1;
      end
      default: begin
        resp_len   = 0;
        fetch_base = 0;
        fetch_count = 0;
      end
    endcase
  end
endmodule
"""

ORACLE_MATCHING = {
    "opcode_oracle_vectors": [
        {
            "opcode_hex": "0x74",
            "name": "GET_ID",
            "response_size": 3,
            "fetch_base": 16,
            "fetch_count": 3,
        },
        {
            "opcode_hex": "0x44",
            "name": "READ_BYTE",
            "response_size": 1,
            "fetch_base": 32,
            "fetch_count": 1,
        },
    ]
}

ORACLE_MISMATCH = {
    "opcode_oracle_vectors": [
        {
            "opcode_hex": "0x74",
            "name": "GET_ID",
            "response_size": 5,
            "fetch_base": 16,
            "fetch_count": 3,
        },
    ]
}


def _setup_project(tmp_path, rtl_text, oracle_dict=None):
    rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "cmd_dispatch.v").write_text(rtl_text)
    if oracle_dict is not None:
        gen = tmp_path / "phase1" / "generated_docs"
        gen.mkdir(parents=True, exist_ok=True)
        (gen / "L10_TB_CONFORMANCE.json").write_text(json.dumps(oracle_dict))


# -- Tests ------------------------------------------------------------------

def test_pass_matching_oracle(tmp_path):
    _setup_project(tmp_path, DISPATCHER_RTL, ORACLE_MATCHING)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    assert j["summary"]["matched"] >= 1
    assert j["summary"]["mismatched"] == 0


def test_fail_byte_mismatch(tmp_path):
    _setup_project(tmp_path, DISPATCHER_RTL, ORACLE_MISMATCH)
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["passed"] is False
    rules = [f["rule"] for f in j["findings"]]
    assert "ORACLE_MISMATCH" in rules


def test_skip_no_oracle(tmp_path):
    _setup_project(tmp_path, DISPATCHER_RTL, oracle_dict=None)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_ORACLE" in rules


def test_skip_no_rtl(tmp_path):
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L10_TB_CONFORMANCE.json").write_text(json.dumps(ORACLE_MATCHING))
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_ORACLE" in rules


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
    assert "rtl_response_byte_oracle_check" in r.stdout
