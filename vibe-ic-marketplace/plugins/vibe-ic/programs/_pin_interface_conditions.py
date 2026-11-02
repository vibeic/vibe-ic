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
_HEADING = re.compile(r'^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$')


def _refuse(reason, detail):
    raise ValueError(f'PIN_INTERFACE_CONDITION_{reason}: {detail}')


def _sections(text):
    """One boundary model for masking and parsing the strict protocol.

    Fences use CommonMark's character, length, indentation and trailing-space
    rules. In a protocol-bearing document, ambiguous/unclosed fences refuse;
    hidden or quoted protocol copies never become authority or silent skips.
    Unrelated documents remain outside this protocol's validation scope.
    """
    lines = text.splitlines(keepends=True)
    sections = []
    start = level = None
    fence = None
    errors = []
    protocol = False
    for index, raw in enumerate(lines):
        line = raw.rstrip('\r\n')
        # Blockquotes are containers, not top-level protocol authority. Strip
        # their markers only to detect a forbidden copy, never to parse rows.
        unquoted = line
        quoted = False
        while re.match(r'^ {0,3}>', unquoted):
            unquoted = re.sub(r'^ {0,3}>[ \t]?', '', unquoted, count=1)
            quoted = True
        heading = _HEADING.fullmatch(unquoted)
        title = heading[2] if heading else None
        header = tuple(c.strip() for c in unquoted.strip().strip('|').split('|'))
        candidate = title == 'Pin interface conditions' or header == _COLUMNS
        if candidate:
            protocol = True
            if quoted or fence is not None:
                errors.append(('HIDDEN_TABLE', index + 1))
        if quoted:
            continue
        marker = re.fullmatch(r'([ \t]*)(`{3,}|~{3,})(.*)', line)
        fence_indent = marker is not None and '\t' not in marker[1] and len(marker[1]) <= 3
        if fence is not None:
            if marker:
                _, token, tail = marker.groups()
                if fence_indent and token[0] == fence[0] and len(token) >= fence[1] and not tail.strip(' \t'):
                    fence = None
                else:
                    # CommonMark keeps this line inside the fence. The strict
                    # authority protocol additionally refuses that ambiguity.
                    errors.append(('INVALID_FENCE', index + 1))
            continue
        if marker and fence_indent:
            _, token, tail = marker.groups()
            # Backticks are forbidden in a backtick fence's info string.
            if token[0] != '`' or '`' not in tail:
                fence = (token[0], len(token), index + 1)
            continue
        if heading:
            depth = len(heading[1])
            if start is not None and depth <= level:
                sections.append((start, index, lines))
                start = level = None
            if title == 'Pin interface conditions':
                if start is not None:
                    _refuse('TABLE_MALFORMED', 'nested condition section')
                start, level = index, depth
    if protocol:
        if errors:
            reason, line = errors[0]
            _refuse(reason, f'line {line}: hidden or ambiguous protocol boundary')
        if fence is not None:
            _refuse('UNCLOSED_FENCE', f'line {fence[2]}')
    if start is not None:
        sections.append((start, len(lines), lines))
    return sections


def _document_sections(extracted):
    """Exactly one authoritative table section in the entire document set."""
    sections = []
    for doc, text in (extracted or {}).items():
        sections.extend((doc, start, end, lines) for start, end, lines in _sections(text))
    if len(sections) > 1:
        _refuse('MULTIPLE_TABLES', str([(doc, start + 1) for doc, start, _, _ in sections]))
    return sections


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
