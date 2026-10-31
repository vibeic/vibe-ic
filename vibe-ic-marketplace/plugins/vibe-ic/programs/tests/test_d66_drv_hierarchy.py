"""A DRV replay must consume the same bound hierarchy as its native STA."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drv_capture_plan as plan
import drv_signoff_capture as capture
import librelane_contract as contract


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def native_fixture(tmp_path, *, patterns=None):
    folder = tmp_path / 'native'
    child = tmp_path / 'child.v'
    child.write_text('module child(input a, output z); assign z=a; endmodule\n')
    spef = tmp_path / 'child.nom.spef'
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    config = {'STA_MACRO_PRIORITIZE_NL': True, 'MACROS': {'child': {
        'nl': [str(child)], 'spef': {p: [str(spef)] for p in (patterns or ['nom_*'])},
        'instances': {'mprj': {}}}}}
    fp = {'step': 'OpenROAD.STAPostPNR', 'config_files': {
        str(p): contract.digest(p) for p in (child, spef)}}
    put(folder / 'config.json', config)
    put(folder / 'state_out.json', {'metrics': {}})
    put(folder / 'input_fingerprint.json', fp)
    put(folder / 'pdk_root.json', {'path': '/fixture/pdk'})
    (folder / 'invocation.log').write_text('source-control fixture, no native PASS claim\n')
    put(folder / 'vibeic_receipt.json', {'input': fp, 'sha256': {
        p.name: contract.digest(p) for p in folder.iterdir() if p.is_file()}})
    return folder / 'state_out.json', child, spef


def test_declared_hierarchy_is_preserved(tmp_path):
    state, child, spef = native_fixture(tmp_path)
    views = plan._macro_scene_views(state, 'nom_ss_100C_1v60')
    assert views['linked_verilogs'] == [plan._ref(child)]
    assert views['instance_spefs'] == [{'instance': 'mprj', **plan._ref(spef)}]


@pytest.mark.parametrize('mutation', ['changed', 'missing'])
def test_macro_input_change_refuses(tmp_path, mutation):
    state, child, _ = native_fixture(tmp_path)
    if mutation == 'changed':
        child.write_text('changed netlist')
    else:
        child.unlink()
    with pytest.raises((ValueError, OSError)):
        plan._macro_scene_views(state, 'nom_ss_100C_1v60')


@pytest.mark.parametrize('patterns', [['max_*'], ['nom_*', '*']])
def test_absent_or_ambiguous_corner_refuses(tmp_path, patterns):
    state, _, _ = native_fixture(tmp_path, patterns=patterns)
    with pytest.raises(ValueError, match='corner population ambiguous'):
        plan._macro_scene_views(state, 'nom_ss_100C_1v60')


def test_replay_loads_child_netlist_and_instance_parasitics(tmp_path):
    state, child, child_spef = native_fixture(tmp_path)
    views = plan._macro_scene_views(state, 'nom_ss_100C_1v60')
    paths = {}
    for name in ['top.v', 'top.sdc', 'top.spef', 'cells.lib']:
        paths[name] = tmp_path / name
        paths[name].write_text('fixture\n')
    request = {'top': 'top', 'identity': {'artifacts': {'sta_netlist': plan._ref(paths['top.v'])}},
               'current': {'sources': {'signoff_sdc': plan._ref(paths['top.sdc'])}}}
    scene = {'linked_liberties': [plan._ref(paths['cells.lib'])],
             'spef': plan._ref(paths['top.spef']), **views}
    script = capture._script(request, scene, tmp_path, control=False, max_count=100)
    assert script.index('read_verilog {' + str(child) + '}') < script.index('link_design')
    assert 'read_spef -path {mprj} {' + str(child_spef) + '}' in script
    child_spef.write_text('stale bytes')
    with pytest.raises(ValueError, match='macro SPEF input changed'):
        capture._script(request, scene, tmp_path, control=False, max_count=100)
