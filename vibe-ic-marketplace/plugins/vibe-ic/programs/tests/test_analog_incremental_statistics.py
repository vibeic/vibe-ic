"""Cohort protocol controls; synthetic captures are not native ADC evidence."""
import json
from pathlib import Path
import multiprocessing
import time

import pytest

import analog_incremental_capture as capture
import analog_incremental_statistics as stats
from test_analog_incremental_pvt import method as pvt_method, _native_fixture_series


@pytest.fixture
def method(pvt_method):
    project, settings, library = pvt_method
    wrapper = project / "mismatch devices.lib"
    wrapper.write_text(".subckt fixture_fet d g s b params: w=2u l=1u\n"
                       "+ mm_ok=0\n"
                       "Ncore d g s b fixture_model\n"
                       "+ w='agauss(w,1e-9,(mm_ok!=1?0:1))'\n"
                       "+ l=l delvto='agauss(0,.01,(mm_ok!=1?0:1))'\n"
                       ".ends fixture_fet\n")
    library.write_text('.lib device_tt\n.param nominal=1\n.endl device_tt\n'
                       '.lib device_tt_stat\n.param process_only=agauss(1,.01,1)\n.endl device_tt_stat\n'
                       '.lib device_tt_mismatch\n.include "mismatch devices.lib"\n.endl device_tt_mismatch\n')
    net = project / "phase3/analog/converter/converter.sp"
    net.write_text(net.read_text().replace('.ends conv',
        'xm1 dout ain 0 0 fixture_fet w=2u l=1u\nxm2 dout ain 0 0 fixture_fet w=2u l=1u\n.ends conv'))
    return project, settings, library, wrapper


def prepared(method, root, **kwargs):
    return stats.prepare(method[0], "converter", method[1], root, 2,
        image="fixture-image", reference_ports=['ref_hi', 'ref_lo'], **kwargs)


def _probes(manifest):
    return [manifest['disabled_control']['control']] + [probe for row in manifest['cohorts'] for probe in row['probes']]


def _write_probe(manifest, probe, *, values=None, code=0, suffix='', temperature=27):
    directory = Path(probe['receipt']).parent
    inputs = {'deck': probe['deck']}
    inputs.update(stats.bound.consumed_input_views(Path(probe['project']), Path(probe['deck']['path'])))
    values = values or {field['key']: (1.0 if 'disabled' in probe['deck']['path'] else 1 + probe['seed'] / 100)
                        for field in manifest['fingerprint_bindings']}
    log = directory / 'native.log'
    log.write_text(f'Doing analysis at TEMP = {temperature} and TNOM = 27\n' +
                   '\n'.join(f'{key}= {value:.17g}' for key, value in values.items()) + '\n' + suffix)
    record = {'status': 'PASS', 'image': manifest['image'], 'native_inputs': inputs,
              'fingerprint': {'fp_0000': 99},  # Deliberately untrusted cached values.
              'execution': {'returncode': code, 'log': str(log), 'log_sha256': stats.bound.sha(log),
                            'argv': ['ngspice', '-b', probe['deck']['path']]}}
    Path(probe['receipt']).write_text(json.dumps(record))
    return record


def populate(manifest):
    for probe in _probes(manifest):
        _write_probe(manifest, probe)
    for cohort in manifest['cohorts']:
        _native_fixture_series({**cohort, 'temperature_c': 27})
    return manifest


def test_prepare_preserves_original_bytes_and_same_chip_seed_across_phases(method, tmp_path, monkeypatch):
    before = {str(path): path.read_bytes() for path in method[0].rglob('*') if path.is_file()}
    monkeypatch.setattr(capture, 'series_main', lambda *a: pytest.fail('prepare cannot run native'))
    manifest = prepared(method, tmp_path / 'chips')
    assert manifest['status'] == 'PASS' and [row['seed'] for row in manifest['cohorts']] == [1, 2]
    assert manifest['sections'][0]['section'] == 'device_tt_mismatch'
    assert len(manifest['fingerprint_bindings']) == 4
    assert {row['parameter'] for row in manifest['fingerprint_bindings']} == {'w', 'delvto'}
    assert stats._validate(manifest)[0] == manifest['cohorts']
    for cohort in manifest['cohorts']:
        text = Path(cohort['native_inputs']['testbench']['path']).read_text()
        assert text.splitlines()[1] == f".option seed={cohort['seed']}"
        assert text.index('.option seed') < text.index('.include')
        assert [probe['phase_index'] for probe in cohort['probes']] == [0, 16]
        for probe in cohort['probes']:
            deck = Path(probe['deck']['path']).read_text()
            assert 'tran 1e-10 1e-9' in deck and 'wrdata ' not in deck
            assert 'let a09_fp_0000 = @n.xdut.xm1.ncore[delvto]' in deck
    assert [sum(row['switch_edits'] for row in variant['files']) for variant in manifest['model_copies']] == [1, 0]
    assert all(Path(path).read_bytes() == data for path, data in before.items())


def test_collect_absent_controls_or_series_is_unmeasured_and_never_runs(method, tmp_path, monkeypatch):
    manifest = prepared(method, tmp_path / 'chips')
    monkeypatch.setattr(capture, 'series_main', lambda *a: pytest.fail('collect cannot run native'))
    result = stats.collect(manifest)
    assert result['status'] == 'NOT_MEASURED'
    assert result['metrics']['samples_executed'] == 0 and result['metrics']['mc_yield_pct'] is None


def test_complete_cohorts_replay_raw_captures_and_native_parameters(method, tmp_path):
    manifest = populate(prepared(method, tmp_path / 'chips'))
    result = stats.collect(manifest)
    assert result['status'] == 'PASS', result
    assert result['metrics']['samples_executed'] == 2 and result['metrics']['mc_yield_pct'] == 100
    assert result['metrics']['mc_source_coverage']['missing'] == []
    assert all(row['activation_proven'] and row['measurements']['enob'] < 99
               and row['measurements']['vref'] == 1 for row in result['metrics']['cohorts'])
    assert any('probe_log:' in key for key in result['native_inputs'])


@pytest.mark.parametrize('mutation', ['different_phase', 'disabled', 'same_seed', 'missing_parameter', 'wrong_temp'])
def test_metadata_or_unproved_variation_cannot_supply_statistical_yield(method, tmp_path, mutation):
    manifest = populate(prepared(method, tmp_path / 'chips'))
    probe = manifest['cohorts'][0]['probes'][1]
    keys = [field['key'] for field in manifest['fingerprint_bindings']]
    if mutation == 'different_phase':
        _write_probe(manifest, probe, values=dict.fromkeys(keys, 1.03))
    elif mutation == 'disabled':
        for probe in manifest['cohorts'][0]['probes']:
            _write_probe(manifest, probe, values=dict.fromkeys(keys, 1.0))
    elif mutation == 'same_seed':
        for probe in manifest['cohorts'][1]['probes']:
            _write_probe(manifest, probe, values=dict.fromkeys(keys, 1.01))
    elif mutation == 'missing_parameter':
        _write_probe(manifest, probe, values={keys[0]: 1.01})
    else:
        _write_probe(manifest, probe, temperature=-40)
    result = stats.collect(manifest)
    assert result['status'] == 'NOT_MEASURED', result
    assert result['metrics']['mc_yield_pct'] is None


@pytest.mark.parametrize('code,suffix,status', [(1, '', 'FAIL'), (0, ';;RESIDUAL_FAIL bad\n', 'FAIL'),
    (143, '', 'NOT_MEASURED'), (124, '', 'NOT_MEASURED'), (None, '', 'NOT_MEASURED')])
def test_native_failure_or_interruption_overrides_cached_pass(method, tmp_path, code, suffix, status):
    manifest = prepared(method, tmp_path / 'chips')
    probe = manifest['cohorts'][0]['probes'][0]
    _write_probe(manifest, probe, code=code, suffix=suffix)
    result = stats.collect(manifest)
    assert result['status'] == status, result


@pytest.mark.parametrize('mutation', ['source', 'model_copy', 'seed', 'geometry', 'score_setting', 'point_temp'])
def test_changed_source_model_seed_or_chip_context_refuses_reuse(method, tmp_path, mutation):
    manifest = populate(prepared(method, tmp_path / 'chips'))
    cohort = manifest['cohorts'][0]
    if mutation in ('source', 'model_copy'):
        path = method[3] if mutation == 'source' else Path(manifest['model_copies'][0]['files'][0]['copy']['path'])
        path.write_text(path.read_text() + '\n.param altered=1\n')
    elif mutation in ('seed', 'geometry'):
        role = 'testbench' if mutation == 'seed' else 'netlist'
        path = Path(cohort['native_inputs'][role]['path'])
        path.write_text(path.read_text().replace('seed=1', 'seed=2') if mutation == 'seed'
                        else path.read_text().replace('w=2u', 'w=3u'))
        cohort['native_inputs'][role] = stats._view(path)  # Resealed metadata cannot hide the electrical change.
    else:
        score = Path(cohort['score']); record = json.loads(score.read_text())
        point_path = Path(record['points'][0]['path']); point = json.loads(point_path.read_text())
        if mutation == 'score_setting':
            point['settings']['numerical_options'] = {'reltol': .001}
        else:
            log = Path(point['executions'][0]['log']); log.write_text(log.read_text().replace('27.000000', '-40.000000'))
            point['executions'][0]['log_sha256'] = stats.bound.sha(log)
        point_path.write_text(json.dumps(point)); record['points'][0] = stats._view(point_path)
        score.write_text(json.dumps(record))
    assert stats.collect(manifest)['status'] == 'NOT_MEASURED'


def test_probe_runner_is_explicit_and_does_not_retry_a_terminal_case(method, tmp_path):
    manifest = prepared(method, tmp_path / 'chips')
    seen = []
    def run(program, argv, *, cwd):
        seen.append((program, argv))
        probe = next(probe for probe in _probes(manifest) if probe['deck']['path'] == argv[-1])
        return _write_probe(manifest, probe)['execution']
    assert stats.run_probes(manifest, run, 'fixture-image') == ['PASS'] * 5
    assert len(seen) == 5 and all(program == '@env' and 'OMP_WAIT_POLICY=PASSIVE' in argv for program, argv in seen)
    assert stats.run_probes(manifest, run, 'fixture-image') == ['PASS'] * 5
    assert len(seen) == 5


def test_no_declared_random_mismatch_or_switch_refuses_prepare(method, tmp_path):
    method[3].write_text(method[3].read_text().replace('mm_ok=0', 'mm_ok=1'))
    with pytest.raises(ValueError, match='declared mm_ok'):
        prepared(method, tmp_path / 'chips')


def test_real_reference_violation_survives_missing_other_chip(method, tmp_path):
    spec_path = method[0] / 'phase3/analog/converter/spec.json'
    spec = json.loads(spec_path.read_text())
    next(row for row in spec['specs'] if row['name'] == 'vref')['max'] = .9
    spec_path.write_text(json.dumps(spec))
    manifest = prepared(method, tmp_path / 'chips')
    for probe in _probes(manifest):
        _write_probe(manifest, probe)
    _native_fixture_series({**manifest['cohorts'][0], 'temperature_c': 27})
    result = stats.collect(manifest)
    assert result['status'] == 'FAIL'
    assert result['metrics']['spec_yield']['vref']['yield_pct'] == 0
    assert result['metrics']['mc_yield_pct'] is None


def test_query_metadata_and_changed_log_cannot_replace_native_parameters(method, tmp_path):
    manifest = populate(prepared(method, tmp_path / 'chips'))
    probe = manifest['cohorts'][0]['probes'][0]
    path = Path(probe['receipt']); record = json.loads(path.read_text())
    log = Path(record['execution']['log']); log.write_text('Doing analysis at TEMP = 27\n')
    record['execution']['log_sha256'] = stats.bound.sha(log)
    record['fingerprint'] = {field['key']: 1.01 for field in manifest['fingerprint_bindings']}
    path.write_text(json.dumps(record))
    assert stats.collect(manifest)['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('residual,status', [(False, 'NOT_MEASURED'), (True, 'FAIL')])
def test_chip_timeout_is_unmeasured_but_actual_native_failure_stays_fail(method, tmp_path, residual, status):
    manifest = populate(prepared(method, tmp_path / 'chips'))
    score_path = Path(manifest['cohorts'][0]['score']); score = json.loads(score_path.read_text())
    path = Path(score['points'][0]['path']); point = json.loads(path.read_text())
    point['executions'][0]['returncode'] = 124
    if residual:
        log = Path(point['executions'][0]['log']); log.write_text(log.read_text() + '\n;;RESIDUAL_FAIL actual\n')
        point['executions'][0]['log_sha256'] = stats.bound.sha(log)
    path.write_text(json.dumps(point)); score['points'][0] = stats._view(path)
    score_path.write_text(json.dumps(score))
    assert stats.collect(manifest)['status'] == status


def _nominal(method, root):
    paths = stats.pvt._paths(method[0], 'converter')
    context = {'project': str(method[0]), 'settings': stats._view(method[1]),
               'native_inputs': {role: stats._view(path) for role, path in paths.items()},
               'temperature_c': 27, 'score': str(root / 'score.json')}
    _native_fixture_series(context)
    return Path(context['score'])


@pytest.mark.parametrize('cached', [False, True])
def test_series_launch_requires_native_source_nominal_a07_raw_pass(method, tmp_path, cached):
    score = tmp_path / 'cached-score.json'
    score.write_text(json.dumps({'status': 'PASS', 'measurements': {'enob': 99}}))
    manifest = prepared(method, tmp_path / 'chips', nominal_score=score if cached else None)
    for probe in _probes(manifest):
        _write_probe(manifest, probe)
    def forbidden(*args):
        pytest.fail('missing native nominal A07 cannot launch chip series')
    result = stats.run(manifest, 'fixture-container', 'fixture-image', 4, 4, forbidden)
    assert result['status'] == 'NOT_MEASURED' and 'nominal A07' in result['detail']


def test_actual_source_nominal_replay_and_activation_allow_bounded_chip_series(method, tmp_path):
    score = _nominal(method, tmp_path / 'nominal')
    manifest = prepared(method, tmp_path / 'chips', nominal_score=score)
    for probe in _probes(manifest):
        _write_probe(manifest, probe)
    seen = []
    def launch(argv):
        seen.append(argv)
        cohort = next(row for row in manifest['cohorts'] if row['project'] == argv[0])
        _native_fixture_series({**cohort, 'temperature_c': 27})
        return 0
    result = stats.run(manifest, 'fixture-container', 'fixture-image', workers=6, cpus=3, launch=launch)
    assert result['status'] == 'PASS', result
    assert len(seen) == 2 and result['metrics']['execution_budget']['total_cpu_ceiling'] <= 3
    assert result['native_inputs']['nominal_A07_score'] == stats._view(score)
    assert all(int(argv[argv.index('--cpus') + 1]) == 1 for argv in seen)


def test_live_producer_cosmetic_change_does_not_rebind_frozen_inputs(method, tmp_path, monkeypatch):
    origin = tmp_path / 'mutable-producer.py'; origin.write_text('# initial producer\n')
    monkeypatch.setattr(stats, '__file__', str(origin))
    manifest = prepared(method, tmp_path / 'chips')
    snapshot = manifest['native_inputs']['producer']
    origin.write_text('# later cosmetic edit\n')
    assert stats._validate(manifest)[0] == manifest['cohorts']
    assert Path(snapshot['path']).read_text() == '# initial producer\n'
    Path(snapshot['path']).write_text('# altered retained snapshot\n')
    assert stats.collect(manifest)['status'] == 'NOT_MEASURED'


def test_two_callers_cannot_claim_the_same_native_parameter_case(method, tmp_path, monkeypatch):
    manifest = prepared(method, tmp_path / 'chips')
    cohorts, probes = stats._validate(manifest)
    probe, current = probes[0]
    monkeypatch.setattr(stats, '_validate', lambda _manifest: (cohorts, [(probe, current)]))
    claim = Path(probe['receipt']).parent / 'running.json'
    exists = Path.exists
    context = multiprocessing.get_context('fork')
    barrier = context.Barrier(2)
    def concurrent_empty_check(path):
        result = exists(path)
        if path == claim:
            barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(Path, 'exists', concurrent_empty_check)
    calls, queue = context.Value('i', 0), context.Queue()
    def native(program, argv, *, cwd):
        with calls.get_lock():
            calls.value += 1
        time.sleep(.05)
        return _write_probe(manifest, probe)['execution']
    def caller():
        queue.put(stats.run_probes(manifest, native, 'fixture-image'))
    processes = [context.Process(target=caller) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    results = [queue.get(timeout=2) for _ in processes]
    assert calls.value == 1
    assert sorted(result[0] for result in results) == ['NOT_MEASURED', 'PASS']


@pytest.mark.parametrize('mutation', ['project', 'block', 'default_template'])
def test_manifest_identity_cannot_misattribute_another_project_or_template(method, tmp_path, mutation):
    manifest = prepared(method, tmp_path / 'chips')
    if mutation == 'project':
        manifest['project'] = str(tmp_path / 'another-project')
    elif mutation == 'block':
        manifest['block'] = 'another_converter'
    else:
        original = Path(manifest['native_inputs']['testbench']['path'])
        alternate = original.with_name('unconfigured_template.sp')
        alternate.write_bytes(original.read_bytes())
        manifest['native_inputs']['testbench'] = stats._view(alternate)
    with pytest.raises(ValueError, match='project/block|testbench'):
        stats._validate(manifest)
    assert stats.collect(manifest)['status'] == 'NOT_MEASURED'
    with pytest.raises(ValueError, match='project/block|testbench'):
        stats.run_probes(manifest, lambda *a, **k: pytest.fail('wrong source cannot run'), 'fixture-image')


def test_explicit_common_template_is_accepted_with_the_exact_source_identity(method, tmp_path):
    canonical = method[0] / 'phase3/analog/converter/tb_converter.sp'
    alternate = canonical.with_name('configured_template.sp')
    alternate.write_bytes(canonical.read_bytes())
    common = json.loads(method[1].read_text()); common['testbench'] = str(alternate)
    method[1].write_text(json.dumps(common))
    manifest = prepared(method, tmp_path / 'chips')
    assert manifest['native_inputs']['testbench'] == stats._view(alternate)
    assert stats._validate(manifest)[0] == manifest['cohorts']
