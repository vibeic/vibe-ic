"""D15 public owner controls; native replay is explicitly distinct from launch."""
from __future__ import annotations
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
import flow109
import flow109_frontend as owner
import flow109_metric_acceptance as metrics
from _hostpaths import require_repo


def put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return {'path': name, 'sha256': owner._sha(path)}


def case(project, monkeypatch):
    monkeypatch.setattr(flow109, 'validate_execution_context', lambda c: c)
    checks = {'isolation': ['ok   clamp = 00'], 'retention': ['ok   retained = a5']}
    items = [{'id': 'sleep', 'domain': 'PD_UNIT', 'state': 'down', 'time': '7'},
             {'id': 'wake', 'domain': 'PD_UNIT', 'state': 'up', 'time': '9'}]
    return inputs(project, checks, items)


def inputs(project, checks, items):
    source = put(project, 'input/power/scenarios.json',
                 {'required_items': items, 'expected_checks': checks})
    put(project, 'requirements/power_verify/required_power_transitions.json', {
        'schema': metrics.AUTHORITY_SCHEMA, 'required_items': items,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': source}})
    manifest = {'schema': 'vibeic.flow109.power-simulation.v1', 'top': 'unit_tb',
        'rtl': [put(project, 'phase2/stage1/rtl/unit.sv', 'module unit; endmodule\n')],
        'testbench': put(project, 'input/verification/unit_tb.sv', 'module unit_tb; initial $finish; endmodule\n'),
        'upf': put(project, 'input/power/unit.upf', 'create_power_domain PD_UNIT\n'),
        'expected_checks': checks}
    put(project, 'input/flow109/D15.json', manifest)
    return {'requested_step': 'D15', 'context_sha256': 'test-context'}, manifest


OUTPUT = """[UPF] Time: 7, Power domain 'PD_UNIT' is powered down
[UPF] Time: 9, Power domain 'PD_UNIT' is powered up
ok   clamp = 00
ok   retained = a5
Simulation finished at time 10 ($finish called)
"""


def replay(monkeypatch, out=OUTPUT, err=''):
    original = owner.subprocess.run
    def run(argv, **kwargs):
        if '--simulate' in argv:
            return SimpleNamespace(returncode=0, stdout=out, stderr=err)
        return original(argv, **kwargs)
    monkeypatch.setattr(owner.subprocess, 'run', run)


def test_public_owner_positive_measures_both_existing_obligations(tmp_path, monkeypatch):
    context, _ = case(tmp_path, monkeypatch)
    replay(monkeypatch)
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'PASS', result
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['metric_acceptance']['obligations'][0]['observed_value'] == ['sleep', 'wake']
    assert result['metric_acceptance']['obligations'][1]['observed_value'] == 0


@pytest.mark.parametrize('mutation', ['retention', 'isolation', 'transition'])
def test_public_owner_rc0_semantic_or_coverage_failure(tmp_path, monkeypatch, mutation):
    context, _ = case(tmp_path, monkeypatch)
    if mutation == 'transition':
        out = OUTPUT.replace("[UPF] Time: 9, Power domain 'PD_UNIT' is powered up\n", '')
    else:
        line = 'ok   retained = a5' if mutation == 'retention' else 'ok   clamp = 00'
        out = OUTPUT.replace(line, 'FAIL ' + mutation + ': incorrect value')
    replay(monkeypatch, out)
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'FAIL', result
    assert result['returncode'] == 0


@pytest.mark.parametrize('kind', ['rtl', 'upf'])
def test_public_owner_wrong_input_identity_refuses_before_native(tmp_path, monkeypatch, kind):
    context, manifest = case(tmp_path, monkeypatch)
    ref = manifest['rtl'][0] if kind == 'rtl' else manifest['upf']
    (tmp_path / ref['path']).write_text('changed bytes\n')
    replay(monkeypatch)
    result = owner.execute(tmp_path, context)
    assert result.get('reason') == 'D15_INPUT_STALE', result
    assert result['native_started'] is False


@pytest.mark.parametrize('command', ['create_pst PST -supplies {VDD}',
    'add_power_state PD_UNIT -state ON', 'create_supply_set SS',
    'set_level_shifter LS -domain PD_UNIT', 'set_retention_control R -save_signal {s high}',
    'load_upf child.upf', 'unknown_required_feature X',
    'set_retention R -domain PD_UNIT -elements {u} -save_signal {s high}',
    'set_isolation ISO -domain PD_UNIT -clamp_value {latch}',
    'set_isolation ISO -domain PD_UNIT -applies_to {inputs}'])
def test_public_owner_ignored_required_upf_refuses(tmp_path, monkeypatch, command):
    context, manifest = case(tmp_path, monkeypatch)
    manifest['upf'] = put(tmp_path, manifest['upf']['path'], command + '\n')
    put(tmp_path, 'input/flow109/D15.json', manifest)
    result = owner.execute(tmp_path, context)
    assert result.get('reason') == 'D15_UPF_UNSUPPORTED', result
    assert result['native_started'] is False


def test_public_owner_native_warning_refuses(tmp_path, monkeypatch):
    context, _ = case(tmp_path, monkeypatch)
    replay(monkeypatch, err='[UPF] warning: unresolved isolation signal\n')
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result.get('metric_acceptance', {}).get('reason') == 'D15_NATIVE_FEATURE_UNRESOLVED', result


@pytest.mark.parametrize('arm,expected', [('positive', 'PASS'), ('missing_retention', 'FAIL'),
                                        ('missing_isolation', 'FAIL')])
def test_reuse_staged_native_controls_without_launch(tmp_path, monkeypatch, arm, expected):
    if not os.environ.get('D15_STAGED'):
        pytest.skip('native replay receipts unavailable: set D15_STAGED to the staged audit input root')
    staged = Path(os.environ['D15_STAGED'])
    controls = staged / 'xezim-native-controls'
    upstream = staged / 'xezim-upstream'
    provenance = json.loads((upstream / 'SOURCE.json').read_text())
    for item in provenance['files']:
        assert owner._sha(upstream / item['path']) == item['sha256']
    context, manifest = case(tmp_path, monkeypatch)
    positive = (controls / 'positive/stdout.log').read_text()
    checks = {'isolation': [line for line in positive.splitlines() if line.startswith('ok   ') and 'clamped' in line],
              'retention': [line for line in positive.splitlines() if line.startswith('ok   ') and 'retained' in line]}
    items = [{'id': name, 'domain': 'PD_ACC', 'state': state, 'time': time}
             for name, state, time in [('sleep', 'down', '77'), ('wake', 'up', '106')]]
    context, manifest = inputs(tmp_path, checks, items)
    manifest['top'] = 'pwr_demo_tb'
    manifest['upf'] = put(tmp_path, 'input/power/native.upf', (controls / arm / 'intent.upf').read_text())
    manifest['rtl'] = [put(tmp_path, 'phase2/stage1/rtl/' + name,
                          (upstream / 'examples/upf' / name).read_text())
                       for name in ('pwr_demo.sv',)]
    manifest['testbench'] = put(tmp_path, 'input/verification/pwr_demo_tb.sv',
        (upstream / 'examples/upf/pwr_demo_tb.sv').read_text())
    put(tmp_path, 'input/flow109/D15.json', manifest)
    replay(monkeypatch, (controls / arm / 'stdout.log').read_text(),
           (controls / arm / 'stderr.log').read_text())
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == expected, result
    assert result['returncode'] == 0


def test_real_registry_keeps_two_obligations_and_predecessors():
    path = require_repo('vibe-ic-marketplace/plugins/vibe-ic/flow/flow109.json')
    row = next(r for r in json.loads(path.read_text())['rows'] if r['id'] == 'D15')
    assert row['acceptance_deps'] == ['D05', 'D09']
    assert {o['metric'] for o in row['obligations']} == {
        'required_power_transitions', 'isolation_retention_behavior_errors'}


def test_public_owner_missing_behavior_check_is_unmeasured(tmp_path, monkeypatch):
    context, _ = case(tmp_path, monkeypatch)
    replay(monkeypatch, OUTPUT.replace('ok   retained = a5\n', ''))
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result.get('metric_acceptance', {}).get('reason') == 'D15_BEHAVIOR_CHECKS_INCOMPLETE', result


@pytest.mark.parametrize('kind', ['rtl', 'upf'])
def test_public_owner_changed_native_readset_during_run_is_refused(tmp_path, monkeypatch, kind):
    context, manifest = case(tmp_path, monkeypatch)
    original = owner.subprocess.run
    def run(argv, **kwargs):
        if '--simulate' in argv:
            ref = manifest['rtl'][0] if kind == 'rtl' else manifest['upf']
            (tmp_path / ref['path']).write_text('changed during native\n')
            return SimpleNamespace(returncode=0, stdout=OUTPUT, stderr='')
        return original(argv, **kwargs)
    monkeypatch.setattr(owner.subprocess, 'run', run)
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result.get('metric_acceptance', {}).get('reason') == 'D15_INPUT_STALE', result


# These tests exercise the real completion/qualification consumers, with an
# explicitly SYNTHETIC qualification registry, predecessor rows and transcript.
# They grant no qualification to the preserved native controls or current row.
completion_overlay = pytest.mark.skipif(not hasattr(metrics, 'accept_d15'),
    reason='D15 completion controls require the isolated ROOT_INTEGRATION.patch overlay')


def completion_case(project, monkeypatch, *, engineering=False, stale_model=False):
    import flow109_admission as admission
    context, manifest = inputs(project,
        {'isolation': ['ok   clamp = 00'], 'retention': ['ok   retained = a5']},
        [{'id': 'sleep', 'domain': 'PD_UNIT', 'state': 'down', 'time': '7'},
         {'id': 'wake', 'domain': 'PD_UNIT', 'state': 'up', 'time': '9'}])
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    plan = flow109.resolve_plan(dict(features, has_power_intent=True))
    for step in ('D05', 'D09'):
        prior = flow109.execution_context(plan, step, step)
        put(project, 'reports/flow109/requests/' + prior['context_sha256'] + '.json', prior)
        row = {'step_id': step, 'component_status': 'PASS', 'default_row_status': 'PASS',
               'completed': True, 'context_sha256': prior['context_sha256']}
        if step == 'D05':
            put(project, owner.D05_INPUT, {'schema': owner.D05_SCHEMA, 'top': 'unit',
                'upf': manifest['upf'], 'rtl': manifest['rtl'],
                'liberty': put(project, 'input/synthetic/unit.lib', 'library(unit) {}'),
                'lefs': [put(project, 'input/synthetic/unit.lef', 'VERSION 5.8 ;')],
                'evaluation': {'site': 'unit', 'die_area': [0, 0, 10, 10],
                               'core_area': [1, 1, 9, 9], 'domain_areas': {}}})
            row['input_sha256'] = owner._d05_prepare(project, prior)['inputs']
        else:
            row['evidence'] = {'rtl_inventory': [
                {'path': Path(r['path']).name, 'sha256': r['sha256']} for r in manifest['rtl']]}
        put(project, 'reports/flow109/default_rows/' + step + '.json', row)
    tool = owner._d15_tool()
    config = {'purpose': 'D15.default.power_aware_runtime_subset',
              'native_steps': ['flow109.D15'], 'model_sources': owner.d15_model_sources(),
              'tool_readset': tool['readset']}
    if stale_model:
        config['model_sources']['flow109_frontend.py:consume_d15'] = '0' * 64
    use = flow109.resolve_step(plan, 'D15')['tool_uses'][0]
    identity = {'use_id': use['use_id'], 'tool_id': 'xezim', 'version': 'SYNTHETIC FIXTURE',
        'build_sha256': tool['readset'][tool['executable']],
        'executable': {'path': tool['executable'], 'sha256': tool['readset'][tool['executable']]},
        'config': put(project, 'input/synthetic/model.json', config),
        'pdk': {'applicable': False, 'reason': 'synthetic behavioral fixture'},
        'deck': {'applicable': False, 'reason': 'synthetic behavioral fixture'},
        'corner': 'synthetic', 'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps']}}
    reference = put(project, 'input/synthetic/reference.json',
                    {'scope': 'SYNTHETIC QUALIFICATION FIXTURE; no native qualification credit'})
    record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
              'reference_evidence': [reference]}
    put(project, 'qualifications.json', {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [record]})
    runtime = [{**identity, 'qualification_sha256': admission.canonical_sha(record)}]
    context = flow109.execution_context(plan, 'D15', 'D15',
        runtime_tool_uses=None if engineering else runtime,
        qualification_registry=None if engineering else 'qualifications.json')
    replay(monkeypatch)
    component = owner.execute(project, context)
    return context, component


@completion_overlay
def test_completion_valid_synthetic_population_completes_automatically(tmp_path, monkeypatch):
    context, component = completion_case(tmp_path, monkeypatch)
    result = flow109._selected_step_result(tmp_path, context, component, owner)
    assert result['default_row_status'] == 'PASS', result
    assert result['completed'] is True
    assert result['qualification'] == 'PASS'
    assert result['flow109_acceptance'] == 'PASS'
    assert result['delivery_accepted'] is False
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'


@completion_overlay
@pytest.mark.parametrize('damage,reason', [
    ('missing_d05', 'FLOW109_D05_RESULT_MISSING'),
    ('missing_d09', 'FLOW109_D09_RESULT_MISSING'),
    ('missing_d05_context', 'D15_PREDECESSOR_CONTEXT_ABSENT'),
    ('stale_d09_context', 'FLOW109_CONTEXT_STALE'),
    ('missing_config', 'QUALIFICATION_INPUT_ABSENT'),
    ('stale_executed_tool', 'D15_PRODUCER_IDENTITY_STALE'),
    ('stale_d05', 'D05_INPUT_STALE'),
    ('stale_d09', 'D15_INPUT_STALE'),
    ('missing_qualification', 'QUALIFICATION_INPUT_ABSENT'),
    ('missing_use', 'QUALIFICATION_USE_ABSENT'),
    ('stale_config', 'QUALIFICATION_STALE'),
    ('stale_reference', 'QUALIFICATION_STALE'),
    ('missing_reference', 'QUALIFICATION_INPUT_ABSENT'),
    ('missing_launch_proof', 'D15_ORIGINAL_EXECUTION_UNQUALIFIED'),
    ('stale_launch_proof', 'D15_ORIGINAL_EXECUTION_UNQUALIFIED'),
    ('completed_flag_bypass', 'D15_ORIGINAL_EXECUTION_UNQUALIFIED')])
def test_completion_absent_or_stale_required_proof_refuses(tmp_path, monkeypatch, damage, reason):
    context, component = completion_case(tmp_path, monkeypatch)
    assert component['component_status'] == 'PASS', component
    if damage in {'missing_d05', 'missing_d09'}:
        (tmp_path / ('reports/flow109/default_rows/' + damage[-3:].upper() + '.json')).unlink()
    elif damage in {'missing_d05_context', 'stale_d09_context'}:
        step = 'D05' if damage == 'missing_d05_context' else 'D09'
        row = json.loads((tmp_path / ('reports/flow109/default_rows/' + step + '.json')).read_text())
        request = tmp_path / ('reports/flow109/requests/' + row['context_sha256'] + '.json')
        if damage == 'missing_d05_context':
            request.unlink()
        else:
            previous = json.loads(request.read_text())
            previous['context_sha256'] = '0' * 64
            request.write_text(json.dumps(previous))
    elif damage == 'missing_config':
        (tmp_path / 'input/synthetic/model.json').unlink()
    elif damage == 'stale_executed_tool':
        executable = component['tool']['executable']
        component['tool']['readset'][executable] = '0' * 64
    elif damage == 'stale_d05':
        (tmp_path / 'input/synthetic/unit.lib').write_text('changed')
    elif damage == 'stale_d09':
        path = tmp_path / 'reports/flow109/default_rows/D09.json'
        row = json.loads(path.read_text())
        row['evidence']['rtl_inventory'][0]['sha256'] = '0' * 64
        path.write_text(json.dumps(row))
    elif damage == 'missing_qualification':
        (tmp_path / 'qualifications.json').unlink()
    elif damage == 'missing_use':
        put(tmp_path, 'qualifications.json', {'schema': 'vibeic.flow109.qualifications.v1', 'uses': []})
    elif damage in {'stale_config', 'stale_reference'}:
        (tmp_path / ('input/synthetic/model.json' if damage == 'stale_config'
                     else 'input/synthetic/reference.json')).write_text('{}')
    elif damage == 'missing_reference':
        (tmp_path / 'input/synthetic/reference.json').unlink()
    elif damage in {'missing_launch_proof', 'completed_flag_bypass'}:
        component.pop('launch_admission')
        if damage == 'completed_flag_bypass':
            component.update(completed=True, default_row_status='PASS')
    elif damage == 'stale_launch_proof':
        component['launch_admission'] = {'status': 'PASS'}
    result = flow109._selected_step_result(tmp_path, context, component, owner)
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert result['completed'] is False
    assert result['normalized_chain_reason'] == reason, result


@completion_overlay
def test_completion_unqualified_engineering_run_cannot_complete(tmp_path, monkeypatch):
    context, component = completion_case(tmp_path, monkeypatch, engineering=True)
    result = flow109._selected_step_result(tmp_path, context, component, owner)
    assert component['component_status'] == 'PASS'
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['normalized_chain_reason'] == 'QUALIFICATION_RUNTIME_ABSENT', result


@completion_overlay
def test_completion_stale_model_refuses_before_native_launch(tmp_path, monkeypatch):
    context, component = completion_case(tmp_path, monkeypatch, stale_model=True)
    assert component['native_started'] is False, component
    assert component['reason'] == 'D15_MODEL_QUALIFICATION_STALE', component
    result = flow109._selected_step_result(tmp_path, context, component, owner)
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['completed'] is False


@completion_overlay
def test_completion_synthetic_qualified_front_door_returns_zero(tmp_path, monkeypatch):
    from _delivery_route import admit
    context, _ = completion_case(tmp_path, monkeypatch)
    assert admit(tmp_path, 'ic') is None
    selection = put(tmp_path, 'selection.json', {
        'features': context['features'], 'runtime_tool_uses': context['runtime_tool_uses'],
        'qualification_registry': context['qualification_registry']})
    args = SimpleNamespace(flow='109', execution_mode=None, flow109_plan_only=False,
        flow109_manifest=tmp_path / selection['path'], entry_step='D15', exit_step='D15', container=None)
    assert flow109.prepare_front_door(args, tmp_path) == 0
    result = json.loads((tmp_path / 'reports/flow109/components/D15.json').read_text())
    assert result['default_row_status'] == 'PASS' and result['completed'] is True
    assert result['qualification'] == 'PASS'
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
