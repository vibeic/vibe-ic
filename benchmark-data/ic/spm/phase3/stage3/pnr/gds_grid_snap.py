
import os
import pya

gds_in = os.environ["GDS_IN"]
gds_out = os.environ["GDS_OUT"]
# Manufacturing grid in micron (sky130 = 0.005); MFG_GRID_UM env wins.
grid_um = float(os.environ.get("MFG_GRID_UM", "0.005"))
ly = pya.Layout()
ly.read(gds_in)
# grid in DBU: round(grid_um / dbu). dbu is micron/DBU (e.g. 0.001).
grid_dbu = int(round(grid_um / ly.dbu))
if grid_dbu < 1:
    grid_dbu = 1


def _snap_dbu(v):
    return int(round(float(v) / grid_dbu)) * grid_dbu


def _snap_local_shapes():
    """Snap every cell's LOCAL geometry vertices to the grid."""
    n = 0
    for ci in range(ly.cells()):
        cell = ly.cell(ci)
        for li in ly.layer_indexes():
            sh = cell.shapes(li)
            if sh.is_empty():
                continue
            reg = pya.Region(sh)
            reg.snap(grid_dbu, grid_dbu)
            sh.clear()
            sh.insert(reg)
            n += 1
    return n


# (1) cell-LOCAL geometry → grid
snapped_layers = _snap_local_shapes()

# (2) instance PLACEMENT → grid. OFFGRID DRC judges ABSOLUTE coordinates
#     (after the instance transform chain), so a std cell whose LOCAL
#     shapes are on-grid still streams off-grid geometry when it is PLACED
#     at an off-grid origin. Snap the displacement of every instance (and
#     any regular-array step vectors) to the grid; for orthogonal, mag-1
#     transforms this makes the absolute coordinates on-grid WITHOUT
#     flattening. Track any exotic transform that breaks that guarantee.
snapped_insts = 0
nonorthogonal = 0
inst_errs = 0
for ci in range(ly.cells()):
    cell = ly.cell(ci)
    for inst in list(cell.each_inst()):
        # Per-instance try/except so one problematic instance cannot abort
        # the whole pass BEFORE ly.write — otherwise the runner would fall
        # back to the original UN-snapped GDS and lose even the working
        # cell-local snap. A nonzero inst_errs in the marker surfaces it.
        try:
            ct = inst.cplx_trans          # ICplxTrans, DBU displacement
            if abs(ct.mag - 1.0) > 1e-9 or (round(ct.angle) % 90) != 0:
                nonorthogonal += 1        # exotic: flatten fallback below
            d = ct.disp
            ndx, ndy = _snap_dbu(d.x), _snap_dbu(d.y)
            changed = (ndx != d.x or ndy != d.y)
            if changed:
                inst.cplx_trans = pya.ICplxTrans(
                    ct.mag, ct.angle, ct.is_mirror(), ndx, ndy)
            # regular arrays: snap the a/b step vectors too
            if inst.is_regular_array():
                a, b = inst.a, inst.b
                na = pya.Vector(_snap_dbu(a.x), _snap_dbu(a.y))
                nb = pya.Vector(_snap_dbu(b.x), _snap_dbu(b.y))
                if na != a or nb != b:
                    inst.a, inst.b = na, nb
                    changed = True
            if changed:
                snapped_insts += 1
        except Exception:
            inst_errs += 1

# (3) guaranteed fallback for exotic transforms: flatten to absolute
#     coordinates and re-snap. Skipped entirely in the common (orthogonal,
#     mag-1) case so hierarchy + memory are preserved.
flattened = 0
if nonorthogonal > 0:
    for tc in ly.top_cells():
        tc.flatten(-1, True)
        flattened += 1
    snapped_layers += _snap_local_shapes()

ly.write(gds_out)
print("GDS_GRID_SNAP_DONE grid_dbu=%d layers=%d insts=%d "
      "nonorthogonal=%d flattened=%d inst_errs=%d"
      % (grid_dbu, snapped_layers, snapped_insts, nonorthogonal,
         flattened, inst_errs))
