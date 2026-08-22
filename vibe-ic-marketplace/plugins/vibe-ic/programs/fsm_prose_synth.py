#!/usr/bin/env python3
"""fsm_prose_synth.py — deterministic SOLVER for the COMBINATIONAL one-hot
FSM-DECODE subset of the prose/tabular FSM family that full_moore_fsm_synth.py
does NOT cover.

WHY (§4.2 absorption, "bucket-② -> bucket-①" / spec-extraction completeness):
full_moore_fsm_synth.py solves the *sequential* Moore FSM (clk + reset + a state
register it OWNS, so the internal encoding is FREE because the TB observes only the
output). It deliberately SKIPs a DIFFERENT mechanically-complete shape that appears
in VerilogEval: the "implement only the state-transition logic and output logic (the
combinational portion) by inspection assuming a one-hot encoding" problem
(Prob079_fsm3onehot, Prob143_fsm_onehot). There:

  * the module has NO clk/reset and NO state register — the FSM's `state` is a
    PRIMARY INPUT (the TB drives it directly), and the module is PURE COMBINATIONAL;
  * the encoding is therefore NOT free — the prompt PINS an explicit one-hot map
    (A=...0001, B=...0010, ...), and the TB compares `next_state` bit-exactly, so a
    re-encoded machine would FAIL. We must honour the stated one-hot mapping;
  * the answer is, by construction, a set of OR-of-AND equations: `next_state[j]` is
    the OR over every (state_i, input-value) arc whose target is state j, ANDed with
    that input value; each Moore output is the OR over the states that assert it.

Given a COMPLETE transition table + the explicit one-hot mapping + the combinational
`state[N] -> next_state[N]` interface, the whole module is a FREE FORMULA — program-
GENERATED, zero authoring variance. That is the gap this solver closes.

NON-OVERLAP with full_moore_fsm_synth.py (READ it first):
  * that solver REQUIRES a clk and a reset port and emits a state REGISTER; this one
    REQUIRES the combinational `state`(input)/`next_state`(output) port pair and emits
    NO register. The two firing predicates are mutually exclusive — a prompt is either
    sequential-with-register (its job) or combinational-one-hot-decode (ours), never
    both. We share port_parser.parse_ports and mirror its §4.05 SKIP discipline.

§4.05 NO-LEAK — returns None (SKIP, author untouched) on ANY ambiguity:
  * not the combinational decode shape (must have a 1-bit `in*`, a `state` input of
    width N>=2, and a `next_state` output of the SAME width N);
  * the table is not complete (every state needs BOTH in=0 and in=1 arcs, all targets
    known, no conflicting duplicate arc);
  * fewer states than the one-hot width, or a state with no bit index;
  * the explicit one-hot mapping is absent, inconsistent, or not a clean power-of-two
    one-hot covering exactly the N states (we NEVER guess the encoding — that is the
    load-bearing fact the TB pins);
  * the Moore output annotations are inconsistent, or the number of annotated outputs
    does not equal the number of 1-bit module outputs;
  * the governing input is not a single 1-bit input (a multi-bit / multi-input decode
    is a different, non-1-bit-arc shape -> SKIP).
  Free-prose BEHAVIOURAL FSMs (the Lemmings critters, PS/2 framing, serial start/stop,
  HDLC bit-stuffing, the 1-0-1 / two-of-three counting FSMs) have NO complete table —
  they require genuine language understanding, so they MUST SKIP. Emitting a guess
  there would be a leak; honesty about that AI-floor is REQUIRED.

API: synth(prompt_text, top="TopModule") -> RTL string | None
"""
from __future__ import annotations
import re


def _parse_ports(prompt):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser   # bullet form OR Verilog module header (the v2/human twins)
    return port_parser.parse_ports(prompt)


def _parse_decode_table(prompt, n_outputs):
    """Return (states, trans, souts) from a COMPLETE one-hot decode table, else None.

    `trans[s]` is {"0": next_on_in0, "1": next_on_in1}; `souts[s]` is the tuple of
    per-state Moore output bits (length == n_outputs), default all-zero unless the
    state is annotated. Two written forms are accepted, mirroring the sibling solver:

      (a) arrow, K-tuple output:  `S8 (1, 0) --0--> S0`   (Prob143; K outputs in order)
      (b) tabular:                `A | A, B | 0`           (Prob079; single output col)

    SKIPs (returns None) on any conflict / incompleteness / inconsistent annotation.
    """
    trans, souts, states = {}, {}, []

    # (a) arrow with a parenthesised K-tuple of 0/1 outputs.
    #   `S8 (1, 0) --0--> S0`  /  `A (0) --1--> B`
    arrow_re = re.compile(
        r"^\s*(\w+)\s*\(\s*([01](?:\s*,\s*[01])*)\s*\)\s*--\s*([01])\s*-->\s*(\w+)",
        re.M)
    saw_arrow = False
    for m in arrow_re.finditer(prompt):
        saw_arrow = True
        s, otxt, i, nx = m.groups()
        obits = tuple(int(b) for b in re.split(r"\s*,\s*", otxt.strip()))
        if len(obits) != n_outputs:          # output arity must match the module
            return None
        if s not in states:
            states.append(s)
        _d = trans.setdefault(s, {})
        if i in _d and _d[i] != nx:          # conflicting duplicate arc -> SKIP
            return None
        _d[i] = nx
        if s in souts and souts[s] != obits:  # inconsistent per-state output -> SKIP
            return None
        souts[s] = obits

    # (b) tabular `state | next0, next1 | output` (single output column only).
    if not saw_arrow:
        if n_outputs != 1:                    # tabular form encodes ONE output column
            return None
        for m in re.finditer(
                r"^\s*(\w+)\s*\|\s*(\w+)\s*,\s*(\w+)\s*\|\s*([01])\s*$", prompt, re.M):
            s, n0, n1, o = m.groups()
            if s.lower() == "state":          # header row
                continue
            if s in trans:                    # duplicate row -> SKIP
                return None
            states.append(s)
            trans[s] = {"0": n0, "1": n1}
            souts[s] = (int(o),)

    if len(states) < 2:
        return None
    known = set(states)
    for s in states:
        if set(trans.get(s, {}).keys()) != {"0", "1"}:   # incomplete -> SKIP
            return None
        if any(nx not in known for nx in trans[s].values()):
            return None
    return states, trans, souts


def _parse_onehot_map(prompt, states):
    """Return {state_name: bit_index} from the EXPLICIT one-hot encoding, else None.

    The encoding is the load-bearing fact the TB pins, so we never guess it. Two
    explicit forms are recognised:

      (a) per-state literal assignment, e.g.
          `A=4'b0001, B=4'b0010, C=4'b0100, D=4'b1000` (Prob079) — each state mapped
          to a one-hot binary literal; the index is the position of the single 1.
      (b) the "state[0] through state[N-1] correspond to the states S0 .. S(N-1),
          respectively" positional form (Prob143) — bit k <-> the k-th listed state.

    Validates that the result is a clean one-hot bijection over EXACTLY the table's
    states (distinct indices, every state covered, indices in 0..N-1). Anything short
    of that -> None (SKIP).
    """
    n = len(states)
    idx = {}

    # (a) per-state binary-literal map: `A=4'b0001` or `A = 0001`.
    lit_re = re.compile(r"\b(\w+)\s*=\s*(?:\d+'b)?([01]{2,})\b")
    for m in lit_re.finditer(prompt):
        s, bits = m.groups()
        if s not in states:
            continue
        if bits.count("1") != 1:             # not one-hot -> reject this map
            continue
        # bit string is MSB-first; index = position of the lone 1 from the LSB.
        k = len(bits) - 1 - bits.index("1")
        if s in idx and idx[s] != k:
            return None
        idx[s] = k
    if len(idx) == n and len(set(idx.values())) == n and set(idx.values()) == set(range(n)):
        return idx

    # (b) positional: "state[0] through state[N-1] correspond to the states S0
    #     through S(N-1), respectively" — bit k is the k-th state in listed order.
    if re.search(
            r"state\s*\[\s*0\s*\].{0,80}?correspond\w*\s+to\s+the\s+states?",
            prompt, re.I | re.S):
        # Require the listed-state order to match our table order AND span 0..N-1.
        # The table's discovery order IS the listing order (we appended states as the
        # arcs/rows were read top-to-bottom), and the prompt asserts state[k] <-> the
        # k-th state, so the positional index is simply the table position.
        # Guard: the prompt must actually NAME the first and last state at the right
        # ends so we are not mis-reading a different correspondence sentence.
        first, last = states[0], states[-1]
        if re.search(rf"correspond\w*\s+to\s+the\s+states?\s+{re.escape(first)}\b",
                     prompt, re.I) and re.search(
                rf"{re.escape(last)}\b", prompt):
            return {s: k for k, s in enumerate(states)}

    return None


def synth(prompt_text: str, top: str = "TopModule"):
    ins, outs = _parse_ports(prompt_text)
    if not ins or not outs:
        return None

    # --- combinational one-hot decode interface: state(input) / next_state(output) ---
    state_in = next(((n, w) for n, w in ins if n.lower() == "state"), None)
    nstate_out = next(((n, w) for n, w in outs if n.lower() == "next_state"), None)
    if state_in is None or nstate_out is None:
        return None                          # not the decode shape -> SKIP
    n_bits = state_in[1]
    if n_bits < 2 or nstate_out[1] != n_bits:
        return None                          # state / next_state width must match, >=2

    # Mutual-exclusion with full_moore_fsm_synth.py: that solver fires on a SEQUENTIAL
    # machine (it REQUIRES clk + reset and emits a register). The combinational decode
    # has neither; if a clk OR reset port is present this is NOT our shape -> SKIP and
    # leave it to the sequential solver / the AI floor.
    lower_in = [n.lower() for n, _ in ins]
    if any(n in ("clk", "clock") for n in lower_in):
        return None
    if any("reset" in n or n in ("rst", "rst_n", "arst", "areset", "resetn")
           for n in lower_in):
        return None

    # the governing input is the single 1-bit input that is NOT `state`.
    one_bit_ins = [n for n, w in ins if w == 1 and n.lower() != "state"]
    if len(one_bit_ins) != 1:
        return None                          # exactly one 1-bit arc input
    in_name = one_bit_ins[0]
    # no OTHER multi-bit input may exist (it would be silently dropped from the decode).
    if any(w != 1 and n.lower() != "state" for n, w in ins):
        return None

    # Moore outputs = every 1-bit output that is NOT next_state. The table annotation
    # arity must equal this count.
    mo_outs = [n for n, w in outs if w == 1 and n.lower() != "next_state"]
    if any(w != 1 and n.lower() != "next_state" for n, w in outs):
        return None                          # an extra multi-bit non-next_state output

    parsed = _parse_decode_table(prompt_text, len(mo_outs))
    if parsed is None:
        return None
    states, trans, souts = parsed
    if len(states) != n_bits:                # one state per one-hot bit, exactly
        return None

    idx = _parse_onehot_map(prompt_text, states)
    if idx is None:
        return None

    # --- emit (free formula, pinned by the explicit one-hot map) ---
    # next_state[j] = OR over (state s, input value v) with trans[s][v] == state_j,
    #                 ANDed with the input being v.
    def in_term(v):
        return in_name if v == "1" else f"!{in_name}"

    next_terms = {j: [] for j in range(n_bits)}
    for s in states:
        for v in ("0", "1"):
            tgt = trans[s][v]
            j = idx[tgt]
            next_terms[j].append(f"({state_in[0]}[{idx[s]}] & {in_term(v)})")

    # output K = OR over states whose annotation bit K is 1.
    out_terms = {k: [] for k in range(len(mo_outs))}
    for s in states:
        for k in range(len(mo_outs)):
            if souts[s][k]:
                out_terms[k].append(f"{state_in[0]}[{idx[s]}]")

    port_lines = [f"input {n}" for n, _ in ins if n.lower() != "state"]
    port_lines.append(f"input [{n_bits-1}:0] {state_in[0]}")
    port_lines += [f"output [{n_bits-1}:0] {nstate_out[0]}"]
    port_lines += [f"output {n}" for n in mo_outs]

    lines = [
        "// program-SOLVED combinational one-hot FSM decode (encoding pinned by the",
        "// stated one-hot map); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join(port_lines),
        ");",
    ]
    for j in range(n_bits):
        rhs = " | ".join(next_terms[j]) if next_terms[j] else "1'b0"
        lines.append(f"    assign {nstate_out[0]}[{j}] = {rhs};")
    for k, on in enumerate(mo_outs):
        rhs = " | ".join(out_terms[k]) if out_terms[k] else "1'b0"
        lines.append(f"    assign {on} = {rhs};")
    lines += ["endmodule", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    from pathlib import Path
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a combinational one-hot FSM decode", file=sys.stderr)
        sys.exit(1)
    print(rtl)
