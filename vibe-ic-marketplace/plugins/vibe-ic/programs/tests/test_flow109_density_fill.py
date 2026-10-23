"""D62 component controls and actual synthetic OpenROAD ODB smoke.

Native smoke is explicitly separate from trusted PDK/tool qualification.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import flow109
import flow109_density_fill as fill
from flow109_admission import AdmissionRefusal
from programs.tests._hostpaths import require_repo


def _unit_inputs(project):
    project.mkdir(parents=True, exist_ok=True)
    def put(name, content):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return fill._record(project, path)
    manifest = {'schema': fill.SCHEMA,
                'input_odb': put('inputs/routed.odb', 'unit contract, not native ODB'),
                'rules': put('inputs/rules.json', '{"layers":{"unit":{}}}'),
                'pdk': put('inputs/pdk.json', '{"scope":"unit-only"}')}
    put(fill.INPUT, json.dumps(manifest))
    use = {'tool_id': 'openroad', 'version': 'unit', 'build_sha256': 'unit',
           'executable': fill._record(project, Path(shutil.which('true'))),
           'deck': manifest['rules'], 'pdk': manifest['pdk'],
           'config': put('inputs/config.json', json.dumps(
               {'schema': fill.SCHEMA, 'operation': 'density_fill', 'area': 'core'})),
           'semantics': {'operation_sources': fill.operation_sources()}}
    owner = put('inputs/owner.md', 'approved unit-only D62 contract\n')
    approval = {'status': 'APPROVED', 'authority': 'requirements_owner',
                'source_reference': owner}
    put('requirements/base_43/fill_density_rules.json', json.dumps({
        'schema': 'vibeic.flow109.requirement-authority.v1', 'approval': approval,
        'limits': {'unit': {'min': 0.1, 'max': 0.9}}, 'units': 'ratio',
        'scope': {'kind': 'tiled_windows', 'area': 'core', 'window_um': 10.0,
                  'step_um': 5.0, 'minimum_core_dimensions_um': [10.0, 10.0]},
        'rules_sha256': manifest['rules']['sha256'],
        'pdk_sha256': manifest['pdk']['sha256']}))
    put('requirements/base_43/fill_keepout_violations.json', json.dumps({
        'schema': 'vibeic.flow109.requirement-authority.v1', 'approval': approval,
        'expected': 0, 'unit': 'count',
        'checker_semantics': 'opendb_fill_obstruction_overlap',
        'validated_absence': True, 'rules_sha256': manifest['rules']['sha256'],
        'pdk_sha256': manifest['pdk']['sha256']}))
    return {'requested_step': 'D62', 'native_step_id': 'flow109.D62', 'runtime_tool_uses': [use]}


@pytest.mark.parametrize('damage', ['odb', 'rules', 'pdk', 'source', 'config', 'unqualified'])
def test_bad_or_unqualified_inputs_stop_before_native(tmp_path, monkeypatch, damage):
    context = _unit_inputs(tmp_path)
    if damage in ('odb', 'rules', 'pdk'):
        path = {'odb':'inputs/routed.odb','rules':'inputs/rules.json','pdk':'inputs/pdk.json'}[damage]
        (tmp_path / path).write_text('changed')
    elif damage == 'source':
        context['runtime_tool_uses'][0]['semantics']['operation_sources'] = {}
    elif damage == 'config':
        (tmp_path / 'inputs/config.json').write_text('{}')
    called = []
    monkeypatch.setattr(fill, '_call', lambda *a: called.append('native'))
    def refusal(*a, **kw):
        raise AdmissionRefusal('QUALIFICATION_UNSUPPORTED', 'unit negative control')
    monkeypatch.setattr(fill, 'require_launch_admission', refusal)
    result = fill.execute(tmp_path, context)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['native_started'] is False and called == []
    assert not (tmp_path / 'reports/flow109/D62/accepted.json').exists()
    assert (tmp_path / result['receipt']['path']).is_file()


def test_registry_selects_odb_component_without_gds_alias():
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    row = flow109.resolve_step(flow109.resolve_plan(features), 'D62')
    assert row['profile']['geometry_format'] == 'ODB'
    assert row['profile']['dispatch']['adapter'] == 'flow109_density_fill'
    assert row['profile']['dispatch']['native_step_id'] == 'flow109.D62'
    assert row['tool_uses'][0]['native_steps'] == [
        'OpenROAD.DensityFill', 'OpenROAD.CheckMetalDensity',
        'OpenROAD.CheckFillObstructions']
    assert row['metric_acceptance_status'] == 'IMPLEMENTED_D62_RUNTIME'


@pytest.mark.parametrize('authority', [
    'requirements/base_43/fill_density_rules.json',
    'requirements/base_43/fill_keepout_violations.json'])
def test_missing_metric_authority_preserves_native_admission(tmp_path, monkeypatch, authority):
    context = _unit_inputs(tmp_path)
    (tmp_path / authority).unlink()
    prepared = fill.prepare(tmp_path, context)
    assert prepared['authorities'] == {}
    assert prepared['authority_inputs'] == {}
    # Missing audit metadata does not bypass the original launch check.
    called = []
    def refuse(*args, **kwargs):
        called.append('admission')
        raise AdmissionRefusal('QUALIFICATION_UNSUPPORTED', 'native scope required')
    monkeypatch.setattr(fill, 'require_launch_admission', refuse)
    result = fill.execute(tmp_path, context)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result['reason'] == 'QUALIFICATION_UNSUPPORTED'
    assert result['native_started'] is False
    assert called == ['admission']
    assert result['metric_acceptance_status'] != 'PASS'


@pytest.mark.parametrize('damage', ['diearea', 'wire', 'old_fill_removed'])
def test_consumer_refuses_nonfill_or_retained_fill_changes(tmp_path, damage):
    before = 'DIEAREA ( 0 0 ) ( 100 100 ) ;\nNETS 1 ;\n- n + ROUTED M1 ( 0 0 ) ( 100 0 ) ;\nEND NETS\n'
    existing = 'FILLS 1 ;\n- LAYER M1 RECT ( 1 1 ) ( 2 2 ) ;\nEND FILLS\n'
    added = 'FILLS 2 ;\n- LAYER M1 RECT ( 1 1 ) ( 2 2 ) ;\n- LAYER M1 RECT ( 4 4 ) ( 5 5 ) ;\nEND FILLS\n'
    output = before + added
    if damage == 'diearea':
        output = output.replace('( 100 100 )', '( 101 100 )')
    elif damage == 'wire':
        output = output.replace('( 100 0 )', '( 99 0 )')
    else:
        output = before + 'FILLS 1 ;\n- LAYER M1 RECT ( 4 4 ) ( 5 5 ) ;\nEND FILLS\n'
    for name, text in [('before.def', before+existing), ('filled.def', output), ('readback.def',output)]:
        (tmp_path / name).write_text(text)
    with pytest.raises(AdmissionRefusal, match='GEOMETRY_CHANGED'):
        fill._geometry_proof(*(tmp_path / name for name in ('before.def','filled.def','readback.def')))


def test_native_openroad_density_fill_writes_readable_odb_and_preserves_route(tmp_path):
    executable = shutil.which('openroad')
    assert executable, 'Run this native smoke in the pinned EDA image'
    fixtures = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests', 'fixtures', 'flow109_density_fill')
    for name in ('tech.lef', 'routed.def', 'rules.json'):
        shutil.copyfile(fixtures / name, tmp_path / name)
    init = tmp_path / 'initialize.tcl'
    init.write_text('read_lef tech.lef\nread_def routed.def\nwrite_db input.odb\n')
    proc = subprocess.run([executable, '-no_init', '-exit', str(init)], cwd=tmp_path,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    original = fill._sha(tmp_path / 'input.odb')
    paths = {'input_odb': tmp_path / 'input.odb', 'rules': tmp_path / 'rules.json'}
    attempts = []
    proof = fill._native_fill(tmp_path, {'paths':paths, 'executable':Path(executable)},
                              tmp_path / 'attempt', lambda: attempts.append('launch'))
    assert attempts == ['launch','launch']
    assert proof['fill_count_after'] > proof['fill_count_before']
    assert proof['nonfill_geometry_preserved'] and proof['odb_readback_matches']
    assert proof['density_signoff'] == 'NOT_MEASURED'
    assert original == fill._sha(tmp_path / 'input.odb')
    assert fill._sha(tmp_path / 'attempt/filled.odb') != original
    assert 'NETS 1 ;' in (tmp_path / 'attempt/readback.def').read_text()
    assert 'sig' in (tmp_path / 'attempt/readback.def').read_text()
    # This native component smoke deliberately does not manufacture a
    # qualification registry, D62 accepted receipt or whole-flow PASS.
    assert not (tmp_path / 'reports/flow109/D62/accepted.json').exists()


@pytest.mark.parametrize('qualification', [{}, {'status': 'NOT_VERIFIED', 'uses': ['synthetic']}, {'status': 'PASS', 'uses': []}])
def test_handoff_refuses_unqualified_component_receipt(tmp_path, qualification):
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'schema': fill.SCHEMA, 'component_status': 'PASS',
                                   'qualification': qualification}))
    with pytest.raises(AdmissionRefusal, match='qualified producer binding required'):
        fill.validate_filled_odb(tmp_path, fill._record(tmp_path, receipt))


def test_handoff_refuses_changed_receipt_before_reading_output(tmp_path):
    receipt = tmp_path / 'receipt.json'
    receipt.write_text('{}')
    reference = fill._record(tmp_path, receipt)
    receipt.write_text('{"component_status":"PASS"}')
    with pytest.raises(AdmissionRefusal, match='receipt.json'):
        fill.validate_filled_odb(tmp_path, reference)


def test_native_call_keeps_owner_supervision_and_nonzero_failure(tmp_path, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 9)
    monkeypatch.setattr(fill.subprocess, 'run', run)
    with pytest.raises(AdmissionRefusal, match='rc=9'):
        fill._call(Path('/actual/openroad'), {}, tmp_path / 'native.log')
    assert len(calls) == 1
    assert calls[0][0] == ['/actual/openroad', '-no_init', '-exit', str(fill.SCRIPT)]
    assert 'timeout' not in calls[0][1]
