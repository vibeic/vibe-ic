"""Bounded Flow109 continuation controls; never whole-flow qualification."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import flow109
import flow109_admission as admission
from programs.tests._hostpaths import require_repo


def _profile():
    return copy.deepcopy(next(
        item["features"] for item in flow109.load_registry()["reference_profiles"]
        if item["name"] == "Small digital IC without DFT"))


def _artifact(project, relative, content):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _window_fixture(project, monkeypatch):
    plan = flow109.resolve_plan(_profile())
    rows = [flow109.resolve_step(plan, step) for step in ("D31", "D32")]
    runtime, records, executables = [], [], {}
    for row in rows:
        for number, use in enumerate(row["tool_uses"]):
            tag = f"{row['id']}-{number}-{use['tool_id']}"
            executable = _artifact(project, f"qualification/{tag}.exe", tag)
            executables[use["executable_name"]] = executable["path"]
            identity = {
                "use_id": use["use_id"], "tool_id": use["tool_id"],
                "version": "unit-window", "build_sha256": executable["sha256"],
                "executable": executable,
                "config": _artifact(project, f"qualification/{tag}.config", "config-" + tag),
                "pdk": _artifact(project, f"qualification/{tag}.pdk", "pdk-" + tag),
                "deck": _artifact(project, f"qualification/{tag}.deck", "deck-" + tag),
                "corner": "unit-corner",
                "semantics": {"purpose": use["purpose"], "native_steps": use["native_steps"]},
            }
            record = {"use_id": use["use_id"], "status": "QUALIFIED",
                      "identity": identity,
                      "reference_evidence": [_artifact(
                          project, f"qualification/{tag}.reference", "reference-" + tag)]}
            records.append(record)
            runtime.append({**identity, "qualification_sha256": admission.canonical_sha(record)})
    monkeypatch.setattr(admission.shutil, "which", lambda name: executables.get(name))
    registry = {"schema": "vibeic.flow109.qualifications.v1", "uses": records}
    (project / "qualifications.json").write_text(json.dumps(registry))
    context = flow109.execution_context(
        plan, "D31", "D32", runtime_tool_uses=runtime,
        qualification_registry="qualifications.json")
    return plan, context, registry


def test_selected_window_resolves_real_canonical_backend_order():
    registry_path = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json")
    registry = json.loads(registry_path.read_text())
    features = copy.deepcopy(next(
        item["features"] for item in registry["reference_profiles"]
        if item["name"] == "Small digital IC without DFT"))
    plan = flow109.resolve_plan(features)
    window = flow109.resolve_execution_window(plan, "D31", "D32")
    assert [row["id"] for row in window["resolved_rows"]] == ["D31", "D32"]
    assert window["dispatch_kind"] == "canonical_backend_window"
    assert (window["native_entry_step"], window["native_exit_step"]) == ("15", "15.5ic")
    assert window["resolved_rows"][1]["data_deps"][0]["step"] == "D31"
    assert "D31" in window["resolved_rows"][1]["acceptance_deps"]


def test_window_refuses_unimplemented_required_row_and_reverse():
    plan = flow109.resolve_plan(_profile())
    with pytest.raises(flow109.Flow109Error, match=r"PRODUCER_UNIMPLEMENTED.*D34"):
        flow109.resolve_execution_window(plan, "D31", "D35")
    with pytest.raises(flow109.Flow109Error, match="WINDOW_REVERSED"):
        flow109.resolve_execution_window(plan, "D32", "D31")


def test_front_door_preserves_one_row_and_translates_bounded_window(tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    plan, context, registry = _window_fixture(tmp_path, monkeypatch)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "features": plan["features"], "runtime_tool_uses": context["runtime_tool_uses"],
        "qualification_registry": "qualifications.json"}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D31", exit_step="D32")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("15", "15.5ic")
    request = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
    assert flow109.validate_execution_context(request) == context
    immutable = Path(os.environ[flow109.ATTEMPT_ENV]) / "request.json"
    assert immutable.is_file()
    assert json.loads(immutable.read_text())["flow109_acceptance"] == "NOT_MEASURED"


def test_canonical_window_missing_inventory_refuses_before_attempt(tmp_path):
    runner = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "vibe_ic_one_shot_runner.py")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "features": _profile(), "runtime_tool_uses": [],
        "qualification_registry": "qualifications.json"}))
    env = dict(os.environ)
    env.pop(flow109.CONTEXT_ENV, None)
    env.pop(flow109.ATTEMPT_ENV, None)
    completed = subprocess.run([
        sys.executable, str(runner), str(tmp_path), "--flow", "109",
        "--flow109-manifest", str(manifest), "--entry-step", "D31",
        "--exit-step", "D32", "--route", "ic", "--no-dashboard",
    ], capture_output=True, text=True, env=env, timeout=60)
    assert completed.returncode == 2
    assert "FLOW109_WINDOW_USE_MISMATCH" in completed.stderr
    assert not (tmp_path / "reports/flow109/attempts").exists()


@pytest.mark.parametrize("status", ["MISSING", "FAIL", "STALE", "UNSUPPORTED"])
def test_second_row_refusal_is_named_and_stops_before_launch(tmp_path, monkeypatch, status):
    _, context, registry = _window_fixture(tmp_path, monkeypatch)
    second_ids = {use["use_id"] for use in context["resolved_rows"][1]["tool_uses"]}
    for record in registry["uses"]:
        if record["use_id"] in second_ids:
            record["status"] = status
    (tmp_path / "qualifications.json").write_text(json.dumps(registry))
    first = flow109.component_context(context, native_step_id="15")
    assert admission.require_launch_admission(
        tmp_path, "15", {"flow109_context": context})["status"] == "PASS"
    with pytest.raises(admission.AdmissionRefusal, match="QUALIFICATION_" + status) as refused:
        admission.require_launch_admission(
            tmp_path, "15.5ic", {"flow109_context": context})
    assert refused.value.report["native_started"] is False
    assert first["requested_step"] == "D31"


def test_consumed_identity_is_revalidated_between_rows(tmp_path, monkeypatch):
    _, context, _ = _window_fixture(tmp_path, monkeypatch)
    assert admission.require_launch_admission(
        tmp_path, "15", {"flow109_context": context})["status"] == "PASS"
    second = flow109.component_context(context, native_step_id="15.5ic")
    Path(second["runtime_tool_uses"][0]["config"]["path"]).write_text("changed")
    with pytest.raises(admission.AdmissionRefusal, match="QUALIFICATION_STALE") as refused:
        admission.require_launch_admission(
            tmp_path, "15.5ic", {"flow109_context": context})
    assert refused.value.report["native_started"] is False


@pytest.mark.parametrize(
    "statuses, expected",
    [(["PASS", "PASS"], "PASS"), (["FAIL"], "FAIL"), (["PASS"], "NOT_MEASURED")],
)
def test_terminal_receipt_is_immutable_and_never_delivery_accepts(
        tmp_path, monkeypatch, statuses, expected):
    _, context, _ = _window_fixture(tmp_path, monkeypatch)
    request = tmp_path / "context.json"
    request.write_text(json.dumps(context))
    attempt = flow109._new_attempt(tmp_path, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    native = ("15", "15.5ic")
    for index, status in enumerate(statuses):
        receipt = tmp_path / "reports/phase3/default_steps" / native[index] / "backend_result.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"verdict": status}))
    canonical = [{"status": status, "detail": "measured-" + status,
                  "extras": {"step_id": native[index]}}
                 for index, status in enumerate(statuses)]
    report = {"bounded": True, "steps": [{"extras": {"canonical_steps": canonical}}]}
    result = flow109.finish_native_window(tmp_path, report)
    assert result["component_status"] == expected
    assert result["flow109_acceptance"] == result["whole_flow_acceptance"] == "NOT_MEASURED"
    assert result["delivery_accepted"] is False
    assert [item["step_id"] for item in result["components"]] == ["D31", "D32"]
    if len(statuses) == 1:
        assert result["components"][1]["component_status"] == "NOT_MEASURED"
        expected_reason = ("not executed" if statuses[0] == "FAIL"
                           else "canonical row result absent")
        assert expected_reason in result["components"][1]["reason"]
    with pytest.raises(FileExistsError):
        flow109.finish_native_window(tmp_path, report)


def test_selected_row_native_not_applicable_is_not_laundered_to_pass(tmp_path, monkeypatch):
    _, context, _ = _window_fixture(tmp_path, monkeypatch)
    request = tmp_path / "context.json"
    request.write_text(json.dumps(context))
    attempt = flow109._new_attempt(tmp_path, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    report = {"steps": [{"extras": {"canonical_steps": [
        {"status": "NOT_APPLICABLE", "detail": "native N/A",
         "extras": {"step_id": "15"}}]}}]}
    result = flow109.finish_native_window(tmp_path, report)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["components"][0]["component_status"] == "NOT_MEASURED"
    assert "cannot inherit native NOT_APPLICABLE" in result["components"][0]["reason"]
