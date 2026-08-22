#!/usr/bin/env python3
"""
tapcell_lattice_placeability_check.py — chip-AGNOSTIC audit of whether the
FIXED well-tap lattice the flow itself inserts can physically host the cells
the flow itself places.

The defect this exists for
--------------------------
`tapcell -distance D -tapcell_master T` tiles EVERY standard-cell row of the
die with FIXED well-tie cells.  OpenROAD lays them at a pitch of ``2*D``, so
the widest single-height cell the lattice can ever host between two
consecutive taps is::

    G = 2*D - width(T)                      # the "lattice free gap"

Any CORE master WIDER than ``G`` has **no legal site anywhere on the die** —
not because the die is full, but because the flow's own obstacle lattice is
finer than the library's own cells.  The placer only discovers this at
legalization time, and it does not degrade gracefully: `detailed_placement`
aborts the whole PnR with ``[ERROR DPL-0036] Detailed placement failed inside
DPL.`` — at *any* utilization, on a die that is 58% empty.

The trap is that nothing in synthesis or global placement knows about the
lattice.  The resizer (`repair_design` inside timing-driven `global_placement`)
sizes buffers for slew/capacitance, and CTS sizes the clock root for fanout;
both are free to pick the library's widest masters.  The moment one of them
does, the run dies at a step unrelated to the design's real engineering
residual.

MEASURED first occurrence (5V 180nm PDK, 8203-instance RISC-V SoC, die 839µm,
utilization 42.2%):

    tap distance D = 14.0µm, tap width = 1.12µm  ->  G = 26.88µm
    per-row max INTERIOR tap-free gap, measured over 205 rows and 5700
        inter-tap gaps: 5582 x 26.88µm, 118 x 12.32µm  (max 26.88µm)
    resizer inserted 4 x 34.72µm buffers and 15 x 28.00µm buffers
    rows able to host 34.72µm:  0 / 205      -> 4 / 4  failed to legalize
    rows able to host 28.00µm:  0 / 205 interior (only 102 die-EDGE slots)
                                            -> 9 / 15 failed to legalize
    everything <= 21.28µm:                  -> 0 / 1816 failed
    => 13 legalization failures, PnR dead.

The correlation with cell WIDTH is exact, and the widest master in the
*synthesized netlist* was 17.92µm — i.e. the design itself always fitted; only
the cells the FLOW inserted did not.

Why the tap pitch must not simply be relaxed
--------------------------------------------
The tap distance is a PDK LATCH-UP rule, not a free knob.  For the PDK where
this was first measured the shipped KLayout deck states a 15µm max tap
distance for the 5V library (the 3.3V variants allow 20µm), and the flow's
14.0µm sits deliberately under it.  Growing the lattice to fit a 34.72µm
buffer would need D >= 17.9µm and would silently break that rule — trading a
loud legalization failure for a quiet reliability/DRC one.  So the *cell
choice* is what must yield: narrow the optimizer's pool to what the lattice
can hold.

What this module provides
-------------------------
Pure, dependency-free geometry helpers (used by `phase3_one_shot_runner` to
emit the guard, and by the regression tests), plus two CLI audit modes:

  * ``--lef <cell.lef> --tap-master <M> --tap-distance <D>``
        library audit — which CORE masters the lattice cannot host.
  * ``--def <placed.def> --lef <cell.lef>``
        artifact audit — measure the REAL per-row interior tap-free gaps from
        the FIXED taps in a placed DEF and compare against the widest master
        actually placed.  This is the negative control: run it on a DEF from
        a run that died on DPL-0036 and it reports the impossibility.

Both modes are chip-AGNOSTIC: every number comes from the LEF/DEF geometry and
the configured tap distance.  No vendor, PDK, cell or design name appears in
any decision.

Usage
-----
    python3 tapcell_lattice_placeability_check.py \
        --lef <cell.lef> --tap-master <master> --tap-distance <um> [--json out]
    python3 tapcell_lattice_placeability_check.py \
        --def <placed.def> --lef <cell.lef> [--json out]

Exit codes
    0  PASS / SKIP
    1  FAIL — the lattice cannot host a master that is (or may be) placed
    2  argument or I/O error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "lattice_free_gap_um",
    "parse_lef_macro_geometry",
    "placeable_core_masters",
    "over_wide_core_masters",
    "widest_fitting_family_member",
    "parse_def_components",
    "measure_def_lattice_gaps",
]

# A LEF ``CLASS CORE`` master with NO subtype is the only kind the placer is
# free to place for logic.  SPACER / WELLTAP / ANTENNACELL / TIEHIGH / TIELOW /
# ENDCAP masters are positioned by dedicated flow steps at coordinates those
# steps choose, so the lattice constraint does not apply to them.
_PLACEABLE_LEF_CLASS = "CORE"


def lattice_free_gap_um(tap_distance_um: float,
                        tap_width_um: float) -> float:
    """Widest single-height cell a ``tapcell -distance D`` lattice can host.

    OpenROAD tiles each std-cell row with FIXED taps at a pitch of ``2*D``
    (``-distance`` is the max distance from any point in the row to a tap),
    so the free run between two consecutive taps is ``2*D - width(tap)``.

    Verified against a real placed DEF: D=14.0µm with a 1.12µm tap master
    produced 5582 interior gaps of exactly 26.88µm == 2*14.0 - 1.12.
    """
    return 2.0 * float(tap_distance_um) - float(tap_width_um)


def parse_lef_macro_geometry(text: str) -> Dict[str, Tuple[float, str]]:
    """``{master_name: (width_um, lef_class)}`` from LEF text.

    ``lef_class`` is the CLASS token(s) upper-cased and whitespace-collapsed,
    e.g. ``CORE``, ``CORE SPACER``, ``CORE WELLTAP``.
    """
    out: Dict[str, Tuple[float, str]] = {}
    for name, body in re.findall(r"^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1",
                                 text, re.S | re.M):
        m = re.search(r"^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", body, re.M)
        if not m:
            continue
        c = re.search(r"^\s*CLASS\s+([^;]+);", body, re.M)
        cls = " ".join(c.group(1).split()).upper() if c else ""
        out[name] = (float(m.group(1)), cls)
    return out


def placeable_core_masters(
        macros: Dict[str, Tuple[float, str]],
        exclude_patterns: Sequence[str] = ()) -> Dict[str, float]:
    """The masters the placer/resizer/CTS may freely place, name -> width."""
    res: Dict[str, float] = {}
    for name, (w, cls) in macros.items():
        if cls != _PLACEABLE_LEF_CLASS:
            continue
        if any(fnmatch(name, p) for p in exclude_patterns):
            continue
        res[name] = w
    return res


def over_wide_core_masters(
        macros: Dict[str, Tuple[float, str]],
        gap_um: float,
        exclude_patterns: Sequence[str] = ()) -> List[Tuple[str, float]]:
    """CORE masters the lattice can NEVER host, widest first."""
    cand = placeable_core_masters(macros, exclude_patterns)
    over = [(n, w) for n, w in cand.items() if w > gap_um + 1e-9]
    over.sort(key=lambda kv: (-kv[1], kv[0]))
    return over


def _family_prefix(name: str) -> str:
    """Drive-strength family of a cell name, derived from the name itself.

    ``<family>_<drive>`` is the near-universal std-cell naming shape (``buf_16``,
    ``CLKBUF_X3``, ``sg13g2_buf_16``).  Strip the trailing drive token so the
    family can be enumerated without any hardcoded vendor string.  Returns the
    prefix INCLUDING its separator, or ``""`` when the name has no drive
    suffix to strip.
    """
    m = re.match(r"^(.*?)(\d+)$", name)
    if not m or not m.group(1):
        return ""
    return m.group(1)


def widest_fitting_family_member(
        name: str,
        macros: Dict[str, Tuple[float, str]],
        gap_um: float,
        exclude_patterns: Sequence[str] = ()) -> Optional[str]:
    """Widest same-family master that DOES fit the lattice, or ``None``.

    Used to downgrade a configured CTS buffer that the lattice cannot host to
    the strongest drive of the SAME cell family that it can.  The family is
    derived from the configured name (see `_family_prefix`), so no vendor or
    PDK literal is involved.  ``None`` means "leave the configured cell alone"
    — either it already fits, or no fitting sibling exists (in which case the
    caller must not silently invent a different cell).
    """
    cand = placeable_core_masters(macros, exclude_patterns)
    cur = cand.get(name)
    if cur is None or cur <= gap_um + 1e-9:
        return None
    pref = _family_prefix(name)
    if not pref:
        return None
    fits = [(w, n) for n, w in cand.items()
            if n != name and n.startswith(pref) and w <= gap_um + 1e-9]
    if not fits:
        return None
    fits.sort(key=lambda wn: (-wn[0], wn[1]))
    return fits[0][1]


_DEF_COMP_RE = re.compile(
    r"-\s+(\S+)\s+(\S+)\s+\+(?:\s+SOURCE\s+\w+\s+\+)?\s+"
    r"(FIXED|PLACED|COVER|UNPLACED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)\s*;")


def parse_def_components(text: str) -> Tuple[List[Tuple[str, str, str, int, int]],
                                             float]:
    """``([(inst, master, status, x_dbu, y_dbu)], dbu_per_um)`` from DEF text."""
    m = re.search(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text, re.M)
    dbu = float(m.group(1)) if m else 1000.0
    try:
        s = text.index("\nCOMPONENTS ")
        e = text.index("END COMPONENTS")
    except ValueError:
        return [], dbu
    comps = [(n, mst, st, int(x), int(y))
             for n, mst, st, x, y, _o in _DEF_COMP_RE.findall(text[s:e])]
    return comps, dbu


def measure_def_lattice_gaps(def_text: str,
                             macros: Dict[str, Tuple[float, str]]) -> dict:
    """Measure the REAL tap lattice of a placed DEF.

    Returns the per-row maximum INTERIOR tap-free gap (the run between two
    consecutive FIXED cells — the only kind of slot a cell can be legalized
    into away from the die edge), the widest master actually placed, and the
    row-coverage counts for it.  Purely geometric; no design knowledge.
    """
    comps, dbu = parse_def_components(def_text)
    rows = re.findall(
        r"^\s*ROW\s+\S+\s+\S+\s+(-?\d+)\s+(-?\d+)\s+\w+\s+DO\s+(\d+)\s+BY\s+"
        r"(\d+)\s+STEP\s+(\d+)\s+(\d+)", def_text, re.M)
    row_h_dbu = 0
    if len(rows) >= 2:
        ys = sorted({int(r[1]) for r in rows})
        if len(ys) >= 2:
            row_h_dbu = min(b - a for a, b in zip(ys, ys[1:]))
    if not row_h_dbu:
        return {"verdict": "SKIP", "reason": "no ROW grid in DEF"}
    y0 = min(int(r[1]) for r in rows)
    x0 = min(int(r[0]) for r in rows)
    x1 = max(int(r[0]) + int(r[2]) * int(r[4]) for r in rows)

    fixed: Dict[int, List[Tuple[float, float]]] = {}
    widest_placed = ("", 0.0)
    for _n, mst, st, x, y in comps:
        w = macros.get(mst, (0.0, ""))[0]
        if st == "FIXED":
            r = round((y - y0) / row_h_dbu)
            fixed.setdefault(r, []).append((x / dbu, x / dbu + w))
        elif st in ("PLACED", "COVER") and w > widest_placed[1]:
            widest_placed = (mst, w)

    per_row_max: List[float] = []
    for r in range(round((max(int(rr[1]) for rr in rows) - y0) / row_h_dbu) + 1):
        t = sorted(fixed.get(r, []))
        best = 0.0
        if not t:
            best = (x1 - x0) / dbu
        else:
            for (_a, b), (c, _d) in zip(t, t[1:]):
                best = max(best, c - b)
        per_row_max.append(best)

    ww = widest_placed[1]
    hostable = sum(1 for g in per_row_max if g >= ww - 1e-9) if ww else 0
    return {
        "rows": len(per_row_max),
        "fixed_instances": sum(len(v) for v in fixed.values()),
        "max_interior_tap_free_gap_um": round(max(per_row_max), 4)
        if per_row_max else 0.0,
        "min_interior_tap_free_gap_um": round(min(per_row_max), 4)
        if per_row_max else 0.0,
        "widest_placed_master": widest_placed[0],
        "widest_placed_width_um": round(ww, 4),
        "rows_that_can_host_widest_placed": hostable,
        "verdict": "PASS" if (not ww or hostable) else "FAIL",
    }


def _audit_library(lef: Path, tap_master: str, tap_distance_um: float,
                   exclude: Sequence[str]) -> Tuple[int, dict]:
    macros = parse_lef_macro_geometry(lef.read_text(errors="ignore"))
    if tap_master not in macros:
        return 0, {"verdict": "SKIP",
                   "reason": f"tap master {tap_master} absent from LEF"}
    tap_w = macros[tap_master][0]
    gap = lattice_free_gap_um(tap_distance_um, tap_w)
    over = over_wide_core_masters(macros, gap, exclude)
    rep = {
        "verdict": "FAIL" if over else "PASS",
        "tap_master": tap_master,
        "tap_width_um": tap_w,
        "tap_distance_um": float(tap_distance_um),
        "lattice_free_gap_um": round(gap, 4),
        "placeable_core_masters": len(placeable_core_masters(macros, exclude)),
        "over_wide_masters": [{"master": n, "width_um": w} for n, w in over],
    }
    return (1 if over else 0), rep


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit well-tap lattice placeability (chip-AGNOSTIC).")
    ap.add_argument("--lef", required=True,
                    help="cell LEF whose MACRO geometry is read")
    ap.add_argument("--tap-master", help="well-tap master name")
    ap.add_argument("--tap-distance", type=float,
                    help="tapcell -distance value in um")
    ap.add_argument("--def", dest="def_file",
                    help="placed DEF to audit against its REAL tap lattice")
    ap.add_argument("--exclude", action="append", default=[],
                    help="glob of masters already excluded from the pool")
    ap.add_argument("--json", help="write the report here")
    args = ap.parse_args(list(argv) if argv is not None else None)

    lef = Path(args.lef)
    if not lef.is_file():
        print(f"ERROR: LEF not found: {lef}", file=sys.stderr)
        return 2

    if args.def_file:
        dp = Path(args.def_file)
        if not dp.is_file():
            print(f"ERROR: DEF not found: {dp}", file=sys.stderr)
            return 2
        macros = parse_lef_macro_geometry(lef.read_text(errors="ignore"))
        rep = measure_def_lattice_gaps(dp.read_text(errors="ignore"), macros)
        rep["def"] = str(dp)
        rc = 1 if rep.get("verdict") == "FAIL" else 0
    else:
        if not args.tap_master or args.tap_distance is None:
            print("ERROR: --tap-master and --tap-distance are required "
                  "without --def", file=sys.stderr)
            return 2
        rc, rep = _audit_library(lef, args.tap_master, args.tap_distance,
                                 args.exclude)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2) + "\n")

    print(f"{rep['verdict']}: tapcell_lattice_placeability_check — " + (
        f"measured max interior tap-free gap "
        f"{rep.get('max_interior_tap_free_gap_um')}um vs widest placed "
        f"{rep.get('widest_placed_width_um')}um "
        f"({rep.get('rows_that_can_host_widest_placed')}/{rep.get('rows')} "
        f"rows can host it)"
        if args.def_file else
        f"lattice free gap {rep.get('lattice_free_gap_um')}um "
        f"(2*{rep.get('tap_distance_um')} - {rep.get('tap_width_um')}); "
        f"{len(rep.get('over_wide_masters', []))} of "
        f"{rep.get('placeable_core_masters')} CORE master(s) cannot be "
        f"hosted"))
    for o in rep.get("over_wide_masters", [])[:20]:
        print(f"  UNPLACEABLE {o['width_um']:7.2f}um  {o['master']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
