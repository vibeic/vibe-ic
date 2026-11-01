"""A01 component adapter for the existing spec producer and read-only gate.

This is a bounded dispatch adapter, not another analog runner. It never calls
topology, simulation or layout. Component completion is not A01 metric signoff.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_json
from flow109 import Flow109Error, validate_execution_context
from flow109_admission import AdmissionRefusal, require_launch_admission
from flow109_metric_acceptance import accept_a01

PRODUCER = HERE / 'analog_a1_spec_emit.py'
CONSUMER = HERE / 'analog_a1_spec_extract_check.py'
INPUTS = ('phase3/analog/analog_block_list.json',
          'phase1/analog/analog_block_list.json',
          'phase1/generated_docs/L1_DATASHEET.json',
          'phase1/generated_docs/L5_ADI_SPEC.json',
          'phase1/generated_docs/L9_INTEGRATION_SPEC.json',
          'requirements/base_A1/electrical_row_attribution.json')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operation_sources():
    """Use the existing transitive source resolver, with portable package paths."""
    from execution_provider_catalog import source_closure
    paths = source_closure({PRODUCER, CONSUMER})
    paths.update((Path(__file__), HERE / 'flow109.py', HERE / 'flow109_admission.py',
                  HERE / 'flow109_metric_acceptance.py',
                  HERE / 'execution_provider_catalog.py'))
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(paths)}


def _inputs(project):
    out = {}
    for relative in INPUTS:
        path = project / relative
        if path.is_symlink() or not path.resolve().is_relative_to(project):
            raise Flow109Error('FLOW109_A01_FOREIGN_INPUT', relative)
        out[relative] = _sha(path) if path.is_file() else None
    return out


def _blocks(project):
    path = next((project / p for p in INPUTS[:2] if (project / p).is_file()), None)
    if path is None:
        raise Flow109Error('FLOW109_A01_BLOCK_LIST_ABSENT', 'A01 requires a declared nonempty block list')
    try:
        data = json.loads(path.read_text())
        rows = data.get('blocks') if isinstance(data, dict) else data
    except (OSError, ValueError) as exc:
        raise Flow109Error('FLOW109_A01_BLOCK_LIST_INVALID', str(path)) from exc
    if not isinstance(rows, list) or not rows:
        raise Flow109Error('FLOW109_A01_BLOCK_LIST_INVALID', 'nonempty structured entries required')
    names = [row.get('name') or row.get('block') for row in rows if isinstance(row, dict)]
    if (len(names) != len(rows)
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', name)
                   or name in ('.', '..') for name in names)
            or len(set(names)) != len(names)):
        raise Flow109Error('FLOW109_A01_BLOCK_LIST_INVALID', 'unique safe structured block names required')
    return names


def _launch(project, context, argv, log, expected_inputs, sources):
    # Recheck at the actual subprocess seam, not only at the front door.
    require_launch_admission(project, 'A1', {'flow109_context': context})
    if operation_sources() != sources or _inputs(project) != expected_inputs:
        raise Flow109Error('FLOW109_A01_SUBJECT_CHANGED', 'source or consumed inputs changed before launch')
    completed = subprocess.run(argv, cwd=project, capture_output=True, text=True)
    log.write_text(completed.stdout + completed.stderr)
    return {'argv': argv, 'returncode': completed.returncode,
            'log': str(log.relative_to(project)), 'log_sha256': _sha(log)}


def execute(project, context):
    project = Path(project).resolve()
    context = validate_execution_context(context)
    if context['requested_step'] != 'A01' or context['native_step_id'] != 'A1':
        raise Flow109Error('FLOW109_A01_WRONG_COMPONENT', str(context['requested_step']))
    # Must reject unsupported/missing qualifications even when no artifact exists.
    require_launch_admission(project, 'A1', {'flow109_context': context})
    sources = operation_sources()
    uses = context['runtime_tool_uses']
    if len(uses) != 1 or uses[0]['semantics'].get('operation_sources') != sources:
        raise AdmissionRefusal('QUALIFICATION_OPERATION_SOURCE_MISMATCH',
                               'A01 qualification must bind adapter, producer, consumer and source closure')
    inputs = _inputs(project)
    names = _blocks(project)
    if inputs['phase1/generated_docs/L5_ADI_SPEC.json'] is None:
        raise Flow109Error('FLOW109_A01_SPEC_INPUT_ABSENT', 'structured L5 is required')
    for name in names:
        directory = project / 'phase3/analog' / name
        if not directory.resolve().is_relative_to(project):
            raise Flow109Error('FLOW109_A01_FOREIGN_OUTPUT', name)
        if (directory / 'spec.json').is_symlink():
            raise Flow109Error('FLOW109_A01_FOREIGN_OUTPUT', name)
    parent = project / 'reports/flow109/attempts'
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix='A01-', dir=parent))
    python = uses[0]['executable']['path']
    producer_report = attempt / 'producer.json'
    record = {'schema': 'vibeic.flow109.analog-component.v1', 'step_id': 'A01',
              'native_step_id': 'A1', 'context_sha256': context['context_sha256'],
              'component_status': 'NOT_MEASURED', 'flow109_acceptance': 'NOT_MEASURED',
              'source_sha256': sources, 'inputs': inputs, 'declared_blocks': names,
              'executions': [], 'blocks': [], 'outputs': {},
              'unimplemented_obligations': [o['id'] for o in context['resolved_row']['obligations']],
              'attempt': str(attempt.relative_to(project))}
    run = _launch(project, context,
                  [python, str(PRODUCER), str(project), '--json', str(producer_report)],
                  attempt / 'producer.log', inputs, sources)
    record['executions'].append(run)
    try:
        produced = json.loads(producer_report.read_text())
    except (OSError, ValueError):
        produced = {}
    record['producer_report'] = produced
    if produced.get('producer') != 'analog_a1_spec_emit' or not isinstance(produced.get('records'), list):
        record.update(component_status='FAIL', reason='A01_PRODUCER_RECEIPT_ABSENT')
    elif run['returncode'] not in (0, 2):
        record.update(component_status='FAIL', reason='A01_PRODUCER_FAILED')
    else:
        record.update(component_status='PASS', reason='A01_NATIVE_COMPONENT_COMPLETE_ONLY')
        for name in names:
            gate_path = attempt / (name + '-gate.json')
            gate_run = _launch(project, context,
                [python, str(CONSUMER), str(project), '--block', name, '--json', str(gate_path)],
                attempt / (name + '-gate.log'), inputs, sources)
            record['executions'].append(gate_run)
            try:
                gate = json.loads(gate_path.read_text())
            except (OSError, ValueError):
                gate = {}
            spec = project / 'phase3/analog' / name / 'spec.json'
            items = [r for r in produced['records'] if isinstance(r, dict) and r.get('block') == name]
            current_emission = len(items) == 1 and items[0].get('action') == 'emitted'
            try:
                body = json.loads(spec.read_text()) if spec.is_file() else {}
            except (OSError, ValueError):
                body = {}
            if not isinstance(body, dict):
                body = {}
            provenance = body.get('_provenance') or {}
            bound = (provenance.get('producer') == 'analog_a1_spec_emit'
                     and (provenance.get('input') or {}).get('sha256') == inputs[
                         'phase1/generated_docs/L5_ADI_SPEC.json'])
            valid_gate = gate.get('gate') == 'analog_a1_spec_extract_check'
            status = ('FAIL' if not valid_gate or gate.get('verdict') == 'FAIL'
                      else 'PASS' if gate_run['returncode'] == 0 and gate.get('verdict') == 'PASS'
                           and current_emission and bound else 'NOT_MEASURED')
            record['blocks'].append({'block': name, 'component_status': status,
                                     'current_emission': current_emission, 'source_input_bound': bound,
                                     'gate': gate, 'gate_report': str(gate_path.relative_to(project))})
            if status == 'FAIL' or (status == 'NOT_MEASURED' and record['component_status'] != 'FAIL'):
                record['component_status'] = status
            for path in (spec, spec.parent / 'spec_gap.json', gate_path):
                if path.is_file():
                    record['outputs'][str(path.relative_to(project))] = _sha(path)
        if record['component_status'] != 'PASS':
            record['reason'] = 'A01_INCOMPLETE_CURRENT_PRODUCTION_OR_CONSUMER'
    if _inputs(project) != inputs or operation_sources() != sources:
        record.update(component_status='FAIL', reason='A01_SOURCE_OR_INPUT_CHANGED')
    for path in (producer_report, attempt / 'producer.log'):
        if path.is_file():
            record['outputs'][str(path.relative_to(project))] = _sha(path)
    from analog_a1_spec_emit import CHIP_SPECS_REL
    if (project / CHIP_SPECS_REL).is_file():
        record['outputs'][CHIP_SPECS_REL] = _sha(project / CHIP_SPECS_REL)
    # Row-level metric acceptance is separate from G1-G9 and whole-flow
    # acceptance.  The latter deliberately remains NOT_MEASURED here.
    require_launch_admission(project, 'A1', {'flow109_context': context})
    record['metric_acceptance'] = accept_a01(project, context, record)
    record['metric_acceptance_status'] = record['metric_acceptance']['status']
    record['unimplemented_obligations'] = [
        item['id'] for item in record['metric_acceptance']['obligations']
        if item['status'] == 'UNIMPLEMENTED_METRIC_BINDING']
    write_json(attempt / 'component.json', record)
    return record
