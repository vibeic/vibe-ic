"""Synthetic contract fixtures only; these records are NOT actual model actions."""
import hashlib
import json
from pathlib import Path
import delivery_intent as di


def review_files(project, *, response=None):
    issued = di.issue_review(project)
    task = json.loads(Path(issued['task_path']).read_text())
    if response is None:
        floors = task['evidence']['floors']
        outcome = ('conflict' if task['evidence']['conflicts'] else
                   'physical' if floors else 'source')
        response = {'schema': di.SCHEMA, 'task_sha256': task['task_sha256'],
                    'outcome': outcome,
                    'requested_source': [] if floors else task['evidence']['candidates'][0]['supports'],
                    'retained_floor_ids': [row['id'] for row in floors],
                    'candidate_dispositions': [
                        {'candidate': row['id'], 'role': 'physical_obligation' if floors else 'external_reference',
                         'supports': row['supports'], 'rationale': 'Synthetic schema fixture, not a semantic evaluation.'}
                        for row in task['evidence']['candidates']], 'additional_floors': []}
    scratch = Path(project).parent / ('fixture-action-' + task['issuance_id'])
    scratch.mkdir()
    response_path = scratch / 'response.json'
    response_path.write_text(json.dumps(response))
    prompt = 'Explicit synthetic test dispatch for task ' + task['task_sha256']
    (scratch / 'dispatch.txt').write_text(prompt)
    observation = {'schema': 'vibeic.codex-delivery-observation.v1',
                   'parent_thread_id': 'fixture-parent', 'agent_thread_id': 'fixture-child',
                   'agent_path': '/fixture/child', 'model': 'fixture-model',
                   'dispatch_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                   'task_sha256s': [task['task_sha256']]}
    (scratch / 'observation.json').write_text(json.dumps(observation))
    final = json.dumps({'task_responses': [{'task_sha256': task['task_sha256'],
                          'response_sha256': hashlib.sha256(response_path.read_bytes()).hexdigest()}]})
    payloads = [
        ('session_meta', {'id': 'fixture-child', 'parent_thread_id': 'fixture-parent',
                         'agent_path': '/fixture/child',
                         'source': {'subagent': {'thread_spawn': {'parent_thread_id': 'fixture-parent'}}}}),
        ('event_msg', {'type': 'task_started', 'turn_id': 'fixture-turn', 'root_turn_id': 'fixture-root'}),
        ('turn_context', {'turn_id': 'fixture-turn', 'model': 'fixture-model'}),
        ('response_item', {'type': 'message', 'role': 'assistant', 'phase': 'final_answer',
                           'content': [{'type': 'output_text', 'text': final}]}),
        ('event_msg', {'type': 'task_complete', 'turn_id': 'fixture-turn', 'root_turn_id': 'fixture-root',
                       'last_agent_message': final, 'completed_at': 'fixture-completion'})]
    (scratch / 'runtime.jsonl').write_text('\n'.join(json.dumps({'type': kind, 'payload': body})
                                                   for kind, body in payloads))
    return {'observation_path': scratch / 'observation.json',
            'runtime_path': scratch / 'runtime.jsonl',
            'dispatch_prompt_path': scratch / 'dispatch.txt', 'response_path': response_path}


def accept_review(project, *, fresh=False):
    if fresh:
        di.issue_review(project, fresh=True)
    return di.collect_review(project, **review_files(project))
