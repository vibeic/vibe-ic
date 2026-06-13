#!/usr/bin/env python3
"""
test_final_test_attestation_check.py — substance-verification tests for
the Step 41 final-test gate.

Covers:
  * PASS fixture     — measured yield >= stated target, good die > 0,
                       clean burn-in, shippable=true consistent.
  * FAIL fixtures    — the real silicon / anti-fabrication escapes:
                         - yield below stated target but shippable=true
                         - burn-in failures present but shippable=true
                         - zero good die
                         - shippable=true with NO target stated
                           (refuse to fabricate a threshold)
                         - good/total count contradicts reported yield
  * Missing-data     — no artefact + no waiver  => SKIP (rc=2)
                       no artefact + waiver      => WAIVED (rc=0)
                       missing measured yield    => honest FAIL (rc=1)
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import final_test_attestation_check as ftac  # noqa: E402


_YIELD_REL = "phase3/stage5_manufacturing/final_test_yield.json"
_BURNIN_REL = "phase3/stage5_manufacturing/burn_in_results.json"


def _write_yield(project: Path, obj: dict):
    p = project / _YIELD_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))
    return p


def _write_burnin(project: Path, obj: dict):
    p = project / _BURNIN_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))
    return p


def _run(project: Path):
    rc = ftac.main([str(project), "--json", str(project / "report.json")])
    report = json.loads((project / "report.json").read_text())
    return rc, report


# ── PASS ────────────────────────────────────────────────────────────
def test_pass_substance_good(tmp_path):
    _write_yield(tmp_path, {
        "measured_yield": 97.3,
        "target_yield": 95.0,
        "good_die": 9730,
        "total_die": 10000,
        "fail_count": 270,
        "shippable": True,
    })
    rc, report = _run(tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "PASS"
    rules = {f["rule"] for f in report["findings"]}
    assert "YIELD_MEETS_TARGET" in rules
    assert "SHIP_JUSTIFIED" in rules


def test_pass_fraction_representation_and_clean_burnin(tmp_path):
    # yield expressed as a fraction (0.99) rather than percent
    _write_yield(tmp_path, {
        "final_test_yield": 0.99,
        "yield_floor": 0.92,
        "passed": 990,
        "tested": 1000,
        "shippable": True,
    })
    _write_burnin(tmp_path, {"failures": 0, "tested": 200})
    rc, report = _run(tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "PASS"
    rules = {f["rule"] for f in report["findings"]}
    assert "BURNIN_CLEAN" in rules


def test_pass_without_shippable_flag(tmp_path):
    # No shippable flag at all: PASS must come purely from the numbers,
    # never from echoing a self-asserted boolean.
    _write_yield(tmp_path, {
        "measured_yield": 96.0,
        "target_yield": 95.0,
        "good_die": 9600,
        "total_die": 10000,
    })
    rc, report = _run(tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "PASS"


# ── FAIL: the silicon / anti-fabrication escapes ────────────────────
def test_fail_yield_below_target_but_shippable_true(tmp_path):
    # Producing step LIES: yield under floor but shippable=true.
    _write_yield(tmp_path, {
        "measured_yield": 88.0,
        "target_yield": 95.0,
        "good_die": 8800,
        "total_die": 10000,
        "shippable": True,
    })
    rc, report = _run(tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    rules = {f["rule"] for f in report["findings"]}
    assert "YIELD_BELOW_TARGET" in rules
    assert "SHIPPABLE_CONTRADICTS_DATA" in rules


def test_fail_burnin_failures_but_shippable_true(tmp_path):
    # Graded-part burn-in has failures yet flagged shippable.
    _write_yield(tmp_path, {
        "measured_yield": 99.0,
        "target_yield": 95.0,
        "good_die": 9900,
        "total_die": 10000,
        "shippable": True,
    })
    _write_burnin(tmp_path, {"failures": 3, "tested": 500})
    rc, report = _run(tmp_path)
    assert rc == 1, report
    assert report["verdict"] == "FAIL"
    rules = {f["rule"] for f in report["findings"]}
    assert "BURNIN_FAILURES" in rules


def test_fail_zero_good_die(tmp_path):
    _write_yield(tmp_path, {
        "measured_yield": 95.5,
        "target_yield": 95.0,
        "good_die": 0,
        "total_die": 10000,
        "shippable": True,
    })
    rc, report = _run(tmp_path)
    assert rc == 1, report
    rules = {f["rule"] for f in report["findings"]}
    assert "ZERO_GOOD_DIE" in rules


def test_fail_no_target_refuse_to_fabricate(tmp_path):
    # Measured yield present, shippable=true, but NO stated target.
    # The checker must refuse to invent a threshold -> FAIL.
    _write_yield(tmp_path, {
        "measured_yield": 99.9,
        "good_die": 9990,
        "total_die": 10000,
        "shippable": True,
    })
    rc, report = _run(tmp_path)
    assert rc == 1, report
    rules = {f["rule"] for f in report["findings"]}
    assert "TARGET_YIELD_MISSING" in rules


def test_fail_count_contradicts_yield(tmp_path):
    # Reported yield 99% but good/total = 50% — internally inconsistent.
    _write_yield(tmp_path, {
        "measured_yield": 99.0,
        "target_yield": 95.0,
        "good_die": 5000,
        "total_die": 10000,
        "shippable": True,
    })
    rc, report = _run(tmp_path)
    assert rc == 1, report
    rules = {f["rule"] for f in report["findings"]}
    assert "YIELD_COUNT_INCONSISTENT" in rules


def test_fail_burnin_present_but_no_failure_count(tmp_path):
    _write_yield(tmp_path, {
        "measured_yield": 99.0, "target_yield": 95.0,
        "good_die": 9900, "total_die": 10000, "shippable": True,
    })
    _write_burnin(tmp_path, {"tested": 500})  # no failure-count field
    rc, report = _run(tmp_path)
    assert rc == 1, report
    rules = {f["rule"] for f in report["findings"]}
    assert "BURNIN_FAIL_COUNT_MISSING" in rules


def test_fail_producer_hold_respected(tmp_path):
    # Numbers fine but producer explicitly held shippable=false.
    _write_yield(tmp_path, {
        "measured_yield": 99.0, "target_yield": 95.0,
        "good_die": 9900, "total_die": 10000, "shippable": False,
    })
    rc, report = _run(tmp_path)
    assert rc == 1, report
    rules = {f["rule"] for f in report["findings"]}
    assert "PRODUCER_NOT_SHIPPABLE" in rules


# ── Missing-data behaviour ──────────────────────────────────────────
def test_missing_artefact_no_waiver_is_skip(tmp_path):
    rc, report = _run(tmp_path)
    assert rc == 2, report
    assert report["verdict"] == "SKIP"


def test_missing_artefact_with_waiver_is_waived(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "final_test_attestation",
            "ticket": "WAIVE-final_test_attestation-001",
            "reason": "engineering sample, no production final test",
            "evidence": "eng-sample-build.log",
        }]
    }))
    rc, report = _run(tmp_path)
    assert rc == 0, report
    assert report["verdict"] == "WAIVED"


def test_missing_measured_yield_is_honest_fail(tmp_path):
    # Artefact present but carries no measured yield => cannot justify
    # ship from absence => honest FAIL, never a vacuous PASS.
    _write_yield(tmp_path, {"target_yield": 95.0, "shippable": True})
    rc, report = _run(tmp_path)
    assert rc == 1, report
    rules = {f["rule"] for f in report["findings"]}
    assert "MEASURED_YIELD_MISSING" in rules


def test_corrupt_yield_json_is_fail(tmp_path):
    p = tmp_path / _YIELD_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not valid json")
    rc, report = _run(tmp_path)
    assert rc == 1, report
    rules = {f["rule"] for f in report["findings"]}
    assert "YIELD_PARSE_ERROR" in rules


def test_does_not_just_echo_shippable_flag(tmp_path):
    # Hard anti-fabrication assertion: shippable=true with garbage
    # numbers MUST NOT pass. (Mirrors the stub-bypass this gate fixes.)
    _write_yield(tmp_path, {
        "measured_yield": 10.0, "target_yield": 95.0,
        "good_die": 0, "shippable": True,
    })
    rc, _ = _run(tmp_path)
    assert rc == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
