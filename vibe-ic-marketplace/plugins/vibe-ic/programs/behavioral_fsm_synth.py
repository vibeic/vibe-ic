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
    return bool(re.search(
        r"\b(?:set|assert|hold|drive|keep|raise)\b[^.\n]*?\b(?:to\s+)?1\b",
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
        return None
    clk, rst = _classify_clk_reset(ins)
    if not clk or not rst:
        return None

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

    return None


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
