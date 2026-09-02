#!/usr/bin/env python3
"""_metal_fill_capacity.py — how much of the die can LEGAL dummy fill reach?

WHY THIS EXISTS (subservient x gf180mcuD, round 3, 2026-09-02)
--------------------------------------------------------------
The density fill reached metal2 22.6% / metal3 25.0% against a foundry
coverage rule of 30% over the entire die, on a 416x416 um die whose signal
routing covers 8.9% / 10.2% of those layers. The report said only "target NOT
reached" and the sign-off DRC said only "M2.4 / M3.4". Nothing in the run
answered the question a reader asks next: COULD any legal fill have reached
30%? MEASURED on that die, with the deck's own dummy-to-circuit clearance
(2 um) applied to the routed metal: the region where dummy metal may legally
exist is 29.8% (metal2) / 30.8% (metal3) of the die. A fill lattice of squares
of width w at spacing s covers at most (w/(w+s))^2 of the region it is laid
in — 60% for this config's widest shape — so the ceiling is
    drawn 8.9% + 0.60 x 29.8% = 26.7%  (metal2)     < 30%
and the PDK's own fill recipe (2x2 um squares, 1.2 um lines) does worse
(19-20%). The rule is out of reach of fill on this layout; only the ROUTED
metal (a denser die, or more of it) can move it. A FAIL that says that is
diagnosed; one that does not is merely repeated.

WHAT THIS MEASURES, per configured layer, on the filled (or unfilled) GDS:
  drawn_frac    routed/drawn metal on the layer, as a fraction of the die
  dummy_frac    dummy fill present, same basis
  free_frac     die MINUS drawn metal grown by the config's `space_to_metal`
                (the deck's dummy-to-circuit rule) MINUS the config's keep-out
                regions grown by their margins — where dummy metal may exist
  packing_achieved   dummy_frac / free_frac (how well the fill used the room)
  absolute_ceiling   drawn_frac + free_frac (all room solid metal — never legal
                     for a wide-metal-ruled layer, an upper bound only)
  lattice_ceiling    drawn_frac + free_frac x (w/(w+s))^2 for the config's
                     `width`/`space` — the best a square lattice of that
                     shape can do in open field; fragmented room does worse
  floor, reachable_by_lattice, reachable_absolute

Nothing here waives, fills, or edits geometry; it reads the layout and the
config the fill already used and writes one JSON. chip/PDK-AGNOSTIC: every
layer number, clearance and width comes from the fill config the PDK's own
deck was parsed into.

    FILL_GDS=<gds> FILL_CONFIG=<cfg.json> FILL_CAPACITY_REPORT=<out.json> \
        [FILL_CELL=<top>] klayout -b -r _metal_fill_capacity.py

`lattice_ceiling` is pure Python and importable on any host (no pya).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional


def lattice_ceiling(drawn_frac: float, free_frac: float,
                    width_um: float, space_um: float) -> Optional[Dict[str, float]]:
    """Best coverage a square lattice (width w, spacing s) laid in the free
    region can reach, plus the drawn metal already there. None when the
    config carries no usable width/space."""
    try:
        w, s = float(width_um), float(space_um)
    except (TypeError, ValueError):
        return None
    if w <= 0 or s < 0:
        return None
    packing = (w / (w + s)) ** 2
    return {"packing": packing,
            "ceiling": float(drawn_frac) + float(free_frac) * packing}


def _floor_frac(cfg: Dict[str, Any]) -> Optional[float]:
    der = cfg.get("_derivation") if isinstance(cfg, dict) else None
    pct = der.get("density_floor_pct") if isinstance(der, dict) else None
    if isinstance(pct, (int, float)) and not isinstance(pct, bool) \
            and 0.0 < float(pct) < 100.0:
        return float(pct) / 100.0
    return None


def measure(gds: str, cfg: Dict[str, Any], cell: Optional[str] = None
            ) -> Dict[str, Any]:
    import pya  # KLayout batch only

    ly = pya.Layout()
    ly.read(gds)
    top = ly.cell(cell) if cell else ly.top_cell()
    if top is None:
        raise RuntimeError(f"top cell {cell!r} not found in {gds}")
    dbu = ly.dbu
    ext = pya.Region(top.bbox())
    die = float(ext.area())
    if die <= 0:
        raise RuntimeError("empty layout extent")

    def um(x: float) -> int:
        return int(round(float(x) / dbu))

    keep = pya.Region()
    keep_used: List[Dict[str, Any]] = []
    for k in cfg.get("keepout_layers") or []:
        try:
            n, dt, margin = int(k[0]), int(k[1]), float(k[2])
        except (TypeError, ValueError, IndexError):
            continue
        li = ly.find_layer(n, dt)
        if li is None:
            continue
        r = pya.Region(top.begin_shapes_rec(li))
        r.merge()
        if r.is_empty():
            continue
        keep += r.sized(um(margin))
        keep_used.append({"layer": [n, dt], "margin_um": margin,
                          "area_frac": r.area() / die})
    keep.merge()

    floor = _floor_frac(cfg)
    layers: List[Dict[str, Any]] = []
    for spec in cfg.get("layers") or []:
        try:
            n, dt = int(spec["layer"][0]), int(spec["layer"][1])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        li = ly.find_layer(n, dt)
        drawn = pya.Region(top.begin_shapes_rec(li)) if li is not None else pya.Region()
        drawn.merge()
        dummy = pya.Region()
        fdt = spec.get("fill_datatype")
        if fdt is not None:
            lf = ly.find_layer(n, int(fdt))
            if lf is not None:
                dummy = pya.Region(top.begin_shapes_rec(lf))
                dummy.merge()
        s2m = float(spec.get("space_to_metal") or spec.get("space") or 0.0)
        free = ext - drawn.sized(um(s2m)) - keep
        free.merge()
        drawn_frac = drawn.area() / die
        dummy_frac = dummy.area() / die
        free_frac = free.area() / die
        lc = lattice_ceiling(drawn_frac, free_frac,
                             float(spec.get("width") or 0.0),
                             float(spec.get("space") or 0.0))
        row: Dict[str, Any] = {
            "name": spec.get("name"),
            "layer": [n, dt],
            "fill_datatype": fdt,
            "space_to_metal_um": s2m,
            "width_um": spec.get("width"),
            "space_um": spec.get("space"),
            "drawn_frac": round(drawn_frac, 6),
            "dummy_frac": round(dummy_frac, 6),
            "free_frac": round(free_frac, 6),
            "packing_achieved": (round(dummy.area() / free.area(), 6)
                                 if free.area() > 0 else None),
            "absolute_ceiling": round(drawn_frac + free_frac, 6),
            "lattice_packing": round(lc["packing"], 6) if lc else None,
            "lattice_ceiling": round(lc["ceiling"], 6) if lc else None,
            "floor": floor,
        }
        if floor is not None:
            row["reachable_absolute"] = bool(drawn_frac + free_frac >= floor)
            row["reachable_by_lattice"] = (bool(lc["ceiling"] >= floor)
                                          if lc else None)
        layers.append(row)
    return {
        "program": "_metal_fill_capacity",
        "gds": gds,
        "top": top.name,
        "die_area_um2": die * dbu * dbu,
        "keepout_regions_applied": keep_used,
        "floor": floor,
        "layers": layers,
        "reading": ("free_frac is where dummy metal may legally exist under "
                    "the config's dummy-to-circuit clearance; a layer whose "
                    "lattice_ceiling is below floor cannot be closed by this "
                    "fill lattice — only the drawn metal can move it"),
    }


def main() -> int:
    gds = os.environ.get("FILL_GDS")
    cfg_path = os.environ.get("FILL_CONFIG")
    out = os.environ.get("FILL_CAPACITY_REPORT")
    cell = os.environ.get("FILL_CELL") or None
    if not (gds and cfg_path and out):
        sys.stderr.write("_metal_fill_capacity: set FILL_GDS, FILL_CONFIG, "
                         "FILL_CAPACITY_REPORT.\n")
        return 2
    try:
        with open(cfg_path) as fh:
            cfg = json.load(fh)
        res = measure(gds, cfg, cell)
    except Exception as exc:  # noqa: BLE001 — a diagnostic must not crash the run
        res = {"program": "_metal_fill_capacity", "error": repr(exc), "gds": gds}
    with open(out, "w") as fh:
        json.dump(res, fh, indent=2)
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    rc = main()
    # Under `klayout -b -r` an exit code is a batch abort; report through the file.
    if "pya" not in sys.modules:
        sys.exit(rc)
