"""Lossless DEF FILLS -> native LibreLane/KLayout stream bridge.

Derives missing FILL purposes from immutable producer rules and a PDK map.
Never edits GDS, the PDK map or fill-rule values. Ambiguous masks/OPC/grid
representations refuse. Geometry is compared per cell without flattening.
This producer/consumer component alone is not final finishing or RCX signoff.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import ast
import json
from pathlib import Path
import re
import shlex
import sys
import tempfile

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from librelane_contract import Refusal

SCHEMA = 'vibeic.fill-stream.v1'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _record(project, path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(project)) if path.is_relative_to(project) else str(path),
            'sha256': _sha(path)}


def fill_records(def_file):
    text = Path(def_file).read_text()
    units = re.findall(r'\bUNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;', text)
    top = re.findall(r'^\s*DESIGN\s+(\S+)\s*;', text, re.M)
    sections = list(re.finditer(r'(?ms)^\s*FILLS\s+(\d+)\s*;\s*\n(.*?)^\s*END FILLS\s*\n', text))
    if len(units) != 1 or len(top) != 1 or len(sections) > 1:
        raise Refusal('FILL_STREAM_DEF_UNSUPPORTED', 'unique units/design/fill section required')
    shapes = []
    bare = text
    if sections:
        section = sections[0]
        records = [row.strip() for row in section[2].split(';') if row.strip()]
        for row in records:
            m = re.fullmatch(r'-\s+LAYER\s+([A-Za-z_][A-Za-z0-9_]*)\s+RECT\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)', row)
            if not m:
                raise Refusal('FILL_STREAM_MASK_OR_SHAPE_UNSUPPORTED', row)
            name, *coords = m.groups()
            coords = list(map(int, coords))
            if coords[0] >= coords[2] or coords[1] >= coords[3]:
                raise Refusal('FILL_STREAM_INVALID_RECTANGLE', row)
            shapes.append({'layer': name, 'rect': coords})
        if len(shapes) != int(section[1]):
            raise Refusal('FILL_STREAM_CENSUS_MISMATCH', str(def_file))
        bare = text[:section.start()] + text[section.end():]
    return {'units': int(units[0]), 'top': top[0], 'shapes': shapes, 'bare_def': bare}


def _map_entries(text):
    result = {}
    for line in text.splitlines():
        words = shlex.split(line, comments=True)
        if not words or words[0] == 'NAME':
            continue
        if len(words) != 4 or not words[2].isdigit() or not words[3].isdigit():
            raise Refusal('FILL_STREAM_MAP_GRAMMAR_UNSUPPORTED', line)
        for purpose in words[1].split(','):
            result.setdefault((words[0], purpose), set()).add((int(words[2]), int(words[3])))
    return result


def derive_map(base_map, rules_file, filled_def, output):
    """Existing explicit FILL authority is valid without any 109 step ID."""
    parsed = fill_records(filled_def)
    entries = _map_entries(Path(base_map).read_text())
    rules = json.loads(Path(rules_file).read_text()) if rules_file is not None else None
    by_name = {}
    if rules is not None:
        if not isinstance(rules.get('layers'), dict):
            raise Refusal('FILL_STREAM_RULES_UNSUPPORTED', str(rules_file))
        for row in rules['layers'].values():
            name = row.get('name')
            if not name or name in by_name:
                raise Refusal('FILL_STREAM_RULES_AMBIGUOUS', str(name))
            by_name[name] = row
    mapping, added = {}, []
    for name in sorted({shape['layer'] for shape in parsed['shapes']}):
        existing = entries.get((name, 'FILL'), set())
        if len(existing) > 1:
            raise Refusal('FILL_STREAM_MAP_AMBIGUOUS', name)
        if rules is not None:
            row = by_name.get(name)
            if not row or row.get('opc') or not isinstance(row.get('non-opc'), dict):
                raise Refusal('FILL_STREAM_RULE_AUTHORITY_ABSENT', name)
            number, datatype, drawn = row.get('layer'), row['non-opc'].get('datatype'), row.get('datatype')
            if any(type(value) is not int or value < 0 or value > 65535 for value in (number, datatype, drawn)):
                raise Refusal('FILL_STREAM_MASK_OR_DATATYPE_AMBIGUOUS', name)
            routing = entries.get((name, 'NET'), set()) | entries.get((name, 'SPNET'), set())
            if routing != {(number, drawn)}:
                raise Refusal('FILL_STREAM_RULE_MAP_MISMATCH', name)
            pair = (number, datatype)
            if existing and existing != {pair}:
                raise Refusal('FILL_STREAM_RULE_MAP_MISMATCH', name + ' FILL')
        elif existing:
            pair = next(iter(existing))
        else:
            raise Refusal('FILL_STREAM_RULE_AUTHORITY_ABSENT', name)
        mapping[name] = list(pair)
        if not existing:
            added.append(f'{name} FILL {pair[0]} {pair[1]}')
    text = Path(base_map).read_text()
    if added:
        text += '\n# Derived FILL purposes; original routing/pin/via entries retained.\n' + '\n'.join(added) + '\n'
    Path(output).write_text(text)
    return {'layer_map': mapping, 'fill_count': len(parsed['shapes']),
            'added_purposes': added, 'base_map_sha256': _sha(base_map),
            'rules_sha256': _sha(rules_file) if rules_file is not None else None,
            'derived_map_sha256': _sha(output)}


def native_script():
    from librelane.common import get_script_dir
    return Path(get_script_dir()) / 'klayout/stream_out.py'





def _instances(cell):
    return sorted((i.cell.name, i.cplx_trans.to_s(), i.a.to_s(), i.b.to_s(), i.na, i.nb)
                  for i in cell.each_inst())


def _expected_regions(parsed, dbu, mapping):
    import klayout.db as db
    expected = {}
    for shape in parsed['shapes']:
        if shape['layer'] not in mapping:
            raise Refusal('FILL_STREAM_MAPPING_MISSING', shape['layer'])
        pair = tuple(mapping[shape['layer']])
        coords = [Fraction(n, parsed['units']) / Fraction(str(dbu)) for n in shape['rect']]
        if any(n.denominator != 1 for n in coords):
            raise Refusal('FILL_STREAM_GRID_UNREPRESENTABLE', str(shape))
        expected.setdefault(pair, db.Region()).insert(db.Box(*map(int, coords)))
    return expected


def _native_fill_child(bare, filled, parsed, mapping):
    """Prove a reader-created child contains only this DEF's declared fills."""
    import klayout.db as db
    original = {c.name for c in bare.each_cell()}
    added = {c.name for c in filled.each_cell()} - original
    if not parsed['shapes']:
        if added:
            raise Refusal('FILL_STREAM_HIERARCHY_CHANGED', 'unexpected new cells without fills')
        return set(), {}
    if not added:
        raise Refusal('FILL_STREAM_FILL_GEOMETRY_MISMATCH', 'declared fill cell missing')
    if len(added) != 1:
        raise Refusal('FILL_STREAM_NATIVE_CELL_UNSUPPORTED', str(sorted(added)))
    name = next(iter(added))
    child = filled.cell(name)
    if list(child.each_inst()):
        raise Refusal('FILL_STREAM_NATIVE_CELL_UNSUPPORTED', 'fill cell contains hierarchy')
    expected = _expected_regions(parsed, filled.dbu, mapping)
    pairs = {(i.layer, i.datatype) for i in filled.layer_infos()} | set(expected)
    for pair in pairs:
        index = filled.find_layer(*pair)
        shapes = child.shapes(index) if index is not None else None
        if shapes is not None and any(not (v.is_box() or v.is_polygon() or v.is_path()) for v in shapes.each()):
            raise Refusal('FILL_STREAM_NATIVE_CELL_UNSUPPORTED', 'fill cell has non-geometric content')
        region = db.Region(shapes) if shapes is not None else db.Region()
        if not (region ^ expected.get(pair, db.Region())).is_empty():
            raise Refusal('FILL_STREAM_FILL_GEOMETRY_MISMATCH', name + str(pair))
    top = filled.cell(parsed['top'])
    refs = [i for c in filled.each_cell() for i in c.each_inst() if i.cell.name == name]
    local_refs = [i for i in top.each_inst() if i.cell.name == name]
    if (len(refs) != 1 or len(local_refs) != 1 or local_refs[0].is_regular_array()
            or local_refs[0].cplx_trans != db.ICplxTrans()):
        raise Refusal('FILL_STREAM_NATIVE_CELL_TRANSFORM', 'one identity top-level fill child required')
    return {name}, expected


def preserve_native_fill_cells(layout, design, input_def, layout_options):
    """Executed immediately before native clearing; no GDS edits or inserts."""
    import klayout.db as db
    parsed = fill_records(input_def)
    if not parsed['shapes']:
        return set()
    entries = _map_entries(Path(layout_options.lefdef_config.map_file).read_text())
    mapping = {}
    for name in {s['layer'] for s in parsed['shapes']}:
        pairs = entries.get((name, 'FILL'), set())
        if len(pairs) != 1:
            raise Refusal('FILL_STREAM_MAPPING_MISSING', name)
        mapping[name] = list(next(iter(pairs)))
    # The exact same reader/options without FILLS identifies reader-created
    # cells independently of their names; ordinary macro cells are never kept.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.def', dir=Path(input_def).parent) as tmp:
        tmp.write(parsed['bare_def']); tmp.flush()
        bare = db.Layout(); bare.read(tmp.name, layout_options)
    keep, _ = _native_fill_child(bare, layout, parsed, mapping)
    return keep


def patched_native_source(source):
    """Use native fill retention or adapt the legacy cell-clearing operation."""
    tree = ast.parse(source)
    if any(isinstance(node, ast.FunctionDef) and node.name == 'should_clear_cell'
           for node in tree.body):
        return source
    anchor = '        # Clear cells\n'
    condition = '                if not i.name.startswith("VIA"):'
    if source.count(anchor) != 1 or source.count(condition) != 1:
        raise Refusal('FILL_STREAM_NATIVE_API_UNSUPPORTED', 'legacy clearing operation is not representable')
    source = source.replace(anchor,
        '        from librelane_fill_stream import preserve_native_fill_cells\n'
        '        fill_cells = preserve_native_fill_cells(main_layout, design_name, input, layout_options)\n' + anchor)
    return source.replace(condition, condition[:-1] + ' and i.name not in fill_cells:')


def geometry_proof(filled_def, bare_gds, filled_gds, mapping):
    import klayout.db as db
    parsed = fill_records(filled_def)
    layouts = []
    for path in (bare_gds, filled_gds):
        layout = db.Layout(); layout.read(str(path)); layouts.append(layout)
    bare, filled = layouts
    if bare.dbu != filled.dbu or not {c.name for c in bare.each_cell()} <= {c.name for c in filled.each_cell()}:
        raise Refusal('FILL_STREAM_HIERARCHY_CHANGED', 'dbu/cell population')
    if bare.cell(parsed['top']) is None or filled.cell(parsed['top']) is None:
        raise Refusal('FILL_STREAM_TOP_ABSENT', parsed['top'])
    added, expected = _native_fill_child(bare, filled, parsed, mapping)
    pairs = {(i.layer, i.datatype) for layout in layouts for i in layout.layer_infos()}
    checked_cells = 0
    for cell in bare.each_cell():
        other = filled.cell(cell.name)
        actual_instances = [i for i in _instances(other) if i[0] not in added]
        if _instances(cell) != actual_instances:
            raise Refusal('FILL_STREAM_HIERARCHY_CHANGED', cell.name)
        for pair in pairs:
            def shapes(layout, item):
                index = layout.find_layer(*pair)
                return sorted(s.to_s() for s in item.shapes(index).each()) if index is not None else []
            if shapes(bare, cell) != shapes(filled, other):
                raise Refusal('FILL_STREAM_NONFILL_GEOMETRY_CHANGED', cell.name + str(pair))
        checked_cells += 1
    return {'fill_count': len(parsed['shapes']), 'layers': mapping,
            'fill_area_dbu2': {f'{pair[0]}/{pair[1]}': region.area() for pair, region in expected.items()},
            'native_fill_cells': sorted(added), 'checked_cells': checked_cells, 'hierarchy_preserved': True,
            'nonfill_geometry_preserved': True, 'fill_geometry_matches_def': True,
            'scope': 'direct per-cell geometry and verified native fill child; no full-chip flatten',
            'final_finishing_acceptance': 'NOT_MEASURED'}
