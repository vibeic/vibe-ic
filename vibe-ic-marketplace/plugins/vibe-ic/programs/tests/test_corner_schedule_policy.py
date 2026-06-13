#!/usr/bin/env python3
"""Tests for corner_schedule_policy.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "corner_schedule_policy.py"


def _run(*args):
    return subprocess.run([sys.executable, str(PROG), *args],
                          capture_output=True, text=True)


# -- POLICY: iter 0 returns TT-only --
def test_policy_iter0_tt_only(tmp_path):
    out = tmp_path / "o.json"
    r = _run("policy", "0", "--corners", "tt_25C", "ss_-40C", "ff_125C",
             "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["tt_only"] is True
    assert rep["run_corners"] == ["tt_25C"]


# -- POLICY: iter 2 returns the full set --
def test_policy_late_iter_full(tmp_path):
    out = tmp_path / "o.json"
    r = _run("policy", "2", "--corners", "tt_25C", "ss_-40C", "ff_125C",
             "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["tt_only"] is False
    assert rep["run_corners"] == ["tt_25C", "ss_-40C", "ff_125C"]


# -- POLICY: negative iteration → bad input exit 2 --
def test_policy_negative_iter():
    r = _run("policy", "-1")
    assert r.returncode == 2


# -- AUDIT PASS: iter0 TT-only, later iters full --
def test_audit_pass(tmp_path):
    h = tmp_path / "hist.json"
    h.write_text(json.dumps({"iterations": [
        {"iter": 0, "changes": "initial", "corners": ["tt_25C"]},
        {"iter": 1, "changes": "M1 +50%",
         "corners": ["tt_25C", "ss_-40C", "ff_125C"]},
    ]}))
    out = tmp_path / "o.json"
    r = _run("audit", str(h), "--json", str(out))
    assert r.returncode == 0
    assert json.loads(out.read_text())["passed"] is True


# -- AUDIT FAIL: iter0 ran a full sweep (wasteful) --
def test_audit_fail_iter0_full(tmp_path):
    h = tmp_path / "hist.json"
    h.write_text(json.dumps({"iterations": [
        {"iter": 0, "changes": "initial",
         "corners": ["tt_25C", "ss_-40C", "ff_125C"]},
    ]}))
    out = tmp_path / "o.json"
    r = _run("audit", str(h), "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert any(f["rule"] == "ITER0_RAN_FULL_SWEEP" for f in rep["findings"])


# -- AUDIT FAIL: late iter ran TT-only (false convergence) --
def test_audit_fail_late_tt_only(tmp_path):
    h = tmp_path / "hist.json"
    h.write_text(json.dumps({"iterations": [
        {"iter": 0, "changes": "initial", "corners": ["tt_25C"]},
        {"iter": 1, "changes": "M1 +50%", "corners": ["tt_25C"]},
    ]}))
    out = tmp_path / "o.json"
    r = _run("audit", str(h), "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert any(f["rule"] == "LATE_ITER_TT_ONLY" for f in rep["findings"])


# -- AUDIT: garbage / empty file → exit 2 (no vacuous PASS) --
def test_audit_missing_file(tmp_path):
    r = _run("audit", str(tmp_path / "nope.json"))
    assert r.returncode == 2


def test_audit_empty_iterations(tmp_path):
    h = tmp_path / "hist.json"
    h.write_text(json.dumps({"iterations": []}))
    r = _run("audit", str(h))
    assert r.returncode == 2
