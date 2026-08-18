#!/usr/bin/env python3
"""Tests for phase1_coverage_report_present_check.py (BACKLOG-v13 Wave 5).

Gate verifies that after Phase 2a, the project has both
`reports/extraction_coverage_report.md` and `.json`, AND that
overall.pct >= 95% (or a waiver is present).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "phase1_coverage_report_present_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put_l(project: Path, name: str, data: dict):
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data, ensure_ascii=False))


def _put_report(project: Path, *, pct: float, per_doc=None):
    rep = project / "reports" / "phase1"
    rep.mkdir(parents=True, exist_ok=True)
    js = {
        "schema_version": 2,
        "overall": {
            "hit": int(pct),
            "total": 100,
            "pct": pct,
        },
        "per_doc": per_doc or [],
    }
    (rep / "extraction_coverage_report.json").write_text(
        json.dumps(js, ensure_ascii=False))
    (rep / "extraction_coverage_report.md").write_text(
        f"# Phase 2a Extraction Coverage Report\nOverall: {pct}%\n")


def _put_waiver(project: Path, key: str, reason: str):
    (project / "waivers.json").write_text(
        json.dumps({key: reason}, ensure_ascii=False))


# -------------------------------------------------------------------
# 1. Bare-skeleton project — the skip must REACH THE TIER (vibe-ic#1185).
# -------------------------------------------------------------------
def test_skip_when_phase1_not_attempted_is_not_counted_as_a_pass(tmp_path):
    """This test used to assert `returncode == 0`, under a section heading
    that called it a "silent skip" — i.e. it pinned the defect.

    `flow_compliance_check` reads only the return code plus a LINE-START
    `VACUOUS_PASS` / `PASS_WITH_WAIVERS` sentinel (`:3658`,
    `line.lstrip().startswith`). A bare `SKIP —` line at rc 0 therefore had NO
    channel to the tier: #1185 measured the step resolving PASS while this
    clause had examined nothing (`test_matrix_d6_skip_discipline[step1]`).

    Changing this expectation is STRENGTHENING it, not weakening it: the old
    assertion was satisfied by a gate that declines to look, and the new one is
    not. rc 2 is this program's own existing convention for "cannot look"
    (already used for a missing project dir) and is what
    `flow_compliance_check:3056` documents as the input-missing skip.
    """
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    # BOTH channels, because either alone is one edit from being dropped.
    assert r.stdout.splitlines()[0].startswith("VACUOUS_PASS"), r.stdout
    assert "SKIP" in r.stdout
    assert "not attempted" in r.stdout
    assert "NOT a pass" in r.stdout


def test_a_report_with_no_measurement_is_also_not_a_pass(tmp_path):
    """The SECOND decline-to-look (vibe-ic#1185), which had no test at all.

    Its own comment used to read "treat as silent skip so we don't penalize
    empty-pattern projects". Not penalising an empty-pattern project is right;
    reporting it as a PASS over a coverage report that was never measured is
    not. The report EXISTS here and carries no measurement, so the gate has
    still examined nothing.
    """
    _put_l(tmp_path, "L1.json", {"x": "y"})
    # `_put_report` hardcodes total=100, which is a MEASURED report; this case
    # is the unmeasured one, so the payload is written directly.
    rep = tmp_path / "reports" / "phase1"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "extraction_coverage_report.json").write_text(json.dumps(
        {"schema_version": 2,
         "overall": {"hit": 0, "total": 0, "pct": None},
         "per_doc": []}))
    (rep / "extraction_coverage_report.md").write_text("# report\n")
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert r.stdout.splitlines()[0].startswith("VACUOUS_PASS"), r.stdout
    assert "NOT measured" in r.stdout


def test_a_measured_report_is_still_an_ordinary_PASS(tmp_path):
    """PAIRED GUARD.

    A checker that returned `VACUOUS_PASS`/2 unconditionally would satisfy both
    tests above. It dies here: a report that WAS measured must come back rc 0
    with no vacuity sentinel, or the disclosure has stopped discriminating and
    every run reads as "nothing was measured".
    """
    _put_l(tmp_path, "L1.json", {"x": "y"})
    _put_report(tmp_path, pct=100.0)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VACUOUS_PASS" not in r.stdout, r.stdout


# -------------------------------------------------------------------
# 2. Phase 2a attempted (generated_docs/) but report missing → FAIL.
# -------------------------------------------------------------------
def test_fail_when_report_missing(tmp_path):
    _put_l(tmp_path, "L1.json", {"x": "y"})
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "report missing" in r.stdout
    # Suggests how to fix
    assert "phase1_coverage_report_gen.py" in r.stdout


# -------------------------------------------------------------------
# 3. Report present + 100% coverage → PASS.
# -------------------------------------------------------------------
def test_pass_when_full_coverage(tmp_path):
    _put_l(tmp_path, "L1.json", {"x": "y"})
    _put_report(tmp_path, pct=100.0)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "100" in r.stdout


# -------------------------------------------------------------------
# 4. Report present but coverage <100% → FAIL with per-doc breakdown.
#    Wave 23 (v0.119.55) — threshold is now 100%, so 99.9% FAILs.
# -------------------------------------------------------------------
def test_fail_below_threshold_with_breakdown(tmp_path):
    _put_l(tmp_path, "L1.json", {"x": "y"})
    _put_report(
        tmp_path, pct=80.0,
        per_doc=[
            {"doc": "doc_a.txt", "hit": 4, "total": 5, "pct": 80.0},
            {"doc": "doc_b.txt", "hit": 10, "total": 10, "pct": 100.0},
        ],
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "80.0" in r.stdout
    assert "doc_a.txt" in r.stdout
    # Above-threshold doc not in breakdown
    assert "doc_b.txt" not in r.stdout


# -------------------------------------------------------------------
# 5. Wave 23 (v0.119.55) — waiver no longer suppresses below-threshold.
# -------------------------------------------------------------------
def test_waiver_no_longer_suppresses_below_threshold(tmp_path):
    _put_l(tmp_path, "L1.json", {"x": "y"})
    _put_report(tmp_path, pct=70.0)
    _put_waiver(
        tmp_path,
        "phase1_coverage_below_threshold_intentional",
        "Vendor docs include legacy ORG block intentionally not "
        "extracted; tracked via TICKET-1234.",
    )
    r = _run(tmp_path)
    # Wave 23 — waiver path removed; FAIL.
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "no waiver" in r.stdout.lower() or "NO waiver" in r.stdout


# -------------------------------------------------------------------
# 6. Invalid project dir → exit 2.
# -------------------------------------------------------------------
def test_invalid_project_dir(tmp_path):
    bogus = tmp_path / "does_not_exist"
    r = _run(bogus)
    assert r.returncode == 2
    assert "not found" in r.stdout


# -------------------------------------------------------------------
# 7. Wired into _STRUCTURAL_RTL_GATES.
# -------------------------------------------------------------------
def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "phase1_coverage_report_present_check" in txt, (
        "Wave 5 gate not wired into flow_compliance_check.py "
        "_STRUCTURAL_RTL_GATES tuple")
