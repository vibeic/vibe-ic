#!/usr/bin/env python3
"""Tests for ir_drop_budget_check.py — numeric IR-drop budget gate.

Covers PASS (under budget), FAIL (over budget), and the honest-failure
edges: missing report, garbage JSON, no drop value, mV-without-Vdd.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "ir_drop_budget_check.py"


def _run(*args) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), *[str(a) for a in args]]
    return subprocess.run(cmd, capture_output=True, text=True)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------- PASS

def test_pass_under_budget_json_mv(tmp_path):
    rpt = _write(tmp_path / "ir.json",
                 {"max_ir_drop_mv": 50.0, "vdd_v": 1.8})  # 50/1800 = 2.78% < 10%
    r = _run(rpt, "--json", tmp_path / "out.json")
    assert r.returncode == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["pass"] is True
    assert rep["measured"]["drop_pct_vdd"] < 10.0


def test_pass_under_budget_pct_key(tmp_path):
    rpt = _write(tmp_path / "ir.json", {"max_ir_drop_pct": 4.5})
    r = _run(rpt)
    assert r.returncode == 0


def test_pass_rpt_text(tmp_path):
    rpt = _write(tmp_path / "ir.rpt",
                 "Power grid sign-off\nWorst static IR drop: 30 mV\nVdd = 1.2 V\n")
    r = _run(rpt)
    assert r.returncode == 0  # 30/1200 = 2.5% < 10%


def test_pass_cli_vdd_overrides(tmp_path):
    rpt = _write(tmp_path / "ir.json", {"max_ir_drop_mv": 80.0})
    r = _run(rpt, "--vdd", "1.8")  # 80/1800 = 4.4% < 10%
    assert r.returncode == 0


def test_pass_directory_discovery(tmp_path):
    _write(tmp_path / "reports" / "phase3" / "ir_drop.rpt",
           "max voltage drop 40 mV\nVdd: 1.8 V\n")
    r = _run(tmp_path)  # directory → discovers the .rpt
    assert r.returncode == 0


# ---------------------------------------------------------------- FAIL

def test_fail_over_budget_mv(tmp_path):
    rpt = _write(tmp_path / "ir.json",
                 {"max_ir_drop_mv": 250.0, "vdd_v": 1.8})  # 13.9% > 10%
    r = _run(rpt)
    assert r.returncode == 1


def test_fail_over_budget_pct(tmp_path):
    rpt = _write(tmp_path / "ir.json", {"worst_ir_drop_percent": 12.0})
    r = _run(rpt)
    assert r.returncode == 1


def test_fail_tight_custom_budget(tmp_path):
    # 6% drop passes default 10% but fails a strict 5% house rule.
    rpt = _write(tmp_path / "ir.json", {"max_ir_drop_pct": 6.0})
    assert _run(rpt).returncode == 0
    assert _run(rpt, "--budget-pct", "5").returncode == 1


# ----------------------------------------------------- HONEST FAILURE / edge

def test_fail_no_drop_value(tmp_path):
    rpt = _write(tmp_path / "ir.json", {"vdd_v": 1.8, "tool": "OpenROAD"})
    r = _run(rpt)
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert any(f["rule"] == "NO_DROP_VALUE" for f in rep["findings"])


def test_fail_mv_without_vdd(tmp_path):
    rpt = _write(tmp_path / "ir.json", {"max_ir_drop_mv": 50.0})
    r = _run(rpt)
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert any(f["rule"] == "NO_VDD" for f in rep["findings"])


def test_fail_garbage_json(tmp_path):
    rpt = _write(tmp_path / "ir.json", "{not valid json,,,}")
    r = _run(rpt)
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert any(f["rule"] == "BAD_JSON" for f in rep["findings"])


def test_exit2_missing_report(tmp_path):
    r = _run(tmp_path / "does_not_exist.json")
    assert r.returncode == 2


def test_exit2_empty_dir(tmp_path):
    # directory exists but holds no IR report → discovery returns None → rc 2
    (tmp_path / "empty").mkdir()
    r = _run(tmp_path / "empty")
    assert r.returncode == 2


def test_exit2_bad_budget(tmp_path):
    rpt = _write(tmp_path / "ir.json", {"max_ir_drop_pct": 3.0})
    r = _run(rpt, "--budget-pct", "0")
    assert r.returncode == 2
