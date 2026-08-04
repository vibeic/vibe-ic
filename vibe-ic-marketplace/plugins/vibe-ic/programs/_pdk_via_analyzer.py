#!/usr/bin/env python3
"""_pdk_via_analyzer.py — chip-AGNOSTIC LEF via-block parser.

It answers two questions about the same blocks, from one scan:

  1. does every routing-layer transition have a SINGLE-CUT via (the original
     subject — OpenROAD DRT-0234), and
  2. is the metal PATCH each via drops on a routing layer at least as wide as
     that layer's own declared minimum width (vibe-ic#768)?

Both read the same `VIA` / `VIARULE ... GENERATE` blocks, so they share one
scanner. Question 2 arrived as a second file with a second, independently
re-derived parser; the two agreed on nothing but the easy case and the new one
could not see the `VIARULE` form at all. There is one parser now.

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
``parse_tech_lef(text) -> TechLef``               (the one scan; everything else
                                                   is a view on it)
``analyze_lef(text) -> Dict[str, Dict[str, Any]]``
``cut_layers_with_single_cut(text) -> Set[str]``  (caller-facing)
``routing_layer_min_widths(text) -> Dict[str, float]``
``via_patch_extents(text) -> Dict[Tuple[str, str], Dict[str, Tuple[float, float]]]``
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

import _prose_polarity


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

# --- the one line-based scan (vibe-ic#768) ---------------------------------
# `_VIA_BLOCK_RE` above deliberately does not match `VIARULE` (see its comment).
# That is right for the cut-count question — a VIARULE is a rule, not a fixed
# via — and wrong for the patch-width one, because the router GENERATES vias
# from those rules and the generated patch is `cut extent + 2*ENCLOSURE`. On
# sky130 the two forms state the SAME 1.42um met5 patch by different arithmetic
# (RECT -0.71..0.71, and 0.8 + 2*0.31), so a parser that reads only one form
# certifies a half-applied PDK fix as clean.
_NUM = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"
_LN_VIA_OPEN = re.compile(r"^VIA\s+(\S+)(?:\s+.*)?$")
_LN_VIARULE_OPEN = re.compile(r"^VIARULE\s+(\S+)\s+GENERATE\b.*$")
_LN_LAYER_OPEN = re.compile(r"^LAYER\s+(\S+)\s*$")
_LN_LAYER_REF = re.compile(r"^LAYER\s+(\S+)\s*;")
_LN_END = re.compile(r"^END\s+(\S+)\s*$")
_LN_TYPE = re.compile(r"^TYPE\s+(\w+)\s*;")
_LN_WIDTH = re.compile(rf"^WIDTH\s+({_NUM})\s*;")
_LN_MINWIDTH = re.compile(rf"^MINWIDTH\s+({_NUM})\s*;")
_LN_RECT = re.compile(
    rf"^RECT\s+(?:MASK\s+\d+\s+)?({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s*;")
_LN_ENCLOSURE = re.compile(rf"^ENCLOSURE\s+({_NUM})\s+({_NUM})\s*;")


class LayerEntry(NamedTuple):
    """One `LAYER <n> ;` occurrence inside a via block, and what followed it.

    An OCCURRENCE, not a per-name dict: `analyze_lef` counts RECTs per
    occurrence, and folding a layer that appears twice into one bucket would
    change a cut count that a routing decision is taken on.
    """
    layer: str
    rects: List[Tuple[float, float, float, float]]
    enclosure: Optional[Tuple[float, float]]


class ViaBlock(NamedTuple):
    kind: str                       # "VIA" (fixed) or "VIARULE" (GENERATE)
    name: str
    entries: List[LayerEntry]
    #: The denial word in the block's OWN lead comment, or None. See
    #: `_lead_comment_denial`.
    source_denial: Optional[str]
    #: That lead comment, verbatim. Carried so a consumer can PRINT the
    #: sentence beside the word it matched: a finding that says "the file
    #: denies this" without quoting the file is not checkable by its reader.
    source_comment: str


class RoutingLayer(NamedTuple):
    name: str
    min_width: float
    #: Which statement the width came from — `MINWIDTH` outranks `WIDTH`.
    width_source: str
    source_denial: Optional[str]


class TechLef(NamedTuple):
    routing: Dict[str, RoutingLayer]
    blocks: List[ViaBlock]


def _strip_lef(line: str) -> str:
    """The statement on `line`, with its comment and indentation removed."""
    return line.split("#", 1)[0].strip()


def _lead_comment_denial(blanked: str) -> Optional[str]:
    """The denial word in an already-scoped, already-blanked lead comment.

    `_prose_polarity` splits the work deliberately: the VOCABULARY is shared
    and the SCOPE — how far to look and what to blank first — belongs to the
    caller. This half is the vocabulary; `parse_tech_lef` owns the scope, and
    that scope is the whole of the correctness here: the CONTIGUOUS comment
    lines immediately above a block's opening line, with no blank line and no
    statement in between. A wider one would be wrong on this file type — the
    sky130 tech LEF opens with

        # This Techfile contains not correct Parasitic Information.

    as a FILE header, and a paragraph- or file-scoped rule would attach that
    denial to every layer and via in the file.

    MEASURED, and this is why the consult is here rather than omitted as
    ceremony: the same file writes

        # Centered via rule, we really do not want to use it
        VIA M4M5_PR_C DEFAULT

    directly above one of the five vias vibe-ic#768 reports. Publishing a
    finding from that block without saying the PDK itself deprecates the via
    states more than the file does. It is RECORDED, never subtracted — a
    comment cannot lower a verdict here, or the file being audited would hold
    the switch that silences the audit.

    ONE VOCABULARY ENTRY IS SKIPPED, and the same file is why. Two blocks
    below the one above it writes

        # Plus via rule, metals are along the non prefered direction
        VIA M4M5_PR_R DEFAULT

    and the shared vocabulary's `\\bnon-?\\b` fires on it. `non` is only ever a
    PREFIX — it denies the noun it is attached to (here: the preferred
    direction), never the statement — where `not` / `no` / `none` negate the
    clause they sit in. Taking it would have reported the PDK as deprecating a
    via it merely describes. Every other entry in both tiers is kept, and the
    FIRST clause-level denial wins, so a comment carrying both still reports
    the real one.
    """
    for m in _prose_polarity.NEGATION_RE.finditer(blanked or ""):
        word = m.group(0)
        if word.lower().rstrip("-") == "non":
            continue
        return word
    return None


def parse_tech_lef(text: str) -> TechLef:
    """One scan of a tech LEF: its routing layers' own minimum widths, and
    every via block's per-layer geometry.

    `MINWIDTH` outranks `WIDTH` where both are stated. They are different
    rules: `WIDTH` on a ROUTING layer is the DEFAULT routing width and
    `MINWIDTH` is the minimum legal width, which is the rule a patch-vs-width
    comparison is about. MEASURED over the 19 tech LEFs
    `ghcr.io/vibeic/vibeic-eda` ships: 66 routing layers state BOTH
    (`sky130_fd_sc_hvl*` and gf180) and on all 66 the two numbers are EQUAL;
    `sky130_fd_sc_hd*` and nangate45 state no `MINWIDTH` at all. So the
    precedence changes no shipped answer today, and is fixed while it is free
    rather than on the PDK that first states them apart.

    The FIRST bare `WIDTH <n> ;` is the layer rule. A `SPACINGTABLE` row is
    `WIDTH <n> <n> ;` and does not match — which matters, because on the PDK
    that motivated this the table row carries the very number the layer rule
    does, and reading the row as the rule would have made the two agree for
    the wrong reason.

    POLARITY. Every value below is a DECLARATION taken out of a text file and
    published as fact, which is the shape `_prose_polarity` exists for: a
    reader that never asks whether the surrounding text DENIES the value
    republishes a retired one as a mandate. This function owns the SCOPE half
    of that contract — the contiguous lead comment, bracketed spans blanked —
    and `_lead_comment_denial` owns the shared vocabulary. It is RECORDED on
    the block, never subtracted from a verdict: a file that could deny its own
    audit would hold the switch that silences it.

    Pure and chip-/PDK-AGNOSTIC: no layer-name literal, no per-PDK table.
    """
    routing: Dict[str, RoutingLayer] = {}
    blocks: List[ViaBlock] = []

    def _denial(lead_lines: List[str]) -> Optional[str]:
        # SCOPE: the contiguous lead comment only, with bracketed qualifiers
        # blanked first — #711's measurement, kept length-preserving by
        # `blank_bracketed` so the caller's offsets would stay valid.
        if not lead_lines:
            return None
        return _lead_comment_denial(
            _prose_polarity.blank_bracketed(" ".join(lead_lines)))

    lines = text.splitlines()
    lead: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        stripped_raw = raw.strip()
        ln = _strip_lef(raw)
        if not ln:
            # A comment line contributes to the lead; a blank line clears it.
            if stripped_raw.startswith("#"):
                lead.append(stripped_raw.lstrip("#").strip())
            else:
                lead = []
            i += 1
            continue

        m_via = _LN_VIA_OPEN.match(ln)
        m_rule = _LN_VIARULE_OPEN.match(ln)
        m_layer = _LN_LAYER_OPEN.match(ln)
        if m_via or m_rule:
            kind = "VIARULE" if m_rule else "VIA"
            name = (m_rule or m_via).group(1)
            entries: List[LayerEntry] = []
            cur = -1                    # index into `entries`, never identity:
            j = i + 1                   # two occurrences of one layer compare
            while j < n:                # equal, and `.index()` would alias them
                b = _strip_lef(lines[j])
                if not b:
                    j += 1
                    continue
                e = _LN_END.match(b)
                if e and e.group(1) == name:
                    break
                lref = _LN_LAYER_REF.match(b)
                if lref:
                    entries.append(LayerEntry(lref.group(1), [], None))
                    cur = len(entries) - 1
                    j += 1
                    continue
                if cur >= 0:
                    r = _LN_RECT.match(b)
                    if r:
                        entries[cur].rects.append(
                            tuple(float(g) for g in r.groups()))
                        j += 1
                        continue
                    en = _LN_ENCLOSURE.match(b)
                    if en:
                        entries[cur] = entries[cur]._replace(
                            enclosure=(float(en.group(1)),
                                       float(en.group(2))))
                j += 1
            if j < n:                                # an END was found
                blocks.append(ViaBlock(kind, name, entries,
                                       _denial(lead), " ".join(lead)))
                i = j + 1
            else:                                    # unterminated block
                i += 1
            lead = []
            continue

        if m_layer:
            lname = m_layer.group(1)
            ldenial = _denial(lead)
            ltype = lwidth = lminwidth = None
            j = i + 1
            while j < n:
                b = _strip_lef(lines[j])
                if not b:
                    j += 1
                    continue
                e = _LN_END.match(b)
                if e and e.group(1) == lname:
                    break
                t = _LN_TYPE.match(b)
                if t:
                    ltype = t.group(1).upper()
                    j += 1
                    continue
                w = _LN_WIDTH.match(b)
                if w and lwidth is None:
                    lwidth = float(w.group(1))
                    j += 1
                    continue
                mw = _LN_MINWIDTH.match(b)
                if mw and lminwidth is None:
                    lminwidth = float(mw.group(1))
                j += 1
            if ltype == "ROUTING":
                if lminwidth is not None:
                    routing[lname] = RoutingLayer(lname, lminwidth,
                                                  "MINWIDTH", ldenial)
                elif lwidth is not None:
                    routing[lname] = RoutingLayer(lname, lwidth,
                                                  "WIDTH", ldenial)
            i = (j + 1) if j < n else (i + 1)
            lead = []
            continue

        lead = []
        i += 1

    return TechLef(routing, blocks)


def routing_layer_min_widths(text: str) -> Dict[str, float]:
    """`{routing layer: its own declared minimum width}`. A CUT layer has no
    width rule of this kind and never appears here."""
    return {k: v.min_width for k, v in parse_tech_lef(text).routing.items()}


def patch_extents(tl: TechLef, block: ViaBlock
                  ) -> Dict[str, Tuple[float, float]]:
    """`{routing layer: (dx, dy)}` — the metal extent this block puts on each
    routing layer, which is what the layout sees after the shapes merge.

    Two forms, both of which a router uses:

      `VIA`      the bounding box of the RECTs the block declares on the layer.
      `VIARULE`  `cut extent + 2 x ENCLOSURE` on each axis, the single-cut and
                 therefore worst case — a multi-cut array has a larger cut
                 envelope, so the same enclosure yields a wider patch.

    The CUT layer is identified as the one the FILE does not declare to be a
    routing layer, not by name vocabulary, so it holds on a PDK that names its
    cut layers anything at all.
    """
    out: Dict[str, Tuple[float, float]] = {}
    cut: Optional[Tuple[float, float]] = None
    for e in block.entries:
        if e.layer in tl.routing or not e.rects:
            continue
        xs = [r[0] for r in e.rects] + [r[2] for r in e.rects]
        ys = [r[1] for r in e.rects] + [r[3] for r in e.rects]
        cut = (round(max(xs) - min(xs), 9), round(max(ys) - min(ys), 9))
    for e in block.entries:
        if e.layer not in tl.routing:
            continue
        if block.kind == "VIA":
            if not e.rects:
                continue
            xs = [r[0] for r in e.rects] + [r[2] for r in e.rects]
            ys = [r[1] for r in e.rects] + [r[3] for r in e.rects]
            dx, dy = round(max(xs) - min(xs), 9), round(max(ys) - min(ys), 9)
        else:
            if e.enclosure is None or cut is None:
                continue
            dx = round(cut[0] + 2.0 * e.enclosure[0], 9)
            dy = round(cut[1] + 2.0 * e.enclosure[1], 9)
        prev = out.get(e.layer)
        out[e.layer] = (dx, dy) if prev is None else (max(prev[0], dx),
                                                      max(prev[1], dy))
    return out


def via_patch_extents(text: str
                      ) -> Dict[Tuple[str, str], Dict[str, Tuple[float,
                                                                 float]]]:
    """`{(kind, name): {routing layer: (dx, dy)}}` over BOTH via forms.

    Keyed on `(kind, name)` because a tech LEF routinely declares
    `VIA M4M5_PR DEFAULT` and `VIARULE M4M5_PR GENERATE` — same name, two
    different statements, and both close with `END M4M5_PR`.
    """
    tl = parse_tech_lef(text)
    return {(b.kind, b.name): patch_extents(tl, b) for b in tl.blocks}


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
    ``via2`` (met2↔met3 → index 2) all map correctly. Pure, chip-AGNOSTIC.

    Reads the shared scan (`parse_tech_lef`) rather than its own regex pass,
    so the cut-count question and the patch-width question can no longer
    disagree about which blocks and which shapes a file declares. FIXED-via
    blocks only: a `VIARULE ... GENERATE` states a rule, not a cut count, and
    counting it would report single-cut coverage a fixed via does not provide.
    """
    cover: Dict[int, bool] = {}
    for blk in parse_tech_lef(text).blocks:
        if blk.kind != "VIA":
            continue
        routing_idx: List[int] = []
        cut_rect_count = 0
        for e in blk.entries:
            kind = _classify_layer_kind(e.layer)
            if kind == "routing":
                ri = _routing_index(e.layer)
                if ri is not None:
                    routing_idx.append(ri)
            elif kind == "cut":
                cut_rect_count = max(cut_rect_count, len(e.rects))
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

    Reads the shared scan; FIXED-via blocks only, for the reason stated on
    `via_transition_coverage`.
    """
    by_cut: Dict[str, Dict[str, Any]] = {}
    for blk in parse_tech_lef(text).blocks:
        if blk.kind != "VIA":
            continue
        via_name = blk.name
        # Find the cut layer + its RECT count.
        cut_layer: str | None = None
        cut_rect_count = 0
        for e in blk.entries:
            if _classify_layer_kind(e.layer) != "cut":
                continue
            count = len(e.rects)
            if count > cut_rect_count:
                cut_rect_count = count
                cut_layer = e.layer
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
