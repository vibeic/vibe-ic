"""Actual D62 runtime metric binding and fail-closed controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

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
    init.write_text("read_lef tech.lef\nread_def routed.def\n"
                    "create_obstruction -layer M1 -region {4 4 6 6} -fill\n"
                    "write_db input.odb\n")
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
        "limits": {"M1": {"min": 0.30, "max": 0.70}}, "units": "ratio",
        "scope": {"kind": "tiled_windows", "area": "core",
                  "window_um": 10.0, "step_um": 5.0,
                  "minimum_core_dimensions_um": [20.0, 20.0]},
        "rules_sha256": manifest["rules"]["sha256"],
        "pdk_sha256": manifest["pdk"]["sha256"]}))
    _put(project, "requirements/base_43/fill_keepout_violations.json", json.dumps({
        "schema": metrics.AUTHORITY_SCHEMA,
        "approval": {"status": "APPROVED", "authority": "requirements_owner",
                     "source_reference": owner},
        "expected": 0, "unit": "count",
        "checker_semantics": "opendb_fill_obstruction_overlap",
        "validated_absence": False,
        "rules_sha256": manifest["rules"]["sha256"],
        "pdk_sha256": manifest["pdk"]["sha256"]}))
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


def _mutate_filled_odb(prepared: dict, attempt: Path, mode: str) -> dict:
    """Create an actual defective ODB while retaining the non-fill subject."""
    script = attempt / f"{mode}-defect.tcl"
    action = ("set fills [$block getFills]\n"
              "foreach fill [lrange $fills 1 end] { odb::dbFill_destroy $fill }\n"
              if mode == "density" else
              "odb::dbFill_create $block 0 0 $layer 4500 4500 5500 5500\n")
    script.write_text(
        f"read_db {attempt / 'filled.odb'}\n"
        "set block [ord::get_db_block]\n"
        "set layer [[ord::get_db_tech] findLayer M1]\n" + action +
        f"write_db {attempt / 'mutated.odb'}\n"
        f"write_def {attempt / 'filled.def'}\n"
        f"write_def {attempt / 'readback.def'}\n"
        f"set out [open {attempt / 'mutation.census'} w]\n"
        "puts $out [llength [$block getFills]]\nclose $out\n")
    proc = subprocess.run([str(prepared["executable"]), "-no_init", "-exit", str(script)],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (attempt / "mutated.odb").replace(attempt / "filled.odb")
    (attempt / "mutation.census").unlink()
    script.unlink()
    proof = fill._geometry_proof(attempt / "before.def", attempt / "filled.def",
                                 attempt / "readback.def")
    (attempt / "producer.census").write_text(
        f"BEFORE {proof['fill_count_before']} AFTER {proof['fill_count_after']}\n")
    (attempt / "consumer.census").write_text(
        f"BEFORE {proof['fill_count_after']} AFTER {proof['fill_count_after']}\n")
    return proof


def test_registry_declares_only_genuinely_supported_d62_bindings():
    registry = flow109.load_registry()
    features = next(p["features"] for p in registry["reference_profiles"]
                    if p["name"] == "Small digital IC without DFT")
    row = flow109.resolve_step(flow109.resolve_plan(features), "D62")
    by_id = {item["id"]: item["status"] for item in row["obligations"]}
    assert row["profile"]["dispatch"]["flow109_metrics_status"] == "IMPLEMENTED_D62_RUNTIME"
    assert row["metric_acceptance_status"] == "IMPLEMENTED_D62_RUNTIME"
    assert by_id == {
        "base_43.fill_density_rules": "IMPLEMENTED_D62_RUNTIME_BINDING",
        "base_43.fill_keepout_violations": "IMPLEMENTED_D62_RUNTIME_BINDING",
        "base_43.fill_geometry_identity": "IMPLEMENTED_D62_RUNTIME_BINDING"}
    assert set(metrics.D62_BINDINGS) == {
        "base_43.fill_density_rules", "base_43.fill_keepout_violations",
        "base_43.fill_geometry_identity"}


def test_actual_native_receipt_positive_missing_stale_and_provider_only_controls(tmp_path):
    _, context = _case(tmp_path)
    run = _run(tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr
    report, observed_context = _report_context(tmp_path)
    assert report["component_status"] == "PASS"
    first = report["metric_acceptance"]
    assert first["status"] == "NOT_MEASURED"
    assert {item["id"]: item["status"] for item in first["obligations"]} == {
        "base_43.fill_density_rules": "PASS",
        "base_43.fill_keepout_violations": "PASS",
        "base_43.fill_geometry_identity": "NOT_MEASURED"}
    density = next(item for item in first["obligations"]
                   if item["id"] == "base_43.fill_density_rules")
    assert density["measurement"]["value"]["violations"] == 0
    assert density["measurement"]["value"]["foundry_deck_signoff"] == "NOT_MEASURED"
    keepout = next(item for item in first["obligations"]
                   if item["id"] == "base_43.fill_keepout_violations")
    assert keepout["measurement"]["checked_fill_obstructions"] == 1
    assert keepout["measurement"]["value"] == 0
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
    assert by_id["base_43.fill_density_rules"]["status"] == "PASS"
    assert by_id["base_43.fill_keepout_violations"]["status"] == "PASS"
    assert positive["status"] == "PASS" and positive["delivery_blocked"] is False

    rerun = _run(tmp_path)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    report, observed_context = _report_context(tmp_path)
    integrated = {item["id"]: item for item in report["metric_acceptance"]["obligations"]}
    assert integrated["base_43.fill_geometry_identity"]["status"] == "PASS"
    assert report["metric_acceptance_status"] == "PASS"

    owner = tmp_path / "input/approved-d62-requirements.md"
    approved = owner.read_text()
    owner.write_text("changed after approval\n")
    stale_authority = metrics.accept_d62(tmp_path, observed_context, report)
    stale_by_id = {item["id"]: item for item in stale_authority["obligations"]}
    assert stale_by_id["base_43.fill_density_rules"]["reason"] == "METRIC_AUTHORITY_STALE"
    assert stale_by_id["base_43.fill_keepout_violations"]["reason"] == "METRIC_AUTHORITY_STALE"
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


@pytest.mark.parametrize('authority', [
    'requirements/base_43/fill_density_rules.json',
    'requirements/base_43/fill_keepout_violations.json'])
def test_native_fill_handoff_without_additional_audit_documents(tmp_path, authority):
    _, context = _case(tmp_path)
    (tmp_path / authority).unlink()
    result = fill.execute(tmp_path, context)
    assert result['native_started'] is True
    assert result['component_status'] == 'PASS'
    assert result['measurements']['nonfill_geometry_preserved'] is True
    assert result['measurements']['odb_readback_matches'] is True
    assert result['handoff']['odb'] == result['outputs']['filled.odb']
    assert 'density.csv' not in result['outputs']
    assert result['metric_acceptance_status'] == 'NOT_MEASURED'
    assert result['metric_acceptance']['delivery_blocked'] is True
    assert result['flow109_acceptance'] == 'NOT_MEASURED'
    assert all(item['status'] != 'PASS'
               for item in result['metric_acceptance']['obligations'])


def test_actual_native_density_defect_is_measured_fail(tmp_path, monkeypatch):
    _, context = _case(tmp_path)
    original = fill._native_fill

    def sparse_after_native(project, prepared, attempt, before_launch):
        original(project, prepared, attempt, before_launch)
        return _mutate_filled_odb(prepared, attempt, "density")

    monkeypatch.setattr(fill, "_native_fill", sparse_after_native)
    result = fill.execute(tmp_path, context)
    assert result["component_status"] == "PASS"
    assert result["metric_acceptance_status"] == "FAIL"
    by_id = {item["id"]: item for item in result["metric_acceptance"]["obligations"]}
    assert by_id["base_43.fill_density_rules"]["status"] == "FAIL"
    assert by_id["base_43.fill_density_rules"]["measurement"]["value"]["violations"] > 0
    assert by_id["base_43.fill_keepout_violations"]["status"] == "PASS"
    assert "UNDER" in (tmp_path / result["outputs"]["density.csv"]["path"]).read_text()


def test_actual_native_keepout_defect_is_measured_fail(tmp_path, monkeypatch):
    _, context = _case(tmp_path)
    original = fill._native_fill

    def overlap_after_native(project, prepared, attempt, before_launch):
        original(project, prepared, attempt, before_launch)
        return _mutate_filled_odb(prepared, attempt, "keepout")

    monkeypatch.setattr(fill, "_native_fill", overlap_after_native)
    result = fill.execute(tmp_path, context)
    assert result["component_status"] == "PASS"
    assert result["metric_acceptance_status"] == "FAIL"
    by_id = {item["id"]: item for item in result["metric_acceptance"]["obligations"]}
    assert by_id["base_43.fill_keepout_violations"]["status"] == "FAIL"
    measured = by_id["base_43.fill_keepout_violations"]["measurement"]
    assert measured["checked_fill_obstructions"] == 1
    assert measured["value"] == 1
    assert by_id["base_43.fill_density_rules"]["status"] == "PASS"
