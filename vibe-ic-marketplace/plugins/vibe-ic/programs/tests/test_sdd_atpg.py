"""Unit tests for sdd_atpg_run.py + sdd_coverage_check.py.

The heavy path (DT2 OpenSTA + Yosys `sat` in Docker, which SDD REUSES rather
than re-implements) is validated end-to-end on spm (recorded in the gatekeeper
report), not re-run here. These tests cover the PURE helpers, which carry the
SDD soundness guarantees:
  - the DISCLOSED small-delay margin (margin_ns = margin_fraction × period)
  - slack → strong / weak / undetected_at_speed bucketing (strong ONLY within
    the margin AND only when sensitizable)
  - the slack-detectability weight (1 strong, margin/slack weak, 0 undetected)
  - grade_path_records mapping DT2 records → SDD per-fault records
  - the slack-weighted / binary-strong coverage math
  - the design-wide SOUND lower bound (no fault strong if no path within margin)
  - the transition-fault population summary
  - the gate's FALSE-CLEAN-PROOF recount: a high-slack path marked 'strong'
    FAILs; a fabricated sensitisation flag FAILs; an inflated coverage FAILs; a
    DOCTORED margin_ns is re-derived and caught
  - NOT_APPLICABLE passthrough, zero-evidence FAIL, margin-fraction cap
"""
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import sdd_atpg_run as sdd  # noqa: E402
import sdd_coverage_check as gate  # noqa: E402


# ── DISCLOSED margin threshold ──────────────────────────────────────────────

def test_margin_ns_from_fraction():
    assert sdd.sdd_margin_ns(10.0, 0.10) == 1.0
    assert sdd.sdd_margin_ns(8.0, 0.25) == 2.0


def test_margin_ns_unknown_period():
    assert sdd.sdd_margin_ns(None, 0.10) is None
    assert sdd.sdd_margin_ns(0.0, 0.10) is None
    assert sdd.sdd_margin_ns(10.0, -0.1) is None


def test_transition_of_edge():
    assert sdd.transition_of_edge("^") == "STR"
    assert sdd.transition_of_edge("v") == "STF"


# ── slack bucketing (strong ONLY within margin AND sensitizable) ────────────

def test_bucket_strong_within_margin():
    # slack 0.5 <= margin 1.0, sensitizable -> strong
    assert sdd.slack_bucket(0.5, True, 1.0) == "strong"
    assert sdd.slack_bucket(1.0, True, 1.0) == "strong"   # boundary inclusive


def test_bucket_weak_above_margin():
    # slack 9.1 >> margin 1.0 (spm-shape), sensitizable -> weak
    assert sdd.slack_bucket(9.117, True, 1.0) == "weak"


def test_bucket_undetected_when_not_sensitizable():
    # a tight path that is NOT sensitizable is never strong/weak
    assert sdd.slack_bucket(0.1, False, 1.0) == "undetected_at_speed"


def test_bucket_undetected_when_no_slack_or_margin():
    assert sdd.slack_bucket(None, True, 1.0) == "undetected_at_speed"
    assert sdd.slack_bucket(0.5, True, None) == "undetected_at_speed"


def test_bucket_violated_slack_is_strong():
    # slack <= 0 (timing violation) is within any positive margin -> strong
    assert sdd.slack_bucket(-0.2, True, 1.0) == "strong"


# ── slack-detectability weight ──────────────────────────────────────────────

def test_weight_strong_is_one():
    assert sdd.sdd_weight(0.5, True, 1.0) == 1.0
    assert sdd.sdd_weight(1.0, True, 1.0) == 1.0


def test_weight_weak_is_margin_over_slack():
    # spm-shape: margin 1.0 / slack 9.117 ≈ 0.1097
    w = sdd.sdd_weight(9.117, True, 1.0)
    assert 0.10 < w < 0.11
    # monotone: a slackier path has a smaller weight
    assert sdd.sdd_weight(18.0, True, 1.0) < w


def test_weight_undetected_is_zero():
    assert sdd.sdd_weight(0.5, False, 1.0) == 0.0
    assert sdd.sdd_weight(None, True, 1.0) == 0.0
    assert sdd.sdd_weight(0.5, True, 0.0) == 0.0


# ── grade_path_records: DT2 records -> SDD per-fault records ────────────────

def _dt2_records():
    # spm-shape: sensitizable high-slack paths (all weak at margin 1.0), plus a
    # non-sensitizable (RED) path and an unmappable one.
    return [
        {"idx": 0, "startpoint": "_423_", "endpoint": "_422_", "end_edge": "v",
         "arrival": 0.6616, "slack": 9.117, "loc_testable": True,
         "nr_verdict": "DET", "robust_verdict": "DET"},
        {"idx": 1, "startpoint": "_421_", "endpoint": "_420_", "end_edge": "^",
         "arrival": 0.6565, "slack": 9.122, "loc_testable": True,
         "nr_verdict": "DET", "robust_verdict": "DET"},
        {"idx": 2, "startpoint": "_419_", "endpoint": "_418_", "end_edge": "v",
         "arrival": 0.6544, "slack": 9.1249, "loc_testable": True,
         "nr_verdict": "RED", "robust_verdict": "RED"},   # false/held
        {"idx": 3, "startpoint": "u", "endpoint": "v", "end_edge": "^",
         "arrival": None, "slack": None, "loc_testable": False,
         "status": "unmappable"},                          # excluded
    ]


def test_grade_path_records_shape():
    recs = sdd.grade_path_records(_dt2_records(), margin_ns=1.0)
    assert len(recs) == 4
    r0 = recs[0]
    assert r0["direction"] == "STF"          # 'v' capture
    assert r0["detecting_path_slack_ns"] == 9.117
    assert r0["sensitizable"] is True
    assert r0["sdd_bucket"] == "weak"        # 9.117 >> 1.0
    assert recs[1]["direction"] == "STR"     # '^' capture
    # RED path: not sensitizable -> undetected
    assert recs[2]["sensitizable"] is False
    assert recs[2]["sdd_bucket"] == "undetected_at_speed"
    # unmappable path: not loc_testable
    assert recs[3]["loc_testable"] is False


def test_grade_records_strong_when_tight():
    tight = [{"idx": 0, "startpoint": "a", "endpoint": "b", "end_edge": "^",
              "arrival": 9.5, "slack": 0.3, "loc_testable": True,
              "nr_verdict": "DET", "robust_verdict": "DET"}]
    recs = sdd.grade_path_records(tight, margin_ns=1.0)
    assert recs[0]["sdd_bucket"] == "strong"
    assert recs[0]["sdd_weight"] == 1.0


# ── coverage math ──────────────────────────────────────────────────────────

def test_coverage_math_spm_shape_mostly_weak():
    recs = sdd.grade_path_records(_dt2_records(), margin_ns=1.0)
    cov = sdd.sdd_coverage_math(recs, margin_ns=1.0, period_ns=10.0)
    # graded = 3 loc_testable (idx0,1 weak; idx2 undetected); idx3 excluded
    assert cov["graded_faults"] == 3
    assert cov["strong"] == 0
    assert cov["weak"] == 2
    assert cov["undetected_at_speed"] == 1
    assert cov["sdd_binary_strong_coverage_pct"] == 0.0
    # slack-weighted = mean(w) over graded = (0.1097 + 0.1097 + 0)/3 * 100 ≈ 7.3
    assert 6.0 < cov["sdd_slack_weighted_coverage_pct"] < 8.0
    # tightest = idx0 (slack 9.117), and even IT is weak
    assert cov["tightest_path"]["endpoint"] == "_422_"
    assert cov["tightest_path"]["sdd_bucket"] == "weak"


def test_coverage_math_with_a_strong_path():
    recs = sdd.grade_path_records(
        _dt2_records() + [
            {"idx": 4, "startpoint": "c", "endpoint": "d", "end_edge": "^",
             "arrival": 9.6, "slack": 0.2, "loc_testable": True,
             "nr_verdict": "DET", "robust_verdict": "DET"}],
        margin_ns=1.0)
    cov = sdd.sdd_coverage_math(recs, margin_ns=1.0, period_ns=10.0)
    assert cov["graded_faults"] == 4
    assert cov["strong"] == 1
    assert cov["sdd_binary_strong_coverage_pct"] == 25.0
    # tightest is now the strong slack-0.2 path
    assert cov["tightest_path"]["sdd_bucket"] == "strong"


def test_coverage_math_empty():
    cov = sdd.sdd_coverage_math([], margin_ns=1.0, period_ns=10.0)
    assert cov["graded_faults"] == 0
    assert cov["sdd_slack_weighted_coverage_pct"] is None
    assert cov["tightest_path"] is None


# ── design-wide SOUND lower bound + population summary ───────────────────────

def test_design_bound_no_path_within_margin():
    recs = sdd.grade_path_records(_dt2_records(), margin_ns=1.0)
    b = sdd.design_small_delay_bound(recs, margin_ns=1.0)
    assert b["min_sensitizable_slack_ns"] == 9.117
    assert b["any_sensitizable_path_within_margin"] is False


def test_design_bound_with_tight_path():
    recs = sdd.grade_path_records(
        [{"idx": 0, "startpoint": "a", "endpoint": "b", "end_edge": "^",
          "arrival": 9.5, "slack": 0.3, "loc_testable": True,
          "nr_verdict": "DET", "robust_verdict": "DET"}], margin_ns=1.0)
    b = sdd.design_small_delay_bound(recs, margin_ns=1.0)
    assert b["min_sensitizable_slack_ns"] == 0.3
    assert b["any_sensitizable_path_within_margin"] is True


def test_population_summary():
    faults = [{"verdict": "DET"}, {"verdict": "DET"}, {"verdict": "RED"},
              {"verdict": "ABORT"}]
    p = sdd.transition_population_summary(faults)
    assert p == {"total": 4, "logic_detected": 2, "redundant": 1, "aborted": 1}


# ══════════════════════════════════════════════════════════════════════════
# GATE — false-clean-proof recount
# ══════════════════════════════════════════════════════════════════════════

def _good_blob():
    """A self-consistent spm-shape blob (all weak; low honest coverage)."""
    recs = sdd.grade_path_records(_dt2_records(), margin_ns=1.0)
    cov = sdd.sdd_coverage_math(recs, margin_ns=1.0, period_ns=10.0)
    return {
        "verdict": "PASS", "clock_period_ns": 10.0, "margin_fraction": 0.10,
        "margin_fraction_cap": 1.0, "margin_ns": 1.0,
        "margin_ns_derivation": "margin_fraction × clock_period",
        "sdd_records": recs, **cov}


def test_gate_passes_consistent_low_coverage():
    # descriptive: a slack-rich design's low coverage is a PASS
    res = gate.evaluate(_good_blob())
    assert res["verdict"] == "PASS"
    assert res["strong"] == 0 and res["weak"] == 2
    assert res["sdd_binary_strong_coverage_pct"] == 0.0


def test_gate_fails_strong_with_high_slack():
    # FALSE-CLEAN: flip idx0 (slack 9.117 >> margin 1.0) to 'strong' by hand
    blob = _good_blob()
    blob["sdd_records"][0]["sdd_bucket"] = "strong"
    blob["strong"] = 1
    blob["sdd_binary_strong_coverage_pct"] = 33.3333
    res = gate.evaluate(blob)
    assert res["verdict"] == "FAIL"
    assert res["strong_high_slack_violations"] >= 1
    assert any("high-slack" in r or "false-clean" in r for r in res["reasons"])


def test_gate_fails_fabricated_sensitization():
    # a RED (non-sensitizable) path flagged sensitizable=True is fabrication
    blob = _good_blob()
    blob["sdd_records"][2]["sensitizable"] = True   # idx2 nr_verdict == RED
    res = gate.evaluate(blob)
    assert res["verdict"] == "FAIL"
    assert res["sensitize_fabrications"] >= 1


def test_gate_fails_inflated_weighted_coverage():
    blob = _good_blob()
    blob["sdd_slack_weighted_coverage_pct"] = 95.0   # wildly inflated
    res = gate.evaluate(blob)
    assert res["verdict"] == "FAIL"
    assert any("exceeds the recount" in r for r in res["reasons"])


def test_gate_catches_doctored_margin_ns():
    # doctor margin_ns to 20 (so 9.117 slack looks 'strong') WITHOUT changing
    # the disclosed fraction 0.10 → gate re-derives 1.0 and re-buckets as weak
    blob = _good_blob()
    blob["margin_ns"] = 20.0
    blob["sdd_records"][0]["sdd_bucket"] = "strong"
    blob["sdd_records"][1]["sdd_bucket"] = "strong"
    blob["strong"] = 2
    res = gate.evaluate(blob)
    assert res["verdict"] == "FAIL"
    # re-derived margin governs (period 10 × fraction 0.10 = 1.0), still weak
    assert res["margin_ns"] == 1.0
    assert res["strong"] == 0
    assert any("doctored" in r for r in res["reasons"])


def test_gate_margin_fraction_cap():
    blob = _good_blob()
    blob["margin_fraction"] = 2.0   # exceeds cap 1.0
    res = gate.evaluate(blob)
    assert any("cap" in r for r in res["reasons"])


def test_gate_not_applicable_passthrough():
    res = gate.evaluate({"verdict": "NOT_APPLICABLE", "scan_flops": 0,
                         "reasons": ["DT2 N/A"]})
    assert res["verdict"] == "NOT_APPLICABLE"


def test_gate_error_is_fail():
    res = gate.evaluate({"verdict": "ERROR", "reasons": ["boom"]})
    assert res["verdict"] == "FAIL"


def test_gate_zero_evidence_fail():
    assert gate.evaluate(None)["verdict"] == "FAIL"
    assert gate.evaluate({"verdict": "PASS", "sdd_records": []})["verdict"] == "FAIL"


def test_gate_optional_min_bar_off_by_default():
    # min_slack_weighted defaults 0 (OFF); low coverage still PASSes
    assert gate.evaluate(_good_blob())["verdict"] == "PASS"
    # but an explicit caller bar can FAIL a slack-rich design
    res = gate.evaluate(_good_blob(), min_slack_weighted=50.0)
    assert res["verdict"] == "FAIL"
    assert any("at-speed bar" in r for r in res["reasons"])


def test_gate_explicit_margin_ns_honoured():
    # explicit --margin-ns path: derivation flag set → written margin used as-is
    blob = _good_blob()
    blob["margin_ns"] = 1.0
    blob["margin_ns_derivation"] = "explicit --margin-ns"
    res = gate.evaluate(blob)
    assert res["verdict"] == "PASS"
    assert res["margin_ns"] == 1.0
