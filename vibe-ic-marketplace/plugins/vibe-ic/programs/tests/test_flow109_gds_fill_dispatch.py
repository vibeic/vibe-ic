"""Native D62 dispatch on the existing neutral GDS/rule fixtures.

This is component/method evidence, never ADC or qualified final-geometry PASS.
The failure-report injection is a software consumer control, not a native run.
"""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
import flow109
import flow109_density_fill as fill
from programs.tests._hostpaths import require_repo


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def case(project, *, blocked=False):
    """Reuse the checked-in stream/map/example config, not a design oracle."""
    programs = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs')
    fixtures = programs / 'tests/fixtures/density_fill'
    source = project / 'input/final.gds'
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixtures / 'filled.gds', source)
    cfg = json.loads((programs / 'metal_fill/fill_config.example.json').read_text())
    rows = [s.split() for s in (fixtures / 'fill.map').read_text().splitlines()
            if s.strip() and not s.startswith('#')]
    metal = next(r for r in rows if 'NET' in r[1].split(','))
    dummy = next(r for r in rows if r[1] == 'FILL')
    cfg['layers'][0]['layer'] = [int(metal[2]), int(metal[3])]
    cfg['layers'][0]['fill_datatype'] = int(dummy[3])
    # Only decode this actual fixture's records to identify its cell/bbox.
    # PyaStub is NOT installed or passed into any native engine.
    spec = importlib.util.spec_from_file_location('gds_fixture_input', fixtures / 'gds_fixture.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    shapes, dbu, cell = module.read_gds(source)
    rects = [r for values in shapes.values() for r in values]
    bbox = [min(r[0] for r in rects)*dbu, min(r[1] for r in rects)*dbu,
            max(r[2] for r in rects)*dbu, max(r[3] for r in rects)*dbu]
    if blocked:
        # Separate neutral negative declaration; no original deck is edited.
        cfg['layers'][0].update(target=0.99, max=1.0)
        cfg['keepout_boxes_um'] = [bbox]
    rules = project / 'input/cmp_fill_targets.json'; put(rules, cfg)
    manifest = {'schema': fill.SCHEMA, 'cell': cell,
                'input_gds': fill._record(project, source), 'rules': fill._record(project, rules)}
    put(project / fill.INPUT, manifest)
    features = copy.deepcopy(next(p['features'] for p in flow109.load_registry()['reference_profiles']
                                  if p['name'] == 'Analog IC external trim'))
    put(project / 'manifest.json', {'features': features})
    put(project / 'input/step_0_5ic_answers.json', {
        'answers': {'deliverable': 'DIE'}, 'answer_provenance': {
            'deliverable': {'answered_by': 'owner',
                            'citation': 'Explicit neutral component carrier, not ADC approval'}}})
    put(project / 'CONTROL_SCOPE.json', {'scope': 'NEUTRAL_NATIVE_COMPONENT_NOT_ADC',
         'fixture': str(fixtures / 'filled.gds'), 'fixture_sha256': fill._sha(source),
         'example': str(programs / 'metal_fill/fill_config.example.json'),
         'negative': blocked, 'no_foundry_or_whole_IC_qualification': True})
    return manifest


def invoke(project):
    args = SimpleNamespace(flow='109', flow109_manifest=project / 'manifest.json',
        flow109_plan_only=False, execution_mode='default', entry_step='D62', exit_step='D62')
    try:
        rc = flow109.prepare_front_door(args, project)
        result = json.loads((project / 'reports/flow109/components/D62.json').read_text())
    except flow109.Flow109Error as exc:
        # Preserve the real pre-fix public boundary refusal, not an import/absence failure.
        rc, result = 2, {'component_status': 'NOT_MEASURED', 'native_started': False,
                        'reason': exc.code, 'detail': str(exc)}
    put(project / 'canonical-observation.json', {'rc': rc, 'component': result})
    return rc, result


def test_canonical_analog_profile_runs_real_fill_and_reopens_bound_report(tmp_path):
    manifest = case(tmp_path)
    rc, result = invoke(tmp_path)
    assert result['component_status'] == 'PASS', result
    assert result['native_started'] is True
    assert rc == 2 and result['default_row_status'] == 'NOT_MEASURED'
    assert result['completed'] is False and result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['inputs'] == {k: manifest[k] for k in ('input_gds', 'rules')}
    assert result['emitter_result']['verdict'] == result['verify_only']['verdict'] == 'PASS'
    assert (tmp_path / result['outputs']['filled.gds']['path']).stat().st_size > 0
    assert result['native_launch']['cid']
    assert fill._sha(tmp_path / manifest['input_gds']['path']) == manifest['input_gds']['sha256']
    assert not (tmp_path / 'reports/flow109/D62/accepted.json').exists()


def test_native_protected_full_bbox_keeps_density_failure(tmp_path):
    manifest = case(tmp_path, blocked=True)
    rc, result = invoke(tmp_path)
    assert result['component_status'] == 'FAIL', result
    assert rc == 1 and result['native_started'] is True
    assert result['reason'] == 'D62_GDS_FILL_FAILED'
    assert result['emitter_result']['verdict'] == 'PARTIAL'
    assert result['emitter_result']['keepout']['declared'] is True
    assert not result['emitter_result']['layers'][0]['reached']
    assert result['outputs']['fill-report.json']['sha256']
    assert fill._sha(tmp_path / manifest['input_gds']['path']) == manifest['input_gds']['sha256']


@pytest.mark.parametrize('damage', ['missing_gds', 'missing_rules', 'stale_gds', 'foreign_gds'])
def test_invalid_bound_inputs_refuse_before_native(tmp_path, damage):
    manifest = case(tmp_path)
    if damage == 'missing_gds':
        (tmp_path / manifest['input_gds']['path']).unlink()
    elif damage == 'missing_rules':
        (tmp_path / manifest['rules']['path']).unlink()
    elif damage == 'stale_gds':
        manifest['input_gds']['sha256'] = '0' * 64
    else:
        manifest['input_gds']['path'] = '../another-carrier/final.gds'
    put(tmp_path / fill.INPUT, manifest)
    _, result = invoke(tmp_path)
    assert result['native_started'] is False and result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] in {'D62_INPUT_ABSENT', 'D62_INPUT_STALE', 'D62_GDS_INPUT_UNBOUND'}
    assert not result['outputs']


def test_equal_fail_reports_with_rc_zero_are_never_component_pass(tmp_path, monkeypatch):
    case(tmp_path)
    real = fill.subprocess.run
    def bad_returncode(argv, *a, **kw):
        if str(fill.HERE / 'metal_fill_emit.py') not in argv:
            return real(argv, *a, **kw)
        # SOFTWARE injected faulty wrapper: no native execution is credited.
        paths = {flag: Path(argv[argv.index(flag)+1]) for flag in ('--out','--report','--json')}
        shutil.copyfile(tmp_path / 'input/final.gds', paths['--out'])
        report = {'verdict': 'FAIL', 'layers': [{'name': 'met1', 'reached': False}],
                  'runner': 'host:' + __import__('_klayout_launch').find_runner().detail,
                  'scope': 'SOFTWARE_FAILURE_REPORT_RC_INJECTION'}
        put(paths['--report'], report); put(paths['--json'], report)
        return SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr='')
    monkeypatch.setattr(fill.subprocess, 'run', bad_returncode)
    rc, result = invoke(tmp_path)
    assert result['component_status'] == 'FAIL', result
    assert rc == 1 and result['reason'] == 'D62_GDS_FILL_FAILED'
    assert result['emitter_result']['scope'] == 'SOFTWARE_FAILURE_REPORT_RC_INJECTION'
