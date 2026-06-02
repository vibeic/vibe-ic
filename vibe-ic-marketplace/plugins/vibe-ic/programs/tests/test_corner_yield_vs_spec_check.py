#!/usr/bin/env python3
"""Tests for corner_yield_vs_spec_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "corner_yield_vs_spec_check.py"


def _run(proj: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(proj),
         "--json", str(proj / "report.json")],
        capture_output=True, text=True)


def _report(proj: Path) -> dict:
    return json.loads((proj / "report.json").read_text())


def _block(proj: Path, name="ldo"):
    d = proj / "phase3" / "analog" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(d: Path, spec, corners):
    if spec is not None:
        (d / "spec.json").write_text(json.dumps(spec))
    if corners is not None:
        (d / "corner_results.json").write_text(json.dumps({"corners": corners}))


# -- PASS: all corners satisfy spec.json limits, worst corner identified --
def test_pass_all_corners_satisfy(tmp_path):
    d = _block(tmp_path)
    _write(d,
           {"specs": {"gain_db": {"min": 55}, "power_uw": {"max": 100}}},
           [{"name": "tt_25C", "measured": {"gain_db": 60, "power_uw": 80}},
            {"name": "ss_-40C", "measured": {"gain_db": 56, "power_uw": 95}},
            {"name": "ff_125C", "measured": {"gain_db": 70, "power_uw": 70}}])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rep = _report(tmp_path)
    assert rep["passed"] is True
    det = rep["summary"]["details"][0]
    # ss_-40C has the tightest gain margin → worst corner
    assert det["worst_corner"] == "ss_-40C"
    assert det["violations"] == 0


# -- FAIL: a corner violates the min limit (status field could lie) --
def test_fail_corner_violates_min(tmp_path):
    d = _block(tmp_path)
    _write(d,
           {"specs": {"gain_db": {"min": 55}}},
           [{"name": "tt_25C", "measured": {"gain_db": 60}},
            {"name": "ss_-40C", "measured": {"gain_db": 48}}])  # < 55
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert rep["passed"] is False
    assert any(f["rule"] == "SPEC_VIOLATED_AT_CORNER" for f in rep["findings"])


# -- FAIL: spec.json declares limits but no corner_results.json --
def test_fail_missing_corner_evidence(tmp_path):
    d = _block(tmp_path)
    _write(d, {"specs": {"gain_db": {"min": 55}}}, None)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "MISSING_CORNER_EVIDENCE" for f in rep["findings"])


# -- FAIL (no vacuous PASS): spec.json with no numeric limits --
def test_fail_no_numeric_limits(tmp_path):
    d = _block(tmp_path)
    _write(d, {"specs": {"gain_db": {"description": "high"}}},
           [{"name": "tt_25C", "measured": {"gain_db": 60}}])
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "NO_NUMERIC_LIMITS" for f in rep["findings"])


# -- FAIL: corner data never overlaps the spec names --
def test_fail_no_overlap(tmp_path):
    d = _block(tmp_path)
    _write(d, {"specs": {"gain_db": {"min": 55}}},
           [{"name": "tt_25C", "measured": {"bandwidth_mhz": 10}}])
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "NO_OVERLAP" for f in rep["findings"])


# -- SKIP: no analog dir → honest self-skip, exit 0 --
def test_skip_no_analog(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = _report(tmp_path)
    assert rep["summary"]["skipped"] is True


# -- SKIP: deterministic-stub corner data --
def test_stub_skipped(tmp_path):
    d = _block(tmp_path)
    (d / "spec.json").write_text(json.dumps({"specs": {"gain_db": {"min": 55}}}))
    (d / "corner_results.json").write_text(json.dumps(
        {"extraction_strategy": "deterministic_stub", "corners": []}))
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = _report(tmp_path)
    assert any(f["rule"] == "YIELD_STUB_SKIPPED" for f in rep["findings"])


# -- FAIL: garbage (unparsable) corner_results.json --
def test_fail_garbage_corner(tmp_path):
    d = _block(tmp_path)
    (d / "spec.json").write_text(json.dumps({"specs": {"gain_db": {"min": 55}}}))
    (d / "corner_results.json").write_text("{not valid json")
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "CORNER_PARSE_ERROR" for f in rep["findings"])
