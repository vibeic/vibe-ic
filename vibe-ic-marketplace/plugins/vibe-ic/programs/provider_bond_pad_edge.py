"""Read-only provider assembly measurement, consumed by its existing precheck.

The provider_target.json bond_pad_edge_distance section declares opening_layer
{name, layer_properties} (a PDK .lyp) and optionally io_lefs (PDK CLASS PAD
masters; otherwise use the selected PDK's existing discovery). max_distance_um
is a provider/packaging declaration, never a tool default. technical_target
supplies dimensions_um and optional origin_um (the operator slot starts at 0,0).
Missing authority/geometry is NOT_MEASURED; measured distances without a limit
are MANUAL_REVIEW. Both prevent an assembly/precheck PASS. No layout is changed.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def measure(project, gds, *, top='', profile_path=None):
    from die_finishing_gen import PROVIDER_TARGET_REL, _release_file
    import _pad_ring as pads

    project, gds = Path(project), Path(gds)
    report = {'check': 'bond_pad_edge_distance', 'verdict': 'NOT_MEASURED',
              'distances_um': None, 'assembly': {
                  'strategy': 'preserve_source_placement', 'applied_offset_um': [0, 0],
                  'basis': 'assembly keeps the source placement; no pad/core transform applied'},
              'scope': 'actual final-GDS opening to declared provider die frame; not packaging acceptance'}

    def local(path):
        path = Path(path)
        return path if path.is_absolute() else project / path

    def numbers(values, length):
        return (isinstance(values, list) and len(values) == length
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) for v in values))

    try:
        report['input'] = _release_file(gds)
        authority = local(profile_path or PROVIDER_TARGET_REL)
        report['profile'] = _release_file(authority)
        profile = json.loads(authority.read_text())
        if not profile.get('provider'):
            raise ValueError('no declared provider profile')
        target = profile['technical_target']
        dims, origin = target['dimensions_um'], target.get('origin_um', [0, 0])
        if not numbers(dims, 2) or min(dims) <= 0 or not numbers(origin, 2):
            raise ValueError('provider frame dimensions/origin are not finite spans')
        frame = [*origin, origin[0] + dims[0], origin[1] + dims[1]]
        report['die_frame_um'] = frame
        report['die_frame_source'] = PROVIDER_TARGET_REL + '.technical_target (operator slot frame)'
        rule = profile.get('bond_pad_edge_distance') or {}
        layer_decl = rule.get('opening_layer') or {}
        if not layer_decl.get('name') or not layer_decl.get('layer_properties'):
            raise ValueError('no PDK pad-opening layer declaration in the provider profile')
        properties = local(layer_decl['layer_properties'])
        layers = set()
        for node in ET.parse(properties).getroot().iter('properties'):
            source = (node.findtext('source') or '').strip()
            match = re.fullmatch(r'(?:' + re.escape(layer_decl['name']) + r'\s+)?(\d+)/(\d+)(?:@\d+)?', source)
            if match and (source.startswith(layer_decl['name'] + ' ')
                          or (node.findtext('name') or '').strip() == layer_decl['name']):
                layers.add(tuple(map(int, match.groups())))
        if len(layers) != 1:
            raise ValueError('PDK pad-opening layer is missing or ambiguous')
        layer, = layers
        report['opening_layer'] = {'name': layer_decl['name'], 'gds': list(layer),
                                   'source': _release_file(properties)}
        lefs = rule.get('io_lefs')
        if lefs is not None:
            if not isinstance(lefs, list) or not lefs:
                raise ValueError('no declared PDK IO LEFs')
            lefs = [local(p) for p in lefs]
        else:
            lefs = pads.discover_io_lefs(profile.get('pdk_root'), profile.get('pdk'))
        masters, sources = set(), []
        for lef in lefs:
            sources.append(_release_file(lef))
            masters.update(name for name, cls in pads.parse_lef_macro_classes(
                Path(lef).read_text()).items() if cls.split()[0] == 'PAD')
        if not masters:
            raise ValueError('no PDK CLASS PAD masters resolved')
        report['master_sources'] = sources
        import klayout.db as k
        layout = k.Layout(); layout.read(str(gds))
        cell = layout.cell(top) if top else (layout.top_cells()[0] if len(layout.top_cells()) == 1 else None)
        if cell is None or cell not in layout.top_cells():
            raise ValueError('final GDS top cell is missing or ambiguous')
        report['top'] = cell.name
        index = layout.find_layer(*layer)
        if index is None:
            raise ValueError('declared pad-opening layer has no final-GDS geometry')
        iterator = cell.begin_shapes_rec(index)
        box, count, used = k.Box(), 0, set()
        while not iterator.at_end():
            shape = iterator.shape()
            ancestry = {iterator.cell().name}
            ancestry.update(layout.cell(part.inst().cell_index).name for part in iterator.path())
            owner = ancestry & masters
            if owner and (shape.is_box() or shape.is_polygon() or shape.is_path()):
                polygon = shape.path.polygon() if shape.is_path() else shape.polygon
                if polygon.area() > 0:
                    box += polygon.transformed(iterator.trans()).bbox()
                    count += 1
                    used.update(owner)
            iterator.next()
        if not count:
            raise ValueError('no actual opening polygons under PDK PAD masters; flattened/unresolved pads are unmeasured')
        extent = [v * layout.dbu for v in [box.left, box.bottom, box.right, box.top]]
        distances = dict(zip(('left', 'bottom', 'right', 'top'),
                             (extent[0] - frame[0], extent[1] - frame[1],
                              frame[2] - extent[2], frame[3] - extent[3])))
        report.update(distances_um=distances, opening_bbox_um=extent, opening_count=count,
                      pad_masters=sorted(used), dbu_um=layout.dbu, tool_version=k.__version__)
        limit = rule.get('max_distance_um')
        report['declared_max_distance_um'] = limit
        report['limit_source'] = PROVIDER_TARGET_REL + '.bond_pad_edge_distance.max_distance_um'
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, float))
                                  or not math.isfinite(limit) or limit < 0):
            raise ValueError('declared packaging/provider maximum is not a finite nonnegative distance')
        report['outside_frame_sides'] = [side for side, value in distances.items() if value < 0]
        report['exceeded_sides'] = ([side for side, value in distances.items() if value > limit]
                                    if limit is not None else [])
        if report['outside_frame_sides'] or report['exceeded_sides']:
            report.update(verdict='FAIL', reason='opening outside declared die frame or beyond declared packaging/provider maximum')
        elif limit is None:
            report.update(verdict='MANUAL_REVIEW', reason='distances measured; no packaging/provider maximum declared')
        else:
            report.update(verdict='PASS', reason='all four measured distances satisfy the declared packaging/provider maximum')
        if _release_file(gds) != report['input']:
            report.update(verdict='NOT_MEASURED', reason='final GDS changed during measurement')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError, RuntimeError, ET.ParseError) as exc:
        report.update(verdict='NOT_MEASURED', reason=str(exc))
    return report
