"""SOURCE_ONLY new CTS-roster/finalizer controls; old controls are not replayed.

Reuse only the old neutral fixture. Receipt, requirements and stage methods are
explicit doubles; disk approvals/native receipts remain invalid. Neutral real
OpenROAD raw reports validate the new field grammar, not SPM/058 qualification.
"""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution_backend_producers as producer
import execution_backend_worker as worker
import flow109
import flow109_clock_plan as planning
import flow109_metric_acceptance as metrics
import librelane_contract as ll
import step_output_collector as versions
import test_flow109_d38_metric_binding as old
import test_flow109_window_continuation as windows
from test_flow109_d38_metric_binding import case as original_case

REAL_DOCUMENT = metrics._approved_document
REAL_AUTHORITY = metrics._approved_authority
COVERAGE = 'requirements/base_25/clock_tree_sink_coverage.json'


def transcript(domains=None, all_pins=None):
    domains = {'core_clock': ['r0/CLK', 'r1/CLK']} if domains is None else domains
    all_pins = ['r0/CLK', 'r1/CLK'] if all_pins is None else all_pins
    lines = ['CLOCK_PLAN_ROSTER_BEGIN', *['CLOCK_PLAN_ALL_SINK ' + p for p in all_pins],
             'CLOCK_PLAN_ALL_SINK_COUNT ' + str(len(all_pins))]
    for clock, pins in domains.items():
        lines += ['CLOCK_PLAN_NATIVE ' + clock + '|10.0|clk',
                  *['CLOCK_PLAN_SINK ' + clock + '|' + pin for pin in pins],
                  'CLOCK_PLAN_SINK_COUNT ' + clock + '|' + str(len(pins))]
    return '\n'.join([*lines, 'CLOCK_PLAN_DONE', ''])


@pytest.fixture
def case(original_case, monkeypatch):
    c = original_case
    numeric_document = metrics._approved_document
    c.numeric_document = numeric_document
    payload = {'reference': {'clocks': {'core_clock': ['r0/CLK', 'r1/CLK']}, 'unclocked': []},
        'reference_identity': {'producer': {'scope': 'SOURCE_ONLY_INDEPENDENT_STRUCTURAL_METHOD_DOUBLE'},
            'checker': {'scope': 'SOURCE_ONLY'}, 'tool_execution': {'scope': 'SOURCE_ONLY'},
            'consumed_inputs': {str(c.model): old.sha(c.model)},
            'requirements': {'scope': 'SOURCE_ONLY'}, 'configuration': {'clocks': ['core_clock']}}}
    source = c.put(planning.SINK_SOURCE, {'clock_sink_inventory': payload})
    adopted_path = c.put(planning.SINK_REFERENCE, 'SOURCE_ONLY_NOT_AN_APPROVED_REFERENCE\n')
    adopted = {'status': 'SOURCE_ONLY_ADOPTED_REFERENCE_METHOD_DOUBLE', 'path': planning.SINK_REFERENCE,
        'sha256': old.sha(adopted_path), 'source': {'path': planning.SINK_SOURCE, 'sha256': old.sha(source)}}
    reference_body = {'schema': 'vibeic.flow109.adopted-reference.v1', 'approval': {'scope': 'SOURCE_ONLY_METHOD_DOUBLE'}, **payload}
    required = [{'clock': 'core_clock', 'pin': p} for p in ['r0/CLK', 'r1/CLK']]
    requirement = c.put(COVERAGE, 'SOURCE_ONLY_NOT_AN_APPROVED_REQUIREMENT\n')
    authority = {'status': 'APPROVED', 'scope': 'SOURCE_ONLY_AUTHORITY_API_DOUBLE_NOT_DISK_APPROVAL',
        'required_items': required, 'validated_absence': False, 'path': COVERAGE,
        'sha256': old.sha(requirement), 'source': dict(adopted['source'])}
    def documents(project, relative, **kwargs):
        if relative == planning.SINK_REFERENCE:
            return adopted, reference_body
        return numeric_document(project, relative, **kwargs)
    monkeypatch.setattr(metrics, '_approved_document', documents)
    monkeypatch.setattr(metrics, '_approved_authority', lambda *a: (authority, {'required_items': required}))
    cfgroot = c.project / 'phase3/librelane/execution-backend-19-config'
    script = cfgroot / 'cts_sink_roster.tcl'
    # Same caller-supplied bytes in candidate/base, captured from the neutral
    # native field probe. The baseline does not have a roster implementation.
    script.write_text(Path('/native-complete/cts_sink_roster.tcl').read_text())
    for index in [3, 4]:
        corner = ['slow_case', 'fast_case'][index - 3]
        config = cfgroot / ('OpenROAD.STAMidPNR@' + corner + '.json')
        body = json.loads(config.read_text());body['STA_EXTRA_CORNER_TCL_FILE'] = str(script)
        config.write_text(json.dumps(body))
        record = c.receipts[str(c.folders[index])]
        record['input']['config'] = old.sha(config)
        record['input']['config_files'][str(script)] = old.sha(script)
    def roster(index=3, value=None):
        log = c.folders[index] / 'invocation.log'
        log.write_text('[INFO] No information on clock propagation in input SDC file-- propagating all clocks.\n' +
                       (transcript() if value is None else value))
        c.receipts[str(c.folders[index])]['sha256']['invocation.log'] = old.sha(log)
    roster(3);roster(4)
    def observe():
        path = c.project / 'reports/phase3/librelane_cts_handoff.json'
        handoff = json.loads(path.read_text())
        return metrics.accept_d38(c.project, json.loads(Path(os.environ[flow109.CONTEXT_ENV]).read_text()),
            {'native_image': 'SOURCE_ONLY_DOUBLE', 'verdict': 'PASS',
             'flow109_d38_targets': handoff['flow109_d38_targets']})
    c.roster, c.observe, c.script = roster, observe, script
    c.required, c.authority, c.adopted, c.source = required, authority, adopted, source
    c.reference_body, c.coverage_requirement = reference_body, requirement
    return c


def accepted(result):
    return result['metric_acceptance']


def read_roster(text):
    method = getattr(metrics, '_d38_sink_roster', None)
    return method(text) if method else {'clocks': {}, 'unclocked': [], 'all_pins': []}


def test_real_native_complete_and_unreached_pin_reports_are_distinct():
    complete = read_roster(Path('/native-complete/native-roster.log').read_text())
    orphan = read_roster(Path('/native-orphan/native-roster.log').read_text())
    assert complete['all_pins'] == ['r0/CK', 'r1/CK', 'r2/CK']
    assert complete['unclocked'] == []
    assert complete['clocks']['clock_orphan'] == ['r2/CK']
    assert orphan['unclocked'] == ['r2/CK']


def test_actual_sink_pairs_and_numerical_fields_reach_both_operators(case):
    result = case.run(complete=True)
    observation = accepted(result)
    assert observation['metric_status'] == 'PASS', result
    assert observation['status'] == observation['qualification'] == 'NOT_MEASURED'
    assert [o['status'] for o in observation['obligations']] == ['PASS', 'PASS']
    assert observation['obligations'][0]['measurements'][0]['measurement']['value'] == case.required
    values = {m['field']: m['measurement']['value'] for m in observation['obligations'][1]['measurements']}
    assert values['clock_skew_ns'] == .2 and values['insertion_delay_ns'] == .3
    assert result['canonical_receipts'][0]['metric_acceptance']['metric_status'] == 'PASS'


@pytest.mark.parametrize('broken', ['unreached', 'wrong_clock', 'missing_pin'])
def test_missing_or_wrong_clock_sink_cannot_complete_and_is_blocking(case, broken):
    domains = {'core_clock': ['r0/CLK']}
    universe = ['r0/CLK', 'r1/CLK']
    if broken == 'wrong_clock':
        domains['other_clock'] = ['r1/CLK']
    elif broken == 'missing_pin':
        universe = ['r0/CLK']
    case.roster(4, transcript(domains, universe))
    result = case.run(complete=True)
    assert result['verdict'] == 'FAIL', result
    assert accepted(result)['obligations'][0]['status'] == 'FAIL'
    assert result['canonical_receipts'][0]['metric_acceptance']['status'] == 'FAIL'


@pytest.mark.parametrize('broken', ['truncated', 'count_only', 'duplicate', 'missing_corner', 'foreign_pin'])
def test_incomplete_native_roster_is_ni_not_coverage(case, broken):
    text = transcript()
    if broken == 'truncated':
        text = text.replace('CLOCK_PLAN_DONE', '')
    elif broken == 'count_only':
        text = text.replace('CLOCK_PLAN_SINK core_clock|r1/CLK\n', '')
    elif broken == 'duplicate':
        text = text.replace('CLOCK_PLAN_SINK core_clock|r1/CLK', 'CLOCK_PLAN_SINK core_clock|r0/CLK')
    elif broken == 'foreign_pin':
        text = text.replace('CLOCK_PLAN_SINK core_clock|r1/CLK', 'CLOCK_PLAN_SINK core_clock|outside/CLK')
    else:
        text = 'NATIVE_SESSION_WITHOUT_ROSTER\n'
    case.roster(4, text)
    observation = accepted(case.run())
    assert observation['metric_status'] == 'NOT_MEASURED', observation
    assert observation['obligations'][0]['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('broken', ['missing_requirement', 'foreign_source', 'incomplete_required_set', 'stale_reference_source'])
def test_independent_adopted_population_cannot_be_replaced_by_observation(case, monkeypatch, broken):
    if broken == 'missing_requirement':
        monkeypatch.setattr(metrics, '_approved_authority', REAL_AUTHORITY)
    elif broken == 'foreign_source':
        path = case.put('other-sink-source.json', case.source.read_text())
        case.authority['source'] = {'path': str(path.relative_to(case.project)), 'sha256': old.sha(path)}
    elif broken == 'incomplete_required_set':
        case.required.pop()
    else:
        case.source.write_text('{}')
    observation = accepted(case.run())
    assert observation['metric_status'] == 'NOT_MEASURED'
    assert observation['obligations'][1]['status'] == 'PASS'


def test_real_authority_reader_refuses_invalid_adopted_fixture_file(case, monkeypatch):
    def documents(project, relative, **kwargs):
        if relative == planning.SINK_REFERENCE:
            return REAL_DOCUMENT(project, relative, **kwargs)
        return case.numeric_document(project, relative, **kwargs)
    monkeypatch.setattr(metrics, '_approved_document', documents)
    observation = accepted(case.run())
    assert observation['metric_status'] == 'NOT_MEASURED'
    assert observation['obligations'][0]['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('late_missing', ['required_set', 'roster'])
def test_real_skew_fail_survives_late_missing_coverage_input(case, monkeypatch, late_missing):
    state = json.loads(case.states[-1].read_text())
    state['metrics']['clock__skew__worst_setup__corner:fast_case'] = 9
    case.states[-1].write_text(json.dumps(state));case.update(4)
    if late_missing == 'required_set':
        monkeypatch.setattr(metrics, '_approved_authority', REAL_AUTHORITY)
    else:
        case.roster(4, 'NO_ROSTER')
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert accepted(result)['obligations'][1]['status'] == 'FAIL'
    assert accepted(result)['obligations'][0]['status'] == 'NOT_MEASURED'


def test_sink_fail_survives_missing_numerical_report(case):
    case.roster(4, transcript({'core_clock': ['r0/CLK']}))
    report = case.folders[4] / 'fast_case/clock.rpt'
    case.receipts[str(case.folders[4])]['sha256'].pop('fast_case/clock.rpt')
    report.unlink()
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert accepted(result)['obligations'][0]['status'] == 'FAIL'
    assert accepted(result)['obligations'][1]['status'] == 'NOT_MEASURED'


def test_native_reporter_script_is_bound_to_its_receipt(case):
    case.after_native.append(lambda: case.script.write_text('FOREIGN_SCRIPT'))
    observation = accepted(case.run())
    assert observation['metric_status'] == 'NOT_MEASURED'


def test_existing_custom_native_reporter_is_preserved_and_refused(case):
    helper = getattr(producer, '_d38_sink_report_config', None)
    if helper is None:
        pytest.fail('native report producer not implemented')
    config = case.project / 'phase3/librelane/execution-backend-19-config/OpenROAD.STAMidPNR@slow_case.json'
    custom = case.put('inputs/custom-report.tcl', 'SOURCE_ONLY_CALLER_REPORT\n')
    body = json.loads(config.read_text());body['STA_EXTRA_CORNER_TCL_FILE'] = str(custom)
    config.write_text(json.dumps(body))
    with pytest.raises(Exception, match='D38_NATIVE_REPORT_CALLBACK_ALREADY_BOUND'):
        helper(ll, config)
    assert custom.read_text() == 'SOURCE_ONLY_CALLER_REPORT\n'


@pytest.fixture
def scene(case, monkeypatch):
    features = case.context['features']
    monkeypatch.setattr(windows, '_profile', lambda: copy.deepcopy(features))
    plan, context, _ = windows._window_fixture(case.project, monkeypatch, 'D38', 'D38')
    path = case.put('reports/flow109/requests/' + context['context_sha256'] + '.json', context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(case.project, context)))
    native = '19'
    for spec in worker.ROWS[native]['canonical_row']['required_outputs']:
        if not any(case.project.glob(spec)):
            assert '*' not in spec and ' OR ' not in spec
            case.put(spec, 'SOURCE_ONLY_GATE_METHOD_DOUBLE')
    inputs = {str(path.relative_to(case.project)): old.sha(path)}
    attempt = versions.begin_step(case.project, native, inputs=inputs)
    produced = case.run(complete=True)
    # A deliberately claimed prior PASS cannot replace current owner readback.
    for value in [produced['metric_acceptance'], produced['canonical_receipts'][0]['metric_acceptance']]:
        value.update(status='PASS', metric_status='PASS', qualification='PASS',
                     scope='SOURCE_ONLY_PRIOR_CLAIM_FIXTURE_NOT_RUNTIME_EVIDENCE')
    monkeypatch.setattr(worker, '_current_step_producer_authority', lambda *a, **kw: (True, 'SOURCE_ONLY', 'PASS'))
    monkeypatch.setattr(worker, 'evaluate', lambda *a: {'status': 'PASS', 'step': {'id': native, 'status': 'PASS'}, 'ledger': []})
    backend = worker.execute_current_step(case.project, step_id=native, producer=produced)
    assert backend['verdict'] == 'PASS', backend
    receipt = case.put('reports/phase3/default_steps/19/backend_result.json', backend)
    version = versions.finish_step(case.project, attempt, verdict='PASS', result=backend, canonical_pass=True)
    selected = {r['id'] for r in plan['rows']}
    dependencies = (set(context['resolved_row']['acceptance_deps']) | {d['step'] for d in context['resolved_row']['data_deps']}) & selected
    for dep in dependencies:
        original = flow109.execution_context(plan, dep, dep)
        case.put('reports/flow109/requests/' + original['context_sha256'] + '.json', original)
        case.put('reports/flow109/default_rows/' + dep + '.json', {'step_id': dep, 'default_row_status': 'PASS', 'completed': True,
            'context_sha256': original['context_sha256'], 'scope': 'SOURCE_ONLY_DEPENDENCY_FIXTURE'})
    report = {'bounded': True, 'steps': [{'extras': {'canonical_steps': [{'status': 'PASS', 'detail': 'SOURCE_ONLY',
        'extras': {'step_id': '19', 'output_version': version['folder']}}]}}]}
    def consume():
        result = flow109.finish_native_window(case.project, report)
        case.put('SOURCE_ONLY_ROSTER_FINALIZATION.json', result)
        return result
    return SimpleNamespace(case=case, project=case.project, consume=consume, receipt=receipt,
        dependencies=dependencies, context=context, plan=plan)


def test_normal_finalizer_reuses_valid_admission_and_full_current_roster(scene):
    result = scene.consume()
    assert result['default_row_status'] == 'PASS', result
    assert result['components'][0]['metric_acceptance']['obligations'][0]['status'] == 'PASS'
    assert result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False


def test_normal_finalizer_missing_admission_keeps_full_metrics_ni(scene):
    (scene.project / 'qualifications.json').unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED'
    assert result['components'][0].get('metric_acceptance', {}).get('metric_status') == 'PASS'


@pytest.mark.parametrize('late_ni', ['admission', 'dependency', 'version'])
def test_normal_finalizer_keeps_fresh_sink_fail_before_late_ni(scene, late_ni):
    scene.case.roster(4, transcript({'core_clock': ['r0/CLK']}))
    if late_ni == 'admission':
        (scene.project / 'qualifications.json').unlink()
    elif late_ni == 'dependency':
        dep = sorted(scene.dependencies)[0]
        (scene.project / 'reports/flow109/default_rows' / (dep + '.json')).unlink()
    else:
        for p in versions._versions_root(scene.project).glob('**/outputs.json'):
            p.unlink()
    result = scene.consume()
    assert result['default_row_status'] == 'FAIL', result
    assert result['components'][0]['metric_acceptance']['obligations'][0]['status'] == 'FAIL'


@pytest.mark.parametrize('broken', ['receipt', 'wrong_context', 'dependency'])
def test_normal_finalizer_rejects_unbound_prior_pass(scene, monkeypatch, broken):
    if broken == 'receipt':
        body = json.loads(scene.receipt.read_text());body['source_sha'] = 'FOREIGN'
        scene.receipt.write_text(json.dumps(body))
    elif broken == 'dependency':
        dep = sorted(scene.dependencies)[0]
        (scene.project / 'reports/flow109/default_rows' / (dep + '.json')).unlink()
    else:
        authority = scene.case.put('other-qualification.json', (scene.project / 'qualifications.json').read_text())
        context = flow109.execution_context(scene.plan, 'D38', 'D38',
            runtime_tool_uses=scene.context['runtime_tool_uses'], qualification_registry=authority.name)
        path = scene.case.put('reports/flow109/requests/' + context['context_sha256'] + '.json', context)
        monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
        monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(scene.project, context)))
    result = scene.consume()
    assert result['default_row_status'] == 'NOT_MEASURED', result
    assert 'reason' in result['components'][0]


def test_complete_observation_does_not_author_new_requirements_for_unused_spare_pins(case):
    case.roster(4, transcript(all_pins=['r0/CLK', 'r1/CLK', 'unused_spare/CLK']))
    observation = accepted(case.run())
    assert observation['metric_status'] == 'PASS', observation
    coverage = observation['obligations'][0]
    assert coverage['observed_rosters']['fast_case']['unclocked'] == ['unused_spare/CLK']
    assert coverage['measurements'][1]['measurement']['value'] == case.required


def test_required_pin_cannot_be_reached_by_an_additional_wrong_clock(case):
    case.roster(4, transcript({'core_clock': ['r0/CLK', 'r1/CLK'], 'other_clock': ['r1/CLK']}))
    result = case.run()
    assert result['verdict'] == 'FAIL', result
    assert accepted(result)['obligations'][0]['status'] == 'FAIL'


def test_actual_derived_cts_config_is_bound_without_guessing_its_filename(case):
    runner, _, _, _ = producer._parameters(case.project, {})
    def policy(configs, *args, **kwargs):
        selected = dict(configs)
        original = configs['OpenROAD.CTS']
        body = json.loads(original.read_text())
        body['EXTRA_EXCLUDED_CELLS'] = ['SOURCE_ONLY_EXCLUDED_MASTER']
        derived = original.with_name('OpenROAD.CTS.cell-policy.json')
        derived.write_text(json.dumps(body))
        selected['OpenROAD.CTS'] = derived
        case.receipts[str(case.folders[0])]['input']['config'] = old.sha(derived)
        return selected, ['OpenROAD.CTS']
    runner._resolved_cell_policy = policy
    result = case.run()
    assert accepted(result)['metric_status'] == 'PASS', result
    handoff = json.loads((case.project / 'reports/phase3/librelane_cts_handoff.json').read_text())
    assert handoff['step_configs'][0]['path'].endswith('OpenROAD.CTS.cell-policy.json')
    assert handoff['step_configs'][0]['sha256'] == case.receipts[str(case.folders[0])]['input']['config']
