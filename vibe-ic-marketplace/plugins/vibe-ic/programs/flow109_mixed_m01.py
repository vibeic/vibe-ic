"""Source-derived mixed interface facts and the native interface audit."""
from __future__ import annotations
import json
from pathlib import Path
import re

import analog_digital_interface_check as interface_check
import l21_doc_supply_rail_synth as rail_source
import spec_analog_iface_extract as iface_source
from _atomic_artefact import write_json

_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*\Z')


class NativeError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _read(path, code='M01_INPUT_INVALID'):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise NativeError(code, str(path)) from exc
    if not isinstance(value, dict):
        raise NativeError(code, str(path))
    return value


def _bound(project, value, code='M01_INPUT_MISSING'):
    raw = value.get('path') if isinstance(value, dict) else value
    if not isinstance(raw, str) or not raw:
        raise NativeError(code, str(value))
    path = Path(raw)
    path = path if path.is_absolute() else project / path
    path = path.resolve()
    if not path.is_relative_to(project) or not path.is_file():
        raise NativeError(code, str(path))
    return path


def _expanded_names(text):
    names = set(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', text))
    for match in re.finditer(r'\b([A-Za-z_]+)(\d+)\.\.([A-Za-z_]*)(\d+)\b', text):
        left, start, right, stop = match.groups()
        if right and right != left: continue
        lo, hi = int(start), int(stop)
        if 0 <= hi - lo <= 256: names.update(left + str(i) for i in range(lo, hi + 1))
    return names


def _basis(project, sources, value, subject):
    if not isinstance(value, list) or not value:
        raise NativeError('M01_SOURCE_BASIS_ABSENT', subject)
    quotes = []
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'source', 'line', 'quote'}
                or item.get('source') not in sources or type(item.get('line')) is not int
                or item['line'] < 1 or not isinstance(item.get('quote'), str)
                or not item['quote'].strip()):
            raise NativeError('M01_SOURCE_BASIS_INVALID', subject)
        lines = sources[item['source']].read_text(errors='replace').splitlines()
        if item['line'] > len(lines) or lines[item['line'] - 1].strip() != item['quote'].strip():
            raise NativeError('M01_SOURCE_BASIS_STALE', subject)
        quotes.append(item['quote'])
    return ' '.join(quotes)


def _mentions(text, token):
    token = str(token)
    if token in _expanded_names(text): return True
    return bool(re.search(r'(?i)(?<![A-Za-z0-9_])' + re.escape(token)
                          + r'(?:s|es)?(?![A-Za-z0-9_])', text))


def _field(project, sources, value, subject, *, vocabulary=None):
    if not isinstance(value, dict) or value.get('status') not in ('BOUND', 'NOT_MEASURED'):
        raise NativeError('M01_FIELD_INVALID', subject)
    text = _basis(project, sources, value.get('basis'), subject)
    if value['status'] == 'NOT_MEASURED':
        if set(value) != {'status', 'reason', 'basis'} or not str(value.get('reason', '')).strip():
            raise NativeError('M01_UNRESOLVED_FIELD_INVALID', subject)
        return None, {'status': 'NOT_MEASURED', 'reason': value['reason'], 'basis': value['basis']}
    if set(value) != {'status', 'value', 'basis'} or not isinstance(value.get('value'), str):
        raise NativeError('M01_BOUND_FIELD_INVALID', subject)
    selected = value['value'].strip()
    if not selected or vocabulary is not None and selected not in vocabulary:
        raise NativeError('M01_BOUND_FIELD_INVALID', subject)
    pin = re.escape(subject.rsplit(':', 1)[0])
    supply = r'\bsuppl(?:y|ies)(?:\s+pins?)?\s+(?:`?\w+`?(?:\s*\([^)]*\))?\s*[,/]\s*)*`?' + pin + r'\b'
    supply += r'|\b' + pin + r'`?\s+(?:is\s+)?(?:a\s+)?suppl(?:y|ies)\b'
    if not (_mentions(text, selected) or selected == 'power' and subject.endswith(':signal_type')
            and re.search(supply, text, re.I)):
        raise NativeError('M01_FIELD_NOT_SOURCE_BOUND', subject + ':' + selected)
    return selected, {'status': 'BOUND', 'value': selected, 'basis': value['basis']}


def _requirements(project, manifest, sources, derived_rails):
    path = _bound(project, manifest.get('requirements'))
    body = _read(path, 'M01_REQUIREMENTS_INVALID')
    rail_map = {row['rail']: row for row in derived_rails}
    domains, domain_names, domain_rails = [], set(), {}
    for row in body.get('domains', []):
        if (not isinstance(row, dict) or set(row) != {'name', 'rail', 'voltage', 'basis'}
                or not _ID.fullmatch(str(row.get('name', ''))) or row['name'] in domain_names):
            raise NativeError('M01_DOMAIN_INVALID', str(row))
        text = _basis(project, sources, row['basis'], 'domain:' + row['name'])
        if not _mentions(text, row['name']):
            raise NativeError('M01_DOMAIN_NOT_SOURCE_BOUND', row['name'])
        rail, rail_receipt = _field(project, sources, row['rail'], row['name'] + ':rail')
        volts, volt_receipt = _field(project, sources, row['voltage'], row['name'] + ':voltage')
        if rail is not None:
            actual = rail_map.get(rail)
            if actual is None:
                raise NativeError('M01_RAIL_NOT_SOURCE_DERIVED', row['name'] + ':' + rail)
            if volts is not None:
                try:
                    stated = float(re.sub(r'[^0-9.+-]', '', volts))
                except ValueError as exc:
                    raise NativeError('M01_VOLTAGE_INVALID', row['name']) from exc
                if stated != float(actual['voltage_v']):
                    raise NativeError('M01_RAIL_VOLTAGE_CONTRADICTION', row['name'])
        domains.append({'name': row['name'], 'rail': rail_receipt,
                        'voltage': volt_receipt, 'basis': row['basis']})
        domain_names.add(row['name'])
        domain_rails[row['name']] = rail
    if not domains:
        raise NativeError('M01_DOMAIN_ABSENT', str(path))

    pins, pin_names, unresolved = [], set(), []
    for row in body.get('pins', []):
        if (not isinstance(row, dict) or set(row) != {'name', 'basis', 'direction', 'signal_type',
                                                     'domain', 'rail', 'unit'}
                or not _ID.fullmatch(str(row.get('name', ''))) or row['name'] in pin_names):
            raise NativeError('M01_PIN_INVALID', str(row))
        text = _basis(project, sources, row['basis'], 'pin:' + row['name'])
        if row['name'] not in _expanded_names(text):
            raise NativeError('M01_PIN_NOT_SOURCE_BOUND', row['name'])
        fields, selected_fields = {}, {}
        for key, vocabulary in (
                ('direction', {'input', 'output', 'inout'}),
                ('signal_type', {'analog', 'digital', 'clock', 'power', 'reference'}),
                ('domain', None), ('rail', None), ('unit', None)):
            selected, receipt = _field(project, sources, row[key], row['name'] + ':' + key,
                                       vocabulary=vocabulary)
            if key == 'domain' and selected is not None and selected not in domain_names:
                raise NativeError('M01_PIN_DOMAIN_UNKNOWN', row['name'] + ':' + selected)
            if key == 'rail' and selected is not None and selected not in rail_map:
                raise NativeError('M01_PIN_RAIL_UNKNOWN', row['name'] + ':' + selected)
            fields[key] = receipt
            selected_fields[key] = selected
            if selected is None:
                unresolved.append(row['name'] + ':' + key)
        if (selected_fields['domain'] is not None and selected_fields['rail'] is not None
                and domain_rails[selected_fields['domain']] is not None
                and selected_fields['rail'] != domain_rails[selected_fields['domain']]):
            raise NativeError('M01_PIN_DOMAIN_RAIL_CONTRADICTION', row['name'])
        pins.append({'name': row['name'], 'basis': row['basis'], **fields})
        pin_names.add(row['name'])
    if not pins:
        raise NativeError('M01_PIN_ABSENT', str(path))

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
            raise NativeError('M01_RELATIONSHIP_INVALID', str(row))
        if row['kind'] != 'clock_output':
            raise NativeError('M01_RELATIONSHIP_KIND_UNSUPPORTED', str(row['kind']))
        text = _basis(project, sources, row['basis'], 'relationship:' + row['id'])
        members = row.get('inputs', []) + row.get('outputs', [])
        if (not isinstance(row.get('inputs'), list) or not isinstance(row.get('outputs'), list)
                or any(name not in pin_names or name not in _expanded_names(text) for name in members)
                or not _mentions(text, row['owner'])):
            raise NativeError('M01_RELATIONSHIP_NOT_SOURCE_BOUND', row['id'])
        if row['status'] == 'NOT_MEASURED':
            unresolved.append('relationship:' + row['id'])
        relationships.append(row)
        relationship_ids.add(row['id'])
    if not relationships:
        raise NativeError('M01_RELATIONSHIP_POPULATION_ABSENT', str(path))

    budgets = []
    for row in body.get('budgets', []):
        if (not isinstance(row, dict) or set(row) != {'name', 'value'}
                or not _ID.fullmatch(str(row.get('name', '')))):
            raise NativeError('M01_BUDGET_INVALID', str(row))
        selected, receipt = _field(project, sources, row['value'], 'budget:' + row['name'])
        if selected is None:
            unresolved.append('budget:' + row['name'])
        budgets.append({'name': row['name'], 'value': receipt})
    if not budgets:
        raise NativeError('M01_BUDGET_POPULATION_ABSENT', str(path))
    return path, body, {'domains': domains, 'pins': pins, 'relationships': relationships,
                        'budgets': budgets}, sorted(unresolved)


def execute(project, context):
    project = Path(project).resolve()
    docs = rail_source.doc_sources(project)
    text = '\n'.join(row[2] for row in docs)
    rails = rail_source.derive(project)['rails']
    extraction = iface_source.extract(text)
    audit = interface_check.run_audit(project)
    unresolved = []
    contract = None
    if context.get('requirements'):
        _, _, contract, unresolved = _requirements(project, context,
            {row[1]: row[0] for row in docs}, rails)
    status = ('NOT_MEASURED' if not rails or not extraction or audit.summary.get('skipped')
              or unresolved else 'PASS' if audit.passed else 'FAIL')
    report = {'component_status': status, 'source_rails': rails,
              'interface_extraction': extraction, 'contract': contract,
              'unresolved': unresolved, 'interface_audit': audit.summary,
              'findings': [vars(finding) for finding in audit.findings],
              'scope': 'source-derived interface and existing per-block interface audit'}
    write_json(project / 'reports/native_tools/mixed_interface.json', report)
    return report
