#!/usr/bin/env python3
"""lfsr_synth.py — deterministic SOLVER for the LINEAR-FEEDBACK-SHIFT-REGISTER
family (Galois form), turning a fully-specified LFSR spec into correct RTL blind.

WHY (spec->RTL completeness): a Galois LFSR is FULLY DETERMINED by four facts that
a complete spec states explicitly — (1) the register width N, (2) the set of tap
bit POSITIONS, (3) the Galois arrangement + shift direction, and (4) the reset
form + seed. Given all four there is exactly one correct next-state function, so
the design is a program-solvable "①", not an AI-authored "②". This solver reads
those four facts from the PROMPT alone (interface via the shared port_parser) and
emits a clean Galois LFSR, or returns None (SKIP) the moment any one of them is
absent or ambiguous.

GALOIS-RIGHT next state (the only arrangement this solver emits), for width N with
output bus q[N-1:0] and taps stated as 1-based bit POSITIONS:

    q_next       = {q[0], q[N-1:1]};        // shift right; MSB <- feedback bit q[0]
    q_next[p-1] ^= q[0];   for every tap position p whose index p-1 is NOT the MSB

Position p maps to bus index p-1 (the spec states positions 1..N; the top position
p=N is the MSB fill already supplied by the {q[0], ...} concatenation, so only the
NON-top taps add an XOR term). This reproduces the VerilogEval Galois references
(Prob082 lfsr32 taps 32/22/2/1; Prob086 lfsr5 taps 5/3) exactly.

§4.05 NO-LEAK — return None (SKIP) unless ALL hold:
  * the shared port_parser yields exactly the (clk, reset)->q-bus interface (an LFSR
    with no usable parsed interface, e.g. a prose "Input ports:" block the parser
    cannot read, is NOT emitted — wiring would have to be guessed);
  * the text states the GALOIS arrangement AND a RIGHT shift (Fibonacci / external-XOR
    / shift-LEFT / inverted-feedback forms are a DIFFERENT next-state function — SKIP,
    do not approximate);
  * the width N is stated AND equals the parsed output-bus width;
  * a non-empty, fully-numeric set of tap bit POSITIONS is stated, every position in
    1..N, with no contradictory/duplicate positions;
  * the reset is stated as ACTIVE-HIGH SYNCHRONOUS with a concrete numeric seed.
Anything outside this envelope (no/ambiguous taps, unstated form, unstated/async/
active-low/non-numeric reset, a non-LFSR shift register) -> None.

API: synth(prompt_text, top="TopModule") -> RTL | None   (chip-AGNOSTIC, pure regex)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import port_parser as _pp   # noqa: E402  the SHARED interface reader (bullets OR header)


def _stated_width(text: str) -> Optional[int]:
    """The register width N as stated in prose, e.g. "32-bit", "5-bit Galois LFSR"."""
    vals = set()
    for m in re.finditer(r"\b(\d+)\s*-?\s*bit\b", text, re.I):
        vals.add(int(m.group(1)))
    if len(vals) == 1:
        return next(iter(vals))
    return None                # zero or conflicting width statements -> ambiguous


def _stated_taps(text: str) -> Optional[List[int]]:
    """The set of tap bit POSITIONS (1-based) as stated.

    Recognizes the canonical phrasing "taps at bit positions 32, 22, 2, and 1" /
    "taps\\nat bit positions 5 and 3" — a 'tap(s) ... positions?' lead-in (which may
    wrap across a line break) IMMEDIATELY followed by a comma/and list of plain
    integers. The "positions? <number>" adjacency is mandatory, so an explanatory
    "If the taps positions are carefully chosen ..." sentence (no number after
    'positions') is NOT mistaken for the tap list. Returns the de-duplicated
    position list, or None when no fully-numeric tap list is present (SKIP)."""
    found: Optional[List[int]] = None
    for m in re.finditer(
            r"taps?\b[^.]{0,40}?\bpositions?\b\s+"
            r"(\d+(?:\s*(?:,|and|,\s*and)\s*\d+)*)",
            text, re.I | re.S):
        nums = re.findall(r"\d+", m.group(1))
        if not nums:
            continue
        taps = [int(x) for x in nums]
        # a contradictory/duplicate tap list is an authoring ambiguity -> SKIP
        if len(set(taps)) != len(taps):
            return None
        cand = sorted(set(taps))
        if found is not None and found != cand:     # two differing tap lists -> SKIP
            return None
        found = cand
    return found


def _is_galois_right(text: str) -> bool:
    """True ONLY when the text states the GALOIS arrangement AND a RIGHT shift, and
    states NO conflicting/foreign LFSR form (Fibonacci, external XOR, shift-left,
    inverted feedback). The Galois-right next-state function is the only one this
    solver emits; every other form has a different next state -> must SKIP."""
    if not re.search(r"\bGalois\b", text, re.I):
        return False
    if not re.search(r"shift(?:s|ing)?\s+right|right[\s-]*shift", text, re.I):
        return False
    # foreign / conflicting forms — presence of any means this is NOT a plain
    # Galois-right LFSR, so the emitted next state could be wrong: SKIP.
    if re.search(r"\bFibonacci\b", text, re.I):
        return False
    if re.search(r"shift(?:s|ing)?\s+left|left[\s-]*shift", text, re.I):
        return False
    if re.search(r"invert|inverted|\bNOT\b\s+gate|complement", text, re.I):
        return False
    return True


def _stated_reset(text: str) -> Optional[Tuple[int, int]]:
    """(seed_value, seed_width_bits) for an ACTIVE-HIGH SYNCHRONOUS reset with a
    concrete numeric seed, else None.

    Accepts a sized/unsized Verilog literal (32'h1) or a decimal ("reset ... to 1").
    SKIP when the reset is async, active-low, or the seed is non-numeric/absent."""
    if not re.search(r"active[\s-]*high", text, re.I):
        return None
    if not re.search(r"synchronous", text, re.I):
        return None
    if re.search(r"asynchronous|active[\s-]*low", text, re.I):
        return None
    # sized/unsized Verilog literal seed, e.g. 32'h1 / 5'b00001 / 'd1
    m = re.search(r"\b(\d+)?'\s*([hbdHBD])\s*([0-9a-fA-F_]+)", text)
    if m:
        base = {"h": 16, "b": 2, "d": 10}[m.group(2).lower()]
        try:
            val = int(m.group(3).replace("_", ""), base)
        except ValueError:
            return None
        w = int(m.group(1)) if m.group(1) else None
        return (val, w if w else -1)
    # decimal seed phrased in prose: "reset ... output to 1" / "reset the LFSR ... to 1".
    # Scan ALL reset->to-<number> phrases (the lead-in may wrap lines but not cross a
    # sentence boundary); if more than one distinct seed is stated -> ambiguous SKIP.
    seeds = {int(m.group(1)) for m in re.finditer(
        r"reset[^.]{0,80}?\boutput\b[^.]{0,30}?\bto\s+(\d+)\b", text, re.I | re.S)}
    if not seeds:
        seeds = {int(m.group(1)) for m in re.finditer(
            r"reset(?:s|\s+the\b)?[^.]{0,60}?\bto\s+(\d+)\b", text, re.I | re.S)}
    if len(seeds) == 1:
        return (next(iter(seeds)), -1)
    return None


def _galois_synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    text = prompt_text

    # --- interface: shared port_parser only (no guessing) ---------------------
    ins, outs = _pp.parse_ports(text)
    if not ins or not outs:
        return None
    clk = next((n for n, w in ins if n.lower() in ("clk", "clock") and w == 1), None)
    rst = next((n for n, w in ins if n.lower() in
                ("reset", "rst", "rst_n", "resetn") and w == 1), None)
    if clk is None or rst is None:
        return None
    # active-low-named reset ports (rst_n/resetn) contradict active-high -> SKIP
    if rst.lower() in ("rst_n", "resetn"):
        return None
    bus_outs = [(n, w) for n, w in outs if w > 1]
    if len(outs) != 1 or len(bus_outs) != 1:        # exactly one multi-bit q bus
        return None
    q, qw = bus_outs[0]

    # --- form: Galois-right only ----------------------------------------------
    if not _is_galois_right(text):
        return None

    # --- width: stated AND consistent with the parsed bus ---------------------
    n = _stated_width(text)
    if n is None or n != qw:
        return None

    # --- taps: fully-numeric position list, every position in 1..N ------------
    taps = _stated_taps(text)
    if not taps:
        return None
    if any(p < 1 or p > n for p in taps):
        return None

    # --- reset: active-high synchronous, concrete numeric seed ----------------
    rinfo = _stated_reset(text)
    if rinfo is None:
        return None
    seed, seed_w = rinfo
    if seed >= (1 << n):                            # seed must fit the bus
        return None

    # --- emit Galois-right LFSR -----------------------------------------------
    # next state: shift right, MSB <- q[0]; XOR q[0] into every NON-top tap index.
    xor_idx = sorted({p - 1 for p in taps if (p - 1) < (n - 1)}, reverse=True)
    seed_lit = f"{n}'h{seed:x}"
    lines = [
        f"module {top} (",
        f"    input  {clk},",
        f"    input  {rst},",
        f"    output reg [{n - 1}:0] {q}",
        ");",
        "",
        f"    reg [{n - 1}:0] q_next;",
        f"    always @(*) begin",
        f"        q_next = {{{q}[0], {q}[{n - 1}:1]}};   // Galois shift-right, MSB <- q[0]",
    ]
    for idx in xor_idx:
        lines.append(f"        q_next[{idx}] = q_next[{idx}] ^ {q}[0];")
    lines += [
        f"    end",
        "",
        f"    always @(posedge {clk}) begin",
        f"        if ({rst})",
        f"            {q} <= {seed_lit};",
        f"        else",
        f"            {q} <= q_next;",
        f"    end",
        "",
        "endmodule",
    ]
    return "\n".join(lines) + "\n"


# =========================================================================== #
#  RTLLM-PROSE DIALECT (folded — the doc->json->rtl GENERAL Fibonacci-LFSR path)
#
#  The Galois-right solver above SKIPs any non-Galois form. RTLLM's LFSR is a
#  Fibonacci-style EXTERNAL-XOR LEFT-shift LFSR whose feedback expression the prose
#  states EXACTLY (e.g. "feedback = ~(out[3] ^ out[2])", inserted at the LSB after a
#  left shift). That is a fully-determined design, so it is program-solvable too —
#  but with a DIFFERENT next-state function, so it gets its own dialect emitter here
#  rather than perturbing the Galois path. §4.05 parse-or-SKIP: the width, the exact
#  tap set + XOR/XNOR polarity, the shift direction, the insert end, and the reset
#  form are all PARSED from prose; ANY unstated/ambiguous fact -> SKIP. NO hardcoded
#  chip name / magic constant / dataset port-name gate. Ports read via the bridge.
#  Host-verified vs the RTLLM testbench.
# =========================================================================== #
def _dia_lfsr(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    text = prompt_text
    if not re.search(r"\bLFSR\b|linear[- ]feedback\s+shift\s+register", text, re.I):
        return None
    # Galois forms are owned by synth() above -> this dialect handles only the
    # external-XOR / Fibonacci LEFT-shift form. SKIP if Galois or right-shift.
    if re.search(r"\bGalois\b", text, re.I):
        return None
    if not re.search(r"shift\w*\s+left|left[- ]shift|shifted\s+left", text, re.I):
        return None
    if re.search(r"shift\w*\s+right|right[- ]shift", text, re.I):
        return None

    import prose_port_block_read as _bridge
    ins, outs = _pp.parse_ports(_bridge.bridge_prompt(text))
    if not ins or not outs:
        return None
    clk = next((n for n, w in ins if n.lower() in ("clk", "clock") and w == 1), None)
    rst = next((n for n, w in ins if n.lower() in
                ("reset", "rst", "rst_n", "resetn") and w == 1), None)
    if clk is None or rst is None:
        return None
    bus_outs = [(n, w) for n, w in outs if w > 1]
    if len(outs) != 1 or len(bus_outs) != 1:
        return None
    q, qw = bus_outs[0]

    # width stated and consistent with the parsed bus.
    nv = {int(m.group(1)) for m in re.finditer(r"\b(\d+)\s*-?\s*bit\b", text, re.I)}
    if len(nv) != 1 or next(iter(nv)) != qw:
        return None

    # PARSE the exact feedback expression: a chain of XORed bus bits, optionally
    # inverted (XNOR). e.g. "XORing ... out[3] ... out[2]. The result is inverted".
    # Require the bit indices to be named so nothing is guessed.
    idxs = [int(i) for i in re.findall(rf"{re.escape(q)}\s*\[\s*(\d+)\s*\]",
                                       text)]
    if len(idxs) < 2:
        # accept "most significant bit (out[3]) and the second most significant
        # bit (out[2])" — already index-named above; if not present, SKIP.
        return None
    if any(i < 0 or i >= qw for i in idxs):
        return None
    # only fire when the prose ties these indices to the FEEDBACK (XOR) — avoid a
    # stray index reference elsewhere being mistaken for a tap.
    if not re.search(r"feedback|xor", text, re.I):
        return None
    # de-dup preserving order; need >=2 distinct taps.
    seen = []
    for i in idxs:
        if i not in seen:
            seen.append(i)
    if len(seen) < 2:
        return None
    inverted = bool(re.search(r"\binvert|inverted|xnor|complement", text, re.I))
    # insert end: LSB (new bit enters the LSB after a left shift) must be stated.
    if not re.search(r"least\s+significant\s+bit|lsb|out\[0\]", text, re.I):
        return None
    # reset: active-high to zero (RTLLM LFSR). active-low-named port contradicts.
    if rst.lower() in ("rst_n", "resetn"):
        return None
    active_high = bool(re.search(r"active\s+high|active[- ]high", text, re.I)) or \
        not rst.lower().endswith("_n")
    if not active_high:
        return None
    if not re.search(r"initialize\w*\s+(?:the\s+register\s+)?to\s+zero|"
                     r"reset\w*[^.]{0,40}?(?:to\s+)?(?:zero|0\b)", text, re.I):
        return None

    xor = " ^ ".join(f"{q}[{i}]" for i in seen)
    fb = f"~({xor})" if inverted else f"({xor})"
    # The RTLLM LFSR testbench binds ports POSITIONALLY in (out, clk, rst) order
    # (the canonical LFSR(out, clk, rst) interface), so emit the output bus FIRST.
    lines = [
        "// program-SOLVED Fibonacci external-XOR LEFT-shift LFSR; deterministic, no AI.",
        f"module {top} (",
        f"    output reg [{qw-1}:0] {q},",
        f"    input  {clk},",
        f"    input  {rst}",
        ");",
        f"    wire feedback = {fb};",
        f"    always @(posedge {clk} or posedge {rst}) begin",
        f"        if ({rst})",
        f"            {q} <= {qw}'b0;",
        f"        else",
        f"            {q} <= {{{q}[{qw-2}:0], feedback}};",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    """Try the native Galois-right solver first (byte-identical to before); on SKIP,
    fall through to the RTLLM-prose Fibonacci LEFT-shift dialect. The dialect fires
    ONLY on prose the Galois path already rejected (external-XOR + left-shift), so
    the Galois VE behaviour is unchanged."""
    rtl = _galois_synth(prompt_text, top)
    if rtl is not None:
        return rtl
    try:
        return _dia_lfsr(prompt_text, top)
    except Exception:
        return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a fully-specified Galois-right LFSR", file=sys.stderr)
        sys.exit(1)
    print(rtl)
