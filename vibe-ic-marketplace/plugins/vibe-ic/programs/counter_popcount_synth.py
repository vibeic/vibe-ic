#!/usr/bin/env python3
"""counter_popcount_synth.py — deterministic SOLVER for the counter / popcount /
parity-reduction family (bucket-② spec -> bucket-① RTL, blind).

Three STATED-structure shapes are fully determined by the prompt, so they can be
EMITTED deterministically without any model judgment:

  (a) POPCOUNT  — "population count" / "counts the number of '1's" over an N-bit
        input bus, combinational `out = sum(in[i])`. The output width must be
        STATED and wide enough to hold 0..N (>= ceil(log2(N+1))); else SKIP.
        e.g. Prob009_popcount3 (in[2:0] -> out[1:0]), Prob030_popcount255
        (in[254:0] -> out[7:0]).

  (b) PARITY / REDUCTION-XOR — a single 1-bit `parity`/`out` that is the XOR
        (EVEN parity, `^in`) or XNOR (ODD parity, `~^in`) of every bit of one
        input bus. The even-vs-odd SENSE must be STATED; else SKIP.
        e.g. Prob025_reduction (even parity of an 8-bit byte).

  (c) MODULO-N UP COUNTER — a clocked register `q` that counts START..END
        inclusive then wraps to START, with a STATED synchronous active-high
        reset (to a STATED reset value) and an OPTIONAL single count-enable.
        The modulus (count range / period) AND reset value AND direction (up)
        must all be UNAMBIGUOUSLY stated; else SKIP.
        e.g. Prob038_count15 (0..15), Prob040_count10 (0..9), Prob035_count1to10
        (1..10 reset->1), Prob037_review2015_count1k (0..999), Prob067_countslow
        (0..9 with slowena enable).

This is the EMITTER. parametric_spec_extractor may hold counter FACTS; this
module turns the stated structure into RTL. It REUSES port_parser.parse_ports
(bullet form OR Verilog module header — the VerilogEval v2/human twins).

§4.05 NO-LEAK: any ambiguity -> return None (SKIP). The emitter never guesses a
width, a modulus, a reset value, a count direction, or a parity sense that the
prompt did not state. General / chip-agnostic — keys on STATED structure only,
never on problem names.

API: synth(prompt_text, top="TopModule") -> str | None  +  __main__
"""
from __future__ import annotations

import math
import os
import re
import sys


def _parse_ports(prompt):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser  # bullet form OR Verilog module header (v2/human twins)
    return port_parser.parse_ports(prompt)


def _emit(top, ports_decl, body):
    return (
        f"module {top} (\n"
        + ",\n".join("  " + p for p in ports_decl)
        + "\n);\n\n"
        + body
        + "\nendmodule\n"
    )


# ---------------------------------------------------------------------------
# (a) population count
# ---------------------------------------------------------------------------
def _try_popcount(prompt, ins, outs, top):
    # STATED structure: a "population count" / "number of 1s" circuit.
    if not re.search(
        r"population\s+count|number\s+of\s+['\"`]?1['\"`]?s|count(?:s|ing)?\s+"
        r"the\s+number\s+of\s+(?:set\s+)?(?:bits|ones)",
        prompt, re.I,
    ):
        return None
    # exactly one input bus and exactly one output -> unambiguous mapping.
    if len(ins) != 1 or len(outs) != 1:
        return None
    in_name, in_w = ins[0]
    out_name, out_w = outs[0]
    if in_w < 1 or out_w < 1:
        return None
    # output must be able to hold 0..N (N = in_w). Required width = bits to hold N.
    need = max(1, math.ceil(math.log2(in_w + 1)))
    if out_w < need:
        return None  # stated width can't represent the max count -> SKIP (don't guess)
    in_decl = f"input [{in_w-1}:0] {in_name}" if in_w > 1 else f"input {in_name}"
    out_decl = (
        f"output reg [{out_w-1}:0] {out_name}" if out_w > 1
        else f"output reg {out_name}"
    )
    if in_w == 1:
        body = f"  always @(*) {out_name} = {in_name};\n"
    else:
        body = (
            "  integer i;\n"
            "  always @(*) begin\n"
            f"    {out_name} = 0;\n"
            f"    for (i = 0; i < {in_w}; i = i + 1)\n"
            f"      {out_name} = {out_name} + {in_name}[i];\n"
            "  end\n"
        )
    return _emit(top, [in_decl, out_decl], body)


# ---------------------------------------------------------------------------
# (b) parity / reduction XOR
# ---------------------------------------------------------------------------
def _try_parity(prompt, ins, outs, top):
    if not re.search(r"parity|reduction|XOR\s+of\s+all|exclusive[- ]or\s+of\s+all",
                     prompt, re.I):
        return None
    # exactly one input bus, exactly one 1-bit output.
    if len(ins) != 1 or len(outs) != 1:
        return None
    in_name, in_w = ins[0]
    out_name, out_w = outs[0]
    if out_w != 1 or in_w < 1:
        return None
    # even-vs-odd SENSE must be unambiguously stated.
    has_even = bool(re.search(r"\beven\b", prompt, re.I))
    has_odd = bool(re.search(r"\bodd\b", prompt, re.I))
    if has_even and not has_odd:
        op = "^"          # even parity == XOR of all bits
    elif has_odd and not has_even:
        op = "~^"         # odd parity == XNOR of all bits
    elif not has_even and not has_odd:
        # No even/odd word: only safe if the prompt LITERALLY says it is the XOR
        # of all the data bits (== even parity). Any "reduction" without the
        # operator named is ambiguous (could be AND/OR/XOR) -> SKIP.
        if re.search(r"\bXOR\b\s+of\s+all|\^\s*{?\s*" + re.escape(in_name),
                     prompt, re.I):
            op = "^"
        else:
            return None
    else:
        return None       # both "even" and "odd" present -> ambiguous -> SKIP
    in_decl = f"input [{in_w-1}:0] {in_name}" if in_w > 1 else f"input {in_name}"
    out_decl = f"output {out_name}"
    body = f"  assign {out_name} = {op}{in_name};\n"
    return _emit(top, [in_decl, out_decl], body)


# ---------------------------------------------------------------------------
# (c) modulo-N up counter
# ---------------------------------------------------------------------------
_NUM = r"(\d[\d,]*)"


def _i(s):
    return int(s.replace(",", ""))


def _try_counter(prompt, ins, outs, top):
    low = prompt.lower()
    if "counter" not in low and "counts" not in low and "count " not in low:
        return None
    # Direction must be UP. Any down/decrement language -> not this shape -> SKIP.
    if re.search(r"down[- ]?counter|counts?\s+down|decrement|count\s+down", low):
        return None
    # Things that are NOT a plain modulo-N up counter (other shapes) -> SKIP.
    if re.search(r"\bbcd\b|saturat|terminal\s+count|am/pm|12-hour|clock\b.*hours|"
                 r"hours|minutes|seconds|load\b|timer", low):
        return None
    # exactly one clocked output bus.
    if len(outs) != 1:
        return None
    q_name, q_w = outs[0]
    if q_w < 1:
        return None
    in_names = [n for n, _ in ins]
    in_low = [n.lower() for n in in_names]
    clk = next((n for n, l in zip(in_names, in_low) if l in ("clk", "clock")), None)
    if clk is None:
        return None
    # reset: synchronous active-high is the ONLY supported reset here. An
    # asynchronous reset (areset) would need different RTL -> SKIP.
    rst = next((n for n, l in zip(in_names, in_low) if l in ("reset", "rst")), None)
    if rst is None:
        return None
    if re.search(r"\basync|asynchronous|areset|negedge\s+reset", low):
        return None
    if not re.search(r"synchronous", low) or not re.search(
            r"active\s+high|active-high", low):
        return None  # reset polarity / sync-ness not unambiguously stated -> SKIP

    # optional single count-enable: any 1-bit input that is neither clk nor reset.
    enables = [(n, w) for (n, w) in ins
               if n != clk and n != rst]
    if len(enables) > 1:
        return None  # more than one extra control -> ambiguous -> SKIP
    ena = None
    if enables:
        en_name, en_w = enables[0]
        if en_w != 1:
            return None
        # the prompt must describe it as an increment-enable / pause control.
        if not re.search(
                re.escape(en_name) + r"[^.]{0,120}?(increment|count|enable|pause)|"
                r"(increment|count|enable|pause)[^.]{0,120}?" + re.escape(en_name),
                prompt, re.I | re.S):
            return None
        ena = en_name

    # ---- modulus + reset value, from STATED range/period ----
    start = end = reset_val = None
    # "counts from A through/to B" / "counts A through B"
    m = re.search(r"counts?\s+(?:from\s+)?" + _NUM +
                  r"\s+(?:through|to|up\s+to|thru)\s+" + _NUM, low)
    if m:
        start, end = _i(m.group(1)), _i(m.group(2))
    if start is None:
        # "<W>-bit binary counter ... period of P" without an explicit range:
        # only the canonical 0..(2^W-1) full-range counter is unambiguous.
        mp = re.search(r"period\s+of\s+" + _NUM, low)
        if mp and re.search(r"binary\s+counter", low):
            period = _i(mp.group(1))
            if period == (1 << q_w):
                start, end = 0, period - 1
    if start is None or end is None:
        return None
    if end <= start:
        return None

    # cross-check an explicitly stated period, if present, against the range.
    mp = re.search(r"period\s+of\s+" + _NUM, low)
    if mp:
        period = _i(mp.group(1))
        if period != (end - start + 1):
            return None  # stated period disagrees with stated range -> SKIP

    # reset value must be STATED ("reset the counter to V"). Don't assume.
    mr = re.search(r"reset(?:s|\s+the\s+counter)?\s+to\s+" + _NUM, low)
    if mr:
        reset_val = _i(mr.group(1))
    else:
        return None
    if reset_val < start or reset_val > end:
        return None

    # width must hold 'end'.
    if (1 << q_w) <= end:
        return None

    # ---- emit ----
    ports = [f"input {clk}", f"input {rst}"]
    if ena:
        ports.append(f"input {ena}")
    ports.append(f"output reg [{q_w-1}:0] {q_name}" if q_w > 1
                 else f"output reg {q_name}")

    # wrap when q == end (or reset) -> start; else q+1. reset has top priority.
    inc = f"if ({q_name} == {end})\n        {q_name} <= {start};\n      else\n        {q_name} <= {q_name} + 1;"
    if ena:
        body = (
            f"  always @(posedge {clk}) begin\n"
            f"    if ({rst})\n"
            f"      {q_name} <= {reset_val};\n"
            f"    else if ({ena}) begin\n"
            f"      {inc}\n"
            f"    end\n"
            f"  end\n"
        )
    else:
        # fold reset and wrap into one branch (reset value may differ from start,
        # so keep them separate when they differ).
        if reset_val == start:
            body = (
                f"  always @(posedge {clk}) begin\n"
                f"    if ({rst} || {q_name} == {end})\n"
                f"      {q_name} <= {start};\n"
                f"    else\n"
                f"      {q_name} <= {q_name} + 1;\n"
                f"  end\n"
            )
        else:
            body = (
                f"  always @(posedge {clk}) begin\n"
                f"    if ({rst})\n"
                f"      {q_name} <= {reset_val};\n"
                f"    else if ({q_name} == {end})\n"
                f"      {q_name} <= {start};\n"
                f"    else\n"
                f"      {q_name} <= {q_name} + 1;\n"
                f"  end\n"
            )
    return _emit(top, ports, body)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def synth(prompt_text: str, top: str = "TopModule"):
    """Emit RTL for a popcount / parity-reduction / modulo-N up counter, or
    None (SKIP) on ANY ambiguity. chip-agnostic; keys on STATED structure."""
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        return None
    try:
        ins, outs = _parse_ports(prompt_text)
    except Exception:
        return None
    if not outs:
        return None

    # Try each shape; the prompt structure makes them mutually exclusive in
    # practice (popcount has a multi-bit out, parity a 1-bit out + parity word,
    # counter is clocked). Order popcount -> parity -> counter.
    for fn in (_try_popcount, _try_parity, _try_counter):
        rtl = fn(prompt_text, ins, outs, top)
        if rtl is not None:
            return rtl
    return None


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a determinate counter / popcount / parity prompt",
              file=sys.stderr)
        sys.exit(1)
    print(rtl)
