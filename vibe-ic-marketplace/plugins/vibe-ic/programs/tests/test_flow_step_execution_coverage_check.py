"""Tests for flow_step_execution_coverage_check.analyze (synthetic data only)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow_step_execution_coverage_check as cov  # noqa: E402


def _report(*steps):
    return {"steps": list(steps)}


def _s(sid, name, status, stage="stage3"):
    return {"id": sid, "name": name, "status": status, "stage": stage}


# A tiny synthetic flow graph: terminal GDS (37) depends on PV (31); PV depends
# on nothing here. Mirrors the real blocks_on shape without any vendor data.
GRAPH = {"37": ["31"], "31": ["30"], "30": []}


def test_ordering_violation_terminal_before_signoff():
    # GDS marked done while the PV step it blocks_on is MISSING → FAIL.
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "PASS"),
        _s(31, "Physical Verification (DRC + LVS + ERC + Density)", "MISSING"),
        _s(37, "GDSII output (only if Step 31 PV fully clean)", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "FAIL"
    assert res["counts"]["ordering_violations"] >= 1
    pair = res["ordering_violations"][0]
    assert str(pair["terminal_id"]) == "37" and str(pair["signoff_id"]) == "31"


def test_clean_flow_all_pass():
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "PASS"),
        _s(31, "Physical Verification (DRC + LVS + ERC + Density)", "PASS"),
        _s(37, "GDSII output (only if Step 31 PV fully clean)", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "PASS"
    assert res["counts"]["ordering_violations"] == 0
    assert res["counts"]["applicable_missing"] == 0


def test_na_signoff_does_not_block_terminal():
    # A legitimately SKIPPED-CONDITION predecessor must NOT flag the terminal.
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "PASS"),
        _s(31, "Physical Verification (DRC + LVS + ERC + Density)",
           "SKIPPED-CONDITION"),
        _s(37, "GDSII output (only if Step 31 PV fully clean)", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "PASS"


def test_applicable_missing_is_a_skip():
    # An applicable step that never produced output → no-skip violation.
    r = _report(
        _s(2, "Lint (RTL + Quartus-unsafe patterns)", "MISSING", stage="stage1"),
        _s(37, "GDSII output", "MISSING"),
    )
    res = cov.analyze(r, {})
    assert res["verdict"] == "FAIL"
    ids = {str(s["id"]) for s in res["applicable_missing"]}
    assert "2" in ids


def test_name_based_fallback_when_no_blocks_on_edges():
    # Terminal ships EMPTY blocks_on (the real GDSII/handoff data bug): the
    # name-based fallback must still guard it against an unfinished sign-off step.
    r = _report(
        _s(31, "Physical Verification (DRC + LVS + ERC)", "MISSING"),
        _s(38, "Foundry Handoff (mask spec + WAT plan)", "PASS"),
    )
    res = cov.analyze(r, {})  # empty graph → fallback path
    assert res["verdict"] == "FAIL"
    assert res["counts"]["ordering_violations"] >= 1


def test_vacuous_pass_SIGNOFF_ancestor_still_blocks():
    # A VACUOUS-PASS SIGN-OFF predecessor (SPICE verification verified nothing)
    # is dangerous → must still block a downstream done-claim.
    r = _report(
        _s(30, "Post-Layout SPICE Verification", "VACUOUS-PASS"),
        _s(31, "Physical Verification", "PASS"),
        _s(37, "GDSII output", "PASS"),
    )
    res = cov.analyze(r, GRAPH)
    assert res["verdict"] == "FAIL"


def test_vacuous_pass_NONsignoff_ancestor_is_acceptable():
    # A VACUOUS-PASS NON-sign-off PROCESS step (synth handoff had no tie-cells /
    # no yosys-template to check) RAN and did not fail — it must NOT flag the
    # downstream steps that depend on it. (The exact spm step-14 false positive.)
    graph = {"16": ["14"], "15": ["14"], "14": []}
    r = _report(
        _s(14, "Synthesis handoff gate (pre-PnR yosys script + netlist audit)",
           "VACUOUS-PASS", stage="stage2"),
        _s(15, "Floorplan + PDN", "PASS"),
        _s(16, "Clock planning", "PASS"),
    )
    res = cov.analyze(r, graph)
    assert res["verdict"] == "PASS"
    assert res["counts"]["ordering_violations"] == 0
