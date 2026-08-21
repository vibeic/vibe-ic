#!/usr/bin/env python3
"""Tests for fpga_sdc_clock_constraint_check.py — Wave 24 / v0.119.56."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "fpga_sdc_clock_constraint_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_project(tmp_path: Path,
                  with_sdc: bool = True,
                  with_create_clock: bool = True,
                  sdc_period_ns: float = 20.0,
                  rtl_period_ns: float = 20.0,
                  with_rtl: bool = True) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase2" / "stage1" / "fpga" / "output_files").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)

    if with_rtl:
        (proj / "phase2" / "stage1" / "rtl" / "top.v").write_text(
            "module top(input clk, input d, output reg q);\n"
            "  always @(posedge clk) q <= d;\n"
            "endmodule\n"
        )
        (proj / "phase2" / "stage1" / "rtl" / "rtl_constants_pkg.sv").write_text(
            f"package rtl_constants_pkg;\n"
            f"  parameter CLOCK_PERIOD_NS = {rtl_period_ns};\n"
            f"endpackage\n"
        )

    if with_sdc:
        sdc_text = ""
        if with_create_clock:
            sdc_text = (
                f"# auto-generated\n"
                f"create_clock -name {{clk_50}} -period {sdc_period_ns} "
                f"-waveform {{0.000 {sdc_period_ns/2}}} "
                f"[get_ports {{CLOCK_50}}]\n"
                f"derive_pll_clocks\n"
                f"derive_clock_uncertainty\n"
            )
        else:
            sdc_text = "# SDC without create_clock\nset_input_delay 5 [all_inputs]\n"
        (proj / "phase2" / "stage1" / "fpga" / "design.sdc").write_text(sdc_text)
    return proj


def test_help():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "Wave 24" in r.stdout or "SDC" in r.stdout


def test_sdc_present_with_create_clock_pass(tmp_path):
    proj = _make_project(tmp_path, with_sdc=True, with_create_clock=True,
                         sdc_period_ns=20.0, rtl_period_ns=20.0)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_no_sdc_fail(tmp_path):
    proj = _make_project(tmp_path, with_sdc=False, with_rtl=True)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FPGA_SDC_MISSING" in r.stdout


def test_sdc_no_create_clock_fail(tmp_path):
    proj = _make_project(tmp_path, with_sdc=True, with_create_clock=False)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FPGA_SDC_NO_CREATE_CLOCK" in r.stdout


def test_period_mismatch_fail(tmp_path):
    # SDC says 10 ns (100 MHz), RTL says 20 ns (50 MHz) → 50 % mismatch
    proj = _make_project(tmp_path, with_sdc=True, with_create_clock=True,
                         sdc_period_ns=10.0, rtl_period_ns=20.0)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FPGA_SDC_PERIOD_MISMATCH" in r.stdout


def test_with_waiver_pass(tmp_path):
    proj = _make_project(tmp_path, with_sdc=False, with_rtl=True)
    (proj / "waivers.json").write_text(json.dumps({
        "fpga_sdc_explicitly_unconstrained":
            "Combinational LUT-only test design; no setup/hold path; "
            "explicitly unconstrained for synthesis benchmarking.",
    }))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout
