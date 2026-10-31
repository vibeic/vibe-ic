"""Source-only neutral controls. No canonical qualification or IC row PASS."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from _stated_eda_image import stated_image

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROGRAMS), str(PROGRAMS / 'tests')]
import analog_native_flow as native
import flow109
import flow109_metric_acceptance as metrics
from test_analog_native_front import _smoke_project


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(root, path, body):
    path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


@pytest.fixture
def case(tmp_path, monkeypatch):
    root, block, smoke = _smoke_project(tmp_path)
    deck = root / smoke['deck']['path']
    deck.write_text(deck.read_text().replace('.dc vgate', '.temp 27\n.dc vgate'))
    smoke['deck']['sha256'] = sha(deck)
    source = root / 'input/synthetic-requirements.txt'
    source.write_text('Synthetic source control. Required cell_alpha device_alpha typical. No qualification.')
    config = put(root, 'input/analog_flow.json', {'model_smokes': [smoke]})
    authority = put(root, 'requirements/base_A2/model_corner_statistics_coverage.json', {
        'schema': metrics.AUTHORITY_SCHEMA,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': {'path': str(source.relative_to(root)), 'sha256': sha(source)}},
        'required_items': [{'block': 'cell_alpha', 'device': 'device_alpha', 'corner': 'typical', 'temperature_c': '27'}]})
    image = stated_image()
    monkeypatch.setattr(native, '_adapter_transport', lambda _: ('', image, 'LOCAL'))
    def window(project, context):
        return native.run_window(project, SimpleNamespace(entry_step='A02', exit_step='A02',
            container='', image=image, transport='LOCAL'), features={'has_analog': True})
    monkeypatch.setattr(native, 'execute_window', window)
    context = {'requested_step': 'A02', 'context_sha256': 'c' * 64,
               'resolved_row': {'id': 'A02'}}
    result = native.execute(root, context)
    return root, context, result, authority, config


def replay(case):
    root, context, result, *_ = case
    return metrics.accept_a02(root, context, result)


def save_result(case):
    root, _, result, *_ = case
    report = result['native_results']
    put(root, str(Path(report['attempt']).relative_to(root) / 'result.json'), report)


def test_real_smoke_metric_positive_without_row_credit(case):
    root, context, result, *_ = case
    assert result['component_status'] == 'PASS', result
    assert result['metric_acceptance_status'] == 'PASS', result
    assert result['metric_acceptance']['metrics']['device_model_load_errors']['value'] == 0
    selected = flow109._selected_step_result(root, context, result, native)
    assert selected['metric_acceptance_status'] == 'PASS', selected
    assert selected['default_row_status'] == 'NOT_MEASURED'
    assert selected['completed'] is False
    assert not (root / 'qualifications.json').exists()


@pytest.mark.parametrize('fault', ['missing_corner', 'empty_required', 'duplicate_required',
    'missing_authority', 'changed_source', 'changed_deck', 'changed_model', 'missing_capture',
    'changed_config', 'changed_log', 'changed_tool', 'missing_block', 'changed_image', 'wrong_device', 'missing_temperature'])
def test_substantive_negative_controls(case, fault):
    root, _, result, authority, config = case
    if fault in ('missing_corner', 'empty_required', 'duplicate_required'):
        doc = json.loads(authority.read_text())
        if fault == 'missing_corner':
            doc['required_items'].append({'block': 'cell_alpha', 'device': 'device_alpha', 'corner': 'slow', 'temperature_c': '27'})
        elif fault == 'empty_required':
            doc['required_items'] = []
        else:
            doc['required_items'] *= 2
        authority.write_text(json.dumps(doc))
        result['a02_invocation']['inputs'][str(authority)] = sha(authority)
    elif fault == 'missing_temperature':
        doc = json.loads(authority.read_text())
        doc['required_items'].append({'block': 'cell_alpha', 'device': 'device_alpha', 'corner': 'typical', 'temperature_c': '-40'})
        authority.write_text(json.dumps(doc))
        result['a02_invocation']['inputs'][str(authority)] = sha(authority)
    elif fault == 'missing_authority':
        authority.unlink()
    elif fault == 'changed_source':
        (root / 'input/synthetic-requirements.txt').write_text('changed')
    elif fault == 'changed_deck':
        (root / 'input/model_smokes/device_alpha.sp').write_text('changed')
    elif fault == 'changed_model':
        (root / 'input/pdk/models/device_alpha.lib').write_text('changed')
    elif fault == 'missing_capture':
        result.pop('a02_invocation')
    elif fault == 'changed_config':
        config.write_text('{}')
    elif fault == 'changed_log':
        row = result['native_results']['steps'][0]
        (root / row['metrics'][0]['log']['path']).write_text('changed')
    elif fault == 'changed_tool':
        result['a02_invocation']['tool']['sha256'] = '0' * 64
    elif fault == 'missing_block':
        result['native_results']['steps'] = []
        save_result(case)
    elif fault == 'changed_image':
        result['native_results']['image'] = 'foreign'
        save_result(case)
    elif fault == 'wrong_device':
        doc = json.loads(config.read_text())
        doc['model_smokes'][0]['device'] = 'device_beta'
        config.write_text(json.dumps(doc))
        digest = sha(config)
        result['a02_invocation']['inputs'][str(config)] = digest
        result['native_results']['steps'][0]['input_views'][str(config)] = digest
        save_result(case)
    answer = replay(case)
    assert answer['status'] != 'PASS', answer
    if fault == 'missing_corner':
        assert answer['status'] == 'FAIL', answer
        assert answer['metrics']['model_corner_statistics_coverage']['missing'][0]['corner'] == 'slow'


def test_measured_failure_survives_later_missing_authority(case):
    root, _, result, authority, _ = case
    row = result['native_results']['steps'][0]
    ex = next(ex for ex in row['executions'] if ex['program'] == '@ngspice')
    path = Path(ex['args'][2])
    path.write_text('Fatal error: unknown subckt device_alpha\n')
    digest = sha(path)
    ex['outputs'][str(path)] = digest
    row['output_views'][str(path)] = digest
    save_result(case)
    authority.unlink()
    answer = replay(case)
    assert answer['status'] == 'FAIL', answer
    assert answer['metrics']['device_model_load_errors']['status'] == 'FAIL'
