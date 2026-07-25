#!/usr/bin/env python3
"""Smoke tests for l22_verification_plan_measurable_check.py (layergate-7).

NEGATIVE CONTROL IS THE POINT
=============================
Every behaviour is asserted in BOTH directions: the gutted layer must
FAIL and the well-formed counterpart must PASS. A test that cannot fail
proves nothing.

All fixtures are SYNTHESISED neutral data — no real design's files are
copied and no fixture carries a design, PDK or vendor identity.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l22_verification_plan_measurable_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _mk(tmp_path, l22=None, docs=None, siblings=None, waivers=None):
    proj = tmp_path / "p"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if l22 is not None:
        (gd / "L22_VERIFICATION_PLAN.json").write_text(
            json.dumps(l22, ensure_ascii=False), encoding="utf-8")
    for code, payload in (siblings or {}).items():
        (gd / f"{code}_SYNTH.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if docs:
        dd = proj / "phase1" / "input_doc"
        dd.mkdir(parents=True, exist_ok=True)
        for name, text in docs.items():
            (dd / name).write_text(text, encoding="utf-8")
    if waivers:
        (proj / "waivers.json").write_text(json.dumps(waivers),
                                           encoding="utf-8")
    return proj


# The exact shape observed in 24/24 sampled real runs: reads as
# populated to any non-empty heuristic, carries zero enforceable target.
_LYING_SKELETON = {
    "doc_id": "L22",
    "doc_name": "L22_VERIFICATION_PLAN",
    "applicability": "APPLICABLE",
    "fields": {
        "coverage_goals": [],
        "formal_properties": [],
        "regression_matrix": {},
        "verification_plan_present": "implicit",
        "verification_categories_derived_from_spec": [
            "Register access", "Nominal transfer", "Error handling",
            "Reset behavior", "Back-to-back operation",
        ],
    },
    "extraction_status": "NOT_YET_EXTRACTED",
    "extraction_evidence": {},
}

_SILENT_SKELETON = {
    "doc_id": "L22",
    "applicability": "APPLICABLE",
    "fields": {"coverage_goals": [], "formal_properties": [],
               "regression_matrix": {}, "verification_plan_present": False},
    "extraction_status": "NOT_YET_EXTRACTED",
    "extraction_evidence": {},
}

_MEASURABLE_GOALS = [
    {"name": "line_coverage", "metric": "line", "target_pct": 90},
    {"name": "functional_coverage", "metric": "functional",
     "target_pct": "95%"},
]

# Synthetic requirement text: a stated, measurable verification target.
_TARGET_DOC = (
    "7.1 Verification Sign-off\n"
    "The regression must reach at least 95% branch coverage before\n"
    "sign-off. Functional coverage target is 100%.\n"
)
# Hard-wrapped, to prove the gate is wrap-insensitive.
_WRAPPED_TARGET_DOC = (
    "7.1 Testplan\n"
    "The goal of this bench is to fully verify the device with 100%\n"
    "coverage. This includes all documented operating modes.\n"
)
# A STATUS report, not a requirement — must NOT trigger.
_STATUS_DOC = (
    "1. Background\n"
    "See `the verification stages guide\n"
    "<https://example.invalid/stages.html#hardware-verification-v>`_.\n"
    "The upstream project has achieved stage V2S, broadly meaning\n"
    "verification is almost complete (over 90% code and functional\n"
    "coverage hit with over 90% regression pass rate)\n"
)
_NO_TARGET_DOC = (
    "7.1 Verification\n"
    "The device shall be exercised across all documented operating\n"
    "modes and the results reviewed by the design owner.\n"
)


# ── skips ────────────────────────────────────────────────────────────

def test_skip_when_no_l22(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    assert _run(proj).returncode == 2


def test_skip_when_not_applicable(tmp_path):
    doc = dict(_LYING_SKELETON, applicability="NOT_APPLICABLE")
    r = _run(_mk(tmp_path, l22=doc, docs={"spec.txt": _TARGET_DOC}))
    assert r.returncode == 2, r.stdout + r.stderr


def test_silent_skeleton_with_no_stated_target_skips(tmp_path):
    """A layer that asserts nothing, for a design that asks nothing."""
    r = _run(_mk(tmp_path, l22=_SILENT_SKELETON,
                 docs={"spec.txt": _NO_TARGET_DOC}))
    assert r.returncode == 2, r.stdout + r.stderr


# ── F1 UNCOMPARABLE_COVERAGE_GOAL — negative control pair ────────────

def test_NEGATIVE_CONTROL_fail_goal_without_numeric_target(tmp_path):
    """GUTTED: a goal a coverage gate cannot compare against."""
    doc = json.loads(json.dumps(_LYING_SKELETON))
    doc["fields"]["coverage_goals"] = [
        {"name": "line_coverage", "target": "high"},
        {"name": "functional_coverage", "target": "full"},
    ]
    r = _run(_mk(tmp_path, l22=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "UNCOMPARABLE_COVERAGE_GOAL" in r.stdout
    assert "numeric_target" in r.stdout


def test_POSITIVE_CONTROL_pass_goals_with_numeric_targets(tmp_path):
    """WELL-FORMED: same two goals, now comparable."""
    doc = json.loads(json.dumps(_LYING_SKELETON))
    doc["fields"]["coverage_goals"] = _MEASURABLE_GOALS
    r = _run(_mk(tmp_path, l22=doc))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_NEGATIVE_CONTROL_fail_prose_string_goal(tmp_path):
    """GUTTED: a sentence is not a target."""
    doc = json.loads(json.dumps(_LYING_SKELETON))
    doc["fields"]["coverage_goals"] = ["Achieve thorough branch coverage"]
    r = _run(_mk(tmp_path, l22=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "UNCOMPARABLE_COVERAGE_GOAL" in r.stdout


def test_NEGATIVE_CONTROL_fail_formal_property_without_statement(tmp_path):
    """GUTTED: a named property a formal tool cannot prove or refute."""
    doc = json.loads(json.dumps(_LYING_SKELETON))
    doc["fields"]["coverage_goals"] = _MEASURABLE_GOALS
    doc["fields"]["formal_properties"] = [{"name": "p_no_overflow"}]
    r = _run(_mk(tmp_path, l22=doc))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "UNCHECKABLE_FORMAL_PROPERTY" in r.stdout


def test_POSITIVE_CONTROL_pass_formal_property_with_statement(tmp_path):
    doc = json.loads(json.dumps(_LYING_SKELETON))
    doc["fields"]["coverage_goals"] = _MEASURABLE_GOALS
    doc["fields"]["formal_properties"] = [
        {"name": "p_no_overflow",
         "assertion": "assert property (@(posedge clk) !(ovf && rdy));"},
    ]
    r = _run(_mk(tmp_path, l22=doc))
    assert r.returncode == 0, r.stdout + r.stderr


# ── F2 TARGET_OUTSIDE_CONSUMING_LAYER — negative control pair ────────

def test_NEGATIVE_CONTROL_fail_target_in_docs_absent_from_l22(tmp_path):
    """GUTTED: the L21 shape — the measurable target is stated in the
    design's own input doc and carried by L22 zero times."""
    r = _run(_mk(tmp_path, l22=_LYING_SKELETON,
                 docs={"vplan.txt": _TARGET_DOC}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "TARGET_OUTSIDE_CONSUMING_LAYER" in r.stdout


def test_POSITIVE_CONTROL_pass_target_present_in_l22(tmp_path):
    """WELL-FORMED: same doc, target now in the consuming layer."""
    doc = json.loads(json.dumps(_LYING_SKELETON))
    doc["fields"]["coverage_goals"] = _MEASURABLE_GOALS
    r = _run(_mk(tmp_path, l22=doc, docs={"vplan.txt": _TARGET_DOC}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_NEGATIVE_CONTROL_fail_hard_wrapped_target(tmp_path):
    """GUTTED: real specs wrap their requirements across lines.

    Measured calibration: a newline-excluding adjacency gap skipped the
    real goal sentence and matched an unrelated status sentence instead
    — the right verdict for the wrong reason. Matching runs on
    whitespace-normalised text so the wrap is invisible.
    """
    r = _run(_mk(tmp_path, l22=_LYING_SKELETON,
                 docs={"vplan.txt": _WRAPPED_TARGET_DOC}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "TARGET_OUTSIDE_CONSUMING_LAYER" in r.stdout


def test_NEGATIVE_CONTROL_fail_target_in_sibling_l_doc(tmp_path):
    sib = {"doc_id": "L24", "fields": {
        "signoff_criteria": ["Code coverage must be at least 90% "
                             "before tapeout sign-off."]}}
    r = _run(_mk(tmp_path, l22=_LYING_SKELETON, siblings={"L24": sib}))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "TARGET_OUTSIDE_CONSUMING_LAYER" in r.stdout


def test_status_report_is_not_a_requirement(tmp_path):
    """A percentage in a status sentence must NOT be read as a target.

    Measured calibration: an earlier draft accepted a bare ``>`` as
    requirement framing, so reStructuredText link markup
    (``…verification-v>`_.``) promoted "the upstream project has
    achieved over 90% coverage" into a requirement for this design.
    Only real requirement words and two-character comparison operators
    count as framing.
    """
    r = _run(_mk(tmp_path, l22=_LYING_SKELETON,
                 docs={"background.txt": _STATUS_DOC}))
    assert "TARGET_OUTSIDE_CONSUMING_LAYER" not in r.stdout
    assert r.returncode == 0, r.stdout + r.stderr


# ── F3 UNFALSIFIABLE_PLAN_ASSERTION — advises, never blocks ──────────

def test_implicit_plan_with_prose_categories_advises(tmp_path):
    """The 24/24 real-run shape: ADVISE, exit 0.

    'implicit' + a prose category list reads as populated to any
    non-empty heuristic while carrying zero enforceable target. It
    ADVISES because the design's own inputs state no numeric target, so
    the layer contradicts no requirement.
    """
    r = _run(_mk(tmp_path, l22=_LYING_SKELETON,
                 docs={"spec.txt": _NO_TARGET_DOC}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[ADVISE]" in r.stdout
    assert "UNFALSIFIABLE_PLAN_ASSERTION" in r.stdout
    assert "[FAIL]" not in r.stdout


def test_advisory_upgrades_to_blocking_when_a_target_exists(tmp_path):
    """Same lying layer + a stated target => BLOCKS, not advises."""
    r = _run(_mk(tmp_path, l22=_LYING_SKELETON,
                 docs={"vplan.txt": _TARGET_DOC}))
    assert r.returncode == 1
    assert "UNFALSIFIABLE_PLAN_ASSERTION" not in r.stdout


# ── waiver ───────────────────────────────────────────────────────────

def test_waiver_suppresses_blocking_finding(tmp_path):
    proj = _mk(tmp_path, l22=_LYING_SKELETON,
               docs={"vplan.txt": _TARGET_DOC},
               waivers=[{"id": "l22_verification_targets_"
                               "intentionally_qualitative",
                         "rationale": "This block is verified by directed "
                                      "review against the reference model; "
                                      "no coverage collector is instantiated "
                                      "at this level."}])
    assert _run(proj).returncode == 2


def test_short_waiver_rationale_does_not_waive(tmp_path):
    proj = _mk(tmp_path, l22=_LYING_SKELETON,
               docs={"vplan.txt": _TARGET_DOC},
               waivers=[{"id": "l22_verification_targets_"
                               "intentionally_qualitative",
                         "rationale": "n/a"}])
    assert _run(proj).returncode == 1


# ── report emission ──────────────────────────────────────────────────

def test_writes_machine_readable_report(tmp_path):
    proj = _mk(tmp_path, l22=_LYING_SKELETON, docs={"vplan.txt": _TARGET_DOC})
    _run(proj)
    rpt = (proj / "reports" / "phase1"
           / "l22_verification_plan_measurable_check.json")
    assert rpt.is_file()
    data = json.loads(rpt.read_text())
    assert data["verdict"] == "FAIL"
    assert data["blocking_findings"][0]["evidence"]
