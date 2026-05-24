#!/usr/bin/env python3
"""Tests for post_layout_sim_check.py (G2: Post-Layout Gate-Level Sim)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "post_layout_sim_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _setup(tmp_path, log_content=None, sdf=True, flag=False):
    sim = tmp_path / "phase3" / "stage3" / "sim_postlayout"
    sim.mkdir(parents=True, exist_ok=True)
    if sdf:
        (sim / "timing.sdf").write_text("(DELAYFILE)")
    if log_content is not None:
        (sim / "results.log").write_text(log_content)
    if flag:
        (sim / "pass.flag").write_text("PASS")


_GOOD_LOG = """\
== Post-layout gate-level simulation ==
Using $sdf_annotate("timing.sdf")
All tests passed: 42/42
"""


def test_pass_with_log(tmp_path):
    _setup(tmp_path, log_content=_GOOD_LOG)
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["pass"] is True
    assert report["summary"]["sdf_referenced"] is True


def test_pass_with_flag(tmp_path):
    _setup(tmp_path, flag=True, sdf=True)
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_no_sim_dir(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_no_sdf(tmp_path):
    _setup(tmp_path, log_content=_GOOD_LOG, sdf=False)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_errors_in_log(tmp_path):
    _setup(tmp_path, log_content="ERROR: timing violation at 100ns\n", sdf=True)
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_no_results(tmp_path):
    sim = tmp_path / "phase3" / "stage3" / "sim_postlayout"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "timing.sdf").write_text("(DELAYFILE)")
    result = _run(tmp_path)
    assert result.returncode == 1


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2
