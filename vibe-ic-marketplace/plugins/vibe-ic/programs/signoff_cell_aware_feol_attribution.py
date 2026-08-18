#!/usr/bin/env python3
"""
signoff_cell_aware_feol_attribution.py -- CELL-AWARE FEOL over-fire attributor.

DISCLOSURE-ONLY. This program NEVER changes a DRC verdict and NEVER waives a
violation. It ATTRIBUTES firing FEOL device-layer space/notch violations into
two classes so an operator gets an accurate root-cause instead of an opaque
"must-fix geometry":

  (a) QUALIFIED-CELL-INTERIOR artifact  -- the violation lies entirely inside the
      union of PLACED, STANDALONE-QUALIFIED cell-master footprints. On a dense
      digital design a foundry std-cell library's FEOL (implant / poly / active /
      well) merges across abutment; each master passes the sign-off deck STANDALONE
      (verify with `svrfdrc <deck> <lib> <rpt> --cell=<master>`), so an abutment
      space/notch between two qualified masters is a flat-flow artifact, NOT a
      backend defect. The foundry sign-off flow exempts these with the deck's
      qualified-cell exclusion marker (drawn on the library GDS) -- input the
      library ships WITHOUT here.

  (b) TOP-LEVEL / non-qualified  -- the violation is NOT contained in a qualified
      footprint (backend geometry, or a master that does NOT pass standalone). This
      is a real / unproven violation. It stays FAIL, always.

WHY THIS IS DISCLOSURE-ONLY (and not a waiver): a FLAT exclusion marker cannot
clear class (a) without carving routing, because on a real commercial deck the
SINGLE don't-check marker (`__x__ = NOT X <marker>`) derives BOTH the implant
AND the metal checked-forms -- so a marker pixel over a routed wire waives its
metal DRC and splits it into min-width slivers (a #511 over-waive). Measured on
the reference deck: 100% of the implant over-fires have routed metal directly
overlapping them, so NO flat-marker paint can exempt them. The correct fix is a
CELL-AWARE (per-master-provenance) exemption inside the DRC ENGINE, where each
violating edge's source cell is known exactly. This program reproduces that
attribution on the HOST (from the DEF placement + library GDS) so the failure is
ACCURATELY DISCLOSED today; it is the reference oracle for the engine fork.

The host footprint is the qualified-master BBOX union grown by an abutment
overhang; it is COARSE (over-inclusive) by design -- a class-(a) label is a
"candidate artifact", never a waiver. The engine fork replaces the bbox proxy
with exact per-shape cell provenance.

chip-AGNOSTIC: FEOL layer numbers are DERIVED from the deck / passed by the
caller; masters come from the DEF; no vendor / IC / SKU / cell literal appears
in this file.

Usage:
    python3 signoff_cell_aware_feol_attribution.py \
        --design <flat.gds> --lib <library.gds> --def <placed.def> \
        --top <TOP> --qualified <m1,m2,...|@file> \
        --feol 4/0,5/0 --space-um 0.26 [--metal 9/0,11/0,...] \
        [--overhang-um 0.2] [--json out.json]

Exit codes:
    0  ran and wrote attribution (NOT a verdict -- disclosure only)
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# DEF orientation -> KLayout Trans(rot_code, mirror). mirror mirrors about the
# X-axis (y -> -y) BEFORE the rotation, matching KLayout's convention.
_DEF_ORIENT = {
    "N": (0, False), "S": (2, False), "FN": (0, True), "FS": (2, True),
    "E": (1, False), "W": (3, False), "FE": (1, True), "FW": (3, True),
}

# The placement status may be preceded by optional `+ SOURCE {DIST|NETLIST|USER|
# TIMING}` / `+ EEQMASTER ...` clauses (router-inserted fillers/decaps carry
# `+ SOURCE DIST`), so match non-greedily up to the placement WITHOUT crossing the
# record `;` terminator. The prior regex required PLACED to immediately follow the
# master and silently dropped every `+ SOURCE ...` component -> a placed-master
# undercount that shrank the qualified-cell footprint (candidate over-fires then
# mis-attributed as top-level). COVER placement is accepted alongside PLACED/FIXED.
_COMP_RE = re.compile(
    r"-\s+(\S+)\s+(\S+)\b[^;]*?\+\s+(?:PLACED|FIXED|COVER)\s*"
    r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)")


def parse_layerlist(spec: str) -> List[Tuple[int, int]]:
    """"4/0,5/0" -> [(4,0),(5,0)]. Empty -> []."""
    out: List[Tuple[int, int]] = []
    for tok in (spec or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        l, _, d = tok.partition("/")
        out.append((int(l), int(d or "0")))
    return out


def parse_def_components(def_path: str) -> List[Tuple[str, str, int, int, str]]:
    """Return [(inst, master, x, y, orient)] for every PLACED/FIXED component."""
    txt = Path(def_path).read_text(errors="ignore")
    return [(m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), m.group(5))
            for m in _COMP_RE.finditer(txt)]


def _load_qualified(spec: str) -> set:
    if spec.startswith("@"):
        raw = Path(spec[1:]).read_text()
        return {t for t in re.split(r"[\s,]+", raw) if t}
    return {t for t in re.split(r"[\s,]+", spec) if t}


def attribute(design_gds: str, lib_gds: str, def_path: str, top: str,
              qualified: Sequence[str], feol_layers: Sequence[Tuple[int, int]],
              space_um: float, overhang_um: float = 0.2,
              metal_layers: Optional[Sequence[Tuple[int, int]]] = None
              ) -> Dict:
    """Pure-geometry attribution. Returns a dict per FEOL layer with total
    violations, qualified-cell-interior candidate count, top-level remainder,
    and (if metal given) how many over-fires have routed metal overlapping
    them (the flat-marker-cannot-exempt corroboration).

    Import-time dependency on `pya` (KLayout) is deferred to call time so the
    module imports for unit-collection even where pya is absent."""
    import pya  # noqa: E402  (KLayout python; present in the sign-off image)

    qualified = set(qualified)
    metal_layers = list(metal_layers or [])

    ly = pya.Layout()
    ly.read(design_gds)
    tcell = ly.cell(top)
    if tcell is None:
        raise ValueError(f"top cell {top!r} not in {design_gds}")
    dbu = ly.dbu
    space_dbu = int(round(space_um / dbu))
    overhang_dbu = int(round(overhang_um / dbu))

    def _flat(layout, cell, layers):
        r = pya.Region()
        for (l, d) in layers:
            r.insert(cell.begin_shapes_rec(layout.layer(pya.LayerInfo(l, d))))
        r.merge()
        return r

    metal = _flat(ly, tcell, metal_layers) if metal_layers else pya.Region()

    # qualified-master footprint = union of placed qualified-master bboxes,
    # grown by the abutment overhang. bbox (not per-shape implant) keeps the
    # footprint robust to DEF-reparse transform drift; it is intentionally
    # over-inclusive -> a "candidate" label, never a waiver.
    lib = pya.Layout()
    lib.read(lib_gds)
    lib_bbox = {c.name: c.bbox() for c in lib.each_cell()}
    foot_qual = pya.Region()
    n_qual_inst = 0
    for _inst, master, x, y, orient in parse_def_components(def_path):
        bb = lib_bbox.get(master)
        if bb is None or bb.empty() or master not in qualified:
            continue
        rot, mir = _DEF_ORIENT.get(orient, (0, False))
        tr = pya.Trans(pya.Vector(x, y)) * pya.Trans(rot, mir)
        foot_qual.insert(tr * bb)
        n_qual_inst += 1
    foot_qual = foot_qual.sized(overhang_dbu)
    foot_qual.merge()

    per_layer = []
    tot = tot_art = tot_top = tot_metal = 0
    for (l, d) in feol_layers:
        imp = _flat(ly, tcell, [(l, d)])
        viol = imp.space_check(space_dbu, False, pya.Region.Euclidian, 90).polygons()
        viol.merge()
        n = viol.count()
        artifact = topvl = metalov = 0
        for p in viol.each():
            pr = pya.Region(p)
            interior = (pr - foot_qual).is_empty()
            if interior:
                artifact += 1
            else:
                topvl += 1
            if metal_layers and pr.interacting(metal).count():
                metalov += 1
        per_layer.append({
            "layer": f"{l}/{d}", "space_um": space_um,
            "violations": n, "qualified_cell_interior_candidate": artifact,
            "top_level_or_unqualified": topvl,
            "metal_overlapping": metalov})
        tot += n
        tot_art += artifact
        tot_top += topvl
        tot_metal += metalov

    return {
        "top": top, "dbu": dbu,
        "qualified_masters": sorted(qualified),
        "qualified_instances_placed": n_qual_inst,
        "overhang_um": overhang_um,
        "per_layer": per_layer,
        "totals": {
            "feol_space_violations": tot,
            "qualified_cell_interior_candidate": tot_art,
            "top_level_or_unqualified": tot_top,
            "metal_overlapping": tot_metal},
        "flat_marker_can_exempt": (tot_metal == 0 and tot_art > 0),
        "disclosure_only": True,
        "note": ("Attribution is DISCLOSURE-ONLY: it NEVER changes the DRC "
                 "verdict and NEVER waives a violation. A qualified-cell-"
                 "interior candidate needs a marker-bearing library GDS or a "
                 "cell-aware (per-master-provenance) sign-off in the DRC "
                 "engine; a flat exclusion marker cannot exempt any over-fire "
                 "that has routed metal overlapping it (metal_overlapping)."),
    }


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", required=True, help="flat design GDS")
    ap.add_argument("--lib", required=True, help="library (cell master) GDS")
    ap.add_argument("--def", dest="def_path", required=True, help="placed DEF")
    ap.add_argument("--top", required=True, help="top cell name")
    ap.add_argument("--qualified", required=True,
                    help="comma/space list of standalone-qualified masters, "
                         "or @file")
    ap.add_argument("--feol", required=True,
                    help="FEOL device layers to check, e.g. 4/0,5/0")
    ap.add_argument("--space-um", type=float, required=True,
                    help="space/notch rule threshold in microns")
    ap.add_argument("--metal", default="",
                    help="routing metal layers (corroborates flat-marker "
                         "inadequacy), e.g. 9/0,11/0,13/0,15/0")
    ap.add_argument("--overhang-um", type=float, default=0.2,
                    help="abutment overhang grown onto master bboxes")
    ap.add_argument("--json", dest="json_out", default=None)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ap = _build_argparser()
    args = ap.parse_args(argv)
    try:
        res = attribute(
            args.design, args.lib, args.def_path, args.top,
            _load_qualified(args.qualified),
            parse_layerlist(args.feol), args.space_um,
            overhang_um=args.overhang_um,
            metal_layers=parse_layerlist(args.metal))
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    t = res["totals"]
    print(f"CELL-AWARE FEOL ATTRIBUTION (DISCLOSURE ONLY -- not a verdict)")
    print(f"  qualified masters placed: {res['qualified_instances_placed']}")
    for pl in res["per_layer"]:
        print(f"  layer {pl['layer']} space<{pl['space_um']}um: "
              f"{pl['violations']} viol -> "
              f"{pl['qualified_cell_interior_candidate']} qualified-cell-interior "
              f"candidate, {pl['top_level_or_unqualified']} top-level/unqualified "
              f"(metal-overlapping {pl['metal_overlapping']})")
    print(f"  TOTAL: {t['feol_space_violations']} FEOL over-fires -> "
          f"{t['qualified_cell_interior_candidate']} candidate artifact(s), "
          f"{t['top_level_or_unqualified']} real/unproven; "
          f"metal-overlapping {t['metal_overlapping']}")
    print(f"  flat-marker CAN exempt these: {res['flat_marker_can_exempt']} "
          f"(False => needs cell-aware engine sign-off)")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
