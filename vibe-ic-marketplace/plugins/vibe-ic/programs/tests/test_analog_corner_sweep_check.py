#!/usr/bin/env python3
"""Tests for analog_corner_sweep_check.py — PVT corner coverage gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_corner_sweep_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _setup_corner_results(tmp_path, block="ldo", total=15, found=15,
                          spec_results=None, mc_yield=None,
                          design_content="structure_and_geometry"):
    """`design_content` is the artefact's own record of WHAT circuit produced
    the corners.

    It has a default because these fixtures are about PVT COVERAGE, and one
    that said nothing would make each of them assert something extra and
    false: that a coverage gate may certify a sweep without knowing what was
    swept. Pass `None` to build the artefact that declines to say.
    """
    d = tmp_path / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    data = {"total_corners": total, "results_found": found}
    if design_content is not None:
        data["design_content"] = design_content
    if spec_results is not None:
        data["spec_results"] = spec_results
    if mc_yield is not None:
        data["mc_yield_pct"] = mc_yield
    (d / "corner_results.json").write_text(json.dumps(data))


# -- Test: PASS with sufficient corners and all specs passing --

def test_pass_all_corners(tmp_path):
    _setup_corner_results(tmp_path, total=15, found=15, spec_results=[
        {"spec": "vout", "corner": "tt_25C", "status": "PASS"},
        {"spec": "vout", "corner": "ss_125C", "status": "PASS"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["blocks_pass"] == 1


# ── WHAT THE COVERED PVT SPACE WAS COVERED FOR ────────────────────────────
# Fifteen corners and every spec clean is true of a library nominal exactly as
# it is of a design sized to its spec, and this gate said the same `[PASS]` for
# either. The ranking below is what stops a producer being paid to say less:
#
#   design-bound   -> [PASS]
#   structure-only -> [PASS_STRUCTURE_ONLY]  disclosed, certifies in its tier
#   undisclosed    -> rc 1                   does not certify at all

def test_a_library_topologys_pvt_space_is_not_this_designs(tmp_path):
    """Disclosed, so it certifies — in its own tier, and never as a plain
    pass. Not a FAIL: failing an honest ceiling teaches the next run to stop
    being honest."""
    _setup_corner_results(tmp_path, total=15, found=15,
                          design_content="structure_only",
                          spec_results=[{"spec": "vout", "status": "PASS"}])
    r = subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[0].startswith("[PASS_STRUCTURE_ONLY]"), \
        r.stdout
    assert "STRUCTURE_ONLY:" in r.stderr, r.stderr


def test_a_sweep_that_will_not_say_what_it_swept_does_not_certify(tmp_path):
    """Silence must not be the cheap answer. Same 15 corners, same clean
    specs, the one field removed — the shape of every artefact written before
    the field existed, and of every stale one."""
    _setup_corner_results(tmp_path, total=15, found=15, design_content=None,
                          spec_results=[{"spec": "vout", "status": "PASS"}])
    r = _run(tmp_path)
    assert r.returncode == 1, (
        "a PVT coverage gate certified a sweep whose artefact will not say "
        "what circuit produced the corners")
    rpt = _load_report(tmp_path)
    assert any(f["rule"] == "CORNER_SUBJECT_UNDECLARED"
               for f in rpt["findings"]), rpt["findings"]


def test_a_coverage_failure_is_still_diagnosed_as_a_coverage_failure(
        tmp_path):
    """Ordering control: an artefact that is BOTH silent and short of corners
    must be reported for the corner count."""
    _setup_corner_results(tmp_path, total=3, found=3, design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = [f["rule"] for f in _load_report(tmp_path)["findings"]]
    assert "INSUFFICIENT_CORNERS" in rules, rules
    assert "CORNER_SUBJECT_UNDECLARED" not in rules, rules


# -- Test: FAIL with insufficient corners --

def test_fail_missing_corner(tmp_path):
    _setup_corner_results(tmp_path, total=3, found=3)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("INSUFFICIENT_CORNERS" in f["rule"] for f in errors)


# -- Test: FAIL with spec violation --

def test_fail_spec_violation(tmp_path):
    _setup_corner_results(tmp_path, total=15, found=15, spec_results=[
        {"spec": "vout", "corner": "ss_125C", "status": "FAIL"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("SPEC_FAIL_AT_CORNER" in f["rule"] for f in errors)


# -- Test: self-skip when no corner data --

def test_skip_no_data(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS, not a plain PASS
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True


# -- Test: exit 2 on non-existent directory --

def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
