#!/usr/bin/env python3
"""metal_fill.py — per-layer density metal-fill on KLayout's native fill engine.

A general, chip/PDK-AGNOSTIC dummy-metal-fill utility. For every metal layer it tiles
the die into density windows, finds the windows below the per-layer target density, and
inserts dummy fill (via KLayout's own C++ ``Region#fill``) to raise them — WITHOUT
creating any new spacing/width/off-grid DRC. This is the FILL emitter the flow was
missing: it had only per-layer density *checkers* (``metal_layer_density_check.py``), so
a sparse die FAILed the CMP density rule and was flagged, not fixed. This tool fixes it,
and is meant to run at STREAMOUT, before sign-off DRC.

Commercial equivalent: Calibre YieldEnhancer / ICC2 metal fill (per-layer dummy metal
insertion for CMP planarity).

DRAWN vs DUMMY DATATYPE (why fill never breaks LVS)
---------------------------------------------------
A foundry density rule measures the *result* metal = drawn signal metal UNION the
dedicated DUMMY-fill datatype (e.g. gf180 ``metal_result = metal_drawn + metal_dummy``),
while the LVS ``connect`` graph uses the DRAWN datatype ONLY. So dummy fill on the
dedicated datatype (a) counts toward the CMP density measurement and (b) is invisible to
LVS — exactly what a real tapeout does. This engine therefore separates:
  * MEASURE layer            = drawn UNION fill-datatype (== the deck's density layer),
  * KEEP-OUT (from drawn)    = ``space_to_metal`` (the deck's dummy-to-circuit rule),
  * KEEP-OUT (from own fill) = ``space`` (the deck's dummy-to-dummy rule),
  * PLACE layer              = the per-layer ``fill_datatype`` (the dummy datatype).
When ``fill_datatype`` equals the drawn datatype the union collapses to the drawn layer
and the two spacings collapse to one (back-compat with single-datatype fill).

DRC-safety (why the fill never violates spacing, width or the manufacturing grid)
---------------------------------------------------------------------------------
* fill cell = a ``width x width`` square, ``width`` snapped to the manufacturing grid
  and >= one grid step                                                  -> on-grid, wide
* keep-out from real metal: fillable = ``window - drawn.sized(space_to_metal)`` — square
  (Chebyshev) sizing, so the euclidean clearance to circuit metal is >= space_to_metal
* keep-out from prior fill: ``… - fill.sized(space)`` + ``fill_margin=(space,space)``
* row/column step = ``pitch >= width + space``, pitch snapped UP to the grid -> fill-to-
  fill euclidean spacing >= space, and every fill edge lands on the manufacturing grid
  (fills anchor at layout origin (0,0), so with an on-grid width and pitch no edge is
  off-grid).

Density guarantee (iterative densify)
-------------------------------------
A single uniform-pitch pass can undershoot (keep-out + margin losses). The tool
DENSIFIES iteratively: each pass re-measures the worst under-target window, recomputes a
tighter pitch to close the remaining deficit, and fills only the still-deficient windows
in the space left between prior fill. It stops when every window reaches the target, when
it hits ``min pitch`` (the physical fill ceiling that the dummy-metal spacing imposes),
or after ``max_passes``. The report states the achieved worst-window density so an
infeasible target is honest, not silently "passed".

Die area == the foundry rule's area
-----------------------------------
The foundry density rule measures coverage over the WHOLE-DIE ``extent`` (the layout
bounding box). This engine measures over the same area: ``boundary_layer`` bbox if
declared + non-empty, else the FULL LAYOUT bbox (``top.bbox()`` == KLayout DRC
``extent``). ``window_um`` null/0 -> the whole die is a SINGLE density window, so the
engine's per-window check is identical to the foundry's whole-die coverage rule.

Config (chip/PDK-AGNOSTIC — every number supplied by the caller / derived from the PDK):
    {
      "boundary_layer": [0, 0],        // optional die-outline layer for the bbox
      "window_um": null,               // null/0 -> single whole-die window (== rule)
      "max_passes": 8,
      "mfg_grid_um": 0.005,            // manufacturing grid; fill snapped to it
      "fill_datatype": null,           // optional GLOBAL dummy-fill datatype override
      "layers": [
        {"name":"metal1","layer":[34,0],"target":0.34,"max":0.95,
         "space":0.98,"space_to_metal":2.0,"width":1.4,"fill_datatype":4}
      ]
    }

Invocation (KLayout has no argv for scripts — parameters come from the environment):
    FILL_GDS=<in.gds> FILL_CONFIG=<cfg.json> FILL_OUT=<out.gds> \
        FILL_REPORT=<report.json> [FILL_CELL=<top>] klayout -b -r metal_fill.py

Output report JSON: per-layer {density_before, density_after, worst_window_before,
worst_window_after, target, reached (bool), fill_shapes, pitch_um[]}.
"""
from __future__ import annotations

import json
import math
import os
import sys


def _load_pya():
    try:
        import pya  # noqa: F401
        return pya
    except Exception:
        sys.stderr.write(
            "metal_fill: KLayout Python module 'pya' not available "
            "(run inside the KLayout fork via `klayout -b -r` or `strmrun`). "
            "DISCLOSED, not faked.\n")
        sys.exit(3)


def _li(ly, spec):
    n, d = int(spec[0]), int(spec[1])
    x = ly.find_layer(n, d)
    return x if x is not None else ly.layer(n, d)


def _windows(bbox, wd):
    """Yield window boxes tiling bbox with edge wd (dbu). wd None -> one whole-die
    window (== the foundry's whole-die coverage rule)."""
    import pya
    if wd is None:
        yield pya.Box(bbox.left, bbox.bottom, bbox.right, bbox.top)
        return
    x = bbox.left
    while x < bbox.right:
        y = bbox.bottom
        while y < bbox.top:
            yield pya.Box(x, y, min(x + wd, bbox.right), min(y + wd, bbox.top))
            y += wd
        x += wd


def _worst_window_density(metal, bbox, wd):
    import pya
    worst = 1.0
    for wb in _windows(bbox, wd):
        a = wb.area()
        if a <= 0:
            continue
        d = (metal & pya.Region(wb)).area() / float(a)
        worst = min(worst, d)
    return worst


def fill_layer(ly, top, spec, wd, max_passes, fill_dt, grid_dbu):
    import pya
    dbu = ly.dbu
    lidx = _li(ly, spec["layer"])                      # drawn / signal metal
    target = float(spec["target"])
    maxd = float(spec.get("max", 1.0))
    space = float(spec["space"])                       # fill-to-fill (dummy-to-dummy)
    space_m = float(spec.get("space_to_metal", space))  # fill-to-circuit (dummy-to-drawn)
    width = float(spec["width"])

    def _snap_near(v):
        return v if grid_dbu <= 1 else int(round(v / grid_dbu)) * grid_dbu

    def _snap_up(v):
        return v if grid_dbu <= 1 else int(math.ceil(v / grid_dbu)) * grid_dbu

    sp = int(round(space / dbu))                       # fill-to-fill sizing (dbu)
    spm = int(round(space_m / dbu))                    # fill-to-drawn sizing (dbu)
    top_fwd = max(_snap_near(int(round(width / dbu))), grid_dbu)   # on-grid top width

    # Fill-size LADDER (large -> small). Large squares fill open regions at a high open-
    # area ceiling (w^2/(w+space)^2, which RISES with w since `space` is fixed by the
    # dummy-metal rule); progressively smaller squares then pack the channels the big
    # squares cannot enter. The floor is the smallest square that still clears the
    # target in an open area, so a small square never lowers a window below target.
    _r = math.sqrt(min(target, 0.999))
    floor_um = space * _r / (1.0 - _r) if _r < 1.0 else width
    floor_fwd = max(_snap_up(int(round(floor_um / dbu))), grid_dbu)
    ladder = []
    cw = max(top_fwd, floor_fwd)
    while cw > floor_fwd:
        ladder.append(cw)
        cw = _snap_near(int(cw * 0.5))
    ladder.append(floor_fwd)

    drawn_dt = int(spec["layer"][1])
    if spec.get("fill_datatype") is not None:
        fdt = int(spec["fill_datatype"])
    elif fill_dt is not None:
        fdt = int(fill_dt)
    else:
        fdt = drawn_dt
    fill_lidx = _li(ly, [spec["layer"][0], fdt])       # dummy / fill placement layer
    separate = (fdt != drawn_dt)

    drawn = pya.Region(top.begin_shapes_rec(lidx)).merged()  # circuit metal (constant)
    drawn_block = drawn.sized(spm)                     # keep-out from real metal
    # Declared keep-out (seal ring / scribe band). Unioned into the SAME
    # blocked region the circuit metal uses, so every fill pass on every ladder
    # rung honours it — there is no path into `fillable` that bypasses this.
    _ko = spec.get("_keepout")
    if _ko is not None and not _ko.is_empty():
        drawn_block = (drawn_block + _ko).merged()

    #: Shapes already on the drawn layer before any fill. In the SHARED-datatype
    #: case the fill is indistinguishable from circuit metal afterwards, so the
    #: fill count is only recoverable as a difference against this.
    n_drawn0 = sum(1 for _ in top.begin_shapes_rec(lidx))

    def _fill_now():
        """Current contents of the fill layer, RE-READ from the layout.

        When `fill_datatype` equals the drawn datatype, `fill_lidx is lidx` and
        this returns drawn+fill — which is exactly what the density target is
        stated against.

        This used to return the `drawn` SNAPSHOT in that case. `drawn` is
        captured once and never changes, so the engine could not observe its own
        fill: `_measure()` returned the same object before and after, the
        in-loop `worst` never rose, `reached_target` never became True, and
        every layer reported `density_after == density_before`. The gate then
        FAILed a fill that had worked — measured on the 50x50um fixture, where
        the emitted GDS reaches 0.675 against a 0.3 target while the report said
        0.0368. A check that cannot pass is the same defect as one that cannot
        fail, and it hid here because the fill and the verdict disagreed only in
        a file nobody re-opened.
        """
        return pya.Region(top.begin_shapes_rec(fill_lidx)).merged()

    def _measure():
        return (drawn + _fill_now()).merged() if separate else _fill_now()

    boundary = spec.get("_bbox")
    metal0 = _measure()
    bbox = boundary if boundary is not None else metal0.bbox()
    if bbox.area() <= 0:
        return {"name": spec["name"], "skipped": "empty bbox"}

    d_before = metal0.area() / float(bbox.area())
    worst_before = _worst_window_density(metal0, bbox, wd)

    pitches = []
    reached_target = False
    for si, cur_fwd in enumerate(ladder):
        if reached_target:
            break
        cur_w_um = cur_fwd * dbu
        min_pitch = _snap_up(cur_fwd + sp)
        # a SEPARATE cell per size: mutating one cell would retroactively resize the
        # fills already placed from it.
        fcell = ly.create_cell(f"FILL_{spec['name']}_{si}")
        fcell.shapes(fill_lidx).insert(pya.Box(0, 0, cur_fwd, cur_fwd))
        fcbox = pya.Box(0, 0, cur_fwd, cur_fwd)
        for _pass in range(max_passes):
            fill_r = _fill_now()
            # Non-separate: `fill_r` IS the re-read layer, so it already
            # carries the fill this loop placed. Reading `drawn` here made
            # the convergence test blind to its own progress.
            metal = (drawn + fill_r).merged() if separate else fill_r
            fill_zone = pya.Region()
            worst = 1.0
            for wb in _windows(bbox, wd):
                a = wb.area()
                if a <= 0:
                    continue
                d = (metal & pya.Region(wb)).area() / float(a)
                worst = min(worst, d)
                if d < target:
                    fill_zone.insert(wb)
            if fill_zone.is_empty() or worst >= target:
                reached_target = True
                break
            fill_zone.merge()
            # Keep out of ALREADY-PLACED fill too, not just circuit metal:
            # in the shared-datatype case `fill_r` now includes it.
            blocked = drawn_block + fill_r.sized(sp)
            fillable = fill_zone - blocked
            if fillable.is_empty():
                break                                   # this size cannot fit -> smaller
            zone_area = float(fill_zone.area())
            frac_fillable = fillable.area() / zone_area if zone_area > 0 else 0.0
            deficit = max(target - worst, 0.0)
            headroom = 1.35
            if deficit > 0 and frac_fillable > 0:
                p_um = cur_w_um * math.sqrt(frac_fillable / (deficit * headroom))
            else:
                p_um = cur_w_um + space
            p = max(_snap_up(int(round(p_um / dbu))), min_pitch)
            pitches.append(round(p * dbu, 4))
            n_before = sum(1 for _ in top.begin_shapes_rec(fill_lidx))
            fillable.fill(top, fcell.cell_index(), fcbox,
                          pya.Vector(p, 0), pya.Vector(0, p),
                          pya.Point(0, 0), None, pya.Vector(sp, sp))
            if sum(1 for _ in top.begin_shapes_rec(fill_lidx)) == n_before:
                break                                   # size saturated -> go smaller

    metal_after = _measure()
    d_after = metal_after.area() / float(bbox.area())
    worst_after = _worst_window_density(metal_after, bbox, wd)
    # Shared-datatype fill is not separable by layer, but it IS countable as a
    # difference against the pre-fill census — so this reports a number rather
    # than `null`, which read as "not measured" for the case that needs it most.
    fill_shapes = (sum(1 for _ in top.begin_shapes_rec(fill_lidx)) if separate
                   else sum(1 for _ in top.begin_shapes_rec(lidx)) - n_drawn0)
    return {
        "name": spec["name"],
        "target": target, "max": maxd,
        "density_before": round(d_before, 4), "density_after": round(d_after, 4),
        "worst_window_before": round(worst_before, 4),
        "worst_window_after": round(worst_after, 4),
        "reached": bool(worst_after >= target - 1e-9),
        "over_max": bool(d_after > maxd + 1e-9),
        "passes": len(pitches), "pitch_um": pitches,
        "fill_datatype": fdt, "fill_shapes": fill_shapes,
        "space_um": space, "space_to_metal_um": space_m,
        "top_width_um": round(top_fwd * dbu, 4),
        "min_width_um": round(floor_fwd * dbu, 4),
        "fill_sizes": len(ladder),
    }


def run(gds, cfg, out_gds, cell_name=None):
    pya = _load_pya()
    ly = pya.Layout()
    ly.read(gds)
    top = ly.cell(cell_name) if cell_name else ly.top_cell()
    if top is None:
        return {"verdict": "ERROR", "error": f"top cell not found: {cell_name}"}

    max_passes = int(cfg.get("max_passes", 8))
    fill_dt = cfg.get("fill_datatype")
    mfg_grid_um = cfg.get("mfg_grid_um")
    grid_dbu = max(int(round(float(mfg_grid_um) / ly.dbu)), 1) if mfg_grid_um else 1

    bbox = None
    bl = cfg.get("boundary_layer")
    if bl is not None:
        br = pya.Region(top.begin_shapes_rec(_li(ly, bl)))
        if not br.is_empty():
            bbox = br.bbox()
    if bbox is None:
        bbox = top.bbox()

    wu = cfg.get("window_um", None)
    wd = None if wu in (None, 0, 0.0) else int(round(float(wu) / ly.dbu))

    # === KEEP-OUT — the region the fill may not enter =======================
    # This engine had none. It tiled every window of the measurement bbox that
    # was under target, keeping out only of CIRCUIT metal on the same layer. On
    # a bare die that is right. On a FINISHED die it is not: the seal ring is
    # drawn at the die edge, it is not circuit metal, and its rules are about
    # the ring's own structure — a dummy square dropped beside it violates them
    # even though it clears every ordinary spacing rule. MEASURED on this
    # design's sealed die: sign-off DRC 1177 -> 18686 with the fill on.
    #
    # The PDK's own `fill_all.rb` solves the same problem by subtracting a
    # fixed scribe ring. Two declared forms are supported here, and BOTH are
    # data — the engine still contains no geometry of its own:
    #
    #   keepout_layers: [[layer, datatype, margin_um], ...]
    #       Subtract the geometry ON a declared layer, grown by margin_um. The
    #       exact form when the PDK ships a marker for the band (the guard-ring
    #       marker the operator's size check already requires to be non-empty),
    #       because it follows the ring the generator actually drew instead of
    #       assuming where it went.
    #
    #   keepout_edge_um: <float>
    #       Subtract a band of this width inside the measurement bbox — the
    #       `fill_all.rb` form, for a PDK that ships no marker.
    #
    # The measurement bbox is NOT changed by either. The foundry's density rule
    # measures over the whole die, so shrinking the denominator to make the
    # numbers look better would be exactly the kind of dishonesty this file's
    # docstring already refuses elsewhere. A keep-out therefore makes the
    # reported density HARDER to reach, and an unreachable target stays
    # visible as `reached: false`.
    keepout = pya.Region()
    keepout_note = []
    for ko in (cfg.get("keepout_layers") or []):
        try:
            kl, kdt = int(ko[0]), int(ko[1])
            kmargin = float(ko[2]) if len(ko) > 2 else 0.0
        except Exception:
            continue
        kr = pya.Region(top.begin_shapes_rec(_li(ly, [kl, kdt]))).merged()
        if kr.is_empty():
            keepout_note.append(f"{kl}/{kdt}:EMPTY")
            continue
        if kmargin > 0:
            kr = kr.sized(int(round(kmargin / ly.dbu)))
        keepout += kr
        keepout_note.append(f"{kl}/{kdt}+{kmargin}um")
    edge = cfg.get("keepout_edge_um")
    if edge:
        e = int(round(float(edge) / ly.dbu))
        inner = pya.Box(bbox.left + e, bbox.bottom + e,
                        bbox.right - e, bbox.top - e)
        if inner.width() > 0 and inner.height() > 0:
            keepout += (pya.Region(bbox) - pya.Region(inner))
            keepout_note.append(f"edge:{edge}um")
        else:
            keepout_note.append(f"edge:{edge}um:DEGENERATE")
    keepout = keepout.merged()

    layers = []
    for spec in cfg["layers"]:
        spec = dict(spec)
        spec["_bbox"] = bbox
        spec["_keepout"] = keepout
        layers.append(fill_layer(ly, top, spec, wd, max_passes, fill_dt, grid_dbu))

    # A FILL CELL THAT WAS NEVER PLACED IS A SECOND TOP CELL, AND A SECOND TOP
    # CELL STOPS SIGN-OFF DRC FROM RUNNING AT ALL.
    #
    # `fill_layer` creates one `FILL_<layer>_<size>` cell per ladder rung BEFORE
    # it knows whether that rung fits anywhere. When a rung places nothing - the
    # square is larger than any fillable channel on that layer - the cell stays
    # in the layout with zero instances, and GDS has no notion of an "unused"
    # cell: it is simply another root. gf180mcu's own sign-off deck then refuses
    # the file outright, before a single rule executes:
    #
    #   ERROR: In .../gf180mcu.drc: 'source': The layout has multiple top cells
    #          in Layout::top_cell
    #
    # MEASURED (r8, KLayout 0.30.10): a fill whose top rung did not fit on
    # metal4 left `FILL_metal4_4` and `FILL_metal4_3` in the stream with
    # `instances: 0`, and `klayout -b -r gf180mcu.drc` aborted with the error
    # above and wrote NO report. A DRC that cannot start is indistinguishable
    # from one that found nothing, so the failure mode is an ABSENT verdict,
    # not a red one.
    #
    # Prune only cells this program created, and only when they were never
    # instanced; a fill that placed something is byte-identical.
    pruned = []
    for _c in list(ly.each_cell()):
        _n = _c.name
        if not _n.startswith("FILL_"):
            continue
        if _c.parent_cells() == 0:
            pruned.append(_n)
            ly.delete_cell(_c.cell_index())
    ly.write(out_gds)
    reached_all = all(l.get("reached", False) for l in layers if "skipped" not in l)
    return {"verdict": "PASS" if reached_all else "PARTIAL",
            "gds_in": gds, "gds_out": out_gds,
            "window_um": cfg.get("window_um"), "mfg_grid_um": mfg_grid_um,
            # The keep-out is REPORTED, not just applied. A reader has to be
            # able to tell a fill that respected the seal ring from one that
            # was simply never asked to, and "the config had the key" is not
            # the same claim as "the geometry was there and was subtracted" —
            # so an EMPTY declared keep-out layer says so by name.
            "keepout": {"declared": bool(cfg.get("keepout_layers")
                                         or cfg.get("keepout_edge_um")),
                        "sources": keepout_note,
                        "area_um2": round(keepout.area() * ly.dbu * ly.dbu, 3),
                        "measurement_bbox_um": [
                            round(bbox.left * ly.dbu, 3),
                            round(bbox.bottom * ly.dbu, 3),
                            round(bbox.right * ly.dbu, 3),
                            round(bbox.top * ly.dbu, 3)]},
            "unplaced_fill_cells_pruned": pruned,
            "layers": layers}


def main():
    gds = os.environ.get("FILL_GDS")
    cfg_path = os.environ.get("FILL_CONFIG")
    out = os.environ.get("FILL_OUT")
    report = os.environ.get("FILL_REPORT")
    cell = os.environ.get("FILL_CELL") or None
    if not gds or not cfg_path or not out:
        sys.stderr.write("metal_fill: set FILL_GDS, FILL_CONFIG, FILL_OUT "
                         "(and FILL_REPORT).\n")
        return 2
    with open(cfg_path) as f:
        cfg = json.load(f)
    res = run(gds, cfg, out, cell)
    text = json.dumps(res, indent=2)
    if report:
        with open(report, "w") as f:
            f.write(text)
    print(text)
    return 0 if res["verdict"] == "PASS" else (1 if res["verdict"] == "PARTIAL" else 2)


if __name__ == "__main__":
    sys.exit(main())
