"""Step 90 inputs: historical LEF spellings and the technology record."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution_backend_producers as backend
import librelane_contract as contract
import librelane_postroute as postroute
import phase3_one_shot_runner as runner

HISTORIC = '/foss/pdks/ciel/kit/versions/abc/kitD/libs.ref/'
CURRENT = '/nix/store/current/kitD/libs.ref/'
TECH, CELL = 'sc/techlef/sc__nom.tlef', 'sc/lef/sc.lef'
PADS = ['io/lef/io__in.lef', 'io/lef/io__bi.lef']


def run_with_inventory(tmp_path, recorded, *, macro_lefs=()):
    inventory = tmp_path / runner.PHYSICAL_VIEW_INVENTORY_REL
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text(json.dumps({'read_lef_paths': list(recorded)}))
    return SimpleNamespace(name='kitD', tech_lef=CURRENT + TECH, tech_lef_source=CURRENT + TECH,
                           cell_lef=CURRENT + CELL, macro_lefs=list(macro_lefs), macro_gds=[])


@pytest.fixture
def rejoin(tmp_path, monkeypatch):
    seen = []
    folder = tmp_path / 'sta'

    def resolve(values, where):
        assert where == folder
        seen.append(list(values))
        return [Path(CURRENT + value.split('/libs.ref/')[1]) for value in values]

    monkeypatch.setattr(postroute, 'stapostpnr_state', lambda project: (folder, {}))
    monkeypatch.setattr(contract, 'resolve_io_lefs_through_pad_lefs', resolve)
    monkeypatch.setattr(runner, '_local_exec_mode', lambda: True)
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda project: None)
    return seen


def historic(*names):
    return [HISTORIC + name for name in names]


def test_unavailable_io_lefs_rebind_as_a_set_and_the_cell_lef_is_not_read_twice(tmp_path, rejoin):
    pdk = run_with_inventory(tmp_path, historic(TECH, CELL, *PADS))
    done = runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    assert rejoin == [historic(*PADS)]
    assert pdk.macro_lefs == [CURRENT + name for name in PADS]
    assert done['macro_lefs'] == pdk.macro_lefs
    assert 'refused' not in done


def test_restoring_twice_adds_nothing(tmp_path, rejoin):
    pdk = run_with_inventory(tmp_path, historic(TECH, CELL, *PADS))
    runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    again = runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    assert pdk.macro_lefs == [CURRENT + name for name in PADS]
    assert again['macro_lefs'] == []


def test_a_view_already_loaded_under_its_current_spelling_is_not_read_twice(tmp_path, rejoin):
    pdk = run_with_inventory(tmp_path, historic(*PADS), macro_lefs=[CURRENT + PADS[0]])
    runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    assert pdk.macro_lefs == [CURRENT + PADS[0], CURRENT + PADS[1]]


def test_a_set_the_resolver_refuses_stops_the_window(tmp_path, rejoin, monkeypatch):
    def refuse(values, where):
        raise contract.Refusal('LL_IO_LEF_JOIN_REFUSED', 'different PDK-relative sets')

    monkeypatch.setattr(contract, 'resolve_io_lefs_through_pad_lefs', refuse)
    pdk = run_with_inventory(tmp_path, historic(TECH, CELL, *PADS))
    done = runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    assert 'LL_IO_LEF_JOIN_REFUSED' in done['refused']
    assert pdk.macro_lefs == []


def test_a_missing_step23_record_refuses_rather_than_passing_the_alias(tmp_path, rejoin, monkeypatch):
    def absent(project):
        raise contract.Refusal('LL_STAPOSTPNR_STATE_ABSENT', 'no record')

    monkeypatch.setattr(postroute, 'stapostpnr_state', absent)
    pdk = run_with_inventory(tmp_path, historic(*PADS))
    done = runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    assert 'LL_STAPOSTPNR_STATE_ABSENT' in done['refused']
    assert pdk.macro_lefs == []


def test_a_container_route_keeps_paths_only_the_container_can_read(tmp_path, rejoin, monkeypatch):
    monkeypatch.setattr(runner, '_local_exec_mode', lambda: False)
    pdk = run_with_inventory(tmp_path, historic(TECH, CELL, *PADS))
    runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    assert rejoin == []
    assert pdk.macro_lefs == historic(*PADS)


def test_a_readable_project_macro_lef_is_kept_as_recorded(tmp_path, rejoin):
    macro = tmp_path / 'input/pdk/macro.lef'
    macro.parent.mkdir(parents=True)
    macro.write_text('MACRO m\nEND m\n')
    pdk = run_with_inventory(tmp_path, [str(macro), *historic(CELL)])
    runner._restore_recorded_physical_views(tmp_path, pdk, 'eda')
    assert rejoin == []
    assert pdk.macro_lefs == [str(macro)]


@pytest.fixture
def step31(tmp_path, monkeypatch):
    calls = []
    final_def = tmp_path / 'phase3/stage3/pnr/filled.def'
    final_def.parent.mkdir(parents=True)
    final_def.write_text('DESIGN unit ;\nEND DESIGN\n')
    row = SimpleNamespace(status='PASS', detail='measured', extras={})

    def publish(project, pdk, container, definition, *, publish_declaration=True):
        calls.append(('publish', definition, publish_declaration))
        return {'verdict': 'PASS'}

    def step(name):
        def run(*args, **kwargs):
            calls.append((name,))
            return row
        return run

    R = SimpleNamespace(
        _layout_basis=lambda *a: ('basis', None),
        _restore_recorded_physical_views=lambda *a: {},
        _ga=SimpleNamespace(admitted_gds=lambda *a: True),
        publish_database_unit_declaration=publish,
        step_drc=step('drc'), step_lvs=step('lvs'),
        _DECLARED_SIGNOFF_GATES=[('drv_signoff',)],
        _run_declared_signoff_gate=lambda *a: row,
        _emit_erc_report=lambda *a: None)
    monkeypatch.setattr(backend, '_parameters', lambda project, params: (R, None, 'pdk', 'eda'))
    monkeypatch.setitem(sys.modules, '_native_erc', SimpleNamespace(emit=lambda *a: None))
    monkeypatch.setitem(sys.modules, 'perc_corpus_sweep', SimpleNamespace(main=lambda argv: 0))
    params = {'step_id': '31', 'top': 'unit', 'pdk_root': '/pdk', 'image_id': 'img',
              'execution_mode': 'default'}
    return tmp_path, final_def, calls, params


def inputs_at(monkeypatch, value):
    import _prestream_native as native

    def selected(project, *roles):
        assert roles == ('def',)
        if isinstance(value, Exception):
            raise value
        return {'def': value}

    monkeypatch.setattr(native, 'signoff_inputs', selected)


def test_default_step31_writes_the_technology_record_before_its_instruments(step31, monkeypatch):
    project, final_def, calls, params = step31
    inputs_at(monkeypatch, final_def)
    assert backend.produce_signoff(project, params)['verdict'] == 'PASS'
    assert calls[0] == ('publish', final_def, False)
    assert [call[0] for call in calls[1:]] == ['drc', 'lvs']


def test_default_step31_without_a_final_def_names_it_and_runs_no_instrument(step31, monkeypatch):
    project, _, calls, params = step31
    inputs_at(monkeypatch, ValueError('CURRENT_FINAL_STATE_VIEW_MISSING: def'))
    result = backend.produce_signoff(project, params)
    assert result['verdict'] == 'NOT_MEASURED'
    assert 'CURRENT_FINAL_STATE_VIEW_MISSING: def' in result['detail']
    assert calls == []


def test_other_modes_keep_their_stream_out_writer(step31, monkeypatch):
    project, final_def, calls, params = step31
    inputs_at(monkeypatch, final_def)
    backend.produce_signoff(project, {**params, 'execution_mode': 'diagnostic'})
    assert [call[0] for call in calls] == ['drc', 'lvs']


@pytest.mark.parametrize('verdict', ['NOT_MEASURED', 'FAIL'])
def test_a_stopped_row_reports_its_producer_not_a_malformed_census(tmp_path, monkeypatch, verdict):
    monkeypatch.setattr(backend, '_native_current_step_output_snapshot', lambda *a: {})
    monkeypatch.setattr(backend, 'produce_signoff',
                        lambda project, params: {'verdict': verdict, 'detail': 'ERC refused'})
    monkeypatch.setattr(backend, '_native_current_step_producer', lambda sid: None)
    result = backend._produce(tmp_path, {'step_id': '31', 'stop_on_producer_failure': True})
    census = result['current_step_declared_producers']
    allowed, reason, authority = backend._current_step_producer_authority(census, project=tmp_path)
    assert allowed is False
    assert 'malformed' not in reason and verdict in reason
    assert authority == 'NOT_MEASURED'
    assert result['verdict'] == verdict
