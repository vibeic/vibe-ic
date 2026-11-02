"""Strict pin-interface table protocol; free prose never authorizes a row.

L1 owns pin limits. L5 spec.input_conditions carries the same source row to
explicitly named consumers, separately from output performance targets.
"""
from copy import deepcopy
import math
import re

_COLUMNS = ('pin', 'condition', 'nominal', 'min', 'max', 'unit',
            'consumer_blocks', 'basis')
_NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z')
_HEADING = re.compile(r'^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$')


def _refuse(reason, detail):
    raise ValueError(f'PIN_INTERFACE_CONDITION_{reason}: {detail}')


# Header detection is deliberately container-agnostic. Prefixes/suffixes do
# not make a copied protocol header disappear from the declared source set.
_HEADER = re.compile(r'\|' + r'\|'.join(r'[ \t]*' + re.escape(c) + r'[ \t]*' for c in _COLUMNS) + r'\|', re.I)
_TEXT = re.compile(r'[^\W_][^<>`~|\t]*\Z')
_FORBIDDEN = re.compile(r'[<>`~]')


def _validate_fences(text):
    """Delimiter integrity only; this never decides table authority.

    Recognize delimiters after punctuation-only container prefixes without
    classifying block types. An unknown/mismatched delimiter refuses rather
    than making a following header live. Authority uses the allowlist below.
    """
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.fullmatch(r'([^\w`~]*)(`{3,}|~{3,})(.*)', line)
        if not marker:
            continue
        prefix, token, tail = marker.groups()
        container = ''.join(prefix.split())
        indentation_valid = bool(container) or ('\t' not in prefix and len(prefix) <= 3)
        if fence is not None:
            if (indentation_valid and container == fence[2] and token[0] == fence[0]
                    and len(token) >= fence[1] and not tail.strip(' \t')):
                fence = None
            else:
                _refuse('INVALID_FENCE', f'line {number}')
        elif indentation_valid and (token[0] != '`' or '`' not in tail):
            fence = (token[0], len(token), container, number)
    if fence is not None:
        _refuse('UNCLOSED_FENCE', f'line {fence[3]}')


def _document_sections(extracted):
    """Strict allowlist, not a Markdown block/context interpreter.

    Exactly one zero-indented declared heading and one bare protocol header
    may authorize a table. Its section admits blank lines and bare table rows
    only. To prove that this heading cannot inherit a hidden container, its
    document also admits only plain unindented preamble text, root headings,
    and bare unrelated table rows outside the section. Markup delimiters are
    forbidden there, not parsed. Other documents retain their own content,
    but any protocol header anywhere else is a named hidden-copy refusal.
    """
    documents = {doc: text.splitlines(keepends=True) for doc, text in (extracted or {}).items()}
    roots, headers = [], []
    for doc, text in (extracted or {}).items():
        _validate_fences(text)
        for index, raw in enumerate(documents[doc]):
            line = raw.rstrip('\r\n')
            heading = _HEADING.fullmatch(line)
            if heading and heading[2] == 'Pin interface conditions':
                roots.append((doc, index, len(heading[1])))
            for match in _HEADER.finditer(line):
                headers.append((doc, index, match.span()))
    if len(roots) > 1 or len(headers) > 1:
        _refuse('MULTIPLE_TABLES', str([(doc, line + 1) for doc, line, _ in headers]))
    if not roots:
        if headers:
            _refuse('HIDDEN_TABLE', str([(doc, line + 1) for doc, line, _ in headers]))
        return []
    doc, start, level = roots[0]
    lines = documents[doc]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        heading = _HEADING.fullmatch(lines[index].rstrip('\r\n'))
        if heading and len(heading[1]) <= level:
            end = index
            break
    if headers:
        owner, index, span = headers[0]
        raw = documents[owner][index].rstrip('\r\n')
        if owner != doc or not start < index < end or span != (0, len(raw.rstrip(' \t'))):
            _refuse('HIDDEN_TABLE', f'{owner}:{index + 1}')
    for index, raw in enumerate(lines):
        line = raw.rstrip('\r\n')
        if not line.strip() or index == start:
            continue
        bare = line == line.lstrip(' \t') and not _FORBIDDEN.search(line)
        row = bare and line.startswith('|') and line.rstrip(' \t').endswith('|')
        if start < index < end:
            if not row:
                _refuse('TABLE_MALFORMED', f'{doc}:{index + 1}: section permits only bare rows and blanks')
        elif not bare or not (row or _HEADING.fullmatch(line) or _TEXT.fullmatch(line)):
            _refuse('HIDDEN_TABLE', f'{doc}:{index + 1}: document outside the authority allowlist')
    return [(doc, start, end, lines)]


def without_condition_tables(extracted):
    """Keep protocol tables out of legacy free-text pin/block discovery.

    Preserve source line positions and never modify the caller's documents.
    A condition row must not declare its own pin or analog block.
    """
    sections = _document_sections(extracted)
    masked = {doc: text.splitlines(keepends=True) for doc, text in (extracted or {}).items()}
    for doc, start, end, _ in sections:
        for index in range(start, end):
            masked[doc][index] = '\n' if masked[doc][index].endswith('\n') else ''
    return {doc: ''.join(lines) for doc, lines in masked.items()}



def _cells(line):
    stripped = line.strip()
    if not stripped.startswith('|') or not stripped.endswith('|'):
        _refuse('TABLE_MALFORMED', f'expected pipe-delimited row: {line!r}')
    cells = [cell.strip() for cell in stripped[1:-1].split('|')]
    if len(cells) != len(_COLUMNS):
        _refuse('TABLE_MALFORMED', f'expected {len(_COLUMNS)} columns: {line!r}')
    return cells


def declared_pin_conditions(extracted, known_units):
    """Parse only the eight-column protocol, refusing ambiguous authority."""
    result = {}
    for doc, start, end, lines in _document_sections(extracted):
        numbered = [(i + 1, lines[i].rstrip('\r\n'))
                    for i in range(start + 1, end) if lines[i].strip()]
        if len(numbered) < 3:
            _refuse('TABLE_MALFORMED', f'{doc}:{start + 1}: missing table rows')
        if tuple(_cells(numbered[0][1])) != _COLUMNS:
            _refuse('TABLE_MALFORMED', f'{doc}: incorrect columns')
        if not all(re.fullmatch(r':?-{3,}:?', cell)
                   for cell in _cells(numbered[1][1])):
            _refuse('TABLE_MALFORMED', f'{doc}: invalid table separator')
        for line, raw in numbered[2:]:
            data = dict(zip(_COLUMNS, _cells(raw)))
            if not all(data.values()) or not all(
                    _NUMBER.fullmatch(data[k]) for k in ('nominal', 'min', 'max')):
                _refuse('TABLE_MALFORMED', f'{doc}:{line}: missing field or nonnumeric limit')
            values = {k: float(data[c]) for k, c in
                      (('typ', 'nominal'), ('min', 'min'), ('max', 'max'))}
            if not all(math.isfinite(v) for v in values.values()):
                _refuse('TABLE_MALFORMED', f'{doc}:{line}: nonfinite limit')
            if not values['min'] <= values['typ'] <= values['max']:
                _refuse('INVALID_RANGE', f'{doc}:{line}: {values}')
            if data['unit'] not in known_units:
                _refuse('UNKNOWN_UNIT', f'{doc}:{line}: {data["unit"]}')
            consumers = [] if data['consumer_blocks'] == '-' else [
                name.strip() for name in data['consumer_blocks'].split(',')]
            if any(not name or name == '-' for name in consumers):
                _refuse('TABLE_MALFORMED', f'{doc}:{line}: invalid consumer list')
            if len(consumers) != len(set(consumers)):
                _refuse('DUPLICATE_CONSUMER', f'{doc}:{line}: {consumers}')
            pin = data['pin']
            row = {'pin': pin, 'name': pin, 'kind': 'input_condition',
                   'condition': data['condition'], 'basis': data['basis'],
                   'unit': data['unit'], 'min_typ_max': values,
                   'consumer_blocks': consumers,
                   'evidence': {'doc': str(doc) if str(doc).startswith('input/')
                                else f'input/docs/{doc}', 'line': line, 'row': raw}}
            if pin in result:
                old = {k: v for k, v in result[pin].items() if k != 'evidence'}
                new = {k: v for k, v in row.items() if k != 'evidence'}
                _refuse('DUPLICATE_PIN' if old == new else 'CONFLICT',
                        f'{pin}: {result[pin]["evidence"]}, {row["evidence"]}')
            result[pin] = row
    return result


def project_pin_conditions(pins, extracted, known_units):
    rows = declared_pin_conditions(extracted, known_units)
    roster = {pin.get('name') for pin in pins}
    for name in rows:
        if name not in roster:
            _refuse('UNKNOWN_PIN', name)
    for pin in pins:
        if pin.get('name') in rows:
            pin.setdefault('electrical_specs', []).append(deepcopy(rows[pin['name']]))


def project_block_conditions(blocks, extracted, known_units, l1):
    rows = declared_pin_conditions(extracted, known_units)
    roster = {pin.get('name'): pin for pin in (l1 or {}).get('pin_table', [])}
    names = {block.get('name') for block in blocks}
    for pin, row in rows.items():
        if pin not in roster:
            _refuse('UNKNOWN_PIN', pin)
        if row not in roster[pin].get('electrical_specs', []):
            _refuse('L1_NOT_CURRENT', pin)
        for name in row['consumer_blocks']:
            if name not in names:
                _refuse('UNKNOWN_CONSUMER', name)
    for block in blocks:
        selected = [deepcopy(row) for row in rows.values()
                    if block.get('name') in row['consumer_blocks']]
        if selected:
            if not isinstance(block.get('spec'), dict):
                block['spec'] = {}
            block['spec']['input_conditions'] = selected
