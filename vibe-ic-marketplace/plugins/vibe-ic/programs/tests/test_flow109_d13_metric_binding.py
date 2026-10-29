"""D13 source controls with explicit SOFTWARE authority/native/upstream fixtures.

These records exercise real normal consumers; they grant no native, product,
or whole-IC credit. Actual retained native reset controls are separate.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import _l10_execution as cases
import arith_oracle_tb_gen as arithmetic
import verilator_coverage_measure as coverage
import design_one_shot_runner as owner
from test_flow109_d11_metric_binding import case as lint_case, put, ref, sha


def qualified_context(project):
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
        if p['name'] == 'Small digital IC without DFT'))
    entries, runtime = [], []
    proof = project / 'input/qualification/D13/SOFTWARE_ONLY.json'
    put(proof, {'scope': 'SOFTWARE_FIXTURE_NOT_NATIVE_QUALIFICATION'})
    for tool, steps in metrics.D13_TOOL_STEPS.items():
        config = project / ('input/qualification/D13/' + tool + '.json')
        put(config, {'purpose': metrics.D13_PURPOSE, 'tool_id': tool,
                     'native_steps': steps, 'model_sources': metrics.d13_model_sources()})
        executable = Path(shutil.which(tool)).resolve()
        identity = {'use_id': 'flow109.D13.default.' + tool, 'tool_id': tool,
            'version': 'SOFTWARE_FIXTURE', 'build_sha256': sha(executable),
            'executable': {'path': str(executable), 'sha256': sha(executable)}, 'config': ref(project, config),
            'pdk': {'applicable': False, 'reason': 'SOFTWARE RTL scope'},
            'deck': {'applicable': False, 'reason': 'no physical deck'}, 'corner': 'RTL',
            'semantics': {'purpose': 'D13.default', 'native_steps': steps}}
        entry = {'use_id': identity['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                 'reference_evidence': [ref(project, proof)]}
        entries.append(entry);runtime.append({**identity, 'qualification_sha256': admission.canonical_sha(entry)})
    registry = project / 'input/qualification/D13/registry.json'
    put(registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': entries})
    return flow109.execution_context(flow109.resolve_plan(features), 'D13', 'D13',
        runtime_tool_uses=runtime, qualification_registry=str(registry.relative_to(project)))


def seal_software_authority(project, source):
    """Only source-test fixture construction, never a product authority writer."""
    path = project / 'input/flow109/D13/source.json';put(path, source)
    approval = {'status': 'APPROVED', 'authority': 'requirements_owner', 'source_reference': ref(project, path)}
    for name in ('required_function_scenarios', 'coverage_targets'):
        put(project / ('requirements/base_07/' + name + '.json'),
            {'schema': metrics.AUTHORITY_SCHEMA, 'approval': approval, **source[name]})
    put(project / 'adopted/base_07/simulation_execution.json',
        {'schema': 'vibeic.flow109.adopted-reference.v1', 'approval': approval, 'reference': source['execution']})


@pytest.fixture
def case(lint_case):
    p = lint_case['project']
    accepted = metrics.accept_d11(p, lint_case['context']);assert accepted['status'] == 'PASS'
    flow109._selected_step_result(p, lint_case['context'], {'step_id': 'D11',
        'context_sha256': lint_case['context']['context_sha256'], 'component_status': 'PASS',
        'default_row_status': 'PASS', 'completed': True, 'metric_acceptance': accepted})
    l10 = p / 'phase1/generated_docs/L10_TEST_CASES.json'
    put(l10, {'test_cases': [{'name': 'binary_case', 'kind': 'functional_vector',
                            'stimulus': 'operand boundaries', 'expected': 'binary comparisons'}]})
    put(p / 'phase1/generated_docs/L22_VERIFICATION_PLAN.json', {'ic_class': 'digital_arithmetic_primitive'})
    put(p / 'plugin_output/declaration.json', {'scope': 'SOFTWARE_SOURCE_CONTROL'})
    declared = {'top': 'neutral', 'width': 4, 'operator': '*', 'integer_encoding': 'unsigned',
        'bit_order': 'LSB', 'latency': 1, 'latency_origin': 'post_nba_sample_offset',
        'transaction_rearm': 'clocked_reset', 'rearm_reset_cycles': 1,
        'parallel_hold': 'through_final_product_bit'}
    rtl = p / 'phase2/stage1/rtl/neutral.v'
    plan = {'schema': 'vibeic.arithmetic_scenario.v1', 'case': 'binary_case', 'scenario': 'operand_boundaries',
        'binding': {str(rtl): sha(rtl)}, 'spec': {'top': 'neutral', 'width': 4, 'operator': '*', 'signed': False},
        'framing': {k: v for k, v in declared.items() if k not in ('top', 'width', 'operator', 'integer_encoding')},
        'pairs': [[0, 0], [1, 1]], 'transactions': 2, 'comparisons': 8}
    tb = p / 'phase2/stage1/sim/tb/binary_case.v'
    put(tb, arithmetic.ARITHMETIC_SCENARIO_HEADER + json.dumps(plan) + '\nmodule binary_case; endmodule\n')
    transcript = p / 'phase2/stage1/sim_professional/binary_case/run.log'
    put(transcript, 'SOFTWARE_ONLY_NOT_NATIVE_EXECUTION\nARITH_SCENARIO_DONE transactions=2 comparisons=8 errors=0 held_edges=0\n')
    measured, _ = arithmetic.capture_arithmetic_scenario_execution(p, tb, transcript, {str(rtl): sha(rtl)})
    record = cases.write_record(p, l10, [{'id': 'binary_case', 'tb_file': str(tb),
        'verdict': 'PASS', 'sim_executed': True, 'arithmetic_scenario': measured}], producer='SOFTWARE_SOURCE_CONTROL')
    junit = p / 'phase2/stage1/sim_professional/binary_case/results.xml'
    put(junit, '<testsuite tests="1" failures="0" errors="0"><testcase name="binary"/></testsuite>')
    dat = p / 'phase2/stage1/sim/cov/coverage.dat'
    scope = [str(p / f['path']) for f in metrics.d11_subject(p)['source_files'] if Path(f['path']).suffix in ('.v', '.sv')]
    lines = []
    for path in scope:
        for category in ('line', 'toggle', 'branch'):
            lines.append("C 'page\x02v_" + category + "/unit\x01f\x02" + path + "\x01l\x021\x01h\x02dut' 1\n")
    put(dat, ''.join(lines))
    union = coverage.union_coverage_dats([str(dat)]);scoped = coverage.scope_totals(union, scope)
    info = dat.with_suffix('.info');put(info, ''.join('SF:' + path + '\nDA:1,1\nend_of_record\n' for path in scope))
    report = p / 'reports/phase2/coverage/coverage_verilator.json'
    put(report, {'tool': 'verilator', 'measurement_scope': 'union-of-suite', 'scope_files': scope,
        'totals': scoped['totals'], 'coverage_dat': str(dat), 'testbenches': [str(tb)],
        'per_testbench': {str(tb): {'measured': True, 'coverage_dat': str(dat)}},
        'line_union_cross_check': {'lcov_info': str(info)}})
    original = p / 'input/flow109/D13/original-owner.json'
    producer = p / 'runtime/design_one_shot_runner.py';put(producer, Path(owner.__file__).read_text())
    runner = p / 'runtime/phase2_one_shot_runner.py';put(runner, '# SOFTWARE_ORIGINAL_RUNNER\n')
    executable = Path(sys.executable)
    put(original, {'runner_binding': {'schema': 'vibeic.runner_report_binding.v1', 'project': str(p),
        'invocation_id': 'software-original-native-scope', 'producer': ref(p, producer),
        'source': {'runner': ref(p, runner), 'consumer': ref(p, producer),
                   'executable': {'path': str(executable), 'sha256': sha(executable)}}}})
    launch = p / 'input/flow109/D13/original-launch.json'
    put(launch, {'scope': 'SOFTWARE_FIXTURE_NOT_NATIVE', 'cid': '1' * 64, 'image_id': 'sha256:' + '2' * 64})
    terminal = p / 'input/flow109/D13/original-terminal.json'
    put(terminal, {'scope': 'SOFTWARE_FIXTURE_NOT_NATIVE', 'host_exit_verified': True,
        'docker_cli_exit_code': 0, 'host_die_event_exit_code': 0, 'source_unchanged': True})
    source = {'purpose': metrics.D13_PURPOSE, 'project': str(p), 'fixture_scope': 'SOFTWARE_AUTHORITY_ONLY',
        'subject': metrics.d13_subject(p), 'source_refs': [ref(p, l10)], 'declared': declared,
        'required_function_scenarios': {'required_items': [{'name': 'binary_case'}]},
        'scenario_requirements': {'binary_case': {'scenario': 'operand_boundaries', 'minimum_transactions': 2}},
        'coverage_targets': {'limits': {'toggle': {'min': 95}, 'branch': {'min': 95}},
            'units': {'toggle': 'percent', 'branch': 'percent'}, 'acceptance_applicable': False,
            'reason': 'SOFTWARE source-classification fixture; measurement remains mandatory'},
        'execution': {'project': str(p), 'original_owner': ref(p, original),
            'original_invocation': 'software-original-native-scope', 'original_producer': ref(p, producer),
            'original_launch': ref(p, launch), 'original_terminal': ref(p, terminal),
            'scenario_record': ref(p, record), 'coverage_report': ref(p, report),
            'unit_junit': ref(p, junit), 'streaming_junit': ref(p, junit)}}
    source['execution']['artifacts'] = [ref(p, x) for x in p.rglob('*') if x.is_file()]
    seal_software_authority(p, source)
    return p, qualified_context(p), source


def test_d13_all_three_actual_consumers_and_current_d11_row_shape(case):
    p, context, _ = case
    result = metrics.accept_d13(p, context)
    assert result['status'] == 'PASS', result
    assert [r['status'] for r in result['obligations']] == ['PASS'] * 3


@pytest.mark.parametrize('changed', ['rtl', 'record', 'coverage', 'missing_authority', 'unqualified'])
def test_d13_refuses_stale_partial_or_unqualified_inputs(case, changed):
    p, context, source = case
    if changed == 'missing_authority':(p / 'requirements/base_07/coverage_targets.json').unlink()
    elif changed == 'unqualified':
        context = flow109.execution_context(flow109.resolve_plan(context['features']), 'D13', 'D13')
    else:
        path = p / {'rtl': source['subject']['rtl']['source_files'][0]['path'],
                    'record': source['execution']['scenario_record']['path'],
                    'coverage': source['execution']['coverage_report']['path']}[changed]
        path.write_bytes(path.read_bytes() + b'\nchanged\n')
    result = metrics.accept_d13(p, context)
    assert result['status'] == 'NOT_MEASURED', result


@pytest.mark.parametrize('applicable,expected', [(False, 'PASS'), (True, 'FAIL')])
def test_d13_actual_target_failure_keeps_source_applicability_separate(case, applicable, expected):
    p, context, source = case
    # Tighten only this SOFTWARE fixture to obtain a deterministic actual
    # target failure. Original product bounds/normal authority are untouched.
    source['coverage_targets']['limits']['toggle']['min'] = 101
    source['coverage_targets']['acceptance_applicable'] = applicable
    seal_software_authority(p, source)
    result = metrics.accept_d13(p, context)
    assert result['obligations'][2]['status'] == 'FAIL', result
    assert result['obligations'][2]['measurement_complete'] is True
    assert result['obligations'][2]['acceptance_applicable'] is applicable
    assert result['status'] == expected, result


def test_d13_required_comparator_failure_wins_beside_missing_coverage(case):
    p, context, source = case
    transcript = p / 'phase2/stage1/sim_professional/binary_case/run.log'
    transcript.write_text(transcript.read_text().replace('errors=0', 'errors=1'))
    row = cases.load_record(p, p / 'phase1/generated_docs/L10_TEST_CASES.json')['rows']['binary_case']
    row['arithmetic_scenario'], _ = arithmetic.capture_arithmetic_scenario_execution(
        p, Path(row['tb_file']), transcript, row['arithmetic_scenario']['sources'])
    row['id'] = 'binary_case';row['verdict'] = 'FAIL'
    record = cases.write_record(p, p / 'phase1/generated_docs/L10_TEST_CASES.json', [row], producer='SOFTWARE_SOURCE_CONTROL')
    for path in (record, transcript):
        relative = str(path.relative_to(p))
        next(r for r in source['execution']['artifacts'] if r['path'] == relative)['sha256'] = sha(path)
    source['execution']['scenario_record'] = ref(p, record)
    seal_software_authority(p, source)
    (p / source['execution']['coverage_report']['path']).unlink()
    result = metrics.accept_d13(p, context)
    assert [r['status'] for r in result['obligations']] == ['FAIL', 'FAIL', 'NOT_MEASURED'], result
    assert result['status'] == 'FAIL'


def test_d13_actual_owner_and_canonical_writer_preserve_aggregate_scope(case, monkeypatch):
    import benchmark_dispatch as dispatch
    import vibe_ic_one_shot_runner as public
    p, context, _ = case
    path = p / 'reports/flow109/context.json';put(path, context)
    attempt = flow109._new_attempt(p, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path));monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    argv = [sys.executable, str(Path(owner.__file__).with_name('phase2_one_shot_runner.py')), str(p),
            '--entry-step', '4', '--exit-step', '4']
    invocation = {'invocation_id': 'software-normal-d13-owner', 'argv': argv, 'project': str(p),
                  'source': dispatch._runner_source_snapshot(argv)}
    assert owner._publish_d13_owner(p, context, invocation_context=invocation) == 0
    assert not (attempt / 'result.json').exists()
    report = json.loads((attempt / 'phase2_one_shot.json').read_bytes())
    finished = public._finish_d13_selected_owner(p, report, invocation, published_current=True)
    assert finished['verdict'] == 'PASS', finished
    result = json.loads((attempt / 'result.json').read_bytes())
    assert result['components'][0]['completed'] is True
    assert result['components'][0]['flow109_acceptance'] == 'PASS'
    assert result['flow109_acceptance'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    paths = [attempt / 'result.json', attempt / 'phase2_one_shot.json']
    before = [(f.read_bytes(), f.stat().st_mtime_ns) for f in paths]
    assert owner._publish_d13_owner(p, context) == 2
    assert [(f.read_bytes(), f.stat().st_mtime_ns) for f in paths] == before


def test_d13_owner_rereads_actual_changed_source(case, monkeypatch):
    p, context, _ = case
    path = p / 'reports/flow109/context.json';put(path, context)
    attempt = flow109._new_attempt(p, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path));monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    observed = [];old = sys.getprofile()
    def observe(frame, event, value):
        if event == 'return' and frame.f_code is metrics.accept_d13.__code__:
            observed.append(value['status'])
            if len(observed) == 1:
                rtl = p / 'phase2/stage1/rtl/neutral.v';rtl.write_bytes(rtl.read_bytes() + b'\nchanged\n')
        if old:old(frame, event, value)
    sys.setprofile(observe)
    try:rc = owner._publish_d13_owner(p, context)
    finally:sys.setprofile(old)
    assert observed == ['PASS', 'NOT_MEASURED']
    assert rc == 2
    assert not (attempt / 'result.json').exists()
    report = json.loads((attempt / 'phase2_one_shot.json').read_bytes())
    assert report['steps'][0]['extras']['completed'] is False
    assert report['steps'][0]['extras']['metric_acceptance']['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('report_state,expected', [('current', 'PASS'), ('missing', 'NOT_MEASURED')])
def test_d13_actual_no_skip_public_and_child_current_report(case, monkeypatch, report_state, expected):
    import benchmark_dispatch as dispatch
    from types import SimpleNamespace
    from test_flow109_selection import _public_d09_entry
    p, context, _ = case
    runner = _public_d09_entry(p, monkeypatch)
    put(p / 'manifest.json', {k: context[k] for k in ('features', 'runtime_tool_uses', 'qualification_registry')})
    argv = [a for a in sys.argv if a not in ('--skip-phase1', '--skip-phase3', '--skip-analog')]
    for flag in ('--entry-step', '--exit-step'):argv[argv.index(flag) + 1] = 'D13'
    monkeypatch.setattr(sys, 'argv', argv)
    assert not set(argv).intersection({'--skip-phase1', '--skip-phase3', '--skip-analog'})
    original = p / 'reports/orchestrator/phase2_one_shot.json';original.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path('/controls/ORIGINAL_ACCEPTED_D09_PHASE2_REPORT.json'), original)
    before = original.read_bytes(), original.stat().st_mtime_ns
    calls = []
    def child(command, *, env=None, **_kwargs):
        assert command[command.index('--entry-step') + 1] == command[command.index('--exit-step') + 1] == '4'
        calls.append(json.loads(env[dispatch._RUNNER_CONTEXT_ENV]))
        with monkeypatch.context() as m:
            for key, value in env.items():m.setenv(key, value)
            m.setattr(sys, 'argv', command[1:])
            m.setattr(owner, '_activate_runtime_program_tree', lambda _p: None)
            m.setattr(owner, '_bootstrap_execution_policy', lambda *_a, **_k: None)
            m.setattr(owner, 'step_reused_ip_consume', lambda *_a: None)
            site = next(name for name, span in owner._spf.RUNNER_PLANS['design_one_shot_runner'].sites if '4' in span)
            m.setattr(owner._spf, 'entry_admission', lambda *_a: {'admitted': True, 'site': site})
            rc = owner.main()
        if report_state == 'missing':(Path(env[flow109.ATTEMPT_ENV]) / 'phase2_one_shot.json').unlink()
        return SimpleNamespace(returncode=rc)
    monkeypatch.setattr(runner.subprocess, 'run', child)
    assert runner._main() == (0 if expected == 'PASS' else 1)
    assert len(calls) == 1
    result = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_bytes())
    summary = json.loads((p / 'reports/orchestrator/vibe_ic_one_shot.json').read_bytes())
    assert summary['dispatched_verdict'] == expected, summary
    assert result['default_row_status'] == expected
    assert result['components'][0]['completed'] is (expected == 'PASS')
    assert result['flow109_acceptance'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['delivery_accepted'] is False
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
