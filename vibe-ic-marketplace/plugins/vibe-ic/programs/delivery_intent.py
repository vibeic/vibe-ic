"""BLOCKING source-bound delivery ownership under a cooperative operator.

A complete-source semantic review grants applicability only. It grants no owner
approval, D1 qualification or native result. Hashes bind bytes, not model truth.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import uuid
from typing import Literal

HERE = Path(__file__).resolve().parent
SCHEMA = 'vibeic.delivery-ownership.v1'
DISCOVERY = 'complete-original-inputs-v2'
POLICY_FILES = ('delivery_intent.py', 'task_nature_route.py', '_path_layout.py',
                'benchmark_io_adapter.py', 'route_decision.py', 'flow109.py',
                'benchmark_dispatch.py')
TARGET_ORDER = {'rtl': 0, 'gds': 1, 'shippable_gds': 2, 'foundry_handoff': 3}


class DeliveryRefusal(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f'{code}: {detail}')


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _hash(value) -> str:
    return _digest(_json_bytes(value))


def _strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('nonfinite JSON number: ' + value)
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=invalid_constant)


def _read(path: Path) -> bytes:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise DeliveryRefusal('DELIVERY_LINKED_INPUT', str(path))
    return path.read_bytes()


def _publish(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise DeliveryRefusal('DELIVERY_LINKED_AUTHORITY', str(path))
    try:
        with path.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        if _read(path) != raw:
            raise DeliveryRefusal('DELIVERY_IMMUTABLE_RECORD_CHANGED', str(path))


@dataclass(frozen=True)
class SourceFile:
    document_id: str
    relative_path: str
    content: bytes
    content_sha256: str


@dataclass(frozen=True)
class SourceBundle:
    files: tuple[SourceFile, ...]
    source_set_sha256: str
    semantic_payload_sha256: str

    def inputs(self) -> list[dict]:
        return [{'path': item.relative_path, 'sha256': item.content_sha256}
                for item in self.files]

    def payload(self) -> list[dict]:
        return [{'document_id': item.document_id, 'path': item.relative_path,
                 'sha256': item.content_sha256, 'text': item.content.decode('utf-8')}
                for item in self.files]


@dataclass(frozen=True)
class Evidence:
    floors: tuple[dict, ...]
    candidates: tuple[dict, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class DeliveryDecision:
    outcome: Literal['source', 'physical', 'unresolved', 'conflict']
    bundle: SourceBundle
    evidence: Evidence
    binding: dict
    floors: tuple[dict, ...] = ()


@dataclass(frozen=True)
class TargetSelection:
    target: str
    route: str
    family: str | None
    minimum_target: str | None
    binding: dict


def capture_sources(project: Path) -> SourceBundle:
    """Capture both original document intakes and preserve staged-copy semantics."""
    from _path_layout import original_input_sources
    project = Path(project).resolve()

    def supplied_files(relative):
        root = project / relative
        entries = [root, *root.rglob('*')] if root.exists() or root.is_symlink() else []
        if any(path.is_symlink() for path in [*root.parents, *entries]):
            raise DeliveryRefusal('DELIVERY_SOURCE_INVALID', 'linked supplied source')
        return {path for path in entries if path.is_file()}

    try:
        prompt = project / 'input/phase1_prompt.md'
        if prompt.exists() or prompt.is_symlink():
            files = set(original_input_sources(project))
        else:
            files = supplied_files('input/docs') or supplied_files('phase1/input_doc')
        original_hashes = {_digest(_read(path)) for path in files}
        for relative in ('input/docs', 'phase1/input_doc', 'input/rtl', 'input/vendor_rtl'):
            files.update(path for path in supplied_files(relative)
                         if path in files or _digest(_read(path)) not in original_hashes)
            original_hashes.update(_digest(_read(path)) for path in files)
        captured = tuple(SourceFile(f'document-{index}', path.relative_to(project).as_posix(),
                                    raw, _digest(raw))
                         for index, path in enumerate(sorted(files))
                         for raw in [_read(path)])
        if not captured or not any(item.content.strip() for item in captured):
            raise ValueError('no nonempty original design input')
        payload = [{'document_id': item.document_id, 'path': item.relative_path,
                    'sha256': item.content_sha256, 'text': item.content.decode('utf-8')}
                   for item in captured]
        return SourceBundle(captured, _hash({'discovery': DISCOVERY,
            'inputs': [{'path': item.relative_path, 'sha256': item.content_sha256}
                       for item in captured]}), _hash(payload))
    except (OSError, ValueError) as exc:
        if isinstance(exc, DeliveryRefusal):
            raise
        raise DeliveryRefusal('DELIVERY_SOURCE_INVALID', str(exc)) from exc


def policy_sha256() -> str:
    return _hash({name: _digest(_read(HERE / name)) for name in POLICY_FILES})


def extract_evidence(bundle: SourceBundle) -> Evidence:
    import task_nature_route as tnr
    floors, candidates, conflicts = [], [], []
    for item in bundle.files:
        text = item.content.decode('utf-8')
        demand = tnr.prompt_delivery_requirements(text)
        span = {'document': item.document_id, 'start_byte': 0,
                'end_byte': len(item.content), 'excerpt': text}
        if demand['status'] == 'CONFLICT':
            conflicts.append(item.document_id)
        if demand['route_family'] is not None or demand['minimum_target'] is not None:
            floors.append({'id': 'floor-' + item.document_id,
                           'family': demand['route_family'] or 'DIE',
                           'minimum_target': demand['minimum_target'],
                           'supports': [span], 'reason': 'recognized physical delivery requirement'})
        # A whole-document obligation remains open even when bounded scans
        # found no object. Only complete-source review closes that uncertainty.
        candidates.append({'id': 'ownership-' + item.document_id,
                           'supports': [span], 'reason': 'complete-source ownership unresolved'})
    if len({row['family'] for row in floors}) > 1:
        conflicts.append('incompatible-source-families')
    return Evidence(tuple(floors), tuple(candidates), tuple(conflicts))


def _snapshot(bundle: SourceBundle, evidence: Evidence) -> dict:
    return {'source_set_sha256': bundle.source_set_sha256,
            'semantic_payload_sha256': bundle.semantic_payload_sha256,
            'policy_sha256': policy_sha256(), 'evidence_sha256': _hash(asdict(evidence))}


def _authority_dir(project: Path) -> Path:
    root = Path(os.environ.get('VIBE_IC_DELIVERY_AUTHORITY_ROOT',
                str(Path.home() / '.local/state/vibe-ic/delivery-ownership'))).absolute()
    project = Path(project).resolve()
    if root.resolve().is_relative_to(project):
        raise DeliveryRefusal('DELIVERY_AUTHORITY_INVALID', 'authority must be outside the project')
    return root / _digest(str(project).encode('utf-8'))


def _state(project: Path) -> tuple[SourceBundle, Evidence, dict]:
    bundle = capture_sources(project)
    evidence = extract_evidence(bundle)
    return bundle, evidence, _snapshot(bundle, evidence)


def _current_task(project: Path, snapshot: dict) -> tuple[Path, dict] | None:
    pointer = _authority_dir(project) / 'current.json'
    if not pointer.exists():
        return None
    current = _strict_json(_read(pointer))
    path = _authority_dir(project) / 'issued' / current['issuance_id'] / 'task.json'
    task = _strict_json(_read(path))
    if (task.get('schema') != SCHEMA or task.get('project') != str(Path(project).resolve())
            or task.get('task_sha256') != _hash({k: v for k, v in task.items() if k != 'task_sha256'})
            or current != {'issuance_id': task['issuance_id'], 'task_sha256': task['task_sha256']}):
        raise DeliveryRefusal('DELIVERY_REVIEW_ISSUANCE_INVALID', str(path))
    public = Path(project) / 'reports/delivery-ownership/tasks' / (task['task_sha256'] + '.json')
    if not public.is_file() or _read(public) != _json_bytes(task):
        raise DeliveryRefusal('DELIVERY_REVIEW_TASK_CHANGED', 'issued public task differs from controller record')
    if task.get('snapshot') != snapshot:
        raise DeliveryRefusal('DELIVERY_REVIEW_STALE', 'source membership, bytes or policy changed; issue a fresh review')
    return path, task


def issue_review(project: Path, *, fresh: bool = False) -> dict:
    project = Path(project).resolve()
    bundle, evidence, snapshot = _state(project)
    try:
        current = _current_task(project, snapshot)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if not isinstance(exc, DeliveryRefusal):
            raise DeliveryRefusal('DELIVERY_REVIEW_ISSUANCE_INVALID', str(exc)) from exc
        if not fresh or exc.code not in ('DELIVERY_REVIEW_STALE', 'DELIVERY_REVIEW_TASK_CHANGED'):
            raise
        current = None
    if current is not None and not fresh:
        path, task = current
    else:
        issuance = uuid.uuid4().hex
        path = _authority_dir(project) / 'issued' / issuance / 'task.json'
        task = {'schema': SCHEMA, 'issuance_id': issuance, 'project': str(project),
                'snapshot': snapshot, 'sources': bundle.payload(), 'evidence': asdict(evidence),
                'instructions': (
                    'Read every complete source. Identify all requested delivered artifacts, physical '
                    'obligations and unresolved references. Source means requested RTL/source artifacts '
                    'only, with no physical obligation or uncertainty anywhere in this complete source set. '
                    'A behavioral reference to an external chip is not ownership of that chip. Retain '
                    'every deterministic floor ID. Explain each ownership candidate over its full source. '
                    'Add physical floors missed by extraction. Do not infer source-only intent from no '
                    'scanner match. Ambiguity stays unresolved. This task grants applicability only, '
                    'never nature, owner approval, D1, flow steps or native PASS. Write your response '
                    'as strict JSON at the path given by the dispatcher. End the fresh action with '
                    'one strict JSON object {"task_responses":[{"task_sha256":"exact issued SHA",'
                    '"response_sha256":"SHA-256 of exact written response bytes"}]}. Include every '
                    'explicitly issued task handled by this action, with distinct response bytes. '),
                'response_contract': {
                    'schema': SCHEMA, 'task_sha256': '<exact issued task digest>',
                    'outcome': 'source | physical | unresolved | conflict',
                    'requested_source': [{'document': '<id>', 'start_byte': 0, 'end_byte': 1,
                                          'excerpt': '<exact UTF-8 source span>'}],
                    'retained_floor_ids': ['<every deterministic floor ID>'],
                    'candidate_dispositions': [{'candidate': '<every candidate ID exactly once>',
                        'role': 'external_reference | physical_obligation | unresolved',
                        'supports': ['<span object as above>'], 'rationale': '<nonempty explanation>'}],
                    'additional_floors': [{'id': '<unique new ID>', 'family': 'DIE | HARDMACRO',
                        'minimum_target': 'rtl | gds | shippable_gds | foundry_handoff | ip_hardmacro | null',
                        'supports': ['<span object as above>'], 'reason': '<nonempty explanation>'}]}}
        task['task_sha256'] = _hash(task)
        _publish(path, _json_bytes(task))
        # The controller owns this pointer. Issuance records remain immutable.
        pointer = _authority_dir(project) / 'current.json'
        staged = pointer.with_name('current.' + issuance)
        _publish(staged, _json_bytes({'issuance_id': issuance, 'task_sha256': task['task_sha256']}))
        os.replace(staged, pointer)
    public = project / 'reports/delivery-ownership/tasks' / (task['task_sha256'] + '.json')
    _publish(public, _json_bytes(task))
    if _state(project)[2] != snapshot:
        raise DeliveryRefusal('DELIVERY_SOURCE_RACE', 'inputs changed while issuing review')
    return {'task_path': str(public), 'task_sha256': task['task_sha256'],
            'issuance_id': task['issuance_id']}


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', label + ' fields differ')


def _spans(value, bundle, *, nonempty=True):
    if not isinstance(value, list) or (nonempty and not value):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'supporting spans required')
    sources = {item.document_id: item.content for item in bundle.files}
    for span in value:
        _keys(span, ('document', 'start_byte', 'end_byte', 'excerpt'), 'span')
        start, end = span['start_byte'], span['end_byte']
        raw = sources.get(span['document'])
        if (raw is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(raw) or not isinstance(span['excerpt'], str)
                or raw[start:end] != span['excerpt'].encode('utf-8')):
            raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'span does not match exact original bytes')


def _validate_response(response: dict, task: dict, bundle: SourceBundle, evidence: Evidence) -> None:
    _keys(response, ('schema', 'task_sha256', 'outcome', 'requested_source', 'retained_floor_ids',
                     'candidate_dispositions', 'additional_floors'), 'response')
    if response['schema'] != SCHEMA or response['task_sha256'] != task['task_sha256']:
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'response is not bound to issued task')
    if response['outcome'] not in ('source', 'physical', 'unresolved', 'conflict'):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'unknown outcome')
    _spans(response['requested_source'], bundle, nonempty=response['outcome'] == 'source')
    retained = response['retained_floor_ids']
    if not isinstance(retained, list) or sorted(retained) != sorted(row['id'] for row in evidence.floors):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'deterministic floor removed or duplicated')
    dispositions = response['candidate_dispositions']
    if not isinstance(dispositions, list):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'candidate dispositions required')
    for row in dispositions:
        _keys(row, ('candidate', 'role', 'supports', 'rationale'), 'candidate disposition')
        if row['role'] not in ('external_reference', 'physical_obligation', 'unresolved'):
            raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'candidate role invalid')
        if not isinstance(row['rationale'], str) or not row['rationale'].strip():
            raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'candidate rationale required')
        _spans(row['supports'], bundle)
    if sorted(row['candidate'] for row in dispositions) != sorted(row['id'] for row in evidence.candidates):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'candidate coverage incomplete or duplicated')
    additional = response['additional_floors']
    if not isinstance(additional, list):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'additional floors must be an array')
    ids = {row['id'] for row in evidence.floors}
    for row in additional:
        _keys(row, ('id', 'family', 'minimum_target', 'supports', 'reason'), 'additional floor')
        if (not isinstance(row['id'], str) or not row['id'] or row['id'] in ids
                or row['family'] not in ('DIE', 'HARDMACRO')
                or row['minimum_target'] not in (None, *TARGET_ORDER, 'ip_hardmacro')
                or (row['family'] == 'DIE' and row['minimum_target'] == 'ip_hardmacro')
                or (row['family'] == 'HARDMACRO' and row['minimum_target'] not in (None, 'ip_hardmacro'))
                or not isinstance(row['reason'], str) or not row['reason'].strip()):
            raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'additional physical floor invalid')
        ids.add(row['id'])
        _spans(row['supports'], bundle)
    floors = [*evidence.floors, *additional]
    conflict = bool(evidence.conflicts) or len({row['family'] for row in floors}) > 1
    roles = {row['role'] for row in dispositions}
    if (response['outcome'] == 'source' and (floors or conflict or roles - {'external_reference'})
            or response['outcome'] == 'physical' and (not floors or conflict or 'unresolved' in roles)
            or conflict and response['outcome'] != 'conflict'
            or 'physical_obligation' in roles and not floors):
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', 'outcome contradicts retained obligations')


def resolve_project_delivery(project: Path) -> DeliveryDecision:
    project = Path(project).resolve()
    try:
        bundle, evidence, snapshot = _state(project)
        current = _current_task(project, snapshot)
        response, authority = None, {'kind': 'deterministic'}
        if current is not None:
            path, task = current
            accepted = path.parent / 'accepted.json'
            if accepted.exists():
                record = _strict_json(_read(accepted))
                response = _strict_json(_read(path.parent / 'response.json'))
                action = _read(path.parent / 'action.jsonl')
                if (record.get('task_sha256') != task['task_sha256']
                        or record.get('response_sha256') != _digest(_read(path.parent / 'response.json'))
                        or record.get('observed_action_sha256') != _digest(action)
                        or record.get('observation_sha256') != _digest(_read(path.parent / 'observation.json'))
                        or record.get('dispatch_prompt_sha256') != _digest(_read(path.parent / 'dispatch.txt'))
                        or any(record.get(key) != value for key, value in snapshot.items())
                        or record.get('schema') != SCHEMA
                        or record.get('acceptance_sha256') != _hash({k: v for k, v in record.items()
                                                                    if k != 'acceptance_sha256'})):
                    raise DeliveryRefusal('DELIVERY_REVIEW_ACCEPTANCE_CHANGED', str(accepted))
                _validate_response(response, task, bundle, evidence)
                authority = {'kind': 'reviewed', **record}
        floors = tuple([*evidence.floors, *(response['additional_floors'] if response else [])])
        if evidence.conflicts or len({row['family'] for row in floors}) > 1:
            outcome = 'conflict'
        elif response is not None:
            outcome = response['outcome']
        else:
            outcome = 'physical' if floors else 'unresolved'
        body = {'outcome': outcome, 'floors': floors, 'authority': authority, **snapshot}
        binding = {**snapshot, 'decision_sha256': _hash(body), 'authority': authority,
                   'outcome': outcome}
        if _state(project)[2] != snapshot:
            raise DeliveryRefusal('DELIVERY_SOURCE_RACE', 'inputs changed during resolution')
        return DeliveryDecision(outcome, bundle, evidence, binding, floors)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, DeliveryRefusal):
            raise
        raise DeliveryRefusal('DELIVERY_REVIEW_INVALID', str(exc)) from exc


def require_source_delivery(decision: DeliveryDecision) -> DeliveryDecision:
    if decision.outcome != 'source':
        raise DeliveryRefusal('DELIVERY_OWNERSHIP_' + decision.outcome.upper(),
                              'complete current sources do not authorize source-only delivery')
    return decision


def require_compatible_target(decision: DeliveryDecision, requested_target: str | None) -> TargetSelection:
    if decision.outcome in ('unresolved', 'conflict'):
        require_source_delivery(decision)
    if requested_target is not None and requested_target not in (*TARGET_ORDER, 'ip_hardmacro'):
        raise DeliveryRefusal('DELIVERY_TARGET_INVALID', str(requested_target))
    family = next((row['family'] for row in decision.floors), None)
    if family == 'HARDMACRO':
        minimum = 'ip_hardmacro'
        target = requested_target or minimum
        valid = target == minimum
    else:
        minimum = max((row['minimum_target'] for row in decision.floors
                       if row['minimum_target'] is not None), key=TARGET_ORDER.get, default=None)
        target = requested_target or minimum or 'rtl'
        valid = target in TARGET_ORDER and TARGET_ORDER[target] >= TARGET_ORDER[minimum or 'rtl']
        if decision.outcome == 'source':
            valid = target == 'rtl'
    if not valid:
        raise DeliveryRefusal('DELIVERY_TARGET_CONFLICT', 'target contradicts current source ownership')
    return TargetSelection(target, 'ic' if family == 'DIE' else 'ip', family, minimum, decision.binding)


def validate_current_delivery_binding(project: Path, expected: dict) -> None:
    if resolve_project_delivery(project).binding != expected:
        raise DeliveryRefusal('DELIVERY_BINDING_STALE', 'source, policy, decision or observed review changed')


def collect_review(project: Path, *, observation_path: Path, runtime_path: Path,
                   dispatch_prompt_path: Path, response_path: Path) -> dict:
    """Import an operator-observed fresh Codex action, never a worker assertion.

    The operator honestly exports its dispatch and completed child records.
    Codex encrypts the child handoff body; the observed dispatch is the trust
    root for that body. Runtime records corroborate identity and completion.
    """
    project = Path(project).resolve()
    try:
        bundle, evidence, snapshot = _state(project)
        current = _current_task(project, snapshot)
        if current is None:
            raise DeliveryRefusal('DELIVERY_REVIEW_UNISSUED', 'issue the exact current task first')
        task_path, task = current
        observation_raw, runtime_raw = _read(observation_path), _read(runtime_path)
        observation = _strict_json(observation_raw)
        _keys(observation, ('schema', 'parent_thread_id', 'agent_thread_id', 'agent_path',
                            'model', 'dispatch_prompt_sha256', 'task_sha256s'), 'observation')
        if observation['schema'] != 'vibeic.codex-delivery-observation.v1':
            raise DeliveryRefusal('DELIVERY_REVIEW_ACTION_UNAVAILABLE', 'unsupported observation format')
        for key in ('parent_thread_id', 'agent_thread_id', 'agent_path', 'model'):
            if not isinstance(observation[key], str) or not observation[key].strip():
                raise ValueError('empty observed ' + key)
        prompt = _read(dispatch_prompt_path)
        tasks = observation['task_sha256s']
        if (not isinstance(tasks, list) or len(tasks) != len(set(tasks))
                or task['task_sha256'] not in tasks
                or _digest(prompt) != observation['dispatch_prompt_sha256']
                or any(not isinstance(digest, str) or len(digest) != 64
                       or digest not in prompt.decode('utf-8') for digest in tasks)):
            raise ValueError('observed dispatch does not name the exact issued tasks')
        events = [_strict_json(line) for line in runtime_raw.splitlines() if line.strip()]
        meta = [row['payload'] for row in events if row.get('type') == 'session_meta']
        contexts = [row['payload'] for row in events if row.get('type') == 'turn_context']
        started = [row['payload'] for row in events if row.get('type') == 'event_msg'
                   and row.get('payload', {}).get('type') == 'task_started']
        completed = [row['payload'] for row in events if row.get('type') == 'event_msg'
                     and row.get('payload', {}).get('type') == 'task_complete']
        finals = [row['payload'] for row in events if row.get('type') == 'response_item'
                  and row.get('payload', {}).get('type') == 'message'
                  and row['payload'].get('role') == 'assistant'
                  and row['payload'].get('phase') == 'final_answer']
        if not all(len(rows) == 1 for rows in (meta, started, completed, finals)) or not contexts:
            raise ValueError('a single completed fresh Codex action is required')
        meta, start, complete, final = meta[0], started[0], completed[0], finals[0]
        if (meta.get('id') != observation['agent_thread_id']
                or meta.get('parent_thread_id') != observation['parent_thread_id']
                or meta.get('agent_path') != observation['agent_path']
                or meta.get('source', {}).get('subagent', {}).get('thread_spawn', {}).get(
                    'parent_thread_id') != observation['parent_thread_id']):
            raise ValueError('foreign runtime action identity')
        turn = start.get('turn_id')
        if (not isinstance(turn, str) or not turn or complete.get('turn_id') != turn
                or complete.get('root_turn_id') != start.get('root_turn_id')
                or not complete.get('completed_at')
                or any(row.get('turn_id') != turn or row.get('model') != observation['model']
                       for row in contexts)):
            raise ValueError('runtime completion or model does not match dispatch')
        if (not isinstance(final.get('content'), list)
                or any(row.get('type') != 'output_text' for row in final['content'])):
            raise ValueError('unsupported final response content')
        final_text = ''.join(row['text'] for row in final['content'])
        if final_text != complete.get('last_agent_message'):
            raise ValueError('final response differs from completed action')
        result = _strict_json(final_text.encode('utf-8'))
        _keys(result, ('task_responses',), 'completion')
        pairs = result['task_responses']
        if not isinstance(pairs, list) or not pairs:
            raise ValueError('completion must bind each explicitly issued task response')
        for pair in pairs:
            _keys(pair, ('task_sha256', 'response_sha256'), 'completed task response')
        if (len({pair['task_sha256'] for pair in pairs}) != len(pairs)
                or {pair['task_sha256'] for pair in pairs} != set(tasks)):
            raise ValueError('completion task membership differs from observed dispatch')
        response_raw = _read(response_path)
        matching = next(pair for pair in pairs if pair['task_sha256'] == task['task_sha256'])
        if matching['response_sha256'] != _digest(response_raw):
            raise ValueError('response bytes differ from the actual completed action')
        response = _strict_json(response_raw)
        _validate_response(response, task, bundle, evidence)
        if _state(project)[2] != snapshot or _current_task(project, snapshot) != current:
            raise DeliveryRefusal('DELIVERY_SOURCE_RACE', 'source or issuance changed during collection')
        record = {'schema': SCHEMA, 'task_sha256': task['task_sha256'],
                  'issuance_id': task['issuance_id'], 'response_sha256': _digest(response_raw),
                  'observed_action_sha256': _digest(runtime_raw),
                  'observation_sha256': _digest(observation_raw),
                  'dispatch_prompt_sha256': _digest(prompt),
                  'agent_thread_id': observation['agent_thread_id'],
                  'parent_thread_id': observation['parent_thread_id'],
                  'agent_path': observation['agent_path'], 'declared_model': observation['model'],
                  'completion_id': turn, **snapshot}
        record['acceptance_sha256'] = _hash(record)
        for name, raw in (('response.json', response_raw), ('action.jsonl', runtime_raw),
                          ('observation.json', observation_raw), ('dispatch.txt', prompt),
                          ('accepted.json', _json_bytes(record))):
            _publish(task_path.parent / name, raw)
        return resolve_project_delivery(project).binding
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        if isinstance(exc, DeliveryRefusal):
            raise
        raise DeliveryRefusal('DELIVERY_REVIEW_ACTION_INVALID', str(exc)) from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('issue', 'resolve', 'collect'))
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--observation', type=Path)
    parser.add_argument('--runtime-export', type=Path)
    parser.add_argument('--dispatch-prompt', type=Path)
    parser.add_argument('--response', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'issue':
            value = issue_review(args.project, fresh=args.fresh)
        elif args.command == 'collect':
            if not all((args.observation, args.runtime_export, args.dispatch_prompt, args.response)):
                parser.error('collect requires observation, runtime-export, dispatch-prompt and response')
            value = collect_review(args.project, observation_path=args.observation,
                runtime_path=args.runtime_export, dispatch_prompt_path=args.dispatch_prompt,
                response_path=args.response)
        else:
            decision = resolve_project_delivery(args.project)
            value = {'outcome': decision.outcome, 'binding': decision.binding,
                     'floors': decision.floors}
        print(json.dumps(value, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, DeliveryRefusal) else 'DELIVERY_REVIEW_INVALID: ' + str(exc)
        print(json.dumps({'status': 'REFUSED', 'reason': reason}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
