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
    """ORGANIC #887 — an empty tree is a DISCLOSED vacuous pass, not a PASS.

    This assertion used to read `returncode == 0`, which is how the defect
    survived: the gate answered rc 0 with zero bytes of output over a tree it
    had never read, `flow_compliance_check` scored that a plain PASS, and the
    step stayed in the published `X/Y executed PASS` numerator. The test that
    should have caught it was pinning it instead.
    """
    r = _run(tmp_path)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    combined = (r.stdout or "") + (r.stderr or "")
    assert any(line.lstrip().startswith("VACUOUS_PASS")
               for line in combined.splitlines()), combined
    rpt = _load(tmp_path)
    # The report must say it too — the verdict and the census can no longer
    # sit in one object contradicting each other.
    assert rpt["summary"]["files_scanned"] == 0
    assert rpt["summary"]["vacuous"] is True
    assert rpt["summary"]["reason"]
