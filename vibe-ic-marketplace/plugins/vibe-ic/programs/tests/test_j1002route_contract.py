"""Synthetic, design-neutral acceptance controls for J1002ROUTE."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import route_decision as rd  # noqa: E402
import task_nature_route as tnr  # noqa: E402
import benchmark_dispatch as bd  # noqa: E402
import benchmark_io_adapter as bio  # noqa: E402


def _route(prompt: str, *, nature: str = "spec_generation",
           evidence: str | None = None, target: str = "rtl",
           source: str | None = None, context: dict | None = None,
           explicit=None) -> dict:
    return tnr.route_decision_receipt(
        prompt, nature=nature, requested_evidence=evidence,
        delivery_target=target, source_sha256=source,
        context=context, explicit_user_evidence=explicit)


def _keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _keys(child)


def _activated(receipt: dict, *, source: str, task: str,
               ldoc: str = "root-test", invocation: str = "call-test"):
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256=source,
        task_sha256=task)
    provenance = {"ran": True, "digest": "e" * 64}
    gate = rd.make_d1_gate(
        verdict="PASS", route_receipt=receipt, provenance=provenance,
        source_sha256=source, task_sha256=task, ldoc_root_handle=ldoc,
        invocation_id=invocation, report_sha256="a" * 64)
    activation = rd.activate_d1(
        pending=pending, route_receipt=receipt, provenance=provenance,
        source_sha256=source, task_sha256=task, ldoc_root_handle=ldoc,
        d1_gate=gate)
    return pending, activation


def test_semantic_payload_is_invariant_under_opaque_coordinator_identity():
    prompt = "Design a two-input neutral combinational module."
    left = tnr.semantic_routing_payload(
        prompt,
        context={"category": "alpha", "problem_id": "p-1",
                 "project_path": "/tmp/one/projects/p-1",
                 "harness": "hidden-a", "golden": "secret-a",
                 "semantic_hint": "new RTL"})
    right = tnr.semantic_routing_payload(
        prompt,
        context={"category": "beta", "problem_id": "p-2",
                 "project_path": "/other/projects/p-2",
                 "harness": "hidden-b", "golden": "secret-b",
                 "semantic_hint": "new RTL"})
    assert left == right
    assert left["semantic_payload_sha256"] == right["semantic_payload_sha256"]
    forbidden = {"id", "problem_id", "benchmark", "project", "project_path",
                 "prompt_path", "response_path", "harness", "golden", "expected"}
    assert not (set(_keys(left)) & forbidden)

    r1 = _route(prompt, source="a" * 64,
                context={"problem_id": "p-1", "project_path": "/tmp/one"})
    r2 = _route(prompt, source="a" * 64,
                context={"problem_id": "p-2", "project_path": "/tmp/two"})
    assert r1 == r2


def _staged_route_input(tmp_path, context=None):
    project = tmp_path / "run" / "projects" / "neutral_input"
    prompt = "Complete the supplied module without renaming its interface.\n"
    staged = bio.stage("cvdp", {
        "id": "neutral_input",
        "record": {"input": {"prompt": prompt, "context": context or {}}},
    }, project)
    proposal = tnr.route_task(prompt, rtl_paths=list(context or {}))
    return project, staged, proposal


def test_issued_route_payload_preserves_exact_supplied_context(tmp_path):
    context = {
        "rtl/neutral.sv": "// supplied λ\r\nmodule neutral(input a, output b);\r\nendmodule\r\n",
        "notes/interface.md": "Keep the declared interface.\n\n  Preserve spacing.\n",
    }
    project, staged, proposal = _staged_route_input(tmp_path, context)
    task = bd._make_ai_route_task(
        "neutral_input", project, staged, proposal, tmp_path / "run", "cvdp",
        benchmark="opaque-suite", dataset_path=tmp_path / "opaque-dataset")
    payload = task["semantic_payload"]
    assert payload["context"]["supplied_context"] == context
    assert payload["prompt"] == (project / "input/phase1_prompt.md").read_text()
    assert all(opaque not in json.dumps(payload) for opaque in
               ("opaque-suite", "opaque-dataset", str(project)))


@pytest.mark.parametrize("damage", ["bytes", "manifest", "prompt"])
def test_issued_route_rejects_changed_original_input(tmp_path, damage):
    project, staged, proposal = _staged_route_input(
        tmp_path, {"neutral.sv": "module neutral; endmodule\n"})
    if damage == "bytes":
        (project / "input/public_original/files/neutral.sv").write_text("changed\n")
    elif damage == "manifest":
        staged["public_original_input"] = dict(staged["public_original_input"],
                                                source_sha256="0" * 64)
    else:
        (project / "input/phase1_prompt.md").write_text("A changed request.\n")
    with pytest.raises(ValueError, match="PUBLIC_INPUT_HANDOFF_INVALID"):
        bd._make_ai_route_task("neutral_input", project, staged, proposal,
                               tmp_path / "run", "cvdp")


def test_prompt_only_issued_route_keeps_existing_payload_bytes(tmp_path):
    project, staged, proposal = _staged_route_input(tmp_path)
    prompt = (project / "input/phase1_prompt.md").read_text()
    previous_payload = tnr.semantic_routing_payload(prompt, context={
        "program_proposal": {
            "nature": proposal.get("nature"),
            "entry_nature": proposal.get("entry_nature"),
            "source": proposal.get("source"),
            "needs_ai_parse": proposal.get("needs_ai_parse"),
        }})
    task = bd._make_ai_route_task("neutral_input", project, staged, proposal,
                                  tmp_path / "run", "cvdp")
    assert json.dumps(task["semantic_payload"], sort_keys=True).encode() == \
        json.dumps(previous_payload, sort_keys=True).encode()


@pytest.mark.parametrize(
    ("nature", "evidence", "target", "expected"),
    [
        ("spec_generation", "lint_validated", "rtl", "2"),
        ("spec_generation", "behaviour", "rtl", "4"),
        ("spec_generation", "lint_validated", "shippable_gds", "37.5ic"),
        ("optimization", "existence", "rtl", "2"),
    ],
)
def test_each_lower_bound_can_dominate(nature, evidence, target, expected):
    receipt = _route("neutral request", nature=nature, evidence=evidence,
                     target=target, source="b" * 64)
    assert receipt["verify_through"] == expected
    assert rd.validate_route_receipt(receipt) == []


def test_join_carries_transitive_dependency_closure():
    joined = rd.dependency_closed_join(["9"])
    assert joined["step"] == "9"
    assert {"D1", "1", "2", "3", "8", "9"} <= set(joined["closed_steps"])
    assert joined["dag_sha256"] == rd.canonical_dag()["sha256"]


def test_answer_location_cannot_weaken_verification():
    receipt = _route("ship the RTL and prove behaviour", evidence="behaviour",
                     target="rtl", source="c" * 64)
    assert receipt["answer_step"] == "1"
    assert receipt["verify_through"] == "4"
    assert receipt["verify_through"] != receipt["answer_step"]


def test_trusted_tables_keep_behaviour_and_gds_step4_in_closure():
    receipt = _route("ship verified design", evidence="behaviour", target="gds",
                     source="5" * 64)
    assert receipt["verify_through"] == "37"
    assert receipt["minimum_steps"] == ["D1", "4", "37"]
    assert "4" in receipt["verify_closed_steps"]
    assert rd.validate_route_receipt(receipt) == []


def test_rehashed_step4_to_step1_route_downgrade_is_rejected():
    receipt = _route("ship verified design", evidence="behaviour", target="gds",
                     source="6" * 64)
    downgraded = dict(receipt)
    downgraded["verify_through"] = "1"
    downgraded["minimum_steps"] = ["D1", "1", "37"]
    downgraded["verify_closed_steps"] = [
        step for step in receipt["verify_closed_steps"] if step != "4"]
    body = {key: downgraded.get(key) for key in (
        "schema", "entry_step", "answer_step", "verify_through",
        "verify_closed_steps", "minimum_steps", "task_nature",
        "requested_evidence", "delivery_target", "mode_intent",
        "semantic_payload_sha256", "source_sha256", "dag_sha256")}
    downgraded["receipt_sha256"] = rd.sha256_json(body)
    errors = rd.validate_route_receipt(downgraded)
    assert "ROUTE_RECEIPT_VERIFY_BELOW_MINIMUM" in errors
    assert "ROUTE_RECEIPT_MINIMUMS_NOT_TABLE_BOUND" in errors
    assert "ROUTE_RECEIPT_CLOSURE_NOT_DEPENDENCY_CLOSED" in errors


def test_every_trusted_closure_member_crosses_runner_admission():
    source = "7" * 64
    receipt = _route("ship verified design", evidence="behaviour", target="gds",
                     source=source)
    pending, activation = _activated(receipt, source=source, task="task-closure")
    admitted = rd.admit_route_closure(
        pending=pending, activation=activation, route_receipt=receipt,
        task_sha256="task-closure", source_sha256=source,
        ldoc_root_handle="root-test")
    assert admitted == receipt["verify_closed_steps"]
    assert "4" in admitted


def test_unrequested_ultra_is_never_inferred_from_metadata():
    request_a = {"prompt": "neutral", "category": "ultra-benchmark",
                 "mode": "ultra", "env": {"EXECUTION_MODE": "ultra"}}
    request_b = {"prompt": "neutral", "category": "ordinary",
                 "mode": "default", "env": {}}
    a = rd.mode_intent(semantic_request=request_a)
    b = rd.mode_intent(semantic_request=request_b)
    assert a["authority"] == b["authority"] == "PROGRAM_DEFAULT"
    assert a["ultra_match"] is b["ultra_match"] is False
    low_power = rd.mode_intent(
        semantic_request={"prompt": "design an ultra-low-power ADC"},
        explicit_user_evidence={"source": "user", "text":
                                 "design an ultra-low-power ADC"})
    assert low_power["authority"] == "PROGRAM_DEFAULT"
    assert low_power["ultra_match"] is False
    vague = rd.mode_intent(
        semantic_request={"prompt": "use ultra-low-power implementation"},
        explicit_user_evidence={"source": "user", "text":
                                 "use ultra-low-power implementation"})
    assert vague["authority"] == "PROGRAM_DEFAULT"
    assert vague["ultra_match"] is False
    explicit = rd.mode_intent(
        semantic_request={"prompt": "neutral"},
        explicit_user_evidence=rd.explicit_ultra_evidence(
            "Please use ultra mode."))
    assert explicit["authority"] == "USER_EXPLICIT_ULTRA"
    assert explicit["ultra_match"] is True
    receipt = _route(
        "Please use ultra mode.", source="8" * 64,
        explicit=rd.explicit_ultra_evidence("Please use ultra mode."))
    assert receipt["mode_intent"]["ultra_match"] is True
    assert rd.validate_route_receipt(receipt) == []


def test_forged_ultra_authority_without_typed_evidence_is_rejected():
    receipt = _route("neutral request", source="9" * 64)
    forged = dict(receipt)
    forged["mode_intent"] = {
        "authority": "USER_EXPLICIT_ULTRA",
        "ultra_match": True,
        "request_digest": rd.sha256_text("forged-request"),
        "evidence_sha256": rd.sha256_text("forged-evidence"),
    }
    body = {key: forged.get(key) for key in (
        "schema", "entry_step", "answer_step", "verify_through",
        "verify_closed_steps", "minimum_steps", "task_nature",
        "requested_evidence", "delivery_target", "mode_intent",
        "semantic_payload_sha256", "source_sha256", "dag_sha256")}
    forged["receipt_sha256"] = rd.sha256_json(body)
    errors = rd.validate_route_receipt(forged)
    assert "ROUTE_RECEIPT_ULTRA_EVIDENCE_INVALID" in errors
    assert "ROUTE_RECEIPT_ULTRA_ISSUER_UNBOUND" in errors


@pytest.mark.parametrize("text", [
    "Do not use ultra mode.",
    "Never use ultra-mode; use default mode.",
    "If useful, use ultra mode.",
    "Use ultra mode, but default mode is preferred.",
    "Do not set execution mode: ultra.",
    "Execution mode: default; ultra mode is unavailable.",
    "I do not want ultra mode.",
    "Refuse ultra mode.",
    "anything except ultra mode; use ultra mode.",
    "prohibited: use ultra mode.",
    "do not ever use ultra mode.",
])
def test_negated_conditional_or_conflicting_ultra_text_cannot_authorize(text):
    assert rd.explicit_ultra_evidence(text) is None
    assert rd.mode_intent(
        semantic_request={"prompt": text},
        explicit_user_evidence={"source": "user", "text": text},
    )["authority"] == "PROGRAM_DEFAULT"


def test_d1_pending_admits_only_d1_until_route_bound_activation():
    receipt = _route("new neutral design", source="d" * 64)
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256="d" * 64,
        task_sha256="task-a")
    assert rd.admit_canonical_step(
        step="D1", pending=pending, activation=None,
        route_receipt=receipt, source_sha256="d" * 64,
        task_sha256="task-a") == rd.D1_PENDING
    with pytest.raises(ValueError, match="D1_ACTIVATION_REQUIRED"):
        rd.admit_canonical_step(
            step="1", pending=pending, activation=None,
            route_receipt=receipt, source_sha256="d" * 64,
            task_sha256="task-a")
    provenance = {"ran": True, "digest": "e" * 64}
    gate = rd.make_d1_gate(
        verdict="PASS", route_receipt=receipt, provenance=provenance,
        source_sha256="d" * 64, task_sha256="task-a", ldoc_root_handle="root-a",
        invocation_id="call-a", report_sha256="a" * 64)
    activation = rd.activate_d1(
        pending=pending, route_receipt=receipt, provenance=provenance,
        source_sha256="d" * 64, task_sha256="task-a",
        ldoc_root_handle="root-a", d1_gate=gate)
    assert rd.admit_canonical_step(
        step="1", pending=pending, activation=activation,
        route_receipt=receipt, source_sha256="d" * 64,
        task_sha256="task-a", ldoc_root_handle="root-a") == rd.D1_ACTIVATED
    with pytest.raises(ValueError, match="ROUTE_INVALID|ROUTE_MISMATCH|SOURCE_MISMATCH"):
        foreign = dict(receipt)
        foreign["receipt_sha256"] = "f" * 64
        rd.admit_canonical_step(
            step="1", pending=pending, activation=activation,
            route_receipt=foreign, source_sha256="d" * 64,
            task_sha256="task-a", ldoc_root_handle="root-a")


def test_d1_fail_or_missing_provenance_cannot_activate():
    receipt = _route("new neutral design", source="f" * 64)
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256="f" * 64,
        task_sha256="task-f")
    with pytest.raises(ValueError, match="PROVENANCE_MISSING"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt,
            provenance={"ran": False}, source_sha256="f" * 64,
            task_sha256="task-f", ldoc_root_handle="root-f")


def test_d1_synthetic_activation_without_provenance_or_typed_gate_fails():
    source = "0" * 64
    receipt = _route("typed D1", source=source)
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256=source,
        task_sha256="task-missing")
    with pytest.raises(ValueError, match="D1_ACTIVATION_PROVENANCE_MISSING"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance={"ran": True},
            source_sha256=source, task_sha256="task-missing",
            ldoc_root_handle="root-missing")
    provenance = {"ran": True, "digest": "1" * 64}
    with pytest.raises(ValueError, match="D1_ACTIVATION_GATE_MISSING"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256=source, task_sha256="task-missing",
            ldoc_root_handle="root-missing")


@pytest.mark.parametrize("field", [
    "d1_gate", "d1_provenance_sha256", "d1_gate_sha256",
    "task_sha256", "ldoc_root_handle", "activation_sha256",
])
def test_d1_activation_missing_field_cannot_be_self_rehashed(field):
    source = "8" * 64
    receipt = _route("typed D1", source=source)
    pending, activation = _activated(receipt, source=source, task="task-schema")
    forged = dict(activation)
    forged.pop(field)
    body = {key: forged[key] for key in (
        "schema", "status", "route_receipt_sha256", "source_sha256",
        "d1_provenance_sha256", "d1_gate_sha256", "d1_gate",
        "task_sha256", "ldoc_root_handle") if key in forged}
    with pytest.raises(ValueError, match="D1_ACTIVATION_SCHEMA_FIELDS_INVALID"):
        rd.require_d1_activation(
            forged, receipt, task_sha256="task-schema", ldoc_root_handle="root-test")


@pytest.mark.parametrize(
    ("invocation_id", "report_sha256", "error"),
    [("", "a" * 64, "INVOCATION"),
     (" bad", "a" * 64, "INVOCATION"),
     ("call-report", "z" * 64, "REPORT")],
)
def test_d1_gate_requires_valid_current_invocation_and_report_digest(
        invocation_id, report_sha256, error):
    source = "9" * 64
    receipt = _route("typed D1", source=source)
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256=source,
        task_sha256="task-gate")
    provenance = {"ran": True, "digest": "b" * 64}
    gate = rd.make_d1_gate(
        verdict="PASS", route_receipt=receipt, provenance=provenance,
        source_sha256=source, task_sha256="task-gate", ldoc_root_handle="root-gate",
        invocation_id=invocation_id, report_sha256=report_sha256)
    with pytest.raises(ValueError, match=error):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256=source, task_sha256="task-gate",
            ldoc_root_handle="root-gate", d1_gate=gate)


@pytest.mark.parametrize("verdict", ["FAIL", "NOT_MEASURED", "BLOCKED"])
def test_d1_nonpassing_gate_cannot_activate(verdict):
    receipt = _route("new neutral design", source="1" * 64)
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256="1" * 64,
        task_sha256="task-h")
    provenance = {"ran": True, "digest": "a" * 64}
    gate = rd.make_d1_gate(
        verdict=verdict, route_receipt=receipt, provenance=provenance,
        source_sha256="1" * 64, task_sha256="task-h", ldoc_root_handle="root-h",
        invocation_id="call-h", report_sha256="b" * 64)
    with pytest.raises(ValueError, match="D1_ACTIVATION_GATE_NOT_PASS"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256="1" * 64, task_sha256="task-h",
            ldoc_root_handle="root-h", d1_gate=gate)


def test_d1_gate_foreign_binding_cannot_activate():
    receipt = _route("new neutral design", source="2" * 64)
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256="2" * 64,
        task_sha256="task-j")
    provenance = {"ran": True, "digest": "c" * 64}
    gate = rd.make_d1_gate(
        verdict="PASS", route_receipt=receipt, provenance=provenance,
        source_sha256="2" * 64, task_sha256="task-other", ldoc_root_handle="root-j",
        invocation_id="call-j", report_sha256="d" * 64)
    with pytest.raises(ValueError, match="TASK_SHA256_MISMATCH"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256="2" * 64, task_sha256="task-j",
            ldoc_root_handle="root-j", d1_gate=gate)


def test_d1_pass_with_waivers_has_typed_policy_absence_on_current_main():
    receipt = _route("new neutral design", source="3" * 64)
    with pytest.raises(NotImplementedError, match="POLICY_PRODUCER_UNAVAILABLE"):
        rd.make_d1_waiver(
            route_receipt=receipt, source_sha256="3" * 64, task_sha256="task-l",
            ldoc_root_handle="root-l", invocation_id="call-l", report_sha256="f" * 64,
            authorized_by="policy-owner", expires_at=4102444800,
            reason="documented D1 exception")
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256="3" * 64,
        task_sha256="task-l")
    provenance = {"ran": True, "digest": "e" * 64}
    forged_policy = {"schema": "vibeic.route_d1_waiver.v1",
                     "scope": "D1", "authorized_by": "caller"}
    gate = rd.make_d1_gate(
        verdict="PASS_WITH_WAIVERS", route_receipt=receipt, provenance=provenance,
        source_sha256="3" * 64, task_sha256="task-l", ldoc_root_handle="root-l",
        invocation_id="call-l", report_sha256="f" * 64,
        waiver_receipt=forged_policy)
    with pytest.raises(ValueError, match="POLICY_PRODUCER_UNAVAILABLE"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256="3" * 64, task_sha256="task-l",
            ldoc_root_handle="root-l", d1_gate=gate)


def test_d1_pww_without_bound_current_waiver_is_refused():
    receipt = _route("new neutral design", source="4" * 64)
    pending = rd.write_d1_pending(
        Path("/dev/null"), route_receipt=receipt, source_sha256="4" * 64,
        task_sha256="task-pww")
    provenance = {"ran": True, "digest": "5" * 64}
    gate = rd.make_d1_gate(
        verdict="PASS_WITH_WAIVERS", route_receipt=receipt, provenance=provenance,
        source_sha256="4" * 64, task_sha256="task-pww", ldoc_root_handle="root-pww",
        invocation_id="call-pww", report_sha256="6" * 64)
    with pytest.raises(ValueError, match="D1_ACTIVATION_WAIVER_MISSING"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256="4" * 64, task_sha256="task-pww",
            ldoc_root_handle="root-pww", d1_gate=gate)
    stale = {"schema": "vibeic.route_d1_waiver.v1", "scope": "D1",
             "authorized_by": "caller", "invocation_id": "foreign-call"}
    gate = rd.make_d1_gate(
        verdict="PASS_WITH_WAIVERS", route_receipt=receipt, provenance=provenance,
        source_sha256="4" * 64, task_sha256="task-pww", ldoc_root_handle="root-pww",
        invocation_id="call-pww", report_sha256="6" * 64,
        waiver_receipt=stale)
    with pytest.raises(ValueError, match="POLICY_PRODUCER_UNAVAILABLE"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256="4" * 64, task_sha256="task-pww",
            ldoc_root_handle="root-pww", d1_gate=gate)
    expired = {"schema": "vibeic.route_d1_waiver.v1", "scope": "D1",
               "authorized_by": "caller", "expires_at": 1}
    gate = rd.make_d1_gate(
        verdict="PASS_WITH_WAIVERS", route_receipt=receipt, provenance=provenance,
        source_sha256="4" * 64, task_sha256="task-pww", ldoc_root_handle="root-pww",
        invocation_id="call-pww", report_sha256="6" * 64,
        waiver_receipt=expired)
    with pytest.raises(ValueError, match="POLICY_PRODUCER_UNAVAILABLE"):
        rd.activate_d1(
            pending=pending, route_receipt=receipt, provenance=provenance,
            source_sha256="4" * 64, task_sha256="task-pww",
            ldoc_root_handle="root-pww", d1_gate=gate)


def test_sequential_route_receipts_advance_pointer_without_mutating_old(tmp_path):
    first = _route("first run", source="7" * 64)
    second = _route("second run", source="8" * 64)
    old_path = bd._publish_current_receipt(
        tmp_path, "route_decision", first, digest_field="receipt_sha256",
        run_id="run-a")
    new_path = bd._publish_current_receipt(
        tmp_path, "route_decision", second, digest_field="receipt_sha256",
        run_id="run-b")
    pointer = json.loads(bd._receipt_current_pointer(tmp_path, "route_decision").read_text())
    assert pointer["payload_digest"] == second["receipt_sha256"]
    assert pointer["sequence"] == 2
    assert old_path.is_file() and new_path.is_file() and old_path != new_path
    with pytest.raises(ValueError, match="changed after issue"):
        bd._write_bound_route_record(old_path, {**first, "source_sha256": "9" * 64})
    with pytest.raises(ValueError, match="RUN_ID_REPLAY"):
        bd._publish_current_receipt(
            tmp_path, "route_decision", first, digest_field="receipt_sha256",
            run_id="run-a")
    with pytest.raises(ValueError, match="PREDECESSOR_COMPARE_FAILED"):
        bd._publish_current_receipt(
            tmp_path, "route_decision", first, digest_field="receipt_sha256",
            run_id="run-c", expected_predecessor_digest=old_path.stem,
            expected_sequence=1)
    current = bd._read_current_receipt(tmp_path, "route_decision")
    assert current["receipt"] == second


def test_same_semantic_decision_gets_distinct_run_receipts(tmp_path):
    decision = _route("same semantic run", source="6" * 64)
    first_path = bd._publish_current_receipt(
        tmp_path, "route_decision", decision, digest_field="receipt_sha256",
        run_id="same-run-a")
    second_path = bd._publish_current_receipt(
        tmp_path, "route_decision", decision, digest_field="receipt_sha256",
        run_id="same-run-b")
    assert first_path != second_path
    pointer = json.loads(bd._receipt_current_pointer(
        tmp_path, "route_decision").read_text())
    assert pointer["payload_digest"] == decision["receipt_sha256"]
    assert pointer["sequence"] == 2


def test_current_pointer_mutated_predecessor_or_rollback_is_refused(tmp_path):
    first = _route("first run", source="a" * 64)
    second = _route("second run", source="b" * 64)
    bd._publish_current_receipt(tmp_path, "route_decision", first,
                                digest_field="receipt_sha256", run_id="run-a")
    bd._publish_current_receipt(tmp_path, "route_decision", second,
                                digest_field="receipt_sha256", run_id="run-b")
    pointer_path = bd._receipt_current_pointer(tmp_path, "route_decision")
    first_path = bd._receipt_store_path(tmp_path, "route_decision",
                                        json.loads(
                                            bd._receipt_current_pointer(
                                                tmp_path, "route_decision").read_text()
                                        )["predecessor_digest"])
    # Replaying the first immutable envelope as the current pointer is a
    # rollback even though its own bytes and predecessor are intact.
    first_envelope = json.loads(first_path.read_text())
    rollback = dict(json.loads(pointer_path.read_text()))
    for key in ("run_id", "sequence", "predecessor_digest", "payload_digest"):
        rollback[key] = first_envelope[key]
    rollback["receipt_digest"] = rd.sha256_json(first_envelope)
    rollback["receipt_path"] = str(first_path)
    pointer_path.write_text(json.dumps(rollback))
    with pytest.raises(ValueError, match="HISTORY_MISMATCH|POINTER_ROLLBACK"):
        bd._read_current_receipt(tmp_path, "route_decision")

    # A separate current pointer mutation exercises the predecessor binding.
    corrupt_root = tmp_path / "corrupt"
    bd._publish_current_receipt(corrupt_root, "route_decision", first,
                                digest_field="receipt_sha256", run_id="run-a")
    bd._publish_current_receipt(corrupt_root, "route_decision", second,
                                digest_field="receipt_sha256", run_id="run-b")
    pointer_path = bd._receipt_current_pointer(corrupt_root, "route_decision")
    pointer = json.loads(pointer_path.read_text())
    pointer["predecessor_digest"] = "0" * 64
    pointer_path.write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="PREDECESSOR.*MISMATCH|POINTER_ROLLBACK"):
        bd._read_current_receipt(corrupt_root, "route_decision")


@pytest.mark.parametrize("mutation", ["corrupt", "missing", "sequence"])
def test_newer_receipt_corruption_blocks_a_b_a_rollback(tmp_path, mutation):
    root = tmp_path / mutation
    first = _route("first run", source="c" * 64)
    second = _route("second run", source="d" * 64)
    first_path = bd._publish_current_receipt(
        root, "route_decision", first, digest_field="receipt_sha256", run_id="run-a")
    second_path = bd._publish_current_receipt(
        root, "route_decision", second, digest_field="receipt_sha256", run_id="run-b")
    if mutation == "corrupt":
        second_path.write_text("{}")
    elif mutation == "missing":
        second_path.unlink()
    else:
        changed = json.loads(second_path.read_text())
        changed["sequence"] = 99
        second_path.write_text(json.dumps(changed))
    pointer_path = bd._receipt_current_pointer(root, "route_decision")
    current = json.loads(pointer_path.read_text())
    first_envelope = json.loads(first_path.read_text())
    for key in ("run_id", "sequence", "predecessor_digest", "payload_digest",
                "payload_digest_field"):
        current[key] = first_envelope[key]
    current["receipt_digest"] = first_path.stem
    current["receipt_path"] = str(first_path)
    pointer_path.write_text(json.dumps(current))
    with pytest.raises(ValueError, match="HISTORY|ENVELOPE|SEQUENCE|CURRENT|regular file"):
        bd._read_current_receipt(root, "route_decision")


def test_semantic_payload_preserves_legitimate_critical_path_and_answer():
    payload = tnr.semantic_routing_payload(
        "protocol design", context={
            "critical_path": "req_valid -> ack_valid",
            "answer": "ack_valid must pulse once",
            "project_path": "/opaque/project",
        })
    assert payload["context"]["critical_path"] == "req_valid -> ack_valid"
    assert payload["context"]["answer"] == "ack_valid must pulse once"
    assert "project_path" not in payload["context"]


def test_nested_design_keys_survive_coordinator_split_and_bind_opaque_paths():
    prompt = "Implement the register protocol."
    left = tnr.semantic_routing_payload(prompt, context={
        "design_context": {
            "register": {"id": "CTRL_STATUS", "mode": "rw"},
            "constraint": {"mode": "timing", "category": "control"},
            "project": "uart_block", "critical_path": "req->ack",
        },
        "coordinator": {
            "benchmark": "bench-a", "problem_id": "p-a",
            "harness_path": "/secret/a/harness", "golden_path": "/secret/a/golden",
            "dataset_path": "/secret/a/dataset",
        },
    })
    right = tnr.semantic_routing_payload(prompt, context={
        "design_context": {
            "register": {"id": "CTRL_STATUS", "mode": "rw"},
            "constraint": {"mode": "timing", "category": "control"},
            "project": "uart_block", "critical_path": "req->ack",
        },
        "coordinator": {
            "benchmark": "bench-b", "problem_id": "p-b",
            "harness_path": "/other/harness", "golden_path": "/other/golden",
            "dataset_path": "/other/dataset",
        },
    })
    assert left == right
    assert left["context"]["register"]["id"] == "CTRL_STATUS"
    assert left["context"]["constraint"]["mode"] == "timing"
    assert left["context"]["project"] == "uart_block"
    assert left["context"]["critical_path"] == "req->ack"
    assert all(secret not in json.dumps(left) for secret in
               ("bench-a", "p-a", "/secret/a/harness", "/secret/a/golden",
                "/secret/a/dataset"))
    binding = rd.build_coordinator_binding(
        benchmark="bench-a", problem_id="p-a", project_path="/project/a",
        prompt_path="/prompt/a", response_path="/response/a",
        dataset_path="/secret/a/dataset", harness_path="/secret/a/harness",
        golden_path="/secret/a/golden", expected_path="/secret/a/expected",
        semantic_payload_sha256=left["semantic_payload_sha256"])
    raw = json.dumps(binding)
    assert all(secret not in raw for secret in (
        "bench-a", "p-a", "/project/a", "/prompt/a", "/response/a",
        "/secret/a/"))
    assert binding["benchmark_handle"] == rd.sha256_text("bench-a")
    assert binding["problem_handle"] == rd.sha256_text("p-a")
    assert binding["dataset_handle"] == rd.sha256_text("/secret/a/dataset")


def test_legacy_mixed_context_only_strips_known_top_level_coordinator_fields():
    payload = tnr.semantic_routing_payload("legacy design", context={
        "problem_id": "opaque-problem", "project_path": "/opaque/project",
        "harness": "opaque-harness", "golden": "opaque-golden",
        "dataset_path": "/opaque/dataset", "design": {
            "register": {"id": "R0"}, "constraint": {"mode": "hold"},
            "category": "datapath", "project": "core", "critical_path": "a->b",
        },
    })
    text = json.dumps(payload, sort_keys=True)
    assert "opaque-problem" not in text and "/opaque/" not in text
    assert payload["context"]["design"]["register"]["id"] == "R0"
    assert payload["context"]["design"]["constraint"]["mode"] == "hold"


def test_canonical_dag_reads_multiline_blocks_and_required_inputs(tmp_path):
    flow = tmp_path / "flow.yaml"
    flow.write_text("""
steps:
  - id: D1
    blocks_on: []
    required_inputs:
      - from: external
  - id: 1
    blocks_on: []
    required_inputs:
      - from: D1
        path: |
          phase1/generated_docs/L1.json
          OR phase1/generated_docs/L5.json
  - id: 2
    blocks_on:
      - D1
      - 1
    required_inputs: []
""")
    dag = rd.canonical_dag(flow)
    assert dag["blocks_on"]["1"] == ["D1"]
    assert dag["required_inputs_from"]["1"] == ["D1"]
    assert rd.dependency_closed_join(["1"], dag=dag)["closed_steps"] == ["D1", "1"]
    assert rd.dependency_closed_join(["2"], dag=dag)["closed_steps"] == ["D1", "1", "2"]


def test_multiline_dependency_mutation_changes_closure_and_dag_digest(tmp_path):
    common = """
steps:
  - id: D1
    blocks_on: []
    required_inputs:
      - from: external
  - id: 1
    blocks_on: []
    required_inputs:
      - from: D1
        path: |
          phase1/generated_docs/L1.json
          OR phase1/generated_docs/L5.json
  - id: 2
    required_inputs: []
"""
    flow_blocks_d1 = tmp_path / "blocks-d1.yaml"
    flow_blocks_1 = tmp_path / "blocks-1.yaml"
    flow_blocks_d1.write_text(common + "    blocks_on:\n      - D1\n")
    flow_blocks_1.write_text(common + "    blocks_on:\n      - 1\n")
    first = rd.canonical_dag(flow_blocks_d1)
    second = rd.canonical_dag(flow_blocks_1)
    assert first["sha256"] != second["sha256"]
    assert rd.dependency_closed_join(["2"], dag=first)["closed_steps"] == ["D1", "2"]
    assert rd.dependency_closed_join(["2"], dag=second)["closed_steps"] == [
        "D1", "1", "2"]


def test_reverse_mutation_of_receipt_is_rejected():
    receipt = _route("neutral request", evidence="behaviour", source="g" * 64)
    mutated = dict(receipt)
    mutated["verify_through"] = "1"
    assert "ROUTE_RECEIPT_DIGEST_MISMATCH" in rd.validate_route_receipt(mutated)


@pytest.mark.parametrize('prompt,affected', [
    ('Debug the supplied RTL; return corrected Verilog.', False),
    ('Implement the RTL module and deliver its LEF and Liberty views.', True),
    ('請設計晶片並交付可投片的實體版圖，完成製造與封裝。', True),
])
def test_issued_r5_route_replays_only_when_source_requirements_are_unchanged(
        tmp_path, monkeypatch, prompt, affected):
    import hashlib
    run = tmp_path / 'run'
    project = run / 'projects/neutral_delivery'
    staged = bio.stage('cvdp', {'id': 'neutral_delivery',
                              'record': {'input': {'prompt': prompt, 'context': {}}}}, project)
    proposal = tnr.route_task(prompt)
    current = tnr.prompt_delivery_requirements(prompt)
    legacy = dict(current, status='UNSPECIFIED', route_family=None,
                  minimum_target=None, evidence=[], reasons=[])
    legacy['requirements_sha256'] = hashlib.sha256(json.dumps(
        {key: value for key, value in legacy.items() if key != 'requirements_sha256'},
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    with monkeypatch.context() as old:
        old.setattr(tnr, 'prompt_delivery_requirements', lambda _text: legacy)
        task = bd._make_ai_route_task('neutral_delivery', project, staged, proposal, run, 'cvdp')
    response = {
        'schema': bd._AI_ROUTE_SCHEMA, 'id': task['id'], 'task_sha256': task['task_sha256'],
        'prompt_sha256': task['prompt_sha256'],
        'source_sha256': task['public_original_input']['source_sha256'],
        'routing_contract_sha256': task['routing_contract_sha256'],
        'disposition': 'CONFIRM', 'ai_nature': proposal['entry_nature'],
        'author': {'kind': 'AI', 'model': 'neutral-source-review'},
        'blind': {'oracle_accessed': False},
        'rationale': 'The visible source asks for this ordinary design task and its declared outputs.',
        'prompt_evidence': [{'excerpt': prompt, 'supports': 'This source states the requested ordinary design task.'}],
        'semantic_decision': {'nature': proposal['entry_nature'], 'delivery_target': 'rtl',
                              'semantic_payload_sha256': task['semantic_payload_sha256']},
    }
    path = Path(task['response_path'])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(response))
    assert task['routing_contract_sha256'] == bd._route_contract_sha256()
    decision, reasons = bd._validate_ai_route(task, run)
    if affected:
        assert decision is None
        assert any('prompt delivery requirements changed after issue' in reason for reason in reasons)
    else:
        assert current == legacy
        assert decision is not None, reasons
