#!/usr/bin/env python3
"""ppa_area_threshold_check.py — v1.0 plugin gate (ORGANIC #729).

DETERMINISTIC PPA area-reduction-threshold gate for lint / PPA-optimization
problems (e.g. cid007 "reduce the area of this RTL"): synthesise the ORIGINAL
RTL and the OPTIMIZED RTL with the SAME yosys recipe, read `stat`'s `Number of
cells` + `Number of wires` off BOTH, compute the cell% and wire% reduction of
optimized-vs-original, and BLOCK if EITHER bound metric is below the prompt-
stated threshold.

THE FAILURE THIS CLOSES
-----------------------
On a v1.0.77 forward-verify, an area-optimization (cid007) problem passed every
shipped gate (interface / hygiene / lint / iverilog / verilator clean,
equivalence PASS) yet its first draft achieved only ~3% area reduction at the
gate level while the spec's success metric is a measurable >=N% reduction in
cells AND wires vs the provided original. No plugin program synthesised the
(original, optimized) pair and checked the delta, so the deterministic chain
could not verify the optimization TARGET — only the hidden scorer's synth gate
could. This program IS that deterministic check.

WHAT IT DOES
------------
  1. Parse the threshold + which metric(s) it binds (cells / wires / both) from
     the prompt text (``--prompt`` file or ``--threshold-pct`` + ``--metric``).
  2. Run yosys ``stat`` on the ORIGINAL and the OPTIMIZED RTL with the SAME
     synth recipe inside the vibeic-eda container. The recipe emits the `stat`
     TWICE: once on the technology-INDEPENDENT GENERIC netlist (after
     ``synth -flatten; opt`` but BEFORE ``techmap``/``abc -g cmos2`` — the
     coarse-grain ``$add``/``$mul``/``$dff`` cells), and once on the
     technology-MAPPED netlist (after ``abc -g cmos2`` — the cmos2 gate count),
     so BOTH a tech-independent and a tech-mapped delta are available.
  3. Compute  reduction% = 100 * (orig - opt) / orig  for cells and for wires,
     on BOTH the GENERIC and the MAPPED counts.
  4. BLOCK (rc 1) iff a BOUND metric's MAPPED reduction is below the stated
     threshold — UNLESS the same metric's GENERIC reduction is ALSO below the
     threshold, which proves the design is already NEAR-MINIMAL (no equivalent
     rewrite, incl. the golden, can clear the bar on the tech-independent count
     either): that is downgraded to NOT-APPLICABLE / advisory, never a BLOCK.

UNREACHABLE-TARGET ESCAPE (§4.05 — false-BLOCK is irreversible)
--------------------------------------------------------------
On a near-minimal design the stated reduction target (e.g. 20% cells+wires) can
be UNACHIEVABLE by ANY functionally-equivalent rewrite — including the golden —
because synthesis already shares the source redundancy and the cmos2-mapped
floor is reached. The MAPPED measurement is right, but an all-or-nothing BLOCK
on an unreachable target would block EVERY equivalent answer including the
golden. The escape: when a bound metric's MAPPED reduction is sub-threshold but
NON-NEGATIVE AND its GENERIC (pre-abc / pre-techmap, technology-independent)
reduction is ALSO sub-threshold, the design MIGHT be near-minimal. CRUCIAL
no-leak: a lazily-optimized design whose GENERIC reduction is AT/ABOVE the
threshold (so it COULD still reach the target) is STILL BLOCKED — only a
proven-near-minimal one is downgraded. SECOND no-leak (#739 remediation): a
design whose MAPPED reduction for a bound metric is NEGATIVE (optimized is LARGER
than original — the submission made the count WORSE) is never near-minimal, so
the escape does NOT fire for it and it is STILL BLOCKED regardless of the generic
count.

GENERIC-MEETS-TARGET (ORGANIC #769 / R6C12) — the CVDP scorer measures GENERIC
-----------------------------------------------------------------------------
The MAPPED (post-`abc -g cmos2`) count is NOT the ground-truth area metric for
the CVDP reference scorer: that scorer's synth.tcl ends at ``synth -top; clean``
with NO techmap/``abc -g cmos2`` and measures the GENERIC ``stat`` cell count
(.env carries ``CELLS=<orig_generic>`` + ``PERCENT_CELLS=<thr>``). So a metric
whose GENERIC reduction CLEARS the bar HAS MET the target the scorer enforces —
even when its MAPPED reduction falls short because a SHARED, irreducible
post-techmap combinational floor (a fixed permutation/mux network) dilutes the
mapped percentage. Treating that as "generic headroom → BLOCK" is exactly
inverted: the generic count the gate would block on is the count the scorer
PASSES. The fix: a sub-threshold-but-NON-NEGATIVE MAPPED metric whose GENERIC
reduction MEETS the bar is SATISFIED (PASS), checked BEFORE the headroom/escape
logic. No-leak: the MAPPED reduction must be NON-NEGATIVE (a GROWN metric is a
real regression, never excused — tracked in its own bucket that DOMINATES even
under an OR combinator so no disjunctive PASS can mask it), and the GENERIC
reduction must itself MEET the bar (a lazy/do-nothing submission has a
sub-threshold generic reduction so it never reaches here).

REACHABILITY IS SUBMISSION-INDEPENDENT (ORGANIC #768 / R6C11)
------------------------------------------------------------
The legacy escape used the SUBMISSION's OWN generic reduction as the
unreachability proxy: a sub-threshold submission whose OWN generic delta is also
sub-threshold was labelled "near-minimal / unreachable". That CONFLATES "how much
THIS submission reduced" with "how much reduction is ACHIEVABLE" — a do-nothing
copy of the original (0% generic) or a shallow submission (small generic delta
because it SKIPPED the structural register-merge / resource-share win) is excused
even though the golden proves the bar is eminently reachable on the SAME
original. Reachability must be anchored INDEPENDENTLY of the submission. Two
anchors now gate the escape, and BOTH must fail for it to fire:
  (1) REFERENCE anchor: when a ``--reference`` golden is supplied, its GENERIC
      reduction vs the original is measured; if the golden CLEARS the generic bar
      the target is PROVEN reachable → a sub-threshold submission is a REAL
      under-reduction (BLOCK), never excused.
  (2) NO-OP FLOOR (no-reference safety net): with NO reference, a submission
      whose own GENERIC reduction is at/below a TIGHT epsilon (the no-op floor,
      just above measurement noise) removed essentially NOTHING — a do-nothing /
      literal-copy answer — so it is a REAL under-reduction (BLOCK). The epsilon
      is deliberately tight so a submission that did real-but-insufficient generic
      work is NOT floor-blocked without a reference (no no-reference false-BLOCK);
      that small-but-real sub-threshold case is caught only when a --reference
      golden proves the bar reachable.

The %-computation + threshold-compare is factored into PURE functions
(``compute_reduction_pct`` / ``parse_threshold_from_prompt`` / ``decide``) so it
is unit-tested against CANNED yosys ``stat`` text WITHOUT needing the container.

§4.05 NO-LEAK (this is a BLOCKING gate)
---------------------------------------
This gate only ever BLOCKs on a REAL measured under-threshold reduction. EVERY
other outcome is a non-blocking exit-0 NOT-APPLICABLE / SKIP, never a false
block:
  * yosys / the vibeic-eda container is unavailable     → NOT-APPLICABLE rc 0.
  * yosys synth fails / `stat` yields no cell|wire #  → NOT-APPLICABLE rc 0.
  * the threshold cannot be parsed from the prompt    → NOT-APPLICABLE rc 0.
  * the ORIGINAL has 0 cells (degenerate, can't form  → NOT-APPLICABLE rc 0.
    a percentage)
  * a sub-threshold MAPPED reduction whose GENERIC reduction → NOT-APPLICABLE
    is ALSO sub-threshold (proven-near-minimal / unreachable    rc 0 (advisory).
    target — no equivalent rewrite incl. golden can clear it)
A real, fully-measured MAPPED reduction at or above the threshold is a PASS
(rc 0); a sub-threshold MAPPED reduction whose GENERIC reduction shows REAL
headroom (>= threshold, i.e. the design COULD have reached the target) is the
ONLY BLOCK (rc 1).

chip-AGNOSTIC: pure synth-stat measurement + arithmetic; no design / chip /
vendor / SKU / PDK literal.

Usage:
    python3 ppa_area_threshold_check.py \\
        --original <orig>.v --optimized <opt>.v --top <module> \\
        ( --prompt <prompt.txt> | --threshold-pct 20 [--metric both] ) \\
        [--container vibeic-eda] [--json OUT]

Exit codes:
    0  PASS (reduction >= threshold)  OR  NOT-APPLICABLE / SKIP (no yosys, no
       parseable threshold, unmeasurable) — NEVER a false block.
    1  BLOCK — a real, measured reduction is below the stated threshold.
    2  setup / argument error (missing file, contradictory args).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from _ppa import cli_exit  # PPA_INTERFACES §1: argparse exits 2; a bad invocation is 3
from _ppa import area as _ppa_area  # noqa: E402  (PPA-009 taxonomy labels)

# ─── WHAT CLASS OF NUMBER THIS GATE PRODUCES (PPA-009, spec §7.3) ────────────
# Everything this program measures is a COUNT off a yosys netlist: cells and
# wires, and the percentage reductions computed from them. Not one of those is
# an area. On a real completed run (`spm`, gf180mcuD) the three numbers that all
# get called "the area" were
#
#     synthesis chip area   4703.5296  library area units, PRE-placement
#     post-route core area  12294      um^2
#     die area              20164.00   um^2
#
# — the synthesis figure is 2.61x under the core and 4.29x under the die, and it
# is not even in the same unit. This gate's counts sit BELOW even that figure in
# the chain of things that determine silicon area. So the report is stamped
# RTL_PROXY / not eligible for physical PPA, and `_ppa.area` refuses to promote
# a record carrying that stamp. The stamp is taken FROM `_ppa.area` rather than
# spelled out here, so that exactly one registry decides what is physical.
# The registry names for the four numbers this gate reports. Naming them here
# means a reader (or a promoter) can look each one up and find RTL_PROXY, rather
# than having to infer a class from the field name.
_PROXY_METRICS = (
    "area.proxy.cell_count",
    "area.proxy.wire_count",
    "area.proxy.cell_count_reduction_pct",
    "area.proxy.wire_count_reduction_pct",
)
_METRIC_CLASS = _ppa_area.RTL_PROXY
_ELIGIBLE_FOR_PHYSICAL_PPA = False
_PROXY_NOTE = (
    "cells/wires are COUNTS off a yosys netlist, taken before placement, "
    "routing, filler and the die envelope exist. A cell-count win is not an "
    "area win: this verdict may never be reported as, promoted to, or "
    "substituted for post-route core/die/standard-cell area. See "
    "docs/PPA_INTERFACES.md §2 and programs/_ppa/area.py.")

# ─── prompt threshold parse ──────────────────────────────────────────────────
# The metric a threshold binds. "both" is the conservative default for an
# area-reduction spec (cells AND wires must both clear the bar).
_METRIC_CELLS = "cells"
_METRIC_WIRES = "wires"
_METRIC_BOTH = "both"
_VALID_METRICS = (_METRIC_CELLS, _METRIC_WIRES, _METRIC_BOTH)

# A percentage threshold near a reduction/area/cell/wire keyword. We bind the
# FIRST such percentage in the prompt. Ordinary-English tokens only match here
# in their natural prose form; nothing here keys off a chip/SKU name.
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# words that, when present near the percentage, indicate it is an AREA-reduction
# target (so we do not pick up an unrelated "50% duty cycle" percentage).
_AREA_WORDS = ("reduc", "reduction", "smaller", "fewer", "less", "area",
               "cell", "cells", "wire", "wires", "gate", "gates", "shrink")
_CELL_WORDS = ("cell", "cells", "gate", "gates", "logic", "lut", "luts")
_WIRE_WORDS = ("wire", "wires", "net", "nets", "interconnect", "routing")


class ThresholdParseError(ValueError):
    """The prompt does not contain a parseable area-reduction threshold."""


def parse_threshold_from_prompt(prompt: str
                                ) -> Tuple[float, str]:
    """Extract (threshold_pct, metric) from a prompt's natural-language text.

    PURE — no I/O. Returns the first area-reduction percentage and which metric
    it binds:
      * mentions cells AND wires (or "area" / "both")  → ``both``
      * mentions ONLY cells / gates / logic            → ``cells``
      * mentions ONLY wires / nets                      → ``wires``
      * a bare reduction percentage with no cell/wire    → ``both`` (the
        conservative default: an unqualified area target binds both metrics).
    Raises ThresholdParseError if no area-reduction percentage is present (the
    caller turns that into a NON-BLOCKING NOT-APPLICABLE — §4.05).
    """
    if not prompt or not prompt.strip():
        raise ThresholdParseError("empty prompt")
    text = prompt
    low = text.lower()
    # find every "<n>%" and keep the first one whose surrounding ±60-char window
    # mentions an area-reduction word.
    best: Optional[Tuple[float, str]] = None
    for m in _PCT_RE.finditer(text):
        pct = float(m.group(1))
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
        window = low[a:b]
        if not any(w in window for w in _AREA_WORDS):
            continue
        has_cell = any(w in window for w in _CELL_WORDS)
        has_wire = any(w in window for w in _WIRE_WORDS)
        if has_cell and has_wire:
            metric = _METRIC_BOTH
        elif has_cell and not has_wire:
            metric = _METRIC_CELLS
        elif has_wire and not has_cell:
            metric = _METRIC_WIRES
        else:
            # an "area" / "reduce by" percentage with neither cell nor wire word
            # → conservative both-metric bind.
            metric = _METRIC_BOTH
        best = (pct, metric)
        break
    if best is None:
        raise ThresholdParseError(
            "no area-reduction percentage found in the prompt (looked for a "
            "'<n>%' near a reduce/area/cell/wire word)")
    return best


# ─── per-metric DISJUNCTIVE / CONJUNCTIVE clause parse (ORGANIC #756) ─────────
# A success criterion can bind a DIFFERENT threshold to EACH metric, joined by
# 'or' (a disjunction — ANY clause clears the bar) or 'and' (a conjunction — ALL
# clauses must clear). e.g. "minimum reduction must be 12% for wires OR 8% for
# cells" → two clauses [(12,'wires'),(8,'cells')] joined by OR.
# The single-tuple parse_threshold_from_prompt() above grabs only the FIRST '%'
# and (when both 'cells' and 'wires' bleed into its ±60-char window) collapses to
# a single 'both' (cells AND wires at the SAME threshold) — doubly wrong (wrong
# per-metric bars + wrong combinator). parse_threshold_clauses_from_prompt()
# fixes that: it scans ALL area '%'s and attaches each to the metric word NEAREST
# it (so 12% binds wires, 8% binds cells), and reads the connective between the
# clauses. chip-AGNOSTIC: ordinary-English tokens only; no design/SKU literal.
_COMBINATOR_OR = "or"
_COMBINATOR_AND = "and"
# the single metric tokens we bind a clause to, by their character offsets.
_CELL_TOKEN_RE = re.compile(
    r"\b(cell|cells|gate|gates|logic|lut|luts)\b", re.IGNORECASE)
_WIRE_TOKEN_RE = re.compile(
    r"\b(wire|wires|net|nets|interconnect|routing)\b", re.IGNORECASE)


def _nearest_metric_for_pct(text: str, low: str, pct_start: int, pct_end: int
                            ) -> Optional[str]:
    """Bind a single '%' (at [pct_start,pct_end)) to the metric word it names.

    PURE. Specs phrase a per-metric clause as "<n>% [...] for <metric>" — the
    binding metric word FOLLOWS the '%' (e.g. "12% ... for wires", "8% for
    cells"). So we look FORWARD first: the closest single cell-token / wire-token
    AFTER the '%' (up to the next '%' or a clause break) is decisive. Only when
    NO metric word follows within range do we look BACKWARD (a "reduce wires by
    12%" phrasing where the metric precedes). This forward-priority is what keeps
    "...for wires OR 8% for cells" from binding the 8% to the previous clause's
    trailing 'wires': 'cells' follows the 8%, 'wires' precedes it, so 8%→cells.
    Returns 'cells'/'wires', or None when no single metric word is in range (the
    caller then falls back to the conservative 'both' bind). Does NOT collapse to
    'both' on clause-bleed — it picks the clause's OWN metric."""
    # FORWARD window: from just after the '%' up to the FIRST clause boundary —
    # the next '%', or a connective that starts the NEXT clause ('and'/'or'/','/
    # ';'), or +56 chars, whichever comes first. Stopping at the connective is
    # what keeps the first clause's forward scan ("...20% and wires...") from
    # reaching into the SECOND clause's metric word.
    fwd_end = min(len(text), pct_end + 56)
    nxt = text.find("%", pct_end)
    if nxt != -1 and nxt < fwd_end:
        fwd_end = nxt
    conn = re.search(r"[,;]|\b(?:and|or|either|while|whereas)\b",
                     text[pct_end:fwd_end], re.IGNORECASE)
    if conn is not None:
        fwd_end = pct_end + conn.start()
    fwd = text[pct_end:fwd_end]

    def _closest_fwd(rx) -> Optional[int]:
        best: Optional[int] = None
        for mm in rx.finditer(fwd):
            if best is None or mm.start() < best:
                best = mm.start()
        return best

    fc = _closest_fwd(_CELL_TOKEN_RE)
    fw = _closest_fwd(_WIRE_TOKEN_RE)
    if fc is not None or fw is not None:
        if fw is None:
            return _METRIC_CELLS
        if fc is None:
            return _METRIC_WIRES
        return _METRIC_CELLS if fc < fw else _METRIC_WIRES

    # BACKWARD fallback: nearest metric word BEFORE the '%' (within 60 chars,
    # not crossing a previous '%').
    # ORGANIC #771 — widened 40→60 to MATCH the single-tuple parser's ±60-char
    # window (`parse_threshold_from_prompt`, line ~198). The asymmetric 40-char
    # backward reach let an explicitly single-metric spec ("…the number of wires
    # used. The minimum reduction must be 50%…") whose metric word sits 41–60
    # chars before the '%' fall through to the conservative `both` bind, so a
    # correct wire-only / cell-only optimization silently degraded to a
    # NOT-APPLICABLE no-enforcement verdict on a degenerate-but-correct design.
    bwd_start = max(0, pct_start - 60)
    prev = text.rfind("%", 0, pct_start)
    if prev != -1 and prev >= bwd_start:
        bwd_start = prev + 1
    bwd = text[bwd_start:pct_start]

    def _closest_bwd(rx) -> Optional[int]:
        best: Optional[int] = None
        for mm in rx.finditer(bwd):
            # distance from end of match to the '%' (smaller = nearer)
            d = len(bwd) - mm.end()
            if best is None or d < best:
                best = d
        return best

    bc = _closest_bwd(_CELL_TOKEN_RE)
    bw = _closest_bwd(_WIRE_TOKEN_RE)
    if bc is None and bw is None:
        return None
    # ORGANIC #771 — when BOTH a cell and a wire token sit in the backward window
    # AND no clause break ('and'/'or'/','/';') separates the nearer one from the
    # '%', this is a SINGLE "both cells and wires by N%" clause, not two clauses.
    # Return None so the caller binds the conservative `both` — matching the
    # single-tuple parser's co-occurrence semantics (line ~204) and preventing the
    # widened (60-char) backward window from mis-binding a true `both` spec to the
    # nearer single metric. (Two genuinely separate clauses are split by the
    # forward-priority scan above before ever reaching here.)
    if bc is not None and bw is not None:
        near_off = len(bwd) - min(bc, bw)   # start offset of the NEARER token
        if not re.search(r"[,;]|\b(?:and|or|either|while|whereas)\b",
                         bwd[near_off:], re.IGNORECASE):
            return None
    if bw is None:
        return _METRIC_CELLS
    if bc is None:
        return _METRIC_WIRES
    return _METRIC_CELLS if bc < bw else _METRIC_WIRES


def parse_threshold_clauses_from_prompt(
        prompt: str) -> Tuple[List[Tuple[float, str]], str]:
    """Extract per-metric reduction clauses + their combinator from a prompt.

    PURE — no I/O. Returns (clauses, combinator):
      * clauses = [(threshold_pct, metric), ...] where metric ∈ {cells, wires,
        both}; one entry per area-reduction '%' in the prompt, each bound to the
        metric word NEAREST it (so '12% for wires or 8% for cells' → [(12,wires),
        (8,cells)], NOT a single (12,both)).
      * combinator ∈ {'or','and'}: 'or' iff an 'or'/'either' connective sits
        between the clauses (a DISJUNCTION — ANY satisfied clause PASSes);
        otherwise 'and' (the conservative default — ALL clauses must clear).
    A clause whose '%' has no single nearby metric word falls back to a 'both'
    bind for that clause (same conservative default as the single-tuple parse).
    Raises ThresholdParseError when no area '%' is present (caller → NOT-
    APPLICABLE). Deduplicates identical (pct,metric) clauses while preserving
    order so a metric repeated in prose does not inflate the clause set."""
    if not prompt or not prompt.strip():
        raise ThresholdParseError("empty prompt")
    text = prompt
    low = text.lower()
    raw: List[Tuple[int, int, float, str]] = []   # (start, end, pct, metric)
    for m in _PCT_RE.finditer(text):
        pct = float(m.group(1))
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
        window = low[a:b]
        if not any(w in window for w in _AREA_WORDS):
            continue
        metric = _nearest_metric_for_pct(text, low, m.start(), m.end())
        if metric is None:
            metric = _METRIC_BOTH   # conservative default for a bare % clause
        raw.append((m.start(), m.end(), pct, metric))
    if not raw:
        raise ThresholdParseError(
            "no area-reduction percentage found in the prompt (looked for a "
            "'<n>%' near a reduce/area/cell/wire word)")

    # dedupe identical (pct, metric) clauses, preserve first-seen order.
    clauses: List[Tuple[float, str]] = []
    seen = set()
    for _s, _e, pct, metric in raw:
        key = (pct, metric)
        if key not in seen:
            seen.add(key)
            clauses.append(key)

    # combinator: look at the connective text BETWEEN the first two clause '%'s.
    # An explicit 'or'/'either' between them ⇒ disjunction; an explicit 'and'/
    # 'both' ⇒ conjunction; nothing ⇒ conservative 'and'.
    combinator = _COMBINATOR_AND
    if len(raw) >= 2:
        gap = low[raw[0][1]:raw[1][0]]
        if re.search(r"\bor\b|\beither\b", gap):
            combinator = _COMBINATOR_OR
        elif re.search(r"\band\b|\bboth\b", gap):
            combinator = _COMBINATOR_AND
    return clauses, combinator


def _metric_red(metric: str, cells_red: Optional[float],
                wires_red: Optional[float]) -> Optional[float]:
    """The MAPPED reduction for a SINGLE-metric clause. A 'both' clause is NOT
    collapsed here — it is expanded into its two underlying metrics and each is
    classified separately (see `_clause_metrics` / the decide_clauses loop), so a
    per-metric lazy under-reduction with generic headroom is never hidden behind
    a min() (#756 adversarial-review leak). PURE."""
    if metric == _METRIC_CELLS:
        return cells_red
    if metric == _METRIC_WIRES:
        return wires_red
    vals = [v for v in (cells_red, wires_red) if v is not None]
    return min(vals) if vals else None


def _clause_metrics(metric: str) -> List[str]:
    """The constituent single metric(s) a clause binds. A 'both' clause expands
    to BOTH cells and wires so each is classified independently (the conjunction
    is recombined by the caller); a single-metric clause stays itself."""
    if metric == _METRIC_BOTH:
        return [_METRIC_CELLS, _METRIC_WIRES]
    return [metric]


def decide_clauses(
        cells_red: Optional[float], wires_red: Optional[float],
        clauses: List[Tuple[float, str]], combinator: str,
        cells_red_generic: Optional[float] = None,
        wires_red_generic: Optional[float] = None,
        cells_red_ref_generic: Optional[float] = None,
        wires_red_ref_generic: Optional[float] = None,
        ) -> Tuple[str, str]:
    """Pure verdict for a LIST of per-metric (threshold, metric) clauses joined
    by `combinator` ∈ {'or','and'}, with the SAME unreachable-target escape and
    grown-design no-leak that single-clause decide() uses.

    DISJUNCTION ('or'): PASS as soon as ANY clause's bound MAPPED reduction is
    >= its own threshold. Only when EVERY clause is sub-threshold do we decide
    BLOCK vs NOT-APPLICABLE: BLOCK iff ANY sub-threshold clause is a REAL failure
    (its bound metric GREW — negative — OR its GENERIC reduction shows headroom);
    if every sub-threshold clause is proven near-minimal (generic also sub-
    threshold, mapped non-negative) the target is unreachable → NOT-APPLICABLE.

    CONJUNCTION ('and'): every clause must clear its own threshold; a single
    real failure blocks, an unmeasurable/unreachable clause (with no real
    failure) is NOT-APPLICABLE, else PASS.

    A clause whose bound MAPPED reduction is None (unmeasurable) is treated as
    NOT-satisfiable for OR (cannot prove it clears the bar) and NOT-APPLICABLE
    for AND — never a fabricated pass, never a false block.
    """
    # evaluate each clause against its own bar.
    sat: List[str] = []          # clauses that PASS their own threshold
    failures: List[str] = []     # real, blockable sub-threshold (headroom) clauses
    grown: List[str] = []        # metrics that GREW (negative mapped reduction)
    unreachable: List[str] = []  # proven-near-minimal sub-threshold clauses
    unmeasurable: List[str] = []
    generic_met: List[str] = []  # metrics SATISFIED on the GENERIC (scorer) count

    def _classify_single(thr: float, single: str) -> str:
        """Classify ONE metric against ONE threshold → a label string; appends
        the human note to the right bucket. Returns 'sat'/'grew'/'headroom'/
        'unreachable'/'unmeasurable'. A 'both' clause calls this for cells AND
        wires separately, so a per-metric grew/headroom is never masked."""
        red = _metric_red(single, cells_red, wires_red)
        gen = _metric_red(single, cells_red_generic, wires_red_generic)
        ref_gen = _metric_red(single, cells_red_ref_generic,
                              wires_red_ref_generic)
        if red is None:
            return "unmeasurable"
        if red >= thr:
            return "sat"
        if red < 0:
            # GROWN metric — the optimized count is LARGER than the original. A
            # genuine regression that DOMINATES every other verdict (even a
            # generic-satisfied sibling under OR): tracked in its OWN bucket so a
            # disjunctive PASS can never mask it (ORGANIC #769 / R6C12).
            grown.append(
                f"{single} reduction {red:.2f}% < {thr:g}% (design GREW — "
                f"never a near-minimal/unreachable target)")
            return "grew"
        # GENERIC-MEETS-TARGET (ORGANIC #769 / R6C12): the MAPPED reduction is
        # sub-threshold but NON-NEGATIVE, and the GENERIC (tech-independent)
        # reduction — the count the CVDP reference scorer actually measures
        # (synth -top; clean; stat, NO abc -g cmos2) — MEETS the bar. The area
        # target IS met on the metric the scorer enforces; the MAPPED shortfall
        # is only a shared/irreducible post-techmap combinational floor diluting
        # the percentage. SATISFIED, not a headroom BLOCK. No-leak: a lazy/
        # do-nothing submission has a sub-threshold GENERIC reduction so it never
        # reaches here.
        if _generic_meets_target(red, gen, thr):
            generic_met.append(
                f"{single} generic {gen:.2f}% >= {thr:g}% (mapped {red:.2f}% "
                f"diluted by post-techmap floor)")
            return "sat"
        # The unreachable-target escape fires ONLY when the target is PROVEN
        # unreachable (no reference golden beats the generic bar AND the
        # submission removed real area beyond the no-op floor); otherwise a
        # sub-threshold metric is a REAL under-reduction (ORGANIC #768 / R6C11).
        if not _escape_eligible(red, gen, thr, ref_gen):
            note = (f"{single} reduction {red:.2f}% < {thr:g}%")
            if _target_reachable_via_reference(ref_gen, thr):
                note += (f" (reference golden generic {ref_gen:.2f}% clears the "
                         f"bar — target REACHABLE)")
            elif gen is not None and gen <= _NOOP_GENERIC_FLOOR_PCT:
                note += (f" (generic {gen:.2f}% <= {_NOOP_GENERIC_FLOOR_PCT:g}% "
                         f"no-op floor — submission removed ~nothing)")
            elif gen is not None:
                note += f" (generic {gen:.2f}% has headroom)"
            failures.append(note)
            return "headroom"
        unreachable.append(
            f"{single} mapped {red:.2f}% / generic "
            f"{gen if gen is None else f'{gen:.2f}'}% both < {thr:g}%")
        return "unreachable"

    for thr, metric in clauses:
        # Expand a 'both' clause into its two metrics and classify each
        # independently; the clause is satisfied only if EVERY metric clears,
        # a real failure (grew/headroom) on ANY metric is a clause failure,
        # else unmeasurable/unreachable. A single-metric clause is just itself.
        labels = [_classify_single(thr, sm) for sm in _clause_metrics(metric)]
        if any(lb in ("grew", "headroom") for lb in labels):
            # a real, blockable under-reduction was already appended to failures.
            continue
        if all(lb == "sat" for lb in labels):
            sat.append(f"{metric} reduction meets {thr:g}%")
        elif any(lb == "unmeasurable" for lb in labels):
            unmeasurable.append(f"{metric} reduction unmeasurable")
        else:
            unreachable.append(f"{metric} near-minimal under {thr:g}%")

    if combinator == _COMBINATOR_OR:
        # A GROWN metric is a genuine regression that DOMINATES — it blocks even
        # when another clause is satisfied (no-leak: a disjunctive PASS must
        # never mask a metric that got WORSE) (ORGANIC #769 / R6C12).
        if grown:
            return ("BLOCK",
                    "a bound area metric GREW (worse than original) — blocks "
                    "regardless of any disjunctive clause: " + "; ".join(grown))
        # ANY satisfied clause ⇒ PASS (the spec's disjunction is met).
        if sat:
            reason = ("area reduction meets a disjunctive clause: "
                      + "; ".join(sat))
            if generic_met:
                reason += (" — generic meets the scorer-measured target: "
                           + "; ".join(generic_met))
            return ("PASS", reason)
        # none satisfied. A REAL failure (headroom) anywhere blocks —
        # the design could have hit at least one bar but did not.
        if failures:
            return ("BLOCK",
                    "no disjunctive area-reduction clause met and at least one "
                    "is a real under-reduction: " + "; ".join(failures))
        # every clause unmeasurable or proven near-minimal → no false block.
        bits = unreachable + unmeasurable
        return ("NOT_APPLICABLE",
                "no disjunctive clause met but none is a real failure "
                "(unreachable target / unmeasurable): " + "; ".join(bits))

    # CONJUNCTION ('and'): every clause must clear; a single real failure blocks.
    # A grown metric is a real failure that always blocks.
    if grown or failures:
        return ("BLOCK",
                "under-threshold area reduction (all clauses bind): "
                + "; ".join(grown + failures))
    if unmeasurable:
        return ("NOT_APPLICABLE",
                "a bound metric is unmeasurable: " + "; ".join(unmeasurable))
    if unreachable:
        return ("NOT_APPLICABLE",
                "unreachable-target escape (conjunctive clauses, near-minimal "
                "design): " + "; ".join(unreachable) + " (advisory, NOT a block)")
    reason = ("area reduction meets every conjunctive clause: "
              + "; ".join(sat))
    if generic_met:
        reason += (" — generic meets the scorer-measured target: "
                   + "; ".join(generic_met))
    return ("PASS", reason)


# ─── yosys stat parse + reduction arithmetic ─────────────────────────────────
# yosys `stat` has shipped TWO summary spellings over its life:
#   OLD (≤ ~0.36):  "   Number of cells:                400"
#                   "   Number of wires:                250"
#   NEW (0.40+):    "       98 cells"   /   "      152 wires"   (count FIRST,
#                   under a "Local Count, excluding submodules." header; the
#                   "<N> wire bits" / "<N> public wires" lines are NOT the
#                   wire/cell count and must NOT match).
# Parse BOTH so the gate works across yosys versions. The NEW form must avoid
# the decoy "wire bits" / "public wires" / "port bits" lines: a "<N> wires" /
# "<N> cells" token must be the WHOLE word at end-of-token (\b...\b, not part
# of "wire bits").
_CELLS_OLD_RE = re.compile(r"Number of cells:\s*(\d[\d,]*)")
_WIRES_OLD_RE = re.compile(r"Number of wires:\s*(\d[\d,]*)")
_CELLS_NEW_RE = re.compile(r"^\s*(\d[\d,]*)\s+cells\s*$", re.MULTILINE)
_WIRES_NEW_RE = re.compile(r"^\s*(\d[\d,]*)\s+wires\s*$", re.MULTILINE)

# Unique markers the recipe `log`s — ON ITS OWN LINE — between the GENERIC
# (pre-techmap/pre-abc, technology-independent) `stat` and the MAPPED (post-abc
# -g cmos2) `stat`, so the two stat blocks can be split off ONE transcript.
# Plain ASCII so it survives container stdout untouched. NOTE: yosys also ECHOES
# the whole command line (`-- Running command \`...; log MARK; stat; ...\``), so
# BOTH markers ALSO appear mid-line inside that one echoed command line — the
# split therefore matches each marker only when it is ALONE on a line (the real
# `log` output), never the mid-line command-echo copy.
_GENERIC_MARK = "PPA_AREA_GENERIC_STAT"
_MAPPED_MARK = "PPA_AREA_MAPPED_STAT"
_GENERIC_MARK_RE = re.compile(r"^[ \t]*" + re.escape(_GENERIC_MARK) + r"[ \t]*$",
                              re.MULTILINE)
_MAPPED_MARK_RE = re.compile(r"^[ \t]*" + re.escape(_MAPPED_MARK) + r"[ \t]*$",
                             re.MULTILINE)


def split_generic_mapped_stat(blob: str) -> Tuple[str, str]:
    """Split a transcript that contains a GENERIC stat block then a MAPPED stat
    block (separated by the recipe's `log` markers) into (generic, mapped) text.

    PURE — no I/O. The recipe is::

        ... opt; log PPA_AREA_GENERIC_STAT; stat; ...
        ... abc -g cmos2; log PPA_AREA_MAPPED_STAT; stat

    so the GENERIC stat lives between _GENERIC_MARK and _MAPPED_MARK, and the
    MAPPED stat lives after _MAPPED_MARK. Each marker is matched ONLY when it is
    ALONE on a line — yosys also echoes the full command line, in which both
    markers appear MID-line, and that command-echo copy must NOT be mistaken for
    the real `log` output. If a standalone marker is missing (older recipe / odd
    output) the WHOLE blob is returned for the missing section so the existing
    single-stat parse still finds the (mapped) numbers — degrade, never crash."""
    text = blob or ""
    gm = _GENERIC_MARK_RE.search(text)
    mm = _MAPPED_MARK_RE.search(text)
    if gm is not None and mm is not None and mm.start() > gm.end():
        generic = text[gm.end():mm.start()]
        mapped = text[mm.end():]
        return generic, mapped
    if mm is not None:
        # only the mapped marker present → everything after it is the mapped
        # stat; no generic section available.
        return "", text[mm.end():]
    # no standalone markers — treat the whole blob as the mapped stat
    # (back-compat with a marker-less transcript).
    return "", text


def parse_stat(stat_text: str) -> Dict[str, Optional[int]]:
    """Extract {'cells': int|None, 'wires': int|None} from yosys `stat` text.

    PURE — feed it the raw yosys transcript (or just the stat block). Handles
    BOTH the OLD ("Number of cells: N") and the NEW ("N cells") yosys summary
    spellings. A metric not present is None (the caller treats a missing metric
    as UNMEASURABLE → NOT-APPLICABLE, never a fabricated 0). The LAST occurrence
    wins (yosys may print a per-module stat then a top stat)."""
    out: Dict[str, Optional[int]] = {"cells": None, "wires": None}
    text = stat_text or ""
    for rx in (_CELLS_OLD_RE, _CELLS_NEW_RE):
        m = rx.findall(text)
        if m:
            out["cells"] = int(m[-1].replace(",", ""))
            break
    for rx in (_WIRES_OLD_RE, _WIRES_NEW_RE):
        m = rx.findall(text)
        if m:
            out["wires"] = int(m[-1].replace(",", ""))
            break
    return out


def compute_reduction_pct(orig: Optional[int], opt: Optional[int]
                          ) -> Optional[float]:
    """reduction% = 100 * (orig - opt) / orig, rounded to 4 dp.

    PURE. Returns None when it cannot be formed honestly:
      * either count is None (UNMEASURABLE), or
      * orig <= 0 (a 0-cell/0-wire original cannot anchor a percentage).
    A NEGATIVE result (optimized GREW) is returned verbatim (it is a real,
    measured anti-reduction → it will fail any positive threshold)."""
    if orig is None or opt is None:
        return None
    if orig <= 0:
        return None
    return round(100.0 * (orig - opt) / orig, 4)


# NO-REFERENCE safety net (ORGANIC #768 / R6C11). The airtight reachability
# anchor is the --reference golden; this floor only matters when NO reference is
# supplied. A submission whose GENERIC reduction is at/below this TIGHT epsilon
# removed essentially NOTHING — it is a do-nothing / literal-copy answer (e.g. an
# optimized file byte-identical to the original measures 0.0% generic), which can
# NEVER be "proven near-minimal"; it is a REAL under-reduction (BLOCK). The
# epsilon is deliberately TIGHT (just above measurement noise) so a submission
# that did real — even if insufficient — generic work is NOT floor-blocked when
# no reference is available (avoiding a no-reference false-BLOCK); such a
# small-but-real-effort sub-threshold submission is only caught as a real miss
# when a --reference golden proves the bar reachable. chip-AGNOSTIC: a pure
# percentage epsilon, no design literal.
_NOOP_GENERIC_FLOOR_PCT = 0.5


def _generic_headroom(metric_red: Optional[float], generic_red: Optional[float],
                      threshold_pct: float) -> bool:
    """True iff the GENERIC (tech-independent) reduction for a metric shows REAL
    headroom — i.e. it is measurable AND at/above the threshold, so a
    functionally-equivalent rewrite COULD still clear the bar on the
    tech-independent count. That is a LAZY optimization the gate must still
    BLOCK. False when the generic reduction is unavailable (no data → cannot
    prove headroom, default to BLOCK) or itself sub-threshold (proven
    near-minimal → eligible for the unreachable-target escape).

    PURE — no I/O. `metric_red` is unused here (kept for call-site symmetry);
    the headroom question is decided wholly on the GENERIC reduction."""
    if generic_red is None:
        return True   # no generic evidence → cannot prove unreachable → BLOCK
    return generic_red >= threshold_pct


def _generic_meets_target(metric_red: Optional[float],
                          generic_red: Optional[float],
                          threshold_pct: float) -> bool:
    """True iff the GENERIC (technology-INDEPENDENT) reduction for a metric MEETS
    the stated threshold while the MAPPED reduction (sub-threshold but NON-
    NEGATIVE) did not — i.e. the design DID reach the area target on the
    tech-independent count, and the only reason the MAPPED count fell short is
    that a SHARED, irreducible combinational floor (introduced by techmap /
    abc -g cmos2) dilutes the post-map percentage.

    THE BUG THIS FIXES (ORGANIC #769 / R6C12, cvdp_copilot_image_rotate_0015):
    the MAPPED count is NOT the ground-truth area metric. The CVDP reference
    scorer (harness synth.tcl) ends at ``synth -top; clean`` with NO techmap/
    ``abc -g cmos2`` and measures the GENERIC ``stat`` cell count; its .env
    carries ``CELLS=<orig_generic>`` + ``PERCENT_CELLS=<thr>``. So a metric whose
    GENERIC reduction clears the bar HAS MET the target the scorer enforces —
    even when the MAPPED reduction is below it because a fixed permutation/mux
    network or other shared combinational mass survives techmap unreduced.
    Treating that as 'generic headroom → BLOCK' is exactly inverted: the generic
    count that the gate would block on is the count the scorer PASSES.

    NO-LEAK: the MAPPED reduction must be NON-NEGATIVE — a design whose MAPPED
    count GREW is a real post-map regression and is NEVER excused here (it is
    classified 'grew' upstream and stays a BLOCK). And the GENERIC reduction must
    itself MEET the threshold — a lazy/shallow/do-nothing submission has a
    sub-threshold GENERIC reduction (the do-nothing copy has 0%), so it does NOT
    satisfy here and remains blockable. PURE — no I/O."""
    if metric_red is None or generic_red is None:
        return False
    return metric_red >= 0.0 and generic_red >= threshold_pct


def _target_reachable_via_reference(ref_generic_red: Optional[float],
                                    threshold_pct: float) -> bool:
    """True iff a REFERENCE (golden) optimized RTL proves the generic bar is
    ACHIEVABLE for this metric on this original — i.e. the reference's GENERIC
    (tech-independent) reduction is measurable AND at/above the threshold.

    This is the SUBMISSION-INDEPENDENT reachability anchor (ORGANIC #768 /
    R6C11). The bug it closes: the unreachable-target escape used the
    SUBMISSION's OWN generic reduction as the reachability proxy, so a shallow /
    no-op submission (whose own generic delta is small precisely because it
    skipped the structural win) was wrongly excused as "near-minimal". The
    reachability question must be answered by what is ACHIEVABLE (the reference),
    not by what THIS submission happened to do. When a reference clears the
    generic bar, the target is proven reachable → a sub-threshold submission is a
    REAL under-reduction (BLOCK).

    PURE — no I/O. Returns False when no reference reduction is available (no
    reference supplied / unmeasurable) → the escape is then governed by the
    no-op floor + the submission's own generic, fail-SAFE (never a fabricated
    'reachable')."""
    if ref_generic_red is None:
        return False
    return ref_generic_red >= threshold_pct


def _escape_eligible(metric_red: Optional[float], generic_red: Optional[float],
                     threshold_pct: float,
                     ref_generic_red: Optional[float] = None) -> bool:
    """True iff the unreachable-target escape may fire for ONE sub-threshold,
    NON-NEGATIVE metric — i.e. the target is PROVEN unreachable, not merely
    under-delivered by a lazy submission (ORGANIC #768 / R6C11).

    Reachability is decided SUBMISSION-INDEPENDENTLY, with the reference golden
    as the ground truth and a no-op floor as the no-reference safety net. The
    precedence is:
      1. REFERENCE supplied AND CLEARS the generic bar → target REACHABLE → a
         sub-threshold submission is a REAL miss → NOT eligible (BLOCK). This is
         the airtight anchor that catches the shallow/no-op leak (#R6C11).
      2. REFERENCE supplied AND itself SUB-BAR on the generic count → target
         PROVEN unreachable even by the golden → eligible (escape), regardless
         of how little THIS submission reduced (a 0% submission that equals an
         already-minimal golden is correctly excused — no false BLOCK).
      3. NO reference → fall back to the submission's own evidence:
           * own generic has headroom (>= threshold) → lazy miss → NOT eligible.
           * own generic at/below the no-op floor → removed ~nothing → NOT
             eligible (a do-nothing submission can never be 'near-minimal').
           * own generic between the floor and the bar → real effort, still
             sub-bar, no reference to disprove → eligible (advisory escape).

    PURE — no I/O. When it returns False for a sub-threshold non-negative metric,
    that metric is a REAL under-reduction (BLOCK)."""
    # ── (1)+(2) reference is the ground truth when present ─────────────────────
    if ref_generic_red is not None:
        # a golden that clears the bar proves reachability → real miss; a golden
        # that itself misses proves the target unreachable → escape.
        return not _target_reachable_via_reference(ref_generic_red,
                                                   threshold_pct)
    # ── (3) no reference: submission's own generic + no-op floor ───────────────
    if _generic_headroom(metric_red, generic_red, threshold_pct):
        return False   # submission generic has headroom → real lazy miss
    if generic_red is None or generic_red <= _NOOP_GENERIC_FLOOR_PCT:
        return False   # do-nothing / barely-touched → not near-minimal → real miss
    return True        # real generic effort, still sub-bar, no reference to
    #                    disprove → genuinely-unreachable (advisory escape)


def decide(cells_red: Optional[float], wires_red: Optional[float],
           threshold_pct: float, metric: str,
           cells_red_generic: Optional[float] = None,
           wires_red_generic: Optional[float] = None,
           cells_red_ref_generic: Optional[float] = None,
           wires_red_ref_generic: Optional[float] = None,
           ) -> Tuple[str, str]:
    """Pure verdict from the MAPPED reductions + bound metric + threshold, with
    an UNREACHABLE-TARGET escape driven by the GENERIC (tech-independent)
    reductions.

    Returns (verdict, reason). verdict ∈ {PASS, BLOCK, NOT_APPLICABLE}:
      * a BOUND metric's MAPPED reduction is None (unmeasurable)  → NOT_APPLICABLE
      * a BOUND metric's MAPPED reduction is NEGATIVE (the design
        GREW — optimized has MORE cells/wires than original); a
        grown design is never near-minimal/unreachable           → BLOCK
      * a BOUND metric's MAPPED reduction is sub-threshold but
        NON-NEGATIVE AND its GENERIC reduction is ALSO
        sub-threshold (proven near-minimal, unreachable target —
        no equivalent rewrite incl. golden can clear the
        tech-independent bar)                                     → NOT_APPLICABLE
      * a BOUND metric's MAPPED reduction is < threshold while its
        GENERIC reduction shows headroom (>= threshold, or no
        generic evidence) → the design COULD have reached it      → BLOCK
      * every bound metric's MAPPED reduction is >= threshold     → PASS
    `cells`/`wires` bind one; `both` binds both.

    `cells_red_generic` / `wires_red_generic` are the GENERIC-cell-count
    reductions (pre-abc / pre-techmap). When BOTH are None (legacy call with no
    generic data) the escape never fires and the behaviour is the prior
    all-or-nothing MAPPED gate — fail-SAFE, no surprise downgrade.
    """
    bind_cells = metric in (_METRIC_CELLS, _METRIC_BOTH)
    bind_wires = metric in (_METRIC_WIRES, _METRIC_BOTH)

    # unmeasurable bound metric → NOT-APPLICABLE (never a false block).
    if bind_cells and cells_red is None:
        return ("NOT_APPLICABLE",
                "cells reduction is unmeasurable (no cell count from yosys "
                "stat on one side); cannot assert the cells threshold")
    if bind_wires and wires_red is None:
        return ("NOT_APPLICABLE",
                "wires reduction is unmeasurable (no wire count from yosys "
                "stat on one side); cannot assert the wires threshold")

    # classify each bound, sub-threshold metric as either a REAL BLOCK (generic
    # headroom exists → the design could have reduced more, OR the design GREW —
    # a negative reduction is never a near-minimal/unreachable design) or an
    # UNREACHABLE target (generic also sub-threshold AND the mapped count did NOT
    # grow → proven near-minimal → escape).
    #
    # GROWN-DESIGN NO-LEAK (#739 remediation): a metric whose MAPPED reduction is
    # NEGATIVE means the optimized count is LARGER than the original — the
    # submission made that metric WORSE. That is never a "near-minimal,
    # target-unreachable" design, so the unreachable-target escape must NOT fire
    # for it even when the generic reduction is small/sub-threshold; keep it a
    # BLOCK. The escape fires ONLY for a genuinely-near-minimal metric: mapped
    # sub-threshold but NON-NEGATIVE, and generic also sub-threshold.
    #
    # GENERIC-MEETS-TARGET (ORGANIC #769 / R6C12): a metric whose MAPPED
    # reduction is sub-threshold but NON-NEGATIVE while its GENERIC (tech-
    # independent) reduction MEETS the bar HAS met the area target on the count
    # the CVDP reference scorer measures (synth -top; clean; stat — NO abc -g
    # cmos2). The mapped shortfall is only a shared, irreducible post-techmap
    # combinational floor diluting the percentage. It is SATISFIED (neither a
    # failure nor an unreachable escape). No-leak: a lazy/do-nothing submission
    # has a sub-threshold GENERIC reduction so this never fires for it.
    failures: List[str] = []         # real, blockable under-reductions
    unreachable: List[str] = []      # proven-near-minimal sub-threshold metrics
    generic_met: List[str] = []      # generic-satisfied (mapped sub-thr) metrics
    if bind_cells and cells_red < threshold_pct:
        if cells_red < 0:
            failures.append(
                f"cells reduction {cells_red:.2f}% < {threshold_pct:g}% "
                f"(design GREW — optimized has MORE cells than original; "
                f"never a near-minimal/unreachable target)")
        elif _generic_meets_target(cells_red, cells_red_generic, threshold_pct):
            # generic count meets the scorer-measured target → satisfied
            generic_met.append(
                f"cells generic {cells_red_generic:.2f}% >= {threshold_pct:g}% "
                f"(mapped {cells_red:.2f}% diluted by post-techmap floor)")
        elif not _escape_eligible(cells_red, cells_red_generic, threshold_pct,
                                  cells_red_ref_generic):
            note = f"cells reduction {cells_red:.2f}% < {threshold_pct:g}%"
            if _target_reachable_via_reference(cells_red_ref_generic,
                                               threshold_pct):
                note += (f" (reference golden generic "
                         f"{cells_red_ref_generic:.2f}% clears the bar — target "
                         f"REACHABLE)")
            elif (cells_red_generic is not None
                  and cells_red_generic <= _NOOP_GENERIC_FLOOR_PCT):
                note += (f" (generic {cells_red_generic:.2f}% <= "
                         f"{_NOOP_GENERIC_FLOOR_PCT:g}% no-op floor — submission "
                         f"removed ~nothing)")
            elif cells_red_generic is not None:
                note += f" (generic {cells_red_generic:.2f}% has headroom)"
            failures.append(note)
        else:
            unreachable.append(
                f"cells mapped {cells_red:.2f}% / generic "
                f"{cells_red_generic:.2f}% both < {threshold_pct:g}%")
    if bind_wires and wires_red < threshold_pct:
        if wires_red < 0:
            failures.append(
                f"wires reduction {wires_red:.2f}% < {threshold_pct:g}% "
                f"(design GREW — optimized has MORE wires than original; "
                f"never a near-minimal/unreachable target)")
        elif _generic_meets_target(wires_red, wires_red_generic, threshold_pct):
            # generic count meets the scorer-measured target → satisfied
            generic_met.append(
                f"wires generic {wires_red_generic:.2f}% >= {threshold_pct:g}% "
                f"(mapped {wires_red:.2f}% diluted by post-techmap floor)")
        elif not _escape_eligible(wires_red, wires_red_generic, threshold_pct,
                                  wires_red_ref_generic):
            note = f"wires reduction {wires_red:.2f}% < {threshold_pct:g}%"
            if _target_reachable_via_reference(wires_red_ref_generic,
                                               threshold_pct):
                note += (f" (reference golden generic "
                         f"{wires_red_ref_generic:.2f}% clears the bar — target "
                         f"REACHABLE)")
            elif (wires_red_generic is not None
                  and wires_red_generic <= _NOOP_GENERIC_FLOOR_PCT):
                note += (f" (generic {wires_red_generic:.2f}% <= "
                         f"{_NOOP_GENERIC_FLOOR_PCT:g}% no-op floor — submission "
                         f"removed ~nothing)")
            elif wires_red_generic is not None:
                note += f" (generic {wires_red_generic:.2f}% has headroom)"
            failures.append(note)
        else:
            unreachable.append(
                f"wires mapped {wires_red:.2f}% / generic "
                f"{wires_red_generic:.2f}% both < {threshold_pct:g}%")
    # PRE-EXISTING / OUT-OF-SCOPE (separate LOW): metric='both' with one
    # unmeasurable partner (mapped reduction None) short-circuits to
    # NOT_APPLICABLE above, masking the other (measured) metric's verdict. That
    # masking pre-dates this fix and is not addressed here — noted only.

    # a metric with REAL generic headroom that still missed the bar BLOCKs —
    # this dominates (no-leak: a lazily-optimized design is never downgraded).
    if failures:
        return ("BLOCK",
                "under-threshold area reduction: " + "; ".join(failures))

    # no real-headroom failure, but some bound metric was sub-threshold AND
    # proven near-minimal on the generic count → unreachable target, advisory.
    if unreachable:
        return ("NOT_APPLICABLE",
                "unreachable-target escape: the stated reduction is unachievable "
                "by ANY functionally-equivalent rewrite for this near-minimal "
                "design — " + "; ".join(unreachable)
                + " (advisory, NOT a block)")

    parts: List[str] = []
    if bind_cells:
        parts.append(f"cells {cells_red:.2f}%")
    if bind_wires:
        parts.append(f"wires {wires_red:.2f}%")
    reason = (f"area reduction meets the {threshold_pct:g}% threshold ("
              + ", ".join(parts) + ")")
    if generic_met:
        # at least one metric cleared the bar on the GENERIC (scorer-measured)
        # count while its MAPPED reduction was diluted by a post-techmap floor.
        reason += (" — generic meets the scorer-measured target: "
                   + "; ".join(generic_met))
    return ("PASS", reason)


# ─── yosys-in-container synth + stat ─────────────────────────────────────────
# Path inside the iic-osic-tools / vibeic-eda container where the EDA tools live.
_TOOLS_IN_CONTAINER = "/foss/tools"

# The SAME lowering recipe the phase-2 synth path uses (synth -flatten; techmap;
# opt; dffunmap; abc -g cmos2) so the cell/wire counts are directly comparable
# between the original and the optimized RTL. The recipe emits the `stat` TWICE
# around an `echo` marker: once on the GENERIC (technology-INDEPENDENT, coarse
# $add/$mul/$dff) netlist right after `synth -flatten; opt` — BEFORE techmap/abc
# — and once on the technology-MAPPED netlist after `abc -g cmos2`, so a
# tech-independent and a tech-mapped reduction are both available off one run
# (the GENERIC one anchors the unreachable-target escape).
_SYNTH_TAIL = ("hierarchy -check -top {top}; proc; flatten; "
               "synth -top {top} -flatten; opt; "
               "log " + _GENERIC_MARK + "; stat; "
               "techmap; opt; dffunmap; abc -g cmos2; "
               "log " + _MAPPED_MARK + "; stat")


def _run(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return 124, out or "", "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _container_running(container: str) -> bool:
    """True iff the named docker container is up (so a `docker exec` will land).
    NOT-APPLICABLE-fast — a single short inspect, no synth attempted if down."""
    rc, out, _ = _run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container],
        timeout=10)
    return rc == 0 and out.strip() == "true"


def _container_mounts(container: str) -> List[Tuple[str, str]]:
    """[(host_src, container_dst), ...] longest-source-first. Mirrors the
    phase-2 runner helper so host RTL paths map to container-visible paths."""
    out: List[Tuple[str, str]] = []
    rc, txt, _ = _run(
        ["docker", "inspect", container, "--format",
         "{{range .Mounts}}{{.Source}}|{{.Destination}}\n{{end}}"], timeout=10)
    if rc == 0:
        for line in txt.splitlines():
            line = line.strip()
            if "|" not in line:
                continue
            src, dst = line.split("|", 1)
            if src and dst:
                out.append((src.rstrip("/"), dst.rstrip("/")))
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


def _to_container_path(host_path: str, mounts: List[Tuple[str, str]]) -> str:
    p = str(host_path)
    for src, dst in mounts:
        if p == src:
            return dst
        if p.startswith(src + "/"):
            return dst + p[len(src):]
    return p


def _docker_exec_raw(container: str, cmd: str, timeout: int = 600
                     ) -> Tuple[int, str, str]:
    """Simple bounded wall-clock docker exec — for short probes. Long tool runs
    use `_docker_exec(..., marker=...)` → the progress-stall watchdog.

    Carries its OWN container-side deadline: a host `subprocess.run` timeout
    kills only the `docker exec` CLIENT and ORPHANS the tool in the container
    (see `_docker_watchdog.wrap_with_container_timeout`). Chip-AGNOSTIC."""
    import _docker_watchdog as _dw
    full = ["docker", "exec", container, "bash", "-lc",
            _dw.wrap_with_container_timeout(cmd, timeout)]
    try:
        cp = subprocess.run(full, capture_output=True, text=True,
                            timeout=timeout)
        return cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        partial = e.stdout
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return 124, partial or "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _docker_exec(container: str, cmd: str, timeout: int = 600, *,
                 marker=None, log_path=None) -> Tuple[int, str, str]:
    """marker=None → `_docker_exec_raw` (short probes). marker set → the shared
    progress-stall watchdog (`_docker_watchdog.run_docker_supervised`) so a long
    synth run is killed ONLY on NO forward progress, never on a fixed estimate.
    `marker` is a token already in the tool's argv. chip/tool-AGNOSTIC."""
    if marker is None:
        return _docker_exec_raw(container, cmd, timeout)
    import _docker_watchdog as _dw
    return _dw.run_docker_supervised(
        container, cmd, marker, docker_exec_raw=_docker_exec_raw,
        log_path=log_path)


def synth_stat_in_container(rtl_path: Path, top: str, container: str
                            ) -> Tuple[Optional[str], str]:
    """Synthesise `rtl_path` (module `top`) inside `container` and return
    (stat_text, err). On any failure stat_text is None and err is non-empty.

    The RTL is `docker cp`'d into a fresh /tmp staging dir inside the container
    (so we never depend on a particular bind-mount layout), synthesised with the
    canonical recipe, and the full transcript (which contains the `stat` block)
    is returned. NEVER fabricates a count."""
    stage = f"/tmp/ppa_area_{abs(hash((str(rtl_path), top)))}"
    base = rtl_path.name
    # fresh staging dir + copy the RTL in
    rc, _o, e = _docker_exec(container, f"rm -rf {stage} && mkdir -p {stage}",
                             timeout=30)
    if rc != 0:
        return None, f"could not create container staging dir: {e[-200:]}"
    rc, _o, e = _run(["docker", "cp", str(rtl_path),
                      f"{container}:{stage}/{base}"], timeout=60)
    if rc != 0:
        return None, f"docker cp {base} → container failed: {e[-200:]}"
    yosys_path = (f"export PATH={_TOOLS_IN_CONTAINER}/yosys/bin:"
                  f"{_TOOLS_IN_CONTAINER}/bin:$PATH")
    recipe = _SYNTH_TAIL.format(top=top)
    cmd = (f"cd {stage} && {yosys_path} && "
           f"yosys -p 'read_verilog -sv {base}; {recipe}' 2>&1")
    rc, out, err = _docker_exec(container, cmd, marker=base)
    # best-effort cleanup
    _docker_exec(container, f"rm -rf {stage}", timeout=20)
    blob = (out or "") + "\n" + (err or "")
    if rc != 0 or "ERROR" in (out or ""):
        return None, ("yosys synth failed: "
                      + "; ".join(blob.strip().splitlines()[-5:]))
    return blob, ""


# ─── orchestration ───────────────────────────────────────────────────────────
def run_ppa_area_threshold(
    original: Path, optimized: Path, top: str,
    prompt_text: Optional[str], threshold_override: Optional[float],
    metric_override: Optional[str], container: str,
    reference: Optional[Path] = None,
) -> Tuple[int, Dict]:
    """Run the gate; return (rc, report). rc is the program exit code.

    rc 0 = PASS / NOT-APPLICABLE / SKIP, rc 1 = BLOCK (under threshold),
    rc 2 = setup error.
    """
    report: Dict = {
        "program": "ppa_area_threshold_check",
        # PPA-009 taxonomy stamp. Written FIRST, before any early return, so
        # that every exit path — NOT_APPLICABLE, BLOCK, PASS, tool-absent —
        # carries it. A label that only appears on the happy path is a label a
        # promoter never sees.
        "metric_class": _METRIC_CLASS,
        "eligible_for_physical_ppa": _ELIGIBLE_FOR_PHYSICAL_PPA,
        "metrics_reported": sorted(_PROXY_METRICS),
        "physical_area_note": _PROXY_NOTE,
        "original": str(original),
        "optimized": str(optimized),
        "top": top,
        "container": container,
        "methodology": ("yosys stat on ORIGINAL + OPTIMIZED with the SAME synth "
                        "recipe, taken TWICE (GENERIC pre-techmap/abc + MAPPED "
                        "post-abc -g cmos2); reduction%% = 100*(orig-opt)/orig "
                        "for cells and wires; BLOCK iff a prompt-bound metric's "
                        "MAPPED reduction is below threshold AND its GENERIC "
                        "reduction shows headroom; a sub-threshold MAPPED whose "
                        "GENERIC is ALSO sub-threshold is an unreachable target "
                        "→ NOT-APPLICABLE/advisory, not a block"),
    }

    # ── resolve the threshold clause(s) + combinator ──────────────────────────
    # explicit --threshold-pct wins; else parse from the prompt. An unparseable
    # threshold is NON-BLOCKING NOT-APPLICABLE (§4.05) — never a false block.
    # The gate now carries a LIST of (pct, metric) clauses + a combinator
    # ('or'/'and') so a per-metric DISJUNCTIVE spec ("12% for wires OR 8% for
    # cells") is honoured instead of being collapsed to a single (12,'both')
    # conjunction (ORGANIC #756).
    if threshold_override is not None:
        threshold = threshold_override
        metric = metric_override or _METRIC_BOTH
        clauses = [(threshold, metric)]
        combinator = _COMBINATOR_AND
        report["threshold_source"] = "explicit"
    else:
        if not prompt_text:
            report["verdict"] = "NOT_APPLICABLE"
            report["reason"] = ("no --threshold-pct and no --prompt; cannot "
                                "determine the area-reduction target")
            return 0, report
        try:
            clauses, combinator = parse_threshold_clauses_from_prompt(
                prompt_text)
        except ThresholdParseError as ex:
            report["verdict"] = "NOT_APPLICABLE"
            report["reason"] = (f"unparseable threshold — {ex}; not blocking "
                                f"(the prompt has no area-reduction target)")
            return 0, report
        # a --metric override on top of a parsed threshold pins EVERY clause to
        # that metric (caller explicitly overriding the parsed bind).
        if metric_override:
            clauses = [(pct, metric_override) for pct, _m in clauses]
        # back-compat scalar fields: the first clause's threshold + (when all
        # clauses share one metric) its metric, else 'both'.
        threshold = clauses[0][0]
        metric = (clauses[0][1] if len({m for _p, m in clauses}) == 1
                  else _METRIC_BOTH)
        report["threshold_source"] = "prompt"
    report["threshold_pct"] = threshold
    report["metric"] = metric
    report["clauses"] = [{"threshold_pct": p, "metric": m} for p, m in clauses]
    report["combinator"] = combinator

    # ── yosys / container availability — refuse-don't-fake (§4.05) ────────────
    if not _docker_available():
        report["verdict"] = "NOT_APPLICABLE"
        report["tool_available"] = False
        report["reason"] = ("docker absent — cannot synthesise to MEASURE the "
                            "area; NOT-APPLICABLE (NOT a fabricated reduction "
                            "or a false block)")
        return 0, report
    if not _container_running(container):
        report["verdict"] = "NOT_APPLICABLE"
        report["tool_available"] = False
        report["reason"] = (f"container {container!r} is not running — cannot "
                            f"synthesise; NOT-APPLICABLE (no false block)")
        return 0, report
    report["tool_available"] = True

    # ── synth + stat BOTH sides with the SAME recipe ──────────────────────────
    orig_blob, orig_err = synth_stat_in_container(original, top, container)
    if orig_blob is None:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = (f"ORIGINAL synth/stat unavailable: {orig_err}; "
                            f"NOT-APPLICABLE (cannot measure → no false block)")
        return 0, report
    opt_blob, opt_err = synth_stat_in_container(optimized, top, container)
    if opt_blob is None:
        report["verdict"] = "NOT_APPLICABLE"
        report["reason"] = (f"OPTIMIZED synth/stat unavailable: {opt_err}; "
                            f"NOT-APPLICABLE (cannot measure → no false block)")
        return 0, report

    # split each transcript into its GENERIC (tech-independent, pre-techmap/abc)
    # stat and its MAPPED (post-abc -g cmos2) stat. The mapped stat is the
    # measured target; the generic stat anchors the unreachable-target escape.
    orig_generic_txt, orig_mapped_txt = split_generic_mapped_stat(orig_blob)
    opt_generic_txt, opt_mapped_txt = split_generic_mapped_stat(opt_blob)

    orig_stat = parse_stat(orig_mapped_txt)
    opt_stat = parse_stat(opt_mapped_txt)
    orig_stat_generic = parse_stat(orig_generic_txt)
    opt_stat_generic = parse_stat(opt_generic_txt)
    report["original_stat"] = orig_stat
    report["optimized_stat"] = opt_stat
    report["original_stat_generic"] = orig_stat_generic
    report["optimized_stat_generic"] = opt_stat_generic

    cells_red = compute_reduction_pct(orig_stat["cells"], opt_stat["cells"])
    wires_red = compute_reduction_pct(orig_stat["wires"], opt_stat["wires"])
    cells_red_generic = compute_reduction_pct(
        orig_stat_generic["cells"], opt_stat_generic["cells"])
    wires_red_generic = compute_reduction_pct(
        orig_stat_generic["wires"], opt_stat_generic["wires"])
    report["cells_reduction_pct"] = cells_red
    report["wires_reduction_pct"] = wires_red
    report["cells_reduction_pct_generic"] = cells_red_generic
    report["wires_reduction_pct_generic"] = wires_red_generic

    # ── REFERENCE (golden) reachability anchor (ORGANIC #768 / R6C11) ─────────
    # The unreachable-target escape must be anchored to what is ACHIEVABLE, NOT
    # to the SUBMISSION's own generic delta (a shallow/no-op submission has a
    # tiny generic delta precisely because it skipped the structural win). When
    # a reference golden is supplied, synth it with the SAME recipe and compute
    # its GENERIC reduction vs the original: if the golden clears the generic
    # bar the target is PROVEN reachable, so a sub-threshold submission is a REAL
    # under-reduction (BLOCK), never excused. No reference → the escape falls
    # back to the submission's own generic PLUS a no-op floor (a do-nothing
    # submission can never be excused), fail-SAFE.
    cells_red_ref_generic: Optional[float] = None
    wires_red_ref_generic: Optional[float] = None
    if reference is not None:
        ref_blob, ref_err = synth_stat_in_container(reference, top, container)
        if ref_blob is None:
            report["reference_stat_note"] = (
                f"reference synth/stat unavailable: {ref_err}; reachability "
                f"anchored on submission generic + no-op floor only")
        else:
            ref_generic_txt, _ref_mapped_txt = split_generic_mapped_stat(
                ref_blob)
            ref_stat_generic = parse_stat(ref_generic_txt)
            report["reference_stat_generic"] = ref_stat_generic
            cells_red_ref_generic = compute_reduction_pct(
                orig_stat_generic["cells"], ref_stat_generic["cells"])
            wires_red_ref_generic = compute_reduction_pct(
                orig_stat_generic["wires"], ref_stat_generic["wires"])
            report["cells_reduction_pct_ref_generic"] = cells_red_ref_generic
            report["wires_reduction_pct_ref_generic"] = wires_red_ref_generic

    verdict, reason = decide_clauses(
        cells_red, wires_red, clauses, combinator,
        cells_red_generic=cells_red_generic,
        wires_red_generic=wires_red_generic,
        cells_red_ref_generic=cells_red_ref_generic,
        wires_red_ref_generic=wires_red_ref_generic)
    report["verdict"] = verdict
    report["reason"] = reason
    if verdict == "BLOCK":
        return 1, report
    return 0, report


def as_metric_records(report: Dict) -> List[Dict]:
    """This gate's numbers as canonical `vibeic.ppa.metric.v1` records.

    THIS IS THE WIRING THAT MAKES THE LABEL LOAD-BEARING (PPA-009). A consumer
    that wants these numbers in canonical form has exactly one way to get them,
    and it goes through `_ppa.area.proxy_record`, which RAISES on a physical
    metric name. So a future extractor cannot accidentally hand a cell count to
    a physical-area comparison: the record it would need does not exist and
    cannot be built from here.

    Numbers that were not measured come back as NOT_MEASURED WITH A REASON, not
    as an omitted row and never as a 0 — "I could not synthesise" and "the
    optimised netlist has zero cells" must not produce the same record.
    """
    scope = {
        "stage": "synth_mapped",
        "tool": "yosys",
        "top": report.get("top"),
        "container": report.get("container"),
    }
    source = {
        "path": str(report.get("optimized") or ""),
        "baseline_path": str(report.get("original") or ""),
        "tool": "yosys",
        "parser": "ppa_area_threshold_check.py",
    }
    out: List[Dict] = []
    for metric, key in (
            ("area.proxy.cell_count_reduction_pct", "cells_reduction_pct"),
            ("area.proxy.wire_count_reduction_pct", "wires_reduction_pct")):
        value = report.get(key)
        if value is None:
            out.append(_ppa_area.proxy_record(
                metric, _ppa_area.NOT_MEASURED, scope=scope,
                reason=(f"{key} is absent from the report "
                        f"(verdict={report.get('verdict')!r}: "
                        f"{report.get('reason', 'no reason recorded')})")))
        else:
            out.append(_ppa_area.proxy_record(
                metric, _ppa_area.DERIVED, value=float(value), scope=scope,
                source=source,
                formula="100*(original-optimized)/original over the yosys "
                        "technology-mapped counts"))
    for metric, key in (("area.proxy.cell_count", "cells"),
                        ("area.proxy.wire_count", "wires")):
        value = (report.get("optimized_stat") or {}).get(key)
        if value is None:
            out.append(_ppa_area.proxy_record(
                metric, _ppa_area.NOT_MEASURED, scope=scope,
                reason=(f"the optimized technology-mapped stat has no {key!r} "
                        f"row (verdict={report.get('verdict')!r})")))
        else:
            out.append(_ppa_area.proxy_record(
                metric, _ppa_area.MEASURED, value=value, scope=scope,
                source=source))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=("DETERMINISTIC PPA area-reduction-threshold gate (#729): "
                     "synth ORIGINAL vs OPTIMIZED with yosys, compute cells%% + "
                     "wires%% reduction, BLOCK if a prompt-bound metric is below "
                     "the prompt-stated threshold."))
    ap.add_argument("--original", required=True,
                    help="the ORIGINAL (un-optimized) RTL file")
    ap.add_argument("--optimized", required=True,
                    help="the OPTIMIZED RTL file (same top module)")
    ap.add_argument("--reference", default=None,
                    help="optional REFERENCE / golden optimized RTL (same top). "
                         "Anchors the unreachable-target escape on what is "
                         "ACHIEVABLE: if the reference clears the generic bar the "
                         "target is REACHABLE, so a sub-threshold submission is a "
                         "real BLOCK (not excused as near-minimal).")
    ap.add_argument("--top", required=True,
                    help="the top module name (same in both files)")
    ap.add_argument("--prompt", default=None,
                    help="path to the prompt/spec text; the threshold + bound "
                         "metric are parsed from it")
    ap.add_argument("--threshold-pct", type=float, default=None,
                    help="explicit reduction threshold percent (overrides the "
                         "prompt-parsed one)")
    ap.add_argument("--metric", default=None, choices=_VALID_METRICS,
                    help="which metric the threshold binds (default: parsed "
                         "from the prompt, else 'both')")
    ap.add_argument("--container", default="vibeic-eda",
                    help="docker container with yosys (default vibeic-eda)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    original = Path(args.original)
    optimized = Path(args.optimized)
    reference = Path(args.reference) if args.reference else None
    if not original.is_file():
        print(f"{cli_exit.MARK_CANNOT_CHECK} --original not found: {original}. Nothing was opened, so no area was compared. rc=2 — this is NOT a pass.", file=sys.stderr)
        return cli_exit.RC_UNDETERMINED
    if not optimized.is_file():
        print(f"{cli_exit.MARK_CANNOT_CHECK} --optimized not found: {optimized}. Nothing was opened, so no area was compared. rc=2 — this is NOT a pass.", file=sys.stderr)
        return cli_exit.RC_UNDETERMINED
    if reference is not None and not reference.is_file():
        print(f"{cli_exit.MARK_CANNOT_CHECK} --reference not found: {reference}. Nothing was opened, so no area was compared. rc=2 — this is NOT a pass.", file=sys.stderr)
        return cli_exit.RC_UNDETERMINED
    if args.threshold_pct is None and args.prompt is None:
        return cli_exit.refuse(ap.prog, "provide --threshold-pct or --prompt; without one there is no declared threshold to adjudicate against")

    prompt_text = None
    if args.prompt is not None:
        pp = Path(args.prompt)
        if not pp.is_file():
            print(f"{cli_exit.MARK_CANNOT_CHECK} --prompt not found: {pp}. The threshold could not be read, so nothing was adjudicated. rc=2.", file=sys.stderr)
            return cli_exit.RC_UNDETERMINED
        prompt_text = pp.read_text(errors="replace")

    rc, report = run_ppa_area_threshold(
        original=original, optimized=optimized, top=args.top,
        prompt_text=prompt_text, threshold_override=args.threshold_pct,
        metric_override=args.metric, container=args.container,
        reference=reference)

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))

    verdict = report.get("verdict")
    if verdict == "NOT_APPLICABLE":
        print(f"NOT-APPLICABLE: {report['reason']}")
    elif verdict == "BLOCK":
        print(f"PPA-AREA-BLOCK: {report['reason']} "
              f"(mapped cells={report.get('cells_reduction_pct')}%, "
              f"wires={report.get('wires_reduction_pct')}%; "
              f"generic cells={report.get('cells_reduction_pct_generic')}%, "
              f"wires={report.get('wires_reduction_pct_generic')}%)")
    elif verdict == "PASS":
        print(f"ppa-area-threshold ok: {report['reason']}")
    else:
        print(f"NOT-APPLICABLE: {report.get('reason', verdict)}")
    # ORGANIC #744 (R3-3 author-UX hint) — measurement-provenance disclaimer.
    # The area verdict is computed from the IN-CONTAINER synthesis (pinned yosys
    # version). A LOCAL yosys of a different version can give an OPPOSITE-SIGN
    # area delta for the SAME RTL pair, so a local re-measure is not a valid
    # cross-check of this verdict.
    # PPA-009: the class travels with the verdict on stdout too, because the
    # thing that gets copied into a summary is the printed line, not the JSON.
    print(f"  metric_class={_METRIC_CLASS} "
          f"eligible_for_physical_ppa={str(_ELIGIBLE_FOR_PHYSICAL_PPA).lower()} "
          f"— {_PROXY_NOTE}")
    if verdict in ("BLOCK", "PASS"):
        print("  hint (#744): this area verdict is valid ONLY from the "
              "in-container measurement (pinned yosys); a local yosys of a "
              "different version can report an opposite-sign delta for the same "
              "RTL pair — do not contradict this verdict with a local re-measure.")
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - the guard, not the path
        # PPA_INTERFACES §1: 3 is INTERNAL ERROR. Letting a traceback propagate
        # exits 1, which is reserved for a FINDING about the design -- so a
        # crash would reach the roll-up as a verdict nothing reached.
        #
        # NEWLY LOAD-BEARING. While this gate took an exact path a crash was a
        # local accident; with `--corpus` it sweeps a whole campaign, so one
        # badly shaped document decides the entire row. The same guard
        # ppa_contract_check has carried from the start.
        print(f"{cli_exit.MARK_REFUSE} ppa_area_threshold_check: internal error "
              f"{type(exc).__name__}: {exc}. Nothing was decided. rc=3 "
              f"(NOT a finding about any design).", file=sys.stderr)
        sys.exit(cli_exit.RC_BAD_INVOCATION)
