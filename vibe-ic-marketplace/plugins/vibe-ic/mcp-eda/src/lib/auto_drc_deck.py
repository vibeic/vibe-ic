#!/usr/bin/env python3
"""
auto_drc_deck.py — auto-derive a minimal KLayout DRC deck from a tech LEF.

Used by mcp-eda's eda_drc_klayout tool when the project supplies
a `custom_techlef` (no foundry-blessed .drc deck) and lets KLayout
enforce only WIDTH and SPACING rules per routing layer.

Stdlib only — no third-party deps. Designed to be called from JS via
`python3 src/lib/auto_drc_deck.py --techlef ... --gds ... --top ...`,
avoiding the shell-escape pitfalls of inlining a Python heredoc inside
a JavaScript template literal (which broke at v0.99.0 vendor benchmark
with `sh: 66: Syntax error: "(" unexpected`).

Output protocol (parsed by index.js):
    LAYERMAP_AUTO_DETECTED=<path>      (optional, when discovered)
    LAYERMAP_RULES=<int>
    TECHLEF_LAYERS=<int>
    AUTO_DRC_GENERATED=<deck_path> rules=<int>
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys


def discover_layermap(techlef: str) -> str | None:
    base = os.path.dirname(techlef)
    candidates: list[str] = []
    for d in (base, os.path.dirname(base)):
        if not d:
            continue
        candidates.extend(glob.glob(os.path.join(d, "*layermap*")))
        candidates.extend(glob.glob(os.path.join(d, "*layer_map*")))
        candidates.extend(glob.glob(os.path.join(d, "*.layermap")))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def parse_techlef_routing_layers(techlef: str) -> list[dict]:
    """Return list of dicts {name, type, width, spacing} for routing/cut
    layers found in the tech LEF. Width/spacing in microns (LEF units)."""
    layers: list[dict] = []
    cur: dict | None = None
    with open(techlef) as f:
        for ln in f:
            m = re.match(r"^LAYER\s+(\w+)", ln)
            if m:
                cur = {"name": m.group(1), "type": None,
                       "width": None, "spacing": None}
                continue
            if cur is None:
                continue
            if "TYPE ROUTING" in ln:
                cur["type"] = "ROUTING"
            elif "TYPE CUT" in ln:
                cur["type"] = "CUT"
            m = re.match(r"\s*WIDTH\s+([\d.]+)", ln)
            if m and cur["width"] is None:
                cur["width"] = float(m.group(1))
            m = re.match(r"\s*SPACING\s+([\d.]+)", ln)
            if m and cur["spacing"] is None:
                cur["spacing"] = float(m.group(1))
            if re.match(r"^END\s+\w+", ln):
                if cur["type"] in ("ROUTING", "CUT") and cur["width"]:
                    layers.append(cur)
                cur = None
    return layers


def parse_layermap(layermap_path: str) -> dict[str, tuple[int, int]]:
    """Parse a KLayout-style layermap. Format per line:
        <LEF_LAYER_NAME>  NET  <gds_layer>  <gds_datatype>
    Returns {LEF_NAME: (gds_layer, gds_datatype)}."""
    out: dict[str, tuple[int, int]] = {}
    if not (layermap_path and os.path.isfile(layermap_path)):
        return out
    with open(layermap_path) as f:
        for ln in f:
            parts = ln.split()
            if len(parts) >= 4:
                try:
                    out.setdefault(parts[0], (int(parts[2]), int(parts[3])))
                except ValueError:
                    pass
    return out


# Spacing/width measurement metric for the auto-synthesized deck.
#
# MUST stay `euclidian` — it is what every foundry sign-off deck uses, and it
# is KLayout's own default for `width`/`space`. The auto-deck is the fallback
# used precisely when a PDK ships NO foundry deck, so if it measures more
# weakly than a real deck it produces a false clean bill of health.
#
# `projection` (used here until this was measured) only compares the facing
# projection of parallel edges: it CANNOT see a corner-to-corner (45-degree)
# separation at all. Measured on KLayout 0.30.6 with two shapes offset
# dx = dy = 0.15 um against a 0.23 um limit (true Euclidean separation
# 0.2121 um, a genuine violation):
#
#     metric=euclidian   violations=2   <- correctly flagged
#     metric=square      violations=2   <- flagged
#     metric=projection  violations=0   <- MISSED
#
# Note the direction: Euclidean is the more PERMISSIVE metric for diagonal
# neighbours (it measures the true hypotenuse, sqrt(2)x longer than the
# rectilinear offset), which is exactly why foundry decks pair a relaxed
# corner-to-corner limit with tighter edge-to-edge limits — e.g. ASAP7
# M1.S.6 corner rule is 20 nm while its edge rules are 25/27/31 nm. A router
# does NOT need extra rectilinear margin to satisfy a Euclidean rule at 45
# degrees; the hazard is the opposite, a deck that under-measures corners.
_METRIC = "euclidian"


def emit_deck(deck_path: str, gds: str, top: str, rdb: str,
              layers: list[dict], gdsmap: dict[str, tuple[int, int]]) -> int:
    """Write the .drc file. Returns the number of rule lines emitted."""
    rules_emitted = 0
    with open(deck_path, "w") as f:
        f.write("source(%r, %r)\n" % (gds, top))
        f.write("report(%r, %r)\n" % ("Auto DRC from techlef", rdb))
        # Parallel-by-default: enable KLayout's tiled multi-CPU DRC. The thread
        # count arrives from the CLI as `-rd threads=<n>` (a Ruby global $threads,
        # a string or nil). KLayout's tiled DRC is RESULT-INVARIANT: it splits the
        # layout into tiles processed in parallel and merges the violation set, so
        # the reported violations are identical to a single-threaded run — only
        # faster. nil.to_i == 0 in Ruby, so an absent/blank $threads floors to 1.
        f.write("threads([$threads.to_i, 1].max)\n")
        # Declare each mapped layer
        for L in layers:
            gd = gdsmap.get(L["name"])
            if not gd:
                continue
            f.write("%s = input(%d, %d)\n" % (L["name"].lower(),
                                              gd[0], gd[1]))
        # Width / spacing rules
        for L in layers:
            gd = gdsmap.get(L["name"])
            if not gd or not L["width"]:
                continue
            nm = L["name"].lower()
            eps = max(L["width"] * 0.999, L["width"] - 0.001)
            f.write(
                "%s.width(%.4f.um, %s)"
                ".output(%r)\n"
                % (nm, eps, _METRIC, "%s.W <%.3f" % (L["name"], L["width"]))
            )
            rules_emitted += 1
            if L["spacing"]:
                sp = max(L["spacing"] * 0.999, L["spacing"] - 0.001)
                f.write(
                    "%s.space(%.4f.um, %s)"
                    ".output(%r)\n"
                    % (nm, sp, _METRIC,
                       "%s.S <%.3f" % (L["name"], L["spacing"]))
                )
                rules_emitted += 1
    return rules_emitted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--techlef", required=True)
    ap.add_argument("--gds", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--rdb", required=True)
    ap.add_argument("--layermap", default="",
                    help="Optional layermap file. If empty, auto-discover.")
    ap.add_argument("--out", required=True,
                    help="Path to write the generated .drc deck.")
    args = ap.parse_args()

    lmap = args.layermap
    if not lmap:
        found = discover_layermap(args.techlef)
        if found:
            lmap = found
            print("LAYERMAP_AUTO_DETECTED=" + lmap)

    layers = parse_techlef_routing_layers(args.techlef)
    gdsmap = parse_layermap(lmap)

    print("LAYERMAP_RULES=" + str(len(gdsmap)))
    print("TECHLEF_LAYERS=" + str(len(layers)))

    rules = emit_deck(args.out, args.gds, args.top, args.rdb, layers, gdsmap)
    print("AUTO_DRC_GENERATED=%s rules=%d" % (args.out, rules))
    return 0


if __name__ == "__main__":
    sys.exit(main())
