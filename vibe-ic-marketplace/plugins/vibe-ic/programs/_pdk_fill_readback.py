"""KLayout-native GDS readback; transformation evidence, never density signoff."""
import json
import os
import pya


def load(path):
    layout = pya.Layout()
    layout.read(path)
    cell = layout.cell(os.environ['D62_CELL'])
    if cell is None:
        raise ValueError('D62_PDK_FILL_TOP_ABSENT')
    return layout, cell


before, old = load(os.environ['D62_BEFORE'])
after, new = load(os.environ['D62_AFTER'])
counts = {}
missing = []
infos = {str(layout.get_info(index)): layout.get_info(index)
         for layout in (before, after) for index in layout.layer_indexes()}
for name, info in sorted(infos.items()):
    a, b = before.find_layer(info), after.find_layer(info)
    old_region = pya.Region(old.begin_shapes_rec(a)) if a is not None else pya.Region()
    new_region = pya.Region(new.begin_shapes_rec(b)) if b is not None else pya.Region()
    # Recursive regions may contain only text shapes: is_empty() can
    # report an unmaterialized iterator as nonempty although count() is zero.
    old_region = old_region.transformed(pya.ICplxTrans(before.dbu / after.dbu, 0, False, 0, 0))
    if (old_region - new_region).count() != 0:
        missing.append(name)
    counts[name] = {'before': old_region.count(), 'after': new_region.count()}
body = {'layers': counts,
        'added_shapes': {name: c['after'] - c['before'] for name, c in counts.items()
                         if c['after'] != c['before']},
        'original_polygon_geometry_preserved': not missing,
        'missing_geometry_layers': missing, 'density_signoff': 'NOT_MEASURED'}
with open(os.environ['D62_READBACK'], 'w') as stream:
    json.dump(body, stream, indent=2)
if missing:
    raise ValueError('D62_PDK_FILL_GEOMETRY_LOST: ' + repr(missing))
