"""Recognize explicit named bit tables before summary-only field fallback.

Bind within a source document by BOTH declared register name and address.
Unsupported/ambiguous sections do not override another producer's fields.
No reset values, reserved-bit behavior, or access policy are inferred here.
"""
import re

_HEADING = re.compile(r'^#{1,6}\s+`*([A-Za-z_]\w*)`*\s+Register\s*\(\s*(0x[0-9a-f]+)\s*\)\s*Bit\s+Fields\s*$', re.I)
_BITS = re.compile(r'^(\d+)(?:\s*[-:]\s*(\d+))?$')


def _fields(lines):
    roles = None
    fields, spans, names = [], [], set()
    for line in lines:
        if not line.strip().startswith('|'):
            if roles is not None:
                break
            continue
        cells = [c.strip().strip('`*') for c in line.strip().strip('|').split('|')]
        if roles is None:
            headers = [c.lower() for c in cells]
            bit = [i for i, c in enumerate(headers) if c in {'bit', 'bits', '位元', '位'}]
            name = [i for i, c in enumerate(headers) if c in {'name', 'field', '名稱', '名称'}]
            desc = [i for i, c in enumerate(headers) if c in {'description', 'function', '功能', '描述'}]
            if len(bit) == len(name) == 1:
                roles = (bit[0], name[0], desc[0] if len(desc) == 1 else None)
            continue
        if all(re.fullmatch(r'[-: ]+', c) for c in cells):
            continue
        bi, ni, di = roles
        if max(bi, ni, di or 0) >= len(cells):
            return None
        match = _BITS.fullmatch(cells[bi])
        if not match:
            return None
        lo, hi = sorted((int(match[1]), int(match[2] or match[1])))
        if any(lo <= old_hi and hi >= old_lo for old_lo, old_hi in spans):
            return None
        spans.append((lo, hi))
        name = cells[ni]
        # This producer owns named fields only; reserved rows carry no new
        # scalar reset/mask or write policy. Preserve their span for overlap checks.
        if name.lower() in {'reserved', '保留'}:
            continue
        if not re.fullmatch(r'[A-Za-z_]\w*', name) or name in names:
            return None
        names.add(name)
        fields.append({'bits': str(lo) if lo == hi else f'{hi}:{lo}',
                       'field_name': name, 'description': cells[di] if di is not None else ''})
    return fields or None


def attach_named_fields(registers, extracted):
    """Attach only one unambiguous table to an existing same-source register."""
    declarations = {}
    for source, text in extracted.items():
        if not isinstance(text, str):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            heading = _HEADING.fullmatch(line.strip())
            if not heading:
                continue
            end = next((j for j in range(i + 1, len(lines))
                        if re.match(r'^#{1,6}\s', lines[j].strip())), len(lines))
            key = (f'input/docs/{source}', heading[1], int(heading[2], 16))
            declarations.setdefault(key, []).append(_fields(lines[i + 1:end]))
    for row in registers:
        if not isinstance(row, dict) or row.get('fields') or row.get('bits'):
            continue
        addr = row.get('address_int')
        if addr is None:
            try:
                addr = int(row.get('address', ''), 16)
            except (ValueError, TypeError):
                continue
        tables = declarations.get((row.get('evidence'), row.get('name'), addr), [])
        if not tables or any(table is None or table != tables[0] for table in tables):
            continue
        row['fields'] = [dict(field) for field in tables[0]]
