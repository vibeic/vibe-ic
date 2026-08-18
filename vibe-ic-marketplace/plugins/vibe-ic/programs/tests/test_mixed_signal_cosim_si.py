#!/usr/bin/env python3
"""Substance-verification tests for the M3-cosim-si gate.

Covers both checkers that compose the gate:
  * mixed_signal_cosim_check.py        (AMS co-sim scenario substance)
  * mixed_signal_interface_si_check.py (interface SI metric-vs-limit)

For each: a PASS fixture (substance good), a FAIL fixture (the exact
silicon/anti-fab failure the gate guards), and the missing-data
behaviour (honest FAIL when analog applies / SKIP when inapplicable).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parent.parent
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import mixed_signal_cosim_check as cosim          # noqa: E402
import mixed_signal_interface_si_check as si      # noqa: E402


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------
def _write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))


def _declare_analog(proj: Path, blocks=("ldo_1v8",)):
    _write(proj / "phase1/analog/analog_block_list.json",
           {"blocks": [{"name": b} for b in blocks]})


def _agg_path(proj: Path) -> Path:
    return proj / "phase3/mixed_signal/cosim/mixed_signal_results.json"


def _si_path(proj: Path) -> Path:
    return proj / "reports/analog/mixed_signal/interface_si.json"


# ===========================================================================
# mixed_signal_cosim_check
# ===========================================================================
def test_cosim_pass_real_scenarios(tmp_path):
    """PASS: aggregate report has real per-scenario PASS verdicts."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_agg_path(proj), {
        # NOTE: deliberately set the self-claimed boolean to a wrong
        # value to prove the checker does NOT echo it.
        "all_scenarios_passed": False,
        "scenarios": [
            {"name": "startup_sequence", "status": "PASS"},
            {"name": "trim_sweep", "status": "passed"},
            {"name": "enable_toggle", "passed": True},
        ],
    })
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["aggregate"]["scenarios_total"] == 3
    assert rep["summary"]["aggregate"]["scenarios_passed"] == 3


def test_cosim_fail_one_scenario_failed(tmp_path):
    """FAIL: one scenario is genuinely failed even though the producer
    asserted all_scenarios_passed=true (the anti-fab hole)."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_agg_path(proj), {
        "all_scenarios_passed": True,   # producer lies
        "scenarios": [
            {"name": "startup_sequence", "status": "PASS"},
            {"name": "trim_sweep", "status": "FAIL"},
        ],
    })
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["passed"] is False
    rules = {f["rule"] for f in rep["findings"]}
    assert "SCENARIO_FAILED" in rules


def test_cosim_fail_zero_scenarios_vacuous(tmp_path):
    """FAIL: aggregate report present but declares zero scenarios — a
    vacuous 'all passed' with nothing simulated."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_agg_path(proj), {"all_scenarios_passed": True, "scenarios": []})
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "AGG_ZERO_SCENARIOS" in rules


def test_cosim_fail_scenario_no_verdict(tmp_path):
    """FAIL: a scenario carries no readable PASS/FAIL verdict."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_agg_path(proj), {
        "scenarios": [
            {"name": "startup_sequence", "status": "PASS"},
            {"name": "mystery", "details": "ran something"},
        ],
    })
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "SCENARIO_NO_VERDICT" in rules


def test_cosim_fail_missing_when_analog_applies(tmp_path):
    """FAIL (not vacuous-PASS): analog declared but NO cosim substance
    anywhere — no aggregate file, no per-block file, no stub."""
    proj = tmp_path
    _declare_analog(proj, blocks=("ldo_1v8", "bandgap"))
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["passed"] is False
    rules = {f["rule"] for f in rep["findings"]}
    # either per-block-missing or the explicit no-substance guard fires
    assert ("COSIM_MISSING" in rules) or ("COSIM_NO_SUBSTANCE" in rules)


def test_cosim_skip_no_analog(tmp_path):
    """SKIP (rc=2): genuinely inapplicable — no analog blocks declared."""
    proj = tmp_path
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 2
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["skip"] is True


def test_cosim_pass_per_block_file(tmp_path):
    """PASS: per-block cosim file present and simulation_passed=true,
    no aggregate file required."""
    proj = tmp_path
    _declare_analog(proj, blocks=("ldo_1v8",))
    _write(proj / "phase3/mixed_signal/cosim/ldo_1v8_cosim_results.json",
           {"block_name": "ldo_1v8", "simulation_passed": True,
            "tests": [{"name": "startup", "status": "PASS"}]})
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 0


def test_cosim_fail_per_block_failed(tmp_path):
    """FAIL: per-block cosim explicitly failed."""
    proj = tmp_path
    _declare_analog(proj, blocks=("ldo_1v8",))
    _write(proj / "phase3/mixed_signal/cosim/ldo_1v8_cosim_results.json",
           {"block_name": "ldo_1v8", "simulation_passed": False,
            "failure_reason": "vout never reached target"})
    rc = cosim.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1


# ===========================================================================
# mixed_signal_interface_si_check
# ===========================================================================
def test_si_pass_metrics_within_stated_limits(tmp_path):
    """PASS: every interface metric within the limit STATED in the
    artefact (the checker recomputes; does not trust the boolean)."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_si_path(proj), {
        "all_interfaces_clean": False,   # producer's boolean ignored
        "interfaces": [
            {"name": "ldo_en_d2a",
             "metrics": {
                 "overshoot_pct": {"measured": 4.2, "max": 10.0},
                 "slew_ns": {"measured": 1.1, "max": 2.0},
                 "setup_margin_ns": {"measured": 0.8, "min": 0.2},
             }},
            {"name": "adc_done_a2d",
             "metrics": [
                 {"name": "jitter_ps", "measured": 12.0, "limit": 25.0,
                  "relation": "max"},
             ]},
        ],
    })
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["interfaces_total"] == 2
    assert rep["summary"]["metrics_checked"] == 4


def test_si_fail_metric_out_of_limit(tmp_path):
    """FAIL: a metric exceeds its stated limit (real SI violation) even
    though the producer claimed all_interfaces_clean=true."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_si_path(proj), {
        "all_interfaces_clean": True,   # producer lies
        "interfaces": [
            {"name": "ldo_en_d2a",
             "metrics": {
                 "overshoot_pct": {"measured": 18.5, "max": 10.0},
             }},
        ],
    })
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "SI_METRIC_OUT_OF_LIMIT" in rules


def test_si_fail_unstated_limit(tmp_path):
    """FAIL: a metric has a measured value but NO stated limit — the
    checker refuses to fabricate a threshold."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_si_path(proj), {
        "interfaces": [
            {"name": "ldo_en_d2a",
             "metrics": {"overshoot_pct": {"measured": 4.2}}},
        ],
    })
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "SI_LIMIT_UNSTATED" in rules


def test_si_fail_self_verdict_disagree(tmp_path):
    """FAIL: producer self-verdict says pass but the recomputed bound
    says fail — the producer lied about its own data."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_si_path(proj), {
        "interfaces": [
            {"name": "ldo_en_d2a",
             "metrics": {
                 "overshoot_pct": {"measured": 18.0, "max": 10.0,
                                   "pass": True},
             }},
        ],
    })
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "SI_SELF_VERDICT_DISAGREE" in rules


def test_si_fail_zero_interfaces_vacuous(tmp_path):
    """FAIL: present file declares zero interfaces — vacuous all-clean."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_si_path(proj), {"all_interfaces_clean": True, "interfaces": []})
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "SI_ZERO_INTERFACES" in rules


def test_si_fail_missing_when_analog_applies(tmp_path):
    """FAIL (not vacuous-PASS): analog declared but interface_si.json
    absent and no waiver."""
    proj = tmp_path
    _declare_analog(proj)
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["verdict"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "SI_REPORT_MISSING" in rules


def test_si_skip_no_analog(tmp_path):
    """SKIP (rc=2): no analog blocks, no artefact — inapplicable."""
    proj = tmp_path
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 2
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["verdict"] == "SKIP"


def test_si_waived_when_ticketed(tmp_path):
    """WAIVED (rc=0): missing artefact but a waiver entry exists."""
    proj = tmp_path
    _declare_analog(proj)
    _write(proj / "waivers.json", {"waived_steps": [
        {"id": "mixed_signal_interface_si", "ticket": "JIRA-123",
         "reason": "SI tool unavailable this run"}]})
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["verdict"] == "WAIVED"


def test_si_pass_lower_bound_metric(tmp_path):
    """PASS: a min-bound metric (eye height) satisfied."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_si_path(proj), {
        "interfaces": [
            {"name": "serdes_rx",
             "metrics": {"eye_height_mv": {"measured": 120.0, "min": 80.0}}},
        ],
    })
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 0


def test_si_fail_lower_bound_violated(tmp_path):
    """FAIL: a min-bound metric (eye height) below the stated floor."""
    proj = tmp_path
    _declare_analog(proj)
    _write(_si_path(proj), {
        "interfaces": [
            {"name": "serdes_rx",
             "metrics": {"eye_height_mv": {"measured": 50.0, "min": 80.0}}},
        ],
    })
    rc = si.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
