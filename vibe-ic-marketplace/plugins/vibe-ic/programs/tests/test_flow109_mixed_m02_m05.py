"""Focused source controls for the canonical M02/M05 mixed adapters."""
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
import flow109_mixed_m02 as m02
import flow109_mixed_m05 as m05
from _hostpaths import require_repo


FIXTURE = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                       "tests", "fixtures", "m3_native")


def _put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _features():
    return next(row["features"] for row in flow109.load_registry()["reference_profiles"]
                if row["name"] == "Mixed hard-IP")


def _qualified_context(project, step, module, *, config, deck, pdk, corner, qualified=True):
    plan = flow109.resolve_plan(_features())
    if not qualified:
        return flow109.execution_context(plan, step, step)
    use = flow109.resolve_step(plan, step)["tool_uses"][0]
    binary = Path(shutil.which("python3")).resolve()
    executable = {"path": str(binary),
                  "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    identity = {"use_id": use["use_id"], "tool_id": "python3", "version": sys.version,
                "build_sha256": executable["sha256"], "executable": executable,
                "config": config, "deck": deck, "pdk": pdk, "corner": corner,
                "semantics": {"purpose": use["purpose"], "native_steps": use["native_steps"],
                              "operation_sources": module.operation_sources()}}
    evidence = _put(project, f"input/flow109/{step}-reference.json",
                    {"scope": "neutral component control; not benchmark signoff"})
    record = {"use_id": use["use_id"], "status": "QUALIFIED", "identity": identity,
              "reference_evidence": [evidence]}
    registry = {"schema": "vibeic.flow109.qualifications.v1", "uses": [record]}
    _put(project, "qualifications.json", registry)
    runtime = [{**identity, "qualification_sha256": admission.canonical_sha(record)}]
    return flow109.execution_context(plan, step, step, runtime_tool_uses=runtime,
                                     qualification_registry="qualifications.json")


def _m02_case(project, *, scope="declared_model_component", qualified=True):
    shutil.copytree(FIXTURE, project, dirs_exist_ok=True)
    if scope != "declared_model_component":
        native_path = project / m02.NATIVE_CONTRACT
        native = json.loads(native_path.read_text())
        native["scope"] = scope
        native_path.write_text(json.dumps(native, indent=2))
    receipts = []
    for step in m02.REQUIRED_PREDECESSORS:
        receipts.append(_put(project, f"reports/flow109/components/{step}.json",
                             {"step_id": step, "component_status": "PASS",
                              "scope": "neutral predecessor control"}))
    contract = project / m02.NATIVE_CONTRACT
    deck = {"path": m02.NATIVE_CONTRACT, "sha256": hashlib.sha256(contract.read_bytes()).hexdigest()}
    plan_path = project / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
    plan = {"path": str(plan_path.relative_to(project)),
            "sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest()}
    pdk = {"applicable": False, "reason": "functional RC fixture is PDK-independent"}
    config = _put(project, m02.INPUT, {"schema": m02.SCHEMA,
        "basis": "current_pre_layout_partition", "top": "bridge_top", "container": "host",
        "native_contract": deck, "scenario_plan": plan, "pdk": pdk,
        "predecessor_receipts": receipts})
    return _qualified_context(project, "M02", m02, config=config, deck=deck,
                              pdk=pdk, corner=["pre_layout"], qualified=qualified)


def test_registry_selects_existing_mixed_adapters():
    plan = flow109.resolve_plan(_features())
    assert flow109.resolve_step(plan, "M02")["profile"]["dispatch"]["adapter"] == "flow109_mixed_m02"
    row = flow109.resolve_step(plan, "M05")
    assert row["profile"]["dispatch"]["adapter"] == "flow109_mixed_m05"
    assert row["capability_status"] == "UNSUPPORTED_OPEN_DEFAULT"


def test_m02_current_component_pass_uses_existing_producer_and_consumer(tmp_path, monkeypatch):
    context = _m02_case(tmp_path)
    monkeypatch.setattr(m02.m3, "produce", lambda *_args: {"cosim_verdict": "PASS"})
    monkeypatch.setattr(m02.m3, "audit", lambda *_args: {"verdict": "PASS", "passed": True})
    def gate(argv):
        _put(Path("/"), argv[argv.index("--json") + 1], {"passed": True, "verdict": "PASS"})
        return 0
    monkeypatch.setattr(m02.cosim_check, "main", gate)
    report = m02.execute(tmp_path, context)
    assert report["component_status"] == "PASS"
    assert report["flow109_acceptance"] == "NOT_MEASURED"
    assert report["scope"].endswith("whole ADC NOT_MEASURED")


def test_m02_measured_fail_has_precedence(tmp_path, monkeypatch):
    context = _m02_case(tmp_path)
    monkeypatch.setattr(m02.m3, "produce", lambda *_args: {"cosim_verdict": "FAIL"})
    monkeypatch.setattr(m02.m3, "audit", lambda *_args: {"verdict": "PASS"})
    def gate(argv):
        _put(Path("/"), argv[argv.index("--json") + 1], {"passed": True, "verdict": "PASS"})
        return 0
    monkeypatch.setattr(m02.cosim_check, "main", gate)
    assert m02.execute(tmp_path, context)["component_status"] == "FAIL"


@pytest.mark.parametrize("metric", ["response_mismatches", "unknown_samples"])
def test_m02_rejects_literal_error_even_when_incomplete_criteria_self_passes(
        tmp_path, monkeypatch, metric):
    context = _m02_case(tmp_path)
    _put(tmp_path, m02.m3.COSIM, {
        "verdict": "PASS", "all_scenarios_passed": True,
        "scenarios": [{"id": "enable_receiver", "status": "PASS",
                       "criteria": [{"native_metric": "drive_transitions", "min": 1,
                                     "measured": 1, "verdict": "PASS"}],
                       "metrics": {"drive_transitions": 1, metric: 1}}]})
    monkeypatch.setattr(m02.m3, "produce", lambda *_args: {"cosim_verdict": "PASS"})
    monkeypatch.setattr(m02.m3, "audit", lambda *_args: {"verdict": "PASS", "passed": True})
    def gate(argv):
        _put(Path("/"), argv[argv.index("--json") + 1], {"passed": True, "verdict": "PASS"})
        return 0
    monkeypatch.setattr(m02.cosim_check, "main", gate)
    report = m02.execute(tmp_path, context)
    assert report["component_status"] == "FAIL"
    assert report["reason"] == "M02_MEASURED_FAIL"
    assert report["literal_measured_failures"] == [{
        "scenario": "enable_receiver", "metric": metric, "measured": 1, "required": 0}]


def test_m02_literal_zero_error_control_remains_component_pass(tmp_path, monkeypatch):
    context = _m02_case(tmp_path)
    _put(tmp_path, m02.m3.COSIM, {
        "verdict": "PASS", "all_scenarios_passed": True,
        "scenarios": [{"id": "enable_receiver", "status": "PASS",
                       "criteria": [{"native_metric": "drive_transitions", "min": 1,
                                     "measured": 1, "verdict": "PASS"}],
                       "metrics": {"drive_transitions": 1, "response_mismatches": 0,
                                   "unknown_samples": 0}}]})
    monkeypatch.setattr(m02.m3, "produce", lambda *_args: {"cosim_verdict": "PASS"})
    monkeypatch.setattr(m02.m3, "audit", lambda *_args: {"verdict": "PASS", "passed": True})
    def gate(argv):
        _put(Path("/"), argv[argv.index("--json") + 1], {"passed": True, "verdict": "PASS"})
        return 0
    monkeypatch.setattr(m02.cosim_check, "main", gate)
    report = m02.execute(tmp_path, context)
    assert report["component_status"] == "PASS"
    assert report["literal_measured_failures"] == []


def test_m02_reuses_only_reverified_current_native_receipt(tmp_path, monkeypatch):
    context = _m02_case(tmp_path)
    _put(tmp_path, m02.m3.RECEIPT, {"cosim_verdict": "PASS", "run_id": "retained"})
    monkeypatch.setattr(m02.m3, "audit",
                        lambda *_args: {"verdict": "PASS", "passed": True})
    monkeypatch.setattr(m02.m3, "produce",
                        lambda *_args: pytest.fail("current verified proof must not rerun"))
    def gate(argv):
        _put(Path("/"), argv[argv.index("--json") + 1], {"passed": True, "verdict": "PASS"})
        return 0
    monkeypatch.setattr(m02.cosim_check, "main", gate)
    report = m02.execute(tmp_path, context)
    assert report["component_status"] == "PASS"
    assert report["reused_current_native"] is True


def test_m02_refuses_spice_only_without_actual_wrapper_partition(tmp_path):
    context = _m02_case(tmp_path, scope="spice_only_block")
    with pytest.raises(admission.AdmissionRefusal, match="M02_PRELAYOUT_PARTITION_UNSUPPORTED"):
        m02.prepare(tmp_path, context)


def test_m02_refuses_input_drift_after_prepare(tmp_path):
    context = _m02_case(tmp_path)
    prepared = m02.prepare(tmp_path, context)
    (tmp_path / "input/mixed_signal/receiver.sp").write_text("changed after admission\n")
    with pytest.raises(admission.AdmissionRefusal, match="M02_STALE_OR_MISSING_INPUT"):
        m02._before(tmp_path, context, prepared)


def _m05_context(project, *, qualified=True):
    pdk = {"applicable": False,
           "reason": "no qualified open substrate extraction/model"}
    config = _put(project, m05.INPUT, {"schema": m05.SCHEMA,
        "basis": "open_default_capability_probe", "substrate_model": pdk})
    return _qualified_context(project, "M05", m05, config=config, deck=pdk,
                              pdk=pdk, corner=["unsupported"], qualified=qualified)


@pytest.mark.parametrize("consumer_verdict,rc,rule,expected", [
    ("PASS", 0, None, "NOT_MEASURED"),
    ("NOT_MEASURED", 1, "SI_COVERAGE_NOT_MEASURED", "NOT_MEASURED"),
    ("FAIL", 1, "FAILED_MEASUREMENT", "FAIL")])
def test_m05_preserves_unsupported_scope_and_measured_fail(
        tmp_path, monkeypatch, consumer_verdict, rc, rule, expected):
    context = _m05_context(tmp_path)
    def consumer(argv):
        _put(Path("/"), argv[argv.index("--json") + 1],
             {"verdict": consumer_verdict, "passed": consumer_verdict == "PASS",
              "findings": [] if rule is None else [{"rule": rule}]})
        return rc
    monkeypatch.setattr(m05.si_check, "main", consumer)
    report = m05.execute(tmp_path, context)
    assert report["component_status"] == expected
    assert report["flow109_acceptance"] == "NOT_MEASURED"
    assert "substrate" in report["unsupported_scope"]


@pytest.mark.parametrize('step,setup,expected', [
    ('M02', _m02_case, None),
    ('M05', _m05_context, 'NOT_MEASURED'),
])
def test_mixed_native_entry_without_qualification_material(tmp_path, step, setup, expected):
    context = setup(tmp_path, qualified=False)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'features': context['features']}))
    result = subprocess.run([
        sys.executable, str(m02.HERE / 'vibe_ic_one_shot_runner.py'), str(tmp_path),
        '--flow', '109', '--flow109-manifest', str(manifest),
        '--entry-step', step, '--exit-step', step, '--route', 'ip', '--no-dashboard'],
        capture_output=True, text=True, timeout=120)
    assert 'QUALIFICATION_RUNTIME_ABSENT' not in result.stdout + result.stderr
    report = json.loads((tmp_path / f'reports/flow109/components/{step}.json').read_text())
    if step == 'M02':
        # Exercise the real producer; missing image utilities remain native FAIL.
        producer = report['producer_receipt']
        audit = report['cosim_audit']
        assert producer is not None and audit is not None
        expected = 'FAIL' if 'FAIL' in (producer['cosim_verdict'], audit['verdict']) else 'PASS'
    assert report['component_status'] == expected, result.stdout + result.stderr
    assert report['qualification_status'] == 'NOT_MEASURED'
    assert report['flow109_acceptance'] == ('FAIL' if expected == 'FAIL' else 'NOT_MEASURED')
