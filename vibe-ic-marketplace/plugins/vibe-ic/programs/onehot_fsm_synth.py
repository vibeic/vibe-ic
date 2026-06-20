#!/usr/bin/env python3
"""onehot_fsm_synth.py — DETERMINISTIC one-hot FSM next-state/output synthesizer
(v1.1.38 clean-room §4.2 absorption).

THE GAP THIS CLOSES
-------------------
The VerilogEval one-hot-FSM "derive next-state logic by inspection" prompts
(Prob150_review2015_fsmonehot) give EVERYTHING deterministically: the one-hot
encoding (state→bit index) is written out in the prompt, the state-transition
table is listed line by line, and each state's asserted Moore outputs are
annotated. For a one-hot encoding the next-state equation is mechanical —
``X_next = OR over every edge into X of (state[from] & condition)`` — and the
Moore outputs are ``OR of state[bit]`` over the asserting states. No oracle, no
judgement. Yet a blind author hand-derives it and flips a bit-ordering or an edge
per round (single-shot variance). Per open-benchmark-methodology §4.2 a GENERAL
no-cheat recovery MUST be absorbed as a PROGRAM. This is that absorption.

§4.05 NO-LEAK
-------------
Fires ONLY when the prompt carries (a) an explicit one-hot encoding tuple mapping
named states to bit indices, (b) a parseable ``<state> (out) --<cond>--> <next>``
transition table, and (c) the requested ``*_next`` / Moore output ports — every
piece read from the prompt itself. SKIPs (emits nothing) on any unparseable piece,
so it can never ship a guess.

USAGE
-----
    python3 onehot_fsm_synth.py --prompt <prompt.txt> --top TopModule [--out s.sv]

EXIT CODES
----------
    0  synthesized + emitted    2  SKIP (outside the envelope)

chip-AGNOSTIC: pure boolean synthesis from the prompt's own table/encoding.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import waveform_truth_table_synth as _wsynth  # noqa: E402

parse_ports = _wsynth.parse_ports

# `<state> (outputs) --<cond>--> <next>`  (the `(outputs)` group may be empty `()`)
_TRANS = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*\(([^)]*)\)\s*--\s*(.+?)\s*-->\s*([A-Za-z_]\w*)\s*$")
# the encoding tuple: `(S, S1, ...) = (10'b...1, 10'b...10, ...)`
_ENC_NAMES = re.compile(r"\(\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*\)\s*=")


def _state_index(prompt: str) -> Optional[Dict[str, int]]:
    """Map state-name -> one-hot bit index from the explicit encoding tuple."""
    m = _ENC_NAMES.search(prompt)
    if not m:
        return None
    names = [n.strip() for n in m.group(1).split(",")]
    if len(names) < 2:
        return None
    return {n: i for i, n in enumerate(names)}


def _cond_expr(cond: str) -> Optional[str]:
    """Translate a transition condition to a Verilog expression over the inputs.
    `d=0`->~d, `done_counting=1`->done_counting, `(always …)`/unconditional->''."""
    c = cond.strip().strip("()").strip()
    if not c or "always" in c.lower():
        return ""  # unconditional
    # comma/space separated equalities: sig=0 / sig=1
    lits = []
    for part in re.split(r"[,\s]+", c):
        mm = re.fullmatch(r"([A-Za-z_]\w*)=([01])", part)
        if not mm:
            return None
        sig, val = mm.group(1), mm.group(2)
        lits.append(sig if val == "1" else f"~{sig}")
    return " & ".join(lits)


def synth(prompt: str, top: str = "TopModule") -> Optional[str]:
    low = prompt.lower()
    if "one-hot" not in low and "one hot" not in low:
        return None
    ports = parse_ports(prompt)
    if not ports:
        return None
    idx = _state_index(prompt)
    if not idx:
        return None
    # parse transitions + per-state asserted outputs
    edges: List[Tuple[str, str, str]] = []   # (from, cond_expr, to)
    asserts: Dict[str, List[str]] = {}       # output-name -> [state names]
    for ln in prompt.splitlines():
        m = _TRANS.match(ln)
        if not m:
            # A line that is CLEARLY a transition FROM an encoded state (its first
            # token is a state name, and it carries the `-->` arrow) but does not
            # fully parse (e.g. a missing `(out)` group) would otherwise be
            # silently skipped, DROPPING that edge and emitting an INCOMPLETE
            # next-state equation (a wrong function that still compiles). The
            # docstring promises SKIP-on-any-unparseable-piece; honor it — a
            # malformed transition row makes the whole table untrustworthy → SKIP.
            # The `first token in idx` qualifier excludes the legend/header line
            # (e.g. `state (output) --input--> next state`), whose first token is
            # not an encoded state. (Step-2.7 §4.05: never EMIT over a partial parse.)
            toks = ln.split()
            if "-->" in ln and toks and toks[0] in idx:
                return None
            continue
        frm, outs, cond, to = m.group(1), m.group(2), m.group(3), m.group(4)
        if frm not in idx or to not in idx:
            return None  # a state not in the encoding -> SKIP (unparseable)
        ce = _cond_expr(cond)
        if ce is None:
            return None
        edges.append((frm, ce, to))
        for o in re.findall(r"([A-Za-z_]\w*)\s*=\s*1", outs):
            asserts.setdefault(o, [])
            if frm not in asserts[o]:
                asserts[o].append(frm)
    if not edges:
        return None
    # The emit references `state[<bit>]`, so `state` MUST be a declared input port
    # WIDE ENOUGH for the highest one-hot index — else the RTL references an
    # undeclared signal (caught only by the downstream compiler) or an
    # out-of-range bit-select that silently evaluates 1'bx (wrong + compiles).
    # Validate structurally and SKIP otherwise. (Step-2.7 §4.05.)
    st = ports.get("state")
    if not st or st[0] != "input" or st[1] <= max(idx.values()):
        return None

    def term(frm: str, ce: str) -> str:
        s = f"state[{idx[frm]}]"
        return f"{s} & {ce}" if ce else s

    assigns = []
    out_ports = [ports[n][2] for n, v in ports.items() if v[0] == "output"]
    for op in out_ports:
        # next-state output: `X_next` asserts when next-state is X
        mn = re.fullmatch(r"(.+?)_next", op, re.IGNORECASE)
        if mn:
            stname = None
            # match the state name case-insensitively against the encoding
            for nm in idx:
                if nm.lower() == mn.group(1).lower():
                    stname = nm
                    break
            if stname is None:
                return None
            terms = [term(f, ce) for (f, ce, t) in edges if t == stname]
            rhs = " | ".join(terms) if terms else "1'b0"
            assigns.append(f"  assign {op} = {rhs};")
        else:
            # Moore output: OR of state[bit] over asserting states
            st = None
            for nm in asserts:
                if nm.lower() == op.lower():
                    st = asserts[nm]
                    break
            if st is None:
                assigns.append(f"  assign {op} = 1'b0;")
            else:
                assigns.append("  assign " + op + " = " +
                               " | ".join(f"state[{idx[s]}]" for s in st) + ";")
    # emit — original-case (testbench-facing) port names
    decl = []
    for nm, (d, w, orig) in ports.items():
        rng = f"[{w-1}:0] " if w > 1 else ""
        decl.append(f"    {d:<6} {rng}{orig}")
    return (f"module {top} (\n" + ",\n".join(decl) + "\n);\n\n"
            + "\n".join(assigns) + "\nendmodule\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: outside the one-hot-FSM synth envelope", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
