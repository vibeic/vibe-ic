"""Outside seal frames. Unknown footprint is BLOCKING, never a guessed margin."""
from __future__ import annotations

import json
import math
from pathlib import Path

import _tapeout_declaration as declaration


class Refusal(ValueError):
    pass


def placement(project, doc=None):
    path = Path(project) / declaration.DECLARATION_REL
    if doc is None:
        if not path.is_file():
            return 'inside'
        doc, why = declaration.load(path)
        if why:
            raise Refusal('SEAL_RING_PLACEMENT_UNREADABLE: ' + why)
    value = declaration.answer(doc, 'seal_ring_placement')
    if value in (None, declaration.NOT_DETERMINED, 'inside'):
        return 'inside'
    if value != 'outside':
        raise Refusal('SEAL_RING_PLACEMENT_INVALID: ' + str(value))
    return value


def box(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in value)
            or value[0] >= value[2] or value[1] >= value[3]):
        raise Refusal('SEAL_RING_FRAME_INVALID: finite nonempty rectangle required')
    return list(value)


def declared_die(project, doc=None):
    if doc is None:
        doc, why = declaration.load(Path(project) / declaration.DECLARATION_REL)
        if why:
            raise Refusal('SEAL_RING_DECLARED_DIE_ABSENT: ' + why)
    return box(declaration.answer(doc, 'die_area_um'))


def grow(die, g):
    die = box(die)
    if isinstance(g, bool) or not isinstance(g, (int, float)) or not math.isfinite(g) or g <= 0:
        raise Refusal('SEAL_RING_FOOTPRINT_NOT_MEASURED: positive finite g required')
    return [die[0] - g, die[1] - g, die[2] + g, die[3] + g]


def from_measurement(die, probe_frame, measured, basis):
    """Measure frame-to-inner depth, including any edge box, on all sides."""
    probe_frame = box(probe_frame)
    try:
        outer = box(measured['outer']['um'])
        if any(not math.isclose(a, b, rel_tol=0, abs_tol=0.0001)
               for a, b in zip(outer, probe_frame)):
            raise ValueError('the measured probe outer edge differs from its requested frame')
        inner = box(measured['inner']['um'])
        depths = [inner[0] - probe_frame[0], inner[1] - probe_frame[1],
                  probe_frame[2] - inner[2], probe_frame[3] - inner[3]]
        if min(depths) <= 0:
            raise ValueError('the probe has no positive frame-to-inner depth')
        g = max(depths)
        return {'placement': 'outside', 'declared_die_um': box(die),
                'grown_frame_um': grow(die, g), 'g_um': g,
                'g_basis': {**basis, 'probe_frame_um': probe_frame,
                            'ring_extent': measured, 'depths_um': depths}}
    except (KeyError, TypeError, ValueError) as exc:
        raise Refusal('SEAL_RING_FOOTPRINT_NOT_MEASURED: ' + str(exc)) from exc


def validate(frame, extent, die=None):
    declared = box(frame['declared_die_um'])
    expected = grow(declared, frame['g_um'])
    outer, inner = box(extent['outer']['um']), box(extent['inner']['um'])
    close = lambda a, b: all(math.isclose(x, y, rel_tol=0, abs_tol=0.0001)
                              for x, y in zip(a, b))
    if die is not None and not close(declared, box(die)):
        raise Refusal('SEAL_RING_DECLARED_DIE_CHANGED')
    if not close(box(frame['grown_frame_um']), expected) or not close(outer, expected):
        raise Refusal('SEAL_RING_DIE_EXTENT_MISMATCH: measured outer edge differs from grown frame')
    if (inner[0] > declared[0] + 0.0001 or inner[1] > declared[1] + 0.0001
            or inner[2] < declared[2] - 0.0001 or inner[3] < declared[3] - 0.0001):
        raise Refusal('SEAL_RING_INNER_EDGE_INSIDE_DIE: ring encroaches on declared die')
    return expected


def completed_frame(project, run=None, doc=None):
    """Consumers use the measured finishing frame, never a precheck-sized guess."""
    try:
        if run is None:
            import die_finishing_check
            path = Path(project) / 'reports/phase3/die_finishing.json'
            run = die_finishing_check._unwrap(json.loads(path.read_text()))
        seal = run['seal_ring']
        if seal.get('state') != 'PASS':
            raise Refusal('SEAL_RING_OUTSIDE_FRAME_NOT_MEASURED: finishing did not pass')
        frame = seal['frame']
        basis = frame['g_basis']
        import hashlib
        measurement = Path(basis['measurement'])
        if hashlib.sha256(measurement.read_bytes()).hexdigest() != basis['sha256']:
            raise Refusal('SEAL_RING_FOOTPRINT_MEASUREMENT_CHANGED')
        observed = json.loads(measurement.read_text())
        if (observed.get('verdict') != 'PASS'
                or observed.get('ring_extent') != basis['ring_extent']):
            raise Refusal('SEAL_RING_FOOTPRINT_MEASUREMENT_INVALID')
        rebuilt = from_measurement(frame['declared_die_um'], basis['probe_frame_um'],
                                   observed['ring_extent'], basis)
        if rebuilt['g_um'] != frame['g_um']:
            raise Refusal('SEAL_RING_FOOTPRINT_MEASUREMENT_CHANGED')
        return validate(frame, seal['ring_check']['ring_extent'], declared_die(project, doc))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise Refusal('SEAL_RING_OUTSIDE_FRAME_NOT_MEASURED: ' + str(exc)) from exc
