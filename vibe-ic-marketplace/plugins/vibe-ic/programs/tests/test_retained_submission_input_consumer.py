"""Actual retained submission consumer controls on an isolated mounted readset.

No design producer, Phase1 extraction/checkpoint, review, EQY or STA executes.
The real source authority and both existing canonical input checks execute.
"""
import json
import os
import shutil
from pathlib import Path

import pytest
import flow109
import flow109_metric_acceptance as metrics
import phase1_one_shot_runner as runner
import tapeout_declaration_check as declaration


@pytest.fixture
def case():
    control = os.environ.get('SUBMISSION_INPUT_CONTROL_ROOT')
    if not control:
        pytest.skip('requires explicit isolated consumer readset')
    root = Path(control)
    project = Path(os.environ['SUBMISSION_INPUT_CONTROL_PROJECT'])
    assert project.is_mount() and (project / 'CONTROL_ONLY.json').is_file()
    marker = json.loads((project / 'CONTROL_ONLY.json').read_text())
    assert marker == {'scope': 'isolated source consumer control', 'baseline': str(root / 'baseline')}
    for path in project.iterdir():
        if path.is_dir():shutil.rmtree(path)
        else:path.unlink()
    shutil.copytree(root / 'baseline', project, dirs_exist_ok=True)
    return project


def acceptance(project):
    manifest = json.loads((project / 'input/flow109-manifest.json').read_text())
    context = flow109.execution_context(flow109.resolve_plan(
        manifest['features'], manifest.get('step_profiles')), 'D02', 'D02')
    return metrics.accept_d02(project, context)


def test_real_area_publication_is_consumed_without_producer(case):
    # BASE reaches the real stale-input refusal, rather than an absent import.
    if hasattr(runner, '_complete_retained_submission_input'):
        runner._complete_retained_submission_input(case)
    result = acceptance(case)
    assert result['status'] == 'PASS', result
    assert result['qualification'] == 'PASS', result
    assert all(item['status'] == 'PASS' for item in result['obligations'])


@pytest.mark.parametrize('change', ['area_value', 'owner_route'])
def test_changed_area_or_owner_cannot_reuse_prior_acceptance(case, change):
    path = case / 'input/step_0_5ic_answers.json'
    doc = json.loads(path.read_text())
    if change == 'area_value':
        doc['answers']['synthesis_area_budget']['stdcell_area_gate'][0]['value_um2'] += 1
    else:
        doc['answers']['deliverable'] = 'HARDMACRO'
    path.write_text(json.dumps(doc, indent=2) + '\n')
    # The existing independent reader must reject the actual changed input.
    checked = declaration.evaluate(case)
    assert checked['verdict'] == 'FAIL', checked
    if hasattr(runner, '_complete_retained_submission_input'):
        with pytest.raises(metrics.MetricRefusal):
            runner._complete_retained_submission_input(case)
    result = acceptance(case)
    expected = 'FAIL' if change == 'owner_route' else 'NOT_MEASURED'
    assert result['status'] == expected and result['qualification'] != 'PASS', result


def test_boolean_return_is_not_original_producer_completion(case):
    import step_output_collector as versions
    record = versions.latest_pass(case, '0.5ic')
    path = case / record.get('storage_root', 'steps') / record['folder'] / 'outputs.json'
    body = json.loads(path.read_text())
    body['result']['producer_return'] = False
    path.write_text(json.dumps(body, indent=2) + '\n')
    with pytest.raises(metrics.MetricRefusal, match='D0102_SUBMISSION_LINEAGE_UNBOUND'):
        runner._complete_retained_submission_input(case)
