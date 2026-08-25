#!/usr/bin/env python3
"""sim_hang_detect.py — emit-side hang-predict heuristics (v1.2.45→v1.2.46).

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
  * 0/6 of the file-named hang subjects above trip the STRONG detector
    — confirming their hang signatures are NOT combinatorial, and the
    tag functions only as a NEXT-LAYER AUDIT HINT.

v1.2.46 EXTENSION — add 3 WEAK heuristics specific to the file-named
hang root-cause shapes (gray-code next-cycle comparator, handshake-valid
one-cycle pulse with test `await RisingEdge` evidence, port-list-vs-
top-level-init DUT mismatch). These all surface ONLY in `signatures`
(audit trail) — they do NOT lift `predicted_hang` to True, preserving
the §4.05 no-leak invariant and `test_baseline_sweep_no_pass_to_fail_flip`
pin set in v1.2.45. Target fire-rate (baseline 302 sweep):
  * gray-code next-cycle comparator: ~1-2/302 (fifo_async cluster)
  * handshake-valid one-cycle pulse: ~2-3/302 (ir_receiver cluster)
  * port-list mismatch: ~1/302 (axi_alu cluster — single nonagentic
    sample Carry port-mismatch in module declaration)

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


# ── 4. (v1.2.46 WEAK) gray-code next-cycle comparator ─────────────────────────────
# Pattern: an async-FIFO `full` / `empty` block computing equality against a
# `_<var>_next` variant instead of the REGISTERED `_var`. Off-by-one cycle
# double-flag in real async-FIFO designs. We surface ONLY via `signatures`
# (audit trail), never blocking — the cycle-level codepath requires post-
# synth / simulation to PROVE, and an over-trigger on golden-class code that
# legitimately uses `_next` for one-cycle-ahead combinational compare would
# false-fire on a wide class of COMPLEX FIFO designs.
_GRAY_NEXT_RE = re.compile(
    r"\b(full|empty|_full|_empty)\s*=(?=[^=]+?(?:_next|w_next|r_next)\b[^;]*==[^;]*(?:_sync[sr]?\d*|_gray|bin|\bgray\b))[^;]+",
    re.IGNORECASE)
# Allow only the LEAD `_full/empty = ` followed by an equality against a
# `_next` variant inside the same statement. A legitimate ALWAYS_BLOCK
# registered `_next` value compared to a sync FFT output is FINE; the
# ANTI-pattern is: comparing `_var_next` to another `_var_sync_X` value
# directly, which rolls a single-cycle of error into full/empty.


def _gray_code_next_cycle_signatures(code: str) -> List[str]:
    """Detect 「empty/full compared against _next instead of registered gray」.

    The shape is: `assign full = (gray_next == ..._sync...);` where the
    LHS uses `_next` instead of the registered value. This is a SQL &
    combinational-fork fire: timing Pathfinder test on `full`/`empty`
    against an out-of-register state must fail at full-cycle because the
    `_next` last-value shifts disqualified ADJACENT.

    Real-example WEAK pattern (axi_alu / fifo_async / pass-trial designs):
        assign full  = (w_gray_next == {~r_gray_sync[ADDR:ADDR-1], r_gray_sync[ADDR-2:0]});
        assign empty = (r_gray_next ==  w_gray_sync2);
    """
    hints: List[str] = []
    if not code:
        return hints
    for m in _GRAY_NEXT_RE.finditer(code):
        # Squelch: only fire if a `_next` token is reachable AND another
        # sync token is reachable AND no immediate registered `gray` (== )
        # REFERENCE of the SAME LHS. This is task-level conservative; an
        # occassional false-positive is preferable to blankly firing.
        body = m.group(0)
        lhs = (m.group(1) or "").lower()
        # Disable trigger when same-statement holds `gray` (the registered
        # shadow) at the SAME compare site, e.g.
        #     `full = (gray == ...) || (gray_next == ...)` — that's legal.
        if re.search(rf"\b{re.escape(lhs)}_?gray\b", body):
            continue
        hints.append(
            f"gray-code next-cycle comparator: `{body.strip()[:120]}` "
            f"(WEAK: registered-vs-_next compare-side ambiguity)"[:240])
    return hints


# ── 5. (v1.2.46 WEAK) handshake-valid one-cycle-only pulse ─────────────────────────
# Pattern: a `valid`/`done`/`complete`/`frame_valid`/`ready` signal is set
# to 1'b1 (or 1) on one line in a sub-state (e.g. `finish`) and reset to
# 1'b0 (or 0) on a SAME-SIGNAL token within an 80-line window downstream.
# When the cocotb test does `await RisingEdge(<signal>)` AFTER a slow-clock
# harness step (the reader clock already sees the FIRST-cycle while the
# signal is HIGH), the `RisingEdge` watcher may NOT fire and the runner
# hangs under watchdog. We surface ONLY via `signatures` (audit trail),
# never BLOCK (§4.05 no-leak).
_VALID_PULSE_SET_RE = re.compile(
    r"\b(valid|done|complete|frame_valid|ir_frame_valid|usb_done|ready)\b"
    r"\s*(?:<=|<|=)\s*"
    r"(?:1(?:'b1|'h1|'d1|b1|h1|d1))",
    re.IGNORECASE)
_VALID_PULSE_RESET_RE = re.compile(
    r"\b(valid|done|complete|frame_valid|ir_frame_valid|usb_done|ready)\b"
    r"\s*(?:<=|<|=)\s*"
    r"(?:0|1(?:'b0|'h0|'d0|b0|h0|d0))",
    re.IGNORECASE)
_MODULE_DECL_RE = re.compile(r"\bmodule\s+(\w+)\s*\(([^;]+)\)",
                             re.MULTILINE)
_SYSTEMVR_WORD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_hdl_comments(text: str) -> str:
    """Blank out `/* ... */` and `// ...` so a declaration written inside a
    comment cannot be read as a declaration.

    `// module round_ctr (a, b)` matches `_MODULE_DECL_RE` and mints a module
    with ports nobody wrote (vibe-ic#729 measured 24 such phantoms). Block
    comments collapse to a space; line comments keep their newline so line
    numbering downstream of a strip is unchanged."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _compute_line_starts(code: str) -> List[int]:
    """Return a list of offset indices where each new line starts in
    `code` (newline character itself). Offset 0 anchors line 1."""
    out: List[int] = [0]
    pos = 0
    while True:
        idx = code.find("\n", pos)
        if idx < 0:
            break
        out.append(idx + 1)
        pos = idx + 1
    return out


def _line_no_at(absolute_idx: int, line_starts: List[int]) -> int:
    """Map an absolute code offset to its 1-based line number."""
    n = 0
    for i, off in enumerate(line_starts):
        if off > absolute_idx:
            return n + 1
        n = i
    return n + 1


def _handshake_one_cycle_pulse_signatures(code: str) -> List[str]:
    """Detect 「a signal is set to 1 then 1'b0 within a small same-module
    downstream window」—`valid <= 1` followed by `valid <= 0` on the SAME
    signal within 80 lines of code.

    Real-example WEAK shape (ir_receiver):
        ir_frame_valid <= 1'b1;
        ...
        ir_frame_valid <= 1'b0;
    The TEST may `await RisingEdge(ir_frame_valid)` and miss the rising
    edge if the harness already sees the first sample-1 cycle.
    """
    if not code:
        return []
    line_starts = _compute_line_starts(code)
    set1_hits: List[Tuple[int, str]] = []
    set0_hits: List[Tuple[int, str]] = []
    for m in _VALID_PULSE_SET_RE.finditer(code):
        sig = (m.group(1) or "").lower()
        if sig:
            set1_hits.append((m.start(), sig))
    for m in _VALID_PULSE_RESET_RE.finditer(code):
        sig = (m.group(1) or "").lower()
        if sig:
            set0_hits.append((m.start(), sig))
    hints: List[str] = []
    seen: set = set()
    # Sort set1 by offset so we hit the LEFT-most first (avoid double-fire
    # on the same signal across distant blocks).
    for off1, sig in sorted(set1_hits):
        if sig in seen:
            continue
        for off0, sig0 in sorted(set0_hits):
            if sig0 != sig:
                continue
            if off0 <= off1:
                continue
            line_diff = _line_no_at(off0, line_starts) - \
                _line_no_at(off1, line_starts)
            if 0 < line_diff <= 80:
                hints.append(
                    f"`{sig}` set=1 then set=0 within {line_diff} lines "
                    f"(WEAK: pulse-1-cycle; cocotb RisingEdge may "
                    f"miss the edge)")
                seen.add(sig)
                break
    return hints


# ── 6. (v1.2.46 WEAK) module-port-list ↔ harness-accessed-port mismatch ───────────────────────────
# Pattern: prompt-side required port (e.g. `axi_awlen_i`) is referenced in
# the test runner (`init_dut(dut.<name>)`) but is NOT in the module port
# declaration list. Same-syntax across test reports causes AttributeError
# when cocotb's `setup_dut` visits the missing child.
#
# Reading-pass: pull port tokens from the `module <top>( ... );` line and
# compare against an _optional_ `expected_ports_csv` parameter. When NOT
# provided, the heuristic only flags if a port in the test script's
# `dut.<x>` access appears to NOT be in the module decl — this requires
# AND prefers the caller providing BOTH the RTL code and the test_script.
# Without test_script, the heuristic is strict-by-default silent.
def _module_ports_from_z(code: str, top_name: Optional[str] = None) -> List[str]:
    """Parse the FIRST module's port list. Return list of port names.

    NOTE: heuristic-wide parsers are conservative — port decls can span
    lines, can have directions, can have widths. We extract the literal
    name tokens between module-decl `(` and the matching `)`. This is a
    text-level port-list, NOT a full SystemVerilog grammar parser; an
    `input wire [7:0] axi_awlen_i  // note` is rewritten to `axi_awlen_i`
    in the returned list.
    """
    if not code:
        return []
    # The scan reads de-commented text. The per-token `startswith("//")` guard
    # below is kept, but it never could have covered this: it filters tokens
    # taken from INSIDE a port list the regex has already accepted, so a whole
    # `module ... ( ... )` written inside a comment mints a phantom module with
    # phantom ports before any token is looked at.
    decommented = _strip_hdl_comments(code)
    # Find first `module <name> (` decl.
    for m in _MODULE_DECL_RE.finditer(decommented):
        return [
            t.strip().rstrip(",").rstrip(";")
            for t in re.findall(
                r"[A-Za-z_]\w*", m.group(2)) if t.strip()
            and not t.strip().startswith("//")
            and _SYSTEMVR_WORD_RE.fullmatch(t.strip())
        ]
    return []


def _port_mismatch_signatures(code: str, expected_ports: Optional[List[str]] = None) -> List[str]:
    """Detects port-list ↔ required-tokens mismatch.

    If `expected_ports` is provided, we flag any token in expected_ports
    that is NOT in the module's port list. If not provided (default), the
    heuristic returns no signatures — the audit layer can pass
    `expected_ports` from the prompt's RTL port requirements.

    Real-example WEAK shape (axi_alu port-mismatch):
        module axi_alu (...);
        endmodule
        // test_runner accesses dut.axi_awlen_i  → AttributeError
    """
    if not code or not expected_ports:
        return []
    ports = set(_module_ports_from_z(code))
    missing: List[str] = []
    for p in expected_ports:
        if not isinstance(p, str):
            continue
        p_norm = p.strip()
        if not p_norm or not _SYSTEMVR_WORD_RE.fullmatch(p_norm):
            continue
        if p_norm not in ports:
            missing.append(p_norm)
    if not missing:
        return []
    return [
        f"module-port-list missing required port(s): {', '.join(missing)} "
        f"(WEAK: cocotb dut.<port> access would AttributeError)"
    ]


# ── public API ─────────────────────────────────────────────────────────────────
def predict_hang(code: str) -> Tuple[bool, str, List[str]]:
    """Return `(predicted_hang, primary_reason, all_signatures)`.

    `predicted_hang = True` iff at least one STRONG hint fires (combinational
    self-loop or `@*` containing `forever`). DEAD-signal and the 3 NEW v1.2.46
    WEAK hints (gray-code next-cycle, handshake-valid one-cycle pulse,
    port-list mismatch) do NOT fire `predicted_hang` — they are surfaced
    only via `signatures` so the field audit can review them, but the gate
    never BLOCKs on them (§4.05 no-leak invariant)."""
    return predict_hang_extended(code, expected_ports=None)


def predict_hang_extended(code: str, expected_ports: Optional[List[str]] = None) -> Tuple[bool, str, List[str]]:
    """Extended entry point — same as `predict_hang` but accepts extra
    context for port-mismatch detection. Returns the same `(predicted_hang,
    primary_reason, all_signatures)` tuple."""
    if not code or not code.strip():
        return False, "(empty)", []
    sigs_combo = _combinational_loop_signatures(code)
    sigs_forever = _forever_signatures(code)
    sigs_dead = _dead_signal_signatures(code)
    sigs_gray = _gray_code_next_cycle_signatures(code)
    sigs_pulse = _handshake_one_cycle_pulse_signatures(code)
    sigs_port = _port_mismatch_signatures(code, expected_ports)
    strong = sigs_combo + sigs_forever
    all_sigs = (sigs_combo + sigs_forever + sigs_dead +
                sigs_gray + sigs_pulse + sigs_port)
    if strong:
        primary = strong[0]
        return True, primary, all_sigs
    # Surface the first WEAK (in canonical discovery order) as reason so the
    # next-layer audit hook sees SOMETHING actionable.
    for w in (sigs_dead, sigs_gray, sigs_pulse, sigs_port):
        if w:
            return False, w[0], all_sigs
    return False, "", []
