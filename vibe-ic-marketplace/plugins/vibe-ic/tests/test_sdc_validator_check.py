#!/usr/bin/env python3
"""Tests for sdc_validator_check.py — gate that validates SDC contents.

Wave 83 — coverage for previously untested wired program.

Cases:
  1. POSITIVE_PASS — fpga/*.sdc with all three required clauses → exit 0.
  2. POSITIVE_FAIL — missing set_input_delay → exit 1 with the issue listed.
  3. SKIP_NO_SDC — fpga/ exists but no .sdc files → exit 0 SKIP.
  4. SKIP_NO_FPGA_DIR — no fpga/ at all → exit 0 SKIP.
  5. EDGE_MULTIPLE_FILES_ALL_PASS — two .sdc files all valid → PASS with count.
  6. EDGE_MULTIPLE_FILES_ONE_BROKEN — one OK, one broken → FAIL.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "programs" / \
    "sdc_validator_check.py"


_GOOD_SDC = """\
create_clock -name clk -period 20 [get_ports CLOCK_50]
set_input_delay  -clock clk 2 [get_ports KEY[0]]
set_output_delay -clock clk 2 [get_ports LEDR[0]]
"""


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _seed_sdc(project: Path, name: str, body: str) -> None:
    fpga = project / "phase2" / "stage1" / "fpga"
    fpga.mkdir(parents=True, exist_ok=True)
    (fpga / name).write_text(body)


def test_positive_pass_all_clauses(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "tb.sdc", _GOOD_SDC)
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] sdc_validator_check" in cp.stdout
    assert "1 SDC" in cp.stdout


def test_positive_fail_missing_input_delay(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    body = _GOOD_SDC.replace("set_input_delay  -clock clk 2 [get_ports KEY[0]]\n",
                              "")
    _seed_sdc(project, "tb.sdc", body)
    cp = _run([str(project)])
    assert cp.returncode == 1
    assert "[FAIL]" in cp.stdout
    assert "set_input_delay" in cp.stdout


def test_skip_no_sdc_files(tmp_path):
    project = tmp_path / "proj"
    (project / "phase2" / "stage1" / "fpga").mkdir(parents=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout


def test_skip_no_fpga_dir(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout


def test_edge_multiple_files_all_pass(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "a.sdc", _GOOD_SDC)
    _seed_sdc(project, "b.sdc", _GOOD_SDC)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[PASS]" in cp.stdout
    assert "2 SDC" in cp.stdout


def test_edge_multiple_files_one_broken(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_sdc(project, "good.sdc", _GOOD_SDC)
    _seed_sdc(project, "bad.sdc",
               "# missing every required clause\n# just a comment\n")
    cp = _run([str(project)])
    assert cp.returncode == 1
    # The bad file's name should appear in the listed issues.
    assert "bad.sdc" in cp.stdout
    assert "[FAIL]" in cp.stdout
