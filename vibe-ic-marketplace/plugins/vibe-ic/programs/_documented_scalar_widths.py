"""Carry explicit scalar register widths without inferring field semantics."""
import re


def attach_documented_scalar_widths(registers, extracted):
    """Bind one unambiguous width by source, register name and address.

    Existing typed widths and arrays remain authoritative. Unsupported or
    contradictory table cells do not supply a width; no bus-width default.
    """
    aliases = {
        'address': {'address', 'addr', 'offset', '位址(hex)', '地址'},
        'name': {'name', 'register', '名稱', '名称'},
        'width': {'width', 'width(bits)', '寬度', '宽度'},
    }
    declarations = {}
    for source, text in extracted.items():
        if not isinstance(text, str):
            continue
        columns = None
        for line_no, line in enumerate(text.splitlines(), 1):
            if not line.strip().startswith('|'):
                columns = None
                continue
            cells = [c.strip().strip('`*') for c in line.strip().strip('|').split('|')]
            keys = [c.lower().replace(' ', '') for c in cells]
            found = {k: [i for i, c in enumerate(keys) if c in names]
                     for k, names in aliases.items()}
            if any(found.values()):
                columns = ({k: positions[0] for k, positions in found.items()}
                           if all(len(v) == 1 for v in found.values()) else None)
                continue
            if columns is None or len(cells) <= max(columns.values()):
                continue
            address, name, width = (cells[columns[k]] for k in ('address', 'name', 'width'))
            if not re.fullmatch(r'0x[0-9a-fA-F]+', address) or not re.fullmatch(r'[A-Za-z_]\w*', name):
                continue
            value = int(width) if re.fullmatch(r'[0-9]+', width) and int(width) > 0 else None
            key = (f'input/docs/{source}', name, int(address, 16))
            declarations.setdefault(key, []).append((value, line_no))
    for reg in registers:
        if reg.get('array') or reg.get('width_bits') is not None:
            continue
        key = (reg.get('evidence'), reg.get('name'), reg.get('address_int'))
        records = declarations.get(key, [])
        values = {value for value, _ in records}
        if len(values) != 1 or None in values:
            continue
        reg['width_bits'] = next(iter(values))
        reg['width_bits_source'] = {'kind': 'documented_scalar_width',
                                    'path': key[0], 'lines': [n for _, n in records]}
