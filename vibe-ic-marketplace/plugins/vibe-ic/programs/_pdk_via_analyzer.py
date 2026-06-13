#!/usr/bin/env python3
"""_pdk_via_analyzer.py — chip-AGNOSTIC LEF VIA-block cut counter.

Background
----------
OpenROAD's TritonRoute (`detailed_route` in newer builds, `drt`) requires
that every routing-layer transition have at least one *single-cut* via
defined in the tech LEF. Some commercial / legacy PDKs ship only
*multi-cut* and *directional* via variants for upper layers (e.g.
``VIA56_CENTER``, ``VIA56_NORTH1Q``, ``VIA56_HORI4`` — each carrying
multiple ``RECT`` shapes inside ``LAYER VIAn`` blocks). On those PDKs
``detailed_route`` aborts with ``[ERROR DRT-0234] VIAn does not have
single-cut via.``

This analyzer scans a tech LEF and, for each via cut layer, tells the
caller whether at least one *single-cut* via exists. The Phase-3 runner
uses the result to decide whether to restrict ``set_routing_layers`` to
the cut layers covered by single-cut vias (the common workaround for
small chips that don't actually need the upper metal layers).

Usage
-----
    _pdk_via_analyzer.py <tech.lef>
        [--json PATH]

Output
------
JSON shape::

    {
      "tech_lef": "...",
      "vias_by_cut_layer": {
        "VIA1": {"total": 2, "single_cut": 2, "multi_cut": 0, "names": [...]},
        "VIA5": {"total": 7, "single_cut": 0, "multi_cut": 7, "names": [...]}
      },
      "single_cut_missing": ["VIA5"],
      "verdict": "PASS" | "WARN"
    }

Exit codes
----------
    0 = analysis succeeded (verdict may still be WARN)
    2 = IO error (file not found / unreadable)

API
---
``analyze_lef(text) -> Dict[str, Dict[str, Any]]``
``cut_layers_with_single_cut(text) -> Set[str]``  (caller-facing)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set


# A "cut" layer is the middle LAYER inside a VIA block whose name in
# practice starts with VIA / V. Routing layers are MET / M / METAL.
# We match by structural position (the LAYER between two routing LAYERS
# inside a VIA block) rather than by name pattern, so it works on PDKs
# that name vias differently.
# v1.6.602 — accept the LEF-spec-conformant `VIA <name> DEFAULT` and
# `VIA <name> GENERATED ...` first-line variants. Real foundry tech
# LEFs include the DEFAULT keyword on virtually every fixed-via
# definition; the pre-v1.6.602 pattern `\s*\n` rejected anything past
# the via name on the same line, so the analyzer silently returned an
# empty dict on production tech LEFs. The `VIA` literal (followed by
# `\s+`) does not clash with the unrelated `VIARULE` statement, which
# is a single token with no separator after `VIA`.
_VIA_BLOCK_RE = re.compile(
    r"^\s*VIA\s+(\S+)[^\n]*\n(.*?)^\s*END\s+\1",
    re.DOTALL | re.MULTILINE,
)
_LAYER_BLOCK_RE = re.compile(
    r"^\s*LAYER\s+(\S+)\s*;\s*\n((?:(?!^\s*LAYER\s+).)*)",
    re.DOTALL | re.MULTILINE,
)
_RECT_RE = re.compile(r"^\s*RECT\b", re.MULTILINE)


def _classify_layer_kind(name: str) -> str:
    """Return 'cut' if name looks like VIAn (cut layer), 'routing' if METn /
    METALn / Mn, else 'unknown'."""
    n = name.upper()
    if n.startswith("VIA") and any(c.isdigit() for c in n):
        return "cut"
    if (n.startswith("MET") or n.startswith("METAL") or
            (n.startswith("M") and len(n) >= 2 and n[1].isdigit())):
        return "routing"
    return "unknown"


def analyze_lef(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse VIA blocks from LEF text and group by cut layer.

    Returns a dict::

        {
          "VIA1": {
              "total": 2,
              "single_cut": 2,
              "multi_cut": 0,
              "names": ["VIA12", "VIA12_hori"],
              "single_cut_names": ["VIA12", "VIA12_hori"],
              "multi_cut_names": [],
          },
          ...
        }
    """
    by_cut: Dict[str, Dict[str, Any]] = {}
    for vm in _VIA_BLOCK_RE.finditer(text):
        via_name = vm.group(1)
        body = vm.group(2)
        # Find the cut layer + its RECT count.
        cut_layer: str | None = None
        cut_rect_count = 0
        for lm in _LAYER_BLOCK_RE.finditer(body):
            lname = lm.group(1)
            lbody = lm.group(2)
            kind = _classify_layer_kind(lname)
            if kind != "cut":
                continue
            # Count RECT entries inside this LAYER block. The block
            # ends at the next "LAYER " or "END VIAname"; LAYER_BLOCK_RE
            # already stops at next LAYER, so just count RECT lines.
            count = len(_RECT_RE.findall(lbody))
            if count > cut_rect_count:
                cut_rect_count = count
                cut_layer = lname
        if cut_layer is None:
            continue
        slot = by_cut.setdefault(cut_layer, {
            "total": 0, "single_cut": 0, "multi_cut": 0,
            "names": [], "single_cut_names": [], "multi_cut_names": [],
        })
        slot["total"] += 1
        slot["names"].append(via_name)
        if cut_rect_count <= 1:
            slot["single_cut"] += 1
            slot["single_cut_names"].append(via_name)
        else:
            slot["multi_cut"] += 1
            slot["multi_cut_names"].append(via_name)
    return by_cut


def cut_layers_with_single_cut(text: str) -> Set[str]:
    """Return the set of cut-layer names (e.g. {'VIA1', 'VIA2', ...})
    for which the LEF defines at least one single-cut via."""
    out: Set[str] = set()
    for cut_name, info in analyze_lef(text).items():
        if info["single_cut"] >= 1:
            out.add(cut_name.upper())
    return out


def routing_layer_upper_bound(text: str) -> int | None:
    """Given the cut-layer single-cut coverage, return the highest metal
    layer index N such that all cut layers VIA1..VIA(N-1) have at least
    one single-cut via. Returns None if no single-cut vias exist at all
    or the LEF has no VIA blocks.

    Example: PDK has single-cut VIA1..VIA4 but only multi-cut VIA5 →
    returns 5 (route Metal1..Metal5; transitions M1↔M5 only need
    VIA1..VIA4).
    """
    covered = cut_layers_with_single_cut(text)
    if not covered:
        return None
    # Extract numeric suffix from VIA names (VIA1 → 1, VIA12 → 12 means
    # M1↔M2; VIA56 → 56 means M5↔M6 — handle both single-digit "VIA1"
    # and concatenated "VIA12" forms).
    indices: Set[int] = set()
    for v in covered:
        m = re.match(r"^VIA(\d+)$", v)
        if not m:
            continue
        s = m.group(1)
        if len(s) == 1:
            indices.add(int(s))                # VIA3 = M3↔M4 transition
        elif len(s) == 2 and s[0] == s[1]:     # never used in practice
            indices.add(int(s[0]))
        else:
            # VIA12 means M1↔M2 — first digit is the lower metal.
            indices.add(int(s[0]))
    if not indices:
        return None
    # Walk upward from 1 until we hit a gap.
    n = 1
    while n in indices:
        n += 1
    # n is the first cut layer NOT covered, so M1..Mn (one above the
    # last covered cut) is the safe routing range.
    return n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Audit a tech LEF for single-cut via coverage.",
    )
    ap.add_argument("tech_lef", help="Path to tech LEF file")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH",
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    p = Path(args.tech_lef)
    try:
        text = p.read_text(errors="ignore")
    except FileNotFoundError:
        print(f"error: file not found: {p}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: cannot read {p}: {exc}", file=sys.stderr)
        return 2

    by_cut = analyze_lef(text)
    missing = sorted(
        c for c, info in by_cut.items() if info["single_cut"] == 0
    )
    upper = routing_layer_upper_bound(text)
    report = {
        "tech_lef": str(p),
        "vias_by_cut_layer": by_cut,
        "single_cut_missing": missing,
        "safe_routing_upper_metal": upper,
        "verdict": "PASS" if not missing else "WARN",
    }
    txt = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        if args.json == "-":
            print(txt)
        else:
            outp = Path(args.json)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(txt + "\n")
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
