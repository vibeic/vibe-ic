#!/usr/bin/env python3
"""Tests for cdc_async_input_check.py"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "cdc_async_input_check.py"

def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )

def _load(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_pass_synchronized(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text("""\
module top(input clk, input rst_n, input data_pad);
  reg sync1, sync2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin sync1 <= 0; sync2 <= 0; end
    else begin sync1 <= data_pad; sync2 <= sync1; end
  wire safe = sync2;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load(tmp_path)
    assert rpt["passed"] is True


def test_fail_unsynchronized(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text("""\
module top(input clk, input rst_n, input data_pad);
  reg q;
  always @(posedge clk)
    q <= data_pad;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path)
    assert rpt["passed"] is False


def test_skip_no_rtl(tmp_path):
    """ORGANIC #887 — the SKIP this test is named for is now SAID.

    It asserted rc 0, which is the flow's word for "I examined the design and
    found it correct" — the one thing a scan of zero files has not done. rc 2
    is this repo's shared input-missing code (`_vacuous_exit.RC_VACUOUS`): the
    clause still passes (`__check_program_exit_zero` maps rc 2 to a vacuous
    PASS) and the P0 structural umbrella records a SKIP instead of a plain
    PASS. The disclosure line is pinned in
    `test_organic887_zero_file_scan_is_not_a_plain_pass.py`.
    """
    r = _run(tmp_path)
    assert r.returncode == 2
    assert json.loads((tmp_path / "report.json").read_text())["verdict"] == \
        "VACUOUS_PASS"
