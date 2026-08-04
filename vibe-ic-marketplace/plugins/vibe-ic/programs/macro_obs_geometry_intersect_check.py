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

    exit 0 = no emitted metal spans a declared obstruction, AND every placed
             master resolved to a LEF
    exit 1 = at least one does (BLOCKING)
    exit 2 = could not be determined — no DEF, no macro LEF, no placed macro,
             no OBS in any of them, or an INCOMPLETE LEF set (a master is
             PLACED and no LEF read declares it, so its OBS — if it has one —
             was never in the comparison). NEVER a vacuous pass: this gate has
             been wrong about nothing before, and "found no crossings" must not
             be the same sentence as "had nothing to look at".

DISCOVERY (#828). With no `--macro-lef`, every `*.lef` under the project that
DECLARES A MACRO is read. The previous default was `input/pdk/**/*.lef` +
`phase3/**/macro*.lef`; an IP LEF legitimately lives outside `input/pdk/`, and
a staged macro LEF need not be named `macro*`, so discovery decided the verdict
at least as much as the geometry did. A file's content answers "does this
define a MACRO" directly; its path and name only guess at it.

WHAT THIS FILE DOES NOT DO. It is not registered in
`flow/phase1_phase2_phase3.yaml` and no runner invokes it; its only caller is
`tools/ci/repo_hygiene_gates.sh`, under `run_tolerating_uncheckable`, over the
tracked cells carrying `phase3/stage3/pnr/routed.def`. See #828 part 2 — not
addressed here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1\s*$", re.S | re.M)
_SIZE_RE = re.compile(r"^\s*SIZE\s+([\d.-]+)\s+BY\s+([\d.-]+)\s*;", re.M)
_OBS_RE = re.compile(r"^\s*OBS\s*$(.*?)(?=^\s*(?:PIN|END)\b)", re.S | re.M)
_LAYER_RE = re.compile(r"\s*LAYER\s+(\S+)\s*;")
_RECT_RE = re.compile(r"\s*RECT\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s*;")
_UNITS_RE = re.compile(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", re.M)
_COMP_RE = re.compile(
    r"^\s*-\s+(\S+)\s+(\S+)[^;]*?\+\s*(?:FIXED|PLACED|COVER)\s*\(\s*"
    r"(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)", re.M)
_COMPONENTS_SEC_RE = re.compile(
    r"^\s*COMPONENTS\b(.*?)^\s*END\s+COMPONENTS", re.S | re.M)


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


def parse_placed_masters(def_text: str) -> Set[str]:
    """Every distinct master PLACED in this DEF, whether or not any LEF was
    read for it.

    `parse_placed_macros` answers "which instances of the masters I already
    know about are placed". This answers the prior question — "what did the
    DEF actually place" — which is what makes "I found no LEF for that
    master" expressible at all.

    Scoped to the COMPONENTS section, and the scoping is load-bearing.
    `_COMP_RE` has `[^;]*?` between the master token and the placement, and
    a negated character class matches newlines, so run over a whole routed
    DEF it also reaches into the PINS section. A pin with a placed port —

        - clk + NET clk + DIRECTION INPUT + USE SIGNAL
          + PORT
            + LAYER Metal2 ( -100 -360 ) ( 100 360 )
            + PLACED ( 109920 360 ) N ;

    matches with inst=`clk` and MASTER=`+`. Measured on the three tracked
    DEFs, the whole-file scan over-counts by exactly 36 on each — one per
    pin — and mints that single phantom master:

        spm/v1.5.58_ihp-sg13g2  COMPONENTS 1826 ; -> whole 1862 / section 1826
        spm/v1.5.65_sky130A     COMPONENTS  558 ; -> whole  594 / section  558
        spm/v1.5.66_gf180mcuD   COMPONENTS 2007 ; -> whole 2043 / section 2007

    Section-scoped, the match count equals the declared count exactly on all
    three and the `+` artifact disappears. A phantom master would otherwise
    be permanently unresolvable and would make this gate cry wolf on every
    design. If the DEF has no delimited COMPONENTS section the whole text is
    scanned, which is the pre-existing behaviour and no worse than it.

    chip-AGNOSTIC: pure DEF grammar."""
    if not isinstance(def_text, str):
        return set()
    sm = _COMPONENTS_SEC_RE.search(def_text)
    body = sm.group(1) if sm else def_text
    out: Set[str] = set()
    for m in _COMP_RE.finditer(body):
        out.add(m.group(2))
    return out


def parse_routed_segments(def_text: str) -> List[Dict[str, Any]]:
    """`[{layer, x1, y1, x2, y2, net, followpin}]` in DEF units.

    SPECIALNETS only: this gate is about supply metal crossing an obstruction,
    which is what follow-pins and straps are. A signal route over a blockage is
    the router's business and the PDK deck's."""
    segs: List[Dict[str, Any]] = []
    sec = re.search(r"^\s*SPECIALNETS\b(.*?)^\s*END\s+SPECIALNETS",
                    def_text, re.S | re.M)
    if not sec:
        return segs
    for entry in re.split(r"\n\s*-\s+", sec.group(1)):
        nm = re.match(r"\s*(\S+)", entry)
        net = nm.group(1) if nm else "?"
        fp = "FOLLOWPIN" in entry
        for rm in re.finditer(
                r"\+\s*(?:ROUTED|FIXED|COVER|SHAPE\s+\w+)?\s*(\w+)\s+\d+"
                r"(?:\s+\+\s*SHAPE\s+\w+)?\s*"
                r"\(\s*(-?\d+|\*)\s+(-?\d+|\*)\s*\)\s*"
                r"\(\s*(-?\d+|\*)\s+(-?\d+|\*)\s*\)", entry):
            layer, a, b, c, d = rm.groups()
            if "*" in (a, b) or "*" in (c, d):
                continue          # a `*` repeats the previous coordinate; skip
            x1, y1, x2, y2 = int(a), int(b), int(c), int(d)
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
    # #828 — the denominator this gate could not see. A master that is
    # PLACED but that no supplied LEF declares at all is a master whose OBS,
    # if it has one, was never in the comparison. Disclosed here rather than
    # left for the reader to infer from a silent [PASS]; `main` refuses to
    # call that a pass.
    placed_masters = parse_placed_masters(def_text)
    without_lef = sorted(placed_masters - set(obs_by_master))
    return {
        "masters_with_obs": sorted(with_obs),
        "placed_instances": len(placed),
        "special_segments": len(segs),
        "findings": findings,
        "placed_masters": len(placed_masters),
        "masters_declared_by_lef": sorted(obs_by_master),
        "placed_masters_without_lef": without_lef,
    }


def discover_macro_lefs(proj: Path) -> List[Path]:
    """Every LEF under the project that DECLARES A MACRO, in a stable order.

    #828 — the previous default was two globs,
    `input/pdk/**/*.lef` + `phase3/**/macro*.lef`, and both miss by one
    step: an IP LEF legitimately lives outside `input/pdk/` (e.g. under a
    `pdk_local` tree, which is not `pdk`), and a macro LEF staged under
    `phase3/` need not have a filename beginning `macro`. A file's LOCATION
    and its NAME are weak proxies for "this file defines a MACRO"; its
    CONTENT answers that question directly and cheaply, so that is what is
    asked here.

    The two original globs are searched FIRST and keep their relative order,
    so every project that already resolved keeps resolving identically —
    `audit` merges with `dict.update`, so discovery order decides which file
    wins a master declared twice. Files that were previously invisible are
    appended after; a master declared BOTH in a previously-visible file and
    in a previously-invisible one therefore now resolves to the latter. That
    is a deliberate consequence of no longer ignoring a file that is in the
    project.

    Only the DEFAULT discovery filters on content. An explicit `--macro-lef`
    is the operator naming the file, and is honoured verbatim.

    chip-AGNOSTIC: pure LEF grammar; no vendor, PDK or path literal beyond
    the two legacy globs it preserves."""
    ordered: List[Path] = []
    seen = set()
    for pat in ("input/pdk/**/*.lef", "phase3/**/macro*.lef", "**/*.lef"):
        for p in sorted(proj.glob(pat)):
            rp = p.resolve()
            if rp in seen or not p.is_file():
                continue
            seen.add(rp)
            ordered.append(p)
    out: List[Path] = []
    for p in ordered:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if _MACRO_RE.search(text):
            out.append(p)
    return out


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
        lefs = discover_macro_lefs(proj)
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

    unresolved = rep["placed_masters_without_lef"]
    # #828 — when the LEF set is incomplete, say so in the SAME breath as the
    # other two refusals. "No macro declares an OBS" reads as a statement
    # about the design; if half the placed masters have no LEF at all it is a
    # statement about the input, and the reader must not have to guess which.
    _incomplete = (
        f" {len(unresolved)} of {rep['placed_masters']} placed master(s) have "
        f"NO LEF declaration in the set that was read "
        f"({', '.join(unresolved[:6])}"
        f"{f', +{len(unresolved) - 6} more' if len(unresolved) > 6 else ''}),"
        f" so the LEF set is INCOMPLETE."
    ) if unresolved else ""

    if not rep["masters_with_obs"]:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: no macro in the "
              "supplied LEF(s) declares an OBS. NOT a pass — nothing was "
              f"checked.{_incomplete}", file=sys.stderr)
        return 2
    if not rep["placed_instances"]:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: "
              f"{len(rep['masters_with_obs'])} master(s) declare an OBS and "
              f"none is PLACED in this DEF. NOT a pass.{_incomplete}",
              file=sys.stderr)
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

    # #828 — reached only when nothing was found to complain about. Whether
    # that means "clean" or "I did not have the file that would have told me"
    # is decided HERE, not left to the reader of a [PASS] line. A run in which
    # a placed master has no OBS source is not a clean run.
    if unresolved:
        print("[CANNOT DETERMINE] macro_obs_geometry_intersect: no crossing "
              f"found among {rep['placed_instances']} placed instance(s) of "
              f"{len(rep['masters_with_obs'])} master(s) with OBS, but"
              f"{_incomplete} An unread LEF may declare an OBS that is "
              "being crossed, so this is not the same sentence as 'none spans "
              "an obstruction'. NOT a pass. Name the missing LEF(s) with "
              "--macro-lef, or stage them under the project.",
              file=sys.stderr)
        return 2

    print(f"[PASS] macro_obs_geometry_intersect: {rep['placed_instances']} placed "
          f"instance(s) of {len(rep['masters_with_obs'])} master(s) with OBS, "
          f"{rep['special_segments']} supply segment(s) — none spans an "
          f"obstruction. All {rep['placed_masters']} placed master(s) resolved "
          f"to a LEF.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
