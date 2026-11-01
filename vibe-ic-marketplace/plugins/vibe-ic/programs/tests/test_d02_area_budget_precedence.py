"""Area producer and D02 lineage boundary controls, not native acceptance.

The lineage envelope is synthetic; its before/after bytes come from the real
area producer. No Phase-1 or design acceptance is claimed by these fixtures.
"""
import hashlib
import json

import pytest
import yaml

import _tapeout_declaration as declaration
import area_budget_basis_gen as area
import flow109_metric_acceptance as metrics
from programs.tests._hostpaths import require_repo


def put(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else (json.dumps(value) + '\n').encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def project_with_fixed_die(project):
    put(project, 'input/docs/L9_constraints.md',
        b'# Implementation constraints\nDIE_AREA = [0, 0, 80, 120] um\nFP_SIZING = absolute\n')
    doc = {'answers': {'deliverable': 'DIE', 'top_cell': 'neutral_core'},
           'answer_provenance': {'deliverable': {
               'answered_by': 'owner', 'citation': 'The owner requests a physical die.'}},
           area.KEY: declaration.NOT_DETERMINED}
    put(project, 'input/step_0_5ic_answers.json', doc)
    return doc


def lineage_publication(project, change=None):
    doc = project_with_fixed_die(project)
    answer = 'input/step_0_5ic_answers.json'
    before = (project / answer).read_bytes()
    assert area.main([str(project)]) == 0
    current = json.loads((project / answer).read_text())
    assert current[area.KEY] == current['answers'][area.KEY]
    if change == 'owner_top':
        current['answers']['top_cell'] = 'different_core'
    elif change == 'owner_route':
        current['answers']['deliverable'] = 'HARDMACRO'
    elif change == 'top_budget':
        current[area.KEY]['max_die_dimensions_um'][0] += 1
    elif change == 'nested_budget':
        current['answers'][area.KEY]['max_die_dimensions_um'][0] += 1
    put(project, answer, current)
    # Exercise the actual shipped canonical row as well as the native producer.
    flow = yaml.safe_load(require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic',
                                      'flow', 'phase1_phase2_phase3.yaml').read_text())
    row = next(r for r in flow['steps'] if str(r['id']) == '0.5ic')
    folder = 'steps/lineage-control'
    old_sha = put(project, folder + '/before.json', before)
    new_sha = put(project, folder + '/after.json', (project / answer).read_bytes())
    put(project, folder + '/outputs.json', {
        'id': str(row['id']), 'status': 'PASS', 'canonical_pass': True,
        'capture_errors': [], 'inputs': {answer: old_sha},
        'input_files': [{'rel': answer, 'sha256': old_sha, 'snapshot': 'before.json'}],
        'written_files': [{'rel': answer, 'sha256': new_sha, 'snapshot': 'after.json'}],
        'outputs': [{'rel': answer, 'sha256': new_sha}],
        'result': {'runner': 'phase1_one_shot_runner', 'site': '_run_step_0_5ic',
                   'producer_return': 0, 'canonical_consumer': {'status': 'PASS'}},
    })
    return {'storage_root': 'steps', 'folder': 'lineage-control'}


def test_producer_written_top_level_budget_reaches_d02_lineage(tmp_path):
    record = lineage_publication(tmp_path)
    reads = {}
    result = metrics._d0102_submission_lineage(tmp_path, record, reads)
    assert result['path'] == 'steps/lineage-control/outputs.json'
    assert result['sha256'] == reads[result['path']]


@pytest.mark.parametrize('change', ['owner_top', 'owner_route'])
def test_real_owner_input_change_still_refuses_d02_lineage(tmp_path, change):
    record = lineage_publication(tmp_path, change)
    with pytest.raises(metrics.MetricRefusal, match='D0102_SUBMISSION_OWNER_INPUT_CHANGED'):
        metrics._d0102_submission_lineage(tmp_path, record, {})


@pytest.mark.parametrize('change', ['top_budget', 'nested_budget'])
def test_normalized_budget_still_requires_exact_native_derivation(tmp_path, change):
    record = lineage_publication(tmp_path, change)
    with pytest.raises(metrics.MetricRefusal, match='D0102_SUBMISSION_AREA_AUTHORITY_STALE'):
        metrics._d0102_submission_lineage(tmp_path, record, {})


@pytest.mark.parametrize('location', ['top', 'nested'])
def test_explicit_not_applicable_survives_fixed_die_producer(tmp_path, location):
    doc = project_with_fixed_die(tmp_path)
    budget = {'status': 'NOT_APPLICABLE', 'rationale': 'No synthesized logic is requested.'}
    if location == 'top':
        doc[area.KEY] = budget
    else:
        doc.pop(area.KEY)
        doc['answers'][area.KEY] = budget
    doc['answer_provenance'][area.KEY] = {
        'answered_by': 'owner', 'citation': 'Explicit implementation-area disposition.'}
    put(tmp_path, 'input/step_0_5ic_answers.json', doc)
    before = (tmp_path / 'input/step_0_5ic_answers.json').read_bytes()
    assert area.main([str(tmp_path)]) == 0
    assert (tmp_path / 'input/step_0_5ic_answers.json').read_bytes() == before
    assert declaration.area_budget_resolution({area.KEY: budget})['status'] == 'NOT_APPLICABLE'


def test_absent_budget_still_derives_fixed_die_limit(tmp_path):
    doc = project_with_fixed_die(tmp_path)
    doc.pop(area.KEY)
    put(tmp_path, 'input/step_0_5ic_answers.json', doc)
    assert area.main([str(tmp_path)]) == 0
    after = json.loads((tmp_path / 'input/step_0_5ic_answers.json').read_text())
    assert after['answers'][area.KEY]['status'] == 'LIMIT'
    assert after['answers'][area.KEY]['max_die_dimensions_um'] == [80.0, 120.0]
    assert area.rederive(tmp_path, after)['answer'] == after['answers'][area.KEY]
