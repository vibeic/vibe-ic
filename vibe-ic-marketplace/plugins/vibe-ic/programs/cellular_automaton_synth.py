#!/usr/bin/env python3
"""cellular_automaton_synth.py — DETERMINISTIC 1-D cellular-automaton → RTL synth.

THE GAP THIS CLOSES
-------------------
The 1-D cellular-automaton family (Wolfram "Rule N", e.g. Rule 90 / Rule 110) is
a CLOSED-FORM spec: the STATED rule number is an 8-bit lookup that fully pins the
next state of every cell, with zero ambiguity and no hidden oracle. For each of
the 8 three-cell neighbourhood patterns (Left, Center, Right), bit
`(L<<2)|(C<<1)|R` of the rule number IS the center cell's next value. A blind RTL
author re-derives the per-cell boolean by eye and can flip the left/right
neighbour wiring or mis-transcribe the 8-row table per round (single-shot
variance). Per open-benchmark-methodology §4.2, a GENERAL no-cheat recovery MUST
be absorbed as a deterministic PROGRAM. This is that absorption: it reads the
rule number, the array width, the load/data/q ports, and the boundary convention
straight from the prompt and emits the exact next-state logic.

It is chip-AGNOSTIC and name-AGNOSTIC: it keys on the STATED rule number +
3-cell neighbourhood + boundary convention, NOT on any problem name ("rule90",
"Prob108", "Wolfram"). Any rule 0..255 over a 3-cell neighbourhood with the
standard {left=higher-index, right=lower-index} array and 0-valued off-array
boundaries is synthesizable.

§4.05 NO-LEAK — EXACT, UNAMBIGUOUS CA SPECS ONLY
------------------------------------------------
Wrong RTL is far worse than a SKIP. This synthesizer FIRES only when EVERY one
of these is unambiguously stated, and SKIPs (returns None / exit 2) otherwise:
  * exactly ONE rule number in 0..255 ("Rule 90"); none / out-of-range / two
    different numbers -> SKIP;
  * a 3-cell (self + two immediate neighbours) neighbourhood -> SKIP if the
    prompt describes a 5-cell / k-neighbour / totalistic / 2-D neighbourhood;
  * the standard load/q sequential CA interface (clk, load, data[W], q[W]) with a
    single matched W -> SKIP on any port/width mismatch;
  * an explicitly 0-valued off-array boundary (q[-1]=q[W]=0). If the prompt names
    a non-zero / wrap-around / cyclic / reflective boundary, the off-array wiring
    is no longer the standard one -> SKIP (do not guess);
  * a per-clock single-step advance (not a multi-step / shift / count variant).
So it can never ship an under-determined or mis-wired guess.

USAGE
-----
    python3 cellular_automaton_synth.py --prompt <prompt.txt> --top TopModule [--out s.sv]

EXIT CODES
----------
    0  synthesized + emitted (exact, unambiguous CA spec)
    2  SKIP — outside the proven-faithful CA envelope
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from port_parser import parse_ports  # noqa: E402  (shared interface reader)


# ---- rule-number lookup -------------------------------------------------------
def _next_bit(rule: int, left: int, center: int, right: int) -> int:
    """Wolfram convention: the neighbourhood (L,C,R) selects bit (L<<2)|(C<<1)|R
    of the 8-bit rule number, which is the center cell's NEXT value."""
    idx = (left << 2) | (center << 1) | right
    return (rule >> idx) & 1


def _flat(prompt: str) -> str:
    """Lower-case + whitespace-collapsed view, so line-wrapped phrases (e.g.
    'one-dimensional cellular\\nautomaton') still match the text gates."""
    return re.sub(r"\s+", " ", prompt.lower())


# ---- prompt parsing -----------------------------------------------------------
def _extract_rule(prompt: str) -> Optional[int]:
    """The single stated rule number in 0..255, or None on absent / out-of-range /
    conflicting. Matches `Rule 90`, `Rule-110`, `rule number 90` (NOT bare `90`)."""
    nums = set()
    for m in re.finditer(r"\brule\b[\s\-]*(?:number[\s\-]*)?(\d{1,3})\b", prompt, re.I):
        nums.add(int(m.group(1)))
    nums = {n for n in nums if 0 <= n <= 255}
    if len(nums) != 1:
        return None  # none, out-of-range, or two different rule numbers -> SKIP
    return next(iter(nums))


def _neighbourhood_ok(prompt: str) -> bool:
    """True only for the standard 3-cell (self + two immediate neighbours)
    neighbourhood. SKIP on 5-cell / k-neighbour / totalistic / 2-D wording."""
    low = _flat(prompt)
    bad = (
        "two-dimensional", "2-dimensional", "2d cellular", "two dimensional",
        "totalistic", "five-cell", "5-cell", "five cell",
        "four neighbour", "four neighbor", "k neighbour", "k neighbor",
        "second-nearest", "next-nearest",
    )
    if any(b in low for b in bad):
        return False
    # Positive evidence: the spec talks about a cell and its TWO neighbours.
    if "neighbour" not in low and "neighbor" not in low:
        return False
    # Reject an explicit non-2 neighbour count. The count word may be separated
    # from "neighbour(s)" by adjectives ("its four NEAREST neighbours",
    # "the eight surrounding neighbors"), so scan a short window (<=3 words) for a
    # number/number-word immediately preceding any "neighbour(s)" mention.
    word2num = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "1": 1, "2": 2}
    for m in re.finditer(r"((?:\b[\w\-]+\s+){0,3})neighbou?rs?\b", low):
        window = m.group(1).split()
        for w in window:
            n = word2num.get(w)
            if n is None and w.isdigit():
                n = int(w)
            if n is not None:
                if n != 2:
                    return False
                break  # found a "two neighbours" count -> fine, stop scanning
    return True


def _boundary_ok(prompt: str) -> bool:
    """True only when the off-array boundary is the standard 0 (off). SKIP on any
    wrap-around / cyclic / periodic / reflective / non-zero boundary statement."""
    low = _flat(prompt)
    cyclic = ("wrap", "wrap-around", "wraparound", "cyclic", "periodic boundary",
              "toroidal", "circular", "reflect", "mirror boundary")
    if any(c in low for c in cyclic):
        return False
    # Must positively state the off-array boundaries are zero / off.
    has_zero = bool(
        re.search(r"boundar(?:y|ies).{0,80}\b(?:zero|0|off)\b", low, re.S)
        or re.search(r"\b(?:zero|0|off)\b.{0,40}boundar", low, re.S)
    )
    return has_zero


def _single_step(prompt: str) -> bool:
    """True for the per-clock single-step advance. The spec must say it advances
    one time step each clock cycle (not a multi-step / shift / count variant)."""
    low = _flat(prompt)
    return ("each clock cycle" in low or "every clock cycle" in low
            or "per clock" in low or "each time step" in low) and "time step" in low


def synth(prompt: str, top: str = "TopModule") -> Optional[str]:
    """Emit synthesizable RTL for an unambiguous 1-D CA spec, else None (SKIP)."""
    low = _flat(prompt)
    # Coarse family gate first: must be a cellular automaton spec.
    if "cellular automaton" not in low and "cellular-automaton" not in low:
        return None

    rule = _extract_rule(prompt)
    if rule is None:
        return None
    if not _neighbourhood_ok(prompt):
        return None
    if not _boundary_ok(prompt):
        return None
    if not _single_step(prompt):
        return None

    ins, outs = parse_ports(prompt)
    in_map = dict(ins)
    out_map = dict(outs)
    # Required canonical CA interface: clk + load + data[W] + q[W], single matched W.
    if "clk" not in in_map or "load" not in in_map:
        return None
    if "data" not in in_map or "q" not in out_map:
        return None
    if in_map["clk"] != 1 or in_map["load"] != 1:
        return None
    width = out_map["q"]
    if width < 3:
        return None  # a 3-cell neighbourhood needs >=3 cells to be well-posed
    if in_map["data"] != width:
        return None  # data must match q width exactly
    # Exactly the four expected ports (extra/renamed ports -> out of envelope).
    if set(in_map) != {"clk", "load", "data"} or set(out_map) != {"q"}:
        return None

    # ---- build the next-state expression for cell i -------------------------
    # Standard 1-D CA wiring (matches the family's reference + both prompts):
    #   Left  = q[i+1]   (higher index)
    #   Center= q[i]
    #   Right = q[i-1]   (lower index)
    #   off-array boundaries q[-1]=q[W]=0.
    # nxt[i] = OR over the (L,C,R) patterns whose rule bit is 1, of (L&C&R literals).
    # We synthesize it as three vector terms over q so it is width-generic and
    # uses ONLY the in-range slices the boundary-zeros allow.
    msb = width - 1
    lines: List[str] = []
    lines.append(f"module {top} (")
    lines.append("    input clk,")
    lines.append("    input load,")
    lines.append(f"    input [{msb}:0] data,")
    lines.append(f"    output reg [{msb}:0] q")
    lines.append(");")
    lines.append("")
    # Vectorized neighbour buses with 0-boundaries:
    #   left  bus L[i] = q[i+1], with L[msb]=0           -> {1'b0, q[msb:1]}
    #   center bus C[i] = q[i]                            -> q
    #   right bus R[i] = q[i-1], with R[0]=0              -> {q[msb-1:0], 1'b0}
    lines.append(f"    wire [{msb}:0] l = {{1'b0, q[{msb}:1]}};   // left  = q[i+1], q[{width}]=0")
    lines.append(f"    wire [{msb}:0] c = q;                 // center = q[i]")
    lines.append(f"    wire [{msb}:0] r = {{q[{msb-1}:0], 1'b0}};   // right = q[i-1], q[-1]=0")
    # Build the SOP of the 8 patterns whose rule bit == 1.
    terms: List[str] = []
    for left in (0, 1):
        for center in (0, 1):
            for right in (0, 1):
                if _next_bit(rule, left, center, right):
                    lit_l = "l" if left else "~l"
                    lit_c = "c" if center else "~c"
                    lit_r = "r" if right else "~r"
                    terms.append(f"({lit_l} & {lit_c} & {lit_r})")
    nxt = " | ".join(terms) if terms else f"{width}'b0"
    lines.append(f"    wire [{msb}:0] nxt = {nxt};")
    lines.append("")
    lines.append("    always @(posedge clk) begin")
    lines.append("        if (load)")
    lines.append("            q <= data;")
    lines.append("        else")
    lines.append("            q <= nxt;")
    lines.append("    end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: outside the unambiguous 1-D cellular-automaton synth envelope",
              file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
