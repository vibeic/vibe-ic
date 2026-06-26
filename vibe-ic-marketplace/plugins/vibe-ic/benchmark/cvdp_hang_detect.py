#!/usr/bin/env python3
"""cvdp_hang_detect.py — emit-side hang-predict heuristics (v1.2.45).

ORGANIC §4 "hang 子集" — the 6 file-named hang subjects (mem_allocator /
manchester_enc / ir_receiver / fifo_async / attenuator / axi_alu cluster)
— bucketed by their cocotb watchdog timeout signature (§ v1.2.41).
Their actual ROOT CAUSE in v1.2.44 is NOT combinational self-loop /
forever — it is wrong-data, timing-margin, and w-r-ptr mismatch shapes
that the heuristic set below does NOT detect. On a baseline sweep of
the 302-responses set in this run:

  * 28 entries trip `predicted_hang = True` (mostly spurious counter-
    idiom / combinational-loop patterns that LEGITIMATELY exist in
    pure-combinational utility code)
  * 17 of those 28 are on the score-final PASS list — proving an
    active BLOCK on this tag would cost 17 false-positives on currently-
    passing entries (a clear §4.05 leak)
  * 0/6 of the file-named hang subjects above trip the detector —
    confirming their hang signatures are NOT combinatorial, and the
    tag below functions only as a NEXT-LAYER AUDIT HINT.

STRICT §4.05 no-leak DISCIPLINE — this module is byte-equivalent AUX only:
  ✓ does NOT modify the completion string in any way
  ✓ does NOT modify the RTL text
  ✓ adds ONLY entry["hang_predicted"]: True / entry["hang_reason"]: ...
    / entry["hang_signatures"]: [...] as advisory-only metadata
  ✗ MUST NOT flip a `pass` to `fail` based on this tag alone — any
    future layer that wants to consume it MUST come back with a
    tighter chip-AGNOSTIC detector that PROVES no-leak on the real
    benchmark before it becomes a verdict input.
chip-AGNOSTIC: 純 RTL 文字規則，不拉 chip 名 / vendor / SKU。
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ── 1. combinational loop (assign-only chain) ───────────────────────────────────
# A small sanity check: an `assign x = something(x)` always_comb that references
# itself transitively produces a iverilog ELAB-loops-on-敏感. stamp shapes
# loop. We do a pairwise assign-pair scan: an `assign dst = expr` where the
# expression references `dst` itself is a textbook unstable combinational loop.

# Variants we cover:
#   a) `assign dst = ~dst;` (bare `assign` line)
#   b) `always @* dst = ~dst;` or `always_comb dst = ...dst...;` (always-block
#      single-statement self-reference — the 6 known hangs include this shape)
#   c) `always @* dst <= ~dst;` (NBA in @* — ill-formed but parity check only)
_ASSIGN_LINE_RE = re.compile(r"^\s*assign\s+(\w+)\s*=", re.MULTILINE)
_ALWAYS_COMB_RE = re.compile(
    r"\balways\s*@?\s*\*\s*|\balways_comb\b", re.IGNORECASE)


def _combinational_loop_signatures(code: str) -> List[str]:
    sigs: List[str] = []
    if not code:
        return sigs
    # (a) bare `assign dst = ..dst..;`
    for m in _ASSIGN_LINE_RE.finditer(code):
        dst = m.group(1)
        start = m.end()
        end_pos = code.find(";", start)
        if end_pos < 0 or end_pos - start > 240:
            continue
        rhs = code[start:end_pos]
        if re.search(rf"\b{re.escape(dst)}\b", rhs):
            sigs.append(f"assign {dst} <- ..{dst}..  // self-loop")
    # (b) `always @* / always_comb <body>` — find every always-block and look
    #     at its body for self-referential assignments.
    body_idx = 0
    while True:
        m_comb = _ALWAYS_COMB_RE.search(code, body_idx)
        if not m_comb:
            break
        body_start = m_comb.end()
        # The body is `begin ... end` OR a single statement up to the next `end`
        # / next always-block opening. Find the matching close.
        depth, i = 0, body_start
        body_end = body_start
        while i < len(code):
            ch = code[i]
            if code[i:i+5] == "begin":
                depth += 1; i += 5; continue
            if code[i:i+3] == "end":
                if depth == 0:
                    body_end = i; break
                depth -= 1; i += 3; continue
            if ch == ";" and depth == 0:
                body_end = i + 1; break
            i += 1
        if body_end <= body_start:
            body_idx = body_start + 1; continue
        body = code[body_start:body_end]
        # Look for `dst = ..dst..` or `dst <= ..dst..` shape inside body
        for asn in re.finditer(
                r"\b(\w+)\s*(<=|=)\s*([^;]+)", body):
            dst = asn.group(1)
            if dst in {"if", "case", "while", "for", "always"}:
                continue
            rhs = asn.group(3)
            # Squelch false-positive `counter += 1` shape: a `dst = dst + 1`
            # expression that adds a literal 1 (or -1) is the legitimate
            # always_comb counter idiom, not a self-loop.
            stripped = rhs.strip()
            if re.fullmatch(rf"{re.escape(dst)}\s*[+\-*/&|^]\s*1", stripped):
                continue
            if re.fullmatch(rf"1\s*[+\-*/&|^]\s*{re.escape(dst)}", stripped):
                continue
            if re.search(rf"\b{re.escape(dst)}\b", rhs):
                sigs.append(
                    f"always_comb body: {dst} {asn.group(2)} ..{dst}..  // self-loop")
        body_idx = body_end
    # dedup
    return list(dict.fromkeys(sigs))


# ── 2. never-asserting handshake ────────────────────────────────────────────────
# Heuristic: an `always @(posedge clk)` body that drives a `valid` / `done` /
# `ready` style signal ONLY from a guarded condition that may never hold
# (e.g. always 0 / always 1 / reset-only cleared register) — wide-net attempt.
# We mark, NOT assert: e.g. detecting `valid <= 1'b0;` only — never `valid <= 1;`.
_VALID_DRV_RE = re.compile(
    r"\b(valid|done|complete|finished|rdy|handshake)\s*<=\s*1['\"]?b?0\b",
    re.IGNORECASE)
_ALWAYS_FOREVER_RE = re.compile(
    r"\balways\s+@\s*\*\s*begin[^;]*?(forever|while\s*\(\s*1)", re.S)


def _dead_signal_signatures(code: str) -> List[str]:
    """Recognise the 「output always stuck at 0」 shape (a flagged, hands-off
    push-only always-zero assign). NOTE: not a hang by itself; cocotb scoring
    will pass-through as FAIL eventually. We duck the hint shape."""
    hints: List[str] = []
    for m in _VALID_DRV_RE.finditer(code or ""):
        sig = m.group(1).lower()
        # Look backwards 120 chars to see context — only flag when the same
        # signal is never driven to 1 elsewhere in the file. NOTE: positive
        # patterns must NOT match the `1` literal in `1'b0` / `1'b1` — only
        # the immediate ` 1` / ` 1'b1` with NO size prefix and a radix-x
        # suffix `b` (or trailing-width syntax). Tighten to disambiguate.
        line = code.rfind("\n", 0, m.start())
        prefix = code[max(0, line - 120): line + 240]
        # `` valid <= 1 ' b1 ' '? — match follow digits-only after the `1`
        # with a SIMPLE `1'b1` / `1`/literal: exclude both `1'b0` and
        # size-then-'b0' that the window may contain.
        if (
            not re.search(rf"\b{sig}\s*(?:<=|=)\s*(?!1['\"]?b?0\b)1",
                          prefix, re.IGNORECASE)
        ):
            hints.append(f"{sig} driven to 0-only (no 1 in window)")
    return hints


# ── 3. forever / infinite-while block in always_comb ─────────────────────────────
def _forever_signatures(code: str) -> List[str]:
    hints: List[str] = []
    for m in _ALWAYS_FOREVER_RE.finditer(code or ""):
        hints.append("`always @*` contains `forever` / `while(1)` (combinational-hang)")
    return hints


# ── public API ─────────────────────────────────────────────────────────────────
def predict_hang(code: str) -> Tuple[bool, str, List[str]]:
    """Return `(predicted_hang, primary_reason, all_signatures)`.

    `predicted_hang = True` iff at least one STRONG hint fires (combinational
    self-loop or `@*` containing `forever`). DEAD-signal and similar WEAK hints
    do NOT fire `predicted_hang` — they are surfaced only via `signatures` so
    the field audit can review them, but the gate never BLOCKs on them."""
    if not code or not code.strip():
        return False, "(empty)", []
    sigs_combo = _combinational_loop_signatures(code)
    sigs_forever = _forever_signatures(code)
    sigs_dead = _dead_signal_signatures(code)
    strong = sigs_combo + sigs_forever
    all_sigs = sigs_combo + sigs_forever + sigs_dead
    if strong:
        primary = strong[0]
        return True, primary, all_sigs
    if sigs_dead:
        return False, sigs_dead[0], all_sigs   # WEAK hint only
    return False, "", []
