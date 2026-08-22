#!/usr/bin/env python3
"""Tests for fpga_test_harness_gen.py — emits DE10-Lite test harness wrapper.

Wave 83 — coverage for previously untested wired program.

The program writes a static SystemVerilog file `rtl/fpga_test_harness.sv`
that wraps `chip_top` with KEY/LED diagnostics. chip-AGNOSTIC scaffold.

Cases:
  1. POSITIVE_PASS — fresh project → harness emitted with required ports.
  2. POSITIVE_PASS_REPLACES — existing harness file is overwritten.
  3. POSITIVE_FAIL_no_project — argparse forwards path even if missing;
                                  rtl dir is created via mkdir(parents=True).
  4. EDGE_OUTPUT_SCHEMA — emitted file must contain CLOCK_50, KEY[1:0],
                          LEDR ports + chip_top instantiation.
  5. EDGE_NO_CHIP_NAME_LEAK — must NOT hard-code EXAMPLE_CHIP / EXAMPLE_TESTER.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "fpga_test_harness_gen.py"


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def test_positive_pass_emit(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] fpga_test_harness_gen" in cp.stdout
    out = project / "phase2" / "stage1" / "rtl" / "fpga_test_harness.sv"
    assert out.is_file()
    text = out.read_text()
    assert "module fpga_test_harness" in text
    assert "CLOCK_50" in text
    assert "chip_top" in text


def test_positive_pass_overwrites_existing(tmp_path):
    project = tmp_path / "proj"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "fpga_test_harness.sv").write_text(
        "// stale content from prior wave\n")
    cp = _run([str(project)])
    assert cp.returncode == 0
    text = (rtl / "fpga_test_harness.sv").read_text()
    assert "stale content" not in text
    assert "chip_top" in text


def test_positive_pass_creates_rtl_dir_if_absent(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    # No rtl/ pre-existing.
    assert not (project / "phase2" / "stage1" / "rtl").is_dir()
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert (project / "phase2" / "stage1" / "rtl").is_dir()
    assert (project / "phase2" / "stage1" / "rtl" / "fpga_test_harness.sv").is_file()


def test_edge_output_schema_required_signals(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    text = (project / "phase2" / "stage1" / "rtl" / "fpga_test_harness.sv").read_text()
    # Required DE10-Lite signals.
    for sig in ("CLOCK_50", "KEY", "GPIO_0", "LEDR"):
        assert sig in text, f"missing signal {sig}"
    # Reset and trigger semantics documented in comments.
    assert "reset_n" in text or "Reset" in text
    assert "endmodule" in text


def test_edge_no_chip_specific_identifiers(tmp_path):
    """chip-AGNOSTIC: harness must not reference any specific chip name."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    text = (project / "phase2" / "stage1" / "rtl" / "fpga_test_harness.sv").read_text()
    forbidden = ("EXAMPLE_CHIP", "EXAMPLE_TESTER", "EXAMPLE_TESTER", "0xF2", "ACC_ID", "A1101")
    for f in forbidden:
        assert f not in text, f"chip-specific identifier leaked: {f}"
