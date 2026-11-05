import json

import pytest

import flow109
import flow109_metric_acceptance as metrics
from test_flow109_d14_metric_binding import case as base_case
from test_formal_required_reachability import reach_case, software_covers


@pytest.mark.parametrize('owner_metadata', ['current', 'older', 'absent'])
def test_complete_formal_measurements_publish_without_case_qualification(reach_case, monkeypatch, owner_metadata):
    project, context = reach_case
    result_path = project / 'phase2/stage1/formal/results.json'
    result = json.loads(result_path.read_text())
    if owner_metadata == 'older':
        result['program_owner_sha256']['formal_property_run.py'] = 'a' * 64
    elif owner_metadata == 'absent':
        del result['program_owner_sha256']
    result_path.write_text(json.dumps(result))
    software_covers(project)
    def qualification(*args):
        raise AssertionError('per-case qualification is not acceptance')
    monkeypatch.setattr(metrics, '_d14_qualification', qualification)
    accepted = metrics.accept_d14(project, context)
    assert accepted['metric_status'] == 'PASS', accepted
    assert accepted['status'] == 'PASS', accepted
    assert accepted['qualification'] == 'NOT_MEASURED'
    published = flow109._selected_step_result(project, context,
        {'step_id': 'D14', 'context_sha256': context['context_sha256'],
         'component_status': 'PASS', 'default_row_status': 'PASS', 'completed': True})
    assert published['default_row_status'] == 'PASS', published
    assert published['completed'] is True
    assert published['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert published['delivery_accepted'] is False
    assert json.loads((project / 'reports/flow109/default_rows/D14.json').read_text()) == published
