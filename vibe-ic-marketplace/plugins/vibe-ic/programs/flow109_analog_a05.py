"""Flow 109 A05: expert-bound sizing/netlist plus native ngspice OP.

Supported subset: one or more source-approved blocks whose current A04 IR
already contains every approved device geometry, model libraries and their
hash-bound transitive closure qualified by the current A02 receipt, explicit
per-library corners, and numeric operating-point thresholds. Unsupported or
unbound forms fail closed.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_bytes, write_json
import _watchdog
from flow109 import Flow109Error, validate_execution_context
from flow109_admission import AdmissionRefusal, require_launch_admission
import flow109_analog_a04 as a04

PRODUCER = HERE / 'analog_a3_netlist_emit.py'
CONSUMER = HERE / 'analog_a3_netlist_gen_check.py'
SCHEMA = 'vibeic.flow109.analog-netlist-sizing.v1'
INPUT = 'input/flow109/A05.json'
FREEZE = 'adopted/analog_netlist_sizing/netlist_freeze.json'
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*\Z')
_MEAS_LINE = re.compile(r'(?i)^\s*MEAS\s+')
_MEAS_PAIR = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
                        r'([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?)\b', re.I)
_LOAD = re.compile(r'(?im)^\s*\.lib\s+(\S+)\s+(\S+)\s*$')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, code='A05_INPUT_INVALID'):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal(code, str(path))
    return value


def _bound(project, record, code='A05_STALE_OR_MISSING_INPUT'):
    if not isinstance(record, dict) or set(record) != {'path', 'sha256'}:
        raise AdmissionRefusal('A05_UNBOUND_INPUT', str(record))
    relative = Path(str(record.get('path', '')))
    if relative.is_absolute() or not relative.parts:
        raise AdmissionRefusal('A05_UNBOUND_INPUT', str(record))
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
    paths = source_closure({Path(__file__), PRODUCER, CONSUMER,
                            HERE / 'flow109_analog_a04.py'})
    paths.update((HERE / 'flow109.py', HERE / 'flow109_admission.py'))
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(paths)}


def _current_receipt(project, record, *, step, schema):
    path = _bound(project, record, f'A05_{step}_RECEIPT_STALE')
    body = _read(path, f'A05_{step}_RECEIPT_INVALID')
    if (body.get('schema') != schema or body.get('step_id') != step
            or body.get('component_status') != 'PASS'
            or body.get('flow109_acceptance') != 'NOT_MEASURED'):
        raise AdmissionRefusal(f'A05_{step}_RECEIPT_NOT_PASS', str(path))
    for source, digest in (body.get('inputs') or {}).items():
        candidate = Path(source)
        if not candidate.is_absolute():
            candidate = project / candidate
        candidate = candidate.resolve()
        if (not candidate.is_relative_to(project) or not candidate.is_file()
                or _sha(candidate) != digest):
            raise AdmissionRefusal(f'A05_{step}_RECEIPT_STALE', source)
    return path, body


def _a02_models(project, receipt):
    out = {}
    for smoke in receipt.get('smokes') or []:
        if not isinstance(smoke, dict) or not smoke.get('device') or not smoke.get('corner'):
            raise AdmissionRefusal('A05_A02_MODEL_SCOPE_UNBOUND', str(smoke))
        record = smoke.get('model')
        if record is None:
            # A02 itself binds the original model in the emitted smoke row in
            # production.  Refuse older/abridged receipts: guessing from an
            # executed copy would sever the source model identity.
            raise AdmissionRefusal('A05_A02_MODEL_PATH_UNBOUND', smoke['device'])
        path = _bound(project, record, 'A05_A02_MODEL_STALE')
        closure = (smoke.get('model_closure') or {}).get('files')
        if closure is None:
            closure = [record]
        if (not isinstance(closure, list) or not closure
                or any(not isinstance(item, dict) for item in closure)):
            raise AdmissionRefusal('A05_A02_MODEL_CLOSURE_UNBOUND', smoke['device'])
        closure_paths = []
        for item in closure:
            closure_paths.append((_bound(project, item, 'A05_A02_MODEL_STALE'), item))
        out[(str(path), smoke['corner'])] = {
            'device': smoke['device'], 'path': path, 'record': record,
            'closure': closure_paths,
        }
    if not out:
        raise AdmissionRefusal('A05_A02_MODEL_SCOPE_UNBOUND', 'empty')
    return out


def _geometry(ir):
    result = []
    for device in ir.get('devices') or []:
        if not isinstance(device, dict):
            continue
        row = {key: device[key] for key in ('name', 'role', 'w', 'l', 'm') if key in device}
        result.append(row)
    return sorted(result, key=lambda x: x.get('name', ''))


def _requirements(project, manifest):
    path = _bound(project, manifest.get('requirements'))
    body = _read(path)
    approval = body.get('approval') or {}
    rows = body.get('blocks')
    if (body.get('schema') != SCHEMA or approval.get('status') != 'APPROVED'
            or approval.get('authority') != 'analog_design_authority'
            or not approval.get('source_reference')
            or not isinstance(rows, list) or not rows):
        raise AdmissionRefusal('A05_REQUIREMENTS_NOT_APPROVED', str(path))
    indexed = {}
    for row in rows:
        name = row.get('block') if isinstance(row, dict) else None
        targets = row.get('operating_point_targets') if isinstance(row, dict) else None
        sizes = row.get('device_sizes') if isinstance(row, dict) else None
        corners = row.get('corners') if isinstance(row, dict) else None
        corner = row.get('corner') if isinstance(row, dict) else None
        corner_set_valid = (
            isinstance(corner, str) and _IDENT.fullmatch(corner) and corners is None
        ) or (
            corner is None and isinstance(corners, list) and corners
            and len(corners) == len(set(corners))
            and all(isinstance(value, str) and _IDENT.fullmatch(value)
                    for value in corners)
        )
        if (not isinstance(name, str) or not _IDENT.fullmatch(name)
                or name in indexed or row.get('required_analysis') != 'op'
                or not corner_set_valid
                or not isinstance(sizes, list) or not sizes
                or not isinstance(targets, dict) or not targets):
            raise AdmissionRefusal('A05_REQUIREMENT_ROW_INVALID', str(name))
        if any(not isinstance(x, dict) or not _IDENT.fullmatch(str(x.get('name', '')))
               or not _IDENT.fullmatch(str(x.get('role', '')))
               or any(not isinstance(x.get(k), (int, float)) or isinstance(x.get(k), bool)
                      or x[k] <= 0 for k in ('w', 'l') if k in x)
               for x in sizes):
            raise AdmissionRefusal('A05_DEVICE_SIZING_UNBOUND', name)
        for metric, threshold in targets.items():
            lo = threshold.get('min') if isinstance(threshold, dict) else None
            hi = threshold.get('max') if isinstance(threshold, dict) else None
            if (not _IDENT.fullmatch(str(metric)) or not isinstance(lo, (int, float))
                    or isinstance(lo, bool) or not isinstance(hi, (int, float))
                    or isinstance(hi, bool) or not math.isfinite(float(lo))
                    or not math.isfinite(float(hi)) or lo <= 0 or hi <= 0 or lo > hi
                    or not isinstance(threshold.get('unit'), str)
                    or not threshold['unit'].strip()):
                raise AdmissionRefusal('A05_OPERATING_POINT_THRESHOLD_UNBOUND', name + ':' + str(metric))
        _bound(project, row.get('spec'))
        indexed[name] = row
    return path, body, indexed


def _row_corners(row):
    """Backward-compatible single-corner rows plus real multi-library decks."""
    return [row['corner']] if row.get('corner') is not None else list(row['corners'])


def prepare(project, context):
    context = validate_execution_context(context)
    if context['requested_step'] != 'A05' or context['native_step_id'] != 'flow109.A05':
        raise Flow109Error('FLOW109_A05_WRONG_COMPONENT', str(context['requested_step']))
    require_launch_admission(project, 'flow109.A05', {'flow109_context': context})
    sources = operation_sources()
    uses = context['runtime_tool_uses']
    by_tool = {x.get('tool_id'): x for x in uses if isinstance(x, dict)}
    if (set(by_tool) != {'python3', 'ngspice'} or len(uses) != 2
            or any((x.get('semantics') or {}).get('operation_sources') != sources
                   for x in uses)):
        raise AdmissionRefusal('QUALIFICATION_OPERATION_SOURCE_MISMATCH',
                               'A05 must bind emitter, reader and native ngspice consumer')
    manifest_path = project / INPUT
    manifest = _read(manifest_path)
    if manifest.get('schema') != SCHEMA or manifest.get('basis') != 'expert_sizing_native_operating_point':
        raise AdmissionRefusal('A05_BASIS_UNSUPPORTED', str(manifest.get('basis')))
    pdk_path = _bound(project, manifest.get('pdk'))
    pdk = _read(pdk_path)
    if (pdk.get('schema') != SCHEMA or not isinstance(pdk.get('family'), str)
            or not pdk.get('family')
            or pdk.get('model_dependency_policy') not in (
                'self_contained_local', 'a02_bound_transitive')):
        raise AdmissionRefusal('A05_PDK_DECLARATION_INVALID', str(pdk_path))
    requirements_path, requirements, rows = _requirements(project, manifest)
    a02_path, a02 = _current_receipt(project, manifest.get('a02_receipt'), step='A02',
        schema='vibeic.flow109.analog-model-qualification.v1')
    if (a02.get('consumer') or {}).get('verdict') != 'PASS':
        raise AdmissionRefusal('A05_A02_RECEIPT_NOT_PASS', str(a02_path))
    models = _a02_models(project, a02)
    a04_path, a04_receipt = _current_receipt(project, manifest.get('a04_receipt'),
        step='A04', schema=a04.SCHEMA)
    if a04_receipt.get('a02_receipt') != manifest.get('a02_receipt'):
        raise AdmissionRefusal('A05_UPSTREAM_CHAIN_MISMATCH', 'A04 and A05 bind different A02 receipts')
    a04_blocks = {x.get('block'): x for x in a04_receipt.get('blocks', []) if isinstance(x, dict)}
    if set(a04_blocks) != set(rows):
        raise AdmissionRefusal('A05_A04_BLOCK_SCOPE_MISMATCH', str(sorted(a04_blocks)))
    inputs = {str(path): _sha(path) for path in
              (manifest_path, pdk_path, requirements_path, a02_path, a04_path)}
    for model in models.values():
        inputs[str(model['path'])] = model['record']['sha256']
        for dependency, dependency_record in model['closure']:
            inputs[str(dependency)] = dependency_record['sha256']
    for name, row in rows.items():
        for corner in _row_corners(row):
            if not any(qualified == corner for _model_path, qualified in models):
                raise AdmissionRefusal('A05_MODEL_CORNER_NOT_QUALIFIED',
                                       name + ':' + corner)
        spec = _bound(project, row['spec'])
        topology = _bound(project, a04_blocks[name].get('topology'), 'A05_A04_TOPOLOGY_STALE')
        ir = _read(topology, 'A05_A04_TOPOLOGY_INVALID')
        if sorted(row['device_sizes'], key=lambda x: x['name']) != _geometry(ir):
            raise AdmissionRefusal('A05_EXPERT_SIZING_MISMATCH', name)
        inputs[str(spec)] = _sha(spec)
        inputs[str(topology)] = _sha(topology)
    corners = sorted({corner for row in rows.values() for corner in _row_corners(row)})
    for identity in uses:
        if (identity['config'] != _record(project, manifest_path)
                or identity['pdk'] != _record(project, pdk_path)
                or identity['deck'] != _record(project, requirements_path)
                or identity['corner'] != corners):
            raise AdmissionRefusal('A05_RUNTIME_SCOPE_MISMATCH', identity['use_id'])
    return {'manifest': manifest, 'pdk': pdk, 'requirements': requirements,
            'rows': rows, 'a02': a02, 'a04': a04_receipt, 'models': models,
            'sources': sources, 'inputs': inputs,
            'python': by_tool['python3']['executable']['path'],
            'ngspice': by_tool['ngspice']['executable']['path']}


def _before(project, context, prepared):
    require_launch_admission(project, 'flow109.A05', {'flow109_context': context})
    if operation_sources() != prepared['sources']:
        raise AdmissionRefusal('A05_OPERATION_SOURCE_CHANGED', 'before native launch')
    for path, digest in prepared['inputs'].items():
        if not Path(path).is_file() or _sha(path) != digest:
            raise AdmissionRefusal('A05_STALE_OR_MISSING_INPUT', path)


def _python(project, context, prepared, argv, log):
    _before(project, context, prepared)
    completed = subprocess.run(argv, cwd=project, capture_output=True, text=True)
    log.write_text(completed.stdout + completed.stderr, encoding='utf-8')
    return {'argv': argv, 'returncode': completed.returncode, 'log': _record(project, log)}


def _model_loads(project, sp, tb, expected_corners, models):
    text = sp.read_text(encoding='utf-8')
    tb_text = tb.read_text(encoding='utf-8')
    if not re.search(r'(?im)^\s*op\s*$', tb_text):
        raise AdmissionRefusal('A05_OPERATING_POINT_ANALYSIS_ABSENT', str(tb))
    loads = _LOAD.findall(text + '\n' + tb_text)
    if not loads:
        raise AdmissionRefusal('A05_MODEL_LOAD_ABSENT', str(sp))
    resolved = []
    for raw, corner in loads:
        if corner not in expected_corners:
            raise AdmissionRefusal('A05_MODEL_CORNER_MISMATCH', corner)
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (sp.parent / candidate).resolve()
        if not candidate.is_relative_to(project) or not candidate.is_file():
            raise AdmissionRefusal('A05_MODEL_PATH_UNBOUND', str(candidate))
        key = (str(candidate), corner)
        if key not in models or _sha(candidate) != models[key]['record']['sha256']:
            raise AdmissionRefusal('A05_MODEL_NOT_QUALIFIED_BY_A02', str(candidate))
        # A02 has already parsed, hash-bound and natively loaded the exact
        # selected section plus its transitive include closure.  Reuse that
        # closure instead of imposing the obsolete self-contained-file rule,
        # which rejects real foundry libraries such as IHP SG13G2.
        for dependency, record in models[key]['closure']:
            if _sha(dependency) != record['sha256']:
                raise AdmissionRefusal('A05_A02_MODEL_STALE', str(dependency))
            resolved.append(dependency)
    return sorted(set(resolved))


def _native(project, context, prepared, attempt, block, row, sp, tb, models):
    _before(project, context, prepared)
    libraries = _model_loads(project, sp, tb, set(_row_corners(row)), models)
    run_root = attempt / 'run'
    copies = []
    for source in [sp, tb, *libraries]:
        relative = source.relative_to(project)
        target = run_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(target, source.read_bytes())
        expected = prepared['inputs'].get(str(source))
        if expected is not None and _sha(target) != expected:
            raise AdmissionRefusal('A05_EXECUTED_INPUT_CHANGED', str(source))
        copies.append({'source': _record(project, source),
                       'executed_path': str(target.relative_to(project))})
    run_tb = run_root / tb.relative_to(project)
    argv = [prepared['ngspice'], '-b', str(run_tb)]
    _before(project, context, prepared)
    supervised = _watchdog.run_host_supervised(argv, cwd=str(run_tb.parent),
                                                stall_grace_s=60, hard_ceiling_s=120)
    completed = _watchdog.completed_process(argv, supervised)
    log = attempt / (block + '.ngspice.log')
    log.write_text(completed.stdout + completed.stderr, encoding='utf-8')
    values = {name: float(value)
              for line in log.read_text().splitlines() if _MEAS_LINE.match(line)
              for name, value in _MEAS_PAIR.findall(line)}
    failures = []
    if completed.returncode != 0 or supervised.outcome == 'stalled':
        failures.append('native ngspice did not complete successfully')
    lower = log.read_text(errors='replace').lower()
    if any(token in lower for token in ('fatal error', 'unknown subckt', 'could not find library file')):
        failures.append('native log contains model/deck load failure')
    for metric, threshold in row['operating_point_targets'].items():
        value = values.get(metric)
        if value is None or not math.isfinite(value):
            failures.append(metric + ': measurement absent or non-finite')
        elif not (float(threshold['min']) <= value <= float(threshold['max'])):
            failures.append(f'{metric}: {value} outside [{threshold["min"]}, {threshold["max"]}]')
    return {'argv': argv, 'returncode': completed.returncode, 'outcome': supervised.outcome,
            'supervision': supervised.supervision, 'log': _record(project, log),
            'executed_inputs': copies, 'measurements': values,
            'thresholds': row['operating_point_targets'], 'failures': failures,
            'verdict': 'PASS' if not failures else 'FAIL'}


def execute(project, context):
    project = Path(project).resolve()
    prepared = prepare(project, context)
    parent = project / 'reports/flow109/attempts'
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix='A05-', dir=parent))
    report = {'schema': SCHEMA, 'step_id': 'A05', 'native_step_id': 'flow109.A05',
              'component_status': 'NOT_MEASURED', 'flow109_acceptance': 'NOT_MEASURED',
              'context_sha256': context['context_sha256'], 'native_started': False,
              'operation_sources': prepared['sources'], 'inputs': prepared['inputs'],
              'executions': [], 'blocks': [],
              'unimplemented_obligations': [x['id'] for x in context['resolved_row']['obligations']],
              'gate_layers': {f'G{i}': 'NOT_MEASURED' for i in range(1, 10)},
              'qualification_scope': ('native operating-point component only; AC/noise/transient, '
                                      'PVT/statistics, full 109 qualification and benchmark PASS NOT_MEASURED')}
    for name, row in prepared['rows'].items():
        producer_json = attempt / (name + '-producer.json')
        run = _python(project, context, prepared,
            [prepared['python'], str(PRODUCER), str(project), '--block', name,
             '--pdk', prepared['pdk']['family'], '--json', str(producer_json)],
            attempt / (name + '-producer.log'))
        report['native_started'] = True
        report['executions'].append(run)
        produced = _read(producer_json, 'A05_PRODUCER_RECEIPT_INVALID')
        records = [x for x in produced.get('records', [])
                   if isinstance(x, dict) and x.get('block') == name]
        if run['returncode'] != 0 or len(records) != 1 or records[0].get('action') != 'emitted':
            report.update(component_status='NOT_MEASURED', reason='A05_NETLIST_NOT_EMITTED')
            break
        bdir = project / 'phase3/analog' / name
        sp, tb = bdir / (name + '.sp'), bdir / ('tb_' + name + '.sp')
        if not sp.is_file() or not tb.is_file():
            raise AdmissionRefusal('A05_SUBSTANTIVE_NETLIST_ABSENT', name)
        text = sp.read_text(encoding='utf-8', errors='replace')
        if (not re.search(r'(?im)^\s*\.subckt\s+' + re.escape(name) + r'\b', text)
                or not re.search(r'(?im)^\s*x\S+\s+', text)
                or not re.search(r'(?im)^\s*\.ends\s+' + re.escape(name) + r'\b', text)):
            raise AdmissionRefusal('A05_SUBSTANTIVE_NETLIST_ABSENT', name)
        gate_json = attempt / (name + '-gate.json')
        gate_run = _python(project, context, prepared,
            [prepared['python'], str(CONSUMER), str(project), '--block', name,
             '--json', str(gate_json)], attempt / (name + '-gate.log'))
        report['executions'].append(gate_run)
        gate = _read(gate_json, 'A05_CONSUMER_RECEIPT_INVALID')
        if gate_run['returncode'] != 0 or gate.get('verdict') not in ('PASS', 'PASS_STRUCTURE_ONLY'):
            report.update(component_status='FAIL', reason='A05_RETAINED_CONSUMER_FAILED')
            break
        native = _native(project, context, prepared, attempt, name, row, sp, tb, prepared['models'])
        report['blocks'].append({'block': name, 'component_status': native['verdict'],
                                 'netlist': _record(project, sp), 'testbench': _record(project, tb),
                                 'producer': produced, 'consumer': gate,
                                 'expert_sizing': row['device_sizes'], 'native_operating_point': native})
        if native['verdict'] != 'PASS':
            report.update(component_status='FAIL', reason='A05_NATIVE_OPERATING_POINT_FAILED')
            break
    else:
        report.update(component_status='PASS', reason='A05_EXPERT_SIZED_NATIVE_OP_COMPONENT_COMPLETE_ONLY')
    _before(project, context, prepared)
    if report['component_status'] == 'PASS':
        freeze = {'schema': SCHEMA, 'status': 'PASS', 'step_id': 'A05',
                  'context_sha256': context['context_sha256'], 'inputs': prepared['inputs'],
                  'blocks': report['blocks'], 'scope': report['qualification_scope']}
        write_json(project / FREEZE, freeze)
        report['freeze'] = _record(project, project / FREEZE)
    write_json(attempt / 'component.json', report)
    return report
