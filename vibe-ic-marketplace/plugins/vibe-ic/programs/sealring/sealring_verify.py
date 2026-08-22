#!/usr/bin/env python3
"""sealring_verify.py — KLayout batch verifier for a PDK-generated seal ring.

Runs INSIDE KLayout (``klayout -zz -b -r sealring_verify.py``) or under any
python that can ``import pya``. Driven entirely by environment variables so it
needs no argv and no sibling imports — the same shape as the ``metal_fill`` and
``gds_antenna`` engines beside it.

    SEAL_IN      the GDS as it was BEFORE the PDK seal-ring script ran
    SEAL_OUT     the GDS the PDK seal-ring script produced
    SEAL_REPORT  where to write the JSON verdict
    SEAL_CELL    (optional) top cell name; default = the layout's own top
    SEAL_MARKER  (optional) "layer/datatype" of the PDK's guard-ring marker
                 layer. When set, that layer must carry geometry in SEAL_OUT.
    SEAL_ID_CELLS (optional) comma-separated cell names to REPORT the
                 INSTANCE COUNT of. Reported only; it never moves the
                 seal-ring verdict, which is a different question with a
                 different owner. A count rather than a boolean because the
                 consumer's own authority (the shuttle's generate_id.py)
                 asserts `len(cell_insts) == 1` per cell, and "present twice"
                 is a different fact from "present".

WHY THE VERDICT IS NOT "THE SCRIPT EXITED 0"
--------------------------------------------
MEASURED 2026-08-19 on the gf180mcuD PDK shipped in the EDA image: its own
``libs.tech/klayout/tech/scripts/sealring.py`` is present, but the PCell library
it imports (``sealring_cells``) is not shipped in that PDK version. The script
prints ``Error: Couldn't load the seal ring library.`` and calls ``sys.exit()``
— with NO argument, so the process exits **0** and writes **no output file**.
A caller that trusted the exit status would have recorded a seal ring that does
not exist. So the verdict here is a MEASUREMENT of the output layout, never a
report of an exit code.

WHAT "A SEAL RING IS PRESENT" MEANS HERE, and why it is testable
----------------------------------------------------------------
Not "some geometry was added" — a script that dropped a single dot would pass
that. A seal ring is an ANNULUS around the die, so the added geometry is
required to behave like one, measured with no tuned constant and no PDK literal:

  * a horizontal scan line through the die centre crosses the added geometry in
    at least TWO disjoint places (the left and the right run of the ring);
  * a vertical scan line through the die centre likewise (bottom and top);
  * the die centre itself is NOT covered by the added geometry (a ring is
    hollow; a solid slab over the core is not a seal ring).

Those three together cannot be satisfied by a dot, a stripe down one edge, or a
filled block, and they hold for a ring of any thickness, any layer count and any
PDK. Verified on a real PDK-generated ring: 2 horizontal crossings,
2 vertical, centre uncovered.

chip/PDK-AGNOSTIC: every layer this reads is DISCOVERED by diffing the two
layouts. No layer number, vendor, foundry or design name appears here.
"""
import json
import os
import sys

import pya                                                    # noqa: E402


def _spec(layout, li):
    info = layout.get_info(li)
    return f"{info.layer}/{info.datatype}"


def _layer_index(layout, layer, datatype):
    """Index of an EXISTING layer, or None. Never creates one — ``Layout.layer``
    would happily invent an empty layer and make "absent" look like "empty"."""
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer == layer and info.datatype == datatype:
            return li
    return None


def _top(layout, name):
    """The cell to measure, BY NAME when one is known.

    The `top_cells()[0]` fallback alone is not safe on the OUTPUT layout, and
    the failure is silent. MEASURED: a generator that adds a die-identification
    cell without instantiating it under the die leaves the layout with TWO top
    cells, and `top_cells()[0]` can then resolve to the empty one — after which
    the layout diff finds no added geometry and the verifier reports the ring
    as absent on a die that carries it. So the caller resolves the INPUT top
    first and asks for that NAME in the output.
    """
    if name:
        for c in layout.each_cell():
            if c.name == name:
                return c
    tops = layout.top_cells()
    return tops[0] if tops else None


def main():
    src = os.environ.get("SEAL_IN", "")
    dst = os.environ.get("SEAL_OUT", "")
    rep = os.environ.get("SEAL_REPORT", "")
    cell = os.environ.get("SEAL_CELL", "") or None
    marker = os.environ.get("SEAL_MARKER", "") or None
    id_cells = [c.strip() for c in
                (os.environ.get("SEAL_ID_CELLS", "") or "").split(",")
                if c.strip()]

    res = {"check": "pdk_seal_ring_present", "gds_in": src, "gds_out": dst}

    def emit(verdict, reason=None, **extra):
        res["verdict"] = verdict
        if reason:
            res["reason"] = reason
        res.update(extra)
        if rep:
            with open(rep, "w") as fh:
                json.dump(res, fh, indent=2)
        print(json.dumps(res, indent=2))
        return 0 if verdict == "PASS" else 1

    if not (src and dst and rep):
        return emit("FAIL", "SEAL_IN / SEAL_OUT / SEAL_REPORT must all be set")
    if not os.path.isfile(dst):
        return emit("FAIL",
                    "the PDK seal-ring script produced no output layout at "
                    f"{dst} — nothing was added to the die")

    lin = pya.Layout()
    lin.read(src)
    lout = pya.Layout()
    lout.read(dst)
    if id_cells:
        # REPORTED, never judged here: whether the shuttle's die-identification
        # cells are instantiated is a separate question with a separate owner,
        # and folding it into the ring's verdict would make one half's silence
        # look like the other half's failure.
        by_name = {c.name: c for c in lout.each_cell()}
        counts = {}
        for n in id_cells:
            c = by_name.get(n)
            counts[n] = (len(list(c.each_parent_inst())) if c is not None
                         else None)
        res["id_cells"] = counts
    tin = _top(lin, cell)
    if tin is None:
        return emit("FAIL", "could not resolve a top cell in the input layout")
    # BY NAME, always: see `_top`. The output may legitimately have gained
    # cells (die identification, the ring's own cell) and its top-cell ORDER is
    # not a fact about the die.
    tout = _top(lout, cell or tin.name)
    if tout is None:
        return emit("FAIL",
                    f"the sealed layout has no cell named {tin.name!r} — the "
                    "generator did not write back the die it was given")
    res["top_cell"] = tout.name

    # Layer-by-layer difference. `added` is everything present in the OUTPUT
    # that the INPUT did not already carry, discovered rather than declared.
    before = {}
    for li in lin.layer_indexes():
        before[_spec(lin, li)] = pya.Region(tin.begin_shapes_rec(li))
    added = pya.Region()
    per_layer = []
    for li in lout.layer_indexes():
        spec = _spec(lout, li)
        ro = pya.Region(tout.begin_shapes_rec(li))
        delta = ((ro - before[spec]) if spec in before else ro).merged()
        # AFTER the merge, not before: a layer can hold degenerate zero-area
        # shapes that make `is_empty()` False while merging to nothing, and
        # those were being listed as added geometry that is not there.
        if delta.count() == 0:
            continue
        per_layer.append({"layer": spec, "polygons": delta.count(),
                          "area_um2": round(delta.area() * lout.dbu * lout.dbu, 3),
                          "new_layer": spec not in before})
        added += delta
    added = added.merged()
    res["added_layers"] = sorted(p["layer"] for p in per_layer)
    res["added_geometry"] = per_layer
    res["added_area_um2"] = round(added.area() * lout.dbu * lout.dbu, 3)

    if added.is_empty():
        return emit("FAIL",
                    "the PDK seal-ring script ran but added no geometry to the "
                    "die — the output layout is identical to the input")

    # The PDK's own guard-ring MARKER layer, when the caller declared one. This
    # is the only PDK-specific fact in the whole check and it is INPUT, never a
    # literal: absent -> the structural ring test below still decides.
    if marker:
        try:
            ml, md = marker.split("/", 1)
            mi = _layer_index(lout, int(ml), int(md))
        except (ValueError, TypeError):
            mi = None
            res["marker_layer_malformed"] = marker
        if mi is None:
            return emit("FAIL",
                        f"the declared guard-ring marker layer {marker} carries "
                        "no geometry in the sealed layout")
        mcount = pya.Region(tout.begin_shapes_rec(mi)).count()
        res["marker_layer"] = {"spec": marker, "shapes": mcount}
        if mcount == 0:
            return emit("FAIL",
                        f"the declared guard-ring marker layer {marker} carries "
                        "no geometry in the sealed layout")

    # Ring topology — see the module docstring. The centre comes from the die
    # (the INPUT layout); the scan lines span the SEALED bbox, so a ring drawn
    # OUTSIDE the original die box is measured too.
    die = tin.bbox()
    span = tout.bbox() + added.bbox()
    cx = (die.left + die.right) // 2
    cy = (die.bottom + die.top) // 2
    res["die_box_dbu"] = [die.left, die.bottom, die.right, die.top]
    horiz = (added & pya.Region(
        pya.Box(span.left, cy, span.right, cy + 1))).merged().count()
    vert = (added & pya.Region(
        pya.Box(cx, span.bottom, cx + 1, span.top))).merged().count()
    centre = (added & pya.Region(
        pya.Box(cx - 1, cy - 1, cx + 1, cy + 1))).count()
    res["ring"] = {"horizontal_crossings": horiz, "vertical_crossings": vert,
                   "centre_covered": bool(centre)}

    # The ring's OUTER and INNER extents, measured rather than assumed. The
    # inner box is the hole: everything inside the ring's own bounding box that
    # the ring does not occupy. A downstream consumer (the finished-die DEF's
    # placement blockage) needs the band, and deriving it from a nominal ring
    # width would be this program inventing foundry data it was careful not to
    # invent anywhere else. Reported in BOTH dbu and micron so a consumer on a
    # different database unit converts from a real number, not from ours.
    # The INNER edge is read off the same two scan lines the enclosure test
    # already cut, not from a subtraction: `Region(outer_bbox) - added` returns
    # every gap in the union of a multi-layer ring, and its bounding box was
    # MEASURED to come back equal to the outer box on a real PDK ring. The core
    # opening is what a consumer needs, and on each axis that is the gap
    # between the two runs the scan line crossed.
    def _gap(region, lo, hi, mid, horizontal):
        """(inner_lo, inner_hi) of the opening around `mid`, or None."""
        boxes = sorted((pp.bbox() for pp in region.each()),
                       key=lambda b: b.left if horizontal else b.bottom)
        before = [b for b in boxes
                  if (b.right if horizontal else b.top) <= mid]
        after = [b for b in boxes
                 if (b.left if horizontal else b.bottom) >= mid]
        if not before or not after:
            return None
        return (max((b.right if horizontal else b.top) for b in before),
                min((b.left if horizontal else b.bottom) for b in after))

    hcut = (added & pya.Region(
        pya.Box(span.left, cy, span.right, cy + 1))).merged()
    vcut = (added & pya.Region(
        pya.Box(cx, span.bottom, cx + 1, span.top))).merged()
    gx = _gap(hcut, span.left, span.right, cx, True)
    gy = _gap(vcut, span.bottom, span.top, cy, False)
    ob = added.bbox()
    dbu = lout.dbu

    def _box(l, b, r, t):
        return {"dbu": [l, b, r, t],
                "um": [round(l * dbu, 4), round(b * dbu, 4),
                       round(r * dbu, 4), round(t * dbu, 4)]}

    res["ring_extent"] = {
        "outer": _box(ob.left, ob.bottom, ob.right, ob.top),
        "inner": (_box(gx[0], gy[0], gx[1], gy[1]) if gx and gy else None),
    }

    if horiz < 2 or vert < 2:
        return emit("FAIL",
                    "the geometry the PDK script added does not enclose the die: "
                    f"a scan line through the die centre crosses it {horiz} time(s) "
                    f"horizontally and {vert} vertically (a ring crosses twice on "
                    "both axes)")
    if centre:
        return emit("FAIL",
                    "the geometry the PDK script added covers the die centre — "
                    "that is a slab over the core, not a seal ring around it")
    return emit("PASS")


if __name__ == "__main__":
    sys.exit(main())
