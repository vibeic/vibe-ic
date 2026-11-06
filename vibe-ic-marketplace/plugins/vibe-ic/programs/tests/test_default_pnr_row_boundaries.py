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


def test_current_flow_reader_refuses_the_old_undeclared_cts_handoff_edge():
    import step_required_inputs_check as inputs
    flow = Path(runner.__file__).parents[1] / 'flow/phase1_phase2_phase3.yaml'
    rows, error = inputs.load_flow(flow)
    assert error is None





































































































def test_spare_checkpoint_is_an_explicit_cts_input():
    import _flow_yaml
    rows = {str(row['id']): row for row in _flow_yaml.load()['steps']}
    checkpoint = 'phase3/stage3/pnr/post_spare.def'
    assert checkpoint in rows['18']['required_outputs']
    assert {'from': 18, 'path': checkpoint} in rows['19']['required_inputs']
