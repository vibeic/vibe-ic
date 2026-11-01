"""Publish source-backed base01/base02 candidates, never requirements approval.

ADVISORY: a candidate contains only the owner's explicit delivery fact. Full
requirement population and feature review remain pending at the existing gates.
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
REPORT = 'phase1/base_requirements_candidates.json'
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


def publish(project: Path) -> dict:
    project = Path(project).resolve()
    result = {'program': 'phase1_base_requirements', 'status': 'NOT_MEASURED',
              'reason': 'D0102_OWNER_ROUTE_UNRESOLVED', 'published': [], 'preserved': [],
              'missing': ['reviewed complete requirement population', 'explicit feature review'],
              'scope': 'source-backed delivery candidate; no approval or acceptance'}
    try:
        documents = metrics._d0102_documents(project, {}, include_owner_request=True)
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
        payload = {'requirements_trace': {**shared, 'features': []},
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
        if source.exists() and json.loads(source.read_text()) != payload:
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
