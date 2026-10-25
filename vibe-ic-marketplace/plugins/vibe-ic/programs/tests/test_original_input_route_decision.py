"""Finite source-authority controls for the existing typed route receipt."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import route_decision as rd  # noqa: E402
import step_required_inputs_check as sri  # noqa: E402
import task_nature_route as tnr  # noqa: E402


PROMPT = "Implement a combinational module whose output is the XOR of its two inputs.\n"


def _receipt(*, nature="spec_generation", evidence="lint_validated", target="rtl",
             prompt=PROMPT, context=None):
    return tnr.route_decision_receipt(
        prompt, nature=nature, requested_evidence=evidence,
        delivery_target=target, context=context)


def _rehash(receipt):
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = rd.sha256_json(body)
    return receipt


def test_canonical_dag_projects_the_shared_yaml_input_resolver(monkeypatch):
    calls = []
    resolve = sri.input_contract

    def recording_resolver(row, kind="structured"):
        calls.append((str(row["id"]), kind))
        return resolve(row, kind)

    monkeypatch.setattr(sri, "input_contract", recording_resolver)
    structured = rd.canonical_dag()
    original = rd.canonical_dag(input_contract="original")
    assert ("1", "original") in calls and ("2", "original") in calls
    assert structured == rd.canonical_dag(input_contract="structured")
    assert "D1" in structured["blocks_on"]["1"]
    assert "D1" in structured["blocks_on"]["2"]
    assert original["blocks_on"]["1"] == []
    assert original["blocks_on"]["2"] == ["1"]
    assert original["required_inputs_from"]["1"] == []
    assert original["required_inputs_from"]["2"] == ["1"]
    assert original["sha256"] != structured["sha256"]


@pytest.mark.parametrize(("evidence", "terminal", "closed"), [
    ("existence", "1", ["1"]),
    ("lint_validated", "2", ["1", "2"]),
])
def test_original_spec_generation_preserves_semantics_and_exact_input(evidence, terminal, closed):
    receipt = _receipt(evidence=evidence)
    payload = tnr.semantic_routing_payload(
        PROMPT, requested_evidence=evidence, delivery_target="rtl")
    assert payload["prompt"] == PROMPT
    assert receipt["task_nature"] == "spec_generation"
    assert receipt["delivery_target"] == "rtl"
    assert receipt["source_sha256"] == rd.sha256_text(PROMPT)
    assert receipt["semantic_payload_sha256"] == payload["semantic_payload_sha256"]
    assert receipt["input_contract"] == "original"
    assert receipt["entry_step"] == "1"
    assert receipt["answer_step"] == "1"
    assert receipt["verify_through"] == terminal
    assert receipt["verify_closed_steps"] == closed
    assert receipt["minimum_steps"] == ["1", terminal, "1"]
    assert receipt["dag_sha256"] == rd.canonical_dag(input_contract="original")["sha256"]
    assert rd.validate_route_receipt(receipt) == []


@pytest.mark.parametrize("target", ["gds", "shippable_gds", "ip_hardmacro", "foundry_handoff"])
def test_physical_delivery_keeps_structured_d1_and_delivery_family(target):
    receipt = _receipt(target=target)
    assert receipt["input_contract"] == "structured"
    assert receipt["entry_step"] == "D1"
    assert "D1" in receipt["verify_closed_steps"]
    assert receipt["delivery_target"] == target
    assert receipt["answer_step"] == tnr.DELIVERY_TARGETS[target]["answer_step"]
    assert receipt["dag_sha256"] == rd.canonical_dag()["sha256"]
    assert rd.validate_route_receipt(receipt) == []


@pytest.mark.parametrize("evidence", ["behaviour", "proof", "area", "timing", "power"])
def test_deeper_rtl_proof_retains_its_structured_input_requirements(evidence):
    receipt = _receipt(evidence=evidence)
    assert receipt["input_contract"] == "structured"
    assert receipt["entry_step"] == "D1"
    assert "D1" in receipt["verify_closed_steps"]
    assert rd.validate_route_receipt(receipt) == []


@pytest.mark.parametrize(("nature", "entry"), [
    ("completion", "D1"), ("functional_modification", "D1"),
    ("optimization", "2"), ("debug", "4"),
])
def test_other_task_natures_keep_their_existing_entry_and_d1_closure(nature, entry):
    receipt = _receipt(nature=nature)
    assert receipt["task_nature"] == nature
    assert receipt["input_contract"] == "structured"
    assert receipt["entry_step"] == entry
    assert "D1" in receipt["verify_closed_steps"]
    assert rd.validate_route_receipt(receipt) == []


@pytest.mark.parametrize("field,value", [
    ("input_contract", "structured"), ("entry_step", "D1"),
    ("verify_closed_steps", ["D1", "1", "2"]),
    ("dag_sha256", "0" * 64), ("derivation_rules_version", "1"),
])
def test_rehashed_original_receipt_mutation_cannot_change_trusted_derivation(field, value):
    receipt = _receipt()
    receipt[field] = value
    assert rd.validate_route_receipt(_rehash(receipt))


def test_rehashed_physical_receipt_cannot_claim_original_or_drop_d1():
    receipt = _receipt(target="ip_hardmacro")
    receipt.update(input_contract="original", entry_step="1",
                   dag_sha256=rd.canonical_dag(input_contract="original")["sha256"])
    receipt["verify_closed_steps"].remove("D1")
    errors = rd.validate_route_receipt(_rehash(receipt))
    assert "ROUTE_RECEIPT_INPUT_CONTRACT_NOT_SEMANTIC_BOUND" in errors
    assert "ROUTE_RECEIPT_ENTRY_NOT_TABLE_BOUND" in errors
    assert "ROUTE_RECEIPT_CLOSURE_NOT_DEPENDENCY_CLOSED" in errors
    assert "ROUTE_RECEIPT_DAG_MISMATCH" in errors


def test_semantic_context_cannot_supply_executable_steps_or_source_contract():
    receipt = _receipt(context={"design_context": {
        "entry_step": "D1", "verify_through": "37", "input_contract": "structured"}})
    assert receipt["entry_step"] == "1"
    assert receipt["verify_through"] == "2"
    assert receipt["input_contract"] == "original"
    assert rd.validate_route_receipt(receipt) == []


def test_prompt_byte_change_changes_both_existing_source_bindings():
    original = _receipt()
    changed = _receipt(prompt=PROMPT.replace("XOR", "AND"))
    for field in ("source_sha256", "semantic_payload_sha256", "receipt_sha256"):
        assert changed[field] != original[field]
    assert rd.validate_route_receipt(changed) == []
    assert _receipt() == original


def test_derivation_revision_changes_contract_digest_without_changing_edges(monkeypatch):
    before = rd.canonical_dag()
    monkeypatch.setattr(rd, "ROUTE_DERIVATION_RULES_VERSION", "future-rules")
    after = rd.canonical_dag()
    assert before["blocks_on"] == after["blocks_on"]
    assert before["sha256"] != after["sha256"]


def test_old_receipt_is_not_silently_reinterpreted_after_rules_change():
    receipt = copy.deepcopy(_receipt(target="gds"))
    del receipt["input_contract"]
    del receipt["derivation_rules_version"]
    errors = rd.validate_route_receipt(_rehash(receipt))
    assert "ROUTE_RECEIPT_DERIVATION_RULES_MISMATCH" in errors
    assert "ROUTE_RECEIPT_INPUT_CONTRACT_NOT_SEMANTIC_BOUND" in errors


def test_explicit_structured_dag_argument_is_reprojected_by_semantics():
    receipt = rd.make_route_receipt(
        nature="spec_generation", requested_evidence="lint_validated",
        delivery_target="rtl", semantic_payload_sha256="a" * 64,
        source_sha256="b" * 64, nature_table=tnr.NATURE_ENTRY,
        evidence_table=tnr.EVIDENCE_EXIT, delivery_table=tnr.DELIVERY_TARGETS,
        dag=rd.canonical_dag())
    assert receipt["input_contract"] == "original"
    assert rd.validate_route_receipt(receipt, dag=rd.canonical_dag()) == []


def test_unknown_input_contract_is_rejected():
    with pytest.raises(ValueError, match="unknown route input contract"):
        rd.canonical_dag(input_contract="unverified")
