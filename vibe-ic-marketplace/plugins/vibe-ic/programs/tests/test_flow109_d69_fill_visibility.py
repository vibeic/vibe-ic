"""Native owner wiring controls; fixture receipts are not extraction qualification."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flow109_admission import AdmissionRefusal
import flow109_final_extract as d69


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
        'reason': 'D69_NATIVE_FINAL_FILL_SPEF_MEASURED',
        'component_scope': 'native_final_gds_floating_fill_component',
        'fill_sensitive_parasitics': {**scope, 'status': 'PASS'},
    }
    with pytest.raises(AdmissionRefusal, match='D69_COMPONENT_SCOPE_CHANGED'):
        d69._component_scope(record, _d62(147))


def _owner_fixture(tmp_path, monkeypatch, *, top="neutral", adopted_views=None,
                   def_text=None):
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


def test_existing_owner_invokes_released_tool_on_final_gds_def_and_binds_spefs(tmp_path, monkeypatch):
    paths, launches = _owner_fixture(tmp_path, monkeypatch)
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    assert result['component_status'] == 'PASS', result
    assert result['native_started'] is True and len(launches) == 1
    argv = launches[0]
    assert argv[1] == 'extract'
    assert argv[argv.index('--gds') + 1] == str(paths['final.gds'])
    assert argv[argv.index('--def') + 1] == str(paths['filled.def'])
    assert argv[argv.index('--top') + 1] == 'neutral'
    assert set(result['final_spefs']) == {'min', 'nom', 'max'}
    assert result['fill_sensitive_parasitics']['status'] == 'NOT_MEASURED'
    assert result['fill_sensitive_parasitics']['reason'] == 'D69_CURRENT_FINAL_FILL_CORRELATION_NOT_MEASURED'
    current = d69.validate_final_parasitics(tmp_path, result['receipt'])
    assert current['final_spefs'] == result['final_spefs']
    assert current['final_gds'] == result['final_gds']
    assert current['flow109_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('damage', ['geometry', 'missing_corner', 'grounded', 'required_net', 'spef'])
def test_native_receipt_consumer_rejects_wrong_or_incomplete_final_inputs(tmp_path, monkeypatch, damage):
    _owner_fixture(tmp_path, monkeypatch)
    result = d69.execute(tmp_path, {'context_sha256': 'developer-control'})
    assert result['component_status'] == 'PASS', result
    receipt = d69._bound(tmp_path, result['native_receipt'])
    value = json.loads(receipt.read_text())
    if damage == 'geometry': value['geometry']['sha256'] = '0' * 64
    if damage == 'missing_corner': value['corners'].pop('max')
    if damage == 'grounded': value['grounded_fill_approximation'] = True
    if damage == 'required_net': value['corners']['min']['retained_net_count'] = 1
    if damage == 'spef': Path(value['corners']['min']['output_spef']).write_text('changed')
    receipt.write_text(json.dumps(value))
    with pytest.raises((AdmissionRefusal, d69.Refusal)):
        d69._native_outputs(tmp_path, d69.files._record(tmp_path, receipt),
                            result['final_gds'], result['final_def'])



def _observe_population(root, result):
    try:
        _, scans = d69._native_outputs(root, result['native_receipt'],
                                        result['final_gds'], result['final_def'])
    except AdmissionRefusal as exc:
        return {'status': exc.status, 'reason': exc.code, 'detail': exc.report['detail']}
    return {'status': 'ACCEPTED', 'counts': {corner: row['d_nets'] for corner, row in scans.items()}}


def _complete_result(root, monkeypatch, **kwargs):
    _owner_fixture(root, monkeypatch, **kwargs)
    result = d69.execute(root, {'context_sha256': 'compatibility-control'})
    assert result['component_status'] == 'PASS', result
    receipt = d69._read(d69._bound(root, result['native_receipt']))
    assert 'required_net_contract' not in receipt
    return result


def test_existing_producer_receipt_without_new_metadata_is_accepted(tmp_path, monkeypatch):
    result = _complete_result(tmp_path, monkeypatch)
    assert _observe_population(tmp_path, result) == {
        'status': 'ACCEPTED', 'counts': {'min': 2, 'nom': 2, 'max': 2}}
    assert result['flow109_acceptance'] == 'NOT_MEASURED'


def _damage_population(root, result, damage, corner='min'):
    receipt_path = d69._bound(root, result['native_receipt'])
    native = d69._read(receipt_path)
    rows = list(native['corners'].values()) if 'keep' in damage else [native['corners'][corner]]
    if 'keep' in damage:
        keep = Path(rows[0]['keep_nets'])
        keep.write_text({'missing_keep': 'A\n', 'duplicate_keep': 'A\nB\nB\n',
                         'unexpected_keep': 'A\nB\nforeign\n', 'shrunk_keep_and_output': 'A\n'}[damage])
        count = len([line for line in keep.read_text().splitlines() if line.strip()])
        native['keep_net_count'] = count
        native['keep_nets_sha256'] = d69._sha(keep)
        for row in rows:
            row['keep_nets_sha256'] = native['keep_nets_sha256']
            row['retained_net_count'] = count
    if damage in {'missing_output', 'shrunk_keep_and_output', 'duplicate_output', 'unexpected_output', 'renamed_output'}:
        for row in rows:
            path = Path(row['output_spef'])
            text = path.read_text()
            if damage in {'missing_output', 'shrunk_keep_and_output'}:
                text = text.split('*D_NET B')[0]
            elif damage in {'duplicate_output', 'unexpected_output'}:
                name = 'B' if damage == 'duplicate_output' else 'foreign'
                text += f'*D_NET {name} 0.1\n*CAP\n1 {name} 0.1\n*END\n'
            else:
                text = text.replace('*D_NET B ', '*D_NET foreign ')
            path.write_text(text)
            row['output_spef_sha256'] = d69._sha(path)
    receipt_path.write_text(json.dumps(native))
    result['native_receipt'] = d69.files._record(root, receipt_path)


@pytest.mark.parametrize('corner', ['min', 'nom', 'max'])
@pytest.mark.parametrize('damage,missing,unexpected,duplicates', [
    ('missing_output', ['B'], [], []),
    ('renamed_output', ['B'], ['foreign'], []),
    ('duplicate_output', [], [], ['B']),
    ('unexpected_output', [], ['foreign'], []),
])
def test_every_corner_rejects_missing_duplicate_or_unexpected_output_names(
        tmp_path, monkeypatch, corner, damage, missing, unexpected, duplicates):
    result = _complete_result(tmp_path, monkeypatch)
    _damage_population(tmp_path, result, damage, corner)
    observed = _observe_population(tmp_path, result)
    assert observed['status'] == 'FAIL', observed
    assert observed['reason'] == 'D69_REQUIRED_NET_CENSUS_FAILED', observed
    assert json.loads(observed['detail']) == {
        'corner': corner, 'artifact': 'output_spef', 'missing': missing,
        'unexpected': unexpected, 'duplicates': duplicates}


@pytest.mark.parametrize('damage,missing,unexpected,duplicates', [
    ('missing_keep', ['B'], [], []),
    ('shrunk_keep_and_output', ['B'], [], []),
    ('duplicate_keep', [], [], ['B']),
    ('unexpected_keep', [], ['foreign'], []),
])
def test_required_names_come_from_bound_def_not_self_consistent_keep_counts(
        tmp_path, monkeypatch, damage, missing, unexpected, duplicates):
    result = _complete_result(tmp_path, monkeypatch)
    _damage_population(tmp_path, result, damage)
    observed = _observe_population(tmp_path, result)
    assert observed['status'] == 'FAIL', observed
    assert observed['reason'] == 'D69_REQUIRED_NET_CENSUS_FAILED', observed
    assert json.loads(observed['detail']) == {
        'corner': 'min', 'artifact': 'keep_nets', 'missing': missing,
        'unexpected': unexpected, 'duplicates': duplicates}


def test_execute_blocks_fresh_hash_output_omission(tmp_path, monkeypatch):
    _owner_fixture(tmp_path, monkeypatch)
    native_run = d69.subprocess.run
    def invoke(argv, **kwargs):
        proc = native_run(argv, **kwargs)
        if '--output-dir' in argv:
            receipt = Path(argv[argv.index('--output-dir') + 1]) / 'FINAL_FILL_EXTRACTION.json'
            native = d69._read(receipt)
            row = native['corners']['max']
            output = Path(row['output_spef'])
            output.write_text(output.read_text().split('*D_NET B')[0])
            row['output_spef_sha256'] = d69._sha(output)
            receipt.write_text(json.dumps(native))
        return proc
    monkeypatch.setattr(d69.subprocess, 'run', invoke)
    observed = d69.execute(tmp_path, {'context_sha256': 'compatibility-control'})
    assert observed['component_status'] == 'FAIL', observed
    assert observed['reason'] == 'D69_REQUIRED_NET_CENSUS_FAILED', observed
    assert '"missing": ["B"]' in observed['detail']
    assert observed['flow109_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('nets', [
    'NETS 2 ;\n- A ( PIN A ) ;\nEND NETS\n',
    'NETS 1 ;\n- A ( PIN A ) ;\n',
    'SPECIALNETS 1 ;\n- A ( PIN A ) ;\nEND SPECIALNETS\n'
    'nets 1 ;\n- B ( PIN B ) ;\nend nets\n',
])
def test_incomplete_def_cannot_define_a_required_population(tmp_path, monkeypatch, nets):
    _owner_fixture(tmp_path, monkeypatch,
        def_text='DESIGN neutral ;\nUNITS DISTANCE MICRONS 1000 ;\n' + nets)
    result = d69.execute(tmp_path, {'context_sha256': 'compatibility-control'})
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D69_REQUIRED_NET_CONTRACT_UNAVAILABLE', result


def _rcx_signal_def(supplies_in_nets=False):
    supplies = '- VDD ( PIN VDD ) + USE POWER ;\n- VSS ( PIN VSS ) + USE GROUND ;\n'
    return ('DESIGN neutral ;\nUNITS DISTANCE MICRONS 1000 ;\n'
            'SPECIALNETS 2 ;\n' + supplies + 'END SPECIALNETS\n'
            f'NETS {4 if supplies_in_nets else 2} ;\n'
            '- A ( PIN A ) + USE SIGNAL ;\n- B ( PIN B ) + USE SIGNAL ;\n'
            + (supplies if supplies_in_nets else '') + 'END NETS\nEND DESIGN\n')


@pytest.mark.parametrize('supplies_in_nets', [False, True])
def test_rcx_shaped_signal_spef_omits_supply_d_nets(tmp_path, monkeypatch, supplies_in_nets):
    result = _complete_result(tmp_path, monkeypatch, def_text=_rcx_signal_def(supplies_in_nets))
    assert _observe_population(tmp_path, result) == {
        'status': 'ACCEPTED', 'counts': {'min': 2, 'nom': 2, 'max': 2}}
    current = d69.validate_final_parasitics(tmp_path, result['receipt'])
    assert current['final_spefs'] == result['final_spefs']
    assert current['flow109_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('corner', ['min', 'nom', 'max'])
def test_rcx_shaped_spef_missing_signal_net_is_refused(tmp_path, monkeypatch, corner):
    result = _complete_result(tmp_path, monkeypatch, def_text=_rcx_signal_def())
    _damage_population(tmp_path, result, 'missing_output', corner)
    observed = _observe_population(tmp_path, result)
    assert observed['status'] == 'FAIL', observed
    assert observed['reason'] == 'D69_REQUIRED_NET_CENSUS_FAILED', observed
    assert json.loads(observed['detail']) == {
        'corner': corner, 'artifact': 'output_spef', 'missing': ['B'],
        'unexpected': [], 'duplicates': []}


def _signal_specialnet_def(use='SIGNAL'):
    intent = '' if use is None else f' + USE {use}'
    return ('DESIGN neutral ;\nUNITS DISTANCE MICRONS 1000 ;\n'
            'SPECIALNETS 3 ;\n- VDD ( PIN VDD ) + USE POWER ;\n'
            '- VSS ( PIN VSS ) + USE GROUND ;\n'
            f'- B ( PIN B ){intent} ;\nEND SPECIALNETS\n'
            'NETS 1 ;\n- A ( PIN A ) ;\nEND NETS\nEND DESIGN\n')


@pytest.mark.parametrize('use', ['SIGNAL', 'CLOCK', None])
def test_use_signal_specialnet_and_single_terminal_net_are_accepted(tmp_path, monkeypatch, use):
    result = _complete_result(tmp_path, monkeypatch, def_text=_signal_specialnet_def(use))
    assert _observe_population(tmp_path, result) == {
        'status': 'ACCEPTED', 'counts': {'min': 2, 'nom': 2, 'max': 2}}
    assert d69.validate_final_parasitics(tmp_path, result['receipt'])['flow109_acceptance'] == 'NOT_MEASURED'


@pytest.mark.parametrize('corner', ['min', 'nom', 'max'])
def test_missing_signal_specialnet_is_refused(tmp_path, monkeypatch, corner):
    result = _complete_result(tmp_path, monkeypatch, def_text=_signal_specialnet_def())
    _damage_population(tmp_path, result, 'missing_output', corner)
    observed = _observe_population(tmp_path, result)
    assert observed['status'] == 'FAIL', observed
    assert observed['reason'] == 'D69_REQUIRED_NET_CENSUS_FAILED', observed
    assert json.loads(observed['detail']) == {
        'corner': corner, 'artifact': 'output_spef', 'missing': ['B'],
        'unexpected': [], 'duplicates': []}


@pytest.mark.parametrize('supplies', [('VDD',), ('VSS',), ('VDD', 'VSS')])
def test_supply_d_nets_are_refused_as_foreign(tmp_path, monkeypatch, supplies):
    result = _complete_result(tmp_path, monkeypatch, def_text=_signal_specialnet_def())
    receipt_path = d69._bound(tmp_path, result['native_receipt'])
    native = d69._read(receipt_path)
    row = native['corners']['min']
    path = Path(row['output_spef'])
    path.write_text(path.read_text() + ''.join(
        f'*D_NET {name} 0.1\n*CAP\n1 {name} 0.1\n*END\n' for name in supplies))
    row['output_spef_sha256'] = d69._sha(path)
    receipt_path.write_text(json.dumps(native))
    result['native_receipt'] = d69.files._record(tmp_path, receipt_path)
    observed = _observe_population(tmp_path, result)
    assert observed['status'] == 'FAIL', observed
    assert observed['reason'] == 'D69_REQUIRED_NET_CENSUS_FAILED', observed
    assert json.loads(observed['detail']) == {
        'corner': 'min', 'artifact': 'output_spef', 'missing': [],
        'unexpected': sorted(supplies), 'duplicates': []}


def test_supply_use_intent_is_shared_by_name_across_def_sections(tmp_path, monkeypatch):
    text = _rcx_signal_def().replace('\nNETS 2 ;', '\nNETS 4 ;').replace(
        'END NETS', '- VDD ( PIN VDD ) ;\n- VSS ( PIN VSS ) ;\nEND NETS')
    result = _complete_result(tmp_path, monkeypatch, def_text=text)
    assert _observe_population(tmp_path, result)['counts'] == {'min': 2, 'nom': 2, 'max': 2}


def test_quoted_use_property_does_not_change_signal_intent(tmp_path, monkeypatch):
    text = _signal_specialnet_def().replace(
        '- B ( PIN B ) + USE SIGNAL ;',
        '- B ( PIN B ) + PROPERTY note "+ USE POWER" + USE SIGNAL ;')
    result = _complete_result(tmp_path, monkeypatch, def_text=text)
    assert _observe_population(tmp_path, result)['status'] == 'ACCEPTED'


@pytest.mark.parametrize('uses', ['SIGNAL + USE POWER', 'SIGNAL + USE SIGNAL'])
def test_ambiguous_def_use_cannot_silently_exclude_signal(tmp_path, monkeypatch, uses):
    _owner_fixture(tmp_path, monkeypatch, def_text=_signal_specialnet_def(uses))
    result = d69.execute(tmp_path, {'context_sha256': 'use-intent-control'})
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D69_REQUIRED_NET_CONTRACT_UNAVAILABLE'
    assert result['detail'].endswith('ambiguous DEF net USE: B')


def test_conflicting_def_use_cannot_silently_exclude_signal(tmp_path, monkeypatch):
    text = _rcx_signal_def().replace('SPECIALNETS 2 ;', 'SPECIALNETS 3 ;').replace(
        'END SPECIALNETS', '- B ( PIN B ) + USE POWER ;\nEND SPECIALNETS')
    _owner_fixture(tmp_path, monkeypatch, def_text=text)
    result = d69.execute(tmp_path, {'context_sha256': 'use-intent-control'})
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D69_REQUIRED_NET_CONTRACT_UNAVAILABLE'
    assert result['detail'].endswith('conflicting DEF net USE: B')


def test_real_archived_def_prefix_has_insufficient_population_authority(tmp_path, monkeypatch):
    from _hostpaths import require_repo
    path = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
                        'fixtures', 'librelane_import', '8HD-9', 'runs', 'cmp3',
                        '52-openroad-fillinsertion', 'spm.def')
    top = d69.files.fill_records(path)['top']
    _owner_fixture(tmp_path, monkeypatch, top=top, def_text=path.read_text())
    result = d69.execute(tmp_path, {'context_sha256': 'compatibility-control'})
    assert result['component_status'] == 'NOT_MEASURED', result
    assert result['reason'] == 'D69_REQUIRED_NET_CONTRACT_UNAVAILABLE', result
    assert 'complete unambiguous DEF net declarations required' in result['detail']
