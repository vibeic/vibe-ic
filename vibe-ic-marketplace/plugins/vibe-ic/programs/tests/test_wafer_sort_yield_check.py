#!/usr/bin/env python3
"""Tests for wafer_sort_yield_check.py — Step 39 wafer-sort yield gate.

Pins the anti-fabrication hardening: the checker must independently
recompute the yield from die counts and compare against a *stated* spec
target — it must never echo a self-asserted boolean, never fabricate a
target, and must FAIL honestly on missing/empty/inconsistent data.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "wafer_sort_yield_check.py"

_spec = importlib.util.spec_from_file_location("wafer_sort_yield_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# fixture builders
# ----------------------------------------------------------------------
def _mfg_dir(project: Path) -> Path:
    d = project / "phase3" / "stage5_manufacturing"
    d.mkdir(parents=True, exist_ok=True)
    # The step's condition artefact (silicon received).
    (d / "silicon_received.json").write_text(json.dumps({"received": True}))
    return d


def _write_yield(d: Path, doc: dict):
    (d / "wafer_sort_yield.json").write_text(json.dumps(doc))


def _write_map(d: Path, n_data_rows: int, header: bool = True):
    p = d / "wafer_map.csv"
    with p.open("w", newline="") as fh:
        w = csv.writer(fh)
        if header:
            w.writerow(["x", "y", "bin", "pass"])
        for i in range(n_data_rows):
            w.writerow([i % 10, i // 10, 1 if i % 7 else 4, int(i % 7 != 0)])


def _run(project: Path):
    out_json = project / "report.json"
    rc = mod.main([str(project), "--json", str(out_json)])
    report = json.loads(out_json.read_text()) if out_json.is_file() else None
    return rc, report


# ----------------------------------------------------------------------
# PASS — substance good
# ----------------------------------------------------------------------
def test_pass_counts_meet_target(tmp_path):
    d = _mfg_dir(tmp_path)
    # 920/1000 = 92.0% measured, target 85% -> PASS
    _write_yield(d, {
        "good_die": 920, "total_die": 1000,
        "target_yield_pct": 85.0,
        # self-asserted boolean that the OLD gate trusted; checker ignores it
        "yield_meets_target": True,
    })
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["measured_yield_pct"] == pytest.approx(92.0)
    assert rep["target_yield_pct"] == pytest.approx(85.0)
    assert rep["wafer_map_rows"] == 1000


def test_pass_with_stated_pct_consistent(tmp_path):
    d = _mfg_dir(tmp_path)
    _write_yield(d, {
        "good_die": 880, "total_die": 1000,
        "yield_pct": 88.0, "target_yield_pct": 80.0,
    })
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 0 and rep["verdict"] == "PASS"


# ----------------------------------------------------------------------
# FAIL — the exact silicon failure the gate guards: yield below target.
# This is what a self-asserted boolean would have falsely PASSed.
# ----------------------------------------------------------------------
def test_fail_yield_below_target(tmp_path):
    d = _mfg_dir(tmp_path)
    # 600/1000 = 60% measured but target 85% -> must FAIL even though the
    # producing step lied with yield_meets_target=True.
    _write_yield(d, {
        "good_die": 600, "total_die": 1000,
        "target_yield_pct": 85.0,
        "yield_meets_target": True,
    })
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "YIELD_BELOW_TARGET" in rules


def test_fail_stated_pct_inconsistent_with_counts(tmp_path):
    # Fabrication smell: stated 95% but counts say 60%.
    d = _mfg_dir(tmp_path)
    _write_yield(d, {
        "good_die": 600, "total_die": 1000,
        "yield_pct": 95.0, "target_yield_pct": 85.0,
    })
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "YIELD_SELF_INCONSISTENT" in {f["rule"] for f in rep["findings"]}


def test_fail_wafer_map_rowcount_inconsistent(tmp_path):
    d = _mfg_dir(tmp_path)
    _write_yield(d, {
        "good_die": 920, "total_die": 1000, "target_yield_pct": 85.0,
    })
    _write_map(d, 640)  # rows != total_die
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "WAFER_MAP_ROWCOUNT_INCONSISTENT" in {
        f["rule"] for f in rep["findings"]
    }


# ----------------------------------------------------------------------
# Missing / insufficient data -> honest FAIL (never vacuous PASS)
# ----------------------------------------------------------------------
def test_fail_missing_artefacts(tmp_path):
    _mfg_dir(tmp_path)  # silicon received, but no yield/map files
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "REQUIRED_ARTEFACT_MISSING" in {f["rule"] for f in rep["findings"]}


def test_fail_no_target_refuses_to_fabricate(tmp_path):
    d = _mfg_dir(tmp_path)
    # Good measured yield but NO stated target -> must FAIL, not invent one.
    _write_yield(d, {"good_die": 990, "total_die": 1000})
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "NO_TARGET_YIELD" in {f["rule"] for f in rep["findings"]}


def test_fail_no_measured_yield(tmp_path):
    d = _mfg_dir(tmp_path)
    _write_yield(d, {"target_yield_pct": 85.0})  # target but no counts/pct
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "NO_MEASURED_YIELD" in {f["rule"] for f in rep["findings"]}


def test_fail_empty_wafer_map(tmp_path):
    d = _mfg_dir(tmp_path)
    _write_yield(d, {"good_die": 920, "total_die": 1000,
                     "target_yield_pct": 85.0})
    (d / "wafer_map.csv").write_text("x,y,bin,pass\n")  # header only
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "WAFER_MAP_EMPTY" in {f["rule"] for f in rep["findings"]}


def test_fail_unparseable_yield_json(tmp_path):
    d = _mfg_dir(tmp_path)
    (d / "wafer_sort_yield.json").write_text("{not valid json")
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert "YIELD_JSON_UNPARSEABLE" in {f["rule"] for f in rep["findings"]}


# ----------------------------------------------------------------------
# Waiver path + SKIP only on operational absence
# ----------------------------------------------------------------------
def test_waived_when_missing_and_waiver_present(tmp_path):
    _mfg_dir(tmp_path)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "wafer_sort_yield",
            "ticket": "WAIVE-39",
            "reason": "non-production bring-up; no sort data",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"


def test_skip_only_when_project_dir_missing(tmp_path):
    rc = mod.main([str(tmp_path / "does_not_exist")])
    assert rc == 2


# ----------------------------------------------------------------------
# alias coverage: fail_die/tested_die reconstruction + legacy path
# ----------------------------------------------------------------------
def test_pass_from_fail_die_alias_and_legacy_path(tmp_path):
    d = tmp_path / "manufacturing"          # legacy location
    d.mkdir(parents=True)
    # silicon condition lives in the canonical place regardless
    _mfg_dir(tmp_path)
    _write_yield(d, {
        "fail_die": 50, "total_die": 1000,   # good = 950 -> 95%
        "target_yield_pct": 90.0,
    })
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 0 and rep["verdict"] == "PASS"
    assert rep["measured_yield_pct"] == pytest.approx(95.0)


# ----------------------------------------------------------------------
# boundary: exactly at target passes
# ----------------------------------------------------------------------
def test_pass_exactly_at_target(tmp_path):
    d = _mfg_dir(tmp_path)
    _write_yield(d, {"good_die": 850, "total_die": 1000,
                     "target_yield_pct": 85.0})
    _write_map(d, 1000)
    rc, rep = _run(tmp_path)
    assert rc == 0 and rep["verdict"] == "PASS"
