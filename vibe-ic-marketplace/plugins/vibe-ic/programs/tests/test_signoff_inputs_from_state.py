"""Ruling 93 signoff inputs from one native final State."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import _prestream_native as native
import librelane_contract as contract
import librelane_pv_signoff as pv
import phase3_one_shot_runner as runner


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


@pytest.fixture
def subject(tmp_path, monkeypatch):
    views = {name: put(tmp_path / 'native' / ('final.' + name), name)
             for name in ('gds', 'def', 'nl', 'sdc', 'odb')}
    views['def'].write_text('DESIGN unit ;\nEND DESIGN\n')
    state = {name: str(path.relative_to(tmp_path)) for name, path in views.items()}
    state['metrics'] = {'route__drc_errors_final': 0}
    state_path = put(tmp_path / 'state_out.json', state)
    for name in ('unit.gds', 'unit.def', 'unit_pnr.v', 'constraint.sdc'):
        put(tmp_path / 'phase3/stage3/pnr' / name, 'old alias')
    monkeypatch.setattr(contract, 'resolve_image', lambda project: 'pinned')
    monkeypatch.setattr(contract, 'resolve_pdk_root', lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(runner, '_streamout_top', lambda *args: ('unit', None))
    monkeypatch.setattr(runner, '_stage_padring_io_lefs_for_lvs', lambda *args: [])
    monkeypatch.setattr(runner._lvs_pa, 'emit_to_file',
                        lambda source, pdk, output, **kwargs: output.write_text('powered'))

    def forbidden(*args, **kwargs):
        pytest.fail('signoff consulted a legacy 37.3 receipt')

    import librelane_fill_dfm as fill
    import _native373_current as streams
    import gds_xor_check as xor
    monkeypatch.setattr(fill, 'validate_default_stream', forbidden)
    monkeypatch.setattr(streams, 'read_current', forbidden)
    monkeypatch.setattr(xor, 'gds_connectivity', forbidden)
    calls = []

    def measured(*args, **kwargs):
        calls.append(kwargs)
        return {'verdict': 'PASS', 'metrics': {}, 'reasons': []}

    monkeypatch.setattr(pv, 'run_half', measured)
    pdk = SimpleNamespace(name='open_fixture', cell_lef='cells.lef')
    return tmp_path, views, state_path, pdk, calls


@pytest.mark.parametrize('half', ['drc', 'lvs'])
def test_step31_consumes_final_state_without_legacy_receipts(subject, half):
    project, views, _, pdk, calls = subject
    row = runner._step31_librelane(project, 'unit', pdk, half, publish=False)
    assert row.status == 'PASS', row.detail
    assert len(calls) == 1
    assert {name: calls[0][argument] for name, argument in (
        ('gds', 'gds'), ('def', 'routed_def'), ('nl', 'netlist'), ('sdc', 'sdc'))} == {
        name: views[name] for name in ('gds', 'def', 'nl', 'sdc')}


@pytest.mark.parametrize('half', ['drc', 'lvs'])
@pytest.mark.parametrize('view', ['gds', 'def', 'nl', 'sdc'])
def test_step31_missing_view_is_named_without_alias_fallback(subject, half, view):
    project, _, state_path, pdk, calls = subject
    state = json.loads(state_path.read_text())
    state.pop(view)
    put(state_path, state)
    row = runner._step31_librelane(project, 'unit', pdk, half, publish=False)
    assert row.status == 'NOT_MEASURED', row.detail
    assert view in row.detail
    assert calls == []


@pytest.mark.parametrize('half', ['drc', 'lvs'])
def test_step31_missing_state_does_not_use_existing_aliases(subject, half):
    project, _, state_path, pdk, calls = subject
    state_path.unlink()
    row = runner._step31_librelane(project, 'unit', pdk, half, publish=False)
    assert row.status == 'NOT_MEASURED', row.detail
    assert 'STATE' in row.detail
    assert calls == []


@pytest.mark.parametrize('half', ['drc', 'lvs'])
def test_step31_retains_native_failure(subject, monkeypatch, half):
    project, _, _, pdk, calls = subject

    def failed(*args, **kwargs):
        calls.append(kwargs)
        return {'verdict': 'FAIL', 'metrics': {}, 'reasons': ['native violation']}

    monkeypatch.setattr(pv, 'run_half', failed)
    row = runner._step31_librelane(project, 'unit', pdk, half, publish=False)
    assert row.status == 'FAIL', row.detail
    assert 'native violation' in row.detail
    assert len(calls) == 1


@pytest.mark.parametrize('view_name', ['gds', 'klayout_gds'])
def test_selected_native_gds_convention_and_relative_paths(subject, view_name):
    project, views, state_path, _, _ = subject
    state = json.loads(state_path.read_text())
    state[view_name] = state.pop('gds')
    state.pop('metrics')
    put(state_path, state)
    assert native.signoff_inputs(project, 'gds', 'def', 'netlist', 'sdc', 'odb') == {
        ('netlist' if name == 'nl' else name): value for name, value in views.items()}


@pytest.mark.parametrize('value', [None, '', ' ', [], {}, 'missing.nl'])
def test_missing_or_invalid_native_view_names_the_native_role(subject, value):
    project, _, state_path, _, _ = subject
    state = json.loads(state_path.read_text())
    state['nl'] = value
    put(state_path, state)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_VIEW_MISSING: nl'):
        native.signoff_inputs(project, 'netlist')


@pytest.mark.parametrize('damage', ['missing', 'empty', 'directory'])
def test_unavailable_view_file_is_named(subject, damage):
    project, views, _, _, _ = subject
    views['sdc'].unlink()
    if damage == 'empty':
        views['sdc'].touch()
    if damage == 'directory':
        views['sdc'].mkdir()
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_VIEW_MISSING: sdc'):
        native.signoff_inputs(project, 'sdc')


def test_declared_broken_gds_does_not_fall_back_to_other_stream(subject):
    project, views, state_path, _, _ = subject
    state = json.loads(state_path.read_text())
    state['klayout_gds'] = str(views['gds'])
    state['gds'] = 'missing.gds'
    put(state_path, state)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_VIEW_MISSING: gds'):
        native.signoff_inputs(project, 'gds')


def stream_state(project, folder, state, step='KLayout.StreamOut'):
    base = project / 'phase3/librelane' / folder
    put(base / 'config.json', {'meta': {'step': step}})
    return put(base / 'state_out.json', state)


@pytest.mark.parametrize('step', ['KLayout.StreamOut', 'Magic.StreamOut',
                                  'Vibeic.FillAwareStreamOut'])
def test_native_stream_state_precedes_stale_sta_pointer(subject, step):
    project, views, direct, _, _ = subject
    state = json.loads(direct.read_text())
    state['klayout_gds'] = state.pop('gds')
    direct.unlink()
    expected = stream_state(project, '37-stream/01-native-streamout', state, step)
    stale = put(project / 'phase3/librelane/23-sta/state_out.json', {
        'def': str(views['def']), 'odb': str(views['odb']), 'nl': 'old.v'})
    put(project / 'reports/phase3/sta_postpnr_signoff.json', {'sta_state': str(stale)})
    stream_state(project, '34-fill/01-klayout-filler', {'gds': 'partial.gds'}, 'KLayout.Filler')
    stream_state(project, '31-drc/01-klayout-drc', state, 'KLayout.DRC')
    assert native.final_state(project, streamed=True) == expected
    assert native.signoff_inputs(project, 'gds', 'netlist') == {
        'gds': views['gds'], 'netlist': views['nl']}


def test_missing_view_in_native_stream_does_not_use_stale_sta(subject):
    project, views, direct, _, _ = subject
    state = json.loads(direct.read_text())
    direct.unlink()
    stale = put(project / 'phase3/librelane/23-sta/state_out.json', state)
    put(project / 'reports/phase3/sta_postpnr_signoff.json', {'sta_state': str(stale)})
    state.pop('nl')
    stream_state(project, '37-stream/01-klayout-streamout', state)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_VIEW_MISSING: nl'):
        native.signoff_inputs(project, 'netlist')


def test_ambiguous_native_streams_refuse_selection(subject):
    project, _, direct, _, _ = subject
    state = json.loads(direct.read_text())
    direct.unlink()
    stream_state(project, 'first/01-klayout-streamout', state)
    stream_state(project, 'second/01-klayout-streamout', state)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_AMBIGUOUS'):
        native.signoff_inputs(project, 'gds')


def test_explicit_root_does_not_merge_a_missing_view_from_another_state(subject):
    project, _, direct, _, _ = subject
    state = json.loads(direct.read_text())
    stream_state(project, '37-stream/01-klayout-streamout', state)
    state.pop('def')
    state.pop('metrics')
    put(direct, state)
    with pytest.raises(ValueError, match='CURRENT_FINAL_STATE_VIEW_MISSING: def'):
        native.signoff_inputs(project, 'def')


def test_only_requested_views_are_required(subject):
    project, views, direct, _, _ = subject
    put(direct, {'def': str(views['def'])})
    assert native.signoff_inputs(project, 'def') == {'def': views['def']}
