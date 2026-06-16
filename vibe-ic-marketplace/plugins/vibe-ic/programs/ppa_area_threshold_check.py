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
     synth recipe inside the iic-eda container. The recipe emits the `stat`
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
reduction is ALSO sub-threshold, the target is proven unreachable for this
design → NOT-APPLICABLE / advisory, not a BLOCK. CRUCIAL no-leak: a
lazily-optimized design whose GENERIC reduction is AT/ABOVE the threshold (so it
COULD still reach the target) is STILL BLOCKED — only a proven-near-minimal one
is downgraded. SECOND no-leak (#739 remediation): a design whose MAPPED
reduction for a bound metric is NEGATIVE (optimized is LARGER than original —
the submission made the count WORSE) is never near-minimal, so the escape does
NOT fire for it and it is STILL BLOCKED regardless of the generic count.

The %-computation + threshold-compare is factored into PURE functions
(``compute_reduction_pct`` / ``parse_threshold_from_prompt`` / ``decide``) so it
is unit-tested against CANNED yosys ``stat`` text WITHOUT needing the container.

§4.05 NO-LEAK (this is a BLOCKING gate)
---------------------------------------
This gate only ever BLOCKs on a REAL measured under-threshold reduction. EVERY
other outcome is a non-blocking exit-0 NOT-APPLICABLE / SKIP, never a false
block:
  * yosys / the iic-eda container is unavailable     → NOT-APPLICABLE rc 0.
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
        [--container iic-eda] [--json OUT]

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

    # BACKWARD fallback: nearest metric word BEFORE the '%' (within 40 chars,
    # not crossing a previous '%').
    bwd_start = max(0, pct_start - 40)
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
    failures: List[str] = []     # real, blockable sub-threshold clauses
    unreachable: List[str] = []  # proven-near-minimal sub-threshold clauses
    unmeasurable: List[str] = []

    def _classify_single(thr: float, single: str) -> str:
        """Classify ONE metric against ONE threshold → a label string; appends
        the human note to the right bucket. Returns 'sat'/'grew'/'headroom'/
        'unreachable'/'unmeasurable'. A 'both' clause calls this for cells AND
        wires separately, so a per-metric grew/headroom is never masked."""
        red = _metric_red(single, cells_red, wires_red)
        gen = _metric_red(single, cells_red_generic, wires_red_generic)
        if red is None:
            return "unmeasurable"
        if red >= thr:
            return "sat"
        if red < 0:
            failures.append(
                f"{single} reduction {red:.2f}% < {thr:g}% (design GREW — "
                f"never a near-minimal/unreachable target)")
            return "grew"
        if _generic_headroom(red, gen, thr):
            failures.append(
                f"{single} reduction {red:.2f}% < {thr:g}%"
                + (f" (generic {gen:.2f}% has headroom)"
                   if gen is not None else ""))
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
        # ANY satisfied clause ⇒ PASS (the spec's disjunction is met).
        if sat:
            return ("PASS",
                    "area reduction meets a disjunctive clause: "
                    + "; ".join(sat))
        # none satisfied. A REAL failure (headroom / grew) anywhere blocks —
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
    if failures:
        return ("BLOCK",
                "under-threshold area reduction (all clauses bind): "
                + "; ".join(failures))
    if unmeasurable:
        return ("NOT_APPLICABLE",
                "a bound metric is unmeasurable: " + "; ".join(unmeasurable))
    if unreachable:
        return ("NOT_APPLICABLE",
                "unreachable-target escape (conjunctive clauses, near-minimal "
                "design): " + "; ".join(unreachable) + " (advisory, NOT a block)")
    return ("PASS",
            "area reduction meets every conjunctive clause: "
            + "; ".join(sat))


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


def decide(cells_red: Optional[float], wires_red: Optional[float],
           threshold_pct: float, metric: str,
           cells_red_generic: Optional[float] = None,
           wires_red_generic: Optional[float] = None,
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
    failures: List[str] = []         # real, blockable under-reductions
    unreachable: List[str] = []      # proven-near-minimal sub-threshold metrics
    if bind_cells and cells_red < threshold_pct:
        if cells_red < 0:
            failures.append(
                f"cells reduction {cells_red:.2f}% < {threshold_pct:g}% "
                f"(design GREW — optimized has MORE cells than original; "
                f"never a near-minimal/unreachable target)")
        elif _generic_headroom(cells_red, cells_red_generic, threshold_pct):
            failures.append(
                f"cells reduction {cells_red:.2f}% < {threshold_pct:g}%"
                + (f" (generic {cells_red_generic:.2f}% has headroom)"
                   if cells_red_generic is not None else ""))
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
        elif _generic_headroom(wires_red, wires_red_generic, threshold_pct):
            failures.append(
                f"wires reduction {wires_red:.2f}% < {threshold_pct:g}%"
                + (f" (generic {wires_red_generic:.2f}% has headroom)"
                   if wires_red_generic is not None else ""))
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
    return ("PASS",
            f"area reduction meets the {threshold_pct:g}% threshold ("
            + ", ".join(parts) + ")")


# ─── yosys-in-container synth + stat ─────────────────────────────────────────
# Path inside the iic-osic-tools / iic-eda container where the EDA tools live.
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


def _docker_exec(container: str, cmd: str, timeout: int = 600
                 ) -> Tuple[int, str, str]:
    full = ["docker", "exec", container, "bash", "-lc", cmd]
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
    rc, out, err = _docker_exec(container, cmd, timeout=600)
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
) -> Tuple[int, Dict]:
    """Run the gate; return (rc, report). rc is the program exit code.

    rc 0 = PASS / NOT-APPLICABLE / SKIP, rc 1 = BLOCK (under threshold),
    rc 2 = setup error.
    """
    report: Dict = {
        "program": "ppa_area_threshold_check",
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

    verdict, reason = decide_clauses(
        cells_red, wires_red, clauses, combinator,
        cells_red_generic=cells_red_generic,
        wires_red_generic=wires_red_generic)
    report["verdict"] = verdict
    report["reason"] = reason
    if verdict == "BLOCK":
        return 1, report
    return 0, report


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
    ap.add_argument("--container", default="iic-eda",
                    help="docker container with yosys (default iic-eda)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)

    original = Path(args.original)
    optimized = Path(args.optimized)
    if not original.is_file():
        print(f"ERROR: --original not found: {original}", file=sys.stderr)
        return 2
    if not optimized.is_file():
        print(f"ERROR: --optimized not found: {optimized}", file=sys.stderr)
        return 2
    if args.threshold_pct is None and args.prompt is None:
        print("ERROR: provide --threshold-pct or --prompt", file=sys.stderr)
        return 2

    prompt_text = None
    if args.prompt is not None:
        pp = Path(args.prompt)
        if not pp.is_file():
            print(f"ERROR: --prompt not found: {pp}", file=sys.stderr)
            return 2
        prompt_text = pp.read_text(errors="replace")

    rc, report = run_ppa_area_threshold(
        original=original, optimized=optimized, top=args.top,
        prompt_text=prompt_text, threshold_override=args.threshold_pct,
        metric_override=args.metric, container=args.container)

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
    if verdict in ("BLOCK", "PASS"):
        print("  hint (#744): this area verdict is valid ONLY from the "
              "in-container measurement (pinned yosys); a local yosys of a "
              "different version can report an opposite-sign delta for the same "
              "RTL pair — do not contradict this verdict with a local re-measure.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
