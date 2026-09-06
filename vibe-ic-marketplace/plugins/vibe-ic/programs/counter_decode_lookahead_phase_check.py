#!/usr/bin/env python3
"""counter_decode_lookahead_phase_check.py — a level decoded from the NEXT
counter value, registered on the same edge that advances the counter.

WHY (RTLLM clean-room run 2026-09-06/07, freq_divbyodd + asyn_fifo)
===================================================================
Two designs in one run failed the hidden reference harness for the same
structural reason, in two different subsystems:

    freq_divbyodd   clk_div1 <= (cnt1_next < NUM_DIV/2);  cnt1 <= cnt1_next;
    asyn_fifo       wptr     <= bin2gray(waddr_bin + wen); waddr_bin <= waddr_bin + wen;

In both, a register is loaded from a LOOKAHEAD of a counter on the very edge
that advances that counter. The result is published one source cycle EARLY
relative to the counter it describes. Both are self-consistent and both look
more "correct" than the form the reference uses — the flop appears to describe
the value it will hold. That reasoning is what produced both bugs: a
`always @(posedge)` block already registers, so decoding the PRE-increment value
is what makes the level line up with the counter state it names.

WHY THE EXISTING GATES DO NOT SEE IT
------------------------------------
* `clock_divider_phase_form_check` matches the SELF-TOGGLE anti-pattern
  (`X <= ~X`, reset LOW). Both designs here use a level decode and are reset
  correctly, so it PASSes them — verified on both the broken and the fixed RTL.
* A ratio/duty oracle is blind by construction: period and duty are exactly
  right; only the phase relative to reset moves.
* For the FIFO the flags round-trip self-consistently, so a write-then-read
  testbench also passes. It takes traffic at the full/empty boundary to see it.

WHAT THIS DETECTS — narrow on purpose
-------------------------------------
Inside one edge-triggered block, a nonblocking assignment whose RHS reads a
LOOKAHEAD of a counter (`cnt + 1`, `cnt + inc`, or a wire defined as such) while
the SAME block advances that counter with the same expression. Both halves must
be present: a design that only computes `cnt_next` and uses it solely to update
the counter is the ordinary pattern and is NOT reported.

`--strict` makes a finding exit non-zero; the default is advisory, because a
lookahead decode is legitimate when the spec asks for the level to lead (a
pre-emptive `almost_full`, a one-cycle-early enable). The finding names the
signal and both statements so a human can decide in seconds.

WHY_NOT_BUCKET_A: whether a lookahead is a defect or the spec's intent needs the
spec. The deterministic half — that a lookahead decode and its counter update
share an edge — is what this program measures, and it is exactly the shape that
was wrong twice in one run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: `// …` to end of line, and `/* … */` across newlines. Stripped before any
#: structural scan: a comment naming a pattern must never decide a verdict.
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)

#: `always @(posedge …)` / `always_ff` header.
_EDGE_BLOCK = re.compile(r"\balways(?:_ff)?\s*@\s*\(([^)]*)\)", re.I)

#: A nonblocking assignment: `lhs <= rhs;`
_NONBLOCKING = re.compile(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=\s*([^;]+);")

#: `name + something` / `name + 1'b1` — a counter lookahead.
def _increment_of(expr: str, name: str) -> bool:
    pat = re.compile(r"\b" + re.escape(name) + r"\s*\+\s*[^\s;)]+")
    return bool(pat.search(expr))


def _strip(src: str) -> str:
    return _COMMENT.sub(" ", src or "")


def _blocks(src: str):
    """(header, body) for each edge-triggered always block, brace-matched."""
    out = []
    for m in _EDGE_BLOCK.finditer(src):
        sens = m.group(1)
        if "posedge" not in sens.lower() and "negedge" not in sens.lower():
            continue
        i = src.find("begin", m.end())
        if i < 0:
            continue
        depth, j = 0, i
        while j < len(src):
            word = re.match(r"\b(begin|end)\b", src[j:])
            if word:
                depth += 1 if word.group(1) == "begin" else -1
                j += len(word.group(1))
                if depth == 0:
                    break
                continue
            j += 1
        out.append((sens, src[i:j]))
    return out


def _lookahead_wires(src: str) -> dict:
    """`wire x = cnt + 1;` → {x: cnt}. Continuous lookahead definitions."""
    found = {}
    for m in re.finditer(
        r"\b(?:wire|logic)\s*(?:\[[^\]]*\])?\s*([A-Za-z_]\w*)\s*=\s*([^;]+);", src
    ):
        name, rhs = m.group(1), m.group(2)
        for cand in re.findall(r"\b([A-Za-z_]\w*)\s*\+", rhs):
            if cand != name:
                found[name] = cand
                break
    return found


def scan(src: str) -> list:
    """Findings: a level decoded from a counter lookahead, registered on the
    same edge that advances that counter."""
    s = _strip(src)
    aliases = _lookahead_wires(s)
    findings = []
    for sens, body in _blocks(s):
        assigns = [(m.group(1), m.group(2), m.group(0))
                   for m in _NONBLOCKING.finditer(body)]
        # counters this block advances: `c <= c + …`
        advanced = {lhs for lhs, rhs, _ in assigns if _increment_of(rhs, lhs)}
        # …or advanced through a lookahead alias: `c <= c_next`
        for lhs, rhs, _ in assigns:
            for alias, base in aliases.items():
                if base == lhs and re.search(r"\b" + re.escape(alias) + r"\b", rhs):
                    advanced.add(lhs)
        if not advanced:
            continue
        for lhs, rhs, stmt in assigns:
            if lhs in advanced:
                continue                      # the counter's own update
            for counter in advanced:
                direct = _increment_of(rhs, counter)
                via_alias = any(
                    base == counter and re.search(r"\b" + re.escape(alias) + r"\b", rhs)
                    for alias, base in aliases.items()
                )
                if not (direct or via_alias):
                    continue
                # A DECODE, not an accumulation. `data_out <= acc + data_in` is
                # the accumulator's own arithmetic result, not a level decoded
                # from a phase counter: reporting it was a false positive on a
                # correct design. Require the lookahead to feed a COMPARISON or
                # an encoding call — the shapes that publish a phase.
                decodes = bool(
                    re.search(r"[<>]=?|==|!=|\?", rhs)          # comparison / mux
                    or re.search(r"\b\w*gray\w*\s*\(", rhs, re.I)  # bin2gray(...)
                )
                if decodes:
                    findings.append({
                        "signal": lhs,
                        "counter": counter,
                        "via": "alias" if (via_alias and not direct) else "inline",
                        "statement": " ".join(stmt.split())[:160],
                        "sensitivity": " ".join(sens.split()),
                    })
                    break
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description="A level decoded from a counter LOOKAHEAD, registered on "
                    "the same edge that advances that counter, is published one "
                    "cycle early.")
    ap.add_argument("rtl", nargs="+", help="RTL file(s) to scan")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on a finding (default: advisory)")
    ap.add_argument("--json", help="write the structured result here")
    args = ap.parse_args()

    rows = []
    for path in args.rtl:
        p = Path(path)
        if not p.is_file():
            print(f"CANNOT CHECK: {path} is not a readable file")
            return 2
        for f in scan(p.read_text(encoding="utf-8", errors="replace")):
            f["file"] = path
            rows.append(f)

    result = {
        "schema": "vibeic.counter_decode_lookahead_phase.v1",
        "findings": rows,
        "verdict": "FINDING" if rows else "PASS",
    }
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2) + "\n",
                                   encoding="utf-8")

    if not rows:
        print("PASS: no level decoded from a counter lookahead on the counter's "
              "own edge.")
        return 0

    print(f"FINDING: {len(rows)} signal(s) decoded from a counter LOOKAHEAD on "
          f"the same edge that advances the counter — each is published one "
          f"cycle early relative to the counter it names:")
    for f in rows:
        print(f"  {f['file']}: {f['signal']} <- lookahead of {f['counter']} "
              f"({f['via']})")
        print(f"      {f['statement']}")
    print("  Decode the PRE-increment value instead, unless the spec asks for a "
          "level that leads by one cycle. A period/duty or write-then-read "
          "oracle cannot see this; only a check anchored to reset or to the "
          "full/empty boundary can.")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
