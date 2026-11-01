"""Geometry and selection controls for the full-span parallel divider pair."""
from copy import deepcopy
import pytest
import _plugin_tree
import analog_a5_layout_emit as a
from test_analog_a5_left_right import fixture_devices
from test_analog_a5_shared_escape import capacitor, geo


def parallel_devices():
    pair = [capacitor('ra'), capacitor('rb')]
    for d in pair:
        d['dev']['class'] = 'resistor'
        d['bbox'] = (-9195, -127, 9195, 127)
        d['cell']['delta'] = (9195, 127)
        d['access_pitch'] = 69
        d['fullspan_pair'] = ('ra', 'rb')
        for g in d['groups']:
            g['level'] = 2
    return pair


def test_parallel_pair_keeps_same_x_in_adjacent_fullspan_subrows():
    ds = fixture_devices(7, 4) + parallel_devices()
    before = deepcopy([d['dev'] for d in ds])
    rows, _, _, desc = a._place_left_right_rows(
        ds, ['top', 'bottom'], geo(), None, 260, [('m0', 'm3')])
    pair = ds[-2:]
    assert [d['dev'] for d in ds] == before
    assert pair[0]['box_x'] == pair[1]['box_x']
    assert pair[1]['row'] == pair[0]['row'] + 1
    assert all(d['placement_region'] == 'fullspan' for d in pair)
    assert pair[1]['box_y'] - pair[0]['box_y'] >= 254 + geo().default_space
    for d in pair:
        row = desc[d['row']]
        assert row['parallel_pair'] == ['ra', 'rb']
        assert row['column_lambda'][0] <= d['box_x'] < d['right_lo'] <= row['column_lambda'][1]
    assert sum(map(len, rows)) == len(ds)
    assert min(d['box_y'] for d in ds[:-2]) > pair[1]['box_y']
    matched = [d for d in ds if d['dev']['name'] in ('m0', 'm3')]
    assert matched[0]['row'] == matched[1]['row']


def test_parallel_access_envelope_refuses_an_actually_narrow_region():
    with pytest.raises(a.Refusal, match='parallel resistor pair access envelope'):
        a._place_left_right_rows(parallel_devices(), ['top', 'bottom'],
                                 geo(), None, 180, ())


def test_r90_preserves_native_masks_and_terminal_identity():
    cell = {'cell': 'native_resistor', 'delta': (81, 9149),
            'bbox': (-127, -9195, 127, 9195),
            'sections': {'metal1': [(-20, -9100, 20, 9100)],
                         'poly': [(-25, -9050, 25, 9050)]},
            'labels': [{'name': 'R1', 'x': 0, 'y': 9078, 'level': 2},
                       {'name': 'R2', 'x': 0, 'y': -9078, 'level': 2}]}
    before = deepcopy(cell)
    rotated = a._r90_cell(cell)
    assert cell == before
    assert rotated['cell'] == cell['cell']
    assert rotated['bbox'] == (-9195, -127, 9195, 127)
    assert rotated['delta'] == (9195, 127)
    assert [(l['name'], l['x'], l['y']) for l in rotated['labels']] == [
        ('R1', -9078, 0), ('R2', 9078, 0)]
    restored = rotated
    for _ in range(3):
        restored = a._r90_cell(restored)
    assert restored['sections'] == cell['sections']
    assert restored['labels'] == cell['labels']


def test_loaded_divider_midpoint_keeps_the_identical_series_pair():
    first = {'name': 'ra', 'class': 'resistor', 'model': 'rppd',
             'nets': ['hi', 'mid', 'vss'], 'pars': {'w': .5, 'l': 181}}
    second = {**first, 'name': 'rb', 'nets': ['mid', 'lo', 'vss']}
    load = {'name': 'load', 'class': 'mosfet', 'nets': ['out', 'mid', 'vss', 'vss']}
    cells = {a.config_key(first): {'bbox': (-127, -9195, 127, 9195)}}
    assert a._series_resistor_pair([first, second, load], ['hi', 'lo', 'vss'], cells) == ['ra', 'rb']
    unequal = {**second, 'pars': {'w': .5, 'l': 180}}
    cells[a.config_key(unequal)] = cells[a.config_key(first)]
    assert a._series_resistor_pair([first, unequal, load], ['hi', 'lo', 'vss'], cells) == []


def test_pair_fit_uses_the_final_colored_bank(monkeypatch):
    original = a._m4_trunk_tracks
    calls = []
    def color(rails, geometry, lower=2, upper=4):
        bus, _ = original(rails, geometry, lower=lower, upper=upper)
        calls.append((lower, upper))
        return bus, 0 if len(calls) == 1 else 1500
    monkeypatch.setattr(a, '_m4_trunk_tracks', color)
    with pytest.raises(a.Refusal, match=r'required=189.42um available=185um colored_bank=15um'):
        a._place_left_right_rows(parallel_devices(), ['top', 'bottom'],
                                 geo(), None, 200, ())
    assert calls == [(4, 5), (4, 5)]


def test_colored_bank_growth_rebudgets_regions_without_clipping(monkeypatch):
    ds = fixture_devices(7, 40) + parallel_devices()
    before = deepcopy([d['dev'] for d in ds])
    widths = [d['bbox'][2] - d['bbox'][0] for d in ds]
    original = a._m4_trunk_tracks
    calls = []
    def color(rails, geometry, lower=2, upper=4):
        bus, _ = original(rails, geometry, lower=lower, upper=upper)
        calls.append((lower, upper))
        return bus, 0 if len(calls) == 1 else (1500 if len(calls) == 2 else 1000)
    monkeypatch.setattr(a, '_m4_trunk_tracks', color)
    rows, _, _, desc = a._place_left_right_rows(
        ds, ['top', 'bottom'], geo(), None, 260, [('m0', 'm3')])
    assert max(r['column_lambda'][1] for r in desc) <= 26000
    assert sum(map(len, rows)) == len(ds)
    assert [d['dev'] for d in ds] == before
    assert [d['right_lo'] - d['box_x'] for d in ds] == widths
    for d in ds:
        column = desc[d['row']]['column_lambda']
        assert column[0] <= d['box_x'] < d['right_lo'] <= column[1]
    pair = ds[-2:]
    assert pair[0]['box_x'] == pair[1]['box_x']
    assert pair[1]['row'] == pair[0]['row'] + 1
    matching = [d for d in ds if d['dev']['name'] in ('m0', 'm3')]
    assert matching[0]['row'] == matching[1]['row']
    assert calls and all(planes == (4, 5) for planes in calls)
