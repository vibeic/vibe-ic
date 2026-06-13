#!/usr/bin/env python3
"""Tests for bus_turnaround_consumes_spec_constant_check.py — magnitude upgrade (P1.2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "bus_turnaround_consumes_spec_constant_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json"],
        capture_output=True, text=True,
    )


def _setup(tmp_path: Path, rtl_text: str, l2: dict | None = None, l8: dict | None = None) -> None:
    rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "dispatcher.v").write_text(rtl_text)
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    if l2:
        (gen / "L2_FRS.json").write_text(json.dumps(l2))
    if l8:
        (gen / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))


RTL_TEMPLATE = """\
module dispatcher(input clk);
  localparam T_SRS_MIN_CYC = {cyc};
  reg [{w}:0] counter;
  always @(posedge clk) begin
    if (counter < T_SRS_MIN_CYC) counter <= counter + 1;
  end
endmodule
"""


def test_pass_magnitude_within_band(tmp_path):
    """Declared 200 cyc, spec needs 150 → within 1-5×, PASS."""
    _setup(
        tmp_path,
        RTL_TEMPLATE.format(cyc=200, w=7),
        l2={"tSRS_min_us": 15.0, "core_clk_hz": 10_000_000},
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "TURNAROUND_MAGNITUDE_OK" in rules


def test_fail_magnitude_too_short(tmp_path):
    """Declared 50 cyc, spec needs 150 → too short, FAIL."""
    _setup(
        tmp_path,
        RTL_TEMPLATE.format(cyc=50, w=7),
        l2={"tSRS_min_us": 15.0, "core_clk_hz": 10_000_000},
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["passed"] is False
    rules = [f["rule"] for f in j["findings"]]
    assert "TURNAROUND_TOO_SHORT" in rules


def test_warn_magnitude_too_long(tmp_path):
    """Declared 5000 cyc, spec needs 150 → >5×, WARN but still PASS (WARNING not ERROR)."""
    _setup(
        tmp_path,
        RTL_TEMPLATE.format(cyc=5000, w=12),
        l2={"tSRS_min_us": 15.0, "core_clk_hz": 10_000_000},
    )
    r = _run(tmp_path)
    j = json.loads(r.stdout)
    rules = [f["rule"] for f in j["findings"]]
    assert "TURNAROUND_TOO_LONG" in rules


def test_magnitude_skip_no_timing(tmp_path):
    """No L2/L8 timing → magnitude check not attempted."""
    _setup(
        tmp_path,
        RTL_TEMPLATE.format(cyc=200, w=7),
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    assert j["summary"]["magnitude_checked"] is False
