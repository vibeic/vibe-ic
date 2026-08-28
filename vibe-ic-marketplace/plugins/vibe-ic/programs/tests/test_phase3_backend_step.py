#!/usr/bin/env python3
"""Tests for phase3_backend_step.py — single dispatcher for 10 backend phases.

Wave 83 — coverage for previously untested wired program.

This dispatcher always returns SKIP from the deterministic side and points
the caller at phase3_one_shot_runner.py for the real chain. The test
ensures the dispatcher (a) accepts the 10 valid step names, (b) rejects
invalid names, (c) reports the dispatch correctly.

Cases:
  1. POSITIVE_PASS_atpg — exit 0 with [SKIP] message naming step.
  2. POSITIVE_PASS_dft_insert — different valid step.
  3. POSITIVE_FAIL_invalid_step — argparse rejects with exit 2.
  4. POSITIVE_FAIL_missing_project — non-existent project dir → exit 2.
  5. EDGE_ALL_TEN_STEPS_ACCEPTED — every documented step name dispatches OK.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / \
    "phase3_backend_step.py"


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True)


def test_positive_pass_atpg(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "atpg"])
    assert cp.returncode == 0, cp.stderr
    assert "[SKIP]" in cp.stdout
    assert "atpg" in cp.stdout
    assert "phase3_one_shot_runner" in cp.stdout


def test_positive_pass_dft_insert(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "dft_insert"])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout
    assert "DFT scan-chain" in cp.stdout


def test_positive_fail_invalid_step(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "totally_made_up_step"])
    assert cp.returncode == 2
    assert "invalid choice" in cp.stderr or "invalid choice" in cp.stdout


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such_dir"
    cp = _run([str(missing), "atpg"])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_edge_all_ten_steps_accepted(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    valid = ["atpg", "dft_insert", "cts_plan", "placement_optimize",
             "em_check", "perc_check", "power_analysis", "upf_author",
             "lef_psm_patch", "open_rcx_fallback"]
    for step in valid:
        cp = _run([str(project), step])
        assert cp.returncode == 0, f"step={step} failed: {cp.stderr}"
        assert "[SKIP]" in cp.stdout
        assert step in cp.stdout


def test_edge_optional_flags(tmp_path):
    """--container and --top-name flags accepted without changing behaviour."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "atpg",
               "--container", "test_chip_eda",
               "--top-name", "test_chip_top"])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout
