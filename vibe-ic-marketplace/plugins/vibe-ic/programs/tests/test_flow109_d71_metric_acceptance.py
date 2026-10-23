"""D71 row-local metric bindings over existing native GLS evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import flow109
import flow109_final_gls as gls
import flow109_metric_acceptance as metrics


_D71_FIXTURES = Path(__file__).resolve().parent / "fixtures/flow109_d71"


def _frozen_D71_sources():
    sources = json.loads((_D71_FIXTURES / "frozen-b74-operation-sources-713.json").read_text())
    provenance = json.loads(
        (_D71_FIXTURES / "frozen-b74-operation-sources-713.provenance.json").read_text())
    return sources, provenance


def _real_D71_operation_sources():
    from execution_provider_catalog import source_closure

    programs = Path(gls.__file__).resolve().parent
    roots = {programs / "sdf_gate_sim.py", programs / "post_layout_sim_check.py"}
    closure = source_closure(roots)
    closure.update({programs / "flow109_final_gls.py", programs / "flow109_admission.py",
                    programs / "full_stack_functional_tb.py",
                    programs / "librelane_plugins/librelane_plugin_vibeic/__init__.py"})
    return {str(path.relative_to(programs.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(closure)}


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _context():
    features = next(item["features"] for item in flow109.load_registry()["reference_profiles"]
                    if item["name"] == "Small digital IC without DFT")
    return flow109.execution_context(flow109.resolve_plan(features), "D71", "D71")


def _refresh_published(project, component):
    result = component["result"]
    published = {key: copy.deepcopy(value) for key, value in result.items()
                 if key not in {"post_layout_sim_check", "results_log", "results_json"}}
    result["results_json"] = _put(project, "reports/D71/results.json", published)


def _refresh_input(project, component, manifest, name, value):
    record = _put(project, name, value)
    component["inputs"][name] = record["sha256"]
    return record


def _case(project, monkeypatch, *, mock_sources=True):
    netlist = _put(project, "inputs/final.v", "module neutral(input a, output y); assign y=a; endmodule\n")
    sdc = _put(project, "inputs/final.sdc", "set_input_delay 0 [get_ports a]\n")
    sdf = _put(project, "inputs/final_tt.sdf", "(DELAYFILE (SDFVERSION \"3.0\"))\n")
    state = _put(project, "reports/D70/state.json", {
        "nl": str((project / netlist["path"]).resolve()),
        "sdc": str((project / sdc["path"]).resolve()),
        "sdf": {"tt": str((project / sdf["path"]).resolve())}})
    d44 = _put(project, "adopted/final_lec/sta_lvs_release_netlist_mapping.json", {
        "producer": "flow109_final_lec", "mapping": "same_logical_bytes"})
    d69 = _put(project, "reports/D69/component.json", {
        "schema": "vibeic.flow109.final-extract.v1", "step_id": "D69",
        "component_status": "PASS", "flow109_acceptance": "NOT_MEASURED"})
    d70 = _put(project, "reports/D70/component.json", {
        "schema": gls.D70_SCHEMA, "step_id": "D70", "producer": "flow109_final_electrical",
        "component_status": "PASS", "flow109_acceptance": "NOT_MEASURED", "sdf_role": "final",
        "required_corners": ["tt"], "final_sdfs": {"tt": sdf}, "netlist": netlist,
        "sdc": sdc, "sta_state": state})
    catalog = _put(project, "inputs/functional_cases.json", {
        "schema": "vibeic.full_stack_functional.v1", "cases": [
            {"name": "functional", "state": "passed", "tb": "inputs/functional.v",
             "tb_sha256": "1" * 64}]})
    requirements = _put(project, "input/flow109/D71-engineering-population.json", {
        "required_corners": ["tt"], "required_scenarios": ["functional"],
        "required_timing_behaviors": ["sdf_delay_annotation", "functional_self_check"],
        "source_catalog": catalog})
    manifest = {"schema": gls.SCHEMA, "top": "neutral", "requirements": requirements}
    manifest_record = _put(project, gls.INPUT, manifest)
    native_manifest = _put(project, "reports/D71/manifest.json", {
        "compile_flags": "-g2012 -ginterconnect -gspecify", "top": "neutral",
        "netlist": str((project / netlist["path"]).resolve()),
        "cases": [{"id": "functional", "module": "functional",
                   "testbench": str((project / "inputs/functional.v").resolve())}]})
    stdout = _put(project, "reports/D71/native/tt/functional.stdout.log",
                  "SDF INFO: Putting delay 1\n[TB functional] PASS\n")
    stdout_path = str((project / stdout["path"]).resolve())
    native_runs_value = {"manifest": str((project / native_manifest["path"]).resolve()),
        "netlist": str((project / netlist["path"]).resolve()), "case_workers": 1,
        "runs": [{"corner": "tt", "case": "functional",
                  "sdf": str((project / sdf["path"]).resolve()),
                  "compile_rc": 0, "sim_rc": 0, "compile_log": stdout_path,
                  "stdout": stdout_path}]}
    native_runs = _put(project, "reports/D71/native/gls_runs.json", native_runs_value)
    copied_sdf = _put(project, "reports/D71/final_tt.sdf", (project / sdf["path"]).read_text())
    checker_value = {"program": "post_layout_sim_check", "version": "1.1.0",
        "verdict": "PASS", "summary": {"pass": True}, "findings": []}
    checker = _put(project, "reports/D71/post_layout_sim_check.json", checker_value)
    pair = {"corner": "tt", "scenario": "functional"}
    case = {"id": "functional", "verdict": "PASS", "passed": 1, "total": 1,
            "compile_rc": 0, "sim_rc": 0, "sdf_delays_applied": 1, "sdf_errors": 0}
    result = {"schema": gls.SCHEMA, "program": "flow109_final_gls", "step_id": "D71",
        "verdict": "PASS", "annotation_population": {
            "required": [pair], "observed": [pair], "missing": [],
            "all_functional_pass": True, "all_corners_annotated": True},
        "final_sdfs": {"tt": copied_sdf}, "d44_baseline": d44,
        "d70_receipt": d70, "d69_receipt": d69, "native_step": native_runs,
        "limitations": list(gls.LIMITATIONS), "judge": {
            "verdict": "PASS", "compile_flags": "-g2012 -ginterconnect -gspecify",
            "corners": {"tt": {"verdict": "PASS", "cases": [case],
                                  "delays_applied": 1, "sdf_errors": 0}},
            "existing_case_readback": [{"corner": "tt", "scenario": "functional",
                "source_self_check": {"state": "passed", "checks": {
                    "total": 1, "comparisons": 1, "errors": 0, "passed": 1}},
                "stdout_sha256": stdout["sha256"], "timingcheck_unsupported": 2}]},
        "execution_scope": gls.ENGINEERING_SCOPE, "full_row_acceptance": "NOT_MEASURED",
        "post_layout_sim_check": checker,
        "results_log": _put(project, "reports/D71/results.log", "VERDICT: PASS\n")}
    component = {"schema": gls.SCHEMA, "step_id": "D71", "component_status": "NOT_MEASURED",
        "engineering_component_status": "PASS", "execution_scope": gls.ENGINEERING_SCOPE,
        "full_row_acceptance": "NOT_MEASURED", "native_started": True,
        "context_sha256": "1" * 64, "operation_sources": {
            "programs/gls.py": "2" * 64,
            metrics.D71_CONSUMER_SOURCE: "3" * 64},
        "inputs": {}, "native": {"manifest": native_manifest, "runs": native_runs},
        "result": result, "checker": checker_value, "limitations": list(gls.LIMITATIONS)}
    for record in (netlist, sdc, sdf, state, d44, d69, d70, catalog, requirements,
                   manifest_record):
        component["inputs"][record["path"]] = record["sha256"]
    _refresh_published(project, component)
    if mock_sources:
        monkeypatch.setattr(gls, "operation_sources", lambda: {
            "programs/gls.py": "2" * 64,
            metrics.D71_CONSUMER_SOURCE: "4" * 64})
    return component, manifest


def test_registry_registers_only_the_three_D71_runtime_bindings():
    row = _context()["resolved_row"]
    assert row["profile"]["dispatch"]["flow109_metrics_status"] == "IMPLEMENTED_D71_RUNTIME"
    assert row["metric_acceptance_status"] == "IMPLEMENTED_D71_RUNTIME"
    assert {item["id"]: item["status"] for item in row["obligations"]} == {
        name: "IMPLEMENTED_D71_RUNTIME_BINDING" for name in metrics.D71_BINDINGS}


def test_current_native_D71_metrics_are_observed_but_pending_authority_and_upstream_block(
        tmp_path, monkeypatch):
    component, _ = _case(tmp_path, monkeypatch)
    accepted = metrics.accept_d71(tmp_path, _context(), component)
    statuses = {item["id"]: item["status"] for item in accepted["obligations"]}
    assert statuses == {"final_gls.final_sdf_annotation": "NOT_MEASURED",
                        "final_gls.final_gls_scenarios": "NOT_MEASURED",
                        "final_gls.final_gls_function_timing_errors": "PASS"}
    assert accepted["status"] == accepted["metric_status"] == "NOT_MEASURED"
    assert accepted["delivery_blocked"] is True
    covers = [item for item in accepted["obligations"] if item["operator"] == "covers_all"]
    assert all(item["measurement"]["status"] == "MEASURED" for item in covers)
    assert all(item["authority"]["status"] == "PENDING_DERIVED_REQUIREMENTS"
               for item in covers)
    assert all(item["measurement"]["identity"]["configuration"]["limitations"]
               for item in accepted["obligations"])


def test_frozen_b74_population_accepts_only_real_consumer_induced_AST_growth():
    recorded, provenance = _frozen_D71_sources()
    canonical = json.dumps(recorded, sort_keys=True, separators=(",", ":")).encode()
    assert len(recorded) == provenance["entry_count"] == 713
    assert hashlib.sha256(canonical).hexdigest() == provenance["canonical_json_sha256"] == (
        "c76f4ba79eacf8422687c6e1c6ca7c09db03a977ead119a2c1370f397d2f9e06")
    assert all(not Path(name).is_absolute() and name.startswith("programs/")
               for name in recorded)
    native_sources = provenance["native_producer_sources"]
    assert native_sources and set(native_sources) <= set(recorded)
    assert {name: recorded[name] for name in native_sources} == native_sources


def test_current_tree_real_consumer_AST_growth_uses_its_own_named_baseline():
    current = _real_D71_operation_sources()
    _, provenance = _frozen_D71_sources()
    programs = Path(gls.__file__).resolve().parent
    native_sources = provenance["native_producer_sources"]
    assert set(native_sources) <= set(current)
    assert {name: current[name] for name in native_sources} == native_sources
    assert all(hashlib.sha256((programs.parent / name).read_bytes()).hexdigest() == digest
               for name, digest in native_sources.items())

    added = {"programs/flow109_final_electrical.py", "programs/flow109_final_extract.py"}
    assert added < set(current)
    generated_baseline = {name: digest for name, digest in current.items()
                          if name not in added}
    assert metrics._d71_source_boundary(generated_baseline, current, gls) is True

    changed = dict(current)
    changed["programs/flow109_final_gls.py"] = "0" * 64
    assert metrics._d71_source_boundary(generated_baseline, changed, gls) is False
    missing = dict(current)
    missing.pop("programs/flow109_final_gls.py")
    assert metrics._d71_source_boundary(generated_baseline, missing, gls) is False
    arbitrary = dict(current)
    arbitrary["programs/arbitrary_consumer_import.py"] = "0" * 64
    assert metrics._d71_source_boundary(generated_baseline, arbitrary, gls) is False


@pytest.mark.parametrize("damage, expected", [
    ("missing_corner", "NOT_MEASURED"),
    ("missing_scenario", "FAIL"),
    ("stale_sdf", "NOT_MEASURED"),
    ("current_netlist", "NOT_MEASURED"),
    ("missing_annotation", "FAIL"),
    ("actual_error", "FAIL"),
    ("checker_fail", "FAIL"),
    ("unsupported_semantics", "NOT_MEASURED"),
    ("producer_source_drift", "NOT_MEASURED"),
    ("current_source_missing", "NOT_MEASURED"),
    ("arbitrary_extra_source", "NOT_MEASURED"),
])
def test_D71_missing_stale_failed_or_unsupported_evidence_refuses(
        tmp_path, monkeypatch, damage, expected):
    component, manifest = _case(tmp_path, monkeypatch)
    result = component["result"]
    if damage == "stale_sdf":
        (tmp_path / "inputs/final_tt.sdf").write_text("changed after D70\n")
    elif damage == "producer_source_drift":
        component["operation_sources"]["programs/gls.py"] = "5" * 64
    elif damage == "current_source_missing":
        monkeypatch.setattr(gls, "operation_sources", lambda: {
            metrics.D71_CONSUMER_SOURCE: "4" * 64})
    elif damage == "arbitrary_extra_source":
        monkeypatch.setattr(gls, "operation_sources", lambda: {
            "programs/gls.py": "2" * 64,
            metrics.D71_CONSUMER_SOURCE: "4" * 64,
            "programs/unrelated.py": "6" * 64})
    elif damage == "current_netlist":
        (tmp_path / "inputs/final.v").write_text("module changed; endmodule\n")
    elif damage == "checker_fail":
        component["checker"]["verdict"] = "FAIL"
        checker_path = tmp_path / result["post_layout_sim_check"]["path"]
        checker_path.write_text(json.dumps(component["checker"], indent=2))
        result["post_layout_sim_check"]["sha256"] = hashlib.sha256(
            checker_path.read_bytes()).hexdigest()
        _refresh_published(tmp_path, component)
    elif damage in {"missing_annotation", "missing_scenario", "actual_error"}:
        case = result["judge"]["corners"]["tt"]["cases"][0]
        if damage == "missing_annotation":
            case["sdf_delays_applied"] = 0
        elif damage == "missing_scenario":
            case["verdict"] = "FAIL"
            result["judge"]["verdict"] = "FAIL"
        else:
            case["verdict"] = "FAIL"
            result["judge"]["existing_case_readback"][0]["source_self_check"]["checks"]["errors"] = 1
            result["judge"]["verdict"] = "FAIL"
        _refresh_published(tmp_path, component)
    elif damage == "unsupported_semantics":
        requirements = json.loads((tmp_path / manifest["requirements"]["path"]).read_text())
        requirements["required_timing_behaviors"].append("setup_hold_timing_checks")
        record = _refresh_input(tmp_path, component, manifest, manifest["requirements"]["path"],
                                requirements)
        manifest["requirements"] = record
        manifest_record = _refresh_input(tmp_path, component, manifest, gls.INPUT, manifest)
        assert manifest_record["sha256"] == component["inputs"][gls.INPUT]
    else:
        d70_path = tmp_path / result["d70_receipt"]["path"]
        d70 = json.loads(d70_path.read_text())
        d70["required_corners"].append("ss")
        record = _refresh_input(tmp_path, component, manifest, result["d70_receipt"]["path"], d70)
        result["d70_receipt"] = record
        _refresh_published(tmp_path, component)
    accepted = metrics.accept_d71(tmp_path, _context(), component)
    assert accepted["status"] == expected
    assert accepted["delivery_blocked"] is True
    if damage == "actual_error":
        item = next(item for item in accepted["obligations"]
                    if item["id"] == "final_gls.final_gls_function_timing_errors")
        assert item["status"] == "FAIL"
        assert item["measurement"]["value"] == 1
    if damage in {"producer_source_drift", "current_source_missing",
                  "arbitrary_extra_source"}:
        assert {item.get("reason") for item in accepted["obligations"]} == {
            "METRIC_EXECUTION_EVIDENCE_STALE"}
        assert all("annotation_items" not in str(item.get("detail"))
                   and "scenario_items" not in str(item.get("detail"))
                   for item in accepted["obligations"])
