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
    """Return 'cut' if name looks like a via cut layer, 'routing' if METn /
    METALn / Mn, else 'unknown'.

    GAP#1 (round-7) — a via cut layer is NOT always ``VIAn``. SKY130 names
    its cut layers ``mcon`` (li1↔met1), ``via`` (met1↔met2, UNNUMBERED),
    ``via2``/``via3``/``via4`` — so the old `startswith("VIA") and has-digit`
    test classified the bare ``via`` and ``mcon`` as 'unknown', dropping the
    M1↔M2 transition from coverage and collapsing signal routing to met1.
    Recognise the bare/unnumbered cut names too. chip-AGNOSTIC: matches the
    generic via/cut/mcon vocabulary, not any chip literal."""
    n = name.upper()
    # routing layers FIRST (so a metal like METAL1 isn't mistaken for a cut).
    if (n.startswith("MET") or n.startswith("METAL") or
            (n.startswith("M") and len(n) >= 2 and n[1].isdigit())):
        return "routing"
    # cut layers: VIAn, the bare/unnumbered VIA, and the sub-metal contact
    # cuts (MCON / LICON / CONT / CO). The structural `routing-pair`
    # derivation below assigns the transition index, so the cut NAME need
    # only be recognised AS a cut — its digits are not relied upon.
    if n.startswith("VIA") or n in ("MCON", "LICON", "LICON1",
                                    "CONT", "CO", "CONTACT"):
        return "cut"
    return "unknown"


def _routing_index(name: str) -> int | None:
    """Map a routing-layer NAME to its metal index (met1→1, metal3→3, M5→5,
    li1→0 = the local-interconnect sub-metal). Returns None if not a routing
    layer. Pure, chip-AGNOSTIC."""
    n = name.upper()
    if n in ("LI", "LI1"):
        return 0  # local interconnect sits below met1.
    m = re.match(r"^(?:METAL|MET|M)(\d+)$", n)
    if m:
        return int(m.group(1))
    return None


def via_transition_coverage(text: str) -> Dict[int, bool]:
    """Structural single-cut coverage keyed by the LOWER metal index of each
    routing-layer transition a via spans. For a via connecting met(k)↔met(k+1)
    the transition index is k; the value is True iff at least one single-cut
    via covers it.

    This is naming-AGNOSTIC: it does NOT parse digits out of the cut-layer
    name (which fails on SKY130's unnumbered ``via`` = M1↔M2). It derives the
    transition from the two ROUTING layers the via block actually connects,
    so ``mcon`` (li1↔met1 → index 0), ``via`` (met1↔met2 → index 1),
    ``via2`` (met2↔met3 → index 2) all map correctly. Pure, chip-AGNOSTIC."""
    cover: Dict[int, bool] = {}
    for vm in _VIA_BLOCK_RE.finditer(text):
        body = vm.group(2)
        routing_idx: List[int] = []
        cut_rect_count = 0
        for lm in _LAYER_BLOCK_RE.finditer(body):
            lname = lm.group(1)
            lbody = lm.group(2)
            kind = _classify_layer_kind(lname)
            if kind == "routing":
                ri = _routing_index(lname)
                if ri is not None:
                    routing_idx.append(ri)
            elif kind == "cut":
                cut_rect_count = max(cut_rect_count,
                                     len(_RECT_RE.findall(lbody)))
        if len(routing_idx) < 2:
            continue
        lo = min(routing_idx)
        is_single = (cut_rect_count <= 1)
        # transition index = lower metal index; True wins (any single-cut
        # via on the transition makes it covered).
        cover[lo] = cover.get(lo, False) or is_single
    return cover


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
    """Return the highest metal layer index N up to which signal routing is
    safe — i.e. every met1↔met2 … met(N-1)↔metN transition has at least one
    SINGLE-CUT via. Returns None when no restriction is warranted (every
    present transition from met1 up is single-cut-covered, the common case
    incl. SKY130) OR when the LEF has no analysable via blocks.

    GAP#1 fix: the transition coverage is now derived STRUCTURALLY from the
    routing-layer pair each via spans (see via_transition_coverage), NOT from
    digits in the cut-layer name. SKY130's unnumbered ``via`` (met1↔met2) and
    ``mcon`` (li1↔met1) are therefore counted, so the analyzer no longer
    falsely reports the M1↔M2 transition as missing and collapses signal
    routing to met1-met1 (which caused GRT-0229). A restriction is returned
    ONLY when a real gap exists (a transition above met1 has multi-cut-only
    vias), and it is floored at met2 — never met1 — so signal routing always
    has at least two layers (a single-metal signal route cannot complete).
    """
    cover = via_transition_coverage(text)
    # keep only the metal-to-metal transitions (index >= 1); index 0 is the
    # li1↔met1 sub-metal contact, not a signal-routing metal transition.
    metal_tx = {k: ok for k, ok in cover.items() if k >= 1}
    if not metal_tx:
        return None  # no analysable metal vias → no restriction (route all).
    # Walk met1 upward: the last fully single-cut-covered transition k means
    # routing up to met(k+1) is safe. Stop at the first uncovered transition.
    k = 1
    while metal_tx.get(k) is True:
        k += 1
    # k is the first UNCOVERED metal transition. If k never advanced past 1
    # AND transition 1 itself isn't present, there is nothing to restrict.
    if k == 1 and 1 not in metal_tx:
        return None
    # highest safe routing metal = the upper metal of the last covered
    # transition = k (transition k-1 covers met(k-1)↔met(k)).
    bound = k
    # Determine the highest metal transition actually present so we can tell
    # "fully covered" (no restriction) from "gap in the middle" (restrict).
    max_tx = max(metal_tx)
    if bound > max_tx:
        # every present transition is covered → no restriction needed.
        return None
    # A genuine gap exists at transition `bound`; restrict routing to
    # met1..met{bound}. Floor at met2 so a single-cut-missing met1↔met2
    # never collapses signal routing to one layer.
    return max(bound, 2)


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
