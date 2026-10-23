"""Existing Default native checkpoints retain their original authority/readset."""
import json
from pathlib import Path
import pytest
import flow109_final_extract as D
import librelane_fill_dfm as F
import librelane_contract as C
import _physical_current as V


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
    def validate(p):
        calls.append(p)
        return {'canonical': str(paths['gds']), 'image': 'pinned'}
    monkeypatch.setattr(F, 'validate_default_stream', validate)
    monkeypatch.setattr(C, 'validate_step_receipt', lambda *a: {})
    monkeypatch.setattr(V, 'default_signoff_inputs', lambda p: {
       'netlist': paths['v'], 'sdc': paths['sdc'], 'gds': paths['gds']})
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


@pytest.mark.parametrize('change,reason', [
    ('state', 'D69_RETAINED_STATE_CHANGED'), ('def', 'D69_RETAINED_DEF_CHANGED'),
    ('netlist', 'D69_RETAINED_ADOPTED_VIEW_MISMATCH'), ('image', 'D69_RETAINED_IMAGE_MISMATCH'),
    ('owner', 'LL_FINISHING_BYTES_CHANGED')])
def test_rejects_changed_native_authority_before_rcx(tmp_path, monkeypatch, change, reason):
    manifest, paths, state, calls = setup(tmp_path, monkeypatch)
    if change == 'state': state.write_text('{}')
    if change == 'def': paths['def'].write_text('changed')
    if change == 'netlist': manifest['adopted_views']['netlist'] = D.files._record(tmp_path, paths['sdc'])
    if change == 'image': manifest['librelane']['image'] = 'other'
    if change == 'owner':
        def refusal(p): raise C.Refusal('LL_FINISHING_BYTES_CHANGED', 'changed stream')
        monkeypatch.setattr(F, 'validate_default_stream', refusal)
    with pytest.raises((D.AdmissionRefusal, C.Refusal), match=reason):
        D._retained_geometry(tmp_path, manifest)


def test_retained_image_verification_does_not_write_provenance(tmp_path, monkeypatch):
    calls = []
    def resolve(project, *, record=True):
        calls.append(record)
        return 'pinned'
    monkeypatch.setattr(F, 'resolve_image', resolve)
    assert F._record_provider_binding(tmp_path, {'image': 'pinned'}) == 'pinned'
    assert calls == [False]
