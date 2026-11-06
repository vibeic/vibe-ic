"""Default dispatch controls; mocked native transport is not IC evidence."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import phase3_one_shot_runner as runner










def test_current_flow_declares_the_immutable_cts_handoff_as_a_step19_output():
    """Use the actual front-door declaration reader on the complete source flow."""
    import step_required_inputs_check as inputs
    flow = Path(runner.__file__).parents[1] / 'flow/phase1_phase2_phase3.yaml'
    rows, error = inputs.load_flow(flow)
    assert error is None
    assert len(rows) == 70
    by_id = {str(row['id']): row for row in rows}
    handoff = 'reports/phase3/librelane_cts_handoff.json'
    assert handoff in by_id['19']['required_outputs']
    assert {'from': 19, 'path': handoff} in by_id['20']['required_inputs']
    assert inputs.declaration_defects(rows) == []


def test_current_flow_reader_refuses_the_old_undeclared_cts_handoff_edge():
    import copy
    import step_required_inputs_check as inputs
    flow = Path(runner.__file__).parents[1] / 'flow/phase1_phase2_phase3.yaml'
    rows, error = inputs.load_flow(flow)
    assert error is None
    rows = copy.deepcopy(rows)
    row19 = next(row for row in rows if str(row['id']) == '19')
    handoff = 'reports/phase3/librelane_cts_handoff.json'
    row19['required_outputs'] = [path for path in row19['required_outputs']
                                 if path != handoff]
    defects = inputs.declaration_defects(rows)
    assert len(defects) == 1
    assert defects[0]['where'] == 'step 20 required_inputs[1]'
    assert handoff in defects[0]['defect']
    assert "NOT one of step 19's declared required_outputs" in defects[0]['defect']
















def test_backend_consumers_use_the_same_canonical_flow_as_default():
    import _flow_yaml
    from execution_provider_catalog import BACKEND_ROWS
    canonical = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    for sid, backend in BACKEND_ROWS.items():
        assert backend['canonical_row'] == canonical[sid], sid


















































































@pytest.mark.parametrize('role', ['producer', 'audit'])
def test_placement_report_identifies_the_actual_writer_for_the_consumer(
        tmp_path, monkeypatch, role):
    import placement_legality_check as placement
    import flow_declared_producer_run as declared
    import _gate_authorship as authorship

    monkeypatch.setenv(authorship.ROLE_ENV, role)
    output = tmp_path / 'placement.json'
    summary = {'placed_def': 'phase3/stage3/pnr/placed.def',
               'declared_components': 1, 'parsed_components': 1,
               'placed': 1, 'unplaced': 0, 'density_pct': None,
               'density_source': None}
    placement._emit(SimpleNamespace(json=str(output)), tmp_path,
                    'PASS', summary, [], None)
    document = json.loads(output.read_text())
    assert document['program'] == 'placement_legality_check'
    assert authorship.role_of(document) == role
    assert declared._producer_target_has_content(output) is (role == 'producer')


def test_spare_checkpoint_is_an_explicit_cts_input():
    import _flow_yaml
    rows = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    checkpoint = 'phase3/stage3/pnr/post_spare.def'
    assert checkpoint in rows['18']['required_outputs']
    assert {'from': 18, 'path': checkpoint} in rows['19']['required_inputs']
