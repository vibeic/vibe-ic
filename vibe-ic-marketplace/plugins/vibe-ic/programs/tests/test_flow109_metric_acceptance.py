"""Runtime metric acceptance controls for the source-whitelisted A01 binding."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

import flow109
import flow109_metric_acceptance as metrics
import flow109_analog as analog
from test_flow109_selection import profile
from programs.tests._hostpaths import require_repo
from test_flow109_analog_a01 import _case, _run
from test_flow109_analog_a01 import legacy_component_registry  # noqa: F401


def _identity():
    return {key: {"identity": key} for key in
            ("producer", "checker", "tool_execution", "consumed_inputs",
             "requirements", "configuration")}


def _authority(tmp_path: Path, name: str, fields: tuple[str, ...], items: list[dict]):
    source = tmp_path / "input/owner-approved-analog-requirements.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        source.write_text("Owner-approved analog requirements, revision neutral-1.\n")
    relative = f"requirements/base_A1/{name}.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": metrics.AUTHORITY_SCHEMA,
        "approval": {"status": "APPROVED", "authority": "requirements_owner", 'approver': 'neutral-requirements-reviewer',
                     "source_reference": {"path": str(source.relative_to(tmp_path)),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}},
        "required_items": [{key: item[key] for key in fields} for item in items],
    }
    path.write_text(json.dumps(body, indent=2) + "\n")
    return path


def _approved_case(tmp_path: Path):
    manifest, registry = _case(tmp_path)
    _authority(tmp_path, "analog_specs_with_units", ("block", "name", "unit"),
               [{"block": "regulator_alpha", "name": "vout", "unit": "V"}])
    _authority(tmp_path, "required_measurements", ("block", "name"),
               [{"block": "regulator_alpha", "name": "vout"}])
    return manifest, registry


@pytest.mark.parametrize('reader', ['required_items', 'document'])
def test_requirement_reader_does_not_require_a_person_name(tmp_path, reader):
    path = _authority(tmp_path, 'limits', ('name',), [{'name': 'setup'}])
    body = json.loads(path.read_text())
    del body['approval']['approver']
    body['limits'] = {'min': 0}
    path.write_text(json.dumps(body))
    relative = path.relative_to(tmp_path).as_posix()
    if reader == 'required_items':
        authority, observed = metrics._approved_authority(
            tmp_path, relative + '#/required_items', ('name',))
        assert authority['required_items'] == [{'name': 'setup'}]
    else:
        authority, observed = metrics._approved_document(
            tmp_path, relative, authority='requirements_owner',
            schema=metrics.AUTHORITY_SCHEMA)
    assert authority['status'] == 'APPROVED'
    assert observed['limits'] == {'min': 0}


def _report_and_context(project: Path):
    report = json.loads((project / "reports/flow109/components/A01.json").read_text())
    # These retained component fixtures have no completed native row owner.
    assert report["default_row_status"] == "NOT_MEASURED"
    assert report["completed"] is False
    assert report["whole_flow_acceptance"] == "NOT_MEASURED"
    request = next((project / "reports/flow109/requests").glob("*.json"))
    return report, json.loads(request.read_text())


def test_checked_in_registry_is_the_source_owned_binding_denominator():
    path = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json")
    registry = json.loads(path.read_text())
    row = next(item for item in registry["rows"] if item["id"] == "A01")
    assert {item["id"] for item in row["obligations"]} == set(metrics.A01_BINDINGS)
    assert {item["expectation"]["operator"] for item in row["obligations"]} == {"covers_all"}
    assert {item["status"] for item in row["obligations"]} == {"IMPLEMENTED_A01_RUNTIME_BINDING"}
    assert row["metric_acceptance_status"] == "IMPLEMENTED_A01_RUNTIME"


def test_safe_operators_are_typed_and_fail_closed():
    ident = _identity()
    assert metrics.evaluate_operator("eq",
        {"status": "MEASURED", "value": 0, "unit": "count", "identity": ident},
        {"status": "APPROVED", "value": 0, "unit": "count"})[0] == "PASS"
    assert metrics.evaluate_operator("covers_all",
        {"status": "MEASURED", "value": ["a", "b"], "identity": ident},
        {"status": "APPROVED", "required_items": ["a"], "validated_absence": False})[0] == "PASS"
    assert metrics.evaluate_operator("within_declared_bounds",
        {"status": "MEASURED", "value": 1.5, "unit": "V", "identity": ident},
        {"status": "APPROVED", "limits": {"min": 1.0, "max": 2.0}, "unit": "V"})[0] == "PASS"
    reference_identity = _identity()
    assert metrics.evaluate_operator("matches_adopted_reference",
        {"status": "MEASURED", "value": {"digest": "a"}, "identity": ident},
        {"status": "APPROVED", "reference": {"digest": "a"},
         "reference_identity": reference_identity})[0] == "PASS"

    for bad in (True, math.nan, math.inf):
        with pytest.raises(metrics.MetricRefusal):
            metrics.evaluate_operator("eq",
                {"status": "MEASURED", "value": bad, "unit": "count", "identity": ident},
                {"status": "APPROVED", "value": 0, "unit": "count"})
    broken = _identity()
    broken["producer"] = {"digest": None}
    with pytest.raises(metrics.MetricRefusal, match="IDENTITY_INCOMPLETE"):
        metrics.evaluate_operator("eq",
            {"status": "MEASURED", "value": 0, "unit": "count", "identity": broken},
            {"status": "APPROVED", "value": 0, "unit": "count"})
    assert metrics.evaluate_operator("covers_all",
        {"status": "MEASURED", "value": [], "identity": ident},
        {"status": "APPROVED", "required_items": [], "validated_absence": False})[0] == "NOT_MEASURED"


def test_actual_front_door_producer_and_consumer_can_pass_both_a01_metrics(tmp_path):
    _approved_case(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    report, _ = _report_and_context(tmp_path)
    assert report["component_status"] == "PASS"
    assert report["metric_acceptance_status"] == "PASS"
    assert report["metric_acceptance"]["delivery_blocked"] is False
    assert [o["status"] for o in report["metric_acceptance"]["obligations"]] == ["PASS", "PASS"]
    assert report["flow109_acceptance"] == "NOT_MEASURED"
    assert all(item["measurement"]["identity"]["tool_execution"]["qualification_sha256"]
               for item in report["metric_acceptance"]["obligations"])


def test_actual_measurement_that_misses_approved_required_set_is_fail(tmp_path):
    _approved_case(tmp_path)
    path = tmp_path / "requirements/base_A1/required_measurements.json"
    body = json.loads(path.read_text())
    body["required_items"].append({"block": "regulator_alpha", "name": "gain"})
    path.write_text(json.dumps(body))
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    report, _ = _report_and_context(tmp_path)
    assert report["metric_acceptance_status"] == "FAIL"
    assert report["metric_acceptance"]["delivery_blocked"] is True


def test_actual_unmeasured_a01_component_with_valid_authority_stays_typed(tmp_path, monkeypatch):
    manifest, _ = _case(tmp_path, specs=False)
    _authority(tmp_path, "analog_specs_with_units", ("block", "name", "unit"),
               [{"block": "regulator_alpha", "name": "vout", "unit": "V"}])
    _authority(tmp_path, "required_measurements", ("block", "name"),
               [{"block": "regulator_alpha", "name": "vout"}])
    context = flow109.execution_context(flow109.resolve_plan(manifest["features"]), "A01", "A01",
        runtime_tool_uses=manifest["runtime_tool_uses"], qualification_registry="qualifications.json")
    # Obtain the real producer/gate NOT_MEASURED component without recursively
    # invoking the metric layer we are about to exercise.
    monkeypatch.setattr(analog, "accept_a01", lambda *_: {
        "status": "NOT_MEASURED", "obligations": []})
    component = analog.execute(tmp_path, context)
    assert component["component_status"] == "NOT_MEASURED"
    result = metrics.accept_a01(tmp_path, context, component)
    assert result["status"] == "NOT_MEASURED"
    assert {item["status"] for item in result["obligations"]} == {"NOT_MEASURED"}


@pytest.mark.parametrize("damage, reason", [
    ("missing", "METRIC_AUTHORITY_ABSENT"),
    ("stale", "METRIC_AUTHORITY_STALE"),
    ("ai", "METRIC_AUTHORITY_UNAPPROVED"),
])
def test_missing_stale_or_ai_owned_requirement_authority_is_not_measured(tmp_path, damage, reason):
    _approved_case(tmp_path)
    path = tmp_path / "requirements/base_A1/analog_specs_with_units.json"
    if damage == "missing":
        path.unlink()
    elif damage == "stale":
        (tmp_path / "input/owner-approved-analog-requirements.md").write_text("changed\n")
    else:
        body = json.loads(path.read_text())
        body["approval"]["authority"] = "AI"
        path.write_text(json.dumps(body))
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    report, _ = _report_and_context(tmp_path)
    acceptance = report["metric_acceptance"]
    assert acceptance["status"] == "NOT_MEASURED" and acceptance["delivery_blocked"]
    assert reason in {o.get("reason") for o in acceptance["obligations"]}


def test_corrupted_current_output_and_false_producer_cannot_pass(tmp_path):
    _approved_case(tmp_path)
    assert _run(tmp_path).returncode == 2
    report, context = _report_and_context(tmp_path)
    spec = tmp_path / "phase3/analog/regulator_alpha/spec.json"
    spec.write_text(spec.read_text().replace('"target": 1.8', '"target": 1.7'))
    stale = metrics.accept_a01(tmp_path, context, report)
    assert stale["status"] == "NOT_MEASURED" and stale["reason"] == "METRIC_EVIDENCE_STALE"

    false = copy.deepcopy(report)
    false["component_status"] = "FAIL"
    false["reason"] = "A01_PRODUCER_FAILED"
    failed = metrics.accept_a01(tmp_path, context, false)
    assert failed["status"] == "FAIL"
    assert {o["status"] for o in failed["obligations"]} == {"FAIL"}


def test_source_whitelist_reverse_guard_keeps_unknown_obligation_unimplemented(tmp_path, monkeypatch):
    _approved_case(tmp_path)
    assert _run(tmp_path).returncode == 2
    report, context = _report_and_context(tmp_path)
    monkeypatch.delitem(metrics.A01_BINDINGS, "base_A1.required_measurements")
    reversed_result = metrics.accept_a01(tmp_path, context, report)
    assert reversed_result["status"] == "NOT_MEASURED"
    assert any(o["status"] == "UNIMPLEMENTED_METRIC_BINDING"
               for o in reversed_result["obligations"])


def test_actual_a01_metrics_bind_approved_rows_and_the_separate_chip_set(tmp_path):
    from test_analog_a1_spec_emit import attribution_case
    _approved_case(tmp_path)
    amendment, _ = attribution_case(tmp_path, existing=True)
    result = _run(tmp_path)
    report, context = _report_and_context(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    acceptance = report['metric_acceptance']
    assert acceptance['status'] == 'PASS', acceptance
    registry = json.loads(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'flow', 'flow109.json').read_text())
    declared = next(row for row in registry['rows'] if row['id'] == 'A01')
    assert {o['id'] for o in acceptance['obligations']} == {o['id'] for o in declared['obligations']}
    measured = acceptance['obligations'][0]['measurement']
    assert {'block': 'regulator_alpha', 'name': 'iload', 'unit': 'mA'} in measured['value']
    assert measured['chip_specs'] == [{'scope': 'chip', 'name': 'supply', 'unit': 'V'}]
    assert 'requirements/base_A1/electrical_row_attribution.json' in report['inputs']
    assert 'phase3/analog/chip_specs.json' in report['outputs']
    amendment.write_text(amendment.read_text() + '\n')
    stale = metrics.accept_a01(tmp_path, context, report)
    assert stale['status'] == 'NOT_MEASURED', stale
    assert stale['reason'] == 'METRIC_INPUT_CHANGED'


def _measurement_intent_case(project, damage=None):
    manifest, registry = _approved_case(project)
    source = project / 'input/docs/measurement-plan.md'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('Measure settling response.\nMeasure ripple response.\n')
    path = project / 'requirements/base_A1/required_measurements.json'
    body = json.loads(path.read_text())
    body['item_review'], body['item_citations'] = [], []
    for index, name in enumerate(('settling', 'ripple'), 1):
        item = {'block': 'regulator_alpha', 'name': name}
        body['required_items'].append(item)
        body['item_review'].append({'item_index': index, 'item': item,
                                    'kind': 'explicit_verification_intent'})
        body['item_citations'].append({'item_index': index, 'item': item, 'citations': [{
            'path': str(source.relative_to(project)),
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'line': index, 'literal': source.read_text().splitlines()[index - 1]}]})
    if damage == 'missing_review':
        body['item_review'].pop()
    elif damage == 'missing_citation':
        body['item_citations'].pop()
    elif damage == 'empty_citations':
        body['item_citations'][-1]['citations'] = []
    elif damage == 'not_intent':
        body['item_review'][-1]['kind'] = 'numeric_spec_declaration_not_simulation'
    elif damage == 'stale_source':
        source.write_text('The measurement plan was withdrawn.\n')
    elif damage == 'wrong_literal':
        body['item_citations'][-1]['citations'][0]['literal'] = 'Text absent from source'
    elif damage == 'wrong_item':
        body['item_review'][-1]['item'] = {'block': 'regulator_alpha', 'name': 'foreign'}
    path.write_text(json.dumps(body))
    return manifest, registry


@pytest.mark.parametrize('damage, status, count', [
    (None, 'PASS', 3), ('missing_review', 'FAIL', 2),
    ('missing_citation', 'FAIL', 2), ('empty_citations', 'FAIL', 2),
    ('not_intent', 'FAIL', 2), ('stale_source', 'NOT_MEASURED', None),
    ('wrong_literal', 'NOT_MEASURED', None), ('wrong_item', 'NOT_MEASURED', None)])
def test_a01_observes_only_reviewed_source_bound_measurement_intent(tmp_path, damage, status, count):
    _measurement_intent_case(tmp_path, damage)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    report, _ = _report_and_context(tmp_path)
    acceptance = report['metric_acceptance']
    specs, intent = acceptance['obligations']
    assert specs['status'] == 'PASS', specs
    assert intent['status'] == status, intent
    assert acceptance['status'] == status, acceptance
    if count is not None:
        assert len(intent['measurement']['value']) == count
        assert len(intent['authority']['required_items']) == 3
        assert intent['operator'] == 'covers_all'
        assert {'block': 'regulator_alpha', 'name': 'settling'} in intent['measurement']['value']
        source = 'input/docs/measurement-plan.md'
        assert intent['measurement']['identity']['consumed_inputs'][source] == hashlib.sha256(
            (tmp_path / source).read_bytes()).hexdigest()
    assert report['whole_flow_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('rule,complete,expected', [
    (None, True, 'PASS'),
    ('RESET_ROLE_UNRESOLVED', False, 'NOT_MEASURED'),
    ('RESET_CYCLE', True, 'FAIL'),
    ('ASYNC_INPUT_UNSYNC', True, 'FAIL'),
    ('CDC_UNSYNC_CROSSING', True, 'FAIL'),
])
def test_d12_current_native_findings_and_roles_decide_status(tmp_path, monkeypatch, rule, complete, expected):
    import flow109_admission
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D12', 'D12')
    source = {'input_domains': {'clk': {'role': 'clock', 'clock': 'clk'}}}
    observed = {'subject': {'graph': 'current'}, 'findings': [] if rule is None else [
        {'rule': rule, 'severity': 'ERROR'}],
        'reset_analysis': {'cycle_detection_complete': complete},
        'population': {'clock_domains': ['clk'], 'crossings': []},
        'input_domains': source['input_domains']}
    monkeypatch.setattr(metrics, '_d12_source', lambda *a: (
        {'status': 'APPROVED'}, {'required_items': []}, source))
    monkeypatch.setattr(metrics, '_d12_observe', lambda *a: observed)
    def census(*args):
        if not complete:
            raise metrics.MetricRefusal('D12_ROLES_UNPROVEN', 'reset role is unresolved')
        return [{'kind': 'clock', 'name': 'clk'}]
    monkeypatch.setattr(metrics, '_d12_census', census)
    monkeypatch.setattr(flow109_admission, 'require_admission', lambda *a: pytest.fail(
        'current native observation must not requalify a historical Python executable'))
    result = metrics.accept_d12(tmp_path, context)
    assert result['status'] == expected
    assert result['component_status'] == expected
    assert result['observed']['findings'] == observed['findings']
