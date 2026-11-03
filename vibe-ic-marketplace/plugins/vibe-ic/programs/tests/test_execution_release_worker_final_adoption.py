import json

import execution_release_worker as release


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_final_adoption_collects_own_aggregate_and_native_views(tmp_path):
    gds = tmp_path / 'phase3/stage4/gds/actual.gds'
    gds.parent.mkdir(parents=True)
    gds.write_bytes(b'fixture')
    netlist = tmp_path / 'phase3/librelane/final/netlist.v'
    netlist.parent.mkdir(parents=True)
    netlist.write_text('module actual; endmodule')
    write(tmp_path / 'reports/flow109/components/D77.json', {'default_row_status': 'PASS'})
    write(tmp_path / 'reports/flow109/components/D70.json', {'netlist': {'path': str(netlist.relative_to(tmp_path))}})
    record = release.execute(tmp_path, {})
    assert record['default_row_status'] == 'PASS'
    assert record['completed'] is True
    assert record['views']['gds'] == str(gds.relative_to(tmp_path))
    assert json.loads((tmp_path / 'reports/phase3/layout_receipts.json').read_text()) == record


def test_unmeasured_aggregate_cannot_be_adopted(tmp_path):
    write(tmp_path / 'reports/flow109/components/D77.json', {'default_row_status': 'NOT_MEASURED'})
    record = release.execute(tmp_path, {})
    assert record['default_row_status'] == 'NOT_MEASURED'
    assert record['completed'] is False
