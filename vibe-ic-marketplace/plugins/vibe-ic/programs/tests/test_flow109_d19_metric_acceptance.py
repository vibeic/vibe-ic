"""D19 existing producer/consumer controls; no native timing qualification."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import design_one_shot_runner as runner
import flow109
import flow109_metric_acceptance as metrics
from programs.tests._hostpaths import require_repo
from test_flow109_selection import _write_dft_intent, profile


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def _ref(project, rel, text):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {'path': rel, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _case(project, monkeypatch, *, scan=True):
    _write_dft_intent(project, monkeypatch, scan=scan, route='ip' if scan else 'ic')
    features = profile('Mapped soft-IP with prestitched scan' if scan else 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D19', 'D19')
    assert context['features']['technology_specific'] is True
    modes = ['functional', 'shift', 'capture'] if scan else ['functional']
    corners, checks = ['approved_slow', 'approved_fast'], ['setup', 'hold']
    libraries = [_ref(project, 'input/pdk/logic.lib', 'library(neutral) {}\n')]
    rc = {'corner': 'approved_rc', 'model': _ref(project, 'input/pdk/rc.tcl', '# approved RC input\n')}
    decks = {mode: _ref(project, f'input/constraints/{mode}.sdc', f'# approved {mode} deck\n')
             for mode in modes}
    required = [{'mode': mode, 'corner': corner, 'check': check}
                for mode in modes for corner in corners for check in checks]
    mapping = [{**item, 'sdc': decks[item['mode']], 'libraries': libraries, 'rc': rc}
               for item in required]
    source = {'scenario_constraints': {'required_modes': modes, 'required_corners': corners,
                                      'required_checks': checks, 'required_items': required},
              'mode_library_rc_mapping': {'reference': mapping}}
    source_ref = _ref(project, 'input/approved-constraints.json', json.dumps(source))
    approval = {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': source_ref}
    fields = {name: {'schema': (metrics.AUTHORITY_SCHEMA if name == 'scenario_constraints'
                               else 'vibeic.flow109.adopted-reference.v1'),
                     'approval': approval, **payload} for name, payload in source.items()}
    _write(project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': fields})
    _write(project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json',
           {'fields': {'dft_present': scan}})
    _write(project / 'context.json', context)
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(project / 'context.json'))
    return context, fields


def _portable_case(project, monkeypatch, *, l20=False):
    _write_dft_intent(project, monkeypatch, scan=False, route='ip')
    context = flow109.execution_context(flow109.resolve_plan(profile('Digital soft-IP')), 'D19', 'D19')
    assert context['features']['technology_specific'] is False
    deck = _ref(project, 'input/constraints/functional.sdc',
                'create_clock -name core -period 20 [get_ports clk]\n'
                'set_input_delay -max 2 -clock core [get_ports d]\n'
                'set_input_delay -min 0 -clock core [get_ports d]\n'
                'set_output_delay -max 2 -clock core [get_ports q]\n'
                'set_output_delay -min 0 -clock core [get_ports q]\n')
    items = [{'mode': 'functional', 'check': check} for check in ('setup', 'hold')]
    source = {'scenario_constraints': {'required_modes': ['functional'],
               'required_checks': ['setup', 'hold'], 'required_items': items},
              'mode_library_rc_mapping': {'reference': [{**item, 'sdc': deck} for item in items]}}
    source_ref = _ref(project, 'input/approved-constraints.json', json.dumps(source))
    fields = {name: {'schema': metrics.AUTHORITY_SCHEMA if name == 'scenario_constraints'
                     else 'vibeic.flow109.adopted-reference.v1',
                    'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                                 'source_reference': source_ref}, **payload}
              for name, payload in source.items()}
    _write(project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': fields})
    if l20:
        _write(project / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json',
               {'fields': {'dft_present': False}})
    _write(project / 'context.json', context)
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT', str(project / 'context.json'))
    return context, fields


def _revise(project, fields, name, edit):
    """A new approved fixture epoch; neither saved producer binding is forged."""
    source_path = project / 'input/approved-constraints.json'
    source = json.loads(source_path.read_text())
    edit(source[name])
    _write(source_path, source)
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    for key in fields:
        fields[key]['approval']['source_reference']['sha256'] = digest
        fields[key].update(source[key])
    _write(project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': fields})


def test_registry_denominator_is_read_from_real_contract():
    registry = json.loads(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'flow', 'flow109.json').read_text())
    row = next(row for row in registry['rows'] if row['id'] == 'D19')
    assert set(metrics.D19_BINDINGS) < {item['id'] for item in row['obligations']}
    for obligation in row['obligations']:
        spec = metrics.D19_BINDINGS.get(obligation['id'])
        if spec:
            assert all(obligation['expectation'][key] == value for key, value in spec.items())


@pytest.mark.parametrize('damage,reason', [
    ('hold', 'D19_REQUIRED_SCENARIO_MISSING'),
    ('capture', 'D19_REQUIRED_SCENARIO_MISSING'),
    ('rc', 'D19_RC_MAPPING_MISSING'),
    ('library', 'D19_LIBRARY_MAPPING_MISSING'),
])
def test_actual_producer_refuses_before_dispatch(tmp_path, monkeypatch, damage, reason):
    _, fields = _case(tmp_path, monkeypatch)
    def edit(payload):
        entries = payload['reference']
        if damage in ('hold', 'capture'):
            field = 'check' if damage == 'hold' else 'mode'
            payload['reference'] = [item for item in entries if item[field] != damage]
        elif damage == 'rc':
            entries[0].pop('rc')
        else:
            entries[0]['libraries'] = []
    _revise(tmp_path, fields, 'mode_library_rc_mapping', edit)
    calls = []
    # Trap the existing canonical emitter; admission must run before it or
    # the Controller, not merely demote an already dispatched native result.
    import execution_policy
    from _ppa import timing
    monkeypatch.setattr(execution_policy, 'dispatch_fixed_step', lambda *a, **k: calls.append('controller'))
    monkeypatch.setattr(timing, 'emit_step7_asic_sdc', lambda *a, **k: calls.append('emitter'))
    result = runner.step_asic_sdc(tmp_path, pdk_config=object())
    assert calls == []
    assert result.status == 'NOT_MEASURED'
    assert result.extras['d19_refusal'] == reason
    assert result.extras['native_started'] is False
    assert not (tmp_path / 'requirements/base_10/scenario_constraints.json').exists()


@pytest.mark.parametrize('scan', [False, True])
def test_existing_artifacts_and_actual_consumer_are_source_bound(tmp_path, monkeypatch, scan):
    context, _ = _case(tmp_path, monkeypatch, scan=scan)
    produced = metrics.d19_admission(tmp_path, context, publish=True)
    accepted = metrics.accept_d19(tmp_path, context, {'d19_plan_admission': produced})
    assert [item['status'] for item in accepted['obligations']] == [
        'PASS', 'PASS', 'UNIMPLEMENTED_METRIC_BINDING']
    assert accepted['status'] == 'NOT_MEASURED' and accepted['delivery_blocked'] is True
    assert produced['native_controls_qualification'] == 'NOT_MEASURED'
    assert set(produced['artifacts']) == {
        'requirements/base_10/scenario_constraints.json', 'adopted/base_10/mode_library_rc_mapping.json'}
    assert not list(tmp_path.rglob('scenario_matrix.json'))


def test_complete_input_reaches_existing_emitter_and_retains_partial_scope(tmp_path, monkeypatch):
    """Only the legacy emitter edge is substituted, never the plan producer,
    metric consumer, artifact writer or row verdict. No native PASS is claimed.
    """
    _case(tmp_path, monkeypatch)
    from _ppa import timing
    calls = []
    def emit(_runtime, project, top, _pdk, _container):
        calls.append(top)
        ref = _ref(project, 'phase2/stage2/constraints/neutral.sdc', '# emitter edge fixture\n')
        return ref
    monkeypatch.setattr(timing, 'emit_step7_asic_sdc', emit)
    def pvt(project, *_args):
        path = project / 'phase2/stage2/constraints/pvt_matrix.json'
        _write(path, {'corners': []})
        return path, 0
    monkeypatch.setattr(runner, '_emit_step7_pvt_matrix', pvt)
    result = runner.step_asic_sdc(tmp_path, 'neutral', pdk_config=object(), _use_controller=False)
    assert calls == ['neutral']
    assert result.status == result.extras['default_row_status'] == 'NOT_MEASURED'
    assert [item['status'] for item in result.extras['metric_acceptance']['obligations']] == [
        'PASS', 'PASS', 'UNIMPLEMENTED_METRIC_BINDING']
    assert result.extras['completed'] is False


@pytest.mark.parametrize('changed', ['sdc', 'library', 'rc', 'L19', 'L20', 'D01', 'artifact'])
def test_current_consumer_rejects_changed_inputs_without_native_dispatch(tmp_path, monkeypatch, changed):
    context, _ = _case(tmp_path, monkeypatch)
    produced = metrics.d19_admission(tmp_path, context, publish=True)
    path = {'sdc': 'input/constraints/shift.sdc', 'library': 'input/pdk/logic.lib',
            'rc': 'input/pdk/rc.tcl', 'L19': 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
            'L20': 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json',
            'D01': 'input/feature-decisions.json',
            'artifact': 'requirements/base_10/scenario_constraints.json'}[changed]
    file = tmp_path / path
    file.write_text(file.read_text() + '\n')
    accepted = metrics.accept_d19(tmp_path, context, {'d19_plan_admission': produced})
    assert accepted['status'] == 'NOT_MEASURED' and accepted['delivery_blocked'] is True
    assert accepted['reason'] != 'D19_PLAN_METRICS_ONLY_NATIVE_CONTROLS_NOT_QUALIFIED'


def test_saved_plan_cannot_hide_removed_required_mode_or_hold(tmp_path, monkeypatch):
    context, _ = _case(tmp_path, monkeypatch)
    produced = metrics.d19_admission(tmp_path, context, publish=True)
    current = copy.deepcopy(produced)
    current['scenarios'] = [item for item in current['scenarios'] if item['mode'] != 'capture']
    result = metrics.accept_d19(tmp_path, context, {'d19_plan_admission': current})
    assert result['reason'] == 'D19_PRODUCER_RECEIPT_STALE'


def test_authority_hash_does_not_substitute_for_semantic_approval(tmp_path, monkeypatch):
    context, fields = _case(tmp_path, monkeypatch)
    fields['scenario_constraints']['required_corners'].append('undeclared_corner')
    _write(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': fields})
    with pytest.raises(metrics.MetricRefusal, match='D19_APPROVED_FIELDS_DIFFER'):
        metrics.d19_admission(tmp_path, context, publish=True)


@pytest.mark.parametrize('field,value,reason', [
    ('required_modes', 'capture', 'D19_REQUIRED_MODE_MISSING'),
    ('required_checks', 'hold', 'D19_REQUIRED_CHECK_MISSING'),
    ('required_corners', None, 'D19_APPROVED_CORNERS_MISSING'),
])
def test_incomplete_approved_census_is_named_refusal(tmp_path, monkeypatch, field, value, reason):
    context, fields = _case(tmp_path, monkeypatch)
    def edit(payload):
        payload[field] = [] if value is None else [v for v in payload[field] if v != value]
    _revise(tmp_path, fields, 'scenario_constraints', edit)
    with pytest.raises(metrics.MetricRefusal, match=reason):
        metrics.d19_admission(tmp_path, context, publish=True)
    assert not (tmp_path / 'requirements/base_10/scenario_constraints.json').exists()


def test_parent_path_cannot_relabel_report_as_approved_input(tmp_path, monkeypatch):
    context, fields = _case(tmp_path, monkeypatch)
    for body in fields.values():
        body['approval']['source_reference']['path'] = 'input/../input/approved-constraints.json'
    _write(tmp_path / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json', {'fields': fields})
    with pytest.raises(metrics.MetricRefusal, match='D19_INPUT_IDENTITY_MISSING'):
        metrics.d19_admission(tmp_path, context, publish=True)


def test_approved_sparse_combinations_do_not_gain_invented_corner_checks(tmp_path, monkeypatch):
    context, fields = _case(tmp_path, monkeypatch)
    def retain(items):
        return [item for item in items if (item['corner'], item['check']) in
                {('approved_slow', 'setup'), ('approved_fast', 'hold')}]
    _revise(tmp_path, fields, 'scenario_constraints',
            lambda payload: payload.update(required_items=retain(payload['required_items'])))
    _revise(tmp_path, fields, 'mode_library_rc_mapping',
            lambda payload: payload.update(reference=retain(payload['reference'])))
    produced = metrics.d19_admission(tmp_path, context, publish=True)
    result = metrics.accept_d19(tmp_path, context, {'d19_plan_admission': produced})
    assert [item['status'] for item in result['obligations'][:2]] == ['PASS', 'PASS']
    assert len(produced['scenarios']) == 6


@pytest.mark.parametrize('l20', [False, True], ids=['no_L20', 'with_L20'])
def test_portable_soft_ip_reaches_real_producer_without_technology(tmp_path, monkeypatch, l20):
    context, _ = _portable_case(tmp_path, monkeypatch, l20=l20)
    monkeypatch.setattr(runner, '_phase2_pdk_config', lambda *_a, **_k:
                        pytest.fail('technology-neutral SDC must not resolve a PDK'))
    result = runner.step_asic_sdc(tmp_path, 'neutral', _use_controller=False)
    assert result.detail.startswith('D19_PORTABLE_SDC_EMITTED'), result.detail
    assert result.status == result.extras['default_row_status'] == 'NOT_MEASURED'
    assert result.extras['producer_status'] == 'PASS'
    assert result.extras['completed'] is False
    accepted = metrics.accept_d19(tmp_path, context, result.extras)
    assert [item['status'] for item in accepted['obligations']] == [
        'PASS', 'NOT_MEASURED', 'UNIMPLEMENTED_METRIC_BINDING']
    assert accepted['obligations'][1]['reason'] == 'D19_TARGET_TECHNOLOGY_NOT_SPECIFIED'
    assert accepted['status'] == 'NOT_MEASURED' and accepted['delivery_blocked'] is True
    for output in result.extras['portable_sdc_outputs']:
        assert (tmp_path / output['sdc']['path']).read_bytes() == (
            tmp_path / output['source_sdc']['path']).read_bytes()
    assert not list((tmp_path / 'input').rglob('*.lib'))
    assert not list(tmp_path.rglob('pvt_matrix.json'))


def test_non_scan_target_tech_does_not_require_l20(tmp_path, monkeypatch):
    context, _ = _case(tmp_path, monkeypatch, scan=False)
    (tmp_path / 'phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json').unlink()
    try:
        metrics.d19_admission(tmp_path, context, publish=True)
        observed = 'PLAN_ADMITTED'
    except metrics.MetricRefusal as exc:
        observed = exc.code
    assert observed == 'PLAN_ADMITTED'


@pytest.mark.parametrize('missing', ['input/pdk/logic.lib', 'input/pdk/rc.tcl'])
def test_target_technology_missing_real_file_stops_before_producer(tmp_path, monkeypatch, missing):
    _case(tmp_path, monkeypatch)
    (tmp_path / missing).unlink()
    result = runner.step_asic_sdc(tmp_path, pdk_config=object(), _use_controller=False)
    assert result.extras['d19_refusal'] == 'D19_INPUT_STALE'
    assert result.status == 'NOT_MEASURED' and result.extras['native_started'] is False


@pytest.mark.parametrize('damage', ['source_sdc', 'output_sdc', 'approval_source', 'approved_fields'])
def test_portable_actual_consumer_reopens_source_approval_and_output(tmp_path, monkeypatch, damage):
    context, _ = _portable_case(tmp_path, monkeypatch)
    produced = runner.step_asic_sdc(tmp_path, _use_controller=False)
    assert produced.extras['metric_acceptance']['obligations'][0]['status'] == 'PASS'
    if damage == 'source_sdc':
        path = tmp_path / 'input/constraints/functional.sdc'
    elif damage == 'output_sdc':
        path = tmp_path / produced.extras['portable_sdc_outputs'][0]['sdc']['path']
    elif damage == 'approval_source':
        path = tmp_path / 'input/approved-constraints.json'
    else:
        path = tmp_path / 'requirements/base_10/scenario_constraints.json'
        body = json.loads(path.read_text())
        body['required_items'].pop()
        _write(path, body)
    if damage != 'approved_fields':
        path.write_text(path.read_text() + '\n')
    result = metrics.accept_d19(tmp_path, context, produced.extras)
    assert result['status'] == 'NOT_MEASURED' and result['delivery_blocked'] is True
    assert result['reason'] in ('D19_INPUT_STALE', 'D19_APPROVED_FIELDS_DIFFER')
    assert not result['obligations']


def test_portable_feature_cannot_hide_explicit_target_pdk(tmp_path, monkeypatch):
    _portable_case(tmp_path, monkeypatch)
    result = runner.step_asic_sdc(tmp_path, pdk_name='declared_target', _use_controller=False)
    assert result.extras['d19_refusal'] == 'D19_TECHNOLOGY_FEATURE_CONFLICT'
    assert result.extras['native_started'] is False
    assert not (tmp_path / 'requirements/base_10/scenario_constraints.json').exists()
