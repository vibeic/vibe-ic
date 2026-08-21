#!/usr/bin/env python3
"""Smoke tests for l13_bringup_contract_check, WITH NEGATIVE CONTROL.

Every rule is asserted in BOTH directions: a deliberately-gutted L13
missing the required content must FAIL, and a well-formed one must PASS.
A test that cannot fail proves nothing.

All fixtures are SYNTHESISED neutral data. Nothing here is copied from a
real design, and no design name, PDK name, vendor part number or pin
literal appears — the well-formed fixture's criterion and parameter keys
are DERIVED at test time from the consumer's own registry, exactly as the
gate derives them.
"""
from __future__ import annotations

import importlib
import json

import pytest

mod = importlib.import_module("l13_bringup_contract_check")


# --------------------------------------------------------------------------
# Fixture builders — synthesised, neutral
# --------------------------------------------------------------------------
def _criterion_and_params():
    """Pick any criterion the CONSUMER can dispatch and pin every knob its
    validator reads. Derived, never hardcoded."""
    crits = mod.consumer_criteria()
    assert crits, "consumer exposes no criteria — gate would be vacuous"
    crit = crits[0]
    params = {k: 1 for k in mod.consumer_required_params(crit)}
    return crit, params


def well_formed_in_scope():
    crit, params = _criterion_and_params()
    return {
        "doc_class": "lab_calibration",
        "lab_calibration_present": True,
        "calibration_targets": [
            {"name": "reference level", "spec": "within declared window"}],
        "lab_equipment": ["bench instrument A"],
        "criterion": crit,
        "criterion_params": params,
        "tester": "bench-rig-01",
        "calibration_steps": [
            {"step": 1, "action": "apply the declared stimulus",
             "expected": "output settles inside the declared window"},
        ],
        "trim_loop": [],
    }


def well_formed_out_of_scope():
    """A part with no lab work at all: no contract required, and the doc
    says so cleanly instead of emitting phantom steps."""
    return {
        "doc_class": "lab_calibration",
        "lab_calibration_present": False,
        "no_lab_calibration_in_input": True,
        "calibration_targets": [],
        "lab_equipment": [],
        "rig_pin_assignments": {},
        "calibration_steps": [],
        "trim_loop": [],
        "notes": "purely digital block; no trim or calibration loop",
    }


def _sev(res, sev):
    return [f for f in res["findings"] if f["severity"] == sev]


def _rules(res, sev=None):
    return {f["rule"] for f in res["findings"]
            if sev is None or f["severity"] == sev}


# --------------------------------------------------------------------------
# POSITIVE controls — a well-formed layer must PASS
# --------------------------------------------------------------------------
def test_well_formed_in_scope_passes():
    res = mod.check(well_formed_in_scope(), phase=1)
    assert res["hardware_in_scope"] is True
    assert _sev(res, "FAIL") == [], res["findings"]
    assert _sev(res, "WARN") == [], res["findings"]


def test_well_formed_out_of_scope_passes():
    res = mod.check(well_formed_out_of_scope(), phase=1)
    assert res["hardware_in_scope"] is False
    assert res["findings"] == [], res["findings"]


# --------------------------------------------------------------------------
# NEGATIVE controls — each gutted layer must FAIL, on the right rule
# --------------------------------------------------------------------------
def test_gutted_missing_criterion_fails():
    """THE motivating defect: hardware work is declared in scope but the
    CONTRACT half is empty, so hardware_pass_attestation_check has nothing
    to dispatch and the hardware claim is silently unattestable."""
    d = well_formed_in_scope()
    d.pop("criterion")
    d.pop("criterion_params")
    res = mod.check(d, phase=1)
    assert "l13_contract_complete" in _rules(res, "FAIL"), res["findings"]


def test_gutted_missing_tester_fails():
    d = well_formed_in_scope()
    d["tester"] = ""
    res = mod.check(d, phase=1)
    assert "l13_contract_complete" in _rules(res, "FAIL"), res["findings"]


def test_gutted_unpinned_criterion_params_fails_only_when_consumer_reads_knobs():
    crit, params = _criterion_and_params()
    d = well_formed_in_scope()
    d["criterion_params"] = {}
    res = mod.check(d, phase=1)
    if params:
        assert "l13_contract_complete" in _rules(res, "FAIL"), res["findings"]
    else:                                  # pragma: no cover - defensive
        pytest.skip(f"consumer criterion {crit} reads no params")


def test_criterion_unknown_to_consumer_fails():
    d = well_formed_in_scope()
    d["criterion"] = "a_criterion_the_consumer_cannot_dispatch"
    res = mod.check(d, phase=1)
    assert "l13_criterion_known_to_consumer" in _rules(res, "FAIL"), \
        res["findings"]


def test_phase1_evidence_half_must_be_empty():
    """EVIDENCE is Phase-2 property. Populated at Phase 1 it is a hardware
    claim with no hardware behind it."""
    d = well_formed_in_scope()
    d["known_pass_transcript"] = {"rx_bytes": "AA BB CC DD"}
    d["known_pass_bitstream"] = {"sha256": "0" * 64}
    res = mod.check(d, phase=1)
    assert "l13_phase1_evidence_must_be_empty" in _rules(res, "FAIL"), \
        res["findings"]
    # ...and the SAME document is legitimate at Phase 2 — the rule is a
    # phase rule, not a blanket ban.
    res2 = mod.check(d, phase=2)
    assert "l13_phase1_evidence_must_be_empty" not in _rules(res2, "FAIL")


def test_partial_contract_pulls_the_doc_into_scope():
    """Half a contract is still a contract: declaring a tester with no
    criterion must not escape by claiming hardware is out of scope."""
    d = well_formed_out_of_scope()
    d["tester"] = "bench-rig-01"
    res = mod.check(d, phase=1)
    assert res["hardware_in_scope"] is True
    assert "l13_contract_complete" in _rules(res, "FAIL"), res["findings"]


def test_unparseable_layer_fails():
    res = mod.check(None, phase=1)
    assert "l13_parseable" in _rules(res, "FAIL")


# --------------------------------------------------------------------------
# Advisory tier — must fire, and must NOT block unless --strict
# --------------------------------------------------------------------------
def test_step_without_expected_is_flagged_as_vacuous_plan_line():
    d = well_formed_in_scope()
    d["calibration_steps"] = [{"step": 1, "action": "apply the stimulus"}]
    res = mod.check(d, phase=1)
    assert "l13_bringup_step_not_actionable" in _rules(res, "WARN"), \
        res["findings"]
    assert _sev(res, "FAIL") == []


def test_document_scaffolding_step_is_flagged():
    d = well_formed_in_scope()
    d["calibration_steps"] = [
        {"step": 1, "action": "# A Heading Lifted From An Input Doc",
         "expected": "n/a"}]
    res = mod.check(d, phase=1)
    assert "l13_bringup_step_not_actionable" in _rules(res, "WARN"), \
        res["findings"]


def test_steps_without_any_declared_hardware_content_is_flagged():
    """bringup_plan_gen would emit an N-step plan for a bring-up the same
    document says does not exist."""
    d = well_formed_out_of_scope()
    d["calibration_steps"] = [
        {"step": 1, "action": "# Section heading"},
        {"step": 2, "action": "- no trimming"},
    ]
    res = mod.check(d, phase=1)
    assert "l13_steps_contradict_declared_absence" in _rules(res, "WARN"), \
        res["findings"]
    assert _sev(res, "FAIL") == []


# --------------------------------------------------------------------------
# CLI: blocking semantics, both directions
# --------------------------------------------------------------------------
def _project(tmp_path, doc, name="p"):
    gd = tmp_path / name / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L13_LAB_CALIBRATION.json").write_text(json.dumps(doc))
    return tmp_path / name


def test_cli_blocks_on_fail_and_passes_on_well_formed(tmp_path):
    good = _project(tmp_path, well_formed_in_scope(), "good")
    assert mod.main([str(good)]) == 0

    gutted = dict(well_formed_in_scope())
    gutted.pop("criterion")
    bad = _project(tmp_path, gutted, "bad")
    assert mod.main([str(bad)]) == 1        # BLOCKS


def test_cli_advisory_tier_does_not_block_without_strict(tmp_path):
    d = well_formed_out_of_scope()
    d["calibration_steps"] = [{"step": 1, "action": "# heading"}]
    proj = _project(tmp_path, d, "advisory")
    assert mod.main([str(proj)]) == 0
    assert mod.main([str(proj), "--strict"]) == 1


def test_cli_skips_when_layer_absent(tmp_path):
    (tmp_path / "empty").mkdir()
    assert mod.main([str(tmp_path / "empty")]) == 2


# --------------------------------------------------------------------------
# The derivation itself must be live, not a copied list
# --------------------------------------------------------------------------
def test_criteria_are_read_out_of_the_consumer_not_hardcoded():
    import hardware_pass_attestation_check as hpa
    assert mod.consumer_criteria() == sorted(hpa._CRITERIA)
    for crit in mod.consumer_criteria():
        keys = mod.consumer_required_params(crit)
        assert isinstance(keys, list)
    # At least one consumer criterion carries a tunable threshold; if none
    # did, the "pin your own thresholds" rule would be dead code.
    assert any(mod.consumer_required_params(c)
               for c in mod.consumer_criteria())
