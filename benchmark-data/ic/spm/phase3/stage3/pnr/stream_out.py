
import pya, os, sys
top = os.environ['TOP']
def_path = os.environ['DEF']
gds_out = os.environ['GDS_OUT']
lefs = os.environ['LEFS'].split(';')
macro_gds_files = os.environ.get('MACRO_GDS', '').split(';')
cell_gds_path = os.environ.get('CELL_GDS', '').strip()
ly = pya.Layout()
# LEFs first — needed so DEF references resolve to LEF cell abstracts
for lp in lefs:
    if lp.strip():
        try: ly.read(lp.strip())
        except Exception as e: print(f"warn lef: {e}")
# v0.3.12 — ORGANIC #509 round-2: drive the DEF reader with the PDK's
# foundry LEF/DEF layer-map when provided, so metal/pin/label land on the
# foundry GDS numbers Magic's tech reads (met3=70/20, .pin=70/16,
# .label=70/5) instead of KLayout's compact default (10..14). Without it,
# signoff-LVS Magic extraction sees no top routing/labels → every top port
# extracts disconnected. Validated: with the map Magic recognises all top
# ports on the real spm GDS (0 → all). LEFs go through the SAME options so
# DEF references resolve. Empty/missing map → legacy numbering preserved.
_lefdef_map = os.environ.get('LEFDEF_MAP', '').strip()
_def_opts = pya.LoadLayoutOptions()
try:
    _cfg = _def_opts.lefdef_config
    if lefs and any(p.strip() for p in lefs):
        _cfg.lef_files = [p.strip() for p in lefs if p.strip()]
    if _lefdef_map and os.path.exists(_lefdef_map):
        _cfg.map_file = [_lefdef_map]
        print(f"LEFDEF_MAP applied: {_lefdef_map}")
    else:
        print("LEFDEF_MAP not applied (none/missing) — legacy numbering")
except Exception as e:
    print(f"warn lefdef_config: {e}")
ly.read(def_path, _def_opts)
# v1.6.560 sub-defect C: also read std-cell GDS so DEF cell instances
# resolve into proper physical hierarchy under the design top — without
# this, klayout writes the LEF abstracts as siblings at GDS top level
# (causing "multiple top cells" when DRC deck does `source($input)`).
if cell_gds_path:
    try:
        ly.read(cell_gds_path)
    except Exception as e:
        print(f"warn cell_gds: {e}")
# Merge any hard-macro PA-GDS files so the final GDS holds full physical
# data (vs the LEF outline only). chip-AGNOSTIC; macro_gds lists every
# vendor PA-GDS discovered under input/pdk_local/.
for gp in macro_gds_files:
    if gp.strip():
        try: ly.read(gp.strip())
        except Exception as e: print(f"warn macro_gds: {e}")
# v1.6.560 sub-defect C: prune the layout to only the design top cell
# and its descendants. This guarantees `ly.top_cells()` returns exactly
# one element (the design), matching what magic-streamed / LibreLane-
# direct GDS provides. Prevents klayout DRC deck `source($input)` from
# failing with "multiple top cells".
top_cell = ly.cell(top)
if top_cell is None:
    # Fallback: pick the first non-std-cell top (rare path)
    for c in ly.top_cells():
        if not c.name.startswith('sky130_fd_sc') and not c.name.startswith('gf180mcu_'):
            top_cell = c
            break
if top_cell is not None:
    keep_ids = {top_cell.cell_index()}
    todo = [top_cell]
    while todo:
        c = todo.pop()
        for child in c.each_child_cell():
            cc = ly.cell(child)
            if cc and cc.cell_index() not in keep_ids:
                keep_ids.add(cc.cell_index())
                todo.append(cc)
    delete_ids = [c.cell_index() for c in ly.each_cell()
                  if c.cell_index() not in keep_ids]
    ly.delete_cells(delete_ids)
ly.write(gds_out)
print(f"GDS_WRITTEN {gds_out}")
print(f"GDS_TOP_CELLS {len(list(ly.top_cells()))}")
