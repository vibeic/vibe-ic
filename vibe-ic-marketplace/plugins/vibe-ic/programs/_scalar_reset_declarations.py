"""Explicit whole-register reset declarations, never proximity inference.

A None candidate denotes an explicit but unsupported/ambiguous declaration;
it blocks choosing another value. Empty candidates mean no declaration.
"""
import re


def _number(raw):
    raw = raw.strip()
    if raw.endswith('.'):
        raw = raw[:-1]
    raw = raw.strip().strip('`').replace('_', '')
    if not re.fullmatch(r'0x[0-9a-fA-F]+|0b[01]+|[0-9]+', raw):
        return None
    return hex(int(raw, 16 if raw.startswith('0x') else 2 if raw.startswith('0b') else 10))


def candidates(text, name, address=None):
    if not isinstance(text, str) or not isinstance(name, str) or not name:
        return set()
    # Only a declaration whose grammatical subject is the complete register
    # name can supply a scalar. A field suffix or intervening bit name cannot.
    subject = re.escape(name) + r'(?:\s+register)?\s+'
    declaration = re.compile(r'^' + subject +
        r'(?:is\s+)?(?:reset(?:\s+value)?|default(?:\s+value)?|power[- ]up(?:\s+value)?)'
        r'\s*(?:is\s+|to\s+|of\s+|[=:]\s*)?(?P<value>.+)$')
    clear = re.compile(r'^' + subject + r'(?:is\s+)?cleared\s+(?:by|on)\s+reset\.?$')
    values = set()
    columns = None
    for raw in text.splitlines():
        line = raw.strip().replace('**', '').replace('`', '')
        if line.startswith('|'):
            cells = [x.strip() for x in line.strip('|').split('|')]
            lower = [x.lower() for x in cells]
            names = [i for i, x in enumerate(lower) if x in {'name', 'register', '名稱', '名称'}]
            resets = [i for i, x in enumerate(lower) if x in {'reset', 'reset value', 'reset_value'}]
            addresses = [i for i, x in enumerate(lower) if x in {'address', 'addr', 'offset'}]
            if len(names) == len(resets) == 1:
                columns = (names[0], resets[0], addresses[0] if len(addresses) == 1 else None)
                continue
            if columns is None:
                continue
            ni, ri, ai = columns
            if max(ni, ri, ai or 0) >= len(cells) or cells[ni] != name:
                continue
            if address is not None:
                if ai is None:
                    continue
                addr = _number(cells[ai])
                if addr is None or int(addr, 16) != address:
                    continue
            values.add(_number(cells[ri]))
            continue
        columns = None
        # Separate complete declarations, but do not split decimal/identifier
        # punctuation or partial bit clauses into fabricated scalar subjects.
        for clause in re.split(r'[;；]', line):
            clause = re.sub(r'^[-*]\s+', '', clause.strip())
            if clear.fullmatch(clause):
                values.add('0x0')
                continue
            match = declaration.fullmatch(clause)
            if match:
                values.add(_number(match['value']))
    return values


def unique_value(values):
    return next(iter(values)) if len(values) == 1 and None not in values else None
