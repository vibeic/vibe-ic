"""Native-folder reader controls. Simulators are not launched by this module."""
import json
import shutil

import pytest

import _plugin_tree  # noqa: F401
from _hostpaths import require_repo
import _default_backend_fixtures as BF
import librelane_contract as LC
import librelane_postroute as LP
import path_spice_tool as PST
import test_default_si_spice_power as base


def native_project(tmp_path):
    project, old, lib = base.project(tmp_path)
    folder = project / 'runs/native/55-openroad-stapostpnr'
    folder.parent.mkdir(parents=True)
    shutil.move(str(old), folder)
    for name in ('vibeic_receipt.json', 'input_fingerprint.json', 'pdk_root.json'):
        (folder / name).unlink()
    (project / LP.STEP23_RECORD).unlink()
    (project / 'phase3/librelane/22-config/OpenROAD.STAPostPNR.json').unlink()
    state = json.loads((folder / 'state_out.json').read_text())
    state['metrics'] = {'timing__setup__ws__corner:nom_typ': 0.2,
                        'timing__setup__ws__corner:slow_scene': -1.0}
    base.put(folder / 'state_out.json', state)
    base.write(folder / 'slow_scene/sta.log',
               "Reading cell library for the 'slow_scene' corner at '/pdk/neutral/neutral.lib'\n")
    base.write(project / 'fixture_pdk/neutral/libs.tech/ngspice/model.sp',
               '.model neutral nmos level=1\n')
    return project, folder, lib


def test_current_context_reads_native_folder_without_vibeic_files(tmp_path):
    project, folder, lib = native_project(tmp_path)
    try:
        subject, context = PST.current_context(project, BF.IMAGE,
                                               project / 'fixture_pdk', 'neutral')
        outcome = context['corner']
    except LC.Refusal as exc:
        outcome = str(exc)
    assert outcome == 'slow_scene'
    roles = {row['role']: row for row in subject['inputs']}
    assert roles['sta_state']['path'] == str(folder / 'state_out.json')
    assert roles['liberty:0']['path'] == str(lib)
    assert all('receipt' not in role and role != 'step23_record' for role in roles)


def test_run_step30_selects_worst_setup_from_native_metrics(tmp_path):
    project, folder, _ = native_project(tmp_path)
    try:
        doc = PST.run_step30(project, BF.IMAGE, project / 'fixture_pdk',
                             'neutral', simulators=())
        outcome = doc['corner']
    except LC.Refusal as exc:
        outcome = str(exc)
    assert outcome == 'slow_scene'
    assert doc['sta_state'] == str(folder / 'state_out.json')


def test_real_native_summary_selects_setup_worst_corner():
    repo = require_repo()
    folder = repo / ('vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/'
                     'librelane_import/8HD-9/runs/cmp3/55-openroad-stapostpnr')
    assert PST.worst_setup_corner(folder) == 'max_ss_125C_4v50'


def test_explicit_native_folder_resolves_ambiguity(tmp_path):
    project, folder, _ = native_project(tmp_path)
    other = project / 'runs/other/another-sta'
    shutil.copytree(folder, other)
    with pytest.raises(LC.Refusal, match='AMBIGUOUS'):
        PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral')
    _, context = PST.current_context(project, BF.IMAGE, project / 'fixture_pdk',
                                     'neutral', sta_step_dir=folder)
    assert context['corner'] == 'slow_scene'


@pytest.mark.parametrize('damage', ['config_step', 'missing_state', 'missing_netlist',
                                   'foreign_netlist', 'foreign_folder', 'foreign_log'])
def test_native_reader_refuses_missing_or_foreign_files(tmp_path, damage):
    project, folder, _ = native_project(tmp_path)
    state_path = folder / 'state_out.json'
    state = json.loads(state_path.read_text())
    if damage == 'config_step':
        config = json.loads((folder / 'config.json').read_text())
        config['meta']['step'] = 'OpenROAD.STAPrePNR'
        base.put(folder / 'config.json', config)
    elif damage == 'missing_state':
        state_path.unlink()
    elif damage == 'missing_netlist':
        __import__('pathlib').Path(state['nl']).unlink()
    elif damage == 'foreign_netlist':
        foreign = base.write(tmp_path / 'foreign.v', base.NETLIST)
        state['nl'] = str(foreign)
        base.put(state_path, state)
    elif damage == 'foreign_folder':
        moved = tmp_path / 'foreign-sta'
        shutil.move(str(folder), moved)
        folder.symlink_to(moved, target_is_directory=True)
    else:
        path = folder / 'slow_scene/sta.log'
        text = path.read_text()
        path.unlink()
        path.symlink_to(base.write(tmp_path / 'foreign.log', text))
    with pytest.raises((LC.Refusal, OSError, ValueError)):
        PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral',
                            sta_step_dir=folder)


@pytest.mark.parametrize('value', [None, True, 'unknown', float('nan'), float('inf')])
def test_native_reader_refuses_unmeasured_setup_corner(tmp_path, value):
    project, folder, _ = native_project(tmp_path)
    state = json.loads((folder / 'state_out.json').read_text())
    state['metrics']['timing__setup__ws__corner:slow_scene'] = value
    base.put(folder / 'state_out.json', state)
    with pytest.raises(LC.Refusal):
        PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral',
                            sta_step_dir=folder)
