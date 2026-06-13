#!/usr/bin/env python3
"""Tests for coverage_closure.py — RTL coverage gap detection.

Wave 83 — coverage for previously untested wired program.

Cases:
  1. POSITIVE_PASS — coverage_actual.json with pct >= 80 → exit 0.
  2. POSITIVE_FAIL — pct < 80 → exit 1 with explanatory message.
  3. SKIP_NO_REPORT — coverage_actual.json missing → exit 0 SKIP.
  4. EDGE_BAD_JSON — malformed JSON → exit 1 with parse error message.
  5. EDGE_PCT_KEY_FALLBACK — uses `pct` key fallback when coverage_pct absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "coverage_closure.py"


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _write_cov(project: Path, body: dict | str) -> None:
    cov_dir = project / "reports" / "phase2" / "coverage"
    cov_dir.mkdir(parents=True, exist_ok=True)
    target = cov_dir / "coverage_actual.json"
    if isinstance(body, str):
        target.write_text(body)
    else:
        target.write_text(json.dumps(body))


def test_positive_pass_above_threshold(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_cov(project, {"coverage_pct": 92})
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] coverage_closure" in cp.stdout
    assert "92" in cp.stdout


def test_positive_fail_below_threshold(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_cov(project, {"coverage_pct": 65})
    cp = _run([str(project)])
    assert cp.returncode == 1
    assert "[FAIL] coverage_closure" in cp.stdout
    assert "65" in cp.stdout
    assert "80" in cp.stdout


def test_skip_no_report(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP] coverage_closure" in cp.stdout


def test_edge_bad_json(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_cov(project, "garbage {not json")
    cp = _run([str(project)])
    assert cp.returncode == 1
    assert "[FAIL] coverage_closure" in cp.stdout
    assert "parse" in cp.stdout


def test_edge_pct_key_fallback(tmp_path):
    """When `coverage_pct` is absent the program falls back to `pct`."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_cov(project, {"pct": 85})
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[PASS]" in cp.stdout and "85" in cp.stdout


def test_edge_threshold_boundary(tmp_path):
    """Exactly at threshold (80) → strict less-than → PASS."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_cov(project, {"coverage_pct": 80})
    cp = _run([str(project)])
    # threshold is `< 80` so exactly 80 is PASS.
    assert cp.returncode == 0
    assert "[PASS]" in cp.stdout
