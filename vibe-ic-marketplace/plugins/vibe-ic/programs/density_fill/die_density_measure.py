#!/usr/bin/env python3
"""die_density_measure.py — measure per-layer coverage over the DIE, in KLayout.

Runs as a KLayout batch script (`klayout -zz -b -r`), i.e. with `pya` bound. It
answers ONE question and answers it the way a foundry minimum-density rule asks
it:

    coverage = merged area of a layer's shapes / DIE AREA

Three things are load-bearing, and are why this is a separate measurement
rather than a number scraped out of a fill log.

1. THE DENOMINATOR IS THE DIE, NOT THE LAYOUT BOUNDING BOX. A foundry rule
   reads "coverage over the entire die". A flow that divides by the bounding
   box of whatever geometry happens to exist reports a sparse die as dense
   whenever the geometry occupies only part of the die -- which is exactly what
   a routed core sitting inside a larger slot looks like. Both denominators are
   reported (`over_bbox`, `over_die`) together with the die rectangle and the
   authority it came from, so the two can never be confused for each other.

2. COVERAGE IS PER GDS LAYER NUMBER, MERGED ACROSS DATATYPES. Dummy fill is
   deposited on its own datatype and the density rules count it -- that is what
   it is for. Merging across datatypes is what makes the roll-up comparable to
   a rule written as "drawn + dummy". The per-(layer, datatype) rows are kept
   beside it so the split stays visible.

3. NO FLOOR IS APPLIED HERE, AND NO LAYER NUMBER IS WRITTEN HERE. Which layers
   exist, what they are called and what each must reach are foundry data. This
   script enumerates what the layout actually carries and measures it. The
   authority on whether a number passes is the PDK's own density rule deck,
   which the sign-off DRC step already runs.

Environment:
  DENS_GDS      layout to measure
  DENS_SPEC     JSON: {"die": [x0,y0,x1,y1] | null, "die_source": str,
                       "layers": [[layer, datatype], ...] | null}
                `layers: null` enumerates every layer/datatype carrying shapes.
  DENS_OUT      JSON file to write
  DENS_CELL     top cell name (optional; the layout's own single top otherwise)
"""
import json
import os
import sys

import pya                                                   # noqa: F401


def main() -> int:
    gds = os.environ["DENS_GDS"]
    spec = json.loads(os.environ.get("DENS_SPEC") or "{}")
    out = os.environ["DENS_OUT"]

    ly = pya.Layout()
    ly.read(gds)

    want = os.environ.get("DENS_CELL") or ""
    top = None
    if want:
        for c in ly.top_cells():
            if c.name == want:
                top = c
                break
    if top is None:
        tops = list(ly.top_cells())
        if len(tops) != 1:
            with open(out, "w") as fh:
                json.dump({"error":
                           "layout has %d top cells (%s) and no top named %r"
                           % (len(tops), ", ".join(c.name for c in tops), want)},
                          fh, indent=2)
            return 1
        top = tops[0]

    b = top.dbbox()
    bbox_area = b.width() * b.height()
    die = spec.get("die")
    die_area = None
    if die:
        die_area = ((float(die[2]) - float(die[0]))
                    * (float(die[3]) - float(die[1])))

    res = {
        "gds": gds,
        "top": top.name,
        "dbu": ly.dbu,
        "bbox_um": [b.left, b.bottom, b.right, b.top],
        "bbox_area_um2": bbox_area,
        "die_um": die,
        "die_source": spec.get("die_source"),
        "die_area_um2": die_area,
        # The defect this step exists to make visible, stated as a number
        # rather than as a warning: a fill generator whose frame is the layout
        # bounding box cannot deposit anything outside it, so when the bounding
        # box is smaller than the die, the part of the die it never reached is
        # exactly the part a die-wide density rule fails on.
        "bbox_covers_die": None,
        "bbox_area_over_die_area": None,
        "by_layer_datatype": {},
        "by_layer": {},
    }
    if die and die_area:
        eps = ly.dbu
        res["bbox_covers_die"] = (
            b.left <= float(die[0]) + eps and b.bottom <= float(die[1]) + eps
            and b.right >= float(die[2]) - eps and b.top >= float(die[3]) - eps)
        res["bbox_area_over_die_area"] = bbox_area / die_area

    declared = spec.get("layers")
    if declared:
        pairs = [(int(a), int(d)) for a, d in declared]
    else:
        pairs = []
        for li in ly.layer_indexes():
            info = ly.get_info(li)
            # A named-only layer has layer/datatype -1 and is not a GDS layer.
            if info.layer >= 0 and info.datatype >= 0:
                pairs.append((info.layer, info.datatype))

    per_layer = {}
    for layer, dt in sorted(set(pairs)):
        li = ly.find_layer(layer, dt)
        if li is None:
            continue
        r = pya.Region(top.begin_shapes_rec(li))
        if r.is_empty():
            continue
        r.merge()
        area = r.area() * ly.dbu * ly.dbu
        res["by_layer_datatype"]["%d/%d" % (layer, dt)] = {
            "area_um2": area,
            "polygons": r.count(),
            "over_bbox": (area / bbox_area) if bbox_area else None,
            "over_die": (area / die_area) if die_area else None,
        }
        per_layer[layer] = (per_layer[layer] + r) if layer in per_layer else r

    for layer, r in sorted(per_layer.items()):
        r.merge()
        area = r.area() * ly.dbu * ly.dbu
        res["by_layer"][str(layer)] = {
            "area_um2": area,
            "datatypes": sorted(dt for (l, dt) in set(pairs) if l == layer
                                and "%d/%d" % (l, dt) in res["by_layer_datatype"]),
            "over_bbox": (area / bbox_area) if bbox_area else None,
            "over_die": (area / die_area) if die_area else None,
        }

    with open(out, "w") as fh:
        json.dump(res, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
