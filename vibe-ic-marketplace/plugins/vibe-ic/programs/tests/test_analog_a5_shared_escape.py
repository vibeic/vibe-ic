"""Direct controls for same-net capacitor escape and local rail allocation."""
from copy import deepcopy
import pytest
import _plugin_tree
import analog_a5_layout_emit as a
import analog_native_physical as physical


def geo():
    rules = {'metal_space_um': {1: .18, 2: .21, 3: .21, 4: .21, 5: .21, 6: 1.64, 7: 2.0},
             'metal_width_um': {1: .2, 2: .24, 3: .24, 4: .24, 5: .24, 6: 1.64, 7: 2.0},
             'metal_area_um2': {1: .09, 2: .144, 3: .144, 4: .144, 5: .144},
             'via_width_um': {1: .2, 2: .2, 3: .2, 4: .2, 5: .62, 6: 1.9},
             'via_space_um': {1: .21, 2: .21, 3: .21, 4: .21, 5: .22, 6: .06},
             'via_surround_um': {(1, 1): .005, (5, 6): .32}}
    return a.Geo(rules, .18, 100, .3, .15)


def capacitor(name, nets=('top', 'bottom')):
    return {'dev': {'name': name, 'class': 'capacitor', 'model': 'native_cap',
                    'nets': list(nets), 'pars': {'w': 10., 'l': 28.}},
            'cell': {'delta': (560, 1500)}, 'bbox': (-560, -1500, 560, 1500),
            'access_pitch': 400,
            'groups': [{'net': net, 'side': side, 'level': level, 'y': 0,
                        'escape_y': 0, 'strapped': False,
                        'labels': [{'x': x, 'y': 0, 'level': level}]}
                       for net, side, level, x in zip(nets, ('left', 'right'), (6, 5), (0, 500))]}


def test_identical_array_retains_instances_and_shares_only_edge_descents():
    ds = [capacitor('c'+str(i)) for i in range(9)]
    before = deepcopy([d['dev'] for d in ds])
    rows, rails, bus, desc = a._place_shared_rows(ds, ['top', 'bottom'], geo(), None, 260, ())
    assert len(rows) == 1
    assert [d['dev'] for d in ds] == before
    assert {d['groups'][0]['lane_x'] for d in ds} == {ds[0]['groups'][0]['lane_x']}
    assert {d['groups'][1]['lane_x'] for d in ds} == {ds[-1]['groups'][1]['lane_x']}
    assert {d['groups'][0]['shared_escape_owner'] for d in ds} == {'c0'}
    assert {d['groups'][1]['shared_escape_owner'] for d in ds} == {'c8'}
    assert min(ds[i+1]['box_x'] - ds[i]['right_lo'] for i in range(8)) >= 400
    assert desc[0]['rail_tracks'] == 1


@pytest.mark.parametrize('change', ['net', 'polarity', 'geometry', 'device_class'])
def test_distinct_devices_keep_private_high_plane_corridors(change):
    ds = [capacitor('c0'), capacitor('c1')]
    if change == 'net':
        ds[1]['dev']['nets'][0] = ds[1]['groups'][0]['net'] = 'other'
    elif change == 'polarity':
        ds[1]['dev']['nets'].reverse()
        for g, net in zip(ds[1]['groups'], ds[1]['dev']['nets']):g['net'] = net
    elif change == 'geometry':
        ds[1]['dev']['pars']['l'] = 27.
    else:
        ds[1]['dev']['class'] = 'resistor'
    a._place_shared_rows(ds, ['top', 'bottom', 'other'], geo(), None, 260, ())
    assert all('shared_escape_owner' not in g for d in ds for g in d['groups'])
    assert ds[1]['box_x'] - ds[0]['right_lo'] >= 1600


def test_local_rail_tracks_reuse_only_disjoint_intervals():
    row = [{'groups': [{'net': 'a', 'lane_x': 1000}, {'net': 'a', 'lane_x': 1100},
                       {'net': 'b', 'lane_x': 3000}, {'net': 'b', 'lane_x': 3100}]}]
    tracks = a._local_rail_tracks(row, {}, geo())
    assert tracks['a'] == tracks['b']
    shared = a._local_rail_tracks(row, {'a': 100, 'b': 200}, geo())
    assert shared['a'] != shared['b']
    row[0]['groups'][2]['lane_x'] = 1200
    row[0]['groups'][3]['lane_x'] = 1250
    near = a._local_rail_tracks(row, {}, geo())
    assert near['a'] != near['b']


def test_matching_unit_stays_in_one_row_and_escape_envelope_clears_rails():
    ds = [capacitor('c0'), capacitor('c1'), capacitor('c2')]
    for d in ds:
        d['dev']['class'] = 'mosfet'; d['access_pitch'] = 69
        for g in d['groups']:g['level'] = 2
    rows, rails, _, _ = a._place_shared_rows(ds, ['top', 'bottom'], geo(), None,
                                             44, [('c0', 'c2')])
    assert ds[0]['row'] == ds[2]['row']
    assert len(rows) == 2
    for d in ds:
        bottom = d['box_y'] + d['cell']['delta'][1] + d['bbox'][1]
        assert bottom > max(rails[d['row']].values())


def test_normal_A11_passes_shared_escape_option(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(physical, '_settings', lambda *args: {'shared_capacitor_escapes': True})
    def run(program, argv, **kwargs):
        seen.append((program, argv)); return {'returncode': 127}
    physical.run_step('A11', tmp_path, {'name': 'unit'}, {'pdk': 'ihp-sg13g2'}, run)
    assert seen[0][0] == 'analog_a5_layout_emit.py'
    assert '--shared-capacitor-escapes' in seen[0][1]
