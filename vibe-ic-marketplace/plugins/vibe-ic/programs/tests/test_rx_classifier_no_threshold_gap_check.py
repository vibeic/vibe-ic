#!/usr/bin/env python3
"""Tests for rx_classifier_no_threshold_gap_check.py (Wave 26 / v0.119.58)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "rx_classifier_no_threshold_gap_check.py")


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw)


def _make_project(tmp_path: Path,
                  l8_table: dict | None,
                  waiver: str | None = None) -> Path:
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    if l8_table is not None:
        (proj / "phase1" / "generated_docs" / "L8_RTL_CONSTANTS.json").write_text(
            json.dumps({"rx_classifier_ticks": l8_table}, indent=2))
    if waiver:
        (proj / "waivers.json").write_text(json.dumps(
            {"rx_classifier_threshold_gap_intentional": waiver}))
    return proj


# ----------------------------------------------------------------------

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0
    assert "threshold" in r.stdout.lower()


def test_no_gap_pass(tmp_path):
    """h1_max=192, h0_min=193 → contiguous → PASS."""
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 192,
        "h0_min": 193, "h0_max": 612,
        "br_min": 613, "br_max": 1314,
        "wkp_min": 738,
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_3_tick_gap_fail(tmp_path):
    """v0.119.57 bug: h1_max=192, h0_min=196 → 3-tick gap → FAIL."""
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 192,
        "h0_min": 196, "h0_max": 612,
        "br_min": 637, "br_max": 1314,
        "wkp_min": 738,
    })
    r = _run([str(proj), "--json"])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["verdict"] == "FAIL"
    msgs = " ".join(f["message"] for f in out["findings"])
    assert "3-tick gap [193..195]" in msgs


def test_overlap_pass(tmp_path):
    """h1_max=200, h0_min=196 → overlap (gap_size = -5) → PASS."""
    proj = _make_project(tmp_path, {
        "h1_min": 1, "h1_max": 200,
        "h0_min": 196, "h0_max": 612,
        "br_min": 613, "br_max": 1314,
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "[PASS]" in r.stdout


def test_no_l8_skip(tmp_path):
    """No L8 file → SKIP."""
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "SKIP"


def test_with_waiver_pass(tmp_path):
    """Waiver ≥40 chars → PASS_WITH_WAIVER even with gap."""
    proj = _make_project(
        tmp_path,
        {"h1_min": 1, "h1_max": 192, "h0_min": 196, "h0_max": 612,
         "br_min": 637, "br_max": 1314},
        waiver=("Vendor table NEW variant chosen for downstream "
                "compat; classifier gap will be tightened by a "
                "follow-up patch in v0.120 wave roadmap."))
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS_WITH_WAIVER"
