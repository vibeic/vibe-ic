"""Signoff selects the actual native final State GDS and post-fill views."""
import json

import pytest

import _prestream_native as native


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path




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
    state = json.loads(final.read_text())
    state['gds'] = str(finished)
    put(final, state)
    return tmp_path, views, final, stream, finished


def test_real_shaped_canonical_signs_the_finished_gds_with_post_fill_views(canonical):
    project, views, final, stream, finished = canonical
    assert native.final_state(project, streamed=True) == final
    selected = native.signoff_inputs(project, 'gds', 'def', 'netlist', 'sdc', 'odb')
    assert selected['gds'] == finished != stream
    assert (selected['def'], selected['netlist'], selected['sdc'], selected['odb']) == (
        views['def'], views['nl'], views['sdc'], views['odb'])




@pytest.mark.parametrize('value', [123, ['finished.gds'], {'path': 'finished.gds'}])
def test_malformed_finished_gds_path_is_not_measured(canonical, value):
    project, _, final, _, _ = canonical
    doc = json.loads(final.read_text())
    doc['gds'] = value
    put(final, doc)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_VIEW_INVALID'):
        native.signoff_inputs(project, 'gds')


def test_views_other_than_gds_do_not_need_the_finishing_record(canonical):
    project, views, _, _, _ = canonical
    assert native.signoff_inputs(project, 'netlist') == {'netlist': views['nl']}








def test_finished_gds_absent_is_named(canonical):
    project, _, _, _, finished = canonical
    finished.unlink()
    with pytest.raises(ValueError, match='CURRENT_FINISHED_GDS_MISSING'):
        native.signoff_inputs(project, 'gds')


def test_later_stream_in_an_unnumbered_folder_is_refused_by_name(canonical):
    project, views, _, _, _ = canonical
    late = state_at(project, 'B-canon-stream/01-klayout-streamout', 'KLayout.StreamOut', views)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_UNORDERED') as exc:
        native.final_state(project, streamed=True)
    assert str(late) in str(exc.value)
