"""Flow109 M01 adapter over the inherited source extractors and interface gate.

This component is BLOCKING at its own boundary: contradictory or unbound
source claims refuse before a contract is adopted. Explicitly unresolved
source fields are retained as NOT_MEASURED and can never become defaults.
Component PASS is not M01 metric, topology, or whole-flow acceptance.
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
import analog_digital_interface_check as interface_check
import l21_doc_supply_rail_synth as rail_source
import spec_analog_iface_extract as iface_source

SCHEMA = 'vibeic.flow109.mixed-interface-contract.v1'
INPUT = 'input/flow109/M01.json'
FREEZE = 'adopted/mixed_signal_interface/interface_contract.json'
_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*\Z')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path, code='M01_INPUT_INVALID'):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise AdmissionRefusal(code, str(path)) from exc
    if not isinstance(value, dict):
        raise AdmissionRefusal(code, str(path))
    return value


def _bound(project, record, code='M01_STALE_OR_MISSING_INPUT'):
    if not isinstance(record, dict) or set(record) != {'path', 'sha256'}:
        raise AdmissionRefusal('M01_UNBOUND_INPUT', str(record))
    rel = Path(str(record.get('path', '')))
    if rel.is_absolute() or not rel.parts:
        raise AdmissionRefusal('M01_UNBOUND_INPUT', str(record))
    cursor = project
    for part in rel.parts:
        cursor /= part
        if cursor.is_symlink():
            raise AdmissionRefusal(code, 'symlinked path component: ' + str(cursor))
    path = (project / rel).resolve()
    if (not path.is_relative_to(project) or not path.is_file()
            or _sha(path) != record.get('sha256')):
        raise AdmissionRefusal(code, str(path))
    return path


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)), 'sha256': _sha(path)}


def operation_sources():
    from execution_provider_catalog import source_closure
    paths = source_closure({Path(__file__), Path(iface_source.__file__),
                            Path(rail_source.__file__), Path(interface_check.__file__)})
    paths.update((HERE / 'flow109.py', HERE / 'flow109_admission.py'))
    return {str(path.relative_to(HERE.parent)): _sha(path) for path in sorted(paths)}


def _expanded_names(text):
    names = set(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', text))
    for match in re.finditer(r'\b([A-Za-z_]+)(\d+)\.\.([A-Za-z_]*)(\d+)\b', text):
        left, start, right, stop = match.groups()
        if right and right != left:
            continue
        lo, hi = int(start), int(stop)
        if 0 <= hi - lo <= 256:
            names.update(left + str(i) for i in range(lo, hi + 1))
    return names


def _basis(project, sources, value, subject):
    if not isinstance(value, list) or not value:
        raise AdmissionRefusal('M01_SOURCE_BASIS_ABSENT', subject)
    quotes = []
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'source', 'line', 'quote'}
                or item.get('source') not in sources or type(item.get('line')) is not int
                or item['line'] < 1 or not isinstance(item.get('quote'), str)
                or not item['quote'].strip()):
            raise AdmissionRefusal('M01_SOURCE_BASIS_INVALID', subject)
        lines = sources[item['source']].read_text(errors='replace').splitlines()
        if item['line'] > len(lines) or lines[item['line'] - 1].strip() != item['quote'].strip():
            raise AdmissionRefusal('M01_SOURCE_BASIS_STALE', subject)
        quotes.append(item['quote'])
    return ' '.join(quotes)


def _mentions(text, token):
    token = str(token)
    if token in _expanded_names(text):
        return True
    return bool(re.search(r'(?i)(?<![A-Za-z0-9_])' + re.escape(token)
                          + r'(?:s|es)?(?![A-Za-z0-9_])', text))


def _field(project, sources, value, subject, *, vocabulary=None):
    if not isinstance(value, dict) or value.get('status') not in ('BOUND', 'NOT_MEASURED'):
        raise AdmissionRefusal('M01_FIELD_INVALID', subject)
    text = _basis(project, sources, value.get('basis'), subject)
    if value['status'] == 'NOT_MEASURED':
        if set(value) != {'status', 'reason', 'basis'} or not str(value.get('reason', '')).strip():
            raise AdmissionRefusal('M01_UNRESOLVED_FIELD_INVALID', subject)
        return None, {'status': 'NOT_MEASURED', 'reason': value['reason'],
                      'basis': value['basis']}
    if set(value) != {'status', 'value', 'basis'} or not isinstance(value.get('value'), str):
        raise AdmissionRefusal('M01_BOUND_FIELD_INVALID', subject)
    selected = value['value'].strip()
    if not selected or vocabulary is not None and selected not in vocabulary:
        raise AdmissionRefusal('M01_BOUND_FIELD_INVALID', subject)
    if not _mentions(text, selected):
        raise AdmissionRefusal('M01_FIELD_NOT_SOURCE_BOUND', subject + ':' + selected)
    return selected, {'status': 'BOUND', 'value': selected, 'basis': value['basis']}


def _requirements(project, manifest, sources, derived_rails):
    path = _bound(project, manifest.get('requirements'))
    body = _read(path, 'M01_REQUIREMENTS_INVALID')
    approval = body.get('source_authority') or {}
    if (body.get('schema') != SCHEMA or approval.get('status') != 'SOURCE_BOUND'
            or approval.get('authority') not in ('requirements_owner', 'fixture_source_owner')
            or not str(approval.get('source_reference', '')).strip()):
        raise AdmissionRefusal('M01_REQUIREMENTS_NOT_SOURCE_BOUND', str(path))
    rail_map = {row['rail']: row for row in derived_rails}
    domains, domain_names, domain_rails = [], set(), {}
    for row in body.get('domains', []):
        if (not isinstance(row, dict) or set(row) != {'name', 'rail', 'voltage', 'basis'}
                or not _ID.fullmatch(str(row.get('name', ''))) or row['name'] in domain_names):
            raise AdmissionRefusal('M01_DOMAIN_INVALID', str(row))
        text = _basis(project, sources, row['basis'], 'domain:' + row['name'])
        if not _mentions(text, row['name']):
            raise AdmissionRefusal('M01_DOMAIN_NOT_SOURCE_BOUND', row['name'])
        rail, rail_receipt = _field(project, sources, row['rail'], row['name'] + ':rail')
        volts, volt_receipt = _field(project, sources, row['voltage'], row['name'] + ':voltage')
        if rail is not None:
            actual = rail_map.get(rail)
            if actual is None:
                raise AdmissionRefusal('M01_RAIL_NOT_SOURCE_DERIVED', row['name'] + ':' + rail)
            if volts is not None:
                try:
                    stated = float(re.sub(r'[^0-9.+-]', '', volts))
                except ValueError as exc:
                    raise AdmissionRefusal('M01_VOLTAGE_INVALID', row['name']) from exc
                if stated != float(actual['voltage_v']):
                    raise AdmissionRefusal('M01_RAIL_VOLTAGE_CONTRADICTION', row['name'])
        domains.append({'name': row['name'], 'rail': rail_receipt,
                        'voltage': volt_receipt, 'basis': row['basis']})
        domain_names.add(row['name'])
        domain_rails[row['name']] = rail
    if not domains:
        raise AdmissionRefusal('M01_DOMAIN_ABSENT', str(path))

    pins, pin_names, unresolved = [], set(), []
    for row in body.get('pins', []):
        if (not isinstance(row, dict) or set(row) != {'name', 'basis', 'direction', 'signal_type',
                                                     'domain', 'rail', 'unit'}
                or not _ID.fullmatch(str(row.get('name', ''))) or row['name'] in pin_names):
            raise AdmissionRefusal('M01_PIN_INVALID', str(row))
        text = _basis(project, sources, row['basis'], 'pin:' + row['name'])
        if row['name'] not in _expanded_names(text):
            raise AdmissionRefusal('M01_PIN_NOT_SOURCE_BOUND', row['name'])
        fields, selected_fields = {}, {}
        for key, vocabulary in (
                ('direction', {'input', 'output', 'inout'}),
                ('signal_type', {'analog', 'digital', 'clock', 'power', 'reference'}),
                ('domain', None), ('rail', None), ('unit', None)):
            selected, receipt = _field(project, sources, row[key], row['name'] + ':' + key,
                                       vocabulary=vocabulary)
            if key == 'domain' and selected is not None and selected not in domain_names:
                raise AdmissionRefusal('M01_PIN_DOMAIN_UNKNOWN', row['name'] + ':' + selected)
            if key == 'rail' and selected is not None and selected not in rail_map:
                raise AdmissionRefusal('M01_PIN_RAIL_UNKNOWN', row['name'] + ':' + selected)
            fields[key] = receipt
            selected_fields[key] = selected
            if selected is None:
                unresolved.append(row['name'] + ':' + key)
        if (selected_fields['domain'] is not None and selected_fields['rail'] is not None
                and domain_rails[selected_fields['domain']] is not None
                and selected_fields['rail'] != domain_rails[selected_fields['domain']]):
            raise AdmissionRefusal('M01_PIN_DOMAIN_RAIL_CONTRADICTION', row['name'])
        pins.append({'name': row['name'], 'basis': row['basis'], **fields})
        pin_names.add(row['name'])
    if not pins:
        raise AdmissionRefusal('M01_PIN_ABSENT', str(path))

    relationships, relationship_ids = [], set()
    for row in body.get('relationships', []):
        expected = {'id', 'kind', 'inputs', 'outputs', 'owner', 'status', 'basis'}
        if isinstance(row, dict) and row.get('status') == 'NOT_MEASURED':
            expected.add('reason')
        if (not isinstance(row, dict) or set(row) != expected
                or not _ID.fullmatch(str(row.get('id', '')))
                or row.get('id') in relationship_ids
                or row.get('status') not in ('BOUND', 'NOT_MEASURED')
                or row.get('status') == 'NOT_MEASURED'
                and not str(row.get('reason', '')).strip()):
            raise AdmissionRefusal('M01_RELATIONSHIP_INVALID', str(row))
        if row['kind'] != 'clock_output':
            raise AdmissionRefusal('M01_RELATIONSHIP_KIND_UNSUPPORTED', str(row['kind']))
        text = _basis(project, sources, row['basis'], 'relationship:' + row['id'])
        members = row.get('inputs', []) + row.get('outputs', [])
        if (not isinstance(row.get('inputs'), list) or not isinstance(row.get('outputs'), list)
                or any(name not in pin_names or name not in _expanded_names(text) for name in members)
                or not _mentions(text, row['owner'])):
            raise AdmissionRefusal('M01_RELATIONSHIP_NOT_SOURCE_BOUND', row['id'])
        if row['status'] == 'NOT_MEASURED':
            unresolved.append('relationship:' + row['id'])
        relationships.append(row)
        relationship_ids.add(row['id'])
    if not relationships:
        raise AdmissionRefusal('M01_RELATIONSHIP_POPULATION_ABSENT', str(path))

    budgets = []
    for row in body.get('budgets', []):
        if (not isinstance(row, dict) or set(row) != {'name', 'value'}
                or not _ID.fullmatch(str(row.get('name', '')))):
            raise AdmissionRefusal('M01_BUDGET_INVALID', str(row))
        selected, receipt = _field(project, sources, row['value'], 'budget:' + row['name'])
        if selected is None:
            unresolved.append('budget:' + row['name'])
        budgets.append({'name': row['name'], 'value': receipt})
    if not budgets:
        raise AdmissionRefusal('M01_BUDGET_POPULATION_ABSENT', str(path))
    return path, body, {'domains': domains, 'pins': pins, 'relationships': relationships,
                        'budgets': budgets}, sorted(unresolved)


def _a04(project, manifest):
    record = manifest.get('a04_receipt')
    if isinstance(record, dict) and record.get('applicable') is False:
        if not str(record.get('reason', '')).strip():
            raise AdmissionRefusal('M01_A04_BINDING_INVALID', str(record))
        return None, {'status': 'NOT_MEASURED', 'reason': record['reason']}, []
    path = _bound(project, record, 'M01_A04_RECEIPT_STALE')
    receipt = _read(path, 'M01_A04_RECEIPT_INVALID')
    if (receipt.get('schema') != 'vibeic.flow109.analog-topology.v1'
            or receipt.get('step_id') != 'A04' or receipt.get('component_status') != 'PASS'
            or receipt.get('flow109_acceptance') != 'NOT_MEASURED'):
        raise AdmissionRefusal('M01_A04_RECEIPT_NOT_COMPONENT_PASS', str(path))
    bound, names = [_record(project, path)], []
    freeze_path = _bound(project, receipt.get('freeze'), 'M01_A04_RECEIPT_STALE')
    freeze = _read(freeze_path, 'M01_A04_RECEIPT_INVALID')
    if freeze.get('status') != 'PASS' or freeze.get('step_id') != 'A04':
        raise AdmissionRefusal('M01_A04_RECEIPT_INVALID', str(freeze_path))
    bound.append(_record(project, freeze_path))
    for row in receipt.get('blocks', []):
        if not isinstance(row, dict) or row.get('component_status') != 'PASS':
            raise AdmissionRefusal('M01_A04_BLOCK_INVALID', str(row))
        topology = _bound(project, row.get('topology'), 'M01_A04_RECEIPT_STALE')
        if _read(topology).get('block_type') != row.get('block'):
            raise AdmissionRefusal('M01_A04_BLOCK_INVALID', str(topology))
        names.append(row['block'])
        bound.append(_record(project, topology))
    if not names or len(names) != len(set(names)):
        raise AdmissionRefusal('M01_A04_BLOCK_INVALID', str(names))
    return path, {'status': 'BOUND_COMPONENT_ONLY', 'receipt': _record(project, path),
                  'freeze': _record(project, freeze_path), 'blocks': sorted(names),
                  'independent_review': 'PENDING'}, bound


def prepare(project, context):
    context = validate_execution_context(context)
    if context['requested_step'] != 'M01' or context['native_step_id'] != 'flow109.M01':
        raise Flow109Error('FLOW109_M01_WRONG_COMPONENT', str(context['requested_step']))
    require_launch_admission(project, 'flow109.M01', {'flow109_context': context})
    sources_id = operation_sources()
    uses = context['runtime_tool_uses']
    if (len(uses) != 1 or uses[0]['tool_id'] != 'python3'
            or (uses[0].get('semantics') or {}).get('operation_sources') != sources_id):
        raise AdmissionRefusal('QUALIFICATION_OPERATION_SOURCE_MISMATCH',
                               'M01 must bind inherited producers, consumer and adapter')
    manifest_path = project / INPUT
    manifest = _read(manifest_path)
    if manifest.get('schema') != SCHEMA or manifest.get('basis') != 'source_bound_interface_facts':
        raise AdmissionRefusal('M01_BASIS_UNSUPPORTED', str(manifest.get('basis')))
    declared_sources = manifest.get('sources')
    if not isinstance(declared_sources, dict) or set(declared_sources) != {'L1', 'L5', 'L9'}:
        raise AdmissionRefusal('M01_SOURCE_POPULATION_INVALID', str(declared_sources))
    sources = {name: _bound(project, record) for name, record in declared_sources.items()}
    if len(set(sources.values())) != 3:
        raise AdmissionRefusal('M01_SOURCE_POPULATION_INVALID', 'three distinct layers required')
    rails = rail_source.derive(project, [str(path.relative_to(project)) for path in sources.values()])['rails']
    if not rails:
        raise AdmissionRefusal('M01_SOURCE_RAILS_ABSENT', 'no source-stated rail/voltage table')
    req_path, requirements, contract, unresolved = _requirements(project, manifest, sources, rails)
    a04_path, a04, a04_bound = _a04(project, manifest)
    owners = {r['owner'] for r in contract['relationships'] if r['status'] == 'BOUND'}
    if owners and a04_path is None:
        raise AdmissionRefusal('M01_A04_BINDING_REQUIRED', str(sorted(owners)))
    if a04_path is not None and not owners <= set(a04['blocks']):
        raise AdmissionRefusal('M01_A04_OWNER_MISMATCH', str(sorted(owners - set(a04['blocks']))))
    extraction = iface_source.extract('\n'.join(path.read_text(errors='replace') for path in sources.values()))
    if not extraction:
        raise AdmissionRefusal('M01_INHERITED_INTERFACE_EXTRACTION_EMPTY', str(manifest_path))
    identity = uses[0]
    if (identity['config'] != _record(project, manifest_path)
            or identity['deck'] != _record(project, req_path)
            or identity['pdk'] != {'applicable': False, 'reason': 'source interface contract is PDK-independent'}
            or identity['corner'] != ['source']):
        raise AdmissionRefusal('M01_RUNTIME_SCOPE_MISMATCH', identity['use_id'])
    inputs = {str(path): _sha(path) for path in [manifest_path, req_path, *sources.values()]}
    for record in a04_bound:
        inputs[str(project / record['path'])] = record['sha256']
    return {'manifest': manifest, 'contract': contract, 'unresolved': unresolved,
            'rails': rails, 'extraction': extraction, 'a04': a04, 'inputs': inputs,
            'sources': sources_id, 'binary': identity['executable']['path']}


def _before(project, context, prepared):
    require_launch_admission(project, 'flow109.M01', {'flow109_context': context})
    if operation_sources() != prepared['sources']:
        raise AdmissionRefusal('M01_OPERATION_SOURCE_CHANGED', 'before consumer')
    for path, digest in prepared['inputs'].items():
        if not Path(path).is_file() or _sha(path) != digest:
            raise AdmissionRefusal('M01_STALE_OR_MISSING_INPUT', path)


def _consumer(project, context, prepared, attempt):
    if prepared['unresolved']:
        return {'verdict': 'NOT_MEASURED', 'reason': 'M01_SOURCE_FACTS_UNRESOLVED',
                'unresolved': prepared['unresolved']}, None
    projection = attempt / 'consumer-project'
    # The inherited checker owns the canonical Phase-3 analog read path.  This
    # attempt-local projection is a consumer input, never a second contract.
    block = projection / 'phase3/analog/interface_contract'
    block.mkdir(parents=True)
    write_json(projection / 'phase3/analog/analog_block_list.json',
               {'blocks': [{'name': 'interface_contract'}]})
    pins = []
    for row in prepared['contract']['pins']:
        pins.append({'name': row['name'], 'direction': row['direction']['value'],
                     'type': row['signal_type']['value'],
                     'voltage_domain': row['domain']['value']})
    write_json(block / 'interface.json', {'pins': pins})
    output = attempt / 'inherited-consumer.json'
    argv = [prepared['binary'], str(Path(interface_check.__file__)), str(projection),
            '--json', str(output)]
    _before(project, context, prepared)
    completed = subprocess.run(argv, cwd=project, capture_output=True, text=True)
    log = attempt / 'inherited-consumer.log'
    log.write_text(completed.stdout + completed.stderr)
    result = _read(output, 'M01_CONSUMER_RECEIPT_INVALID')
    verdict = 'PASS' if completed.returncode == 0 and result.get('passed') is True else 'FAIL'
    return {'verdict': verdict, 'program': 'analog_digital_interface_check',
            'receipt': result}, {'argv': argv, 'returncode': completed.returncode,
                                 'log': _record(project, log)}


def execute(project, context):
    project = Path(project).resolve()
    prepared = prepare(project, context)
    parent = project / 'reports/flow109/attempts'
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix='M01-', dir=parent))
    consumer, execution = _consumer(project, context, prepared, attempt)
    contract = {'schema': SCHEMA, 'step_id': 'M01', 'context_sha256': context['context_sha256'],
                'sources': prepared['manifest']['sources'], 'inputs': prepared['inputs'],
                'pins': prepared['contract']['pins'], 'domains': prepared['contract']['domains'],
                'relationships': prepared['contract']['relationships'],
                'budgets': prepared['contract']['budgets'], 'source_rails': prepared['rails'],
                'inherited_extraction': prepared['extraction'], 'a04_binding': prepared['a04'],
                'unresolved': prepared['unresolved'],
                'scope': 'interface component only; topology and Flow109 acceptance NOT_MEASURED'}
    status = consumer['verdict']
    report = {**contract, 'native_step_id': 'flow109.M01', 'component_status': status,
              'flow109_acceptance': 'NOT_MEASURED', 'consumer': consumer,
              'execution': execution, 'operation_sources': prepared['sources'],
              'metric_acceptance_status': 'UNIMPLEMENTED',
              'unimplemented_obligations': [o['id'] for o in context['resolved_row']['obligations']],
              'gate_layers': {f'G{i}': 'NOT_MEASURED' for i in range(1, 10)}}
    _before(project, context, prepared)
    if status in ('PASS', 'NOT_MEASURED'):
        target = project / FREEZE
        if target.is_file() and json.loads(target.read_text()) != contract:
            raise AdmissionRefusal('M01_IMMUTABLE_RECEIPT_CONFLICT', str(target))
        write_json(target, contract)
        report['freeze'] = _record(project, target)
    write_json(attempt / 'component.json', report)
    return report
