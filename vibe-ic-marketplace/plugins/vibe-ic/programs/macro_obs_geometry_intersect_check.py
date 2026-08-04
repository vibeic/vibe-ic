#!/usr/bin/env python3
"""Emitted metal that crosses a placed macro's declared obstruction. vibe-ic#686.

THIS GATE BLOCKS (rc=1).

WHY IT EXISTS
-------------
A hard macro's `OBS` rectangle is the macro vendor's statement of where the
integrator may not put metal. The flow reads that LEF, uses its `PIN` section,
and discards its `OBS`. Follow-pins, core straps and the macro grid are all
emitted without consulting it, and NOTHING anywhere intersects emitted geometry
with a placed macro's obstructions.

MEASURED on a routed DEF from a run the flow called clean but for one unrelated
integration gap: **28 of 292 MET1 FOLLOWPIN segments run straight through a
placed macro's full-footprint MET1 obstruction** — an obstruction declared in
the very LEF the run loaded.

THE FAILURE IS SILENT BY CONSTRUCTION, which is the part worth naming. Every
existing check is either

  * a COUNT OF ATTACHMENTS — `PG_NET_OWNERSHIP_AUDIT: total=3337 no_net=1` tests
    `[$_pg_t getNet] eq "NULL"`, i.e. whether a terminal has a net. A wire that
    crosses a blockage is attached to exactly the right net. (Spelled
    `PG_CONNECT_AUDIT: unconnected=N` through v1.9.62, until vibe-ic#699 renamed
    it to what it measures.)
  * a GEOMETRIC DRC AGAINST THE PDK DECK — `drc_signoff.json: passed: true,
    real_violation_total: 0`, `detailed route: violation report: 0`. A macro
    obstruction is not in the PDK deck; it is in the macro's LEF.

A macro obstruction is neither, so it was invisible to all of them at once.

WHAT IT MEASURES
----------------
For every macro instance PLACED in the DEF, transform the macro's `OBS` rects to
placed coordinates and intersect them with the routed metal on the same layer.
A segment counts as a violation when it SPANS the obstruction — enters one side
and leaves the other — not when it merely touches near an edge, because a
fragment at the boundary is ordinary and flagging it would bury the real finding
in noise.

Orientation is honoured: `N/S/FN/FS` keep the macro's own axes, `E/W/FE/FW`
swap them. A checker that ignored orientation would measure a rotated macro
against an unrotated obstruction and report crossings that are not there — a
fabricated finding is worse than none.

chip-AGNOSTIC and PDK-AGNOSTIC: pure LEF/DEF grammar. No design, PDK, vendor or
layer-name literal appears in the logic.

USAGE
-----
    macro_obs_geometry_intersect_check.py <project_dir> [--json OUT]
                                          [--def PATH] [--macro-lef PATH ...]

    exit 0 = no emitted metal spans a declared obstruction
    exit 1 = at least one does (BLOCKING)
    exit 2 = could not be determined — no DEF, no macro LEF, no placed macro,
             or no OBS in any of them. NEVER a vacuous pass: this gate has been
             wrong about nothing before, and "found no crossings" must not be
             the same sentence as "had nothing to look at".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1\s*$", re.S | re.M)
_SIZE_RE = re.compile(r"^\s*SIZE\s+([\d.-]+)\s+BY\s+([\d.-]+)\s*;", re.M)
_OBS_RE = re.compile(r"^\s*OBS\s*$(.*?)(?=^\s*(?:PIN|END)\b)", re.S | re.M)
_LAYER_RE = re.compile(r"\s*LAYER\s+(\S+)\s*;")
_RECT_RE = re.compile(r"\s*RECT\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s*;")
_UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", re.M)
_COMP_RE = re.compile(
    r"^\s*-\s+(\S+)\s+(\S+)[^;]*?\+\s*(?:FIXED|PLACED|COVER)\s*\(\s*"
    r"(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)", re.M)


def parse_macro_obs(lef_text: str) -> Dict[str, Dict[str, Any]]:
    """{master: {"size": (w,h) um, "obs": [(layer, x1,y1,x2,y2) um]}}.

    `LAYER OVERLAP` is a LEF keyword declaring the macro's own extent, not a
    metal layer, and is excluded — treating it as one would make every macro
    block every layer."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(lef_text, str):
        return out
    for mm in _MACRO_RE.finditer(lef_text):
        master, body = mm.group(1), mm.group(2)
        sm = _SIZE_RE.search(body)
        rects: List[Tuple[str, float, float, float, float]] = []
        om = _OBS_RE.search(body)
        if om:
            layer = None
            for line in om.group(1).splitlines():
                lm = _LAYER_RE.match(line)
                if lm:
                    layer = lm.group(1)
                    continue
                rm = _RECT_RE.match(line)
                if rm and layer and layer.upper() != "OVERLAP":
                    x1, y1, x2, y2 = (float(v) for v in rm.groups())
                    rects.append((layer, min(x1, x2), min(y1, y2),
                                  max(x1, x2), max(y1, y2)))
        out[master] = {
            "size": ((float(sm.group(1)), float(sm.group(2))) if sm else None),
            "obs": rects,
        }
    return out


def place_rect(rect: Tuple[float, float, float, float],
               size: Tuple[float, float], ox: float, oy: float,
               orient: str) -> Tuple[float, float, float, float]:
    """A macro-local rect in PLACED coordinates.

    Orientation is honoured because ignoring it measures a rotated macro against
    an unrotated obstruction — a fabricated finding, which is worse than none.
    Only the axis mapping matters here: a bounding box is symmetric under the
    mirror flips, so N/FN/S/FS all keep the macro's axes and E/FE/W/FW swap
    them."""
    x1, y1, x2, y2 = rect
    w, h = size
    o = (orient or "N").upper()
    if o in ("N", "FN", "S", "FS"):
        return (ox + x1, oy + y1, ox + x2, oy + y2)
    if o in ("E", "FE", "W", "FW"):
        # 90-degree rotation: the macro occupies h x w in placed space.
        return (ox + y1, oy + x1, ox + y2, oy + x2)
    return (ox + x1, oy + y1, ox + x2, oy + y2)


def parse_placed_macros(def_text: str,
                        masters: Sequence[str]) -> List[Dict[str, Any]]:
    """Every COMPONENT whose master is one of `masters`, with its placement."""
    want = set(masters)
    out = []
    for m in _COMP_RE.finditer(def_text):
        inst, master, x, y, orient = m.groups()
        if master in want:
            out.append({"inst": inst, "master": master,
                        "x": int(x), "y": int(y), "orient": orient})
    return out


# A wiring path inside a SPECIALNETS entry. DEF introduces the FIRST path of a
# net with `+ ROUTED` (or FIXED / COVER) and every SUBSEQUENT path of that same
# net with the bare keyword `NEW` — no `+`. Anchoring on `+` therefore sees one
# path per net and silently discards the rest.
_PATH_HEAD_RE = re.compile(
    r"(?:\+\s*(?:ROUTED|FIXED|COVER|SHAPE\s+\w+)?\s*|\bNEW\s+)(\w+)\s+\d+",
    re.I)

# `( x y )`, with an optional third value (the wire extension). Either
# coordinate may be `*`, which DEF defines as "repeat the one before it".
_PATH_POINT_RE = re.compile(r"\(\s*(-?\d+|\*)\s+(-?\d+|\*)(?:\s+-?\d+)?\s*\)")


# A via placed INSIDE a wiring path: a bare identifier sitting between two
# coordinate groups. LEF/DEF 5.8: "If you specify a via, layerName for the next
# routing coordinates (if any) is implicitly changed to the other routing layer
# for the via." So the head layer governs only up to the first via.
_PATH_TOKEN_RE = re.compile(
    r"\(\s*(-?\d+|\*)\s+(-?\d+|\*)(?:\s+-?\d+)?\s*\)"      # a point
    r"|([A-Za-z_][A-Za-z0-9_]*)")                          # or a bare name

# `- <viaName> ... + LAYERS <lower> <cut> <upper> ...` in the DEF's own VIAS
# section. That is where a via's two routing layers are stated.
_VIAS_SEC_RE = re.compile(r"^\s*VIAS\s+\d+\s*;(.*?)^\s*END\s+VIAS",
                          re.S | re.M)
_VIA_LAYERS_RE = re.compile(r"\+\s*LAYERS\s+(\S+)\s+(\S+)\s+(\S+)", re.I)

# DEF's own vocabulary, which occupies the same syntactic slot as a via name
# inside a wiring path. Not vias.
_PATH_KEYWORDS = {
    "NEW", "ROUTED", "FIXED", "COVER", "SHAPE", "USE", "STYLE", "MASK",
    "RECT", "VIRTUAL", "NONDEFAULTRULE", "TAPER", "TAPERRULE",
    "FOLLOWPIN", "STRIPE", "IOWIRE", "COREWIRE", "BLOCKWIRE", "BLOCKAGEWIRE",
    "FILLWIRE", "FILLWIREOPC", "DRCFILL", "RING", "PADRING", "BLOCKRING",
    "POWER", "GROUND", "SIGNAL", "CLOCK", "TIEOFF", "ANALOG", "RESET", "SCAN",
}


def parse_via_layers(def_text: str) -> Dict[str, Tuple[str, str]]:
    """{viaName: (lowerRoutingLayer, upperRoutingLayer)} from the VIAS section.

    Only vias DEFINED IN THIS DEF are resolvable here. A via that comes from the
    tech LEF is not, and the caller must treat it as unknown rather than guess —
    see `_path_segments`."""
    out: Dict[str, Tuple[str, str]] = {}
    sec = _VIAS_SEC_RE.search(def_text)
    if not sec:
        return out
    for entry in re.split(r"\n\s*-\s+", sec.group(1)):
        nm = re.match(r"\s*(\S+)", entry)
        lm = _VIA_LAYERS_RE.search(entry)
        if nm and lm:
            out[nm.group(1)] = (lm.group(1), lm.group(3))
    return out


def _path_segments(body: str, head_layer: str,
                   via_layers: Dict[str, Tuple[str, str]]
                   ) -> List[Tuple[str, int, int, int, int]]:
    """`[(layer, x1, y1, x2, y2)]` for ONE wiring path.

    Two things the head layer alone cannot tell you:

    * `*` is not a missing coordinate — DEF defines it as the PREVIOUS point's
      coordinate, and it is how every real writer spells an orthogonal segment.
      Dropping those points drops the segments they describe.
    * a via inside the path switches the layer for everything after it. Stamping
      the whole path with the head layer puts upper-layer metal on the lower
      layer, which on a BLOCKING gate does not merely miss a violation — it
      FABRICATES one, against an obstruction the metal never went near.

    When a via cannot be resolved (it is defined in the tech LEF, which this gate
    does not read), the layer after it is UNKNOWN. This stops emitting rather
    than continuing under the previous layer: an unreported segment is a gap, an
    unreported segment attributed to the wrong layer is a false accusation, and
    on a gate that blocks the second is strictly worse. `parse_routed_segments`
    counts these so the caller can see the gap instead of inferring silence."""
    segs: List[Tuple[str, int, int, int, int]] = []
    layer = head_layer
    px: Optional[int] = None
    py: Optional[int] = None
    for tm in _PATH_TOKEN_RE.finditer(body):
        a, b, name = tm.group(1), tm.group(2), tm.group(3)
        if name is not None:
            # A via is an identifier sitting BETWEEN coordinates. The same
            # position also carries DEF's own keywords (`+ SHAPE FOLLOWPIN`
            # before the first point, `+ USE POWER ;` after the last), so a
            # bare-identifier rule alone reads `SHAPE` as an unresolvable via
            # and abandons the whole path. Require both: we are mid-path, and
            # the token is not vocabulary.
            if px is None or name.upper() in _PATH_KEYWORDS:
                continue
            pair = via_layers.get(name)
            if pair is None:
                return segs                      # unresolvable via: stop here
            lo, hi = pair
            # the via connects two routing layers; move to whichever is not the
            # one we are on. If neither matches, the path is not describable.
            if layer.lower() == lo.lower():
                layer = hi
            elif layer.lower() == hi.lower():
                layer = lo
            else:
                return segs
            continue
        x = px if a == "*" else int(a)
        y = py if b == "*" else int(b)
        if x is None or y is None:
            continue      # a `*` in a path's first point has nothing to repeat
        if px is not None and py is not None:
            segs.append((layer, px, py, x, y))
        px, py = x, y
    return segs


def parse_routed_segments(def_text: str) -> List[Dict[str, Any]]:
    """`[{layer, x1, y1, x2, y2, net, followpin}]` in DEF units.

    SPECIALNETS only: this gate is about supply metal crossing an obstruction,
    which is what follow-pins and straps are. A signal route over a blockage is
    the router's business and the PDK deck's.

    A path is a POLYLINE: N points describe N-1 segments, and every one of them
    is metal that can cross an obstruction. Reading only the first pair reports
    on the first leg of each path and stays silent about the others."""
    segs: List[Dict[str, Any]] = []
    sec = re.search(r"^\s*SPECIALNETS\b(.*?)^\s*END\s+SPECIALNETS",
                    def_text, re.S | re.M)
    if not sec:
        return segs
    via_layers = parse_via_layers(def_text)
    for entry in re.split(r"\n\s*-\s+", sec.group(1)):
        nm = re.match(r"\s*(\S+)", entry)
        net = nm.group(1) if nm else "?"
        fp = "FOLLOWPIN" in entry
        heads = list(_PATH_HEAD_RE.finditer(entry))
        for i, hm in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(entry)
            for layer, x1, y1, x2, y2 in _path_segments(
                    entry[hm.end():end], hm.group(1), via_layers):
                segs.append({"layer": layer, "net": net, "followpin": fp,
                             "x1": min(x1, x2), "y1": min(y1, y2),
                             "x2": max(x1, x2), "y2": max(y1, y2)})
    return segs


def spans(seg: Dict[str, Any], box: Tuple[float, float, float, float]) -> bool:
    """Does the segment cross the box, entering one side and leaving the other?

    SPANNING, not merely touching: a fragment near an edge is ordinary, and
    flagging it would bury the real finding under noise. Horizontal and vertical
    are handled separately because a segment is one or the other."""
    bx1, by1, bx2, by2 = box
    horizontal = (seg["y2"] - seg["y1"]) <= (seg["x2"] - seg["x1"])
    if horizontal:
        return (seg["x1"] < bx1 and seg["x2"] > bx2
                and by1 <= seg["y1"] <= by2)
    return (seg["y1"] < by1 and seg["y2"] > by2
            and bx1 <= seg["x1"] <= bx2)


def audit(def_text: str, macro_lef_texts: Sequence[str]) -> Dict[str, Any]:
    obs_by_master: Dict[str, Dict[str, Any]] = {}
    for t in macro_lef_texts:
        obs_by_master.update(parse_macro_obs(t))
    with_obs = {m: e for m, e in obs_by_master.items() if e["obs"]}
    um = _UNITS_RE.search(def_text)
    units = int(um.group(1)) if um else 1000
    placed = parse_placed_macros(def_text, list(with_obs))
    segs = parse_routed_segments(def_text)

    findings: List[Dict[str, Any]] = []
    for inst in placed:
        e = with_obs[inst["master"]]
        if not e["size"]:
            continue
        ox, oy = inst["x"] / units, inst["y"] / units
        for (layer, x1, y1, x2, y2) in e["obs"]:
            box = place_rect((x1, y1, x2, y2), e["size"], ox, oy,
                             inst["orient"])
            box_du = tuple(v * units for v in box)
            for s in segs:
                if s["layer"].lower() != layer.lower():
                    continue
                if spans(s, box_du):
                    findings.append({
                        "inst": inst["inst"], "master": inst["master"],
                        "layer": layer, "net": s["net"],
                        "followpin": s["followpin"],
                        "seg": [s["x1"], s["y1"], s["x2"], s["y2"]],
                    })
    return {
        "masters_with_obs": sorted(with_obs),
        "placed_instances": len(placed),
        "special_segments": len(segs),
        "findings": findings,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--def", dest="def_path", type=Path, default=None)
    ap.add_argument("--macro-lef", dest="macro_lefs", type=Path, action="append",
                    default=None)
    ap.add_argument("--json", dest="json_out", type=Path, default=None)
    a = ap.parse_args(argv)

    proj = a.project_dir
    def_p = a.def_path
    if def_p is None:
        cands = sorted(proj.glob("phase3/stage3/pnr/routed*.def"))
        def_p = cands[0] if cands else None
    if def_p is None or not def_p.is_file():
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: no routed DEF "
              f"under {proj}. NOT a pass.", file=sys.stderr)
        return 2

    lefs = list(a.macro_lefs or [])
    if not lefs:
        lefs = sorted(proj.glob("input/pdk/**/*.lef")) + \
               sorted(proj.glob("phase3/**/macro*.lef"))
    texts = []
    for p in lefs:
        try:
            texts.append(p.read_text(errors="replace"))
        except OSError:
            continue
    if not texts:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: no macro LEF "
              "found. A run with no macro LEF is not a run with no obstruction "
              "— it is one this gate could not read. NOT a pass.",
              file=sys.stderr)
        return 2

    rep = audit(def_p.read_text(errors="replace"), texts)
    if a.json_out:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(rep, indent=2) + "\n")

    if not rep["masters_with_obs"]:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: no macro in the "
              "supplied LEF(s) declares an OBS. NOT a pass — nothing was "
              "checked.", file=sys.stderr)
        return 2
    if not rep["placed_instances"]:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: "
              f"{len(rep['masters_with_obs'])} master(s) declare an OBS and "
              "none is PLACED in this DEF. NOT a pass.", file=sys.stderr)
        return 2

    f = rep["findings"]
    if f:
        fp = sum(1 for x in f if x["followpin"])
        print(f"[FAIL] {len(f)} supply segment(s) SPAN a placed macro's declared "
              f"obstruction ({fp} of them follow-pins):")
        for x in f[:12]:
            print(f"   {x['inst']} ({x['master']}) {x['layer']}: net {x['net']}"
                  f"{' FOLLOWPIN' if x['followpin'] else ''}  seg {x['seg']}")
        if len(f) > 12:
            print(f"   … {len(f) - 12} more")
        print("\n  A macro OBS is the vendor's statement of where the integrator "
              "may not put\n  metal. It is not in the PDK deck, so sign-off DRC "
              "cannot see this; and the\n  wire is attached to the right net, so "
              "a connectivity audit cannot either.")
        return 1

    print(f"[PASS] macro_obs_geometry_intersect: {rep['placed_instances']} placed "
          f"instance(s) of {len(rep['masters_with_obs'])} master(s) with OBS, "
          f"{rep['special_segments']} supply segment(s) — none spans an "
          f"obstruction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
