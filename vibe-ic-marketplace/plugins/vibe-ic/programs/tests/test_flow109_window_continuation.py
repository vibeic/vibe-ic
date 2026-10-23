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


def _window_fixture(project, monkeypatch, entry="D31", exit_="D32"):
    plan = flow109.resolve_plan(_profile())
    selected = [row["id"] for row in plan["rows"]]
    first, last = selected.index(entry), selected.index(exit_)
    rows = [flow109.resolve_step(plan, step)
            for step in selected[first:last + 1]]
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
        plan, entry, exit_, runtime_tool_uses=runtime,
        qualification_registry="qualifications.json")
    return plan, context, registry


def _one_row_request(project, monkeypatch, step="D38", *, spares=False):
    features = _profile()
    features["requires_spares"] = spares
    plan = flow109.resolve_plan(features)
    context = flow109.execution_context(plan, step, step)
    path = project / "reports/flow109/requests" / (context["context_sha256"] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
    return context


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


@pytest.mark.parametrize(
    "entry,exit_,native,components",
    [
        ("D77", "D78", ("37.4", "36"),
         (("signoff_metrics_aggregate",),
          ("flow_compliance_check", "tapeout_signoff_check"))),
        ("D80", "D81", ("37.5ic", "38"),
         (("tapeout_precheck", "ic_release_docs_gen"),
          ("foundry_handoff_pack_gen", "tapeout_checklist_gen"))),
    ],
)
def test_delivery_windows_route_to_existing_default_consumers(
        entry, exit_, native, components):
    import phase3_one_shot_runner as phase3
    plan = flow109.resolve_plan(_profile())
    window = flow109.resolve_execution_window(plan, entry, exit_)
    assert window["dispatch_kind"] == "canonical_backend_window"
    assert (window["native_entry_step"], window["native_exit_step"]) == native
    assert phase3._phase3_window_steps(*native) == list(native)
    assert phase3._phase3_window_sites(*native) == ["default_backend"]
    assert [row["id"] for row in window["resolved_rows"]] == [entry, exit_]
    for row, expected in zip(window["resolved_rows"], components):
        profile = row["profile"]
        assert tuple(profile["native_steps"]) == expected
        assert profile["dispatch"]["consumer"] == "execution_backend_gates.py:evaluate"
        assert profile["dispatch"]["acceptance_scope"] == "existing_native_component_only"
        assert profile["dispatch"]["flow109_metrics_status"] == "UNIMPLEMENTED"


@pytest.mark.parametrize(
    "entry,exit_,native_statuses,expected,missing_reason",
    [
        ("D77", "D78", ("PASS", "FAIL"), "FAIL", ""),
        ("D80", "D81", ("PASS",), "NOT_MEASURED", "canonical row result absent"),
    ],
)
def test_delivery_receipts_preserve_failure_and_missing_release_evidence(
        tmp_path, monkeypatch, entry, exit_, native_statuses, expected,
        missing_reason):
    _, context, _ = _window_fixture(tmp_path, monkeypatch, entry, exit_)
    request = tmp_path / "context.json"
    request.write_text(json.dumps(context))
    attempt = flow109._new_attempt(tmp_path, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(request))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    native = (context["native_entry_step"], context["native_exit_step"])
    canonical = []
    for index, status in enumerate(native_statuses):
        receipt = (tmp_path / "reports/phase3/default_steps" / native[index]
                   / "backend_result.json")
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"verdict": status}))
        canonical.append({"status": status, "detail": "native-" + status,
                          "extras": {"step_id": native[index]}})
    result = flow109.finish_native_window(
        tmp_path, {"bounded": True, "steps": [
            {"extras": {"canonical_steps": canonical}}]})
    assert result["component_status"] == expected
    assert result["delivery_accepted"] is False
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    if missing_reason:
        assert missing_reason in result["components"][-1]["reason"]


def test_clock_planning_row_reaches_registered_special_native_owner_and_reverse():
    plan = flow109.resolve_plan(_profile())
    resolved = flow109.resolve_execution_window(plan, "D34", "D34")
    assert resolved["resolved_row"]["id"] == "D34"
    assert resolved["native_step_id"] == "flow109.D34"
    context = flow109.execution_context(plan, "D34", "D34")
    admission_record = flow109.source_owned_native_admission(context)
    assert admission_record["status"] == "NOT_APPLICABLE"
    assert admission_record["qualification_status"] == "NOT_CLAIMED"
    assert admission_record["native_step_id"] == "flow109.D34"
    assert admission_record["flow109_acceptance"] == "NOT_MEASURED"
    with pytest.raises(flow109.Flow109Error, match="WINDOW_REVERSED"):
        flow109.resolve_execution_window(plan, "D32", "D31")


def test_cts_predecessor_uses_latest_selected_physical_producer(tmp_path, monkeypatch):
    _one_row_request(tmp_path, monkeypatch, spares=False)
    assert flow109.active_native_predecessor(tmp_path, "19") == {
        "row_id": "D35", "native_step_id": "17",
        "output": "phase3/stage3/pnr/placed.def"}

    _one_row_request(tmp_path, monkeypatch, spares=True)
    assert flow109.active_native_predecessor(tmp_path, "19") == {
        "row_id": "D37", "native_step_id": "18",
        "output": "phase3/stage3/pnr/post_spare.def"}


def test_cts_predecessor_rejects_stale_context(tmp_path, monkeypatch):
    context = _one_row_request(tmp_path, monkeypatch)
    path = Path(os.environ[flow109.CONTEXT_ENV])
    context["features"]["requires_spares"] = True
    path.write_text(json.dumps(context))
    with pytest.raises(flow109.Flow109Error, match="FLOW109_CONTEXT_STALE"):
        flow109.active_native_predecessor(tmp_path, "19")


def test_one_row_canonical_receipt_is_component_only(tmp_path, monkeypatch):
    context = _one_row_request(tmp_path, monkeypatch)
    receipt = tmp_path / "reports/phase3/default_steps/19/backend_result.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"verdict": "PASS"}))
    report = {"steps": [{"extras": {"canonical_steps": [
        {"status": "PASS", "detail": "current CTS consumer PASS",
         "extras": {"step_id": "19"}}]}}]}
    result = flow109.finish_native_window(tmp_path, report)
    component = json.loads((tmp_path / "reports/flow109/components/D38.json").read_text())
    assert result["component_status"] == component["component_status"] == "PASS"
    assert component["context_sha256"] == context["context_sha256"]
    assert result["flow109_acceptance"] == result["whole_flow_acceptance"] == "NOT_MEASURED"
    assert result["delivery_accepted"] is False
    assert not (tmp_path / "reports/flow109/attempts").exists()


def test_one_row_missing_canonical_receipt_cannot_pass(tmp_path, monkeypatch):
    _one_row_request(tmp_path, monkeypatch)
    report = {"steps": [{"extras": {"canonical_steps": [
        {"status": "PASS", "detail": "unbound", "extras": {"step_id": "19"}}]}}]}
    result = flow109.finish_native_window(tmp_path, report)
    assert result["component_status"] == "NOT_MEASURED"
    assert "current native PASS receipt absent" in result["components"][0]["reason"]


def test_cts_producer_binds_selected_placement_receipt_and_rejects_changed_def(
        tmp_path, monkeypatch):
    import execution_backend_producers as producers
    _one_row_request(tmp_path, monkeypatch)
    placed = tmp_path / "phase3/stage3/pnr/placed.def"
    placed.parent.mkdir(parents=True, exist_ok=True)
    placed.write_text("VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    receipt = tmp_path / "reports/phase3/default_steps/17/backend_result.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "verdict": "PASS", "producer_verdict": "PASS",
        "outputs": {"phase3/stage3/pnr/placed.def": hashlib.sha256(
            placed.read_bytes()).hexdigest()}}))
    assert producers._cts_selected_predecessor(tmp_path, "19") == "placed.def"
    placed.write_text(placed.read_text() + "# changed after acceptance\n")
    with pytest.raises(Exception, match="BACKEND_CTS_PREDECESSOR_UNBOUND"):
        producers._cts_selected_predecessor(tmp_path, "19")


def test_cts_issuer_replaces_only_unselected_spare_input(tmp_path, monkeypatch):
    import execution_policy
    _one_row_request(tmp_path, monkeypatch)
    params = {}
    execution_policy._fixed_inputs({
        "project": tmp_path, "policy": {"mode": "default"}, "registry": None,
    }, "19", parameters=params)
    declarations = params["resolved_input_manifest"]["declarations"]
    assert {"from": 17, "path": "phase3/stage3/pnr/placed.def"} in declarations
    assert {"from": 18, "path": "phase3/stage3/pnr/post_spare.def"} not in declarations
    assert {"from": 16, "path": "phase3/stage3/cts/clock_plan.json"} in declarations


def test_front_door_preserves_one_row_and_translates_bounded_window(tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        monkeypatch.delenv(name)
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


def test_source_owned_default_window_uses_existing_launch_admission_without_registry(
        tmp_path, monkeypatch):
    import _delivery_route
    assert _delivery_route.admit(tmp_path, "ic") is None
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        monkeypatch.delenv(name)
    plan = flow109.resolve_plan(_profile())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"features": plan["features"]}))
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D31", exit_step="D32")
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("15", "15.5ic")
    admission_record = json.loads(
        (tmp_path / "reports/flow109/admission.json").read_text())
    assert admission_record["status"] == "NOT_APPLICABLE"
    assert admission_record["qualification_status"] == "NOT_CLAIMED"
    assert admission_record["native_step_id"] == ["15", "15.5ic"]
    request = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
    assert admission.require_launch_admission(
        tmp_path, "15", {"flow109_context": request})["status"] == "NOT_APPLICABLE"
    assert admission.require_launch_admission(
        tmp_path, "15.5ic", {"flow109_context": request})["status"] == "NOT_APPLICABLE"


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
