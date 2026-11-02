"""Current-owner PERC uses the real emitter and canonical consumer; no aliases."""
import json
import shutil
from pathlib import Path

import pytest

import _flow_yaml
import execution_adapters_backend as adapters
import execution_backend_producers as backend
import execution_policy as policy
import librelane_contract as contract
import librelane_ir_antenna as ir
import phase3_one_shot_runner as runner
from _hostpaths import require_repo
from test_backend_input_contract_sdc import _project
from test_d57_current_native_preflight import _install_current
from test_u22_perc_sweep_lef_class import _perc_project


def _write(root, rel, value):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return p


def _scene(tmp_path):
    project, pdk = _perc_project(tmp_path)
    upstream = _project(tmp_path / 'upstream')
    shutil.copytree(upstream, project, dirs_exist_ok=True)
    legacy = project / 'phase3/stage3/pnr/chip_top.def'
    physical = legacy.read_text().replace('DESIGN chip_top', 'DESIGN neutral')
    project, folder, views = _install_current(project)
    views['def'].write_text(physical)
    # The neutral instrument reissues the real input/output fingerprint after
    # selecting its physical view. Production validation is not mocked.
    fingerprint = json.loads((folder / 'input_fingerprint.json').read_text())
    import hashlib
    fingerprint['state_files'][str(views['def'])] = hashlib.sha256(views['def'].read_bytes()).hexdigest()
    (folder / 'input_fingerprint.json').write_text(json.dumps(fingerprint))
    hashes = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in folder.rglob('*') if p.is_file() and p.name != 'vibeic_receipt.json'}
    (folder / 'vibeic_receipt.json').write_text(json.dumps({'input': fingerprint, 'sha256': hashes}))
    import hashlib
    io_lef = project / 'input/pdk/libs.ref/neutral_io/lef/io.lef'
    sc_lef = _write(project, 'input/pdk/sc.lef', 'MACRO neutral_logic\n CLASS CORE ;\nEND neutral_logic\n')
    _write(project, 'reports/phase3/io_pad_chip_top.json', {'verdict': 'WROTE', 'io_library_lefs': [str(io_lef)]})
    config = json.loads((folder / 'config.json').read_text())
    config.update(CELL_LEFS=[str(sc_lef)], PAD_LEFS=[str(io_lef)], EXTRA_LEFS=[])
    (folder / 'config.json').write_text(json.dumps(config))
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    receipt['input']['config_files'].update({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (sc_lef, io_lef)})
    receipt['sha256']['config.json'] = hashlib.sha256((folder / 'config.json').read_bytes()).hexdigest()
    (folder / 'input_fingerprint.json').write_text(json.dumps(receipt['input']))
    receipt['sha256']['input_fingerprint.json'] = hashlib.sha256((folder / 'input_fingerprint.json').read_bytes()).hexdigest()
    (folder / 'vibeic_receipt.json').write_text(json.dumps(receipt))
    wrong = 'DESIGN chip_top ;\nCOMPONENTS 1 ;\n- stale core_cell ;\nEND COMPONENTS\nEND DESIGN\n'
    legacy.write_text(wrong)
    _write(project, 'phase3/stage3/pnr/routed.def', wrong)
    for name in ('antenna', 'ir_drop', 'em', 'erc'):
        _write(project, f'reports/phase3/{name}.json', {'verdict': 'PASS'})
    return project, folder, views, pdk


def _issued(project):
    out = {}
    policy._fixed_inputs({'project': project, 'policy': {'mode': 'default'}}, '28', parameters=out)
    return out['resolved_input_manifest']


def _row(project, pdk, monkeypatch):
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *_: {
        'pdk_root': str(project / 'input/pdk'), 'image_id': 'SOURCE_CONTROL_ONLY'})
    monkeypatch.setattr(backend, '_parameters', lambda *_: (runner, None, pdk, 'SOURCE_CONTROL_ONLY'))
    return runner._default_pnr_rows(project, 'chip_top', pdk, 'SOURCE_CONTROL_ONLY', ['28'])


@pytest.mark.parametrize('verdict', ['PASS', 'ERC_DIRTY'])
def test_current_perc_whole_default_emitter_and_consumer(tmp_path, monkeypatch, verdict):
    project, _, views, pdk = _scene(tmp_path)
    _write(project, 'reports/phase3/erc.json', {'verdict': verdict})
    result = _row(project, pdk, monkeypatch)
    doc = json.loads((project / 'reports/phase3/perc_equivalent.json').read_text())
    esd = next(c for c in doc['categories'] if c['category'] == 'ESD protection presence')
    assert esd['pad_count'] == 4, esd  # Base reads the stale one-component DEF.
    assert esd['esd_presence'] == 'PRESENT', esd
    assert views['def'].is_file()
    assert doc['commercial_calibre_perc_run'] is False
    assert result.status == ('PASS' if verdict == 'PASS' else 'FAIL'), result.detail
    assert doc['verdict'] == ('PERC_EQUIV_PASS' if verdict == 'PASS' else 'PERC_EQUIV_FAIL')
    assert (project / 'reports/phase3/PERC_SIGNOFF_MEMO.md').is_file()
    assert (project / 'reports/phase2/gates/perc_signoff.json').is_file()


def test_current_perc_manifest_reuses_checked_in_parent_contract(tmp_path):
    artifact = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'phase1_phase2_phase3.yaml')
    assert artifact.is_file()
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '28')
    assert {'from': 21, 'path': 'phase3/stage3/pnr/routed.def'} in row['required_inputs']
    project, folder, views, _ = _scene(tmp_path)
    issued = _issued(project)
    assert issued['missing'] == []
    assert str(views['def'].relative_to(project)) in issued['files']
    assert str((folder / 'state_out.json').relative_to(project)) in issued['files']
    assert ir.CURRENT_STA_RECORD in issued['files']
    assert 'phase3/stage3/pnr/routed.def' not in [x.get('path') for x in issued['declarations'] if isinstance(x, dict)]


@pytest.mark.parametrize('damage', ['missing', 'stale_def', 'stale_state'])
def test_current_perc_refuses_invalid_owner_before_publication(tmp_path, damage):
    project, folder, views, _ = _scene(tmp_path)
    if damage == 'missing':
        views['def'].unlink()
    elif damage == 'stale_def':
        views['def'].write_text(views['def'].read_text() + 'changed\n')
    else:
        (folder / 'state_out.json').write_text('{}\n')
    error = contract.Refusal if damage == 'stale_state' else ValueError
    match = 'LL_STAPOSTPNR_STATE_DRIFT' if damage == 'stale_state' else 'current STAPostPNR'
    with pytest.raises(error, match=match):
        _issued(project)
    assert not (project / 'reports/phase3/perc_equivalent.rpt').exists()


def test_legacy_and_explicit_final_subject_contracts_unchanged(tmp_path, monkeypatch):
    project, pdk = _perc_project(tmp_path)
    # No current-owner manifest: an explicit final-subject caller still uses
    # its own issued DEF. It must not silently switch to an unrelated owner.
    monkeypatch.setattr(backend, '_parameters', lambda *_: (runner, None, pdk, 'SOURCE_CONTROL_ONLY'))
    got = backend.produce_signoff(project, {
        'step_id': '28', 'top': 'chip_top', 'pdk_root': str(tmp_path),
        'image_id': 'SOURCE_CONTROL_ONLY', 'execution_mode': 'default',
        'resolved_input_manifest': {'files': {}}})
    assert got['verdict'] == 'PASS'
    doc = json.loads((project / 'reports/phase3/perc_equivalent.json').read_text())
    assert next(c for c in doc['categories'] if c['category'] == 'ESD protection presence')['pad_count'] == 4
    declarations = ({'from': 21, 'path': 'phase3/stage3/pnr/routed.def'},)
    assert adapters.backend_canonical_input_contract(project, '28', declarations, execution_mode='ultra') == declarations
    assert adapters.backend_canonical_input_contract(project, '28', declarations, execution_mode='default') == declarations


def _reseal(folder):
    import hashlib
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    for name in receipt['input']['state_files']:
        receipt['input']['state_files'][name] = contract.digest(Path(name))
    (folder / 'input_fingerprint.json').write_text(json.dumps(receipt['input']))
    receipt['sha256'] = {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in folder.rglob('*') if p.is_file() and p.name != 'vibeic_receipt.json'}
    (folder / 'vibeic_receipt.json').write_text(json.dumps(receipt))


def _geometry_scene(tmp_path, monkeypatch, *, gap=False):
    import re
    from test_default_current_power import original_transport
    project, folder, views, pdk = _scene(tmp_path)
    # No naming tokens: authoritative CORE/WELLTAP/PAD/ENDCAP classes alone
    # distinguish two coincident populations at opposite sides of the die.
    sc = project / 'input/pdk/sc.lef'
    sc.write_text('MACRO neutral_logic\n CLASS CORE ;\nEND neutral_logic\n'
                  'MACRO substrate\n CLASS CORE WELLTAP ;\nEND substrate\n')
    receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
    receipt['input']['config_files'][str(sc)] = contract.digest(sc)
    (folder / 'vibeic_receipt.json').write_text(json.dumps(receipt))
    text = views['def'].read_text()
    text = re.sub(r'(- \S+ \S+) ;', r'\1 + FIXED ( 350000 350000 ) N ;', text)
    extra = [f'- a{i} neutral_logic + PLACED ( {200000 if gap else 1000+i} 1000 ) N ;' for i in range(80)]
    extra += ['- s0 substrate + PLACED ( 1000 1000 ) N ;']
    text = re.sub(r'COMPONENTS (\d+)', lambda m: f'COMPONENTS {int(m[1])+81}', text)
    text = text.replace('END COMPONENTS', '\n'.join(extra)+'\nEND COMPONENTS')
    text = 'UNITS DISTANCE MICRONS 1000 ;\nDIEAREA ( 0 0 ) ( 400000 400000 ) ;\n'+text
    original = original_transport(tmp_path, monkeypatch, project, folder)
    original['def'].write_text(text)
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    state.update(odb=str(original['odb']), **{'def': str(original['def'])}, nl=str(original['netlist']), sdc=str(original['sdc']))
    state_path.write_text(json.dumps(state))
    fp = json.loads((folder / 'vibeic_receipt.json').read_text())
    fp['input']['state_files'].update({str(original[k]):contract.digest(original[k]) for k in ('odb','def','netlist','sdc')})
    (folder / 'vibeic_receipt.json').write_text(json.dumps(fp))
    _reseal(folder)
    marker = project / ir.CURRENT_STA_RECORD
    doc = json.loads(marker.read_text());doc['sta_state_sha256'] = contract.digest(state_path);marker.write_text(json.dumps(doc))
    return project, folder, original['def'], pdk


@pytest.mark.parametrize('gap', [False, True])
def test_full_row_external_def_uses_complete_lef_roles(tmp_path, monkeypatch, gap):
    project, folder, native_def, pdk = _geometry_scene(tmp_path, monkeypatch, gap=gap)
    issued = _issued(project)
    assert issued['missing'] == []
    result = _row(project, pdk, monkeypatch)
    doc = json.loads((project/'reports/phase3/perc_equivalent.json').read_text())
    geom = next(c for c in doc['categories'] if c['category'] == 'Latch-up tap spacing (geometry)')
    assert geom['geometry_status'] == ('WELLTAP_SPACING_GAP' if gap else 'SPACING_OK_NECESSARY_NOT_SUFFICIENT')
    context = doc.get('geometry_lef_context', {})
    assert context.get('def', {}).get('path') == str(native_def)
    assert context['roles']['neutral_io__corner'] == 'ENDCAP TOPLEFT'
    assert context['roles']['neutral_logic'] == 'CORE'
    assert context['roles']['substrate'] == 'CORE WELLTAP'
    assert result.status == ('FAIL' if gap else 'PASS'), result.detail
    gate=json.loads((project/'reports/phase2/gates/perc_signoff.json').read_text())
    assert gate['verdict'] == ('FAIL' if gap else 'PASS_WITH_OPEN_ITEMS')
    assert doc['manual_review_pending']  # Geometry never certifies device physics.
    assert 'reports/phase3/io_pad_chip_top.json' in issued['files']
    assert 'input/pdk/sc.lef' in issued['files']


@pytest.mark.parametrize('damage', ['missing_io', 'wrong_io', 'stale_io', 'missing_sc', 'conflict', 'missing_role', 'unsupported_role'])
def test_full_row_lef_authority_refusal(tmp_path, monkeypatch, damage):
    project, folder, native_def, pdk = _geometry_scene(tmp_path, monkeypatch)
    io_record = project/'reports/phase3/io_pad_chip_top.json'
    io_lef = project/'input/pdk/libs.ref/neutral_io/lef/io.lef'
    if damage == 'missing_sc':
        (project/'input/pdk/sc.lef').unlink()
    elif damage == 'missing_io':
        io_record.unlink()
    elif damage == 'wrong_io':
        wrong = _write(project, 'wrong.lef', io_lef.read_text())
        io_record.write_text(json.dumps({'verdict':'WROTE','io_library_lefs':[str(wrong)]}))
    elif damage == 'stale_io':
        io_lef.write_text(io_lef.read_text()+'\n# changed\n')
    else:
        text = io_lef.read_text()
        if damage == 'conflict':
            text += '\nMACRO neutral_io__corner\n CLASS CORE ;\nEND neutral_io__corner\n'
        elif damage == 'missing_role':
            text=text.replace('CLASS ENDCAP TOPLEFT ;','')
        else:
            text=text.replace('CLASS ENDCAP TOPLEFT ;','CLASS BLOCK ;')
        io_lef.write_text(text)
        receipt=json.loads((folder/'vibeic_receipt.json').read_text())
        receipt['input']['config_files'][str(io_lef)] = contract.digest(io_lef)
        (folder/'vibeic_receipt.json').write_text(json.dumps(receipt));_reseal(folder)
    with pytest.raises((ValueError, OSError), match='PERC_LEF|LL_INPUT_CHANGED|LL_INPUT_MATERIAL_MISSING|No such file'):
        _issued(project)
    assert not (project/'reports/phase3/perc_equivalent.rpt').exists()
