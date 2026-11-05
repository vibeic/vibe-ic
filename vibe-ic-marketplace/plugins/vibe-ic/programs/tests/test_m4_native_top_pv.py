"""Native M4 top subject: actual tools, current consumer, no tapeout credit."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pytest
import _mixed_signal_top_pv as producer
import librelane_contract as contract
import mixed_signal_signoff_check as gate

import mixed_signal_signoff_run as m4

FIXTURE = Path(__file__).parent / 'fixtures/m4_native_top'
PROGRAMS = Path(m4.__file__).parent
IMAGE = json.loads((FIXTURE / 'phase3/librelane_switch.json').read_text())['image']


def declare(project):
    spec = {'schema': 'vibeic.mixed_signal.top_pv_inputs.v1', 'top': 'mixed_probe',
            'scope': 'merged_top_native_pv', 'pdk': 'sky130A', 'image': IMAGE,
            'layout': 'phase3/mixed_signal/top_merged.gds',
            'logical': 'phase2/stage2/synth/mixed_probe_synth.v',
            'powered_netlist': 'phase3/stage3/pnr/mixed_probe_pnl.v',
            'cdl': 'input/mixed_signal/mixed_probe.cdl',
            'routed_def': 'phase3/stage3/pnr/routed.def',
            'sdc': 'phase3/stage3/pnr/constraint.sdc',
            'spice_models': ['input/mixed_signal/sense_receiver.spice'],
            'cdl_models': ['input/mixed_signal/sense_receiver.cdl']}
    inputs = [p for p in project.rglob('*') if p.is_file() and
              not str(p.relative_to(project)).startswith('phase3/librelane/') and
              not str(p.relative_to(project)).startswith('reports/phase3/') and
              p.name != 'librelane_pdk_root.provenance.json' and
              p.name not in ('signoff.json', 'top_pv_run.json', 'top_pv.json')]
    spec['input_sha256'] = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(inputs)}
    path = project / 'input/mixed_signal/top_pv.json'
    path.write_text(json.dumps(spec, indent=2) + '\n')


def native_project(tmp_path):
    project = tmp_path / 'mixed'
    shutil.copytree(FIXTURE, project)
    # M1 evidence is freshly produced, never a fixture PASS assertion.
    cmd = ['docker', 'run', '--rm', '--memory=8g', '--memory-swap=8g',
           '-v', f'{project}:{project}', '-v', f'{PROGRAMS}:{PROGRAMS}:ro',
           IMAGE, '--skip', 'python3', str(PROGRAMS / 'mixed_signal_top_lvs_run.py'),
           str(project), '--top', 'mixed_probe', '--pdk', 'sky130A', '--container', 'host']
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    declare(project)
    return project


def test_ordinary_m4_runs_native_current_top_pv(tmp_path):
    project = native_project(tmp_path)
    assert m4.main([str(project), '--top', 'mixed_probe']) in (1, 2)
    result = json.loads((project / m4.OUTPUT).read_text())
    checks = {c['step']: c for c in result['checks']}
    rows = checks['PV_drc']['native'].get('rows', {})
    for key in ('magic__drc_error__count', 'klayout__drc_error__count'):
        assert rows.get(key, {}).get('value', 'NOT_MEASURED') == 0, checks['PV_drc']
    lvs = checks['PV_lvs']['native'].get('rows', {})
    assert lvs.get('design__lvs_error__count', {}).get('value', 'NOT_MEASURED') == 0, checks['PV_lvs']
    assert result['ready_for_tapeout'] is False
    assert m4.derive(project, 'mixed_probe') == result


@pytest.fixture(scope='module')
def current(tmp_path_factory):
    project = native_project(tmp_path_factory.mktemp('m4_current'))
    assert m4.main([str(project), '--top', 'mixed_probe']) == 2
    producer.verify(project, 'mixed_probe')
    return project


@pytest.mark.parametrize('damage', ['stale_gds', 'stale_logical', 'wrong_top',
                                   'foreign_path', 'foreign_symlink', 'receipt',
                                   'native_receipt', 'replay', 'missing_execution'])
def test_current_consumer_refuses_mutations(current, tmp_path, damage):
    project = current
    spec = json.loads((project / producer.REQUEST).read_text())
    rel = {'stale_gds': spec['layout'], 'stale_logical': spec['logical'],
           'wrong_top': producer.REQUEST, 'foreign_path': producer.REQUEST,
           'foreign_symlink': spec['logical'], 'receipt': producer.OUTPUT,
           'native_receipt': 'phase3/librelane/31-lvs/01-netgen-lvs/vibeic_receipt.json',
           'missing_execution': 'phase3/librelane/31-lvs/01-netgen-lvs/state_out.json'}.get(damage)
    if damage == 'replay':
        project = tmp_path / 'foreign_project'
        shutil.copytree(current, project)
        with pytest.raises(ValueError): producer.verify(project, 'mixed_probe')
        assert m4.audit(project)['passed'] is False
        return
    path = project / rel; original = path.read_bytes()
    try:
        if damage in ('stale_gds', 'stale_logical'): path.write_bytes(original + b'\n')
        elif damage == 'wrong_top':
            spec['top'] = 'foreign_top'; path.write_text(json.dumps(spec))
        elif damage == 'foreign_path':
            spec['logical'] = str(tmp_path / 'foreign.v'); path.write_text(json.dumps(spec))
        elif damage == 'foreign_symlink':
            outside = tmp_path / 'foreign.v'; outside.write_bytes(original)
            path.unlink(); path.symlink_to(outside)
        elif damage == 'missing_execution': path.unlink()
        else:
            data = json.loads(original)
            if damage == 'receipt': data['image'] = 'unverified-image'
            else: data['input']['step'] = 'Syntax.Only'
            path.write_text(json.dumps(data))
        with pytest.raises(ValueError): producer.verify(project, 'mixed_probe')
        assert m4.audit(project)['passed'] is False
        result = m4.derive(project, 'mixed_probe')
        assert result['ready_for_tapeout'] is False
        assert all(c['verdict'] != 'PASS' for c in result['checks'] if c['step'].startswith('PV_'))
    finally:
        if path.is_symlink(): path.unlink()
        path.write_bytes(original)
    producer.verify(current, 'mixed_probe')


def test_audit_is_read_only_and_does_not_certify_its_output(current, monkeypatch):
    before = producer.outputs(current)
    monkeypatch.setattr(producer, 'produce', lambda *a: pytest.fail('audit invoked a producer'))
    assert m4.main([str(current), '--check-only']) == 1
    assert gate.main([str(current), '--require-current-production']) == 1
    assert producer.outputs(current) == before


@pytest.mark.parametrize('damage', ['missing_input', 'missing_tool'])
def test_missing_declared_input_or_tool_is_not_measured(tmp_path, monkeypatch, damage):
    project = native_project(tmp_path)
    if damage == 'missing_input':
        spec = json.loads((project / producer.REQUEST).read_text())
        (project / spec['cdl']).unlink()
    else:
        def unavailable(*a, **k):
            raise contract.Refusal('LL_TOOL_UNAVAILABLE', 'declared native image/tool unavailable')
        monkeypatch.setattr(contract, 'pdk_root_resolution', unavailable)
    assert m4.main([str(project), '--top', 'mixed_probe']) == 2
    result = json.loads((project / m4.OUTPUT).read_text())
    assert result['ready_for_tapeout'] is False
    assert all(c['verdict'] == 'NOT_MEASURED' for c in result['checks'] if c['step'].startswith('PV_'))
    receipt = json.loads((project / producer.OUTPUT).read_text())
    assert receipt['refusals']
    assert receipt['native'] == {}


def test_real_logical_mismatch_fails_despite_unmeasured_second_engine(tmp_path):
    project = native_project(tmp_path)
    pnl = project / 'phase3/stage3/pnr/mixed_probe_pnl.v'
    original = pnl.read_text()
    changed = original.replace('.Y(Y)', '.Y(A)')
    assert changed != original
    pnl.write_text(changed)
    declare(project)
    assert m4.main([str(project), '--top', 'mixed_probe']) == 1
    receipt = producer.verify(project, 'mixed_probe')
    lvs = receipt['native']['lvs']
    assert lvs['rows']['design__lvs_error__count']['value'] > 0
    assert lvs['rows']['klayout__lvs_error__count']['value'] == 'NOT_MEASURED'
    assert lvs['verdict'] == 'FAIL'
    result = json.loads((project / m4.OUTPUT).read_text())
    assert result['verdict'] == 'FAIL' and result['ready_for_tapeout'] is False
    assert next(c for c in result['checks'] if c['step'] == 'PV_lvs')['verdict'] == 'FAIL'
    assert gate.main([str(project), '--require-current-production']) == 1
    assert m4.audit(project)['verdict'] == 'FAIL'




@pytest.mark.parametrize('damage', ['assertion', 'unbound_dependency', 'missing_hash', 'M1_identity', 'tool_selection'])
def test_incomplete_or_asserted_declaration_cannot_invoke_tools(current, monkeypatch, damage):
    spec_path = current / producer.REQUEST
    spec_bytes = spec_path.read_bytes(); spec = json.loads(spec_bytes)
    rel = {'unbound_dependency': spec['spice_models'][0],
           'M1_identity': 'reports/analog/mixed_signal/top_lvs.json',
           'tool_selection': 'phase3/librelane_switch.json'}.get(damage)
    path = current / rel if rel else None
    original = path.read_bytes() if path else None
    try:
        if damage == 'assertion': spec['ready_for_tapeout'] = True
        elif damage == 'missing_hash': spec['input_sha256'].pop(spec['powered_netlist'])
        elif damage == 'unbound_dependency':
            path.write_bytes(original + b'\n.include "unbound.sp"\n')
            spec['input_sha256'][rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif damage == 'tool_selection':
            data = json.loads(original); data['steps']['31'] = 'undeclared_tool'
            path.write_text(json.dumps(data))
            spec['input_sha256'][rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            data = json.loads(original); data['layout_top'] = 'other_design'
            path.write_text(json.dumps(data))
            spec['input_sha256'][rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        spec_path.write_text(json.dumps(spec))
        monkeypatch.setattr(contract, 'run_chain', lambda *a, **k: pytest.fail('preflight invoked tools'))
        with pytest.raises(ValueError): producer.request(current, 'mixed_probe')
        result = m4.derive(current, 'mixed_probe')
        assert all(c['verdict'] != 'PASS' for c in result['checks'] if c['step'].startswith('PV_'))
    finally:
        spec_path.write_bytes(spec_bytes)
        if path: path.write_bytes(original)


def test_full_devices_and_current_pdk_material_are_required(current, monkeypatch):
    folder = current / 'phase3/librelane/31-lvs/01-netgen-lvs'
    report = json.loads((folder / 'reports/lvs.netgen.json').read_text())
    cell = next(c for c in report['cells'] if c.get('name') == ['sense_receiver', 'sense_receiver'])
    assert all(sum(count for _, count in population) == 2 for population in cell['devices'])
    fp = json.loads((current / 'phase3/librelane/31-drc/01-magic-drc/input_fingerprint.json').read_text())
    # This disposable cache is resolved by the native producer from its image.
    # Mutate actual deck material, not a manufactured receipt or metric.
    path = next(Path(p) for p in fp['config_files'] if p.endswith('/sky130A.tech'))
    original = path.read_bytes()
    try:
        path.write_bytes(original + b'\n# reverse current material mutation\n')
        monkeypatch.setattr(contract, 'run_chain', lambda *a, **k: pytest.fail('audit invoked tools'))
        with pytest.raises(ValueError): producer.verify(current, 'mixed_probe')
        assert m4.audit(current)['passed'] is False
        assert m4.main([str(current), '--check-only', '--json', str(current / producer.OUTPUT)]) == 1
    finally:
        path.write_bytes(original)
    producer.verify(current, 'mixed_probe')
