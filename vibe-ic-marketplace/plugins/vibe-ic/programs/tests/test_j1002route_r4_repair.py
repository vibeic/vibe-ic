"""R4 route admission controls and reverse mutations."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd  # noqa: E402
import emit_attestation as ea  # noqa: E402
import route_decision as rd  # noqa: E402
import task_nature_route as tnr  # noqa: E402
import _path_layout as path_layout  # noqa: E402
from _benchmark_io_fixture import issue_io_fixture  # noqa: E402


def _receipt(prompt: str, *, target: str = "shippable_gds") -> dict:
    source = hashlib.sha256(prompt.encode()).hexdigest()
    return tnr.route_decision_receipt(
        prompt,
        nature="spec_generation",
        requested_evidence="behaviour",
        delivery_target=target,
        source_sha256=source,
    )


def _route_state(tmp_path: Path, *, target: str = "gds") -> tuple[
        Path, Path, dict, dict, dict]:
    run = tmp_path / "run"
    project = run / "projects" / "p1"
    (project / "input").mkdir(parents=True)
    prompt = "Design a complete chip and deliver a verified GDS."
    (project / "input" / "phase1_prompt.md").write_text(prompt)
    receipt = _receipt(prompt, target=target)
    task = {"id": "p1", "project": str(project), "task_sha256": "t" * 64}
    result = {
        "id": "p1",
        "route_receipt": receipt,
        "entry": receipt["entry_step"],
        "exit": receipt["verify_through"],
        "delivery_route": tnr.delivery_route_for_target(target, "DIE"),
    }
    bd._publish_current_receipt(
        project, "route_decision", receipt,
        digest_field="receipt_sha256", run_id="r4-route-run")
    return run, project, receipt, task, result


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [("exit", "2", "ROUTE_REENTRY_EXIT_MUTATION"),
     ("delivery_route", "ip", "ROUTE_REENTRY_ROUTE_MUTATION")],
)
def test_immutable_route_receipt_rejects_executable_field_mutation(
        tmp_path, field, value, reason):
    run, _project, _receipt_value, task, result = _route_state(tmp_path)
    result[field] = value
    state = bd._validated_route_reentry_state(
        bench="rtllm", dataset=None, fmt=None, run_p=run, pid="p1",
        result=result, route_worklist=[task], allow_d1_only=False,
        supplied_rtl=True)
    assert state["status"] == "REFUSED"
    assert state["reason"] == reason


def _publish_live_d1(project: Path, receipt: dict, task_sha: str) -> dict:
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1.json").write_text('{"schema":"r4.fixture.ldoc.v1"}\n')
    provenance = ea.phase1_provenance(project)
    ldoc_handle = hashlib.sha256(str(docs.resolve()).encode()).hexdigest()
    report_path = path_layout.report_path(project, "phase1_one_shot.json")
    report = {
        "schema": "r4.fixture.phase1.report.v1",
        "verdict": "PASS",
        "runner_binding": {
            "schema": "vibeic.runner_report_binding.v1",
            "invocation_id": "r4-call-1",
            "project": str(project.resolve()),
            "report_name": "phase1_one_shot.json",
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_bytes = json.dumps(report, sort_keys=True).encode()
    report_path.write_bytes(report_bytes)
    pending = rd.write_d1_pending(
        project / "reports" / "orchestrator" / "receipts" /
        "d1_pending.current.json",
        route_receipt=receipt, source_sha256=receipt["source_sha256"],
        task_sha256=task_sha)
    gate = rd.make_d1_gate(
        verdict="PASS", route_receipt=receipt, provenance=provenance,
        source_sha256=receipt["source_sha256"], task_sha256=task_sha,
        ldoc_root_handle=ldoc_handle, invocation_id="r4-call-1",
        report_sha256=hashlib.sha256(report_bytes).hexdigest())
    activation = rd.activate_d1(
        pending=pending, route_receipt=receipt, provenance=provenance,
        source_sha256=receipt["source_sha256"], task_sha256=task_sha,
        ldoc_root_handle=ldoc_handle, d1_gate=gate)
    bd._publish_current_receipt(
        project, "d1_pending", pending,
        digest_field="activation_sha256", run_id="r4-pending-run")
    bd._publish_current_receipt(
        project, "d1_activation", activation,
        digest_field="activation_sha256", run_id="r4-activation-run")
    return activation


@pytest.mark.parametrize("mutation", ["prompt", "report"])
def test_stale_live_d1_cannot_authorize_later_launch(tmp_path, mutation):
    run, project, receipt, task, result = _route_state(tmp_path, target="gds")
    _publish_live_d1(project, receipt, task["task_sha256"])
    if mutation == "prompt":
        (project / "input" / "phase1_prompt.md").write_text(
            "Design a different chip and deliver a verified GDS.")
        expected = "D1_CURRENT_PROMPT_PROVENANCE_MISMATCH"
    else:
        report_path = path_layout.report_path(project, "phase1_one_shot.json")
        report = json.loads(report_path.read_text())
        report["verdict"] = "FAIL"
        report_path.write_text(json.dumps(report, sort_keys=True))
        expected = "D1_CURRENT_REPORT_NOT_PASS"
    state = bd._validated_route_reentry_state(
        bench="rtllm", dataset=None, fmt=None, run_p=run, pid="p1",
        result=result, route_worklist=[task], allow_d1_only=False,
        supplied_rtl=True)
    assert state["status"] == "REFUSED"
    assert expected in state["reason"]


def test_integrated_hardmacro_classifies_delivered_chip_as_ic():
    integrated = tnr.prompt_delivery_requirements(
        "Integrate an IP hardmacro into a complete chip and deliver a GDS.")
    standalone = tnr.prompt_delivery_requirements(
        "Deliver a standalone IP hardmacro with GDS, LEF and Liberty views.")
    assert integrated["route_family"] == "DIE"
    assert standalone["route_family"] == "HARDMACRO"
    assert tnr.resolve_prompt_delivery_target(integrated, "gds")["ok"]
    assert tnr.resolve_prompt_delivery_target(
        standalone, "ip_hardmacro")["ok"]


@pytest.mark.parametrize("option", ["program_regate", "program_retry"])
def test_program_reentry_missing_route_admission_refuses_before_dispatch(
        tmp_path, monkeypatch, capsys, option):
    run = tmp_path / "run"
    project = run / "projects" / "p1"
    (project / "input").mkdir(parents=True)
    (run / "responses").mkdir(parents=True)
    prompt = project / "input" / "phase1_prompt.md"
    prompt.write_text("repair the supplied module")
    task = {
        "schema": bd._REVIEW_TASK_SCHEMA,
        "id": "p1",
        "candidate_origin": "AI_REPAIR",
        "project": str(project),
        "prompt_path": str(prompt),
        "prompt_sha256": bd._sha256_text(prompt.read_text()),
        "rtl_sha256": "a" * 64,
        "response_path": str(run / "responses" / "p1.json"),
    }
    task_digest = bd._review_task_digest(task)
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    bd._atomic_write_json(run / "solve_report.json", {
        "acceptance_policy": {
            "required": True,
            "review_task_schema": bd._REVIEW_TASK_SCHEMA,
            "review_schema": bd._AI_REVIEW_SCHEMA,
        },
        "results": [{
            "id": "p1", "accepted": False, "exit": "2",
            "route_receipt": None,
        }],
    })
    # Issue the input-only I/O envelope, retaining the missing route receipt
    # and D1 admission this negative control is meant to refuse.
    issue_io_fixture(run, "rtllm", Path("/unused"), task=task)
    request = {
        "schema": bd._PROGRAM_REGATE_SCHEMA,
        "id": "p1",
        "task_sha256": task_digest,
        "prompt_sha256": task["prompt_sha256"],
        "stale_output_sha256": task["rtl_sha256"],
        "signed_input_sha256": "b" * 64,
        "program_identity": bd._program_source_identity(),
        "program_version_before": "old",
        "program_version_after": bd._program_version(),
        "author": {"kind": "AI", "model": "r4-test"},
        "blind": {"oracle_accessed": False},
        "rationale": "This explicit re-entry is bound to the fixed Program "
                     "and requires the current route and D1 admission.",
    }
    request_path = run / "program_regate_request.json"
    request_path.write_text(json.dumps(request))
    calls = []
    monkeypatch.setattr(bd._RunnerBudget, "run",
                        lambda *_args, **_kwargs: calls.append(1))
    assert bd.cmd_resume("rtllm", "/unused", str(run), worker_threads=1,
                         **{option: str(request_path)}) == 2
    assert "PROGRAM_REGATE_REFUSED" in capsys.readouterr().err
    assert calls == []
