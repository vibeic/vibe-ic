"""The real D1 clause consumes producer evidence without changing its subject."""
import hashlib
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_compliance_check as fc
import phase1_expert_parse_track as track
from test_issue2204_expert_second_pass_is_reachable import _project, _report, _answer_path, _ANSWER


def _command():
    flow = Path(track.__file__).parents[1] / 'flow/phase1_phase2_phase3.yaml'
    commands = []

    def walk(node):
        if isinstance(node, dict):
            value = node.get('program_exit_zero')
            if isinstance(value, str) and value.startswith('phase1_expert_parse_track '):
                commands.append(value)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(yaml.safe_load(flow.read_text()))
    assert len(commands) == 1
    return commands[0]


def _snapshot(project):
    return {str(p.relative_to(project)): (
                p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_mode,
                hashlib.sha256(p.read_bytes()).hexdigest())
            for p in project.rglob('*') if p.is_file()}


def _audit_unchanged(project):
    before = _snapshot(project)
    # The raw clause's True is protocol acceptance, NOT a PASS verdict:
    # #2014 maps rc 4 + INCOMPLETE to the consumer's INCOMPLETE tier. Exercise
    # that real consumer with the command declared by D1, without unrelated
    # D1 checks hiding this clause's status behind missing fixture artifacts.
    result = fc.check_step(project, {
        'id': 'T2206', 'name': 'D1 expert producer evidence',
        'gate': {'program_exit_zero': _command()},
    }, {})
    assert _snapshot(project) == before, 'D1 rewrote its subject'
    return result


def test_pending_answer_is_not_consumed_by_the_real_d1_clause(tmp_path):
    p = _project(tmp_path, 'pending', answer=False, report=False)
    assert track.main([str(p)]) == track.AWAITING_EXIT_CODE
    _answer_path(p).write_text(json.dumps(_ANSWER))
    result = _audit_unchanged(p)
    assert result.status == 'NOT_MEASURED', result
    assert json.loads(_report(p).read_text())['ai_subtrack']['status'] == track.AI_HANDOFF_EMITTED




@pytest.mark.parametrize('change', ['missing', 'malformed', 'answer', 'layer', 'false_complete'])
def test_missing_or_stale_producer_evidence_is_refused_without_repair(tmp_path, change):
    p = _project(tmp_path, change, answer=True, report=False)
    assert track.main([str(p)]) == 0
    if change == 'missing':
        _report(p).unlink()
    elif change == 'malformed':
        _report(p).write_text('[]')
    elif change == 'answer':
        _answer_path(p).write_text(json.dumps({**_ANSWER, 'changed': True}))
    elif change == 'layer':
        next((p / 'phase1/generated_docs').glob('L*.json')).write_text('{"changed": true}')
    else:
        rep = json.loads(_report(p).read_text())
        rep['execution']['complete'] = False
        _report(p).write_text(json.dumps(rep))
    result = _audit_unchanged(p)
    assert result.status == 'FAIL', result
