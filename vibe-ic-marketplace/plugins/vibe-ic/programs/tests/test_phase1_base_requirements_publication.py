"""Candidate publication preserves owner approval and the existing metric gate."""
import json
import sys

import pytest

import phase1_one_shot_runner as runner
from programs.tests._hostpaths import require_repo
from test_flow109_phase1_metric_completion import write


def owner_case(project):
    source = write(project, 'input/owner_request.md', 'Build an IC from the supplied specification.\n')
    write(project, 'input/docs/spec.md', 'The design has one signal input.\nNo calibration or trim interface is required.\n')
    write(project, 'input/step_0_5ic_answers.json', {
        'answers': {'deliverable': 'DIE'}, 'answer_provenance': {
            'deliverable': {'answered_by': 'owner',
                            'citation': 'Build an IC from the supplied specification.'}}})
    return source




def authority(project, key, metric):
    return json.loads((project / f'requirements/{key}/{metric}.json').read_text())






















def test_publication_only_cli_does_not_dispatch_extraction(tmp_path, monkeypatch, capsys):
    owner_case(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('publication-only continuation dispatched unrelated extraction')
    for name in ['_run_docs_mode', '_run_step_0_5ic', '_run_expert_track', 'step_ingest_render']:
        monkeypatch.setattr(runner, name, forbidden)
    monkeypatch.setattr(sys, 'argv', ['phase1_one_shot_runner.py', str(tmp_path), '--publish-base-requirements'])
    assert runner.main() == 4
    output = capsys.readouterr().out
    assert 'INCOMPLETE: D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' in output
    assert 'IC Expert' in output
    assert authority(tmp_path, 'base_02', 'endpoint_delivery_items')['approval']['status'] == 'PENDING'






















def test_authority_documentation_names_owner_role_and_review_stop():
    root = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic')
    flow = (root / 'flow/FLOW109.md').read_text()
    command = (root / 'commands/vibe-ic-all.md').read_text()
    assert 'AI-owned authority remains' not in flow
    assert '`requirements_owner` is a role' in flow
    assert 'named approver' in flow
    assert 'current source hash' in flow
    assert 'Programs never write approvals' in flow
    assert 'D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED' in command
    assert 'exit 4' in command
    assert 'input/docs/**' in command
