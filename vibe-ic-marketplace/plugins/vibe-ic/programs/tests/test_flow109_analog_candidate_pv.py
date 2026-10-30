"""Neutral native D42 controls. No ADC, full-row or native qualification credit."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import flow109
import analog_a6_native_pv as pv


@pytest.fixture
def carrier(tmp_path):
    source = os.environ.get('D42_NATIVE_CARRIER')
    if not source:
        pytest.skip('explicit neutral native candidate inputs not supplied')
    project = tmp_path / 'project'
    shutil.copytree(source, project, ignore=shutil.ignore_patterns('reports', '.vibeic'))
    return project


def change(project, edit):
    p = project / 'input/flow109/D42.json'
    d = json.loads(p.read_text()); edit(d); p.write_text(json.dumps(d))


def invoke(project):
    args = SimpleNamespace(flow='109', flow109_manifest=project/'manifest.json',
        flow109_plan_only=False, execution_mode='default', entry_step='D42', exit_step='D42')
    try:
        rc = flow109.prepare_front_door(args, project)
        result = json.loads((project/'reports/flow109/components/D42.json').read_text())
    except flow109.Flow109Error as exc:
        rc, result = 2, {'component_status': exc.code, 'reason': str(exc), 'native_started': False}
    (project.parent/'observed.json').write_text(json.dumps({'rc': rc, 'component': result}, indent=2))
    return rc, result


def test_native_clean_DRC_cannot_claim_missing_required_pin_coverage(carrier):
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['drc']['status'] == 'PASS', result
    assert result['drc']['violations'] == 0
    assert len(result['drc']['meta']['authoritative']['graded']) > 0
    assert result['connectivity']['status'] == 'NOT_MEASURED'
    assert result['component_status'] == 'NOT_MEASURED'
    assert rc == 2 and result['completed'] is False
    assert result['default_row_status'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['qualification'] == 'NOT_CLAIMED'
    for ref in result['outputs']:
        assert hashlib.sha256((carrier/ref['path']).read_bytes()).hexdigest() == ref['sha256']


def test_actual_bad_geometry_native_violations_block(carrier):
    bad = carrier/'input/candidate/too_narrow.gds'
    change(carrier, lambda d: d.update(layout={'path': str(bad.relative_to(carrier)), 'sha256': hashlib.sha256(bad.read_bytes()).hexdigest()}))
    rc, result = invoke(carrier)
    assert result['drc']['violations'] > 0, result
    assert result['drc']['status'] == result['component_status'] == 'FAIL'
    assert rc == 1 and result['default_row_status'] == 'FAIL'
    (Path(os.environ['D42_NATIVE_CARRIER'])/'prior_bad_drc.json').write_text(json.dumps(result))


@pytest.mark.parametrize('mutation', ['missing_geometry', 'stale_geometry', 'stale_deck', 'wrong_reference'])
def test_invalid_bound_inputs_refuse_before_native(carrier, mutation):
    if mutation == 'missing_geometry':
        (carrier/'input/candidate/candidate.gds').unlink()
    elif mutation == 'stale_geometry':
        change(carrier, lambda d: d['layout'].update(sha256='0'*64))
    elif mutation == 'stale_deck':
        change(carrier, lambda d: d['drc_deck'].update(sha256='0'*64))
    else:
        p = carrier/'input/candidate/logical.spice'; p.write_text('.subckt other A B\n.ends other\n')
        change(carrier, lambda d: d['logical_netlist'].update(sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['native_started'] is False and rc == 2


def test_wrong_candidate_top_refuses_native_drc(carrier):
    p = carrier/'input/candidate/logical.spice'; p.write_text('.subckt absent A B\n.ends absent\n')
    change(carrier, lambda d: d.update(top='absent', logical_netlist={'path': str(p.relative_to(carrier)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D42_CANDIDATE_TOP_ABSENT_OR_EMPTY'
    assert 'drc' not in result and rc == 2


def test_rc_zero_but_no_report_is_not_clean(carrier, monkeypatch):
    # SOFTWARE_ONLY injected process result, never native qualification.
    original = pv._docker_exec
    def no_report(container, cmd, *args, **kwargs):
        if ' -rd input=' in cmd:
            return 0, '', ''
        return original(container, cmd, *args, **kwargs)
    monkeypatch.setattr(pv, '_docker_exec', no_report)
    rc, result = invoke(carrier)
    assert result['drc']['status'] == 'NOT_MEASURED', result
    assert result['component_status'] == 'NOT_MEASURED' and rc == 2


def test_earlier_real_DRC_fail_survives_late_connectivity_gap(carrier, monkeypatch):
    # Retained actual native bad-geometry result is reopened, not restamped.
    raw = json.loads((carrier/'prior_bad_drc.json').read_text())
    assert raw['drc']['status'] == 'FAIL' and raw['drc']['violations'] > 0
    monkeypatch.setattr(pv, '_klayout_drc_runner', lambda *a, **k: (raw['drc']['violations'], raw['drc']['meta']))
    monkeypatch.setattr(pv, '_klayout_lvs_runset_runner', lambda *a, **k: (_ for _ in ()).throw(ValueError('TEST_ONLY_LATE_CONNECTIVITY_GAP')))
    rc, result = invoke(carrier)
    assert result['drc']['status'] == result['component_status'] == 'FAIL', result
    assert rc == 1 and result['reason'] == 'TEST_ONLY_LATE_CONNECTIVITY_GAP'


@pytest.mark.parametrize('verdict,expected', [('MATCH','PASS'),('MISMATCH','FAIL'),(None,'NOT_MEASURED')])
def test_current_LVS_consumer_uses_native_verdict_vocabulary(carrier, monkeypatch, verdict, expected):
    # SOFTWARE_ONLY branch control, not an execution/adoption/qualification.
    def drc(*args):
        return 0, {'authoritative': {'graded': ['neutral_width'], 'violations': {}}}
    def lvs(*args):
        db = args[-1]/'native.lvsdb'; db.parent.mkdir(parents=True); db.write_text('TEST_ONLY_DB')
        return verdict, {'rc': 0, 'source_devices': 1, 'report': str(db)}
    monkeypatch.setattr(pv, '_klayout_drc_runner', drc)
    monkeypatch.setattr(pv, '_klayout_lvs_runset_runner', lvs)
    rc, result = invoke(carrier)
    assert result['connectivity']['status'] == expected, result
    assert result['component_status'] == expected
    assert rc == (1 if expected == 'FAIL' else 2)
    assert result['completed'] is False and result['qualification'] == 'NOT_CLAIMED'


def test_absent_declared_PDK_is_not_an_implicit_first_installed_choice(carrier):
    (carrier/'phase1/generated_docs/L19_CONSTRAINTS_PDK.json').write_text('{"fields":{}}')
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D42_DECLARED_PDK_ABSENT'
    assert result['native_started'] is False and rc == 2
