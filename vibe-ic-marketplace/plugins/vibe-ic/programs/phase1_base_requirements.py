"""Publish source-backed base01/base02 candidates, never requirements approval.

Physical candidates contain only the owner's explicit delivery fact. A bounded
RTL request emits a pending independent review task. Existing gates alone read
and validate the reviewer-authored requirement population and feature review.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import _atomic_artefact as atomic
import _path_layout as layout
import _submission_template as submission
import _tapeout_declaration as declaration
import flow109_metric_acceptance as metrics


SOURCE = 'input/base_requirements_candidates.json'
SOURCE_SCHEMA = 'vibeic.phase1.base-requirements-source.v1'
REPORT = 'phase1/base_requirements_candidates.json'
REVIEW = 'reports/phase1/requirements_review_handoff.json'
PACK = 'reports/audit/phase1/expert_parse_track_pack'
REVIEW_OUTPUTS = (f'{PACK}/l_doc_expectations.json',
                  'reports/audit/ai_judgements/D1.json', SOURCE,
                  'requirements/base_01/requirements_trace.json',
                  'requirements/base_02/endpoint_delivery_items.json')
ROWS = (('base_01', 'requirements_trace'), ('base_02', 'endpoint_delivery_items'))


def _owner_fact(project: Path, documents: dict) -> tuple[dict, str]:
    doc, endpoint = declaration.read_owner_delivery(project, submission.DESIGN_ANSWERS_REL)
    citation = declaration.attestation_of(doc, 'deliverable')['citation'].strip()
    for relative, digest in documents.items():
        for number, text in enumerate((project / relative).read_text().splitlines(), 1):
            if citation and citation in text:
                return {
                    'id': 'delivery-route', 'layer': 'L19_CONSTRAINTS_PDK',
                    'field_path': '/constraints/tapeout_geometry/deliverable',
                    'requirement': 'Preserve the explicit owner delivery route.',
                    'expected_tokens': [endpoint],
                    'evidence': [f'{relative}:{number} sha256:{digest} — {citation}'],
                }, endpoint
    raise ValueError('D0102_OWNER_SOURCE_UNBOUND')


def _references(project: Path, relatives) -> list[dict]:
    return [{'path': relative, 'sha256': hashlib.sha256(
        metrics._safe_project_file(project, relative).read_bytes()).hexdigest()}
        for relative in relatives]


def _reading_material(project: Path) -> list[dict]:
    _references(project, [f'{PACK}/ic_expert_agent_handoff.json',
                          f'{PACK}/authoring_schema.json'])
    layers = sorted(p.relative_to(project).as_posix()
                    for p in (project / 'phase1/generated_docs').glob('L*.json'))
    pack = sorted(p.relative_to(project).as_posix()
                  for p in (project / PACK).rglob('*')
                  if p.is_file() and p.relative_to(project).as_posix() not in REVIEW_OUTPUTS)
    return _references(project, layers + pack)


def review_output_manifest(project: Path) -> list[dict]:
    """Transport identity only. Existing native consumers validate these answers."""
    return _references(project, [name for name in REVIEW_OUTPUTS
                                if (project / name).exists()])


def read_review_action(project: Path, action: dict) -> dict:
    """Reopen a producer-issued descriptor and reject stale reading material."""
    reference = action['descriptor']
    if action.get('action_kind') != 'INPUT_REVIEW' or reference.get('path') != REVIEW:
        raise ValueError('INPUT_REVIEW_ACTION_INVALID')
    path = metrics._safe_project_file(project, REVIEW)
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference.get('sha256'):
        raise ValueError('INPUT_REVIEW_DESCRIPTOR_STALE')
    descriptor = json.loads(path.read_text())
    if (descriptor.get('project') != str(Path(project).resolve())
            or descriptor.get('producer_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
        raise ValueError('INPUT_REVIEW_PRODUCER_OR_PROJECT_STALE')
    import flow109
    scope = descriptor['delivery_scope']
    context_path = f"reports/flow109/requests/{scope['context_sha256']}.json"
    context = flow109.validate_execution_context(json.loads(
        metrics._safe_project_file(project, context_path).read_text()))
    current = flow109._rtl_scope_binding(project, project / scope['manifest']['path'], context)
    if scope != {**current, 'context_sha256': context['context_sha256']}:
        raise ValueError('INPUT_REVIEW_SCOPE_STALE')
    if (descriptor.get('schema') != 'vibeic.phase1.requirements-review.v1'
            or descriptor.get('status') != 'PENDING'):
        raise ValueError('INPUT_REVIEW_DESCRIPTOR_INVALID')
    documents = metrics._d0102_documents(project, {}, include_owner_request=True)
    if descriptor.get('source_documents') != [
            {'path': name, 'sha256': sha} for name, sha in documents.items()]:
        raise ValueError('INPUT_REVIEW_SOURCE_STALE')
    if descriptor.get('reading_material') != _reading_material(project):
        raise ValueError('INPUT_REVIEW_MATERIAL_STALE')
    return descriptor


def _publish_rtl_review(project: Path, scope: dict, documents: dict) -> dict:
    """Publish the reading task, never a guessed population or an approval."""
    import ai_signed_judgement as judgement
    missing = []
    if not judgement.check(project, 'D1')[0]:
        missing.append('independent current D1 AI judgement')
    import flow109
    context_path = f"reports/flow109/requests/{scope['context_sha256']}.json"
    context = flow109.validate_execution_context(json.loads(
        metrics._safe_project_file(project, context_path).read_text()))
    selected = context.get('resolved_rows') or [context['resolved_row']]
    acceptance = []
    for row in selected:
        consume = {'D01': metrics.accept_d01, 'D02': metrics.accept_d02}.get(row['id'])
        if consume is None:
            continue
        current = flow109.component_context(context, requested_step=row['id'])
        observed = consume(project, current)
        acceptance.append({key: observed[key] for key in
                           ('step_id', 'status', 'qualification', 'delivery_blocked', 'reason')})
        if (observed['status'] != 'PASS' or observed['qualification'] != 'PASS'
                or observed['delivery_blocked'] is not False):
            missing.append(f"{row['id']}: {observed['reason']}")
    if not acceptance:
        missing.append('D0102_SELECTED_REQUIREMENTS_WINDOW_ABSENT')
    result = {'program': 'phase1_base_requirements', 'status': 'NOT_MEASURED',
              'reason': 'D0102_NATIVE_REVALIDATION_REQUIRED', 'published': [],
              'preserved': [name for name in REVIEW_OUTPUTS if (project / name).exists()],
              'missing': missing, 'native_acceptance': acceptance,
              'scope': 'source-backed review transport; no approval or acceptance'}
    if not missing:
        return result
    layers = sorted(p.relative_to(project).as_posix()
                    for p in (project / 'phase1/generated_docs').glob('L*.json'))
    if not layers:
        raise ValueError('INPUT_REVIEW_LDOCS_ABSENT')
    descriptor = {
        'schema': 'vibeic.phase1.requirements-review.v1', 'status': 'PENDING',
        'project': str(project),
        'producer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'action_kind': 'INPUT_REVIEW', 'requested_author': 'vibe-ic:ic-expert-agent',
        'reviewer': 'independent AI; record actual identity and model in review findings and D1 signature',
        'delivery_scope': scope,
        'source_documents': [{'path': name, 'sha256': sha} for name, sha in documents.items()],
        'reading_material': _reading_material(project),
        'missing': missing,
        'output_contracts': {
            f'{PACK}/l_doc_expectations.json': 'Existing D1 handoff answer_contract; preserve input_frame_sha256 when supplied.',
            'reports/audit/ai_judgements/D1.json': {
                'schema': judgement.SCHEMA, 'step_id': 'D1',
                'rule': 'Actual independent reviewer judgement only; bind exact current evidence via ai_signed_judgement.evidence_sha256 after completing review. PASS or FAIL must reflect findings.'},
            SOURCE: {
                'schema': SOURCE_SCHEMA,
                'requirements_trace': ['required_items', 'source_documents', 'expectations', 'features'],
                'endpoint_delivery_items': ['required_items', 'source_documents', 'expectations', 'assignments'],
                'rule': 'Declare the exact source schema above for these derived review populations. Complete original-source normative population; actual current declared L addresses; explicit selected feature declarations; every trace id assigned to its actual endpoint and owning address. Evidence: path:line sha256:<hash> — literal source excerpt. The schema classifies derived consumer context only; native consumers still decide source binding and acceptance.'},
            **{f'requirements/{key}/{metric}.json': {
                'schema': metrics.AUTHORITY_SCHEMA, 'required_items': 'exact corresponding source payload ids',
                'approval': {'status': 'PENDING until actual source review approves exact bytes',
                    'authority': 'requirements_owner',
                    'source_reference': 'path and current sha256 of reviewed input JSON source'},
                'rule': 'Preserve existing approved/preexisting source documents. Approval is reviewer-authored; missing source facts or undeclared addresses remain unresolved.'}
               for key, metric in ROWS}},
        'review_findings': 'Record actual reviewer/model, original source bindings, omissions, contradictions and scope in an audit artifact; no physical owner answer is implied.',
        'normal_reentry': 'Resume the original declared Program window. Existing second-track answer consumer and retained D1 checkpoint revalidator reread outputs; native D01/D02 gates alone decide approval and acceptance. No RTL authoring is released by this descriptor.',
    }
    path = metrics._safe_project_file(project, REVIEW)
    atomic.write_json(path, descriptor)
    result.update(status='PENDING', reason='D0102_REQUIREMENTS_REVIEW_REQUIRED',
                  pending_action={'action_kind': 'INPUT_REVIEW',
                      'descriptor': {'path': REVIEW, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}})
    return result


def publish(project: Path) -> dict:
    project = Path(project).resolve()
    result = {'program': 'phase1_base_requirements', 'status': 'NOT_MEASURED',
              'reason': 'D0102_OWNER_ROUTE_UNRESOLVED', 'published': [], 'preserved': [],
              'missing': ['reviewed complete requirement population', 'explicit feature review'],
              'scope': 'source-backed delivery candidate; no approval or acceptance'}
    try:
        documents = metrics._d0102_documents(project, {}, include_owner_request=True)
        import flow109
        scope = flow109.active_rtl_scope(project)
        if scope is not None:
            try:
                result = _publish_rtl_review(project, scope, documents)
            except (OSError, ValueError, TypeError, KeyError, metrics.MetricRefusal) as exc:
                result.update(reason='INPUT_REVIEW_PUBLICATION_REFUSED', detail=str(exc),
                    pending_action={'action_kind': 'INPUT_REVIEW', 'blocked_reason': str(exc)})
            atomic.write_json(layout.report_path(project, REPORT), result)
            return result
        try:
            fact, endpoint = _owner_fact(project, documents)
        except ValueError as exc:
            if str(exc) == 'D0102_OWNER_SOURCE_UNBOUND':
                result['reason'] = str(exc)
            raise
        source_documents = [{'path': path, 'sha256': digest} for path, digest in documents.items()]
        population = [{'id': fact['id']}]
        shared = {'required_items': population, 'source_documents': source_documents,
                  'expectations': [fact]}
        payload = {'schema': SOURCE_SCHEMA, 'requirements_trace': {**shared, 'features': []},
                   'endpoint_delivery_items': {**shared, 'assignments': [{
                       'id': fact['id'], 'endpoint': endpoint,
                       'layer': fact['layer'], 'field_path': fact['field_path']}]}}
        existing = {}
        for key, metric in ROWS:
            relative = f'requirements/{key}/{metric}.json'
            path = metrics._safe_project_file(project, relative)
            if path.exists():
                try:
                    existing[relative] = json.loads(path.read_text())
                    if not isinstance(existing[relative], dict):
                        raise metrics.MetricRefusal('D0102_EXISTING_AUTHORITY_INVALID', relative + ': object required')
                    approval = existing[relative].get('approval')
                    if not isinstance(approval, dict):
                        raise metrics.MetricRefusal('D0102_EXISTING_AUTHORITY_INVALID', relative + ': approval object required')
                    source_reference = approval.get('source_reference')
                    if not isinstance(source_reference, dict):
                        raise metrics.MetricRefusal('D0102_EXISTING_AUTHORITY_INVALID', relative + ': source_reference object required')
                except (metrics.MetricRefusal, json.JSONDecodeError) as exc:
                    result['preserved'].append(relative)
                    if isinstance(exc, metrics.MetricRefusal):
                        raise
                    raise metrics.MetricRefusal('D0102_EXISTING_AUTHORITY_INVALID', relative + ': invalid JSON') from exc
                if (approval.get('status') != 'PENDING'
                        and source_reference.get('path') == SOURCE):
                    result['preserved'].append(relative)
        if result['preserved']:
            result['reason'] = 'D0102_PROTECTED_CANDIDATE_SOURCE'
            raise ValueError('D0102_PROTECTED_CANDIDATE_SOURCE')
        source = metrics._safe_project_file(project, SOURCE)
        if source.exists():
            prior = json.loads(source.read_text())
            legacy = {k: v for k, v in payload.items() if k != 'schema'}
            if prior != payload and prior != legacy:
                result['reason'] = 'D0102_CANDIDATE_SOURCE_CHANGED'
                raise ValueError('D0102_CANDIDATE_SOURCE_CHANGED')
        if not source.exists():
            atomic.write_json(source, payload)
        reference = {'path': SOURCE, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        for key, metric in ROWS:
            relative = f'requirements/{key}/{metric}.json'
            path = metrics._safe_project_file(project, relative)
            candidate = {'schema': metrics.AUTHORITY_SCHEMA, 'required_items': population,
                         'approval': {'status': 'PENDING', 'authority': 'requirements_owner',
                                      'source_reference': reference}}
            if relative in existing and existing[relative] != candidate:
                result['preserved'].append(relative)
                continue
            if not path.exists():
                atomic.write_json(path, candidate)
            result['published'].append(relative)
        result.update(status='PENDING', reason='D0102_REQUIREMENTS_OWNER_REVIEW_REQUIRED')
    except (OSError, ValueError, TypeError, KeyError, metrics.MetricRefusal) as exc:
        if isinstance(exc, metrics.MetricRefusal):
            result['reason'] = exc.code
        result['detail'] = str(exc)
    atomic.write_json(layout.report_path(project, REPORT), result)
    return result
