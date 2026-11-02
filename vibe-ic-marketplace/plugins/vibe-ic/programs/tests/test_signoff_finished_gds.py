"""Ruling 93b: signoff reads the GDS the finishing publisher named, not the stream."""
import hashlib
import json

import pytest

import _prestream_native as native


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_at(project, folder, step, state):
    base = project / 'phase3/librelane' / folder
    put(base / 'config.json', {'meta': {'step': step}})
    return put(base / 'state_out.json', {k: str(v) for k, v in state.items()})


@pytest.fixture
def canonical(tmp_path):
    """The real default flow's layout: seal, fill and top-up follow the final stream."""
    ll = tmp_path / 'phase3/librelane'
    fill = ll / '34/01-openroad-fillinsertion'
    views = {'nl': put(fill / 'chip_top.nl.v', 'netlist'), 'sdc': put(fill / 'chip_top.sdc', 'sdc'),
             'odb': put(fill / 'chip_top.odb', 'odb'),
             'def': put(tmp_path / 'phase3/stage3/pnr/filled.def', 'filled def')}
    for folder, step, name in (('15-floorplan/47-magic-streamout', 'Magic.StreamOut', 'gds'),
                               ('15-floorplan/48-klayout-streamout', 'KLayout.StreamOut', 'klayout_gds')):
        old = put(ll / folder / 'chip_top.gds', 'floorplan stream')
        state_at(tmp_path, folder, step, {name: old, 'def': views['def']})
    stream = put(ll / '37-default-stream/01-klayout-streamout/chip_top.klayout.gds', 'unfinished')
    final = state_at(tmp_path, '37-default-stream/01-klayout-streamout', 'KLayout.StreamOut',
                     {**views, 'klayout_gds': stream})
    sealed = put(ll / '26.5ic/01-klayout-sealring/chip_top.gds', 'sealed')
    state_at(tmp_path, '26.5ic/01-klayout-sealring', 'KLayout.SealRing', {'gds': sealed})
    filled = put(ll / '34-fill/01-klayout-filler/chip_top.gds', 'filled')
    state_at(tmp_path, '34-fill/01-klayout-filler', 'KLayout.Filler', {'gds': filled})
    topped = put(ll / '34-fill-topup/chip_top.topped.gds', 'finished')
    finished = put(tmp_path / 'phase3/stage4/gds/spm.gds', 'finished')
    record = put(ll / '37-default-promotion.json', {
        'stream': str(stream), 'stream_sha256': sha(stream),
        'stream_state': str(final), 'stream_state_sha256': sha(final),
        'source': str(topped), 'source_sha256': sha(topped),
        'canonical': str(finished), 'canonical_sha256': sha(finished)})
    return tmp_path, views, final, stream, finished, record


def test_real_shaped_canonical_signs_the_finished_gds_with_post_fill_views(canonical):
    project, views, final, stream, finished, _ = canonical
    assert native.final_state(project, streamed=True) == final
    selected = native.signoff_inputs(project, 'gds', 'def', 'netlist', 'sdc', 'odb')
    assert selected['gds'] == finished != stream
    assert (selected['def'], selected['netlist'], selected['sdc'], selected['odb']) == (
        views['def'], views['nl'], views['sdc'], views['odb'])


def test_missing_finishing_record_is_named(canonical):
    project, _, _, _, _, record = canonical
    record.unlink()
    with pytest.raises(ValueError, match='CURRENT_FINISHED_GDS_RECORD_MISSING: '
                                         'phase3/librelane/37-default-promotion.json'):
        native.signoff_inputs(project, 'gds')


@pytest.mark.parametrize('value', [123, ['finished.gds'], {'path': 'finished.gds'}])
@pytest.mark.parametrize('half', ['drc', 'lvs'])
def test_malformed_finished_gds_path_is_not_measured(canonical, value, half):
    import phase3_one_shot_runner as runner

    project, _, _, _, _, record = canonical
    doc = json.loads(record.read_text())
    doc['canonical'] = value
    put(record, doc)
    try:
        row = runner._step31_librelane(project, 'unit', None, half, publish=False)
        observed = row.status, row.detail
    except TypeError as exc:
        observed = type(exc).__name__, str(exc)
    assert observed[0] == 'NOT_MEASURED'
    assert 'CURRENT_FINISHED_GDS_RECORD_INVALID: canonical' in observed[1]


def test_views_other_than_gds_do_not_need_the_finishing_record(canonical):
    project, views, _, _, _, record = canonical
    record.unlink()
    assert native.signoff_inputs(project, 'netlist') == {'netlist': views['nl']}


def test_record_naming_another_stream_state_is_refused(canonical):
    project, _, _, _, _, record = canonical
    doc = json.loads(record.read_text())
    doc['stream_state'] = str(project / 'phase3/librelane/15-floorplan/48-klayout-streamout/state_out.json')
    put(record, doc)
    with pytest.raises(ValueError, match='CURRENT_FINISHED_GDS_OTHER_STATE'):
        native.signoff_inputs(project, 'gds')


def test_finished_gds_changed_after_publication_is_refused(canonical):
    project, _, _, _, finished, _ = canonical
    finished.write_text('rewritten')
    with pytest.raises(ValueError, match='CURRENT_FINISHED_GDS_CHANGED'):
        native.signoff_inputs(project, 'gds')


def test_finished_gds_absent_is_named(canonical):
    project, _, _, _, finished, _ = canonical
    finished.unlink()
    with pytest.raises(ValueError, match='CURRENT_FINISHED_GDS_MISSING'):
        native.signoff_inputs(project, 'gds')


def test_later_stream_in_an_unnumbered_folder_is_refused_by_name(canonical):
    project, views, _, _, _, _ = canonical
    late = state_at(project, 'B-canon-stream/01-klayout-streamout', 'KLayout.StreamOut', views)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_UNORDERED') as exc:
        native.final_state(project, streamed=True)
    assert str(late) in str(exc.value)
