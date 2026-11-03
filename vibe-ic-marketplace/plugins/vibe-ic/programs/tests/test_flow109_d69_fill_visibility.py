"""Native owner wiring controls; fixture receipts are not extraction qualification."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from flow109_admission import AdmissionRefusal
import flow109_final_extract as d69

# Resolved before any test patches shutil.which or subprocess.run.
_REDUCER = shutil.which('vibeic-final-fill-spef')
_RUN = subprocess.run


def _d62(fill_count=None, **untrusted):
    measurements = {} if fill_count is None else {'fill_count_after': fill_count}
    return {'measurements': measurements, **untrusted}


@pytest.mark.parametrize('count,reason', [
    (None, 'D69_CURRENT_FINAL_FILL_CORRELATION_NOT_MEASURED'),
    (0, 'D69_CURRENT_FINAL_FILL_CORRELATION_NOT_MEASURED'),
    (147, 'D69_CURRENT_FINAL_FILL_CORRELATION_NOT_MEASURED'),
])
def test_fill_scope_is_derived_from_native_census(count, reason):
    assert d69._fill_extraction_scope(_d62(count)) == {
        'status': 'NOT_MEASURED',
        'reason': reason,
        'native_fill_count': count,
        'basis': 'source-owned D62 census; current final-GDS correlation remains separate',
    }


def test_forged_verified_string_cannot_upgrade_fill_scope():
    baseline = d69._fill_extraction_scope(_d62(147))
    forged = d69._fill_extraction_scope(_d62(147, extraction_fill_sensitivity='VERIFIED'))
    assert forged == baseline
    assert forged['status'] == 'NOT_MEASURED'


def test_consumer_refuses_forged_fill_sensitive_pass():
    scope = d69._fill_extraction_scope(_d62(147))
    record = {
        'reason': 'D69_FINAL_STATE_RCX_MEASURED',
        'component_scope': 'final_filled_odb_rcx_component_only',
        'fill_sensitive_parasitics': {**scope, 'status': 'PASS'},
    }
    with pytest.raises(AdmissionRefusal, match='D69_COMPONENT_SCOPE_CHANGED'):
        d69._component_scope(record, _d62(147))


def _owner_fixture(tmp_path, monkeypatch, *, top="neutral", adopted_views=None,
                   def_text=None, rcx_nets=(('A', 50), ('B', 200))):
    from types import SimpleNamespace
    def record(path):
        return d69.files._record(tmp_path, path)
    paths = {}
    for name, text in {
        'filled.odb': 'unit ODB placeholder', 'final.gds': 'unit GDS placeholder',
        'filled.def': def_text or ('VERSION 5.8 ;\nDESIGN neutral ;\n'
            'UNITS DISTANCE MICRONS 1000 ;\nNETS 2 ;\n'
            '- A ( PIN A ) + USE SIGNAL ;\n- B ( PIN B ) + USE SIGNAL ;\nEND NETS\nEND DESIGN\n'),
        'netlist.v': 'module neutral; endmodule', 'constraint.sdc': '',
        'tech': 'unit extraction-tech placeholder', 'tool': 'unit subprocess double',
    }.items():
        path = tmp_path / name; path.write_text(text.replace('neutral', top)); paths[name] = path
    d62 = tmp_path / 'd62.json'
    d62.write_text(json.dumps({'outputs': {'filled.def': record(paths['filled.def'])}}))
    manifest = {'schema': d69.SCHEMA, 'd62_receipt': record(d62),
        'stream_bridge': {'path': 'bridge.json', 'sha256': 'fixture'},
        'librelane': {'image': 'unit', 'pdk_root': str(tmp_path), 'pdk': 'unit'},
        'adopted_views': adopted_views or {'netlist': record(paths['netlist.v']),
                          'sdc': record(paths['constraint.sdc'])}}
    target = tmp_path / d69.INPUT; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest))
    odb = record(paths['filled.odb']); launches = []
    monkeypatch.setattr(d69, 'require_launch_admission', lambda *a, **kw: None)
    monkeypatch.setattr(d69.density, 'validate_filled_odb', lambda *a, **kw:
                        {'odb': odb, 'measurements': {'fill_count_after': 147}})
    monkeypatch.setattr(d69.files, 'validate_bridge', lambda *a, **kw:
        {'d62_receipt': manifest['d62_receipt'], 'odb': odb, 'gds': record(paths['final.gds'])})
    def rcx(*args, **kwargs):
        assert kwargs['extract'] is True and kwargs['time'] is False
        assert kwargs['routed_odb'] == paths['filled.odb']
        folder = tmp_path / 'phase3/librelane/flow109-d69'; folder.mkdir(parents=True, exist_ok=True)
        spefs = {}
        for corner in ('min', 'nom', 'max'):
            spef = folder / f'{corner}.spef'
            spef.write_text(f'*SPEF "IEEE 1481-1998"\n*DESIGN "{top}"\n*C_UNIT 1 FF\n' + ''.join(
                f'*D_NET {net} {value}\n*CAP\n1 {net}:1 {value}\n*RES\n1 {net}:1 {net}:2 1.0\n*END\n'
                for net, value in rcx_nets))
            spefs[f'{corner}_*'] = str(spef)
        (folder / 'state_out.json').write_text(json.dumps({'spef': spefs}))
        (folder / 'vibeic_receipt.json').write_text('{}')
        rcx_calls.append(kwargs)
        return {'rcx': folder, 'spef': spefs}
    rcx_calls = []
    monkeypatch.setattr(d69.signoff, 'run', rcx)
    monkeypatch.setattr(d69.signoff, 'bind_rcx_spefs', lambda *a, **kw: {'producer': 'OpenROAD.RCX'})
    def which(name):
        assert name == 'vibeic-final-fill-spef'
        return str(paths['tool'])
    monkeypatch.setattr(d69.shutil, 'which', which)
    original_run = d69.subprocess.run
    def invoke(argv, **kwargs):
        if argv[0] != str(paths['tool']):
            return original_run(argv, **kwargs)
        launches.append(argv)
        folder = Path(argv[argv.index('--output-dir') + 1]); folder.mkdir()
        keep = folder / 'routed-nets.txt'; keep.write_text('A\nB\n')
        corners = {}
        for corner in ('min', 'nom', 'max'):
            leaf = folder / corner; leaf.mkdir()
            raw, final = leaf / 'raw.spef', leaf / 'final.spef'
            text = ('*SPEF "IEEE 1481-1998"\n*DESIGN "neutral"\n*C_UNIT 1 PF\n'
                    '*D_NET A 0.1\n*CAP\n1 A 0.1\n*END\n'
                    '*D_NET B 0.2\n*CAP\n1 B 0.2\n*END\n')
            raw.write_text(text.replace('neutral', top)); final.write_text(text.replace('neutral', top))
            corners[corner] = {'status': 'PASS',
                'method': 'exact-capacitance-matrix-schur-complement',
                'floating_boundary_condition': 'zero-net-charge',
                'grounded_fill_approximation': False, 'retained_net_count': 2}
            for key, path in (('raw_spef', raw), ('keep_nets', keep), ('output_spef', final)):
                corners[corner].update({key: str(path), key + '_sha256': d69._sha(path)})
        receipt = {'status': 'PASS', 'geometry': {'path': str(paths['final.gds']),
                   'sha256': d69._sha(paths['final.gds'])},
            'routed_def': {'path': str(paths['filled.def']), 'sha256': d69._sha(paths['filled.def'])},
            'top': top, 'fill_aware_tech': record(paths['tech']),
            'declared_corner_set': ['min', 'nom', 'max'], 'keep_net_count': 2,
            'keep_nets_sha256': d69._sha(keep), 'corners': corners,
            'floating_boundary_condition': 'zero-net-charge', 'grounded_fill_approximation': False}
        (folder / 'FINAL_FILL_EXTRACTION.json').write_text(json.dumps(receipt))
        return SimpleNamespace(returncode=0, stdout='unit double, no native calibration', stderr='')
    monkeypatch.setattr(d69.subprocess, 'run', invoke)
    return paths, launches


def test_sta_spefs_are_the_openrcx_outputs_on_the_final_state(tmp_path, monkeypatch):
    paths, launches = _owner_fixture(tmp_path, monkeypatch)
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    assert result['component_status'] == 'PASS', result
    assert result['reason'] == 'D69_FINAL_STATE_RCX_MEASURED'
    assert set(result['final_spefs']) == {'min', 'nom', 'max'}
    assert all('flow109-d69' in ref['path'] for ref in result['final_spefs'].values())
    assert result['fill_sensitive_parasitics']['status'] == 'NOT_MEASURED'
    current = d69.validate_final_parasitics(tmp_path, result['receipt'])
    assert current['spefs'] == current['final_spefs'] == result['final_spefs']
    assert current['final_gds'] == result['final_gds']
    assert current['flow109_acceptance'] == 'NOT_MEASURED'
    fill_totals = {row['fill_totals']['path'] for row in result['fill_net_comparison']['corners'].values()}
    assert len(fill_totals) == 3 and not fill_totals & {r['path'] for r in current['spefs'].values()}


def test_net_capacitance_comparison_is_reported_in_common_units(tmp_path, monkeypatch):
    paths, launches = _owner_fixture(tmp_path, monkeypatch)
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    argv = launches[0]
    assert argv[1] == 'extract'
    assert argv[argv.index('--gds') + 1] == str(paths['final.gds'])
    assert argv[argv.index('--def') + 1] == str(paths['filled.def'])
    comparison = result['fill_net_comparison']
    assert comparison['status'] == 'MEASURED'
    nom = comparison['corners']['nom']
    assert (nom['common_nets'], nom['only_openrcx'], nom['only_fill']) == (2, 0, 0)
    assert nom['openrcx_total_pf'] == pytest.approx(0.25)
    assert nom['fill_total_pf'] == pytest.approx(0.3)
    assert nom['fill_over_openrcx']['min'] == pytest.approx(1.0)
    assert nom['fill_over_openrcx']['max'] == pytest.approx(2.0)


def test_nets_only_one_side_has_are_counted_not_compared(tmp_path, monkeypatch):
    _owner_fixture(tmp_path, monkeypatch, rcx_nets=(('A', 100), ('C', 1)))
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    nom = result['fill_net_comparison']['corners']['nom']
    assert (nom['common_nets'], nom['only_openrcx'], nom['only_fill']) == (1, 1, 1)


@pytest.mark.parametrize('failure', ['absent', 'refused', 'no_receipt'])
def test_a_failed_comparison_leaves_the_openrcx_verdict_alone(tmp_path, monkeypatch, failure):
    _owner_fixture(tmp_path, monkeypatch)
    if failure == 'absent':
        monkeypatch.setattr(d69.shutil, 'which', lambda name: None)
    else:
        code = 1 if failure == 'refused' else 0
        monkeypatch.setattr(d69.subprocess, 'run', lambda *a, **kw:
                            SimpleNamespace(returncode=code, stdout='', stderr=''))
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    assert result['component_status'] == 'PASS', result
    assert result['fill_net_comparison']['status'] == 'NOT_MEASURED'
    assert d69.validate_final_parasitics(tmp_path, result['receipt'])['final_spefs'] == result['final_spefs']


def test_openrcx_failure_is_the_verdict_and_skips_the_comparison(tmp_path, monkeypatch):
    _, launches = _owner_fixture(tmp_path, monkeypatch)
    def failed(*args, **kwargs):
        raise d69.Refusal('LL_STEP_FAILED', 'OpenROAD.RCX')
    monkeypatch.setattr(d69.signoff, 'run', failed)
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    assert (result['component_status'], result['reason']) == ('FAIL', 'LL_STEP_FAILED')
    assert not launches and 'fill_net_comparison' not in result


def test_native_configuration_is_required_before_openrcx_starts(tmp_path, monkeypatch):
    _owner_fixture(tmp_path, monkeypatch)
    target = tmp_path / d69.INPUT
    manifest = json.loads(target.read_text()); del manifest['librelane']
    target.write_text(json.dumps(manifest))
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    assert result['reason'] == 'D69_NATIVE_CONFIGURATION_ABSENT'
    assert result['native_started'] is False


@pytest.mark.parametrize('damage', ['spef', 'state', 'binding'])
def test_consumer_refuses_changed_openrcx_output(tmp_path, monkeypatch, damage):
    _owner_fixture(tmp_path, monkeypatch)
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    if damage == 'spef':
        (tmp_path / result['final_spefs']['min']['path']).write_text('changed')
    if damage == 'state':
        state = tmp_path / result['rcx_state']['path']
        value = json.loads(state.read_text()); del value['spef']['max_*']
        state.write_text(json.dumps(value))
        path = d69._bound(tmp_path, result['receipt'])
        record = json.loads(path.read_text()); record['rcx_state'] = d69.files._record(tmp_path, state)
        path.write_text(json.dumps(record)); result['receipt'] = d69.files._record(tmp_path, path)
    if damage == 'binding':
        monkeypatch.setattr(d69.signoff, 'bind_rcx_spefs', lambda *a, **kw: {'producer': 'other'})
    with pytest.raises((AdmissionRefusal, d69.Refusal)):
        d69.validate_final_parasitics(tmp_path, result['receipt'])


needs_reducer = pytest.mark.skipif(_REDUCER is None, reason='shipped vibeic-final-fill-spef absent')


def _raw_spef(degrees, conn='', ground='0.5'):
    width = max(degrees)
    text = '*SPEF "IEEE 1481-1998"\n*DESIGN "neutral"\n*C_UNIT 1 PF\n\n'
    text += ''.join(f'*D_NET R{i} 0.1\n*CAP\n1 R{i} 0.1\n*END\n\n' for i in range(1, width + 1))
    for k, degree in enumerate(degrees, 1):
        text += (f'*D_NET F{k} 1\n' + conn.replace('F1', f'F{k}') + f'*CAP\n1 F{k} {ground}\n'
                 + ''.join(f'{i + 1} F{k} R{i} 0.01\n' for i in range(1, degree + 1)) + '*END\n\n')
    return text


def _guarded_extract(tmp_path, monkeypatch, degrees, **raw):
    width = max(degrees)
    nets = ''.join(f'- R{i} ( PIN R{i} ) + USE SIGNAL ;\n' for i in range(1, width + 1))
    paths, _ = _owner_fixture(tmp_path, monkeypatch, rcx_nets=[('R1', 100)], def_text=(
        f'VERSION 5.8 ;\nDESIGN neutral ;\nUNITS DISTANCE MICRONS 1000 ;\nNETS {width} ;\n'
        f'{nets}END NETS\nEND DESIGN\n'))
    launches = []

    def extract(argv, **kwargs):
        if argv[0] != str(paths['tool']):
            return _RUN(argv, **kwargs)
        launches.append(argv)
        folder = Path(argv[argv.index('--output-dir') + 1]); folder.mkdir()
        keep = folder / 'routed-nets.txt'
        keep.write_text(''.join(f'R{i}\n' for i in range(1, width + 1)))
        bound = argv[argv.index('--max-degree'):][:2] if '--max-degree' in argv else []
        corners = {}
        for corner in ('nom', 'max', 'min'):
            leaf = folder / corner; leaf.mkdir()
            (leaf / 'raw.spef').write_text(_raw_spef(degrees, **raw))
            proc = _RUN([_REDUCER, 'reduce', '--raw', str(leaf / 'raw.spef'), '--keep-nets', str(keep),
                         '--output', str(leaf / 'final.spef'), '--receipt', str(leaf / 'reduction.json'),
                         *bound], capture_output=True, text=True)
            if proc.returncode:
                return SimpleNamespace(returncode=proc.returncode, stdout='', stderr=proc.stderr)
            corners[corner] = json.loads((leaf / 'reduction.json').read_text())
        receipt = {'status': 'PASS', 'top': 'neutral', 'corners': corners,
                   'geometry': {'path': str(paths['final.gds']), 'sha256': d69._sha(paths['final.gds'])},
                   'routed_def': {'path': str(paths['filled.def']), 'sha256': d69._sha(paths['filled.def'])},
                   'fill_aware_tech': d69.files._record(tmp_path, paths['tech']),
                   'declared_corner_set': ['min', 'nom', 'max'], 'keep_net_count': width,
                   'keep_nets_sha256': d69._sha(keep), 'floating_boundary_condition': 'zero-net-charge',
                   'grounded_fill_approximation': False}
        (folder / 'FINAL_FILL_EXTRACTION.json').write_text(json.dumps(receipt))
        return SimpleNamespace(returncode=0, stdout=json.dumps(receipt), stderr='')
    monkeypatch.setattr(d69.subprocess, 'run', extract)
    return launches


@needs_reducer
@pytest.mark.parametrize('degree,bound', [(40, None), (80, 160)])
def test_shipped_degree_guard_measures_and_one_relaunch_covers_it(tmp_path, monkeypatch, degree, bound):
    launches = _guarded_extract(tmp_path, monkeypatch, [degree])
    result = d69.execute(tmp_path, {'context_sha256': 'degree-control'})
    assert result['component_status'] == 'PASS', result
    comparison = result['fill_net_comparison']
    assert comparison['status'] == 'MEASURED', comparison
    assert '--max-degree' not in launches[0]
    assert comparison['execution']['argv'] == launches[-1]
    if bound is None:
        assert len(launches) == 1 and 'degree_bound' not in comparison
        return
    assert len(launches) == 2 and launches[1][-2:] == ['--max-degree', str(bound)]
    measuring = comparison['degree_bound'].pop('measuring_execution')
    assert comparison['degree_bound'] == {'floating_node': 'F1', 'measured_degree': degree,
        'tool_limit': 64, 'headroom_factor': 2, 'max_degree': bound}
    assert measuring['argv'] == launches[0] and measuring['returncode'] == 2


@needs_reducer
@pytest.mark.parametrize('raw,refusal', [
    ({'conn': '*CONN\n*P F1 I\n'}, 'refusing to eliminate non-retained net F1 with ports or resistance'),
    ({'ground': 'nan'}, 'invalid capacitance nan: ground CAP'),
])
def test_other_shipped_refusals_are_not_relaunched(tmp_path, monkeypatch, raw, refusal):
    launches = _guarded_extract(tmp_path, monkeypatch, [80], **raw)
    result = d69.execute(tmp_path, {'context_sha256': 'degree-control'})
    assert result['component_status'] == 'PASS', result
    comparison = result['fill_net_comparison']
    assert (comparison['status'], comparison['reason']) == ('NOT_MEASURED', 'FILL_TOOL_REFUSED')
    assert len(launches) == 1 and 'degree_bound' not in comparison
    assert f'REFUSED: {refusal}' in d69._bound(tmp_path, comparison['execution']['log']).read_text()


@needs_reducer
def test_a_degree_beyond_the_measured_bound_stays_refused(tmp_path, monkeypatch):
    launches = _guarded_extract(tmp_path, monkeypatch, [70, 150])
    result = d69.execute(tmp_path, {'context_sha256': 'degree-control'})
    assert result['component_status'] == 'PASS', result
    comparison = result['fill_net_comparison']
    assert comparison['reason'] == 'FILL_TOOL_REFUSED'
    assert len(launches) == 2 and launches[1][-2:] == ['--max-degree', '140']


@pytest.mark.parametrize('returncode,stderr', [
    (1, 'REFUSED: floating node F degree 80 exceeds fail-closed limit 64\n'),
    (2, 'REFUSED: floating node F degree 64 exceeds fail-closed limit 64\n'),
    (2, 'REFUSED: floating node F degree 80 exceeds fail-closed limit 64 later\n'),
    (2, 'REFUSED: x\nREFUSED: floating node F degree 80 exceeds fail-closed limit 64\n'),
    (2, 'REFUSED: refusing to eliminate non-retained net F with ports or resistance\n'),
])
def test_only_the_shipped_degree_refusal_is_a_measurement(returncode, stderr):
    assert d69._measured_degree(SimpleNamespace(returncode=returncode, stderr=stderr)) is None
