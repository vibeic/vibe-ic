"""Exercise canonical recovery through the real CLI, without native qualification."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import flow109


def _invoke(tmp_path, request, *, route="ic", plan_only=False):
    project = tmp_path / "project"
    project.mkdir()
    features = copy.deepcopy(next(
        row["features"] for row in flow109.load_registry()["reference_profiles"]
        if row["name"] == "Small digital IC without DFT"))
    manifest = tmp_path / "selection.json"
    manifest.write_text(json.dumps({"features": features}))
    request_path = tmp_path / "resume.json"
    request_path.write_text(json.dumps(request))
    programs = Path(os.environ.get(
        "VIBEIC_TEST_PROGRAMS", Path(__file__).resolve().parents[1]))
    argv = [sys.executable, str(programs / "vibe_ic_one_shot_runner.py"),
            str(project), "--flow109-manifest", str(manifest),
            "--route", route, "--execution-mode", "default", "--no-dashboard"]
    argv += ["--flow109-plan-only"] if plan_only else [
        "--resume-request", str(request_path)]
    env = {k: v for k, v in os.environ.items()
           if k not in (flow109.CONTEXT_ENV, flow109.ATTEMPT_ENV,
                        "VIBE_IC_RUNNER_LOCK_TOKEN")}
    result = subprocess.run(argv, capture_output=True, text=True,
                            env=env, timeout=60)
    (tmp_path / "public-result.json").write_text(json.dumps({
        "argv": argv, "rc": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr}, indent=2))
    plans = sorted((project / "reports/orchestrator").glob(
        "minimal_resume_plan-*.json"))
    return project, result, [json.loads(p.read_text()) for p in plans]


def _request(**kwargs):
    return {"schema": "vibeic/minimal-resume-request/1",
            "consumer_step": "D09", **kwargs}


def _decision(result, plans):
    return (plans[-1]["status"] if plans else
            result.stderr.split("REFUSED: ", 1)[-1].split(":", 1)[0])


@pytest.mark.parametrize("steps,native_exit", [(["D09"], "4"), (["D09", "D10"], "1")])
def test_public_explicit_resume_reaches_only_current_owner_window(tmp_path, steps, native_exit):
    project, result, plans = _invoke(tmp_path, _request(
        explicit_rerun_steps=steps, reason="owner requested bounded RTL control"))
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(plans) == 1, result.stdout + result.stderr
    assert plans[0]["status"] == "READY"
    assert plans[0]["execution_steps"] == steps
    owner = json.loads((project / "reports/flow109/owner_route.json").read_text())
    assert owner["owner_runner"] == "design_one_shot_runner"
    assert owner["entry_step"] == "1"
    assert owner["exit_step"] == native_exit
    assert "FLOW109_WINDOW_REQUIRED" not in result.stderr
    # An empty control project owes real inputs; reaching its owner is not PASS.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "20 declared input(s) ABSENT" in result.stderr
    row_path = project / "reports/flow109/default_rows/D09.json"
    if steps == ["D09"]:
        row = json.loads(row_path.read_text())
        assert row["component_status"] == row["default_row_status"] == "NOT_MEASURED"
        assert row["whole_flow_acceptance"] == "NOT_MEASURED"
        assert row["completed"] is False
    else:
        assert not row_path.exists()


def test_current_plan_reuses_native_bytes_without_rewriting_original_receipt(tmp_path):
    import hashlib
    import importlib.util

    programs = Path(os.environ.get(
        "VIBEIC_TEST_PROGRAMS", Path(__file__).resolve().parents[1]))
    spec = importlib.util.spec_from_file_location(
        "resume_source_under_test", programs / "vibe_ic_one_shot_runner.py")
    front = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(front)

    features = next(row["features"] for row in flow109.load_registry()["reference_profiles"]
                    if row["name"] == "Small digital IC without DFT")
    selected = flow109.resolve_plan(features)
    # A planner source control: one retained native checkpoint, no IC proof.
    row = next(row for row in selected["rows"] if row["id"] == "D09")
    selected["rows"] = [row]
    row["data_deps"] = []
    row["acceptance_deps"] = []
    source = tmp_path / "source.txt"
    output = tmp_path / "output.txt"
    source.write_text("approved neutral input")
    output.write_text("retained neutral output")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    folder = tmp_path / "steps/phase/stage/native"
    folder.mkdir(parents=True)
    receipt = folder / "outputs.json"
    receipt.write_text(json.dumps({
        "id": "1", "canonical_pass": True, "status": "PASS",
        "inputs": {"source.txt": {"sha256": digest(source)}},
        "outputs": [{"rel": "output.txt", "sha256": digest(output)}]}))
    (tmp_path / "steps/latest_pass.json").write_text(json.dumps({"steps": {
        "1": {"folder": "phase/stage/native"}}}))
    original = receipt.read_bytes()
    plan = front._minimal_resume_plan(tmp_path, _request(
        revalidate_consumer=True), flow_plan=selected)
    assert plan["status"] == "READY"
    assert plan["execution_steps"] == plan["reused_checkpoints"] == ["D09"]
    assert plan["checkpoint_observations"][0]["native_step_id"] == "1"
    assert receipt.read_bytes() == original
    source.write_text("changed neutral input")
    plan = front._minimal_resume_plan(tmp_path, _request(), flow_plan=selected)
    assert plan["execution_steps"] == ["D09"]
    assert plan["reused_checkpoints"] == []
    assert "input source.txt changed" == plan["reason"]
    assert receipt.read_bytes() == original


def test_public_automatic_resume_refuses_unknown_retained_inputs_before_dispatch(tmp_path):
    project, result, plans = _invoke(tmp_path, _request(revalidate_consumer=True))
    assert _decision(result, plans) == "UNRESOLVED"
    assert len(plans) == 1, result.stdout + result.stderr
    assert plans[0]["status"] == "UNRESOLVED"
    assert plans[0]["execution_steps"] == []
    assert any("D09" in item for item in plans[0]["unknown_impact"])
    assert result.returncode == 2
    assert not (project / "reports/flow109/owner_route.json").exists()
    assert not (project / "reports/flow109/attempts").exists()


@pytest.mark.parametrize("steps", [["D09", "D13"], ["D13", "D09"]])
def test_public_resume_cannot_expand_sparse_or_reversed_window(tmp_path, steps):
    project, result, plans = _invoke(tmp_path, _request(explicit_rerun_steps=steps))
    assert _decision(result, plans) == "UNRESOLVED"
    assert len(plans) == 1, result.stdout + result.stderr
    assert plans[0]["status"] == "UNRESOLVED"
    assert plans[0]["execution_steps"] == []
    assert result.returncode == 2
    assert not (project / "reports/flow109/attempts").exists()


def test_public_resume_rejects_internal_step_ids(tmp_path):
    project, result, plans = _invoke(tmp_path, {
        "schema": "vibeic/minimal-resume-request/1", "consumer_step": "1",
        "explicit_rerun_steps": ["1"]})
    assert result.returncode == 2
    assert "unknown consumer_step '1'" in result.stderr
    assert plans == []
    assert not (project / "reports/flow109/attempts").exists()


def test_public_resume_keeps_manifest_route_admission(tmp_path):
    project, result, _ = _invoke(tmp_path, _request(
        explicit_rerun_steps=["D09"]), route="ip")
    assert result.returncode == 2
    assert "FLOW109_ROUTE_CONFLICT" in result.stderr
    assert not (project / "reports/flow109/attempts").exists()


def test_public_plan_only_remains_a_plan(tmp_path):
    project, result, plans = _invoke(tmp_path, _request(), plan_only=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert plans == []
    plan = json.loads((project / "reports/flow109/plan.json").read_text())
    assert plan["runtime_verdict"] == "NOT_MEASURED"
    assert not (project / "reports/flow109/attempts").exists()
