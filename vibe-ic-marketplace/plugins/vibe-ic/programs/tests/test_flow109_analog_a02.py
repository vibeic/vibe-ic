"""A02 actual-ngspice component controls; these are not PDK signoff."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest

import flow109
import flow109_admission as admission
import flow109_analog_a02 as analog
import flow109_analog_model_check as model_check
from _analog_producer_fixture import block, make_project


def _put(project, name, body):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body, indent=2))
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _case(project, *, broken=False, missing_corner=False, transitive=False,
          pinned_ihp=False):
    make_project(project, [block('regulator_alpha', 'ldo',
        [{'name': 'Vout', 'target': 1.8, 'unit': 'V'}])])
    drc = _put(project, 'input/pdk/klayout/open_dev.drc', '# developer DRC inventory\n')
    lvs = _put(project, 'input/pdk/netgen/open_dev.tcl', '# developer LVS inventory\n')
    dependencies = []
    if pinned_ihp:
        source = Path('/foss/pdks/ihp-sg13g2/libs.tech/ngspice/models')
        assert source.is_dir(), 'pinned IHP model directory absent'
        target = project / 'input/pdk/spice/models'
        shutil.copytree(source, target)
        model_path = target / 'cornerMOSlv.lib'
        model = {'path': str(model_path.relative_to(project)),
                 'sha256': hashlib.sha256(model_path.read_bytes()).hexdigest()}
        dependencies = [
            {'path': str(path.relative_to(project)),
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(target.rglob('*')) if path.is_file() and path != model_path]
        device = 'not_the_declared_device' if broken else 'sg13_lv_nmos'
    else:
        device = 'not_the_declared_device' if broken else 'open_n'
        directive = ''
        if transitive:
            if transitive == 'lib':
                directive = '.lib open_dev_child.lib child_tt\n'
            else:
                directive = ('.include open_dev_child.lib\n' if transitive != 'unsupported'
                             else '.include open_dev_child.lib extra-token\n')
            if transitive not in ('missing', 'escape'):
                child_body = (
                    '.include open_dev_models.lib\n' if transitive == 'cycle' else
                    '.lib child_tt\n.model open_n nmos level=1 vto=0.5 kp=100u\n'
                    '.endl child_tt\n' if transitive == 'lib' else
                    '.model open_n nmos level=1 vto=0.5 kp=100u\n')
                child = _put(project, 'input/pdk/spice/open_dev_child.lib', child_body)
                if transitive != 'unbound':
                    dependencies.append(child)
                if transitive == 'symlink':
                    real = project / 'input/pdk/spice/open_dev_real_child.lib'
                    (project / child['path']).replace(real)
                    (project / child['path']).symlink_to(real.name)
                    child = {'path': str(real.relative_to(project)),
                             'sha256': hashlib.sha256(real.read_bytes()).hexdigest()}
                    dependencies[-1] = child
            if transitive == 'escape':
                outside = project.parent / (project.name + '-escaped-model.lib')
                outside.write_text('.model open_n nmos level=1\n')
                directive = f'.include ../../../../{outside.name}\n'
        model_body = ''.join(
            '.lib ' + corner + '\n' + directive
            + ('' if transitive else '.model ' + device
               + ' nmos level=1 vto=0.5 kp=100u\n')
            + '.endl ' + corner + '\n' for corner in ('ss', 'tt', 'ff'))
        model = _put(project, 'input/pdk/spice/open_dev_models.lib', model_body)
    smokes = []
    requested_corners = (('mos_tt',) if pinned_ihp else
                         ('ss', 'tt', 'absent') if missing_corner else ('ss', 'tt', 'ff'))
    for corner in requested_corners:
        instance = ('xprobe d g 0 0 sg13_lv_nmos w=10u l=0.13u\n'
                    if pinned_ihp else 'mprobe d g 0 0 open_n w=10u l=1u\n')
        deck = _put(project, f'input/flow109/decks/open_n_{corner}.sp',
            '* source-owned developer model smoke\n'
            f'.lib {model["path"]} {corner}\n'
            'vdrain d 0 1.2\nvgate g 0 0\n' + instance
            + '.dc vgate 0 1.2 0.6\n'
            '.measure dc drain_current find i(vdrain) at=1.2\n.end\n')
        smokes.append({'id': f'open_n_{corner}',
                       'device': ('sg13_lv_nmos' if pinned_ihp else 'open_n'), 'corner': corner,
                       'model': model, 'deck': deck,
                       'required_measurements': ['drain_current']})
    requirements = _put(project, 'input/flow109/A02-requirements.json', {
        'schema': analog.SCHEMA,
        'approval': {'status': 'APPROVED', 'authority': 'requirements_owner',
                     'source_reference': 'developer open-model A02 control'},
        'required_smokes': smokes})
    declared_models = [model] + dependencies
    _present, spice_inventory_path = analog.completeness._axis_status(project, 'spice_models')
    spice_inventory = {'path': spice_inventory_path,
                       'sha256': hashlib.sha256(
                           (project / spice_inventory_path).read_bytes()).hexdigest()}
    pdk = _put(project, 'input/flow109/A02-pdk.json', {
        'schema': analog.SCHEMA, 'name': 'open-developer-model',
        'model_files': declared_models,
        'inventory_files': {'spice_models': spice_inventory,
                            'drc_deck': drc, 'lvs_deck': lvs}})
    config = _put(project, analog.INPUT, {
        'schema': analog.SCHEMA, 'basis': 'declared_model_device_smoke',
        'pdk': pdk, 'requirements': requirements, 'smokes': smokes})

    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Analog model-IP')
    plan = flow109.resolve_plan(features)
    use = flow109.resolve_step(plan, 'A02')['tool_uses'][0]
    binary = Path(shutil.which('ngspice')).resolve()
    executable = {'path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    identity = {'use_id': use['use_id'], 'tool_id': 'ngspice',
                'version': subprocess.run([binary, '-v'], capture_output=True, text=True).stdout.strip(),
                'build_sha256': executable['sha256'], 'executable': executable,
                'config': config, 'pdk': pdk, 'deck': requirements,
                'corner': sorted(requested_corners),
                'semantics': {'purpose': use['purpose'], 'native_steps': use['native_steps'],
                              'operation_sources': analog.operation_sources()}}
    reference = _put(project, 'input/flow109/A02-reference.json', {
        'scope': 'developer control only', 'native_engine': 'ngspice',
        'signoff': 'NOT_MEASURED'})
    record = {'use_id': use['use_id'], 'status': 'QUALIFIED', 'identity': identity,
              'reference_evidence': [reference]}
    registry = {'schema': 'vibeic.flow109.qualifications.v1', 'uses': [record]}
    manifest = {'features': features, 'qualification_registry': 'qualifications.json',
                'runtime_tool_uses': [{**identity,
                    'qualification_sha256': admission.canonical_sha(record)}]}
    (project / 'qualifications.json').write_text(json.dumps(registry))
    (project / 'manifest.json').write_text(json.dumps(manifest))
    return manifest, registry, model


def _run(project):
    return subprocess.run([
        'python3', str(analog.HERE / 'vibe_ic_one_shot_runner.py'), str(project),
        '--flow', '109', '--flow109-manifest', str(project / 'manifest.json'),
        '--entry-step', 'A02', '--exit-step', 'A02', '--route', 'ip', '--no-dashboard'],
        capture_output=True, text=True)


def test_actual_a02_runs_declared_model_device_smoke_and_keeps_signoff_unmeasured(tmp_path):
    _case(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A02.json').read_text())
    assert report['component_status'] == 'PASS'
    assert report['flow109_acceptance'] == 'NOT_MEASURED'
    assert report['inventory']['verdict'] == 'PASS' and report['inventory']['waivers'] == 0
    assert len(report['smokes']) == 3 and all(row['returncode'] == 0 for row in report['smokes'])
    assert all(row['executed_model']['path'].startswith('reports/flow109/attempts/A02-')
               and row['executed_deck']['path'].startswith('reports/flow109/attempts/A02-')
               for row in report['smokes'])
    assert {row['corner'] for row in report['consumer']['smokes']} == {'ss', 'tt', 'ff'}
    assert all(row['measurements']['drain_current'] != 0 for row in report['consumer']['smokes'])
    assert report['unimplemented_obligations'] == [
        'base_A2.device_model_load_errors', 'base_A2.model_corner_statistics_coverage']
    freeze = json.loads((tmp_path / analog.FREEZE).read_text())
    assert freeze['status'] == 'PASS' and 'signoff NOT_MEASURED' in freeze['scope']


def test_broken_declared_device_is_a_native_failure_not_a_pass(tmp_path):
    _case(tmp_path, broken=True)
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A02.json').read_text())
    assert report['component_status'] == 'FAIL'
    assert report['reason'] in ('A02_NATIVE_MODEL_LOAD_FAILED', 'A02_NATIVE_MEASUREMENT_ABSENT')
    assert report['native_started'] is True
    assert not (tmp_path / analog.FREEZE).exists()


def test_missing_declared_model_refuses_before_ngspice_or_attempt(tmp_path):
    _manifest, _registry, model = _case(tmp_path)
    (tmp_path / model['path']).unlink()
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_STALE_OR_MISSING_INPUT' in result.stderr
    assert not (tmp_path / 'reports/flow109/attempts').exists()


def test_stale_model_bytes_refuse_before_ngspice(tmp_path):
    _manifest, _registry, model = _case(tmp_path)
    (tmp_path / model['path']).write_text('* changed after approval\n')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_STALE_OR_MISSING_INPUT' in result.stderr
    assert not (tmp_path / 'reports/flow109/attempts').exists()


def test_absent_declared_corner_refuses_before_ngspice(tmp_path):
    _case(tmp_path, missing_corner=True)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_MODEL_CORNER_ABSENT' in result.stderr
    assert not (tmp_path / 'reports/flow109/attempts').exists()


def test_symlinked_model_parent_refuses_before_ngspice(tmp_path):
    _case(tmp_path)
    pdk = tmp_path / 'input/pdk'
    real = tmp_path / 'input/pdk-real'
    pdk.rename(real)
    pdk.symlink_to(real, target_is_directory=True)
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'symlinked path component' in result.stderr
    assert not (tmp_path / 'reports/flow109/attempts').exists()


def test_unbound_abbreviated_include_refuses_before_ngspice(tmp_path):
    _case(tmp_path, transitive='missing')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_MODEL_DEPENDENCY_MISSING' in result.stderr
    assert not (tmp_path / 'reports/flow109/attempts').exists()


def test_bound_transitive_model_is_staged_and_receipted(tmp_path):
    _case(tmp_path, transitive='bound')
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A02.json').read_text())
    assert report['component_status'] == 'PASS'
    for smoke in report['smokes']:
        closure = smoke['model_closure']
        assert len(closure['files']) == 2
        assert closure['edges'] == [{
            'from': 'input/pdk/spice/open_dev_models.lib',
            'line': {'ss': 2, 'tt': 5, 'ff': 8}[smoke['corner']],
            'directive': 'include', 'target': 'input/pdk/spice/open_dev_child.lib',
            'section': None}]
        assert {row['sha256'] for row in smoke['executed_model_files']} == {
            row['sha256'] for row in closure['files']}


def test_altered_bound_transitive_bytes_refuse_before_native(tmp_path):
    _case(tmp_path, transitive='bound')
    child = tmp_path / 'input/pdk/spice/open_dev_child.lib'
    child.write_text(child.read_text() + '* stale after source approval\n')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_STALE_OR_MISSING_INPUT' in result.stderr
    assert not (tmp_path / 'reports/flow109/attempts').exists()


def test_bound_transitive_lib_section_is_staged_and_receipted(tmp_path):
    _case(tmp_path, transitive='lib')
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A02.json').read_text())
    assert report['component_status'] == 'PASS'
    for smoke in report['smokes']:
        closure = smoke['model_closure']
        assert closure['edges'][0]['directive'] == 'lib'
        assert closure['edges'][0]['section'] == 'child_tt'
        child = next(row for row in closure['bindings']
                     if row['path'].endswith('open_dev_child.lib'))
        assert child['section'] == 'child_tt' and child['sha256']


def test_unbound_existing_transitive_model_refuses(tmp_path):
    _case(tmp_path, transitive='unbound')
    pdk = json.loads((tmp_path / 'input/flow109/A02-pdk.json').read_text())
    assert pdk['inventory_files']['spice_models']['path'].endswith('open_dev_child.lib')
    assert all(not row['path'].endswith('open_dev_child.lib')
               for row in pdk['model_files'])
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_MODEL_DEPENDENCY_UNBOUND' in result.stderr


def test_escaped_transitive_model_refuses(tmp_path):
    _case(tmp_path, transitive='escape')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_MODEL_DEPENDENCY_ESCAPE' in result.stderr


def test_symlinked_transitive_model_refuses(tmp_path):
    _case(tmp_path, transitive='symlink')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_MODEL_DEPENDENCY_SYMLINK' in result.stderr


def test_model_dependency_cycle_refuses(tmp_path):
    _case(tmp_path, transitive='cycle')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_MODEL_DEPENDENCY_CYCLE' in result.stderr


def test_unsupported_model_directive_refuses(tmp_path):
    _case(tmp_path, transitive='unsupported')
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'A02_MODEL_DIRECTIVE_UNSUPPORTED' in result.stderr


def test_model_closure_source_reverse_and_restored(tmp_path, monkeypatch):
    """The repaired source traversal, not fixture bytes alone, enables closure."""
    _case(tmp_path, transitive='bound')
    pdk = json.loads((tmp_path / 'input/flow109/A02-pdk.json').read_text())
    requirements = json.loads((tmp_path / 'input/flow109/A02-requirements.json').read_text())
    smoke = requirements['required_smokes'][0]
    declared = {(tmp_path / row['path']).resolve(): row for row in pdk['model_files']}
    model = (tmp_path / smoke['model']['path']).resolve()
    canonical = analog._model_closure
    good = canonical(tmp_path.resolve(), smoke, model, declared)
    assert len(good['files']) == 2

    def old_refusal(*_args, **_kwargs):
        raise admission.AdmissionRefusal('A02_TRANSITIVE_MODEL_INPUT_UNIMPLEMENTED',
                                         smoke['id'])

    monkeypatch.setattr(analog, '_model_closure', old_refusal)
    with pytest.raises(admission.AdmissionRefusal,
                       match='A02_TRANSITIVE_MODEL_INPUT_UNIMPLEMENTED'):
        analog._deck_contract(tmp_path.resolve(), smoke, model,
                              tmp_path / smoke['deck']['path'], declared)

    monkeypatch.setattr(analog, '_model_closure', canonical)
    restored = analog._deck_contract(tmp_path.resolve(), smoke, model,
                                     tmp_path / smoke['deck']['path'], declared)
    assert restored == good


def test_actual_pinned_ihp_transitive_model_smoke_has_full_receipt(tmp_path):
    _case(tmp_path, pinned_ihp=True)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / 'reports/flow109/components/A02.json').read_text())
    assert report['component_status'] == 'PASS'
    assert report['flow109_acceptance'] == 'NOT_MEASURED'
    smoke = report['smokes'][0]
    assert smoke['corner'] == 'mos_tt' and smoke['device'] == 'sg13_lv_nmos'
    assert len(smoke['model_closure']['files']) >= 2
    assert len(smoke['executed_model_files']) == len(smoke['model_closure']['files'])
    assert all(row['sha256'] for row in smoke['model_closure']['files'])


def test_unsupported_qualification_refuses_before_component_dispatch(tmp_path):
    manifest, registry, _model = _case(tmp_path)
    registry['uses'][0]['status'] = 'UNSUPPORTED'
    record = registry['uses'][0]
    manifest['runtime_tool_uses'][0]['qualification_sha256'] = admission.canonical_sha(record)
    (tmp_path / 'qualifications.json').write_text(json.dumps(registry))
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    result = _run(tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'QUALIFICATION_UNSUPPORTED' in result.stderr
    assert not (tmp_path / 'reports/flow109/attempts').exists()


def test_a02_diagnostic_prose_polarity_counterexample_and_source_reverse(tmp_path, monkeypatch):
    """A denied fatal phrase is clean; a live fatal phrase still blocks."""
    _case(tmp_path)
    native = _run(tmp_path)
    assert native.returncode == 0, native.stdout + native.stderr
    component_path = tmp_path / 'reports/flow109/components/A02.json'
    report = json.loads(component_path.read_text())
    requirements = json.loads((tmp_path / 'input/flow109/A02-requirements.json').read_text())
    row = report['smokes'][0]
    log = tmp_path / row['log']['path']
    original = log.read_bytes()

    log.write_bytes(original + b'\nno fatal error occurred\n')
    row['log']['sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
    consulted = model_check.consume(tmp_path, requirements, report)
    _put(tmp_path, 'reports/flow109/A02-polarity-consulted.json', consulted)
    assert consulted['verdict'] == 'PASS', consulted

    canonical = model_check._polarity.is_denied
    monkeypatch.setattr(model_check._polarity, 'is_denied', lambda *_a, **_k: None)
    reversed_result = model_check.consume(tmp_path, requirements, report)
    _put(tmp_path, 'reports/flow109/A02-source-reverse.json', reversed_result)
    assert reversed_result['verdict'] == 'FAIL'
    assert reversed_result['reason'] == 'A02_NATIVE_MODEL_LOAD_FAILED'

    monkeypatch.setattr(model_check._polarity, 'is_denied', canonical)
    restored = model_check.consume(tmp_path, requirements, report)
    _put(tmp_path, 'reports/flow109/A02-source-restored.json', restored)
    assert restored['verdict'] == 'PASS', restored

    # Here "no" belongs to the diagnostic itself: it constitutes failure and
    # must not be mistaken for prose that retracts the diagnostic.
    log.write_bytes(original + b'\nno simulations run\n')
    row['log']['sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
    constitutive_fatal = model_check.consume(tmp_path, requirements, report)
    _put(tmp_path, 'reports/flow109/A02-constitutive-fatal.json', constitutive_fatal)
    assert constitutive_fatal['verdict'] == 'FAIL'
    assert constitutive_fatal['reason'] == 'A02_NATIVE_MODEL_LOAD_FAILED'

    log.write_bytes(original + b'\nfatal error occurred\n')
    row['log']['sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
    live_fatal = model_check.consume(tmp_path, requirements, report)
    _put(tmp_path, 'reports/flow109/A02-live-fatal.json', live_fatal)
    assert live_fatal['verdict'] == 'FAIL'
    assert live_fatal['reason'] == 'A02_NATIVE_MODEL_LOAD_FAILED'

    # Measurement identifiers are formal ngspice tokens.  A token containing
    # an English denial spelling is still data, not prose to suppress.
    formal_report, formal_requirements = copy.deepcopy(report), copy.deepcopy(requirements)
    formal_row = formal_report['smokes'][0]
    formal_need = next(item for item in formal_requirements['required_smokes']
                       if item['id'] == formal_row['id'])
    formal_row['required_measurements'] = formal_need['required_measurements'] = ['no_gain']
    log.write_bytes(original + b'\nno_gain = 1.0\n')
    formal_row['log']['sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
    formal = model_check.consume(tmp_path, formal_requirements, formal_report)
    _put(tmp_path, 'reports/flow109/A02-formal-measurement.json', formal)
    assert formal['verdict'] == 'PASS', formal
    assert formal['smokes'][0]['measurements'] == {'no_gain': 1.0}
