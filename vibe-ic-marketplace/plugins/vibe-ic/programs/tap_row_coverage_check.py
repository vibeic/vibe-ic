#!/usr/bin/env python3
"""tap_row_coverage_check — does every active cell have a well tie in ITS OWN
WELL ISLAND within the distance the PDK's DRC deck requires? Judged on the
TOOL's DEF.

WHY THIS PROGRAM EXISTS (review70 step 15, harvest item 2; T96)
===============================================================
Step 15 on the chip path is LibreLane `OpenROAD.TapEndcapInsertion`: OpenROAD
`tapcell -distance FP_TAPCELL_DIST`, with the distance from the PDK's LibreLane
config. The direct deck kept two things of its own around the same command, the
#684 post-placement tap prune and the post-route well-tie coverage repair, and
review70 dropped both from the tool path (they cost correctness twice: DF.13/14
60 violations from the prune, 5 KLayout / 15 Magic markers from the repair on
spm final14). What it kept is the LESSON they were built on, as a gate:

  * The number is the FOUNDRY's. The deck states it (gf180mcu `comp.rb`:
    `# Rule DF.13_MV: Max distance of Nwell tap ... is 15um.`), per voltage
    class; a flow knob is only a request. The caller resolves it through the
    runner's one reader (`deck_tap_max_distance_um`) and passes it with its
    source.
  * Coverage counts inside one WELL ISLAND. DF.13 grows the tap inside
    n-well: two abutted rows that share their power edge share one n-well,
    while the neighbour across the ground edge is a separate island (MEASURED
    by the direct flow: `wire70` sat 7.84 um from a tie one row below, across
    that edge, and violated). The substrate taps (DF.14) pair the other way.

  MEASURED on the spm LibreLane chain (0.3.79, FP_TAPCELL_DIST 20, gf180mcuD):
  OpenROAD's two-phase checkerboard lays ties 39.2 um apart in a row and
  19.6 um apart in each n-well island; the KLayout sign-off deck (df_13_mv,
  df_14_mv at 15 um) reads 0. A same-ROW ruler read 181 of 413 active cells
  uncovered on that layout, the island ruler 0 -- the same-row reading was a
  false alarm; the island is the deck's own geometry. The row-start endcap
  ties the well too (its supply pin draws the well in its LEF): without it,
  3 cells read uncovered at 16.8 um.

THE RULE
========
Over the DEF's own ROWS and placed COMPONENTS, with master geometry and pin
use from the LEFs the step read:

  * A TIE is a placed instance of the declared tap master, or of the endcap
    master when its own LEF shows its supply pin drawing the well.
  * A row's n-well edge is the edge its POWER rail sits on (from the tap
    master's LEF); a flipped row (FS, S) turns it over. Rows sharing an n-well
    edge form one n-well island; rows sharing a ground edge, one substrate
    island.
  * An ANCHOR is a placed CORE instance, not a tie, with at least one
    non-supply pin whose DIRECTION is INPUT, OUTPUT or INOUT -- the functional
    selector the direct repair used, so no PDK cell is named here.
  * `--scope cells`: every point of every anchor's extent must be within the
    deck distance of a tie in its n-well island AND of one in its substrate
    island (TAP_ROW_COVERAGE_GAP). The worst point of an extent is one of its
    ends or a midpoint between consecutive ties inside it, so those are the
    points measured (exactly; no sampling grid).
  * `--scope lattice`: the tool's lattice itself, on a DEF with nothing placed
    (TapEndcapInsertion's output): every point of every row span, the same way
    (TAP_LATTICE_GAP). This is the pre-placement check the review asked for,
    as a measurement of what the tool built rather than a formula over its
    knob.

Exit codes: 0 PASS, 1 FAIL, 2 NOT_MEASURED (unreadable input, no row, the tap
master absent from every LEF, a placed row master of unknown geometry, or --
`cells` -- no anchor at all: a floorplan with nothing placed proves nothing).
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import argparse                                                     # noqa: E402
import bisect                                                       # noqa: E402
import json                                                         # noqa: E402
import re                                                           # noqa: E402
import sys                                                          # noqa: E402
from pathlib import Path                                            # noqa: E402
from typing import Any, Dict, List, Optional, Sequence, Tuple       # noqa: E402

from _atomic_artefact import write_json as atomic_write_json        # noqa: E402

PROGRAM = "tap_row_coverage_check"
INSTRUMENT = "tap_row_coverage_check::audit"
DEFAULT_JSON = "reports/phase3/pnr/tap_row_coverage.json"

_SIGNAL_DIRECTIONS = ("INPUT", "OUTPUT", "INOUT")
_SUPPLY_USES = ("POWER", "GROUND")


# ── LEF: master size, class and pin use/direction ──────────────────────────
def read_lef_masters(texts: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """`{master: {class, width_um, signal_pin}}` from LEF MACRO blocks.

    `signal_pin` is True when some PIN is not a supply (`USE POWER/GROUND`)
    and declares an INPUT/OUTPUT/INOUT direction.
    """
    masters: Dict[str, Dict[str, Any]] = {}
    for text in texts:
        for mac in re.finditer(r"(?ms)^\s*MACRO\s+(\S+)\s*$(.*?)^\s*END\s+\1\s*$", text):
            name, body = mac.group(1), mac.group(2)
            cls = re.search(r"(?m)^\s*CLASS\s+([^;]+?)\s*;", body)
            size = re.search(r"(?m)^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;", body)
            signal = False
            supply_y: Dict[str, List[float]] = {"POWER": [], "GROUND": []}
            well_on_supply = False
            for pin in re.finditer(r"(?ms)^\s*PIN\s+(\S+)\s*$(.*?)^\s*END\s+\1\s*$", body):
                pbody = pin.group(2)
                use = re.search(r"(?m)^\s*USE\s+(\S+)\s*;", pbody)
                dirn = re.search(r"(?m)^\s*DIRECTION\s+(\S+)", pbody)
                if use and use.group(1).upper() in _SUPPLY_USES:
                    if re.search(r"(?mi)^\s*LAYER\s+[np]well\s*;", pbody):
                        well_on_supply = True
                    for r in re.finditer(r"(?m)^\s*RECT\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+"
                                         r"(-?[0-9.]+)\s+(-?[0-9.]+)\s*;", pbody):
                        supply_y[use.group(1).upper()].append(
                            (float(r.group(2)) + float(r.group(4))) / 2)
                    continue
                if dirn and dirn.group(1).upper() in _SIGNAL_DIRECTIONS:
                    signal = True
            height = float(size.group(2)) if size else None
            power_top = None
            if height and supply_y["POWER"] and supply_y["GROUND"]:
                pw = sum(supply_y["POWER"]) / len(supply_y["POWER"])
                gd = sum(supply_y["GROUND"]) / len(supply_y["GROUND"])
                power_top = pw > gd if pw != gd else None
            masters[name] = {
                "class": " ".join(cls.group(1).split()).upper() if cls else "",
                "width_um": float(size.group(1)) if size else None,
                "height_um": height,
                "signal_pin": signal,
                # the supply edge the master's POWER pin sits on (N orientation):
                # the n-well side of a row, which a flipped row turns over
                "power_top": power_top,
                # the supply pin's own PORT draws the well: the cell ties the
                # well to that supply (a tap), not merely sits in it
                "well_on_supply": well_on_supply,
            }
    return masters


# ── DEF: units, rows, placed components ────────────────────────────────────
#: Orientations that turn a row upside down (its supply edges swap).
_FLIPPED = ("FS", "S")


def read_def(text: str) -> Dict[str, Any]:
    """Units, ROWS (y -> orientation, and y -> [(x0, x1)]) and placed
    COMPONENTS of a DEF."""
    units = re.search(r"(?m)^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", text)
    if not units:
        raise ValueError("TAP_DEF_UNREADABLE: no UNITS DISTANCE MICRONS")
    dbu = int(units.group(1))
    rows: Dict[int, str] = {}
    spans: Dict[int, List[Tuple[int, int]]] = {}
    for m in re.finditer(
            r"(?m)^\s*ROW\s+\S+\s+\S+\s+(-?\d+)\s+(-?\d+)\s+(\S+)"
            r"(?:\s+DO\s+(\d+)\s+BY\s+\d+(?:\s+STEP\s+(\d+)\s+\d+)?)?", text):
        x, y, orient = int(m.group(1)), int(m.group(2)), m.group(3)
        if rows.setdefault(y, orient) != orient:
            raise ValueError(f"TAP_DEF_ROW_ORIENT_AMBIGUOUS: rows at y={y} "
                             f"declare {rows[y]} and {orient}")
        spans.setdefault(y, []).append((x, x + int(m.group(4) or 1) * int(m.group(5) or 0)))
    start = re.search(r"(?m)^\s*COMPONENTS\s+\d+\s*;", text)
    end = re.search(r"(?m)^\s*END\s+COMPONENTS", text)
    if not start or not end:
        raise ValueError("TAP_DEF_UNREADABLE: no COMPONENTS section")
    comps: List[Tuple[str, str, int, int, str]] = []
    for stmt in text[start.end():end.start()].split(";"):
        head = re.match(r"\s*-\s+(\S+)\s+(\S+)", stmt)
        loc = re.search(r"\+\s+(?:PLACED|FIXED|FIRM|COVER)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)"
                        r"\s+(\S+)", stmt)
        if head and loc:
            comps.append((head.group(1), head.group(2), int(loc.group(1)),
                          int(loc.group(2)), loc.group(3)))
    return {"dbu": dbu, "rows": rows, "spans": spans, "components": comps}


def _worst_distance(xa: int, xb: int, centres: List[int]) -> int:
    """max over p in [xa, xb] of the distance from p to the nearest centre
    (-1 when there is no centre at all)."""
    if not centres:
        return -1
    points = [xa, xb]
    lo = bisect.bisect_left(centres, xa)
    hi = bisect.bisect_right(centres, xb)
    for i in range(max(lo, 1), min(hi + 1, len(centres))):
        mid = (centres[i - 1] + centres[i]) // 2
        if xa <= mid <= xb:
            points.append(mid)
    worst = 0
    for p in points:
        j = bisect.bisect_left(centres, p)
        near = min(abs(centres[k] - p) for k in (j - 1, j) if 0 <= k < len(centres))
        worst = max(worst, near)
    return worst


def well_islands(rows: Dict[int, str], height: int, power_top: bool
                 ) -> Tuple[Dict[int, int], Dict[int, int]]:
    """For each row y: the y of its n-well edge and of its substrate edge.

    A row's n-well sits on the edge its cells' POWER rail sits on (from the
    tap master's own LEF); a flipped row (FS, S) turns it over. Two rows whose
    n-well edges coincide share ONE n-well (the abutted pair across the power
    rail); two rows whose ground edges coincide share one substrate strip. A
    neighbour across the OTHER edge is a separate island -- the measured
    `wire70` case (7.84 um from a tie in the row below, violating).
    """
    nwell: Dict[int, int] = {}
    sub: Dict[int, int] = {}
    for y, orient in rows.items():
        top = power_top != (orient in _FLIPPED)
        nwell[y] = y + height if top else y
        sub[y] = y if top else y + height
    return nwell, sub


def audit(def_text: str, lef_texts: Sequence[str], tap_master: str,
          distance_um: float, endcap_master: Optional[str] = None,
          scope: str = "cells") -> Dict[str, Any]:
    """Measure tap coverage, raising ValueError on unreadable input."""
    masters = read_lef_masters(lef_texts)
    tap = masters.get(tap_master)
    if not tap or not tap["width_um"] or not tap["height_um"]:
        raise ValueError(f"TAP_MASTER_NOT_IN_LEF: {tap_master}")
    if tap["power_top"] is None:
        raise ValueError(f"TAP_MASTER_SUPPLY_EDGE_UNDECIDED: {tap_master} declares no "
                         "POWER and GROUND pin geometry on distinct edges")
    d = read_def(def_text)
    dbu, rows = d["dbu"], d["rows"]
    if not rows:
        raise ValueError("TAP_DEF_NO_ROWS: the DEF declares no ROW")
    radius = int(round(distance_um * dbu))
    # The declared WELLTAP_CELL is a tie by declaration. The ENDCAP_CELL is one
    # only when its own LEF says so (its supply pin draws the well); otherwise
    # it is a row terminator and ties nothing.
    tie_w = {tap_master: int(round(tap["width_um"] * dbu))}
    endcap = masters.get(endcap_master or "")
    endcap_ties = bool(endcap and endcap["well_on_supply"] and endcap["width_um"])
    if endcap_ties:
        tie_w[endcap_master] = int(round(endcap["width_um"] * dbu))
    nwell_of, sub_of = well_islands(rows, int(round(tap["height_um"] * dbu)),
                                    tap["power_top"])
    ties: Dict[int, List[int]] = {}
    anchors: List[Tuple[str, str, int, int, int]] = []
    unknown: List[str] = []
    for name, master, x, y, _orient in d["components"]:
        # in a row: its origin on the row's y and inside the row's own span
        # (a pad-ring filler can share a y with a core row, outside it)
        if y not in rows or not any(x0 <= x < x1 for x0, x1 in d["spans"][y]):
            continue
        if master in tie_w:
            ties.setdefault(y, []).append(x + tie_w[master] // 2)
            continue
        info = masters.get(master)
        if info is None:
            unknown.append(master)
            continue
        if not info["class"].startswith("CORE") or not info["signal_pin"]:
            continue
        width = int(round((info["width_um"] or 0.0) * dbu))
        anchors.append((name, master, y, x, x + width))
    by_nwell: Dict[int, List[int]] = {}
    by_sub: Dict[int, List[int]] = {}
    for y, xs in ties.items():
        by_nwell.setdefault(nwell_of[y], []).extend(xs)
        by_sub.setdefault(sub_of[y], []).extend(xs)
    for group in (by_nwell, by_sub):
        for xs in group.values():
            xs.sort()
    uncovered = []
    for name, master, y, xa, xb in anchors:
        worst = {"nwell": _worst_distance(xa, xb, by_nwell.get(nwell_of[y], [])),
                 "substrate": _worst_distance(xa, xb, by_sub.get(sub_of[y], []))}
        bad = sorted(k for k, w in worst.items() if w < 0 or w > radius)
        if bad:
            uncovered.append({"instance": name, "master": master,
                              "row_y_um": y / dbu, "x_um": [xa / dbu, xb / dbu],
                              "islands": bad,
                              "nearest_tie_um": {k: (None if w < 0 else round(w / dbu, 4))
                                                 for k, w in worst.items()}})
    gaps = []
    if scope == "lattice":
        # The tool's tap lattice itself, before anything is placed: every
        # point of every row span within the distance of a tie in its island.
        for y in sorted(rows):
            for x0, x1 in d["spans"][y]:
                worst = {"nwell": _worst_distance(x0, x1, by_nwell.get(nwell_of[y], [])),
                         "substrate": _worst_distance(x0, x1, by_sub.get(sub_of[y], []))}
                bad = sorted(k for k, w in worst.items() if w < 0 or w > radius)
                if bad:
                    gaps.append({"row_y_um": y / dbu, "x_um": [x0 / dbu, x1 / dbu],
                                 "islands": bad,
                                 "nearest_tie_um": {k: (None if w < 0 else round(w / dbu, 4))
                                                    for k, w in worst.items()}})
    worst_all = [w for u in uncovered + gaps for w in u["nearest_tie_um"].values()
                 if w is not None]
    return {
        "dbu": dbu, "rows": len(rows), "ties": sum(len(v) for v in ties.values()),
        "rows_with_ties": len(ties), "anchors": len(anchors),
        "rows_with_anchors": len({a[2] for a in anchors}),
        "power_edge": "top" if tap["power_top"] else "bottom",
        "tie_masters": sorted(tie_w),
        "endcap_counted": ({"master": endcap_master, "ties_well": endcap_ties}
                           if endcap_master else None),
        "scope": scope,
        "uncovered": uncovered,
        "lattice_gaps": gaps,
        "unknown_masters": sorted(set(unknown)),
        "worst_island_distance_um": max(worst_all) if worst_all else None,
    }


def unplaceable_masters(def_text: str, lef_texts: Sequence[str],
                        candidates: Optional[Sequence[str]] = None
                        ) -> Dict[str, Any]:
    """Masters no row of this DEF can hold: wider than its longest free run.

    review70 step 15 harvest 4 (#951: a 62-site buffer, 0 of 563 nets routed,
    9957 DRC from DPL-0701). Over the tool's own ROWS and the FIXED/PLACED
    instances already in them (taps, endcaps), the longest stretch of free
    row, in microns; every CORE master (of `candidates`, else every CORE
    master in the LEFs that is not a tie) wider than it can never be legally
    placed, so the placer and resizer must not be offered it. A derivation
    from the tool's DEF, never a number from a run's metrics.
    """
    masters = read_lef_masters(lef_texts)
    d = read_def(def_text)
    dbu = d["dbu"]
    occupied: Dict[int, List[Tuple[int, int]]] = {}
    for _name, master, x, y, _orient in d["components"]:
        info = masters.get(master)
        if y in d["rows"] and info and info["width_um"]:
            occupied.setdefault(y, []).append((x, x + int(round(info["width_um"] * dbu))))
    longest = 0
    for y, spans in d["spans"].items():
        taken = sorted(occupied.get(y, []))
        for x0, x1 in spans:
            cursor = x0
            for a, b in taken:
                if b <= x0 or a >= x1:
                    continue
                longest = max(longest, a - cursor)
                cursor = max(cursor, b)
            longest = max(longest, x1 - cursor)
    names = candidates if candidates is not None else [
        m for m, info in masters.items()
        if info["class"] == "CORE" and info["signal_pin"]]
    wide = sorted(m for m in names
                  if masters.get(m, {}).get("width_um")
                  and int(round(masters[m]["width_um"] * dbu)) > longest)
    return {"longest_free_run_um": longest / dbu, "unplaceable": wide}


def judge(def_path: Path, lef_paths: Sequence[Path], tap_master: str,
          distance_um: Optional[float], distance_source: str, *,
          endcap_master: Optional[str] = None, scope: str = "cells",
          tool_distance_um: Optional[float] = None,
          tool_distance_source: str = "") -> Dict[str, Any]:
    """The verdict document (PASS / FAIL / NOT_MEASURED).

    ``scope="lattice"`` judges the tool's tap lattice on a DEF with nothing
    placed yet (TapEndcapInsertion's output): the pre-placement half, which
    replaces a formula over FP_TAPCELL_DIST with a measurement of what the
    tool built. ``scope="cells"`` judges every active cell of a placed or
    routed DEF. The tool's configured distance is recorded, never judged: the
    lattice is.
    """
    rep: Dict[str, Any] = {
        "program": PROGRAM, "instrument": INSTRUMENT, "scope": scope,
        "def": str(def_path), "lefs": [str(p) for p in lef_paths],
        "tap_master": tap_master, "endcap_master": endcap_master,
        "deck_distance_um": distance_um, "deck_distance_source": distance_source,
        "tool_distance_um": tool_distance_um,
        "tool_distance_source": tool_distance_source or None,
        "findings": [],
    }
    if distance_um is None or distance_um <= 0:
        rep.update(verdict="NOT_MEASURED",
                   reason=f"TAP_DECK_DISTANCE_UNDECLARED: {distance_source}")
        return rep
    try:
        measured = audit(def_path.read_text(errors="replace"),
                         [p.read_text(errors="replace") for p in lef_paths],
                         tap_master, distance_um, endcap_master, scope)
    except (OSError, ValueError) as exc:
        rep.update(verdict="NOT_MEASURED", reason=str(exc))
        return rep
    rep["measured"] = measured
    if measured["unknown_masters"]:
        rep.update(verdict="NOT_MEASURED",
                   reason=("TAP_MASTER_GEOMETRY_UNKNOWN: placed row masters absent "
                           f"from every LEF read: {measured['unknown_masters'][:8]}"))
        return rep
    if scope == "cells" and not measured["anchors"]:
        rep.update(verdict="NOT_MEASURED",
                   reason=("TAP_NO_ANCHOR: no placed active cell in any row -- "
                           "coverage of an empty floorplan proves nothing"))
        return rep
    if measured["lattice_gaps"]:
        rep["findings"].append({
            "rule": "TAP_LATTICE_GAP",
            "detail": (f"{len(measured['lattice_gaps'])} row span(s) of the tool's "
                       f"tap lattice hold a point further than {distance_um} um "
                       f"from every tie in its well island (worst "
                       f"{measured['worst_island_distance_um']} um)")})
    if measured["uncovered"]:
        rep["findings"].append({
            "rule": "TAP_ROW_COVERAGE_GAP",
            "detail": (f"{len(measured['uncovered'])} of {measured['anchors']} active "
                       f"cell(s) have no tie in their well island within "
                       f"{distance_um} um (worst {measured['worst_island_distance_um']} um)")})
    rep["verdict"] = "FAIL" if rep["findings"] else "PASS"
    rep["reason"] = ("; ".join(f["rule"] + ": " + f["detail"] for f in rep["findings"])
                     or (f"{scope}: {measured['anchors']} active cell(s) and "
                         f"{measured['rows']} row(s) within {distance_um} um of a tie "
                         f"in their well island ({measured['ties']} ties of "
                         f"{measured['tie_masters']}; {distance_source})"))
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--def", dest="def_path", required=True)
    ap.add_argument("--lef", action="append", default=[], required=True)
    ap.add_argument("--tap-master", required=True)
    ap.add_argument("--endcap-master", default=None,
                    help="counted as a tie only when its own LEF ties the well")
    ap.add_argument("--scope", choices=("cells", "lattice"), default="cells")
    ap.add_argument("--distance-um", type=float, required=True,
                    help="the deck's max tap distance for this library")
    ap.add_argument("--distance-source", required=True)
    ap.add_argument("--tool-distance-um", type=float, default=None)
    ap.add_argument("--tool-distance-source", default="")
    ap.add_argument("--json", default=DEFAULT_JSON)
    args = ap.parse_args(argv)
    project = Path(args.project_dir).resolve()
    rep = judge(Path(args.def_path), [Path(p) for p in args.lef],
                args.tap_master, args.distance_um, args.distance_source,
                endcap_master=args.endcap_master, scope=args.scope,
                tool_distance_um=args.tool_distance_um,
                tool_distance_source=args.tool_distance_source)
    out = Path(args.json)
    out = out if out.is_absolute() else project / out
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out, rep)
    print(f"=== {PROGRAM} ({project.name}) ===\n  verdict: {rep['verdict']}\n"
          f"  {rep.get('reason', '')}")
    return {"PASS": 0, "FAIL": 1}.get(rep["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
