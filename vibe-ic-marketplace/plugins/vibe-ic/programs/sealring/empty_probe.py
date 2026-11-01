"""Create an empty probe with the input's top name and database unit; draw nothing."""
import json
import os
import pya

source = pya.Layout()
source.read(os.environ['SEAL_PROBE_SOURCE'])
top = source.top_cell()
if top is None:
    raise ValueError('SEAL_RING_PROBE_TOP_UNRESOLVED')
if os.environ.get('SEAL_PROBE_RING'):
    ring = pya.Layout()
    ring.read(os.environ['SEAL_PROBE_RING'])
    child = source.create_cell(source.unique_cell_name(top.name + '_seal_frame'))
    child.copy_tree(ring.top_cell())
    x, y = json.loads(os.environ['SEAL_PROBE_OFFSET'])
    top.insert(pya.DCellInstArray(child.cell_index(), pya.DCplxTrans(1, 0, False, x, y)))
    source.write(os.environ['SEAL_PROBE_INPUT'])
else:
    probe = pya.Layout()
    probe.dbu = source.dbu
    probe.create_cell(top.name)
    probe.write(os.environ['SEAL_PROBE_INPUT'])
