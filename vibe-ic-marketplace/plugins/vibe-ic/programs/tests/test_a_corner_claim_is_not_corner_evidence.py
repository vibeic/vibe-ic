"""A field called `multi_corner_substantiated` was true on zero corner evidence.

The defect
----------
`_check_sta` computed

    corners_ok = True                    # starts True
    for cd in corner_dirs:               # only per_corner dirs that EXIST
        ... corners_ok = False           # empty dir, or identical copies

so `corners_ok` means *no BROKEN multi-corner claim was found*. A project that
never ran multi-corner STA has no `per_corner` directory, the loop body never
executes, and `corners_ok` stays `True`. It was published as

    "multi_corner_substantiated": true

directly beside

    "corner_dirs_found": 0,
    "corner_reports": 0,
    "corner_reports_distinct": 0,
    "multi_corner_executed": false

Measured verbatim on `edge_llm_accel x nangate45` (plugin v1.9.74) — that JSON
is what `flow_compliance_check --strict` prints as the step's evidence for
BOTH step 10 and step 23, each of which the flow names "multi-corner".

The property field, `multi_corner_executed`, was already correct. Only the name
of the other one was wrong, and it was wrong in the direction that overclaims.

This is the repair #699 made to the PG audit, whose own comment in
`phase3_one_shot_runner` states the rule: "A check that answers one question
and reports another is worse than no check: it converts an unknown into a false
clean bill of health. Every name here now states the question that was actually
asked."

Renamed to `multi_corner_claim_not_broken`. No verdict changes: `result.passed`
still reads the same `corners_ok`, and the STA_SINGLE_CORNER_ONLY advisory is
untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eda_report_audit as ERA                                # noqa: E402

_SRC = (_PROGRAMS / "eda_report_audit.py").read_text(encoding="utf-8")

_RPT = "Startpoint: a\nEndpoint: b\nPath Type: max\nslack (MET)\nOpenSTA\n"


def _single_corner_project(tmp_path: Path) -> Path:
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(_RPT)
    return tmp_path


def test_no_corner_evidence_publishes_no_substantiation_claim(tmp_path):
    r = ERA._check_sta(_single_corner_project(tmp_path))
    s = r.summary
    assert s["corner_dirs_found"] == 0
    assert s["corner_reports"] == 0
    assert s["corner_reports_distinct"] == 0
    assert s["multi_corner_executed"] is False
    assert "multi_corner_substantiated" not in s, (
        "the summary still asserts multi-corner SUBSTANTIATION while its own "
        f"corner counters are all zero: {s}")
    assert s["multi_corner_claim_not_broken"] is True


def test_the_renamed_field_still_carries_the_same_measurement(tmp_path):
    """NEGATIVE CONTROL — the rename must not change what is measured. An
    EMPTY per_corner directory is a broken claim and must still read False."""
    proj = _single_corner_project(tmp_path)
    (proj / "phase3" / "stage3" / "sta" / "per_corner").mkdir()
    r = ERA._check_sta(proj)
    assert r.summary["multi_corner_claim_not_broken"] is False
    assert any(f.rule == "STA_PER_CORNER_EMPTY" and f.severity == "ERROR"
               for f in r.findings)


def test_two_distinct_corner_reports_are_still_multi_corner(tmp_path):
    """POSITIVE CONTROL — real multi-corner evidence still reads True on both
    fields, so the rename did not narrow the passing case."""
    proj = _single_corner_project(tmp_path)
    pc = proj / "phase3" / "stage3" / "sta" / "per_corner"
    pc.mkdir()
    (pc / "ss.rpt").write_text(_RPT + "corner: ss\n")
    (pc / "ff.rpt").write_text(_RPT + "corner: ff\n")
    r = ERA._check_sta(proj)
    assert r.summary["multi_corner_claim_not_broken"] is True
    assert r.summary["multi_corner_executed"] is True


def test_the_overclaiming_name_is_gone_from_the_emitter():
    """It survives in ONE comment, which documents the defect. It must not
    survive as an emitted key."""
    emitted = [ln for ln in _SRC.splitlines()
               if '"multi_corner_substantiated":' in ln
               and not ln.strip().startswith("#")]
    assert emitted == [], emitted
