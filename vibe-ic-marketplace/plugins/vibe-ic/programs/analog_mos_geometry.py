#!/usr/bin/env python3
"""Source-bound calibrated MOS geometry and declared wrapper finger counts.

IR width is total width. A finger count divides that width; multiplicity is
independent. Missing model-domain declarations do not invent a width limit.
"""
from __future__ import annotations

import copy
import hashlib
import math
import posixpath
from pathlib import Path
import re
import shlex

import analog_pdk_deck_context as deck

MOS_ROLES = ('nmos', 'pmos')


class GeometryDomainError(ValueError):
    pass


def _tokens(line):
    if not line.strip() or line.lstrip().startswith('*'):
        return []
    try:
        return shlex.split(line)
    except ValueError:
        return []


def _selected(text, section):
    active, found, in_section = section is None, section is None, False
    result = []
    for line in text.splitlines():
        tokens = _tokens(line)
        if tokens and tokens[0].casefold() == '.lib' and len(tokens) == 2:
            in_section = True
            active = section is not None and tokens[1].casefold() == str(section).casefold()
            found |= active
            result.append('')
            continue
        if tokens and tokens[0].casefold() == '.endl':
            in_section = False
            active = section is None
            result.append('')
            continue
        # Keep source-header calibration comments outside any section too.
        if active or (not in_section and not tokens and line.lstrip().startswith('*')):
            result.append(line)
        else:
            result.append('')
    if not found:
        raise GeometryDomainError('selected model section is absent: ' + str(section))
    return '\n'.join(result)


def _closure(path, section, reader, seen=None):
    path = Path(posixpath.normpath(str(path)))
    seen = set() if seen is None else seen
    key = (str(path), section)
    if key in seen:
        return {}
    seen.add(key)
    text = reader(str(path))
    if text is None:
        return {}
    selected = _selected(text, section)
    result = {key: {'path': str(path), 'text': selected,
                    'sha256': hashlib.sha256(text.encode()).hexdigest()}}
    for line in selected.splitlines():
        tokens = _tokens(line)
        if not tokens:
            continue
        directive = tokens[0].casefold()
        if directive in ('.include', '.inc') and len(tokens) >= 2:
            child_section = None
        elif directive == '.lib' and len(tokens) >= 3:
            child_section = tokens[2]
        else:
            continue
        child = Path(tokens[1])
        if not child.is_absolute():
            child = Path(path).parent / child
        result.update(_closure(child, child_section, reader, seen))
    return result


_RANGE = re.compile(r'(?i)\b([wl])\s*=\s*\(\s*([\d.eE+-]+)\s*[-–]\s*([\d.eE+-]+)\s*\)\s*(µm|μm|um|nm|mm)\b')


def calibrated_ranges(text):
    """Read explicit source 'Valid range for model' headers, including W/L continuation."""
    declarations, current, remaining = [], {}, 0
    for number, line in enumerate(text.splitlines(), 1):
        if re.search(r'(?i)\bvalid\s+range\s+for\s+model\b', line):
            if current:
                declarations.append(current)
            current, remaining = {'rows': []}, 5
        if remaining:
            for match in _RANGE.finditer(line):
                scale = {'um': 1., 'µm': 1., 'μm': 1., 'nm': .001, 'mm': 1000.}[match[4].casefold()]
                low, high = float(match[2])*scale, float(match[3])*scale
                if not 0 < low <= high or not math.isfinite(high):
                    raise GeometryDomainError('invalid calibrated model geometry range')
                current[match[1].casefold()] = (low, high)
                current['rows'].append({'line': number, 'text': line.strip()})
            remaining -= 1
    if current:
        declarations.append(current)
    return [row for row in declarations if 'w' in row or 'l' in row]


def _finger_declaration(text, model):
    body = deck.subckt_body(text, model)
    if not body:
        return None
    header, core = deck._split_subckt_header(body)
    header = deck.spice_code_only(header, blank_quoted=True)
    matches = list(re.finditer(r'(?i)\b(ng|nf)\s*=\s*([^\s]+)', header))
    if len(matches) > 1:
        raise GeometryDomainError('ambiguous declared finger parameters: ' + model)
    if not matches:
        return None
    match = matches[0]
    try:
        default = float(match[2])
    except ValueError:
        default = None
    formal = match[1].casefold()
    code = deck.spice_code_only(core)
    width_formal = deck.subckt_geometry_param_names(text, model).get('w', 'w')
    cards = []
    for line in code.splitlines():
        if line.lstrip().startswith('+') and cards:
            cards[-1] += ' ' + line.lstrip()[1:]
        elif line.strip():
            cards.append(line)
    # Every native or nested device carrying width/finger geometry must use
    # this same mapping. One valid card cannot vouch for another that drops
    # or transforms the declared count/width.
    relevant = [card for card in cards if re.match(r'(?i)^\s*[mnx]\S*\s', card)
                and re.search(r'(?i)\b(?:w|nf|ng)\s*=', card)]
    def direct_mapping(card):
        assignments = re.findall(r'''(?i)\b(w|nf|ng)\s*=\s*('[^']*'|"[^"]*"|\S+)''', card)
        width = [value for name, value in assignments if name.casefold() == 'w']
        fingers = [value for name, value in assignments if name.casefold() in ('nf', 'ng')]
        if len(width) != 1 or len(fingers) != 1:
            return False
        def formal_value(value):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('\'', '"'):
                value = value[1:-1]
            return value.strip().casefold()
        return formal_value(width[0]) == width_formal.casefold() and formal_value(fingers[0]) == formal
    direct = bool(relevant) and all(direct_mapping(card) for card in relevant)
    return {'finger_parameter': formal if direct else None, 'finger_default': default,
            'declared_finger_parameter': formal,
            'width_semantics': 'total width passed unchanged with native finger count' if direct else 'unsupported native width/finger mapping'}


def discover_context(pdkctx, project=None, container='', reader=None):
    """Discover each elected MOS wrapper's actual parameter and unambiguous source bounds."""
    reader = reader or (deck.container_reader(container or pdkctx.get('container', ''))
                        if container or pdkctx.get('container') else deck._default_reader)
    loads = pdkctx.get('deck_loads') or [(pdkctx.get('model_lib'), pdkctx.get('typ_section'))]
    contexts = {}
    for path, section in loads:
        if not path:
            continue
        path = Path(path)
        if not path.is_absolute() and project is not None:
            path = Path(project)/path
        files = _closure(path, section, reader)
        if not files:
            continue
        blob = '\n'.join(row['text'] for row in files.values())
        for role in MOS_ROLES:
            model = (pdkctx.get('role_models') or {}).get(role)
            if not model:
                continue
            if not deck.subckt_body(blob, model):
                # A composed deck also loads resistor/capacitor libraries.
                # Their calibration headers do not describe this MOS wrapper.
                continue
            declaration = _finger_declaration(blob, model) or {'finger_parameter': None, 'finger_default': None}
            ranges = [row for file in files.values() for row in calibrated_ranges(file['text'])]
            bounds = {}
            for dimension in ('w', 'l'):
                choices = {tuple(row[dimension]) for row in ranges if dimension in row}
                if len(choices) > 1:
                    raise GeometryDomainError('ambiguous source calibrated ' + dimension + ' range for ' + model)
                if choices:
                    bounds[dimension] = next(iter(choices))
            contexts[role] = {**declaration, 'model': model, 'bounds': bounds,
                'inputs': {row['path']: {'path': row['path'], 'sha256': row['sha256']} for row in files.values()},
                'source_rows': [item for row in ranges for item in row['rows']]}
    return contexts


def apply_fingers(ir, overrides, context):
    """Return effective parameters and source-attributed count records without mutating IR."""
    effective, records = copy.deepcopy(overrides), []
    for device in ir.get('devices') or []:
        name, role = device['name'], device.get('role')
        supplied = effective.get(name, {})
        explicit = supplied.get('ng', device.get('ng'))
        legacy = {key: value for key, value in (device.get('params') or {}).items() if key.casefold() in ('ng', 'nf')}
        if explicit is not None and legacy or len(legacy) > 1:
            raise GeometryDomainError(name + ': duplicate finger declarations')
        if legacy:
            explicit = next(iter(legacy.values()))
        if role not in MOS_ROLES:
            if explicit is not None:
                raise GeometryDomainError(name + ': finger count is valid only for MOS devices')
            continue
        selected = context.get(role) or {}
        parameter = selected.get('finger_parameter')
        if explicit is not None and not parameter:
            raise GeometryDomainError(name + ': bound wrapper declares no supported finger parameter')
        if legacy and next(iter(legacy)).casefold() != parameter:
            raise GeometryDomainError(name + ': finger alias is not supported by the bound wrapper')
        bounds = selected.get('bounds') or {}
        if not bounds and explicit is None:
            continue
        width, length = (supplied.get(p, device.get(p)) for p in ('w', 'l'))
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in (width, length)):
            raise GeometryDomainError(name + ': MOS width/length must be finite and positive')
        maximum = bounds.get('w', (None, None))[1]
        count = max(1, math.ceil(width/maximum)) if maximum else 1
        if explicit is not None:
            if isinstance(explicit, bool) or not isinstance(explicit, (int, float)) or not math.isfinite(explicit) or explicit < 1 or explicit != int(explicit):
                raise GeometryDomainError(name + ': finger count must be a positive integer')
            count = int(explicit)
        if count > 1 and not parameter:
            raise GeometryDomainError(name + ': calibrated width requires unsupported wrapper fingering')
        finger_width = width/count
        for dimension, value in (('w', finger_width), ('l', length)):
            if dimension in bounds and not bounds[dimension][0] <= value <= bounds[dimension][1]:
                raise GeometryDomainError(name + ': geometry is outside calibrated model ' + dimension + ' range')
        emit = bool(parameter) and (explicit is not None or count > 1 or selected.get('finger_default') != 1)
        if emit:
            effective.setdefault(name, {})['ng'] = count
        records.append({'device': name, 'role': role, 'total_width_um': width, 'length_um': length,
            'ng': count, 'finger_width_um': finger_width, 'finger_parameter': parameter,
            'emit_finger': emit, 'explicit': explicit is not None, 'bounds': bounds,
            'source_inputs': selected.get('inputs', {}), 'source_rows': selected.get('source_rows', [])})
    return effective, records
