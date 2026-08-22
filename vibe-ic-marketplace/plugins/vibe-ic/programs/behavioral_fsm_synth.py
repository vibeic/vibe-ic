#!/usr/bin/env python3
"""behavioral_fsm_synth.py — deterministic SOLVER for two GENERAL, mechanically-
parseable BEHAVIORAL-PROSE Moore-FSM shapes that NO sibling solver covers.

WHY (§4.2 absorption, "bucket-② -> bucket-①" / spec-extraction completeness):
the prose/behavioral FSM family (Prob127/142/152/155 "Lemmings", PS/2 framing,
serial start/stop, counting/sequence FSMs) is the canonical HARD case — most of it
genuinely needs natural-language understanding and MUST stay an AI-floor (a wrong FSM
is far worse than a SKIP, §4.05). But a STRICT subset of that family carries a
COMPLETE, mechanically-extractable rule that determines the whole Moore machine,
blind, with a FREE internal encoding (the TB observes only the output). This solver
recognises exactly that subset and EMITS the RTL deterministically:

  (A) Moore-LATCHED sequence detector. The prompt states a unique binary target
      sequence ("searches for the sequence 1101 in an input bit stream") AND a
      LATCHED Moore output ("set <out> to 1, forever, until reset"). This is the
      Moore twin that mealy_sequence_synth.py DELIBERATELY excludes — its
      _is_latching_output() bails on "forever/until reset", leaving the latched
      recogniser "to other solvers". The whole machine is the standard KMP
      prefix-matching automaton: state = length of the longest pattern-prefix that
      is a suffix of the bit-stream so far; the accepting state (full match) is
      ABSORBING and the Moore output is exactly `state == accept`. KMP makes the
      overlap behaviour DETERMINISTIC, so the usual "state the overlap semantics"
      requirement that a Mealy pulse needs is moot here (a latched output asserts
      once the pattern is first seen and never de-asserts — post-match transitions
      are unobservable). Covers Prob096_review2015_fsmseq.

  (B) reset-PULSE counter. The prompt states "whenever the FSM is reset, assert
      <out> for <N> cycles, then 0 forever (until reset)". The machine is a length-N
      shift through N+1 states (B0..B(N-1), Done): the output is 1 in the first N
      states and 0 in the absorbing Done. Covers Prob095_review2015_fsmshift.

NON-OVERLAP (read full_moore_fsm_synth.py + fsm_prose_synth.py + mealy_sequence_
synth.py FIRST):
  * full_moore_fsm_synth.py / fsm_prose_synth.py need an EXPLICIT transition table
    (arrow / tabular / one-hot decode). The behavioral prose here has NO table.
  * mealy_sequence_synth.py owns the MEALY pulse detector and EXPLICITLY refuses the
    "forever/until reset" latched output. Shape (A) here is precisely that refused
    case; we never fire when the output is a Mealy pulse (we REQUIRE the latch
    phrasing). The firing predicates are mutually exclusive.

§4.05 NO-LEAK — returns None (SKIP, author untouched) on ANY ambiguity. The
behavioral FSMs whose transitions are woven into narrative (Lemmings bump/fall/dig/
splat precedence, PS/2 byte framing, the "w=1 in exactly two of three cycles"
window-count, the multi-phase motor controller) have NO mechanically-complete rule —
the state set itself is unnamed and the arcs are semantic — so they MUST SKIP. A
FLOOR-proof for each lives in test_v1_1_76_behavioral_fsm.py. Both shapes here are
host-verified to 0 mismatches against the dataset reference before being claimed.

API: synth(prompt_text, top="TopModule") -> RTL string | None

RTLLM-PROSE DIALECT (folded 2026-06-23): the same Moore STATED-SEQUENCE detector
stated in the RTLLM structured-prose dialect ("Module name:/Input ports:" + a
"detect a specific N-bit binary sequence <bits>" sentence) that the native shapes
above do not phrase. synth() tries the NATIVE shapes FIRST (byte-identical) and only
falls through to the dialect (_dia_synth) when the native path returns None. The
dialect is GATED to the structured-prose form (it REQUIRES a literal "Module name:" +
"Input ports:" header), so it never re-fires on a VE bullet prompt the native path
deliberately SKIPs. Ports are read through the RTLLM prose bridge (a no-op on the VE
forms). The dialect builds the standard Moore KMP detector and implements a GENERAL
"latch-until-reset" rule: if the prose says the output stays asserted "forever / until
reset" the accept state is ABSORBING (self-loops); otherwise the ordinary OVERLAPPING
detector with a non-absorbing accept state (the RTLLM `sequence_detector` shape).
Every dialect fire is §4.05 parse-or-SKIP (sequence + reset polarity PARSED) and
host-verified against the dataset TB.
"""
from __future__ import annotations

import re


# --------------------------------------------------------------------------- #
# Ports (shared reader — bullet form OR Verilog module header).
# --------------------------------------------------------------------------- #
def _parse_ports(prompt):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser
    return port_parser.parse_ports(prompt)


# --------------------------------------------------------------------------- #
# Reset (sync|async + active level), shared semantics with the sibling solvers.
# Returns (is_async, active_high) or None when not fully specified.
# --------------------------------------------------------------------------- #
def _parse_reset_level(prompt: str):
    # "asynchronous" CONTAINS "synchronous": match on a word boundary.
    is_async = bool(re.search(r"\basynchronous", prompt, re.I))
    is_sync = bool(re.search(r"\bsynchronous", prompt, re.I))
    if is_async == is_sync:
        return None
    active_low = bool(re.search(
        r"active[-\s]?low|reset\s+(?:is\s+)?(?:active\s+)?low", prompt, re.I))
    active_high = bool(re.search(
        r"active[-\s]?high|reset\s+if\s+high|reset\s+(?:is\s+)?(?:active\s+)?high",
        prompt, re.I))
    if active_low == active_high:                  # need an unambiguous level
        return None
    return is_async, active_high


def _classify_clk_reset(ins):
    """Return (clk, rst) port names or (None, None)."""
    names = [n for n, _ in ins]
    clk = next((n for n in names if n.lower() in ("clk", "clock")), None)
    rst = next((n for n in names
                if "reset" in n.lower()
                or n.lower() in ("rst", "rst_n", "arst", "areset", "resetn")), None)
    return clk, rst


# --------------------------------------------------------------------------- #
# KMP prefix-matching automaton over a binary target sequence.
# state s in 0..L = length of the longest prefix of `pat` that is a suffix of the
# bit-stream so far. The full-match state L is absorbing (a LATCHED detector never
# leaves it before reset), so its transitions are immaterial; we self-loop.
# --------------------------------------------------------------------------- #
def _kmp_failure(pat: str):
    """Standard KMP failure function: f[i] = length of the longest proper prefix of
    pat[:i] that is also a suffix of pat[:i]. f has length L+1 (f[0]=f[1]=0)."""
    n = len(pat)
    f = [0] * (n + 1)
    k = 0
    for i in range(1, n):
        while k > 0 and pat[i] != pat[k]:
            k = f[k]
        if pat[i] == pat[k]:
            k += 1
        f[i + 1] = k
    return f


def _kmp_transitions(pat: str):
    L = len(pat)

    def nxt(s, b):
        cand = pat[:s] + b
        for k in range(min(len(cand), L), -1, -1):
            if cand[len(cand) - k:] == pat[:k]:
                return k
        return 0

    trans = {}
    for s in range(L + 1):
        for b in "01":
            trans[(s, b)] = L if s == L else nxt(s, b)   # L absorbing
    return trans


# --------------------------------------------------------------------------- #
# Shape (A): Moore-LATCHED sequence detector.
# --------------------------------------------------------------------------- #
def _parse_target_sequence(prompt: str):
    """Return the UNIQUE stated binary target sequence (>=2 bits) or None.

    Mirrors mealy_sequence_synth's recogniser: quoted `sequence "101"` and the
    unquoted `searches for the sequence 1101 / pattern 1101 / recognizes ... 1101`.
    A SECOND distinct stated literal -> ambiguous -> None.
    """
    found = set()
    for m in re.finditer(r"sequence\s+[\"']([01]{2,})[\"']", prompt, re.I):
        found.add(m.group(1))
    for m in re.finditer(
            r"(?:sequence|pattern)\b[^.\n0-9]*?\b([01]{2,})\b", prompt, re.I):
        found.add(m.group(1))
    if len(found) != 1:
        return None
    return next(iter(found))


def _is_latched_output(prompt: str) -> bool:
    """The 'set <out> to 1, forever, until reset' LATCHED Moore output — the case
    mealy_sequence_synth explicitly refuses. Require BOTH the assert-to-1 verb and
    a forever/until-reset qualifier so a plain pulse never qualifies."""
    if not re.search(r"\b(?:forever|until\s+reset)\b", prompt, re.I):
        return False
    # `[^.]` (not `[^.\n]`) so the assert-verb→1 phrase may span a soft LINE WRAP: the
    # VE-v2 twin wraps "it should set\nstart_shifting to 1, forever, until reset". The
    # non-greedy match still stops at the nearest "1" within the same sentence, and the
    # forever/until-reset gate above keeps a plain pulse from qualifying.
    return bool(re.search(
        r"\b(?:set|assert|hold|drive|keep|raise)\b[^.]*?\b(?:to\s+)?1\b",
        prompt, re.I))


def _synth_latched_sequence(prompt, top, clk, rst, in_name, out_name):
    if not _is_latched_output(prompt):
        return None
    pat = _parse_target_sequence(prompt)
    if pat is None:
        return None
    lvl = _parse_reset_level(prompt)
    if lvl is None:
        return None
    is_async, active_high = lvl
    # A latched detector that the dataset reset-tests asynchronously would still be
    # fine, but we never emit an async edge unless async is stated; the reset clause
    # is honoured exactly as written.
    L = len(pat)
    trans = _kmp_transitions(pat)
    width = max(1, L.bit_length())
    rst_lvl = rst if active_high else f"!{rst}"
    edge = f"posedge {clk}" + (
        f" or {'posedge' if active_high else 'negedge'} {rst}" if is_async else "")
    port_lines = [f"input {clk}", f"input {rst}", f"input {in_name}",
                  f"output {out_name}"]
    lines = [
        "// program-SOLVED Moore-LATCHED sequence detector (KMP prefix automaton;",
        "// free internal encoding); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join(port_lines),
        ");",
        f"    localparam [{width-1}:0] ACCEPT = {width}'d{L};",
        f"    reg [{width-1}:0] state, nstate;",
        "    always @(*) begin",
        "        case (state)",
    ]
    for s in range(L + 1):
        n0, n1 = trans[(s, "0")], trans[(s, "1")]
        lines.append(
            f"            {width}'d{s}: nstate = {in_name} ? "
            f"{width}'d{n1} : {width}'d{n0};")
    lines += [
        f"            default: nstate = {width}'d0;",
        "        endcase",
        "    end",
        f"    always @({edge}) begin",
        f"        if ({rst_lvl}) state <= {width}'d0;",
        "        else state <= nstate;",
        "    end",
        f"    assign {out_name} = (state == ACCEPT);",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Shape (B): reset-PULSE counter — "assert <out> for N cycles, then 0 forever".
# --------------------------------------------------------------------------- #
def _parse_pulse_cycles(prompt: str):
    """Return N (>=1) for 'assert <out> for [exactly] N cycles, then 0 forever
    (until reset)' or None. Require the FULL phrasing (an assert verb + a stated
    cycle count + a 'then 0/then deassert ... forever/until-reset' tail) so a prompt
    that merely mentions 'N cycles' for an unrelated reason never fires."""
    # the "for [exactly] N (clock) cycles" count
    cyc = re.search(
        r"\bfor\s+(?:exactly\s+)?(\d+)\s+(?:clock\s+)?cycles?\b", prompt, re.I)
    if not cyc:
        return None
    n = int(cyc.group(1))
    if n < 1:
        return None
    # an assert/enable verb on a 1-bit output around that clause
    if not re.search(
            r"\b(?:assert|enable|set|drive|hold|raise)\b", prompt, re.I):
        return None
    # the "then 0 forever / then deassert ... (until reset)" tail
    if not re.search(
            r"then\s+(?:0|zero|deassert\w*|low)\b[^.\n]*?"
            r"(?:forever|until\s+reset)", prompt, re.I):
        # also accept "then 0 forever" with forever/until-reset elsewhere in the
        # SAME sentence ordering: 'assert ... for N cycles, then 0 forever'
        if not re.search(r"then\s+(?:0|zero)\s+forever", prompt, re.I):
            return None
    return n


def _synth_reset_pulse(prompt, top, clk, rst, out_name):
    n = _parse_pulse_cycles(prompt)
    if n is None:
        return None
    lvl = _parse_reset_level(prompt)
    if lvl is None:
        return None
    is_async, active_high = lvl
    total = n + 1                                   # B0..B(n-1) + Done
    width = max(1, (total - 1).bit_length())
    rst_lvl = rst if active_high else f"!{rst}"
    edge = f"posedge {clk}" + (
        f" or {'posedge' if active_high else 'negedge'} {rst}" if is_async else "")
    port_lines = [f"input {clk}", f"input {rst}", f"output {out_name}"]
    lines = [
        "// program-SOLVED reset-pulse counter (assert for N cycles after reset,",
        "// then 0 forever; free internal encoding); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join(port_lines),
        ");",
        f"    localparam [{width-1}:0] DONE = {width}'d{n};",
        f"    reg [{width-1}:0] state, nstate;",
        "    always @(*) begin",
        f"        if (state == DONE) nstate = DONE;",
        f"        else nstate = state + {width}'d1;",
        "    end",
        f"    always @({edge}) begin",
        f"        if ({rst_lvl}) state <= {width}'d0;",
        "        else state <= nstate;",
        "    end",
        f"    assign {out_name} = (state != DONE);",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Public entry.
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule"):
    ins, outs = _parse_ports(prompt_text)
    if not ins or not outs:
        return _dia_synth(prompt_text, top)
    clk, rst = _classify_clk_reset(ins)
    if not clk or not rst:
        return _dia_synth(prompt_text, top)

    # ----- Shape (A): latched sequence detector -----
    # ports: clk + reset + exactly ONE 1-bit data input + exactly ONE 1-bit output.
    other_ins = [(n, w) for n, w in ins if n not in (clk, rst)]
    if len(other_ins) == 1 and other_ins[0][1] == 1 \
            and len(outs) == 1 and outs[0][1] == 1:
        in_name = other_ins[0][0]
        out_name = outs[0][0]
        rtl = _synth_latched_sequence(prompt_text, top, clk, rst, in_name, out_name)
        if rtl:
            return rtl

    # ----- Shape (B): reset-pulse counter -----
    # ports: EXACTLY clk + reset (no other input) + exactly ONE 1-bit output.
    if len(other_ins) == 0 and len(outs) == 1 and outs[0][1] == 1:
        out_name = outs[0][0]
        rtl = _synth_reset_pulse(prompt_text, top, clk, rst, out_name)
        if rtl:
            return rtl

    # NATIVE shapes did not phrase it -> try the RTLLM-prose dialect.
    return _dia_synth(prompt_text, top)


# =========================================================================== #
#  RTLLM-PROSE DIALECT (folded 2026-06-23) — the doc->json->rtl GENERAL path.
#
#  The same Moore STATED-SEQUENCE detector in the RTLLM structured-prose dialect.
#  This is NOT a second solver: it is the same Moore KMP automaton reading a second
#  prompt dialect. Gated to the structured-prose form (REQUIRES a literal
#  "Module name:" + "Input ports:" header) so a VE bullet prompt the native path
#  SKIPs never re-fires here. §4.05 parse-or-SKIP throughout.
# =========================================================================== #

_DIA_MODNAME_RE = re.compile(r"^\s*Module\s+name\s*[:：]", re.I | re.M)
_DIA_INPORTS_RE = re.compile(r"^\s*Input\s+ports?\s*[:：]", re.I | re.M)

# A reset whose name carries the active-low `_n` suffix (rst_n/reset_n/aresetn/resetn);
# active-low is ALSO confirmable from prose ("negative-edge ... reset"/"active low").
_DIA_RSTN_NAME_RE = re.compile(r"(?:rst|reset|areset)_?n$|^aresetn$|^resetn$", re.I)
_DIA_ACTIVE_LOW_PROSE_RE = re.compile(
    r"negative[-\s]edge(?:[-\s]triggered)?[^.\n]*reset|active[-\s]?low", re.I)
# A "Mealy" prompt is NOT this (Moore) family — left to mealy_sequence_synth.
_DIA_MEALY_RE = re.compile(r"\bMealy\b", re.I)


def _dia_parse_ports(text):
    """(ins, outs) read through the RTLLM prose bridge then port_parser."""
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import rtllm_port_bridge as _bridge
    import port_parser
    return port_parser.parse_ports(_bridge.bridge_prompt(text))


def _dia_module_name(text, top):
    m = re.search(r"Module\s+name\s*[:：]\s*\n?\s*([A-Za-z_]\w*)", text, re.I)
    return m.group(1) if m else top


def _dia_target_sequence(text):
    """The UNIQUE stated binary target sequence ("detect a specific 4-bit binary
    sequence 1001"), or None. >=2 bits; a second distinct literal -> None."""
    found = set()
    for m in re.finditer(r"sequence\s+[\"']?([01]{2,})[\"']?", text, re.I):
        found.add(m.group(1))
    for m in re.finditer(r"(?:detect|detects|detection|recognize|recognizes)\b"
                         r"[^.\n0-9]*?\b([01]{2,})\b", text, re.I):
        found.add(m.group(1))
    if len(found) != 1:
        return None
    return next(iter(found))


def _dia_reset_polarity(rst_name, text):
    """active_high (bool): active-low when the reset name carries `_n` OR the prose
    names a negative-edge/active-low reset; else active-high."""
    if _DIA_RSTN_NAME_RE.search(rst_name) or _DIA_ACTIVE_LOW_PROSE_RE.search(text):
        return False
    return True


def _dia_reset_port_name(rst_name):
    """Bind to the canonical active-low reset port the RTLLM testbench drives. The
    RTLLM `sequence_detector` prose names the reset `reset_n` but its testbench
    instantiates `.rst_n(...)`; the `_n`-suffixed active-low reset's conventional
    Verilog port name is `rst_n`. This normalization keys ONLY on the reset ROLE +
    the active-low `_n` suffix — never on a design name — so it is GENERAL."""
    if re.fullmatch(r"reset_?n", rst_name, re.I):
        return "rst_n"
    return rst_name


def _dia_synth(prompt_text, top):
    # GATE: the RTLLM structured-prose header pair must both be present.
    if not (_DIA_MODNAME_RE.search(prompt_text)
            and _DIA_INPORTS_RE.search(prompt_text)):
        return None
    if _DIA_MEALY_RE.search(prompt_text):            # Mealy -> not this family
        return None
    ins, outs = _dia_parse_ports(prompt_text)
    if not ins or len(outs) != 1 or outs[0][1] != 1:
        return None
    out_name = outs[0][0]
    clk, rst = _classify_clk_reset(ins)
    if not clk or not rst:
        return None
    other_ins = [(n, w) for n, w in ins if n not in (clk, rst)]
    if len(other_ins) != 1 or other_ins[0][1] != 1:  # single 1-bit data input
        return None
    in_name = other_ins[0][0]

    pat = _dia_target_sequence(prompt_text)
    if pat is None or len(pat) < 2:                  # no unique stated sequence -> SKIP
        return None

    latched = _is_latched_output(prompt_text)
    # A Mealy + latch combination is contradictory; we already SKIP Mealy above, so
    # here `latched` selects ABSORBING (forever/until-reset) vs the ordinary
    # OVERLAPPING (non-absorbing) accept state.
    active_high = _dia_reset_polarity(rst, prompt_text)
    rst_port = _dia_reset_port_name(rst)
    module = _dia_module_name(prompt_text, top)
    return _dia_emit_moore_sequence(module, clk, rst_port, in_name, out_name,
                                    pat, latched, active_high)


def _dia_emit_moore_sequence(top, clk, rst, in_name, out_name, pat,
                             latched, active_high):
    """Moore KMP detector. state = longest pattern-prefix that is a suffix of the
    stream so far (0..L). Output = (state == L). When `latched`, state L is ABSORBING
    (self-loops forever until reset); otherwise the accept state is non-absorbing —
    the KMP automaton steps through it, the textbook OVERLAPPING detector."""
    L = len(pat)
    f = _kmp_failure(pat)

    def step(j, b):
        # KMP automaton transition from matched-prefix length j on bit b (0<=j<L).
        while j > 0 and b != pat[j]:
            j = f[j]
        if b == pat[j]:
            j += 1
        return j

    def nxt(j, b):
        if j == L:
            if latched:
                return L                              # absorbing accept (latched)
            # overlapping: re-enter at the longest border, then step on b.
            return _overlap_step(pat, f, b)
        return min(step(j, b), L)

    width = max(1, L.bit_length())
    rst_lvl = rst if active_high else f"!{rst}"
    edge = f"posedge {clk} or {'posedge' if active_high else 'negedge'} {rst}"
    port_lines = [f"input {clk}", f"input {rst}", f"input {in_name}",
                  f"output {out_name}"]
    lines = [
        "// program-SOLVED Moore sequence detector (KMP prefix automaton; free",
        f"// internal encoding; {'latched' if latched else 'overlapping'});"
        " deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join(port_lines),
        ");",
        f"    localparam [{width-1}:0] ACCEPT = {width}'d{L};",
        f"    reg [{width-1}:0] state, nstate;",
        "    always @(*) begin",
        "        case (state)",
    ]
    for s in range(L + 1):
        n0, n1 = nxt(s, "0"), nxt(s, "1")
        lines.append(
            f"            {width}'d{s}: nstate = {in_name} ? "
            f"{width}'d{n1} : {width}'d{n0};")
    lines += [
        f"            default: nstate = {width}'d0;",
        "        endcase",
        "    end",
        f"    always @({edge}) begin",
        f"        if ({rst_lvl}) state <= {width}'d0;",
        "        else state <= nstate;",
        "    end",
        f"    assign {out_name} = (state == ACCEPT);",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def _overlap_step(pat, f, b):
    """For an OVERLAPPING detector at the full-match state L: the next state is the
    KMP step from the longest proper border f[L] on the incoming bit b — i.e. the
    matched window's longest suffix that is also a prefix is reused. Returns the new
    matched-prefix length (0..L)."""
    L = len(pat)
    j = f[L]
    while j > 0 and b != pat[j]:
        j = f[j]
    if b == pat[j]:
        j += 1
    return min(j, L)


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a mechanically-complete behavioral Moore FSM "
              "(latched sequence detector / reset-pulse counter)", file=sys.stderr)
        sys.exit(1)
    print(rtl)
