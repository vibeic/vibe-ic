#!/usr/bin/env python3
"""Tests for analog_hw_spice_correlation_check.py — HW-vs-SPICE correlation gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_hw_spice_correlation_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_analog_dir(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_dir"


def test_skip_no_hw_data(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "ldo" / "spec.json").write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_hw_data"


def test_pass_within_tolerance(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "hw_measurements.json").write_text(json.dumps({
        "measurements": {"vout": 3.25, "iq": 48e-6}
    }))
    (ad / "corner_results.json").write_text(json.dumps({
        "pvt_results": {"TT_25C": {"vout": 3.3, "iq": 50e-6}}
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["measurements_compared"] == 2


def test_fail_critical_mismatch(tmp_path):
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    (ad / "hw_measurements.json").write_text(json.dumps({
        "measurements": {"vout": 2.0}
    }))
    (ad / "corner_results.json").write_text(json.dumps({
        "pvt_results": {"TT_25C": {"vout": 3.3}}
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("HW_SPICE_CRITICAL_MISMATCH" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# --- Item 3: <10% IDEAL classification tier (INFO-only, verdict unchanged) ---

def test_ideal_tier_under_10pct_passes(tmp_path):
    """A <10% discrepancy yields HW_SPICE_IDEAL + ideal_count>=1 AND still PASSES."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    # 3.27 vs 3.3 => 0.9% discrepancy (well under 10%)
    (ad / "hw_measurements.json").write_text(json.dumps({
        "measurements": {"vout": 3.27}
    }))
    (ad / "corner_results.json").write_text(json.dumps({
        "pvt_results": {"TT_25C": {"vout": 3.3}}
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["measurements_compared"] == 1
    assert rpt["summary"]["ideal_count"] >= 1
    assert rpt["summary"]["ideal_pct"] == 100.0
    rules = [f["rule"] for f in rpt["findings"]]
    assert "HW_SPICE_IDEAL" in rules
    # The ideal finding must be INFO severity (granularity only, not a verdict change)
    ideal_findings = [f for f in rpt["findings"] if f["rule"] == "HW_SPICE_IDEAL"]
    assert all(f["severity"] == "INFO" for f in ideal_findings)


def test_15pct_is_acceptable_but_not_ideal(tmp_path):
    """A 15% case is INFO/acceptable (CORRELATED) but NOT ideal; still PASSES."""
    ad = tmp_path / "phase3" / "analog" / "ldo"
    ad.mkdir(parents=True)
    # 2.805 vs 3.3 => exactly 15% discrepancy (between 10% and 20%)
    (ad / "hw_measurements.json").write_text(json.dumps({
        "measurements": {"vout": 2.805}
    }))
    (ad / "corner_results.json").write_text(json.dumps({
        "pvt_results": {"TT_25C": {"vout": 3.3}}
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["measurements_compared"] == 1
    assert rpt["summary"]["ideal_count"] == 0
    assert rpt["summary"]["ideal_pct"] == 0.0
    rules = [f["rule"] for f in rpt["findings"]]
    assert "HW_SPICE_CORRELATED" in rules
    assert "HW_SPICE_IDEAL" not in rules


def test_verdict_invariant_ideal_vs_acceptable(tmp_path):
    """Verdict (passed/rc) is identical for the <10% and 15% cases — INFO granularity only."""
    # <10% case
    ad1 = tmp_path / "ideal" / "phase3" / "analog" / "ldo"
    ad1.mkdir(parents=True)
    (ad1 / "hw_measurements.json").write_text(json.dumps({"measurements": {"vout": 3.27}}))
    (ad1 / "corner_results.json").write_text(json.dumps({"pvt_results": {"TT_25C": {"vout": 3.3}}}))
    r1 = _run(tmp_path / "ideal")
    rpt1 = _load_report(tmp_path / "ideal")

    # 15% case
    ad2 = tmp_path / "accept" / "phase3" / "analog" / "ldo"
    ad2.mkdir(parents=True)
    (ad2 / "hw_measurements.json").write_text(json.dumps({"measurements": {"vout": 2.805}}))
    (ad2 / "corner_results.json").write_text(json.dumps({"pvt_results": {"TT_25C": {"vout": 3.3}}}))
    r2 = _run(tmp_path / "accept")
    rpt2 = _load_report(tmp_path / "accept")

    # Verdict invariant across both INFO tiers
    assert r1.returncode == r2.returncode == 0
    assert rpt1["passed"] == rpt2["passed"] is True
    # but the IDEAL granularity differs
    assert rpt1["summary"]["ideal_count"] == 1
    assert rpt2["summary"]["ideal_count"] == 0


def test_ideal_summary_fields_present_on_skip_paths(tmp_path):
    """ideal_count/ideal_pct are summary-only on the compare path; skip paths keep their shape."""
    # no analog dir -> skipped summary unchanged (no ideal fields required)
    r = _run(tmp_path)
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["skipped"] is True
    assert "ideal_count" not in rpt["summary"]
