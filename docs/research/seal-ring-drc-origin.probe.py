#!/usr/bin/env python3
"""Reproduces every geometric measurement in seal-ring-drc-origin.md.

Runs INSIDE KLayout:  klayout -b -zz -r seal-ring-drc-origin.probe.py
Driven by environment variables so it carries no design, PDK or foundry literal:

    SEALED    the sealed layout (after the PDK seal-ring script)
    UNSEALED  the same die before it
    TOPCELL   top cell name
    LAYERS    "name:layer/datatype,..."  the BEOL stack to measure
    METALS    comma-separated subset of LAYERS names the width rule applies to
              (the guard-ring width rule is metal-only; running it over a via
              array reports every via and means nothing)
    MARKER    "layer/datatype" of the PDK guard-ring marker
    RINGPFX   cell-name prefix the generator uses for its own cells
    FILLPAT   comma-separated substrings identifying metal-fill cells

It MEASURES ONLY. It writes no layout and modifies nothing.
"""
import os
import pya

SEALED = os.environ["SEALED"]
UNSEALED = os.environ.get("UNSEALED", "")
TOP = os.environ["TOPCELL"]
MARKER = os.environ["MARKER"]
RINGPFX = os.environ.get("RINGPFX", "sealring")
FILLPAT = [s for s in os.environ.get("FILLPAT", "FILL,fill_cell").split(",") if s]
LAYERS = [(n, int(s.split("/")[0]), int(s.split("/")[1]))
          for n, s in (kv.split(":") for kv in os.environ["LAYERS"].split(","))]
METALS = set(s for s in os.environ.get("METALS", "").split(",") if s) or \
    set(n for n, _, _ in LAYERS)

L = pya.Layout(); L.read(SEALED); top = L.cell(TOP); dbu = L.dbu


def region(cell, li):
    return pya.Region(cell.begin_shapes_rec(li)).merged()


def klass(name):
    if name.lower().startswith(RINGPFX):
        return "RING"
    if any(p in name for p in FILLPAT):
        return "FILL"
    return "DESIGN"


def by_source(li):
    """Split a layer into RING / FILL / DESIGN by the cell each shape comes from."""
    s = {"RING": pya.Region(), "FILL": pya.Region(), "DESIGN": pya.Region()}
    s["DESIGN"].insert(top.shapes(li))
    for inst in top.each_inst():
        c = L.cell(inst.cell_index)
        r = pya.Region(c.begin_shapes_rec(li)); r.transform(inst.trans)
        s[klass(c.name)] += r
    return {k: v.merged() for k, v in s.items()}


ml, md = (int(x) for x in MARKER.split("/"))
mi = next((i for i in L.layer_indexes()
           if L.get_info(i).layer == ml and L.get_info(i).datatype == md), None)
grmk = region(top, mi)
print("marker band: polys=%d area_um2=%.1f bbox_um=%s"
      % (grmk.count(), grmk.area() * dbu * dbu,
         [round(v * dbu, 3) for v in (grmk.bbox().left, grmk.bbox().bottom,
                                      grmk.bbox().right, grmk.bbox().top)]))

# 1. The guard-ring width rule as the deck states it —
#    metal.not_outside(marker).width(12um) — for the ring ALONE and AS BUILT.
print("\n%-8s %18s %12s" % ("layer", "ring metal ALONE", "as built"))
ta = tb = 0
for name, l, d in LAYERS:
    li = L.find_layer(l, d)
    if li is None or name not in METALS:
        continue
    a = by_source(li)["RING"].width_check(int(round(12.0 / dbu))).count()
    b = region(top, li).not_outside(grmk).width_check(int(round(12.0 / dbu))).count()
    ta += a; tb += b
    print("%-8s %18d %12d" % (name, a, b))
print("%-8s %18d %12d" % ("TOTAL", ta, tb))

# 2. Who is inside the band, and what the touch drags outside it.
print("\n%-8s %12s %12s %12s %12s %12s"
      % ("layer", "RING tot", "RING in band", "FILL in band", "DESIGN in band", "leak"))
for name, l, d in LAYERS:
    li = L.find_layer(l, d)
    if li is None:
        continue
    s = by_source(li)
    sel = region(top, li).not_outside(grmk)
    leak = sel - grmk
    print("%-8s %12.1f %12.3f %12.3f %12.3f %12.3f"
          % (name, s["RING"].area() * dbu * dbu,
             (s["RING"] & grmk).area() * dbu * dbu,
             (s["FILL"] & grmk).area() * dbu * dbu,
             (s["DESIGN"] & grmk).area() * dbu * dbu,
             leak.area() * dbu * dbu))
    if not leak.is_empty():
        b = leak.bbox()
        print("         leak bbox_um = (%.2f, %.2f) - (%.2f, %.2f)"
              % (b.left * dbu, b.bottom * dbu, b.right * dbu, b.top * dbu))

# 3. The precondition the gate does not test: is the band empty BEFORE the ring?
if UNSEALED:
    U = pya.Layout(); U.read(UNSEALED); tu = U.cell(TOP)
    die = pya.Region(top.bbox())
    inner = pya.Region(grmk.bbox()) - grmk          # the hole, measured not assumed
    band = die - inner
    print("\nPRECONDITION  pre[L] & band must be EMPTY:")
    bad = 0
    for name, l, d in LAYERS:
        li = U.find_layer(l, d)
        if li is None:
            continue
        a = (region(tu, li) & band).area() * dbu * dbu
        if a > 0:
            bad += 1
        print("   %-8s in band = %10.3f um^2%s" % (name, a, "   <-- NON-EMPTY" if a else ""))
    print("   verdict: %s (%d layer(s) non-empty)"
          % ("FAIL" if bad else "PASS", bad))
