"""Native-folder reader controls. Simulators are not launched by this module."""
import json
import shutil
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401
from _hostpaths import require_repo
import _default_backend_fixtures as BF
import librelane_contract as LC
import librelane_postroute as LP
import path_spice_tool as PST
import spice_correlation_check as SC
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


def test_native_config_owns_identity_even_with_a_foreign_receipt(tmp_path):
    project, folder, _ = native_project(tmp_path)
    base.put(folder / 'vibeic_receipt.json', {'input': {'step': 'Unrelated.Step'}})
    _, context = PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral')
    assert context['corner'] == 'slow_scene'


def test_native_corner_aliases_without_tool_outputs_are_not_missing_scenes(tmp_path):
    project, folder, _ = native_project(tmp_path)
    config = json.loads((folder / 'config.json').read_text())
    config['STA_CORNERS'] = ['nom_typ', 'slow_scene', 'equivalent_alias']
    base.put(folder / 'config.json', config)
    _, context = PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral')
    assert context['corner'] == 'slow_scene'


@pytest.mark.parametrize('archive', ['steps', 'reports/step_versions'])
def test_native_discovery_excludes_input_snapshot_copies(tmp_path, archive):
    project, folder, _ = native_project(tmp_path)
    shutil.copytree(folder, project / archive / 'attempt/inputs/runs/sta')
    assert PST.native_sta_folder(project) == folder


@pytest.mark.parametrize('layout', ['managed', 'imported'])
def test_normal_caller_selects_current_sta_and_preserves_run_chain_attempts(
        tmp_path, monkeypatch, layout):
    project, folder, _ = (base.project(tmp_path) if layout == 'managed'
                           else native_project(tmp_path))
    base.write(project / 'fixture_pdk/neutral/libs.tech/ngspice/model.sp',
               '.model neutral nmos level=1\n')
    archive = folder.parent / 'attempts' / (folder.name + '-0001')
    shutil.copytree(folder, archive)
    preserved = {path.relative_to(archive): LC.digest(path)
                 for path in archive.rglob('*') if path.is_file()}
    monkeypatch.setattr(LC, 'resolve_image', lambda *_: BF.IMAGE)
    monkeypatch.setattr(LC, 'pdk_root_resolution', lambda *_a, **_k: {
        'path': str(project / 'fixture_pdk')})
    reached = []
    def stop_before_native(*_args, **kwargs):
        reached.append(kwargs['sta_step_dir'])
        raise LC.Refusal('SOURCE_TEST_NATIVE_BOUNDARY', 'no native tools launched')
    monkeypatch.setattr(PST, 'run_step30', stop_before_native)
    result = SC.run_installed_pdk_path_correlation(project, '')
    assert result['reason'] == 'SOURCE_TEST_NATIVE_BOUNDARY: no native tools launched'
    assert reached == [folder]
    assert result['measurement'] == 'NOT_MEASURED'
    assert {path.relative_to(archive): LC.digest(path)
            for path in archive.rglob('*') if path.is_file()} == preserved


def test_native_discovery_does_not_adopt_an_archive_without_a_current_folder(tmp_path):
    project, folder, _ = native_project(tmp_path)
    archive = folder.parent / 'attempts' / (folder.name + '-0001')
    archive.parent.mkdir()
    folder.rename(archive)
    with pytest.raises(LC.Refusal, match='LL_STAPOSTPNR_STATE_ABSENT'):
        PST.native_sta_folder(project)


def test_native_input_manifest_excludes_retained_snapshots(tmp_path):
    import execution_policy as policy
    project, folder, _ = native_project(tmp_path)
    runtime = {'project': project, 'policy': {'mode': 'default'}}
    before = policy._fixed_inputs(runtime, '30')
    for archive in ('steps', 'reports/step_versions'):
        shutil.copytree(folder, project / archive / 'old/inputs/runs/native/sta')
    after = policy._fixed_inputs(runtime, '30')
    assert set(after) == set(before)
    assert not any(name.startswith(('steps/', 'reports/step_versions/')) for name in after)


def test_native_metrics_file_selects_the_setup_scene(tmp_path):
    project, folder, _ = native_project(tmp_path)
    state = json.loads((folder / 'state_out.json').read_text())
    metrics = state.pop('metrics')
    base.put(folder / 'state_out.json', state)
    base.put(folder / 'metrics.json', metrics)
    subject, context = PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral')
    assert context['corner'] == 'slow_scene'
    assert any(row['path'] == str(folder / 'metrics.json') for row in subject['inputs'])


@pytest.mark.parametrize('verdict', ['PASS', 'FAIL'])
def test_native_folder_current_producer_and_readback_preserve_verdict(tmp_path, monkeypatch, verdict):
    project, folder, lib = native_project(tmp_path)
    state = json.loads((folder / 'state_out.json').read_text())
    state['metrics'].pop('timing__setup__ws__corner:slow_scene')
    base.put(folder / 'state_out.json', state)
    (folder / 'slow_scene/sta.log').unlink()
    result = base.spice_produce(project, folder, lib, monkeypatch, verdict=verdict)
    assert result['status'] == 'RAN' and result['verdict'] == verdict
    gate = SC.run_audit(project, run_spice=False)
    assert gate.summary['current_binding'] == 'CURRENT'
    assert gate.summary['measurement'] == 'MEASURED'
    assert gate.summary['verdict'] == verdict
    assert gate.passed == (verdict == 'PASS')
    state['metrics']['timing__setup__ws__corner:nom_typ'] = -2.0
    base.put(folder / 'state_out.json', state)
    gate = SC.run_audit(project, run_spice=False)
    assert gate.summary['current_binding'] == 'REFUSED'
    assert gate.summary['measurement'] == 'NOT_MEASURED'


@pytest.mark.parametrize('source', ['config.json', 'state_out.json', 'metrics.json', 'summary.rpt'])
def test_native_reader_rejects_foreign_selection_sources(tmp_path, source):
    project, folder, _ = native_project(tmp_path)
    selected = folder / source
    payload = selected.read_text() if selected.is_file() else '{}'
    selected.unlink(missing_ok=True)
    selected.symlink_to(base.write(tmp_path / source, payload))
    with pytest.raises(LC.Refusal):
        PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral')


@pytest.mark.parametrize('damage', ['duplicate', 'missing_scene', 'nonfinite'])
def test_native_summary_refuses_incomplete_or_ambiguous_scenes(tmp_path, damage):
    project, folder, _ = native_project(tmp_path)
    state = json.loads((folder / 'state_out.json').read_text())
    state['metrics'] = {}
    base.put(folder / 'state_out.json', state)
    rows = ['│ nom_typ │ 0 │ 0 │ 0 │ 0 │ 0 │ 1.0 │',
            '│ slow_scene │ 0 │ 0 │ 0 │ 0 │ 0 │ -1.0 │']
    if damage == 'duplicate':
        rows.append(rows[-1])
    elif damage == 'missing_scene':
        rows.pop()
    else:
        rows[-1] = rows[-1].replace('-1.0', 'NaN')
    base.write(folder / 'summary.rpt', '\n'.join(rows) + '\n')
    with pytest.raises(LC.Refusal, match='LL_STEP30_CORNER_UNDECLARED'):
        PST.current_context(project, BF.IMAGE, project / 'fixture_pdk', 'neutral')


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
        Path(state['nl']).unlink()
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


def test_native_case_runs_without_requalifying_the_tool(tmp_path, monkeypatch):
    project, folder, _ = native_project(tmp_path)
    monkeypatch.setattr(PST, 'prepare_arm', lambda *a, **kw: {'prepared': 'native inputs'})
    seen = []
    def simulate(arm, **kwargs):
        seen.append(kwargs)
        return {'paths': [{'status': 'MEASURED', 'verdict': 'CORRELATED'}]}
    monkeypatch.setattr(PST, 'simulate_arm', simulate)
    result = PST.run_case_correlation(project, BF.IMAGE, project / 'fixture_pdk',
                                       'neutral', sta_step_dir=folder)
    assert result['verdict'] == 'PASS'
    assert result['corner'] == 'slow_scene'
    assert seen == [{'workers': 3, 'characterize': False}]
    assert (project / 'reports/phase3/spice_correlation.json').is_file()
