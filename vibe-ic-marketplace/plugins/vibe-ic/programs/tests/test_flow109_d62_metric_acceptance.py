"""Actual D62 runtime metric binding and fail-closed controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import flow109
import flow109_admission as admission
import flow109_density_fill as fill
import flow109_metric_acceptance as metrics
from programs.tests._hostpaths import require_repo


def _put(project: Path, relative: str, data: str) -> dict:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _identity() -> dict:
    return {key: {"identity": key} for key in
            ("producer", "checker", "tool_execution", "consumed_inputs",
             "requirements", "configuration")}


def _case(project: Path) -> tuple[dict, dict]:
    project.mkdir(parents=True, exist_ok=True)
    fixtures = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                            "tests", "fixtures", "flow109_density_fill")
    for name in ("tech.lef", "routed.def", "rules.json"):
        target = project / "input" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixtures / name, target)
    executable = Path(shutil.which("openroad") or "")
    assert executable.is_file(), "Run this D62 control in the pinned EDA image"
    init = project / "input/initialize.tcl"
    init.write_text("read_lef tech.lef\nread_def routed.def\nwrite_db input.odb\n")
    proc = subprocess.run([str(executable), "-no_init", "-exit", str(init)],
        cwd=project / "input", capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    manifest = {"schema": fill.SCHEMA,
                "input_odb": fill._record(project, project / "input/input.odb"),
                "rules": fill._record(project, project / "input/rules.json"),
                "pdk": _put(project, "input/pdk.json", '{"pdk":"fixture-only"}\n')}
    _put(project, fill.INPUT, json.dumps(manifest))
    config = _put(project, "input/d62-config.json", json.dumps(
        {"schema": fill.SCHEMA, "operation": "density_fill", "area": "core"}))
    features = next(p["features"] for p in flow109.load_registry()["reference_profiles"]
                    if p["name"] == "Small digital IC without DFT")
    plan = flow109.resolve_plan(features)
    expected = flow109.resolve_step(plan, "D62")["tool_uses"][0]
    exe = fill._record(project, executable)
    identity = {"use_id": expected["use_id"], "tool_id": "openroad",
                "version": subprocess.run([str(executable), "-version"], capture_output=True,
                    text=True, timeout=10).stdout.strip(),
                "build_sha256": exe["sha256"], "executable": exe,
                "config": config, "pdk": manifest["pdk"], "deck": manifest["rules"],
                "corner": "not-applicable-to-density-fill",
                "semantics": {"purpose": expected["purpose"],
                              "native_steps": expected["native_steps"],
                              "operation_sources": fill.operation_sources()}}
    evidence = _put(project, "input/qualification-control.json",
                    '{"scope":"developer contract control; not PDK qualification"}\n')
    record = {"use_id": expected["use_id"], "status": "QUALIFIED",
              "identity": identity, "reference_evidence": [evidence]}
    _put(project, "qualifications.json", json.dumps(
        {"schema": "vibeic.flow109.qualifications.v1", "uses": [record]}))
    run_manifest = {"features": features, "qualification_registry": "qualifications.json",
                    "runtime_tool_uses": [{**identity,
                        "qualification_sha256": admission.canonical_sha(record)}]}
    _put(project, "manifest.json", json.dumps(run_manifest))
    owner = _put(project, "input/approved-d62-requirements.md",
                 "Approved D62 fixture limits and adopted geometry.\n")
    _put(project, "requirements/base_43/fill_density_rules.json", json.dumps({
        "schema": metrics.AUTHORITY_SCHEMA,
        "approval": {"status": "APPROVED", "authority": "requirements_owner",
                     "source_reference": owner},
        "limits": {"min": 0.0, "max": 1.0}, "units": "ratio",
        "rules_sha256": manifest["rules"]["sha256"]}))
    context = flow109.execution_context(plan, "D62", "D62",
        runtime_tool_uses=run_manifest["runtime_tool_uses"],
        qualification_registry="qualifications.json")
    return run_manifest, context


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(fill.HERE / "vibe_ic_one_shot_runner.py"),
        str(project), "--flow", "109", "--flow109-manifest", str(project / "manifest.json"),
        "--entry-step", "D62", "--exit-step", "D62", "--route", "ic", "--no-dashboard"],
        capture_output=True, text=True, timeout=60)


def _report_context(project: Path) -> tuple[dict, dict]:
    report = json.loads((project / "reports/flow109/components/D62.json").read_text())
    request = next((project / "reports/flow109/requests").glob("*.json"))
    return report, json.loads(request.read_text())


def _adopt(project: Path, reference: dict) -> None:
    source = fill._record(project, project / "input/approved-d62-requirements.md")
    _put(project, "adopted/base_43/fill_geometry_identity.json", json.dumps({
        "schema": "vibeic.flow109.adopted-reference.v1",
        "approval": {"status": "APPROVED", "authority": "layout_owner",
                     "source_reference": source},
        "reference": reference, "reference_identity": _identity()}))


def test_registry_declares_only_genuinely_supported_d62_bindings():
    registry = flow109.load_registry()
    features = next(p["features"] for p in registry["reference_profiles"]
                    if p["name"] == "Small digital IC without DFT")
    row = flow109.resolve_step(flow109.resolve_plan(features), "D62")
    by_id = {item["id"]: item["status"] for item in row["obligations"]}
    assert row["profile"]["dispatch"]["flow109_metrics_status"] == "PARTIAL_RUNTIME_BINDING"
    assert row["metric_acceptance_status"] == "PARTIAL_D62_RUNTIME"
    assert by_id == {
        "base_43.fill_density_rules": "AUTHORITY_BOUND_MEASUREMENT_NOT_MEASURED",
        "base_43.fill_keepout_violations": "UNIMPLEMENTED_METRIC_BINDING",
        "base_43.fill_geometry_identity": "IMPLEMENTED_D62_RUNTIME_BINDING"}
    assert set(metrics.D62_BINDINGS) == {
        "base_43.fill_density_rules", "base_43.fill_geometry_identity"}


def test_actual_native_receipt_positive_missing_stale_and_provider_only_controls(tmp_path):
    _, context = _case(tmp_path)
    run = _run(tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr
    report, observed_context = _report_context(tmp_path)
    assert report["component_status"] == "PASS"
    first = report["metric_acceptance"]
    assert first["status"] == "NOT_MEASURED"
    assert {item["id"]: item["status"] for item in first["obligations"]} == {
        "base_43.fill_density_rules": "NOT_MEASURED",
        "base_43.fill_keepout_violations": "UNIMPLEMENTED_METRIC_BINDING",
        "base_43.fill_geometry_identity": "NOT_MEASURED"}
    density = next(item for item in first["obligations"]
                   if item["id"] == "base_43.fill_density_rules")
    assert density["reason"] == "D62_DENSITY_VALUE_NOT_MEASURED"
    measured = metrics._d62_measurement(tmp_path, report, observed_context)
    assert measured["status"] == "MEASURED"
    assert set(measured["value"]["outputs"]) == {
        "filled.odb", "before.def", "filled.def", "readback.def",
        "producer.census", "consumer.census"}
    assert report["handoff"]["odb"] == report["outputs"]["filled.odb"]

    _adopt(tmp_path, measured["value"])
    positive = metrics.accept_d62(tmp_path, observed_context, report)
    by_id = {item["id"]: item for item in positive["obligations"]}
    assert by_id["base_43.fill_geometry_identity"]["status"] == "PASS"
    assert by_id["base_43.fill_density_rules"]["status"] == "NOT_MEASURED"
    assert by_id["base_43.fill_keepout_violations"]["status"] == "UNIMPLEMENTED_METRIC_BINDING"
    assert positive["status"] == "NOT_MEASURED" and positive["delivery_blocked"] is True

    rerun = _run(tmp_path)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    report, observed_context = _report_context(tmp_path)
    integrated = {item["id"]: item for item in report["metric_acceptance"]["obligations"]}
    assert integrated["base_43.fill_geometry_identity"]["status"] == "PASS"
    assert report["metric_acceptance_status"] == "NOT_MEASURED"

    owner = tmp_path / "input/approved-d62-requirements.md"
    approved = owner.read_text()
    owner.write_text("changed after approval\n")
    stale_authority = metrics.accept_d62(tmp_path, observed_context, report)
    assert any(item.get("reason") == "METRIC_AUTHORITY_STALE"
               for item in stale_authority["obligations"])
    owner.write_text(approved)

    filled = tmp_path / report["outputs"]["filled.def"]["path"]
    filled.write_text(filled.read_text() + "# stale\n")
    stale_output = metrics.accept_d62(tmp_path, observed_context, report)
    geometry = next(item for item in stale_output["obligations"]
                    if item["id"] == "base_43.fill_geometry_identity")
    assert geometry["status"] == "NOT_MEASURED"

    provider_only = metrics.accept_d62(tmp_path, context,
        {"component_status": "PASS", "inputs": report["inputs"]})
    assert provider_only["status"] == "NOT_MEASURED"
    assert all(item["status"] != "PASS" for item in provider_only["obligations"])


def test_actual_native_measured_failure_precedes_missing_reference(tmp_path, monkeypatch):
    _, context = _case(tmp_path)
    original = fill._native_fill

    def corrupt_after_native(project, prepared, attempt, before_launch):
        proof = original(project, prepared, attempt, before_launch)
        filled = attempt / "filled.def"
        text = filled.read_text()
        changed = text.replace("( 20000 20000 )", "( 20001 20000 )", 1)
        assert changed != text
        filled.write_text(changed)
        return proof

    monkeypatch.setattr(fill, "_native_fill", corrupt_after_native)
    result = fill.execute(tmp_path, context)
    assert result["component_status"] == "FAIL"
    assert result["reason"] == "D62_NONFILL_GEOMETRY_CHANGED"
    assert result["metric_acceptance_status"] == "FAIL"
    geometry = next(item for item in result["metric_acceptance"]["obligations"]
                    if item["id"] == "base_43.fill_geometry_identity")
    assert geometry["status"] == "FAIL"
    assert not (tmp_path / "reports/flow109/D62/accepted.json").exists()
