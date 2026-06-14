
import os
import pya

gds_in = os.environ["GDS_IN"]
gds_out = os.environ["GDS_OUT"]
ly = pya.Layout()
ly.read(gds_in)
# Flatten so abutting geometry across cell-instance boundaries becomes
# co-resident in one cell and merges (a hierarchical merge would not union
# a cell pin against a top-level route).
for tc in ly.top_cells():
    tc.flatten(-1, True)
merged_layers = 0
for tc in ly.top_cells():
    for li in ly.layer_indexes():
        sh = tc.shapes(li)
        if sh.is_empty():
            continue
        reg = pya.Region(sh)
        reg.merge()                 # union abutting/overlapping same-layer
        sh.clear()
        sh.insert(reg)
        merged_layers += 1
ly.write(gds_out)
print("GDS_LAYER_MERGE_DONE layers=%d" % merged_layers)
