"""Existing Default native checkpoints retain their original authority/readset."""
import json
from pathlib import Path
import pytest
import flow109_final_extract as D
import librelane_fill_dfm as F
import librelane_contract as C


def setup(tmp_path, monkeypatch):
    owner = tmp_path / 'owner'
    report = owner / F.RECORD_REL
    report.parent.mkdir(parents=True)
    state = owner / 'phase3/librelane/34/01-openroad-fillinsertion/state_out.json'
    state.parent.mkdir(parents=True)
    paths = {k: owner / ('subject.' + k) for k in ['odb', 'def', 'v', 'sdc', 'gds']}
    paths['odb'] = state.parent / 'filled.odb'
    for path in paths.values(): path.write_text(str(path))
    state.write_text(json.dumps({'odb': str(paths['odb']), 'def': str(paths['def'])}))
    (state.parent / 'vibeic_receipt.json').write_text('{}')
    report.write_text(json.dumps({'odb': {'tool': {'state': str(state),
       'state_sha256': C.digest(state), 'filled_def_sha256': C.digest(paths['def'])}}}))
    calls = []
    def resolve(p, *, record=True):
        assert record is False
        calls.append(p)
        return 'pinned'
    monkeypatch.setattr(C, 'resolve_image', resolve)
    monkeypatch.setattr(C, 'validate_step_receipt', lambda *a: {})
    def forbidden(*args, **kwargs):
        pytest.fail('final-State extraction consulted legacy stream receipts')
    monkeypatch.setattr(F, 'validate_default_stream', forbidden)
    (owner / 'state_out.json').write_text(json.dumps({
       'odb': str(paths['odb']), 'def': str(paths['def']),
       'nl': str(paths['v']), 'sdc': str(paths['sdc']), 'gds': str(paths['gds'])}))
    manifest = {'retained_default_fill': D.files._record(tmp_path, report),
       'adopted_views': {'netlist': D.files._record(tmp_path, paths['v']),
                         'sdc': D.files._record(tmp_path, paths['sdc'])},
       'librelane': {'image': 'pinned'}}
    return manifest, paths, state, calls


def test_reopens_native_owner_and_retains_unknown_fill_scope(tmp_path, monkeypatch):
    manifest, paths, state, calls = setup(tmp_path, monkeypatch)
    result = D._retained_geometry(tmp_path, manifest)
    assert calls == [tmp_path / 'owner']
    assert D.files._bound(tmp_path, result['odb']) == paths['odb']
    assert D._fill_extraction_scope({})['status'] == 'NOT_MEASURED'


@pytest.mark.parametrize('view', ['odb', 'def'])
def test_retained_extraction_requires_final_state_physical_view(tmp_path, monkeypatch, view):
    manifest, _, _, _ = setup(tmp_path, monkeypatch)
    path = tmp_path / 'owner/state_out.json'
    state = json.loads(path.read_text())
    state.pop(view)
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_VIEW_MISSING: ' + view):
        D._retained_geometry(tmp_path, manifest)


def test_retained_extraction_selects_final_state_odb_and_def(tmp_path, monkeypatch):
    manifest, _, _, _ = setup(tmp_path, monkeypatch)
    path = tmp_path / 'owner/state_out.json'
    state = json.loads(path.read_text())
    expected = {}
    for view in ('odb', 'def'):
        final = tmp_path / 'owner' / ('final.' + view)
        final.write_text('final ' + view)
        state[view] = str(final)
        expected[view] = final
    path.write_text(json.dumps(state))
    result = D._retained_geometry(tmp_path, manifest)
    for role, view in (('odb', 'odb'), ('filled_def', 'def')):
        assert D.files._bound(tmp_path, result[role]) == expected[view]


@pytest.mark.parametrize('change,reason', [
    ('state', 'D69_RETAINED_STATE_CHANGED'), ('def', 'D69_RETAINED_DEF_CHANGED'),
    ('netlist', 'D69_RETAINED_ADOPTED_VIEW_MISMATCH'), ('image', 'D69_RETAINED_IMAGE_MISMATCH'),
    ('gds', 'CURRENT_FINAL_STATE_VIEW_MISSING: gds')])
def test_rejects_changed_native_authority_before_rcx(tmp_path, monkeypatch, change, reason):
    manifest, paths, state, calls = setup(tmp_path, monkeypatch)
    if change == 'state': state.write_text('{}')
    if change == 'def': paths['def'].write_text('changed')
    if change == 'netlist': manifest['adopted_views']['netlist'] = D.files._record(tmp_path, paths['sdc'])
    if change == 'image': manifest['librelane']['image'] = 'other'
    if change == 'gds': paths['gds'].unlink()
    with pytest.raises((D.AdmissionRefusal, C.Refusal, ValueError), match=reason):
        D._retained_geometry(tmp_path, manifest)


def test_retained_image_verification_does_not_write_provenance(tmp_path, monkeypatch):
    calls = []
    def resolve(project, *, record=True):
        calls.append(record)
        return 'pinned'
    monkeypatch.setattr(F, 'resolve_image', resolve)
    assert F._record_provider_binding(tmp_path, {'image': 'pinned'}) == 'pinned'
    assert calls == [False]
