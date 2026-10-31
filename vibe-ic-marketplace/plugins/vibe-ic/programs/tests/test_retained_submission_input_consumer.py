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


def test_actual_control_prose_and_area_refusal_reach_normal_row(case, monkeypatch):
    """Actual extra control files cannot replace the authored area readset.

    A newly authored area input remains a real changed input. Its exact normal
    MetricRefusal must reach the existing NOT_MEASURED row and collector.
    """
    import sys
    import area_budget_basis_gen as area
    import step_output_collector as versions
    answer = json.loads((case / 'input/step_0_5ic_answers.json').read_text())
    expected = {'answer': answer['answers'][area.KEY],
                'provenance': answer['answer_provenance'][area.KEY]}
    initial_equal = area.rederive(case, answer) == expected
    prior = versions.latest_pass(case, '0.5ic')
    original = case / prior.get('storage_root', 'steps') / prior['folder'] / 'outputs.json'
    original_raw = original.read_bytes()
    # Preserve the legacy author-input path: this is not Flow109 collateral.
    (case / 'input/owner-area-requirement.md').write_text(
        '# Owner area intent\nThe implementation may choose the die size.\n')
    manifest = json.loads((case / 'input/flow109-manifest.json').read_text())
    context = flow109.execution_context(flow109.resolve_plan(
        manifest['features'], manifest.get('step_profiles')), 'D02', 'D02')
    target = case / 'control-request.json'
    target.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(target))
    attempt = flow109._new_attempt(case, context)
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(case),
        '--complete-retained-metrics', '--route', 'ic', '--ic-name', 'spm'])
    try:
        observed = ('returned', runner.main())
    except metrics.MetricRefusal as exc:
        observed = ('raised', exc.code)
    assert observed == ('returned', 1), observed  # BASE raises real AREA_AUTHORITY_STALE.
    assert initial_equal is True
    row = json.loads((case / 'reports/flow109/default_rows/D02.json').read_text())
    assert row['default_row_status'] == 'NOT_MEASURED'
    assert row['reason'] == 'D0102_SUBMISSION_AREA_AUTHORITY_STALE'
    assert row['metric_acceptance']['reason'] == row['reason']
    assert row['metric_acceptance']['detail'].startswith(row['reason'] + ':')
    assert row['metric_acceptance']['qualification'] == 'NOT_MEASURED'
    assert row['metric_acceptance']['metric_status'] == 'PASS'
    finished = json.loads((attempt / 'result.json').read_text())
    assert finished['components'][0]['reason'] == row['reason']
    assert finished['default_row_status'] == 'NOT_MEASURED'
    assert original.read_bytes() == original_raw
