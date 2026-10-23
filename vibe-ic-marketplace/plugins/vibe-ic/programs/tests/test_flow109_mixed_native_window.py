"""Source controls for a selected adapter-to-backend Flow109 window.

These controls do not run EDA and do not claim benchmark, Flow109, or whole-IC
acceptance.  The existing D34 and D35 owners remain responsible for native
input, source, producer, and consumer evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS.parent))

import flow109
import flow109_clock_plan as clock
from programs.tests._route_fixture import stage_owner_route


@pytest.fixture(autouse=True)
def _isolate_flow109_window_environment(monkeypatch):
    # The production front door installs these directly; restore absent or
    # prior values when pytest reuses this worker for another native owner.
    for name in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV):
        monkeypatch.setenv(name, os.environ.get(name, ""))
        monkeypatch.delenv(name)


def _profile():
    return next(item["features"] for item in flow109.load_registry()["reference_profiles"]
                if item["name"] == "Small digital IC without DFT")


def _request(project: Path, extra=None):
    project.mkdir(exist_ok=True)
    stage_owner_route(project, "ic")
    manifest = project / "manifest.json"
    manifest.write_text(json.dumps({"features": _profile(), **(extra or {})}))
    args = SimpleNamespace(
        flow="109", flow109_manifest=manifest, flow109_plan_only=False,
        execution_mode="default", entry_step="D34", exit_step="D35")
    return args


def _component(step, status, context):
    return {
        "schema": "vibeic.flow109.clock-plan-component.v1",
        "step_id": step,
        "native_step_id": "16",
        "component_status": status,
        "reason": "controlled-" + status.lower(),
        "native_started": status == "PASS",
        "context_sha256": context["context_sha256"],
        "flow109_acceptance": "NOT_MEASURED",
        "whole_flow_acceptance": "NOT_MEASURED",
    }


def test_d34_d35_resolution_changes_from_refusal_to_selected_sequence():
    plan = flow109.resolve_plan(_profile())
    try:
        observed = flow109.resolve_execution_window(plan, "D34", "D35")[
            "dispatch_kind"]
    except flow109.Flow109Error as exc:
        observed = exc.code
    assert observed == "selected_native_sequence", observed


@pytest.mark.parametrize("backend_status", ["PASS", "FAIL"])
def test_selected_d34_d35_keeps_both_existing_owners_and_backend_value(
        tmp_path, monkeypatch, backend_status):
    observed = []

    def existing_clock_owner(project, context):
        observed.append(context)
        return _component("D34", "PASS", context)

    monkeypatch.setattr(clock, "execute", existing_clock_owner)
    args = _request(tmp_path)
    assert flow109.prepare_front_door(args, tmp_path) is None
    assert (args.entry_step, args.exit_step) == ("17", "17")
    assert len(observed) == 1
    assert observed[0]["requested_step"] == "D34"
    assert observed[0]["native_step_id"] == "flow109.D34"

    context = json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text())
    assert context["dispatch_kind"] == "selected_native_sequence"
    assert [row["id"] for row in context["resolved_rows"]] == ["D34", "D35"]
    assert flow109.source_owned_native_admission(context)["native_step_id"] == [
        "flow109.D34", "17"]
    admission = json.loads((tmp_path / "reports/flow109/admission.json").read_text())
    assert admission["qualification_status"] == "NOT_CLAIMED"

    receipt = tmp_path / "reports/phase3/default_steps/17/backend_result.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"verdict": backend_status}))
    report = {"bounded": True, "steps": [{"extras": {"canonical_steps": [{
        "status": backend_status, "detail": "controlled backend " + backend_status,
        "extras": {"step_id": "17"}}]}}]}
    result = flow109.finish_native_window(tmp_path, report)
    assert result["component_status"] == backend_status
    assert [item["component_status"] for item in result["components"]] == [
        "PASS", backend_status]
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert result["whole_flow_acceptance"] == "NOT_MEASURED"
    assert result["delivery_accepted"] is False


def test_actual_d34_missing_sdc_stops_before_d35_backend(tmp_path, monkeypatch):
    (tmp_path / "phase3/stage3/pnr").mkdir(parents=True)
    (tmp_path / "phase3/stage3/pnr/floorplan.def").write_text("VERSION 5.8 ;\n")
    (tmp_path / "phase1/generated_docs").mkdir(parents=True)
    (tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").write_text("{}\n")
    args = _request(tmp_path)
    assert flow109.prepare_front_door(args, tmp_path) == 2
    assert (args.entry_step, args.exit_step) == ("D34", "D35")
    attempt = Path(os.environ[flow109.ATTEMPT_ENV])
    result = json.loads((attempt / "result.json").read_text())
    assert result["component_status"] == "NOT_MEASURED"
    assert [item["component_status"] for item in result["components"]] == [
        "NOT_MEASURED", "NOT_MEASURED"]
    assert result["components"][0]["reason"] == "D34_SDC_ABSENT"
    assert result["components"][1]["reason"] == "not executed: an earlier row stopped"
    assert not (tmp_path / "reports/phase3/default_steps/17/backend_result.json").exists()


def test_failed_first_owner_cannot_dispatch_later_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(clock, "execute",
                        lambda project, context: _component("D34", "FAIL", context))
    args = _request(tmp_path)
    assert flow109.prepare_front_door(args, tmp_path) == 1
    assert (args.entry_step, args.exit_step) == ("D34", "D35")
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / "result.json").read_text())
    assert [item["component_status"] for item in result["components"]] == [
        "FAIL", "NOT_MEASURED"]
    assert not (tmp_path / "reports/phase3/default_steps/17/backend_result.json").exists()


def test_arbitrary_mixed_owner_crossing_remains_unsupported():
    plan = flow109.resolve_plan(_profile())
    row = next(item for item in plan["rows"] if item["id"] == "D35")
    row["profile"]["dispatch"] = {
        "kind": "canonical_owner_window", "native_step_id": "17",
        "owner_runner": "phase3_one_shot_runner",
        "owner_entry_step": "17", "owner_exit_step": "17"}
    with pytest.raises(flow109.Flow109Error, match="FLOW109_WINDOW_DISPATCH_UNSUPPORTED"):
        flow109.resolve_execution_window(plan, "D34", "D35")


def test_explicit_qualification_claim_stays_on_strict_inventory_path(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        clock, "execute", lambda *args: pytest.fail("native owner must not start"))
    args = _request(tmp_path, {
        "runtime_tool_uses": [], "qualification_registry": "missing.json"})
    with pytest.raises(flow109.Flow109Error, match="FLOW109_WINDOW_USE_MISMATCH"):
        flow109.prepare_front_door(args, tmp_path)
    assert not (tmp_path / "reports/flow109/attempts").exists()
