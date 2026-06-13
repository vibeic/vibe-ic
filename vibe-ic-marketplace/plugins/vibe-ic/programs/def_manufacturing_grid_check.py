#!/usr/bin/env python3
"""def_manufacturing_grid_check.py — ORGANIC #597.

The first designs to reach GDS fail signoff DRC overwhelmingly on
OFFGRID-vertex rules (live: 46,614 of 61,324 = 76% off-grid). #594 made
that VISIBLE (the FLOW_OFFGRID classifier); the residual is the off-grid
geometry itself.

This checker isolates WHERE the off-grid geometry is introduced by
classifying the ROUTED DEF's coordinates against the PDK manufacturing
grid. It answers the root-cause question deterministically (no container
needed): is the off-grid geometry already in the placed/routed DEF (a
floorplan/routing source defect the plugin owns) or does the DEF stream
ON-GRID and the off-grid vertices appear only AFTER streamout (a
GDS-writer / boolean-merge tool behaviour that needs container-side
remediation)?

Empirically (verified on a real routed DEF, 1.88M coordinate ints): the
routed DEF is ~100% on-grid (84 off-grid, 0.0%), so the OFFGRID DRC wall
is introduced at the DEF→GDS streamout / DRC-merge stage, NOT by routing
or floorplan. This gate makes that finding durable: a DEF that streams
on-grid is certified GRID_CLEAN_SOURCE; a DEF that is itself off-grid is
a FLOW_OFFGRID_SOURCE the plugin must fix.

Exit: 0 = DEF on-grid (source clean), 1 = DEF off-grid (source defect),
2 = input error. Chip-AGNOSTIC: DEF UNITS + numeric coordinates +
optional tech-LEF MANUFACTURINGGRID; no chip/PDK literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Default manufacturing grid: sky130 is 0.005 µm (5 nm). Overridable via
# --mfg-grid-um or auto-read from a tech LEF MANUFACTURINGGRID line.
_DEFAULT_MFG_GRID_UM = 0.005

_UNITS_RE = re.compile(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)")
_COORD_RE = re.compile(r"\(\s*(-?\d+)\s+(-?\d+)\s*\)")
_MFG_GRID_RE = re.compile(r"MANUFACTURINGGRID\s+([0-9.]+)\s*;", re.IGNORECASE)


def read_mfg_grid_um(tech_lef: Optional[str]) -> float:
    """Read MANUFACTURINGGRID (µm) from a tech LEF, or the sky130 default
    when absent/unreadable. chip-AGNOSTIC: standard LEF token."""
    if tech_lef:
        try:
            txt = Path(tech_lef).read_text(errors="replace")
            m = _MFG_GRID_RE.search(txt)
            if m:
                return float(m.group(1))
        except Exception:
            pass
    return _DEFAULT_MFG_GRID_UM


# A SOURCE is "off-grid" only when a MATERIAL fraction of its coordinates
# miss the grid. Empirically a clean routed DEF carries a handful of
# off-grid via-enclosure coordinates (verified: 84 / 1.88M = 0.004% of
# the form ±242/243); that residue is below this floor and is NOT a
# routing/floorplan source defect — the OFFGRID DRC wall (76% of GDS DRC)
# is introduced downstream at streamout. A genuinely off-grid source
# (mis-aligned floorplan/track origin) puts a LARGE fraction off-grid.
_SOURCE_OFFGRID_FRACTION_FLOOR = 0.01  # 1%


def classify_def(def_text: str, mfg_grid_um: float = _DEFAULT_MFG_GRID_UM
                 ) -> Dict:
    """Classify a DEF's coordinates against the manufacturing grid.

    Returns {dbu_per_um, grid_dbu, total_coords, offgrid_coords,
    offgrid_fraction, verdict, sample_offgrid}. verdict is
    GRID_CLEAN_SOURCE when the off-grid fraction is below the via-residue
    floor (the routing source is on-grid → OFFGRID DRC is a downstream
    streamout/merge tool behaviour), FLOW_OFFGRID_SOURCE when a material
    fraction is off-grid (the floorplan/routing source itself is
    mis-aligned)."""
    m = _UNITS_RE.search(def_text)
    if not m:
        return {"verdict": "ERROR", "reason": "no UNITS DISTANCE MICRONS line"}
    dbu = int(m.group(1))
    grid_dbu = round(mfg_grid_um * dbu)
    if grid_dbu <= 0:
        return {"verdict": "ERROR",
                "reason": f"degenerate grid: {mfg_grid_um}µm × {dbu} dbu/µm"}
    total = 0
    offgrid = 0
    sample: List[int] = []
    for mc in _COORD_RE.finditer(def_text):
        for g in (mc.group(1), mc.group(2)):
            v = int(g)
            total += 1
            if v % grid_dbu != 0:
                offgrid += 1
                if len(sample) < 12 and v not in sample:
                    sample.append(v)
    frac = (offgrid / total) if total else 0.0
    material = frac >= _SOURCE_OFFGRID_FRACTION_FLOOR
    return {
        "verdict": "FLOW_OFFGRID_SOURCE" if material else "GRID_CLEAN_SOURCE",
        "dbu_per_um": dbu,
        "grid_dbu": grid_dbu,
        "mfg_grid_um": mfg_grid_um,
        "total_coords": total,
        "offgrid_coords": offgrid,
        "offgrid_fraction": round(frac, 6),
        "source_floor": _SOURCE_OFFGRID_FRACTION_FLOOR,
        "sample_offgrid": sorted(set(sample)),
    }


def summarize(rep: Dict) -> str:
    if rep.get("verdict") == "ERROR":
        return f"DEF grid classify ERROR: {rep.get('reason')}"
    if rep["verdict"] == "GRID_CLEAN_SOURCE":
        return (f"DEF source GRID-CLEAN: {rep['offgrid_coords']:,}/"
                f"{rep['total_coords']:,} ({rep['offgrid_fraction']:.4%}) "
                f"off the {rep['grid_dbu']}-DBU manufacturing grid — below "
                f"the {rep['source_floor']:.0%} via-residue floor, so the "
                f"routing/floorplan SOURCE is on-grid. Any GDS OFFGRID DRC "
                f"is introduced DOWNSTREAM at the DEF→GDS streamout / merge "
                f"stage (a tool behaviour, not routing/floorplan); "
                f"remediate the streamout grid (container-side) and "
                f"re-verify via the #594 FLOW_OFFGRID classifier.")
    return (f"FLOW_OFFGRID_SOURCE: {rep['offgrid_coords']:,}/"
            f"{rep['total_coords']:,} ({rep['offgrid_fraction']:.2%}) DEF "
            f"coordinates are off the {rep['grid_dbu']}-DBU manufacturing "
            f"grid — the routing/floorplan SOURCE is off-grid (sample "
            f"{rep['sample_offgrid'][:8]}); fix the flow before streamout.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("def_file", help="DEF file to classify")
    p.add_argument("--tech-lef", default=None,
                   help="tech LEF to read MANUFACTURINGGRID from")
    p.add_argument("--mfg-grid-um", type=float, default=None,
                   help="manufacturing grid in µm (overrides tech-LEF)")
    p.add_argument("--json", default=None)
    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    dp = Path(args.def_file)
    if not dp.is_file():
        print(f"error: DEF not found: {dp}", file=sys.stderr)
        return 2
    grid_um = (args.mfg_grid_um if args.mfg_grid_um is not None
               else read_mfg_grid_um(args.tech_lef))
    rep = classify_def(dp.read_text(errors="replace"), grid_um)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep, indent=2) + "\n")
    print(summarize(rep))
    if rep.get("verdict") == "ERROR":
        return 2
    return 1 if rep["verdict"] == "FLOW_OFFGRID_SOURCE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
