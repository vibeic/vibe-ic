"""Direct controls for spending the M4 interval bank savings on region rows."""
from copy import deepcopy
import _plugin_tree
import analog_a5_layout_emit as a
from test_analog_a5_left_right import assert_regional_rails_clear, fixture_devices
from test_analog_a5_shared_escape import geo


def test_freed_bank_width_is_repacked_into_complete_matching_rows():
    ds = fixture_devices(7, 40)
    before = deepcopy([d['dev'] for d in ds])
    pairs = [('m0', 'm3'), ('m5', 'm8')]
    rows, rails, bus, desc = a._place_left_right_rows(
        ds, ['top', 'bottom'], geo(), None, 260, pairs)
    columns = {r['region']: r['column_lambda'] for r in desc}
    margin = min(b[0] for b in columns.values())
    channel = columns['ota'][0] - columns['cmim'][1]
    assert columns['ota'][1] == 26000
    assert sum(b[1] - b[0] for b in columns.values()) == 26000 - margin - channel
    assert [d['dev'] for d in ds] == before
    assert sum(map(len, rows)) == len(ds)
    assert len(rows) == len(rails) == len(desc)
    for first, second in pairs:
        pair = [d for d in ds if d['dev']['name'] in (first, second)]
        assert pair[0]['row'] == pair[1]['row']
    for row in rows:
        names = {d['dev']['name'] for d in row}
        for d in row:
            region = d['placement_region']
            assert columns[region][0] <= d['box_x'] < d['right_lo'] <= columns[region][1]
            for terminal in d['groups']:
                if 'shared_escape_owner' in terminal:
                    assert terminal['shared_escape_owner'] in names
    assert_regional_rails_clear(desc, geo())


def test_rebudget_favours_the_taller_region_and_reduces_its_rows():
    ds = fixture_devices(7, 40)
    _, _, _, desc = a._place_left_right_rows(
        ds, ['top', 'bottom'], geo(), None, 260, ())
    columns = {r['region']: r['column_lambda'] for r in desc}
    assert columns['ota'][1] - columns['ota'][0] > columns['cmim'][1] - columns['cmim'][0]
    assert sum(r['region'] == 'ota' for r in desc) < 5


def test_insufficient_width_preserves_all_geometry_and_reports_overflow():
    ds = fixture_devices(2, 4)
    before = deepcopy([d['dev'] for d in ds])
    rows, rails, _, desc = a._place_left_right_rows(
        ds, ['top', 'bottom'], geo(), None, 40, [('m0', 'm3')])
    assert [d['dev'] for d in ds] == before
    assert sum(map(len, rows)) == 6
    assert len(rows) == len(rails) == len(desc)
    assert max(r['column_lambda'][1] for r in desc) > 4000
    pair = [d for d in ds if d['dev']['name'] in ('m0', 'm3')]
    assert pair[0]['row'] == pair[1]['row']
