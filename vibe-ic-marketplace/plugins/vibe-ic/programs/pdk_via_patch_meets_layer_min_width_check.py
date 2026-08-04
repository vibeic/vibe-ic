#!/usr/bin/env python3
"""pdk_via_patch_meets_layer_min_width_check.py — a via's metal patch must
be at least as wide as that metal layer's own declared minimum WIDTH.

A tech LEF states both halves of this in the same file: `LAYER <m> ... TYPE
ROUTING ... WIDTH w ;` is the layer's minimum width, and `VIA <name> ...
LAYER <m> ; RECT x1 y1 x2 y2 ;` is the patch a via drops on it. When the
patch is narrower than the width, the PDK contradicts itself, and the
contradiction is only invisible while every via happens to sit in the middle
of a wire. It becomes sign-off DRC the moment a wire ENDS on one: the patch
protrudes past the wire end, and in the protrusion the metal is narrower than
the layer's minimum.

MEASURED, not hypothesised (sky130A, 880x880um, 79499 instances, KLayout
sign-off deck on the shipped GDS):

  * the design routed 3 signal segments on the top metal; every one of them
    ended on the PDK's default top via
  * `sky130_fd_sc_hd__nom.tlef` declares `LAYER met5 ... WIDTH 1.6` and, 430
    lines later, `VIA M4M5_PR DEFAULT ... LAYER met5 ; RECT -0.71 -0.71 0.71
    0.71` -> a 1.42um patch
  * the deck reported 9 `m5.1` (min m5 width) items — 3 sites x 3 edge pairs
  * the geometry matched the via RECT to the nanometre at all three sites
  * replacing each offending polygon with its own bounding box (i.e. "the
    patch is as wide as the wire") and re-running the SAME deck took the run
    from 11 violations to 2, introducing nothing new

The router's own in-loop DRC recorded `violation report: 0` for the same
layout, so nothing upstream of sign-off sees this.

SCOPE AND HONESTY. A narrow patch is a LATENT defect, not a certain
violation: it fires only where a wire terminates on the via, so a PDK can
carry it for years while designs happen not to route on the affected layer.
This checker reports the PDK fact, which is knowable at setup time, and does
not claim to predict a count.

BASELINE. Every finding this repo already lives with is recorded in
`pdk_via_patch_min_width_baseline.json`, which MAY ONLY SHRINK — the same
shape `pdk_registry_selectable_check` uses, and for the same reason: failing
a pre-existing gap on day one makes a gate people route around. Anything NEW
fails, and an entry that stops occurring must be removed from the baseline
or this check FAILs, so the record cannot become standing permission.

Usage:
    pdk_via_patch_meets_layer_min_width_check.py --tech-lef A.tlef [B.tlef ...]
                                                 [--json out.json]
                                                 [--baseline F] [--write-baseline]

Exit codes:
    0 = no NEW finding, and every baselined finding still occurs
    1 = a NEW finding, or a baselined finding that no longer occurs
    2 = no readable tech LEF given (refuses rather than reporting clean)

chip-AGNOSTIC and PDK-AGNOSTIC: pure LEF arithmetic, no layer-name literal,
no per-PDK table, no threshold.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_NUM = r"[-+]?\d*\.?\d+"
_RE_LAYER_OPEN = re.compile(r"^LAYER\s+(\S+)\s*$")
_RE_LAYER_REF = re.compile(r"^LAYER\s+(\S+)\s*;")
_RE_TYPE = re.compile(r"^TYPE\s+(\w+)\s*;")
_RE_WIDTH = re.compile(rf"^WIDTH\s+({_NUM})\s*;")
_RE_MINWIDTH = re.compile(rf"^MINWIDTH\s+({_NUM})\s*;")
_RE_VIA_OPEN = re.compile(r"^VIA\s+(\S+)(?:\s+DEFAULT)?\s*$")
_RE_RECT = re.compile(
    rf"^RECT\s+(?:MASK\s+\d+\s+)?({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})"
    rf"\s*;")

#: How much narrower than the layer's own WIDTH still counts as equal.
#: LEF distances are decimal micrometres; this is float-comparison slack,
#: NOT a tolerance on the rule.
_EPS = 1e-9


def _strip(line: str) -> str:
    return line.split("#", 1)[0].strip()


def parse_tech_lef(text: str) -> Tuple[Dict[str, float],
                                       Dict[str, Dict[str, Tuple[float,
                                                                 float]]]]:
    """`(routing_min_width, via_patch_extents)` from one tech LEF.

    `routing_min_width[layer] = w` for TYPE ROUTING layers only — a cut
    layer has no width rule of this kind and must not be compared.
    `via_patch_extents[via][layer] = (dx, dy)` is the bounding extent of
    every RECT the via declares on that layer, which is what the layout
    sees after the shapes merge.
    """
    routing: Dict[str, float] = {}
    vias: Dict[str, Dict[str, Tuple[float, float]]] = {}

    cur_layer: Optional[str] = None
    cur_type: Optional[str] = None
    cur_width: Optional[float] = None
    cur_minwidth: Optional[float] = None

    cur_via: Optional[str] = None
    via_layer: Optional[str] = None
    boxes: Dict[str, List[float]] = {}

    for raw in text.splitlines():
        ln = _strip(raw)
        if not ln:
            continue

        if cur_via is None:
            m = _RE_VIA_OPEN.match(ln)
            if m:
                cur_via, via_layer, boxes = m.group(1), None, {}
                continue

        if cur_via is not None:
            if re.match(r"^END\s+" + re.escape(cur_via) + r"\s*$", ln):
                vias[cur_via] = {
                    lay: (round(b[2] - b[0], 9), round(b[3] - b[1], 9))
                    for lay, b in boxes.items()}
                cur_via = None
                continue
            m = _RE_LAYER_REF.match(ln)
            if m:
                via_layer = m.group(1)
                continue
            m = _RE_RECT.match(ln)
            if m and via_layer is not None:
                x1, y1, x2, y2 = (float(g) for g in m.groups())
                nb = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
                b = boxes.get(via_layer)
                boxes[via_layer] = nb if b is None else [
                    min(b[0], nb[0]), min(b[1], nb[1]),
                    max(b[2], nb[2]), max(b[3], nb[3])]
            continue

        if cur_layer is None:
            m = _RE_LAYER_OPEN.match(ln)
            if m:
                cur_layer = m.group(1)
                cur_type = cur_width = cur_minwidth = None
            continue

        if re.match(r"^END\s+" + re.escape(cur_layer) + r"\s*$", ln):
            w = cur_width if cur_width is not None else cur_minwidth
            if cur_type == "ROUTING" and w is not None:
                routing[cur_layer] = w
            cur_layer = None
            continue
        m = _RE_TYPE.match(ln)
        if m:
            cur_type = m.group(1).upper()
            continue
        # The FIRST bare `WIDTH <n> ;` is the layer rule. A SPACINGTABLE row
        # is `WIDTH <n> <n> ;` and does not match — which matters, because on
        # the PDK that motivated this check the table row carries the very
        # number the layer rule does, and reading the row as the rule would
        # have made the two agree for the wrong reason.
        m = _RE_WIDTH.match(ln)
        if m and cur_width is None:
            cur_width = float(m.group(1))
            continue
        m = _RE_MINWIDTH.match(ln)
        if m and cur_minwidth is None:
            cur_minwidth = float(m.group(1))

    return routing, vias


def findings_for(lef: Path) -> List[dict]:
    """Every (via, routing layer) whose patch is narrower than the layer's
    own minimum width, in either axis."""
    routing, vias = parse_tech_lef(lef.read_text(errors="ignore"))
    out: List[dict] = []
    for via in sorted(vias):
        for layer in sorted(vias[via]):
            w = routing.get(layer)
            if w is None:            # cut layer, or no width rule stated
                continue
            dx, dy = vias[via][layer]
            if dx + _EPS < w or dy + _EPS < w:
                out.append({
                    "tech_lef": lef.name,
                    "via": via,
                    "layer": layer,
                    "patch_x_um": dx,
                    "patch_y_um": dy,
                    "layer_min_width_um": w,
                    "narrow_axis": ("x" if dx + _EPS < w else "")
                                   + ("y" if dy + _EPS < w else ""),
                })
    return out


def _key(f: dict) -> str:
    return f"{f['tech_lef']}::{f['via']}::{f['layer']}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tech-lef", action="append", default=[],
                    help="tech LEF to check (repeatable)")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=str(
        Path(__file__).with_name("pdk_via_patch_min_width_baseline.json")))
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()

    lefs = [Path(p) for p in args.tech_lef]
    readable = [p for p in lefs if p.is_file()]
    if not readable:
        print("[REFUSE] pdk_via_patch_meets_layer_min_width_check: no "
              "readable --tech-lef given. An unchecked PDK is not a clean "
              "PDK, so this refuses rather than reporting 0 findings.",
              file=sys.stderr)
        return 2

    found: List[dict] = []
    for p in readable:
        found.extend(findings_for(p))

    bl_path = Path(args.baseline)
    try:
        known = set(json.loads(bl_path.read_text()).get("known", []))
    except (OSError, ValueError):
        known = set()

    now = sorted({_key(f) for f in found})
    new = [f for f in found if _key(f) not in known]
    # Only entries whose tech LEF we actually looked at can be judged paid.
    seen_lefs = {p.name for p in readable}
    paid = sorted(k for k in known
                  if k.split("::", 1)[0] in seen_lefs and k not in set(now))

    report = {
        "program": "pdk_via_patch_meets_layer_min_width_check",
        "tech_lefs_checked": [str(p) for p in readable],
        "findings": found,
        "new_findings": new,
        "baseline_entries_no_longer_occurring": paid,
        "verdict": "FAIL" if (new or paid) else "PASS",
    }
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")

    if args.write_baseline:
        bl_path.write_text(json.dumps(
            {"_comment": (
                "(tech LEF, VIA, LAYER) triples where the via's patch on a "
                "TYPE ROUTING layer is narrower than that layer's own "
                "declared minimum WIDTH. Each one is a latent min-width "
                "violation that fires wherever a wire ENDS on the via. MAY "
                "ONLY SHRINK — fix the PDK (fork it) or drop the layer from "
                "the signal routing range; do not add rows."),
             "known": now}, indent=2) + "\n")
        print(f"wrote {bl_path} ({len(now)} entr(ies))")
        return 0

    for f in found:
        mark = "NEW " if _key(f) not in known else "recorded"
        print(f"  [{mark}] {f['tech_lef']}: VIA {f['via']} puts a "
              f"{f['patch_x_um']:g} x {f['patch_y_um']:g} um patch on "
              f"{f['layer']}, whose own minimum WIDTH in the same file is "
              f"{f['layer_min_width_um']:g} um "
              f"(narrow in {f['narrow_axis']})")
    for k in paid:
        print(f"  [FAIL] {k} no longer occurs — shrink the baseline so it "
              f"cannot become standing permission.")

    if new or paid:
        print(f"[FAIL] {len(new)} new finding(s), {len(paid)} stale baseline "
              f"entr(ies). A via patch narrower than its own layer's minimum "
              f"width is a sign-off DRC violation wherever a wire terminates "
              f"on that via, and the router's in-loop DRC does not see it.")
        return 1
    print(f"[PASS] {len(readable)} tech LEF(s), {len(found)} recorded "
          f"finding(s), 0 new. Every via patch that is narrower than its "
          f"own layer's minimum width is already on the shrink-only "
          f"baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
