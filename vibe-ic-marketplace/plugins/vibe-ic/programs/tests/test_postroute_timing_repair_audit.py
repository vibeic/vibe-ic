#!/usr/bin/env python3
"""Tests for postroute_timing_repair_audit.py (G4: timing repair loop)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "postroute_timing_repair_audit.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "out.json")]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_pass_no_repair_needed(tmp_path):
    flag = tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "no_repair_needed.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("all sign-off passed first time")
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert report["summary"]["repair_needed"] is False


def test_pass_repair_reverified(tmp_path):
    _write_json(tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "repair_log.json", {
        "changes": [{"type": "buffer_insert", "net": "clk"}],
        "re_verified": True,
        "affected_steps": [21, 27],
    })
    result = _run(tmp_path)
    assert result.returncode == 0


def test_fail_no_artifact(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_not_reverified(tmp_path):
    _write_json(tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "repair_log.json", {
        "changes": [{"type": "resize", "cell": "U42"}],
        "re_verified": False,
        "affected_steps": [21],
    })
    result = _run(tmp_path)
    assert result.returncode == 1


def test_fail_empty_changes(tmp_path):
    _write_json(tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "repair_log.json", {
        "changes": [],
        "re_verified": True,
        "affected_steps": [],
    })
    result = _run(tmp_path)
    assert result.returncode == 1


def test_exit2_bad_dir(tmp_path):
    cmd = [sys.executable, str(PROG), str(tmp_path / "nonexistent")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 2


# ── REPAIR_REGRESSED — the audit's missing question: did the repair actually help? ──
#
# Every assertion below is written so it FAILS on the pre-fix program: the
# regressed record satisfies changes / re_verified / affected_steps and used to
# exit 0. The healthy and unmeasured cases are the negative controls — if the
# guard fired on those it would be flagging ECOs that did nothing wrong.

_REGRESSED = {
    "changes": [{"type": "multi_corner_repair_timing"}],
    "re_verified": True,
    "affected_steps": [21, 23, 24, 29, 30],
    "repair_before": {"setup_worst_slack_ns": -0.68},
    "repair_after": {"setup_worst_slack_ns": -8.92},
    "repair_setup_delta_ns": -8.24,
    "repair_regressed": True,
}


def test_repair_that_regressed_timing_fails_the_audit(tmp_path):
    """A repair that made timing 12x worse must not pass as 'applied'."""
    _write_json(tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "repair_log.json",
                _REGRESSED)
    result = _run(tmp_path)
    assert result.returncode == 1
    report = json.loads((tmp_path / "out.json").read_text())
    codes = {f["category"] for f in report["findings"]}
    assert "REPAIR_REGRESSED" in codes
    # and it must be an ERROR, not a WARNING that a caller can ignore
    assert any(f["category"] == "REPAIR_REGRESSED" and f["severity"] == "ERROR"
               for f in report["findings"])


def test_regression_is_detected_from_the_delta_alone(tmp_path):
    """`repair_regressed` absent — the audit must still read the measured delta,
    so an older runner's record cannot slip a regression past the gate."""
    rec = dict(_REGRESSED)
    rec.pop("repair_regressed")
    _write_json(tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "repair_log.json", rec)
    assert _run(tmp_path).returncode == 1


def test_repair_that_improved_timing_still_passes(tmp_path):
    """NEGATIVE CONTROL — a real repair that gained slack is untouched."""
    rec = dict(_REGRESSED)
    rec.update({"repair_before": {"setup_worst_slack_ns": -8.92},
                "repair_after": {"setup_worst_slack_ns": -0.68},
                "repair_setup_delta_ns": 8.24, "repair_regressed": False})
    _write_json(tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "repair_log.json", rec)
    result = _run(tmp_path)
    assert result.returncode == 0
    report = json.loads((tmp_path / "out.json").read_text())
    assert "REPAIR_REGRESSED" not in {f["category"] for f in report["findings"]}


def test_unmeasured_before_after_is_not_treated_as_a_regression(tmp_path):
    """NEGATIVE CONTROL — no delta measured is NOT evidence of a regression.
    Absence of a measurement must never be read as a measurement."""
    rec = dict(_REGRESSED)
    for k in ("repair_setup_delta_ns", "repair_regressed", "repair_before", "repair_after"):
        rec.pop(k, None)
    _write_json(tmp_path / "phase3" / "stage3" / "postroute_timing_repair" / "repair_log.json", rec)
    assert _run(tmp_path).returncode == 0
