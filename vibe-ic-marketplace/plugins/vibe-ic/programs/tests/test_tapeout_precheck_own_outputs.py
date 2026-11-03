import json

import pytest
import tapeout_precheck as precheck
import tapeout_declaration_gen as declaration


@pytest.mark.parametrize('declared_size,status', [(100, 'PASS'), (200, 'FAIL')])
def test_native_geometry_is_checked_against_the_unchanged_contract(tmp_path, monkeypatch, declared_size, status):
    doc = precheck._decl.blank_declaration()
    doc['answers'].update(deliverable='DIE', top_cell='actual_top',
                          die_origin_um=[0, 0], die_area_um=[0, 0, declared_size, declared_size],
                          database_unit_um=.001)
    doc[precheck._decl.PROVENANCE_KEY] = {key: {
        'answered_by': precheck._decl.ANSWERED_BY_OWNER_VALUE,
        'citation': 'Neutral original input contract.'} for key in doc['answers']}
    doc['operator_template'] = {'absent_reason': 'Independent die delivery selected by original input.'}
    native = {'verdict': 'PASS', 'declared_contract': doc, 'measurement': {
        'tool': 'KLayout', 'top_cell': 'actual_top', 'database_unit_um': .001,
        'bbox_um': [0, 0, 100, 100], 'width_um': 100, 'height_um': 100}}
    monkeypatch.setattr(declaration, 'measure_final', lambda project: native)
    for step in ('D65', 'D75'):
        path = tmp_path / f'reports/flow109/components/{step}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'component_status': 'PASS'}))
    result = precheck.execute(tmp_path, {})
    assert result['default_row_status'] == status, result
    assert result['completed'] == (status == 'PASS')
    assert doc['answers']['die_area_um'] == [0, 0, declared_size, declared_size]
