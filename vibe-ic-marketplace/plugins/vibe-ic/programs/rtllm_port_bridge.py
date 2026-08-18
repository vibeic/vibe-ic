#!/usr/bin/env python3
"""rtllm_port_bridge.py — a GENERAL prose-port-block reader for the RTLLM benchmark
family (and any spec that states its interface in the same "Input ports:/Output
ports:" prose form), bridging it to the bullet form `port_parser.parse_ports`
already reads.

WHY: the shared `port_parser.parse_ports` understands two interface forms — the
VerilogEval-v2 bullet (` - input a (8 bits)`) and the VerilogEval-human module
header (`module TopModule ( input [7:0] a, ... );`). RTLLM states its interface in
a THIRD, equally-regular prose form:

    Input ports:
        a [7:0]: 8-bit input operand A.       <- explicit [hi:lo] after the name
        cin: Carry-in input.                  <- no width token  -> implicit 1-bit
        data_in: 8-bit input data ...         <- width from a "N-bit" description token
    Output ports:
        sum [7:0]: 8-bit output ...
        cout: Carry-out output.

Because `parse_ports` returned ([],[]) on every RTLLM prompt, every registry
deterministic solver SKIPped RTLLM. This module reads the RTLLM prose form and
re-emits it as the bullet form, so `bridge_prompt(text)` can be fed straight into
the existing solver chain (registry.generate / *_synth.synth) WITHOUT touching any
existing file — the solvers keep seeing the full original prose for their body
semantics; they additionally now see a leading bullet port block they can parse.

This is a GENERAL FORMAT READER, not keyed to any RTLLM design name:
  * It keys ONLY on the literal section headers "Input ports" / "Output ports"
    (ASCII colon ':' OR full-width '：' — RTLLM has both), never on a module name.
  * Width is read from the explicit `[hi:lo]` bus range, else from a width token
    in the SAME line's description ("8-bit", "8 bit", "One-bit", "single bit",
    "1-bit"), else defaulted to 1 ONLY when the line carries no range and no
    competing/contradictory width token. ANY ambiguity (a port line that names a
    width range we cannot reduce to a single integer, or two contradictory width
    tokens) drops THAT port — a dropped port makes the downstream solver SKIP,
    which is the §4.05-conservative behavior we want (never fabricate a width).
  * It NEVER reads a golden/reference solution: input is the prompt text only.

Pure-function module. chip-AGNOSTIC, deterministic.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Section header that opens a port block. ASCII ':' or CJK full-width '：'.
_SEC_RE = re.compile(r"^\s*(Input|Output)\s+ports?\s*[:：]", re.I)
# A line that opens SOME OTHER labelled section (ends a port block). We accept a
# small open-ended set: any "Word(s):" heading at column-0-ish that is NOT a port
# header. Examples seen: Implementation:, Function:, Parameter:, Memory Array:,
# Initial Block:, Behavior:, Module name:.
_OTHER_SEC_RE = re.compile(r"^\s*[A-Z][A-Za-z][A-Za-z ./-]{0,30}\s*[:：]\s*$")
# An explicit bus range `[hi:lo]` (optionally spaced) immediately introducing width.
_RANGE_RE = re.compile(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]")
# A width token inside the description: "8-bit", "8 bit", "16-bit", "1 bit".
_NBIT_RE = re.compile(r"\b(\d+)\s*-?\s*bits?\b", re.I)
# Spelled single-bit cues -> width 1 (do NOT let these be read as a multi-bit token).
_ONEBIT_RE = re.compile(r"\b(one|single)\s*-?\s*bit\b", re.I)
# A port line: leading whitespace, a Verilog identifier, optional range, then ':'.
#   name [hi:lo]: desc     |     name: desc
_PORT_LINE_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*(\[\s*\d+\s*:\s*\d+\s*\])?\s*[:：](.*)$")


# Sentinel: the description carries a width token, but it is AMBIGUOUS (contradictory
# tokens). Distinct from None, which means "no width token at all" (-> implicit 1-bit).
_AMBIGUOUS = object()


def _width_from_desc(desc: str):
    """Width inferred from a description's width token.

    Returns: an int width when a SINGLE unambiguous token is present; None when NO
    width token is present (the caller defaults to implicit 1-bit); the _AMBIGUOUS
    sentinel when ≥2 contradictory tokens are present (the caller DROPs the port so
    the downstream solver SKIPs — never a guessed width).
    """
    if _ONEBIT_RE.search(desc):
        # "One-bit"/"single-bit" -> 1, but only if no contradicting multi-bit token.
        nbits = {int(m.group(1)) for m in _NBIT_RE.finditer(desc)}
        if nbits and nbits != {1}:
            return _AMBIGUOUS  # contradictory (e.g. "single 8-bit") -> drop
        return 1
    nbits = {int(m.group(1)) for m in _NBIT_RE.finditer(desc)}
    if not nbits:
        return None          # no token -> implicit 1-bit
    if len(nbits) > 1:
        return _AMBIGUOUS    # two different widths in one line -> drop
    return next(iter(nbits))


def _section_blocks(text: str) -> List[Tuple[str, List[str]]]:
    """Slice the prompt into (direction, [port-lines]) blocks. A block runs from an
    "Input/Output ports:" header to the next port header OR other labelled section
    OR a blank line that is followed by a non-indented other-section/EOF."""
    lines = text.splitlines()
    blocks: List[Tuple[str, List[str]]] = []
    i = 0
    n = len(lines)
    while i < n:
        sm = _SEC_RE.match(lines[i])
        if not sm:
            i += 1
            continue
        direction = "input" if sm.group(1).lower() == "input" else "output"
        i += 1
        body: List[str] = []
        while i < n:
            ln = lines[i]
            if _SEC_RE.match(ln):           # next port header -> stop (re-enter loop)
                break
            if _OTHER_SEC_RE.match(ln):     # a different labelled section -> stop
                break
            if ln.strip() == "":
                # A blank line ends the block only if what follows is NOT another
                # indented continuation/port line (RTLLM occasionally blank-separates).
                j = i + 1
                while j < n and lines[j].strip() == "":
                    j += 1
                if j >= n or _SEC_RE.match(lines[j]) or _OTHER_SEC_RE.match(lines[j]):
                    break
                # otherwise a stray blank inside the block: skip it
                i += 1
                continue
            body.append(ln)
            i += 1
        blocks.append((direction, body))
    return blocks


def parse_rtllm_ports(text: str) -> Tuple[List[Tuple[str, int]], List[Tuple[str, int]]]:
    """(ins, outs) as [(name, width)] read from the RTLLM prose port block.

    A port line whose width cannot be reduced to a single integer is DROPPED (so
    the downstream solver SKIPs rather than guessing). Returns ([],[]) when no
    "Input/Output ports:" block is present at all.
    """
    ins: List[Tuple[str, int]] = []
    outs: List[Tuple[str, int]] = []
    for direction, body in _section_blocks(text):
        for ln in body:
            pm = _PORT_LINE_RE.match(ln)
            if not pm:
                continue
            name, rng, desc = pm.group(1), pm.group(2), pm.group(3)
            # A leaf line whose "identifier" is actually a prose word followed by a
            # colon (e.g. "Note: ...") would be caught here — but inside a port block
            # such lines are rare; we still keep it only if it parses to a width.
            width: Optional[int]
            if rng:
                rm = _RANGE_RE.search(rng)
                hi, lo = int(rm.group(1)), int(rm.group(2))
                width = abs(hi - lo) + 1
                # A description width token, if present, must AGREE; else ambiguous.
                dw = _width_from_desc(desc)
                if dw is _AMBIGUOUS:
                    continue  # contradictory desc tokens -> drop
                if dw is not None and dw != width:
                    continue  # range vs desc disagree -> drop (ambiguous)
            else:
                dw = _width_from_desc(desc)
                if dw is _AMBIGUOUS:
                    continue  # contradictory desc tokens, no range -> drop
                width = dw if dw is not None else 1
            (ins if direction == "input" else outs).append((name, width))
    return ins, outs


def _emit_bullets(ins, outs) -> str:
    out_lines = []
    for name, w in ins:
        out_lines.append(f" - input {name} ({w} bits)" if w != 1 else f" - input {name}")
    for name, w in outs:
        out_lines.append(f" - output {name} ({w} bits)" if w != 1 else f" - output {name}")
    return "\n".join(out_lines)


def bridge_prompt(text: str) -> str:
    """Return `text` with an equivalent VerilogEval bullet port block PREPENDED, so
    the existing `port_parser.parse_ports` (bullet form) reads the interface while
    every solver still sees the full original prose for its body semantics.

    If no RTLLM port block is found, returns `text` unchanged (a no-op bridge — the
    solver chain then behaves exactly as before)."""
    ins, outs = parse_rtllm_ports(text)
    if not ins and not outs:
        return text
    return _emit_bullets(ins, outs) + "\n\n" + text


def main(argv=None) -> int:
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="RTLLM-style prompt text file")
    ap.add_argument("--emit-bridged", action="store_true",
                    help="print the bridged prompt (bullets + original) instead of the port JSON")
    a = ap.parse_args(argv)
    text = Path(a.prompt).read_text(errors="replace")
    if a.emit_bridged:
        print(bridge_prompt(text))
        return 0
    ins, outs = parse_rtllm_ports(text)
    print(json.dumps({"inputs": [{"name": n, "width": w} for n, w in ins],
                      "outputs": [{"name": n, "width": w} for n, w in outs]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
