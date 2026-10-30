"""Neutral D43 actual native and SOFTWARE_ONLY refusal controls, not ADC signoff."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import flow109
import gds_antenna_deck_check as gate


@pytest.fixture
def carrier(tmp_path):
    source = os.environ.get('D43_NATIVE_CARRIER')
    if not source:
        pytest.skip('explicit neutral native carrier not supplied')
    project = tmp_path/'project'
    shutil.copytree(source, project, ignore=shutil.ignore_patterns('reports','.vibeic'))
    return project


def change(project, edit):
    p = project/'input/flow109/D43.json'
    d = json.loads(p.read_text()); edit(d); p.write_text(json.dumps(d))


def invoke(project):
    args = SimpleNamespace(flow='109', flow109_manifest=project/'manifest.json',
        flow109_plan_only=False, execution_mode='default', entry_step='D43', exit_step='D43')
    try:
        rc = flow109.prepare_front_door(args, project)
        result = json.loads((project/'reports/flow109/components/D43.json').read_text())
    except flow109.Flow109Error as exc:
        rc, result = 2, {'component_status': exc.code, 'reason': str(exc), 'native_started': False}
    (project.parent/'observed.json').write_text(json.dumps({'rc':rc,'component':result},indent=2))
    return rc, result


def select(project, name):
    p = project/'input/candidate'/name
    change(project, lambda d: d.update(layout={'path':str(p.relative_to(project)), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))


def test_native_rules_run_without_promoting_unknown_gate_population(carrier):
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    native = result['native']
    assert native['violations'] == 0 and len(native['graded_rules']) == 31
    assert native['checked_gate_nets'] is None and native['coverage_status'] == 'NOT_MEASURED'
    assert native['rc'] == 0 and native['verdict'] == 'DISCLOSED_SKIP'
    assert 'threads=1' in native['execution']['argv']
    assert rc == 2 and result['completed'] is False
    assert result['default_row_status'] == result['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert result['qualification'] == 'NOT_CLAIMED'
    for ref in result['outputs']:
        assert hashlib.sha256((carrier/ref['path']).read_bytes()).hexdigest() == ref['sha256']


def test_native_violating_conductor_blocks_even_when_process_rc_zero(carrier):
    select(carrier, 'violating.gds')
    rc, result = invoke(carrier)
    assert result['component_status'] == 'FAIL', result
    assert result['native']['violations'] == 7 and result['native']['rc'] == 0
    assert rc == 1 and result['default_row_status'] == 'FAIL'


def test_actual_gate_free_native_geometry_cannot_pass(carrier):
    select(carrier, 'no_gate.gds')
    rc, result = invoke(carrier)
    assert result['native']['violations'] == 0 and result['native']['rc'] == 0, result
    assert result['component_status'] == 'NOT_MEASURED' and rc == 2
    assert result['native']['checked_gate_nets'] is None


@pytest.mark.parametrize('kind',['missing_geometry','stale_geometry','stale_deck','foreign_deck','missing_PDK'])
def test_unbound_inputs_refuse_before_native(carrier, kind):
    if kind == 'missing_geometry':
        (carrier/'input/candidate/clean.gds').unlink()
    elif kind == 'stale_geometry':
        change(carrier, lambda d: d['layout'].update(sha256='0'*64))
    elif kind == 'stale_deck':
        change(carrier, lambda d: d['antenna_deck'].update(sha256='0'*64))
    elif kind == 'foreign_deck':
        change(carrier, lambda d: d['antenna_deck'].update(path='/other-pdk/antenna.drc'))
    else:
        (carrier/'phase1/generated_docs/L19_CONSTRAINTS_PDK.json').write_text('{"fields":{}}')
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED' and result['native_started'] is False, result
    assert rc == 2


def test_ambiguous_native_top_cannot_select_a_macro_as_candidate(carrier):
    select(carrier, 'ambiguous.gds')
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D43_SUBJECT_TOP_ABSENT_AMBIGUOUS_OR_EMPTY'
    assert 'native' not in result and rc == 2


def test_process_rc_zero_without_native_report_cannot_pass(carrier, monkeypatch):
    # SOFTWARE_ONLY process-edge result; no native qualification credit.
    monkeypatch.setattr(gate._kl.HostRunner,'run_argv_supervised',lambda *a,**k: SimpleNamespace(rc=0,out='',err='',outcome='natural',elapsed_s=0,supervision={}))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED' and rc == 2, result
    assert result['native']['verdict'] != 'PASS'


def test_missing_current_launch_cannot_contribute_native_measurement(carrier, monkeypatch):
    # SOFTWARE_ONLY missing input: original host-retained launch is untouched.
    monkeypatch.setenv('VIBEIC_LIBRELANE_LOCAL_ATTESTATION', str(carrier/'absent-launch.json'))
    rc, result = invoke(carrier)
    assert result['component_status'] not in ('PASS', 'FAIL'), result
    assert result['native_started'] is False and 'native' not in result
    assert rc == 2
