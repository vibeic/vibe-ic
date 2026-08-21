#!/usr/bin/env python3
"""Tests for waiver_staleness_check.py (BACKLOG-v10 P1.3)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "waiver_staleness_check.py")


def _run(project_dir: Path, **flags) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(project_dir),
           "--json", str(project_dir / "waiver_staleness_check.json")]
    for k, v in flags.items():
        cmd.extend([f"--{k.replace('_', '-')}", str(v)])
    return subprocess.run(cmd, capture_output=True, text=True)


def _load(project_dir: Path) -> dict:
    return json.loads(
        (project_dir / "waiver_staleness_check.json").read_text())


def _waivers(project_dir: Path, entries: list):
    (project_dir / "waivers.json").write_text(
        json.dumps({"waivers": entries}))


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


def test_no_waivers_silent(tmp_path):
    """No waivers.json → silent."""
    r = _run(tmp_path)
    assert r.returncode == 2


def test_fresh_waiver_pass(tmp_path):
    """Recently-approved waiver → PASS."""
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "DRC deck not yet supplied by foundry; tracking ticket A1",
        "approver": "signoff_engineer",
        "approved_at": _days_ago(10),
    }])
    r = _run(tmp_path)
    assert r.returncode == 0


def test_old_waiver_warn(tmp_path):
    """100-day-old waiver → WARNING (no FAIL)."""
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "DRC deck not yet supplied by foundry; tracking ticket A1",
        "approver": "signoff_engineer",
        "approved_at": _days_ago(100),
    }])
    r = _run(tmp_path)
    assert r.returncode == 0  # WARN doesn't FAIL
    rpt = _load(tmp_path)
    assert any(f["rule"] == "WAIVER_STALE_WARN" for f in rpt["findings"])


def test_very_old_waiver_err(tmp_path):
    """200-day-old waiver → ERROR."""
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "DRC deck not yet supplied by foundry; tracking ticket A1",
        "approver": "signoff_engineer",
        "approved_at": _days_ago(200),
    }])
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load(tmp_path)
    assert any(f["rule"] == "WAIVER_STALE_ERR" for f in rpt["findings"])


def test_closed_waiver_silent(tmp_path):
    """200-day-old waiver WITH closure_proof → silent (closed, not stale)."""
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "DRC deck supplied at foundry review",
        "approver": "signoff_engineer",
        "approved_at": _days_ago(200),
        "closure_proof": "reports/foundry_signoff_2026Q4.pdf",
    }])
    r = _run(tmp_path)
    assert r.returncode == 2  # no parseable open entries → skip


def test_missing_approved_at_silent(tmp_path):
    """Entry missing approved_at → silent (other gate handles)."""
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "no date provided yet",
        "approver": "signoff_engineer",
    }])
    r = _run(tmp_path)
    assert r.returncode == 2


def test_custom_thresholds(tmp_path):
    """Custom warn/err thresholds via CLI."""
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "DRC deck not yet supplied; ticket A1",
        "approver": "signoff_engineer",
        "approved_at": _days_ago(45),
    }])
    # With warn=30 err=60, 45 days → WARN
    r = _run(tmp_path, warn_days=30, err_days=60)
    assert r.returncode == 0
    rpt = _load(tmp_path)
    assert any(f["rule"] == "WAIVER_STALE_WARN" for f in rpt["findings"])
    # With warn=14 err=30, 45 days → ERR
    r = _run(tmp_path, warn_days=14, err_days=30)
    assert r.returncode == 1


def test_disabled_via_zero_warn_days(tmp_path):
    """warn_days=0 disables the gate entirely."""
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "old waiver",
        "approver": "signoff_engineer",
        "approved_at": _days_ago(500),
    }])
    r = _run(tmp_path, warn_days=0, err_days=0)
    assert r.returncode == 2


def test_iso_datetime_parses(tmp_path):
    """approved_at with full ISO datetime parses correctly."""
    iso = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    _waivers(tmp_path, [{
        "id": 28,
        "reason": "old waiver, full datetime stamp",
        "approver": "signoff_engineer",
        "approved_at": iso,
    }])
    r = _run(tmp_path)
    assert r.returncode == 1
