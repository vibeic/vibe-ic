"""D60 native stream/readback controls, never ADC or tool qualification.

D60_NATIVE_CARRIER names an explicit neutral die-top with real native-produced
macro views. No test edits GDS bytes or relocates a streamed shape. The failed
producer injection is SOFTWARE_ONLY, separately from actual native controls.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import flow109
import analog_hardmacro_gds_emit as stream


@pytest.fixture
def carrier(tmp_path):
    raw = os.environ.get('D60_NATIVE_CARRIER')
    if not raw:
        pytest.skip('neutral native die-top input carrier not supplied')
    project = tmp_path / 'project'
    shutil.copytree(raw, project, ignore=shutil.ignore_patterns('reports', '.vibeic'))
    return project


def invoke(project):
    args = SimpleNamespace(flow='109', flow109_manifest=project/'manifest.json',
        flow109_plan_only=False, execution_mode='default', entry_step='D60', exit_step='D60')
    try:
        rc = flow109.prepare_front_door(args, project)
        result = json.loads((project/'reports/flow109/components/D60.json').read_text())
    except flow109.Flow109Error as exc:
        rc, result = 2, {'component_status': exc.code, 'native_started': False, 'reason': str(exc)}
    (project.parent/'observed.json').write_text(json.dumps({'rc':rc, 'component':result},indent=2)+'\n')
    return rc, result


def test_normal_die_top_stream_reads_real_views_without_row_promotion(carrier):
    rc, result = invoke(carrier)
    assert result['component_status'] == 'PASS', result
    assert rc == 2 and result['default_row_status'] == 'NOT_MEASURED'
    assert result['completed'] is False and result['delivery_accepted'] is False
    assert result['qualification'] == 'NOT_CLAIMED'
    measured = result['measurements']
    cfg = json.loads((carrier/'input/flow109/D60.json').read_text())
    assert measured['top'] == cfg['top']
    inventory = json.loads((carrier/'input/macro_inventory.json').read_text())
    assert sorted(measured['cells']) == sorted([cfg['top'], *{v['master'] for v in inventory['instances'].values()}])
    assert len(result['executions']) == 2 and all(x['returncode'] == 0 for x in result['executions'])
    gds = carrier/result['outputs'][0]['path']
    assert hashlib.sha256(gds.read_bytes()).hexdigest() == measured['gds_sha256'] == result['outputs'][0]['sha256']


def test_missing_required_child_refuses_before_native(carrier):
    child = next((carrier/'input/native').glob('*_view.mag'))
    child.unlink()  # TEST_ONLY source copy, original native views stay intact.
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert 'D60_REQUIRED_CHILD_ABSENT' in result['reason']
    assert result['native_started'] is False and rc == 2


def test_wrong_adopted_master_cannot_be_stream_success(carrier):
    path = carrier/'input/macro_inventory.json'
    inventory = json.loads(path.read_text())
    first, second = list(inventory['instances'].values())
    first['gds'] = second['gds']  # Source GDS bytes are not edited.
    path.write_text(json.dumps(inventory))
    plan = carrier/'input/flow109/D31.json'
    value = json.loads(plan.read_text())
    value['macro_inventory']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    plan.write_text(json.dumps(value))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'FAIL', result
    assert 'D60_ADOPTED_MASTER_ABSENT' in result['reason']
    assert rc == 1 and result['default_row_status'] == 'FAIL'


def test_unknown_source_layer_cannot_silently_disappear(carrier):
    path = next((carrier/'input/native').glob('*_view.mag'))
    path.write_text(path.read_text().replace('<< metal1 >>','<< unavailable_neutral_layer >>'))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'FAIL', result
    assert rc == 1 and result['default_row_status'] == 'FAIL'


def test_zero_exit_rejected_producer_is_not_component_pass(carrier, monkeypatch):
    monkeypatch.setattr(stream.Stage, 'sh', lambda *args, **kwargs: (0, 'FAIL\n', 'producer rejected\n'))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'FAIL', result
    assert result['reason'] == 'D60_NATIVE_STREAM_REJECTED'
    assert rc == 1 and result['default_row_status'] == 'FAIL'


def test_stale_declared_layout_refuses_before_native(carrier):
    cfg = json.loads((carrier/'input/flow109/D60.json').read_text())
    path = carrier/cfg['layout']['path']
    path.write_text(path.read_text()+'\n# TEST_ONLY changed input\n')
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert 'INPUT_STALE' in result['reason'] and result['native_started'] is False
    assert rc == 2


def test_single_macro_cannot_replace_the_die_top(carrier):
    path = carrier/'input/flow109/D60.json'
    cfg = json.loads(path.read_text())
    child = next((carrier/'input/native').glob('*_view.mag'))
    cfg['top'] = child.stem
    cfg['layout'] = {'path':str(child.relative_to(carrier)), 'sha256':hashlib.sha256(child.read_bytes()).hexdigest()}
    path.write_text(json.dumps(cfg))
    rc, result = invoke(carrier)
    assert result['component_status'] == 'NOT_MEASURED', result
    assert 'D60_DIE_MACRO_POPULATION_MISMATCH' in result['reason']
    assert result['native_started'] is False and rc == 2


def test_only_exact_d60_analog_profile_can_use_this_native_owner():
    import copy
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Analog IC external trim')
    row = flow109.resolve_step(flow109.resolve_plan(features), 'D60')
    dispatch = flow109.source_owned_native_dispatch(row)
    assert dispatch['adapter'] == 'analog_hardmacro_gds_emit'
    assert dispatch['engine_families'] == ['magic','klayout']
    for key,value in [('id','D61')]:
        foreign = copy.deepcopy(row); foreign[key] = value
        assert flow109.source_owned_native_dispatch(foreign) is None
    foreign = copy.deepcopy(row); foreign['profile']['id'] = 'assembly'
    assert flow109.source_owned_native_dispatch(foreign) is None
    invalid = copy.deepcopy(row); invalid['profile']['dispatch']['acceptance_scope'] = 'whole_die'
    with pytest.raises(flow109.Flow109Error, match='FLOW109_NATIVE_OWNER_INVALID'):
        flow109.source_owned_native_dispatch(invalid)
