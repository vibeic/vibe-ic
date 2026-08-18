#!/usr/bin/env python3
"""Tests for post_layout_sim_check.py (G2: Post-Layout Gate-Level Sim)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "post_layout_sim_check.py"


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


def test_bare_flag_without_log_fails(tmp_path):
    # #437(d): pass.flag WITHOUT results.log is existence, not evidence
    _setup(tmp_path, flag=True, sdf=True)
    result = _run(tmp_path)
    assert result.returncode == 1
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["verdict"] == "FAIL"
    assert any(f["category"] == "FLAG_WITHOUT_LOG" for f in report["findings"])


def test_approximation_flag_maps_to_skipped_condition(tmp_path):
    # #437(d): a flag that self-declares an approximation is honest but
    # still not a PASS — verdict SKIPPED-CONDITION, exit 1
    sim = tmp_path / "phase3" / "stage3" / "sim_postlayout"
    sim.mkdir(parents=True)
    (sim / "timing.sdf").write_text("(DELAYFILE)")
    (sim / "pass.flag").write_text(
        "PASS\n# Production tapeout requires SDF-annotated re-sim; this\n"
        "# flag is the open-source-flow approximation.\n")
    result = _run(tmp_path)
    assert result.returncode == 1
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["verdict"] == "SKIPPED-CONDITION"
    assert report["summary"]["pass"] is False
    assert any(f["category"] == "APPROX_FLAG_NOT_SDF_SIM"
               for f in report["findings"])


def test_log_without_sdf_reference_fails(tmp_path):
    # #437(d): NO_SDF_REF escalated WARNING→ERROR — an un-annotated log
    # is an RTL sim wearing a post-layout name
    _setup(tmp_path, log_content="All tests passed: 42/42\n", sdf=True)
    result = _run(tmp_path)
    assert result.returncode == 1
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["sdf_referenced"] is False
    assert any(f["category"] == "NO_SDF_REF" and f["severity"] == "ERROR"
               for f in report["findings"])


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
