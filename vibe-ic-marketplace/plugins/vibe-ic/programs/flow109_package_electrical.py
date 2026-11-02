"""D67: BLOCKING checks of owner-provided, bounded passive package RLC models.

Reuses the existing SPICE subcircuit reader, top-port reader, ngspice model
consumer and metric operators. This does not extract or qualify a physical
package. Thermal, full-wave, raw IBIS and unspecified signal requirements
remain NOT_MEASURED. A bare-die C load from SDC/Liberty is not a package R/L.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _atomic_artefact import write_bytes, write_json, write_text
from _specrtl_common import parse_rtl_ports
import _watchdog
import flow109
from flow109_admission import AdmissionRefusal, require_launch_admission
import flow109_analog_model_check as model_check
from flow109_metric_acceptance import evaluate_operator, MetricRefusal, _identity_complete
from _pad_ring import parse_spice_subckts
from analog_a7_post_layout_emit import spice_number

SCHEMA = 'vibeic.flow109.package-electrical.v1'
INPUT = 'input/flow109/D67.json'
BOUNDS = 'requirements/package_electrical/package_rc_thermal_validity.json'
PORTS = 'adopted/package_electrical/package_model_ports_identity.json'
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
MEASURES = {'voltage_at_sample': ('V', 'find v(observe) at={sample_s}'),
            'maximum_voltage': ('V', 'max v(observe)'),
            'source_current_at_sample': ('A', 'find i(vdrive) at={sample_s}')}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _refuse(code, detail, *, failed=False):
    raise AdmissionRefusal('D67_' + code, str(detail),
                           status='FAIL' if failed else 'NOT_MEASURED')


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        _refuse('INPUT_ABSENT_OR_INVALID', path)
    if not isinstance(value, dict):
        _refuse('INPUT_ABSENT_OR_INVALID', path)
    return value


def _bound(project, record):
    if not isinstance(record, dict) or set(record) != {'path', 'sha256'}:
        _refuse('INPUT_UNBOUND', record)
    if not isinstance(record['path'], str) or not record['path']:
        _refuse('INPUT_UNBOUND', record)
    raw = project / record['path']
    if any(p.is_symlink() for p in (raw, *raw.parents)):
        _refuse('INPUT_SYMLINK_UNSUPPORTED', raw)
    path = raw.resolve()
    if not path.is_file() or _sha(path) != record['sha256']:
        _refuse('INPUT_STALE_OR_MISSING', path)
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project)
            else str(path), 'sha256': _sha(path)}


def operation_sources():
    names = ('flow109_package_electrical.py', '_pad_ring.py', 'analog_a7_post_layout_emit.py',
             'flow109_analog_model_check.py', '_specrtl_common.py', '_watchdog.py',
             '_atomic_artefact.py', 'flow109_metric_acceptance.py',
             'flow109.py', 'flow109_admission.py')
    return {'programs/' + name: _sha(HERE / name) for name in names}


def _number(value, *, positive=False):
    finite = isinstance(value, (int, float)) and not isinstance(value, bool)
    try:
        finite = finite and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or (positive and value <= 0):
        _refuse('INVALID_NUMBER', value)
    return value


def _approved(project, doc):
    approval = doc.get('approval', {})
    if (approval.get('status') != 'APPROVED'
            or approval.get('authority') != 'requirements_owner'
            or not isinstance(approval.get('approver'), str)
            or not approval['approver'].strip()):
        _refuse('REQUIREMENTS_NOT_APPROVED', approval)
    return _bound(project, approval.get('source_reference'))


def _model(path, case):
    text = path.read_text()
    parsed = parse_spice_subckts(text)
    lines = [line.strip() for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith('*')]
    if (set(parsed) != {case['subckt']} or len(lines) < 3
            or lines[0].lower().split()[:2] != ['.subckt', case['subckt'].lower()]
            or lines[-1].lower().split() not in
               (['.ends'], ['.ends', case['subckt'].lower()])):
        _refuse('MODEL_SCOPE_UNSUPPORTED', 'one self-contained passive subcircuit required')
    pins, cards = parsed[case['subckt']]
    # Keep the original closed subset: do not let a permissive CDL reader
    # discard directives, extra subcircuits, parameters or unknown tokens.
    if (lines[0].split()[2:] != pins
            or cards != [line.split() for line in lines[1:-1]]):
        _refuse('MODEL_SCOPE_UNSUPPORTED', 'exact formal SPICE cards required')
    if len(pins) != 3 or len(set(pins)) != 3 or not all(IDENT.fullmatch(p) for p in pins):
        _refuse('MODEL_PORTS_UNSUPPORTED', pins)
    components = {}
    units = {'R': 'ohm', 'L': 'H', 'C': 'F'}
    nodes = set()
    for words in cards:
        line = ' '.join(words)
        if (len(words) != 4 or not IDENT.fullmatch(words[0])
                or words[0][0].upper() not in units
                or not all(IDENT.fullmatch(node) for node in words[1:3])):
            _refuse('MODEL_SCOPE_UNSUPPORTED', line)
        token = words[3]
        # Validate one complete numeric token before consulting the existing
        # SPICE scale reader; prose suffixes and quoted expressions stay out.
        numeric = token.rstrip('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
        suffix = token[len(numeric):].lower()
        if (not numeric or set(numeric) - set('0123456789.eE+-')
                or suffix not in ('', 't', 'g', 'meg', 'k', 'm', 'u', 'n', 'p', 'f')
                or words[0] in components):
            _refuse('MODEL_PARAMETER_UNSUPPORTED', line)
        try:
            float(numeric)
        except ValueError:
            _refuse('MODEL_PARAMETER_UNSUPPORTED', line)
        value = _number(spice_number(token), positive=True)
        components[words[0]] = {'value': value, 'unit': units[words[0][0].upper()]}
        nodes.update(words[1:3])
    if not set(pins) <= nodes or {name[0].upper() for name in components} != {'R', 'L', 'C'}:
        _refuse('PHYSICAL_PACKAGE_RLC_ABSENT', 'C-only interface loads do not establish package R/L')
    if len(components) > 64:
        _refuse('MODEL_SCOPE_UNSUPPORTED', 'bounded lumped model supports at most 64 components')
    return pins, components


def prepare(project, context):
    if any(c in str(project) for c in ('\n', '\r', '"')):
        _refuse('PROJECT_PATH_UNSUPPORTED', project)
    if not isinstance(context, dict):
        _refuse('CONTEXT_MISMATCH', 'canonical D67 context required')
    context = flow109.validate_execution_context(context)
    if context.get('requested_step') != 'D67' or context.get('native_step_id') != 'flow109.D67':
        _refuse('CONTEXT_MISMATCH', 'selected Default D67 required')
    require_launch_admission(project, 'flow109.D67', {'flow109_context': context})
    if (context.get('runtime_tool_uses') is not None
            or context.get('qualification_registry') is not None):
        _refuse('QUALIFIED_ROUTE_UNSUPPORTED', 'this adapter proves only the declared model component')
    manifest = _read(project / INPUT)
    if manifest.get('schema') != SCHEMA:
        _refuse('INPUT_SCHEMA_UNSUPPORTED', manifest.get('schema'))
    requirements_path = _bound(project, manifest.get('requirements'))
    reference_path = _bound(project, manifest.get('port_reference'))
    if requirements_path != project / BOUNDS or reference_path != project / PORTS:
        _refuse('AUTHORITY_PATH_MISMATCH', 'canonical D67 bounds/reference required')
    requirements, reference = _read(requirements_path), _read(reference_path)
    owners = [_approved(project, doc) for doc in (requirements, reference)]
    _identity_complete(reference.get('reference_identity'))
    scope = requirements.get('scope', {})
    if not isinstance(scope, dict):
        _refuse('REQUIRED_SCOPE_UNSUPPORTED', scope)
    if (set(scope) != {'basis', 'thermal_required', 'full_wave_required', 'other_signal_requirements'}
            or scope.get('basis') != 'provided_lumped_rlc'
            or scope.get('thermal_required') is not False
            or scope.get('full_wave_required') is not False
            or scope.get('other_signal_requirements') != []):
        _refuse('REQUIRED_SCOPE_UNSUPPORTED', scope)
    netlist = _bound(project, requirements.get('netlist'))
    top = requirements.get('top')
    if not isinstance(top, str) or not IDENT.fullmatch(top):
        _refuse('TOP_PORT_IDENTITY_INVALID', top)
    parsed_top, ports = parse_rtl_ports(netlist.read_text(), top)
    if parsed_top != top or not ports or any(p.width != 1 for p in ports):
        _refuse('TOP_PORT_SCOPE_UNSUPPORTED', top)
    ports = {p.name: p.direction for p in ports}
    cases = requirements.get('cases')
    if not isinstance(cases, list) or not cases:
        _refuse('MODELS_MISSIONS_CORNERS_ABSENT', 'nonempty approved cases required')
    ids = [c.get('id') for c in cases if isinstance(c, dict)]
    if (len(ids) != len(cases) or not all(isinstance(v, str) for v in ids)
            or len(set(ids)) != len(ids)):
        _refuse('CASE_POPULATION_INVALID', ids)
    inputs = {str(p): _sha(p) for p in [project / INPUT, requirements_path,
                                      reference_path, netlist, *owners]}
    resolved, identity = [], {'top': top, 'netlist': requirements['netlist'], 'models': []}
    for case in cases:
        for key in ('id', 'corner', 'mission_mode', 'subckt'):
            if not isinstance(case.get(key), str) or not IDENT.fullmatch(case[key]):
                _refuse('CASE_IDENTITY_INVALID', key)
        model = _bound(project, case.get('model'))
        pins, components = _model(model, case)
        mapping = case.get('port_map')
        if not isinstance(mapping, dict) or set(mapping) != {'drive', 'observe', 'return'}:
            _refuse('PORT_MAP_ABSENT', case['id'])
        expected_keys = {'drive': {'model_port', 'design_port'},
                         'return': {'model_port', 'design_port'},
                         'observe': {'model_port', 'external_port'}}
        for role, keys in expected_keys.items():
            row = mapping[role]
            if not isinstance(row, dict) or set(row) != keys:
                _refuse('PORT_MAP_INVALID', role)
            if any(not isinstance(v, str) or not IDENT.fullmatch(v) for v in row.values()):
                _refuse('PORT_MAP_INVALID', role)
            if role != 'observe' and row['design_port'] not in ports:
                _refuse('PORT_IDENTITY_MISMATCH', row, failed=True)
        if (ports[mapping['drive']['design_port']] not in ('output', 'inout')
                or mapping['drive']['design_port'] == mapping['return']['design_port']
                or {r['model_port'] for r in mapping.values()} != set(pins)):
            _refuse('PORT_IDENTITY_MISMATCH', mapping, failed=True)
        mission = case.get('mission')
        if not isinstance(mission, dict) or set(mission) != {
                'waveform', 'initial_voltage_v', 'voltage_v', 'temperature_c',
                'rise_s', 'step_s', 'stop_s', 'sample_s'}:
            _refuse('MISSION_ABSENT_OR_UNSUPPORTED', case['id'])
        if mission['waveform'] != 'ideal_voltage_ramp_hold':
            _refuse('MISSION_SCOPE_UNSUPPORTED', mission['waveform'])
        for key, value in mission.items():
            if key != 'waveform':
                _number(value, positive=key not in ('temperature_c', 'initial_voltage_v'))
        if not (mission['rise_s'] < mission['sample_s'] < mission['stop_s']
                and mission['step_s'] <= mission['rise_s']
                and mission['stop_s'] / mission['step_s'] <= 10000):
            _refuse('MISSION_SCOPE_UNSUPPORTED', mission)
        limits, declared_units = case.get('limits'), case.get('units')
        if not isinstance(limits, dict) or not isinstance(declared_units, dict):
            _refuse('BOUNDS_ABSENT', case['id'])
        measurements = set(limits) - set(components)
        if (not set(components) < set(limits) or not measurements <= set(MEASURES)
                or set(limits) != set(declared_units)):
            _refuse('REQUIRED_METRIC_UNSUPPORTED_OR_ABSENT', case['id'])
        for name, bound in limits.items():
            if not isinstance(bound, dict) or not bound or set(bound) - {'min', 'max'}:
                _refuse('BOUNDS_ABSENT_OR_INVALID', name)
            for value in bound.values():
                _number(value)
            if bound.get('min', -math.inf) > bound.get('max', math.inf):
                _refuse('BOUNDS_INVALID', name)
            unit = components[name]['unit'] if name in components else MEASURES[name][0]
            if declared_units[name] != unit:
                _refuse('BOUNDS_UNIT_MISMATCH', name)
        item = {'id': case['id'], 'corner': case['corner'], 'mission_mode': case['mission_mode'],
                'subckt': case['subckt'], 'model': case['model'], 'ports': pins, 'port_map': mapping}
        identity['models'].append(item)
        inputs[str(model)] = _sha(model)
        resolved.append({'case': case, 'model': model, 'pins': pins,
                         'components': components, 'measurements': sorted(measurements)})
    if identity != reference.get('reference'):
        _refuse('PORT_IDENTITY_MISMATCH', 'native subcircuit/top mapping differs from adopted reference', failed=True)
    executable = shutil.which('ngspice')
    if not executable:
        _refuse('SELECTED_TOOL_ABSENT', 'ngspice')
    executable = str(Path(executable).resolve())
    return {'inputs': inputs, 'sources': operation_sources(), 'resolved': resolved,
            'identity': identity, 'reference': reference, 'requirements': requirements,
            'executable': executable, 'binary_sha256': _sha(executable)}


def _deck(item, model):
    case, pins = item['case'], item['pins']
    mission = case['mission']
    nodes = {case['port_map'][r]['model_port']: n for r, n in
             (('drive', 'drive'), ('observe', 'observe'), ('return', '0'))}
    lines = ['* D67 owner-provided lumped electrical component; no physical extraction',
             f'.include "{model}"', f'.temp {mission["temperature_c"]}',
             f'vdrive drive 0 PWL(0 {mission["initial_voltage_v"]} '
             f'{mission["rise_s"]} {mission["voltage_v"]} '
             f'{mission["stop_s"]} {mission["voltage_v"]})',
             'xpackage ' + ' '.join(nodes[p] for p in pins) + ' ' + case['subckt'],
             f'.tran {mission["step_s"]} {mission["stop_s"]}']
    for name in item['measurements']:
        lines.append('.meas tran ' + name + ' ' + MEASURES[name][1].format(**mission))
    return '\n'.join(lines + ['.end', ''])


def consume(project, context, report):
    """Normal D67 consumer: re-open current source, model, deck and native log."""
    project = Path(project).resolve()
    prepared = prepare(project, context)
    if (report.get('schema') != SCHEMA or report.get('step_id') != 'D67'
            or report.get('native_started') is not True):
        _refuse('NATIVE_RECEIPT_INVALID', 'executed D67 component required')
    if (report.get('context_sha256') != context['context_sha256']
            or report.get('inputs') != prepared['inputs']
            or report.get('operation_sources') != prepared['sources']
            or report.get('binary_sha256') != prepared['binary_sha256']
            or report.get('executable') != prepared['executable']):
        _refuse('CURRENT_EVIDENCE_MISMATCH', 'context/readset/source/tool changed')
    native = report.get('native')
    if not isinstance(native, list) or [r.get('id') for r in native] != [i['case']['id'] for i in prepared['resolved']]:
        _refuse('NATIVE_COVERAGE_MISMATCH', 'every approved model/mission/corner required')
    identity = {key: value for key, value in (
        ('producer', prepared['sources']), ('checker', prepared['sources']),
        ('tool_execution', {'binary': report['binary_sha256'], 'argv': [r['argv'] for r in native]}),
        ('consumed_inputs', prepared['inputs']), ('requirements', {'sha256': hashlib.sha256(json.dumps(
            prepared['requirements'], sort_keys=True).encode()).hexdigest()}),
        ('configuration', {'context_sha256': context['context_sha256']}))}
    port_status, port_reason = evaluate_operator('matches_adopted_reference',
        {'status': 'MEASURED', 'value': prepared['identity'], 'identity': identity},
        {'status': 'APPROVED', **prepared['reference']})
    checked = []
    for item, row in zip(prepared['resolved'], native):
        case = item['case']
        model, deck = _bound(project, row['model']), _bound(project, row['deck'])
        _bound(project, row['log'])
        if (_sha(model) != _sha(item['model']) or deck.read_text() != _deck(item, model)
                or row.get('argv') != [prepared['executable'], '-b', str(deck)]):
            _refuse('EXECUTED_MODEL_DECK_MISMATCH', case['id'])
        need = {'id': case['id'], 'device': case['subckt'], 'corner': case['corner'],
                'model': row['model'], 'deck': row['deck'],
                'required_measurements': item['measurements']}
        if row.get('outcome') in ('stalled', 'ceiling', 'aborted'):
            _refuse('NATIVE_NOT_MEASURED', row['outcome'])
        consumed = model_check.consume(project, {'required_smokes': [need]},
            {'smokes': [{**need, 'log': row['log'], 'returncode': row['returncode']}]})
        if consumed['verdict'] != 'PASS':
            _refuse('NATIVE_MODEL_CHECK_FAILED', consumed, failed=True)
        values = {**item['components'], **{name: {'value': value, 'unit': MEASURES[name][0]}
                  for name, value in consumed['smokes'][0]['measurements'].items()}}
        for name, value in values.items():
            status, reason = evaluate_operator('within_declared_bounds',
                {'status': 'MEASURED', **value, 'identity': identity},
                {'status': 'APPROVED', 'limits': case['limits'][name], 'unit': case['units'][name]})
            checked.append({'case': case['id'], 'corner': case['corner'],
                            'mission_mode': case['mission_mode'], 'metric': name,
                            **value, 'status': status, 'reason': reason})
    rc_status = 'PASS' if all(c['status'] == 'PASS' for c in checked) else 'FAIL'
    return {'status': 'PASS' if port_status == rc_status == 'PASS' else 'FAIL',
            'scope': prepared['requirements']['scope'],
            'package_model_ports_identity': {'status': port_status, 'reason': port_reason,
                                             'value': prepared['identity']},
            'package_rc_thermal_validity': {'status': rc_status, 'checks': checked,
                                           'thermal': 'NOT_REQUIRED_BY_APPROVED_SCOPE',
                                           'parameter_basis': 'provided_model_constants_not_extracted_package'},
            'physical_package_qualification': 'NOT_MEASURED'}


def execute(project, context):
    project = Path(project).resolve()
    report = {'schema': SCHEMA, 'step_id': 'D67', 'context_sha256': context.get('context_sha256') if isinstance(context, dict) else None,
              'component_status': 'NOT_MEASURED', 'native_started': False, 'native': [],
              'flow109_acceptance': 'NOT_MEASURED', 'whole_flow_acceptance': 'NOT_MEASURED',
              'metric_acceptance_status': 'NOT_MEASURED'}
    attempt = None
    try:
        prepared = prepare(project, context)
        report.update({key: prepared[key] for key in
                       ('inputs', 'executable', 'binary_sha256')})
        report['operation_sources'] = prepared['sources']
        parent = project / 'reports/flow109/attempts'
        parent.mkdir(parents=True, exist_ok=True)
        attempt = Path(tempfile.mkdtemp(prefix='D67-', dir=parent))
        for item in prepared['resolved']:
            if any(not Path(p).is_file() or _sha(p) != sha for p, sha in prepared['inputs'].items()):
                _refuse('INPUT_STALE_OR_MISSING', 'readset changed before native launch')
            require_launch_admission(project, 'flow109.D67', {'flow109_context': context})
            if _sha(prepared['executable']) != prepared['binary_sha256']:
                _refuse('EXECUTABLE_CHANGED', prepared['executable'])
            case = item['case']
            model = attempt / (case['id'] + '.model.sp')
            payload = item['model'].read_bytes()
            if hashlib.sha256(payload).hexdigest() != case['model']['sha256']:
                _refuse('INPUT_STALE_OR_MISSING', item['model'])
            write_bytes(model, payload)
            deck = attempt / (case['id'] + '.sp')
            write_text(deck, _deck(item, model))
            argv = [prepared['executable'], '-b', str(deck)]
            run = _watchdog.run_host_supervised(argv, cwd=str(attempt),
                                                stall_grace_s=15, hard_ceiling_s=30)
            completed = _watchdog.completed_process(argv, run)
            log = attempt / (case['id'] + '.ngspice.log')
            write_text(log, completed.stdout + completed.stderr)
            report['native_started'] = True
            report['native'].append({'id': case['id'], 'argv': argv,
                'model': _record(project, model), 'deck': _record(project, deck),
                'log': _record(project, log), 'returncode': completed.returncode,
                'outcome': run.outcome, 'supervision': run.supervision})
        report['metrics'] = consume(project, context, report)
        report['component_status'] = report['metrics']['status']
        report['metric_acceptance_status'] = report['metrics']['status']
        report['reason'] = 'D67_DECLARED_LUMPED_ELECTRICAL_' + report['component_status']
    except (AdmissionRefusal, MetricRefusal) as exc:
        report['component_status'] = getattr(exc, 'status', 'NOT_MEASURED')
        report['reason'] = exc.code
        report['detail'] = str(exc)
    if attempt is not None:
        write_json(attempt / 'component.json', report)
    destination = project / 'reports/flow109/components/D67.json'
    write_json(destination, report)
    return report
