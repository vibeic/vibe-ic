#!/usr/bin/env python3
"""prose_interface_recover.py — a GENERAL interface recoverer for the RTLLM prose
header DIALECTS that the base prose_port_block_read does not yet read.

prose_port_block_read.parse_rtllm_ports reads the canonical RTLLM form:

    Input ports:
        a [7:0]: 8-bit ...        <- integer-literal range OR a "N-bit" desc token
    Output ports:
        sum [7:0]: ...

A handful of RTLLM prompts state the SAME interface in a regular but DIFFERENT
prose form the base reader returns ([],[]) on. This module recovers those, so the
conformance gate can bind a meaningful interface (the T4->T3 / T3->T2 converge
lever) WITHOUT ever guessing or reading a golden:

  (1) `Inputs:` / `Outputs:` section headers (synonyms of `Input ports:` /
      `Output ports:`). e.g. traffic_light.

  (2) PAREN-DIRECTION port lines `name (input [31:0]): desc` /
      `name (output reg [31:0]): desc` — the direction (and width) is in the
      parenthetical, not a section header. e.g. float_multi. The line's own
      `(input|output)` keyword fixes the direction, so these lines are read
      regardless of which section they sit under.

  (3) PARAMETER-EXPRESSION widths `a [N-1:0]: ...` / `[WIDTH-1:0]` / `[Q-1:0]`.
      The width is parameter-driven (resolved at elaboration by the harness),
      so the port is recovered with width=None — PRESENT but width-unknown. The
      gate then enforces port PRESENCE + direction and NEVER a literal width
      (§4.05: a parameterized port must never be false-rejected for not matching
      a literal). e.g. fixed_point_adder / fixed_point_substractor.

§4.05 / GENERAL:
  * Keys ONLY on the literal header words (Input/Output, with or without "ports")
    and the in-line `(input|output ...)` keyword — never on a design name.
  * A port line whose width token is AMBIGUOUS (two contradictory integer widths)
    is DROPPED (the consumer SKIPs rather than guessing). A parameter-expression
    width is recovered as width=None (present, unknown), never as a guessed int.
  * Reads the PROMPT only; never a golden/reference.

Public API
    recover_ports(text) -> (ins, outs)   each [(name, width|None)]
chip-AGNOSTIC, deterministic, pure-function.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

Port = Tuple[str, Optional[int]]

# Section header: "Input ports:", "Output ports:", OR the bare "Inputs:"/"Outputs:".
_SEC_RE = re.compile(r"^\s*(Input|Output)s?(?:\s+ports?)?\s*[:：]\s*$", re.I)
# Some other labelled section that ENDS a port block (e.g. Implementation:,
# Internal Registers:, Parameters:, Registers and Wires:). A "Word(s):" heading.
_OTHER_SEC_RE = re.compile(r"^\s*[A-Z][A-Za-z][A-Za-z ./-]{0,34}\s*[:：]\s*$")

# An integer-literal range `[hi:lo]`.
_INT_RANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
# A parameter-expression range `[N-1:0]`, `[WIDTH-1:0]`, `[Q-1:0]`, `[N:1]` — any
# range containing a non-pure-digit token. PRESENT but width-unknown.
_PARAM_RANGE_RE = re.compile(r"\[\s*[^\]]*[A-Za-z][^\]]*\s*:\s*[^\]]*\s*\]")
# width token in a description: "8-bit", "16 bit". Single-bit cue -> width 1.
_NBIT_RE = re.compile(r"\b(\d+)\s*-?\s*bits?\b", re.I)
_ONEBIT_RE = re.compile(r"\b(one|single)\s*-?\s*bit\b", re.I)

# A PAREN-DIRECTION port line: `name (input [31:0]): desc` / `name (output reg ...)`.
_PAREN_DIR_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*\(\s*(input|output|inout)\b([^)]*)\)\s*[:：]?(.*)$", re.I)
# A plain port line under a section: `name [range]: desc` / `name: desc`. The range
# may be integer-literal OR parameter-expression OR absent.
_PLAIN_PORT_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*[:：](.*)$")

_AMBIGUOUS = object()


def _width_from_desc(desc: str):
    if _ONEBIT_RE.search(desc):
        nbits = {int(m.group(1)) for m in _NBIT_RE.finditer(desc)}
        if nbits and nbits != {1}:
            return _AMBIGUOUS
        return 1
    nbits = {int(m.group(1)) for m in _NBIT_RE.finditer(desc)}
    if not nbits:
        return None
    if len(nbits) > 1:
        return _AMBIGUOUS
    return next(iter(nbits))


def _width_from_range(rng: Optional[str], desc: str):
    """Width from a `[range]` token (and a corroborating desc token).
    Returns an int, None (present-but-unknown / no token), or _AMBIGUOUS (drop)."""
    if rng:
        mi = _INT_RANGE_RE.search(rng)
        if mi:
            # An EXPLICIT integer `[hi:lo]` range is AUTHORITATIVE — it is the HDL
            # declaration's own width. A width token in the trailing description
            # ("16-bit output ... of two 8-bit inputs") is PROSE that may mention
            # OTHER widths (the operands), so it is NOT a contradiction that drops
            # the port. We trust the range. (The base prose_port_block_read is stricter
            # and drops on range-vs-desc disagreement; this recoverer is the
            # CONVERGE path that recovers the port the range unambiguously gives.)
            return abs(int(mi.group(1)) - int(mi.group(2))) + 1
        if _PARAM_RANGE_RE.search(rng):
            return None  # parameter-expression width: present, unknown
        # a bracket we cannot classify -> ambiguous, drop
        return _AMBIGUOUS
    dw = _width_from_desc(desc)
    if dw is _AMBIGUOUS:
        return _AMBIGUOUS
    return dw if dw is not None else 1


def recover_ports(text: str) -> Tuple[List[Port], List[Port]]:
    """(ins, outs) recovered from the RTLLM header dialects. Each is [(name,width)]
    with width an int, or None for a parameter-expression (present-but-unknown)
    width. A port whose width is AMBIGUOUS is dropped (SKIP-safe)."""
    lines = text.splitlines()
    ins: List[Port] = []
    outs: List[Port] = []
    seen = set()
    cur: Optional[str] = None  # current section direction
    for ln in lines:
        sm = _SEC_RE.match(ln)
        if sm:
            cur = "input" if sm.group(1).lower() == "input" else "output"
            continue
        # a paren-direction line carries its OWN direction (works in any section).
        pm = _PAREN_DIR_RE.match(ln)
        if pm:
            name, d, inside, desc = pm.group(1), pm.group(2).lower(), pm.group(3), pm.group(4)
            if d == "inout":
                continue  # not modelled here
            rng_m = re.search(r"\[[^\]]*\]", inside or "")
            w = _width_from_range(rng_m.group(0) if rng_m else None, (inside or "") + " " + (desc or ""))
            if w is _AMBIGUOUS:
                continue
            key = (d, name)
            if key in seen:
                continue
            seen.add(key)
            (ins if d == "input" else outs).append((name, w))
            continue
        # otherwise, only parse plain port lines INSIDE a known section.
        if cur is None:
            continue
        if _OTHER_SEC_RE.match(ln):
            cur = None
            continue
        if ln.strip() == "":
            continue
        ppm = _PLAIN_PORT_RE.match(ln)
        if not ppm:
            continue
        name, rng, desc = ppm.group(1), ppm.group(2), ppm.group(3)
        w = _width_from_range(rng, desc)
        if w is _AMBIGUOUS:
            continue
        key = (cur, name)
        if key in seen:
            continue
        seen.add(key)
        (ins if cur == "input" else outs).append((name, w))
    return ins, outs


def main(argv=None) -> int:
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    a = ap.parse_args(argv)
    ins, outs = recover_ports(Path(a.prompt).read_text(errors="replace"))
    print(json.dumps({"inputs": [{"name": n, "width": w} for n, w in ins],
                      "outputs": [{"name": n, "width": w} for n, w in outs]},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
