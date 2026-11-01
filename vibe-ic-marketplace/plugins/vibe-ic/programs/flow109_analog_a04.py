"""Flow 109 A04: source-authorized topology emission and retained checking.

The existing A2 emitter renders a declared circuit class.  It is not the
design authority.  This adapter requires a separately approved topology and
budget declaration, checks the emitted IR against it, and keeps Flow 109
metric/G1--G9 acceptance explicitly NOT_MEASURED.
"""
from __future__ import annotations

import hashlib
import json
import math
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

PRODUCER = HERE / 'analog_a2_topology_emit.py'
CONSUMER = HERE / 'analog_a2_topology_select_check.py'
SCHEMA = 'vibeic.flow109.analog-topology.v1'
INPUT = 'input/flow109/A04.json'
FREEZE = 'adopted/analog_topology/topology_freeze.json'
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*\Z')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, code='A04_INPUT_INVALID'):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal(code, str(path))
    return value


def _bound(project, record, code='A04_STALE_OR_MISSING_INPUT'):
    if not isinstance(record, dict) or set(record) != {'path', 'sha256'}:
        raise AdmissionRefusal('A04_UNBOUND_INPUT', str(record))
    relative = Path(str(record.get('path', '')))
    if relative.is_absolute() or not relative.parts:
        raise AdmissionRefusal('A04_UNBOUND_INPUT', str(record))
    cursor = project
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise AdmissionRefusal(code, 'symlinked path component: ' + str(cursor))
    path = (project / relative).resolve()
    if (not path.is_relative_to(project) or not path.is_file()
            or _sha(path) != record.get('sha256')):
        raise AdmissionRefusal(code, str(path))
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)), 'sha256': _sha(path)}


def operation_sources():
    from execution_provider_catalog import source_closure
    paths = source_closure({Path(__file__), PRODUCER, CONSUMER})
    paths.update((HERE / 'flow109.py', HERE / 'flow109_admission.py'))
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(paths)}


def _current_a02(project, record):
    path = _bound(project, record, 'A04_A02_RECEIPT_STALE')
    receipt = _read(path, 'A04_A02_RECEIPT_INVALID')
    if (receipt.get('schema') != 'vibeic.flow109.analog-model-qualification.v1'
            or receipt.get('step_id') != 'A02'
            or receipt.get('component_status') != 'PASS'
            or receipt.get('flow109_acceptance') != 'NOT_MEASURED'
            or (receipt.get('consumer') or {}).get('verdict') != 'PASS'
            or not receipt.get('smokes')):
        raise AdmissionRefusal('A04_A02_RECEIPT_NOT_PASS', str(path))
    for source, digest in (receipt.get('inputs') or {}).items():
        candidate = Path(source)
        if not candidate.is_absolute():
            candidate = project / candidate
        try:
            candidate = candidate.resolve()
        except OSError as exc:
            raise AdmissionRefusal('A04_A02_RECEIPT_STALE', source) from exc
        if (not candidate.is_relative_to(project) or not candidate.is_file()
                or _sha(candidate) != digest):
            raise AdmissionRefusal('A04_A02_RECEIPT_STALE', source)
    qualified = {(row.get('device'), row.get('corner'))
                 for row in receipt.get('smokes', []) if isinstance(row, dict)}
    if not qualified or any(not a or not b for a, b in qualified):
        raise AdmissionRefusal('A04_A02_MODEL_SCOPE_UNBOUND', str(path))
    return path, receipt, sorted([list(x) for x in qualified])


def budget_leaves(budgets, block, path=()):
    """Read scalar or named sub-circuit/condition allocations; refuse every gap."""
    label = ':'.join((block, *path))
    if not isinstance(budgets, dict) or not budgets:
        raise AdmissionRefusal('A04_BUDGET_UNBOUND', label)
    if {'status', 'limit', 'unit'} & budgets.keys():
        value = budgets.get('limit')
        if (set(budgets) != {'status', 'limit', 'unit'}
                or budgets.get('status') != 'BOUND'
                or not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value <= 0
                or not isinstance(budgets.get('unit'), str) or not budgets['unit'].strip()):
            raise AdmissionRefusal('A04_BUDGET_UNBOUND', label)
        return [(path, budgets)]
    leaves = []
    for key, child in budgets.items():
        if not isinstance(key, str) or not key.strip():
            raise AdmissionRefusal('A04_BUDGET_UNBOUND', label)
        leaves.extend(budget_leaves(child, block, (*path, key)))
    return leaves


def _approved_requirements(project, manifest):
    path = _bound(project, manifest.get('requirements'))
    body = _read(path)
    approval = body.get('approval') or {}
    rows = body.get('blocks')
    if (body.get('schema') != SCHEMA or approval.get('status') != 'APPROVED'
            or approval.get('authority') != 'analog_design_authority'
            or not approval.get('source_reference')
            or not isinstance(rows, list) or not rows):
        raise AdmissionRefusal('A04_REQUIREMENTS_NOT_APPROVED', str(path))
    names = []
    numeric_fields = ('min', 'typ', 'max', 'value', 'target')
    for row in rows:
        name = row.get('block') if isinstance(row, dict) else None
        budgets = row.get('budgets') if isinstance(row, dict) else None
        if (not isinstance(name, str) or not _IDENT.fullmatch(name)
                or not isinstance(row.get('block_type'), str)
                or not isinstance(row.get('selected_topology'), str)
                or not row['selected_topology'].strip()
                or not isinstance(row.get('topology_constraints'), list)
                or not row['topology_constraints']
                or not isinstance(row.get('required_device_roles'), list)
                or not row['required_device_roles']):
            raise AdmissionRefusal('A04_REQUIREMENT_ROW_INVALID', str(name))
        budget_leaves(budgets, name)
        spec = _bound(project, row.get('spec'))
        spec_body = _read(spec)
        values = spec_body.get('specs')
        if (not isinstance(values, list) or not values
                or any(not isinstance(item, dict)
                       or not any(key in item for key in numeric_fields)
                       or any(not isinstance(item[key], (int, float))
                              or isinstance(item[key], bool)
                              for key in numeric_fields if key in item)
                       or not item.get('unit') for item in values)):
            raise AdmissionRefusal('A04_ANALOG_SPEC_UNBOUND', name)
        names.append(name)
    if len(names) != len(set(names)):
        raise AdmissionRefusal('A04_REQUIREMENT_ROW_INVALID', 'duplicate block')
    return path, body, {row['block']: row for row in rows}


def prepare(project, context):
    context = validate_execution_context(context)
    if context['requested_step'] != 'A04' or context['native_step_id'] != 'flow109.A04':
        raise Flow109Error('FLOW109_A04_WRONG_COMPONENT', str(context['requested_step']))
    require_launch_admission(project, 'flow109.A04', {'flow109_context': context})
    sources = operation_sources()
    uses = context['runtime_tool_uses']
    if (len(uses) != 1 or uses[0]['tool_id'] != 'python3'
            or (uses[0].get('semantics') or {}).get('operation_sources') != sources):
        raise AdmissionRefusal('QUALIFICATION_OPERATION_SOURCE_MISMATCH',
                               'A04 must bind its adapter, emitter and retained reader')
    manifest_path = project / INPUT
    manifest = _read(manifest_path)
    if manifest.get('schema') != SCHEMA or manifest.get('basis') != 'source_bound_expert_topology':
        raise AdmissionRefusal('A04_BASIS_UNSUPPORTED', str(manifest.get('basis')))
    pdk_path = _bound(project, manifest.get('pdk'))
    pdk = _read(pdk_path)
    if (pdk.get('schema') != SCHEMA or not isinstance(pdk.get('family'), str)
            or not pdk.get('family') or not isinstance(pdk.get('typed_models'), list)
            or not pdk['typed_models']):
        raise AdmissionRefusal('A04_PDK_DECLARATION_INVALID', str(pdk_path))
    requirements_path, requirements, rows = _approved_requirements(project, manifest)
    a02_path, a02, qualified = _current_a02(project, manifest.get('a02_receipt'))
    declared_pairs = {(x.get('device'), x.get('corner')) for x in pdk['typed_models']
                      if isinstance(x, dict)}
    if declared_pairs != {tuple(x) for x in qualified}:
        raise AdmissionRefusal('A04_MODEL_SCOPE_MISMATCH', str(sorted(declared_pairs)))
    identity = uses[0]
    if (identity['config'] != _record(project, manifest_path)
            or identity['pdk'] != _record(project, pdk_path)
            or identity['deck'] != _record(project, requirements_path)
            or identity['corner'] != sorted({x[1] for x in declared_pairs})):
        raise AdmissionRefusal('A04_RUNTIME_SCOPE_MISMATCH', identity['use_id'])
    inputs = {str(path): _sha(path) for path in
              (manifest_path, pdk_path, requirements_path, a02_path)}
    for row in rows.values():
        spec = _bound(project, row['spec'])
        inputs[str(spec)] = _sha(spec)
    return {'manifest': manifest, 'pdk': pdk, 'requirements': requirements,
            'rows': rows, 'a02': a02, 'sources': sources, 'inputs': inputs,
            'binary': identity['executable']['path']}


def _before(project, context, prepared):
    require_launch_admission(project, 'flow109.A04', {'flow109_context': context})
    if operation_sources() != prepared['sources']:
        raise AdmissionRefusal('A04_OPERATION_SOURCE_CHANGED', 'before producer launch')
    for path, digest in prepared['inputs'].items():
        if not Path(path).is_file() or _sha(path) != digest:
            raise AdmissionRefusal('A04_STALE_OR_MISSING_INPUT', path)


def _launch(project, context, prepared, argv, log):
    _before(project, context, prepared)
    completed = subprocess.run(argv, cwd=project, capture_output=True, text=True)
    log.write_text(completed.stdout + completed.stderr, encoding='utf-8')
    return {'argv': argv, 'returncode': completed.returncode,
            'log': _record(project, log)}


def execute(project, context):
    project = Path(project).resolve()
    prepared = prepare(project, context)
    parent = project / 'reports/flow109/attempts'
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix='A04-', dir=parent))
    report = {'schema': SCHEMA, 'step_id': 'A04', 'native_step_id': 'flow109.A04',
              'component_status': 'NOT_MEASURED', 'flow109_acceptance': 'NOT_MEASURED',
              'context_sha256': context['context_sha256'], 'native_started': False,
              'operation_sources': prepared['sources'], 'inputs': prepared['inputs'],
              'a02_receipt': _record(project, _bound(project, prepared['manifest']['a02_receipt'])),
              'executions': [], 'blocks': [],
              'unimplemented_obligations': [x['id'] for x in context['resolved_row']['obligations']],
              'gate_layers': {f'G{i}': 'NOT_MEASURED' for i in range(1, 10)},
              'qualification_scope': ('topology component only; performance, statistics, '
                                      'Flow 109 qualification and benchmark PASS NOT_MEASURED')}
    for name, authority in prepared['rows'].items():
        producer_json = attempt / (name + '-producer.json')
        run = _launch(project, context, prepared,
            [prepared['binary'], str(PRODUCER), str(project), '--block', name,
             '--pdk', prepared['pdk']['family'], '--json', str(producer_json)],
            attempt / (name + '-producer.log'))
        report['native_started'] = True
        report['executions'].append(run)
        produced = _read(producer_json, 'A04_PRODUCER_RECEIPT_INVALID')
        records = [x for x in produced.get('records', [])
                   if isinstance(x, dict) and x.get('block') == name]
        if run['returncode'] != 0 or len(records) != 1 or records[0].get('action') != 'emitted':
            report.update(component_status='NOT_MEASURED', reason='A04_TOPOLOGY_NOT_EMITTED')
            break
        ir_path = project / 'phase3/analog' / name / 'topology.json'
        ir = _read(ir_path, 'A04_TOPOLOGY_IR_INVALID')
        roles = sorted({x.get('role') for x in ir.get('devices', []) if isinstance(x, dict)})
        if (ir.get('block_type') != authority['block_type']
                or ir.get('topology') != authority['selected_topology']
                or roles != sorted(authority['required_device_roles'])
                or (ir.get('_provenance') or {}).get('producer') != 'analog_a2_topology_emit'):
            raise AdmissionRefusal('A04_EXPERT_SELECTION_MISMATCH', name)
        gate_json = attempt / (name + '-gate.json')
        gate_run = _launch(project, context, prepared,
            [prepared['binary'], str(CONSUMER), str(project), '--block', name,
             '--json', str(gate_json)], attempt / (name + '-gate.log'))
        report['executions'].append(gate_run)
        gate = _read(gate_json, 'A04_CONSUMER_RECEIPT_INVALID')
        status = 'PASS' if gate_run['returncode'] == 0 and gate.get('verdict') == 'PASS' else 'FAIL'
        report['blocks'].append({'block': name, 'component_status': status,
                                 'expert_authority': _record(project, _bound(project, prepared['manifest']['requirements'])),
                                 'topology': _record(project, ir_path),
                                 'topology_md': _record(project, ir_path.with_name('topology.md')),
                                 'producer': produced, 'consumer': gate})
        if status != 'PASS':
            report.update(component_status='FAIL', reason='A04_RETAINED_CONSUMER_FAILED')
            break
    else:
        report.update(component_status='PASS', reason='A04_SOURCE_AUTHORIZED_TOPOLOGY_COMPONENT_COMPLETE_ONLY')
    _before(project, context, prepared)
    if report['component_status'] == 'PASS':
        freeze = {'schema': SCHEMA, 'status': 'PASS', 'step_id': 'A04',
                  'context_sha256': context['context_sha256'], 'inputs': prepared['inputs'],
                  'a02_receipt': report['a02_receipt'], 'blocks': report['blocks'],
                  'scope': report['qualification_scope']}
        write_json(project / FREEZE, freeze)
        report['freeze'] = _record(project, project / FREEZE)
    write_json(attempt / 'component.json', report)
    return report
