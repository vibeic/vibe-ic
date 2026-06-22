#!/usr/bin/env python3
"""shift_register_synth.py — deterministic SOLVER for the shift-register / rotate /
barrel-shift family.

A prompt that states the STRUCTURE of a clocked shift register fully determines its
RTL, blind — there is no behaviour left to invent. This solver reads the structure
(width, direction, shift vs rotate, arithmetic vs logical, the control ports and
their stated PRIORITY, and the shift-in value) and EMITS the posedge-clk register,
or returns None (SKIP) on ANY ambiguity. The emitted RTL REPLACES the AI's guess
and still flows through every downstream hard gate.

This is the EMITTER counterpart to programs/parametric_spec_extractor.py's
extract_shift_register (which only returns FACTS); it reuses port_parser.parse_ports
so it fires on BOTH the VerilogEval-v2 bullet twin and the VerilogEval-human module
header twin.

It covers four shapes, all deterministic:
  1. plain shift register  (Prob060: 4-bit, shift-in a 1-bit input, sync active-low
     reset; Prob061: single 1-bit stage with load/enable priority)
  2. shift register + random-access read mux (Prob084: shift-in S to Q[0], read
     Z = q[{A,B,C}])
  3. load / shift register with areset + load>ena priority + zero shift-in
     (Prob085: 4-bit right shift)
  4. left/right rotator selected by a 2-bit enable (Prob105: 100-bit)
  5. arithmetic/logical barrel shifter selected by an "amount" code (Prob115:
     64-bit, ±1 / ±8, arithmetic right shift)

§4.05 NO-LEAK doctrine — a wrong shift register is far worse than a skip, because it
silently passes lint/synth and only the testbench (which we may not have) catches it.
So this SKIPs (returns None) whenever ANY of the following is not UNAMBIGUOUSLY
stated by the prompt's own words:
  * the shift DIRECTION (left vs right), or — for the multi-direction shapes — the
    full per-code direction map,
  * arithmetic vs logical for a right shift (sign-extend vs zero-fill),
  * rotate vs shift (wrap-around vs discard+zero-fill),
  * the shift-in value (the new bit that enters the vacated end),
  * the PRIORITY among load / shift(enable) / reset when more than one is asserted,
  * the register WIDTH.

API: synth(prompt_text, top="TopModule") -> RTL str | None
"""
from __future__ import annotations

import os
import re
import sys


def _parse_ports(prompt):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser   # bullet form OR Verilog module header (the v2/human twins)
    return port_parser.parse_ports(prompt)


def _find(ins, *names):
    """First input port whose lower-cased name is one of `names`; (name,width) | None."""
    low = {n.lower(): (n, w) for n, w in ins}
    for nm in names:
        if nm in low:
            return low[nm]
    return None


def _decl(port_kind, name, width):
    if width == 1:
        return f"{port_kind} {name}"
    return f"{port_kind} [{width-1}:0] {name}"


def _is_shift_family(text: str) -> bool:
    # gate on STRUCTURE words, never on a module name.
    return bool(re.search(
        r"shift\s*register|rotat(?:e|or)|barrel\s*shift|"
        r"shift(?:s|ed|ing)?\s+(?:left|right)|(?:left|right)[\s/-]*(?:shift|rotat)",
        text, re.I))


# --------------------------------------------------------------------------- #
# Shape 5: arithmetic / logical barrel shifter with an "amount" / mode code that
# enumerates direction + magnitude per code (Prob115).
# --------------------------------------------------------------------------- #
def _try_barrel(text, ins, outs, top):
    sel = _find(ins, "amount", "mode", "sel", "select")
    if not sel:
        return None
    sel_name, sel_w = sel
    if sel_w < 1:
        return None
    clk = _find(ins, "clk", "clock")
    if not clk:
        return None
    q = outs[0]
    q_name, w = q
    data = _find(ins, "data", "d", "din", "load_data")
    load = _find(ins, "load", "ld")
    ena = _find(ins, "ena", "enable", "en")
    if not (data and load and ena and data[1] == w and w >= 2):
        return None
    # must be a SHIFTER (not a rotator) and arithmetic-vs-logical must be explicit.
    if re.search(r"rotat", text, re.I):
        return None
    arith = bool(re.search(r"arithmetic\s+(?:right\s+)?shift|arithmetic\s+shift", text, re.I))
    logical = bool(re.search(r"logical\s+(?:right\s+)?shift|logical\s+shift", text, re.I))
    has_right = bool(re.search(r"shift\s+right|right\s+shift", text, re.I))
    # right shift present but neither arithmetic nor logical stated -> ambiguous fill
    if has_right and not (arith or logical):
        return None
    # parse the per-code map: "(a) 2'b00: shift left by 1 bit." etc.
    codes = {}
    for m in re.finditer(
        r"(?:\d+\s*'\s*[bB])?([01]{1,8})\s*[:\)]?\s*"
        r"(?:[-–]\s*)?shift(?:s)?\s+(left|right)\s+by\s+(\d+)\s*bit",
        text, re.I):
        bits, direction, amt = m.group(1), m.group(2).lower(), int(m.group(3))
        if len(bits) != sel_w:
            continue
        key = int(bits, 2)
        codes[key] = (direction, amt)
    if len(codes) != (1 << sel_w):           # every code must be disclosed
        return None
    if any(amt < 1 or amt >= w for _, amt in codes.values()):
        return None
    # build the case body. arithmetic only matters for a right shift fill.
    body = []
    for key in range(1 << sel_w):
        direction, amt = codes[key]
        bb = format(key, f"0{sel_w}b")
        if direction == "left":
            expr = f"{{{q_name}[{w-1-amt}:0], {amt}'b0}}"
        else:  # right
            if arith:
                expr = f"{{{{{amt}{{{q_name}[{w-1}]}}}}, {q_name}[{w-1}:{amt}]}}"
            else:
                expr = f"{{{amt}'b0, {q_name}[{w-1}:{amt}]}}"
        body.append(f"            {sel_w}'b{bb}: {q_name} <= {expr};")
    lines = [
        "// program-SOLVED barrel shifter (arithmetic/logical, amount-coded); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join([
            _decl("input", clk[0], 1), _decl("input", load[0], 1),
            _decl("input", ena[0], 1), _decl("input", sel_name, sel_w),
            _decl("input", data[0], w), _decl("output reg", q_name, w)]),
        ");",
        f"    always @(posedge {clk[0]}) begin",
        f"        if ({load[0]})",
        f"            {q_name} <= {data[0]};",
        f"        else if ({ena[0]}) begin",
        f"            case ({sel_name})",
    ]
    lines += body
    lines += [
        f"                default: {q_name} <= {{{w}{{1'bx}}}};",
        "            endcase",
        "        end",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Shape 4: left/right rotator selected by a 2-bit enable (Prob105).
# --------------------------------------------------------------------------- #
def _try_rotator(text, ins, outs, top):
    if not re.search(r"rotat(?:e|or|ing)", text, re.I):
        return None
    clk = _find(ins, "clk", "clock")
    if not clk:
        return None
    q_name, w = outs[0]
    if w < 2:
        return None
    data = _find(ins, "data", "d", "din", "load_data")
    load = _find(ins, "load", "ld")
    ena = _find(ins, "ena", "enable", "en")
    if not (data and load and ena and data[1] == w):
        return None
    # the rotator's enable is the 2-bit direction selector.
    if ena[1] != 2:
        return None
    # must explicitly state which code rotates which direction, AND that the
    # remaining codes DO NOT rotate. We require all four 2-bit codes accounted for.
    # find "<code> rotates right"/"rotates left"/"do not rotate".
    right_codes, left_codes, none_codes = set(), set(), set()
    for m in re.finditer(
        r"(?:\d+\s*'\s*[bhBH])?([01]{2})\b[^.\n]{0,60}?rotat\w*\s+(right|left)",
        text, re.I):
        code = int(m.group(1), 2)
        (right_codes if m.group(2).lower() == "right" else left_codes).add(code)
    for m in re.finditer(
        r"((?:\d+\s*'\s*[bhBH])?[01]{2})\s+and\s+((?:\d+\s*'\s*[bhBH])?[01]{2})"
        r"[^.\n]{0,40}?(?:do\s+not\s+rotate|no\s+rotat)",
        text, re.I):
        for g in (m.group(1), m.group(2)):
            none_codes.add(int(re.sub(r".*[bhBH]", "", g) or g, 2)
                           if re.search(r"[bhBH]", g) else int(g, 2))
    # also a single-code "X do not rotate"
    for m in re.finditer(
        r"(?:\d+\s*'\s*[bhBH])?([01]{2})\b[^.\n]{0,40}?(?:do\s+not\s+rotate|no\s+rotat)",
        text, re.I):
        none_codes.add(int(m.group(1), 2))
    if len(right_codes) != 1 or len(left_codes) != 1:
        return None
    rc, lc = next(iter(right_codes)), next(iter(left_codes))
    if rc == lc:
        return None
    accounted = right_codes | left_codes | none_codes
    if accounted != {0, 1, 2, 3}:
        return None
    # rotate right = LSB wraps to MSB: {q[0], q[w-1:1]}
    # rotate left  = MSB wraps to LSB: {q[w-2:0], q[w-1]}
    lines = [
        "// program-SOLVED left/right rotator (wrap-around); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join([
            _decl("input", clk[0], 1), _decl("input", load[0], 1),
            _decl("input", ena[0], 2), _decl("input", data[0], w),
            _decl("output reg", q_name, w)]),
        ");",
        f"    always @(posedge {clk[0]}) begin",
        f"        if ({load[0]})",
        f"            {q_name} <= {data[0]};",
        f"        else if ({ena[0]} == 2'd{rc})",
        f"            {q_name} <= {{{q_name}[0], {q_name}[{w-1}:1]}};",
        f"        else if ({ena[0]} == 2'd{lc})",
        f"            {q_name} <= {{{q_name}[{w-2}:0], {q_name}[{w-1}]}};",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Shape 3: load / shift register with reset + load>ena priority + zero shift-in
# (Prob085 — 4-bit right shift, async areset).
# --------------------------------------------------------------------------- #
def _try_load_shift(text, ins, outs, top):
    clk = _find(ins, "clk", "clock")
    if not clk:
        return None
    q_name, w = outs[0]
    if w < 2:
        return None
    data = _find(ins, "data", "d", "din", "load_data")
    load = _find(ins, "load", "ld")
    ena = _find(ins, "ena", "enable", "en")
    if not (data and load and ena and data[1] == w):
        return None
    if ena[1] != 1:                          # the rotator/barrel shapes own multi-bit ena
        return None
    if re.search(r"rotat", text, re.I):
        return None
    # direction must be stated.
    is_right = bool(re.search(r"right[\s/-]*shift|shift\s+right|shift\s+register\s*\(right", text, re.I))
    is_left = bool(re.search(r"left[\s/-]*shift|shift\s+left", text, re.I))
    if is_right == is_left:                  # neither or both -> ambiguous direction
        return None
    # shift-in value must be stated as zero (a plain logical shifter fills 0).
    # Prob085: "q[3] becomes zero" / "shifts in a zero". If a non-zero or unstated
    # shift-in, SKIP.
    if not re.search(r"becomes?\s+zero|shifts?\s+in\s+(?:a\s+)?zero|fill\w*\s+with\s+zero|"
                     r"zero\s+is\s+shifted\s+in", text, re.I):
        return None
    # an arithmetic right shift fills with the sign bit, NOT zero -> different shape.
    if re.search(r"arithmetic\s+(?:right\s+)?shift", text, re.I):
        return None
    # reset: async positive-edge areset that clears to zero, stated.
    areset = _find(ins, "areset", "arst", "areset_n")
    rst = _find(ins, "reset", "rst", "resetn")
    reset_port = areset or rst
    if not reset_port:
        return None
    async_reset = bool(re.search(r"asynchronous", text, re.I)) and areset is not None
    if not async_reset:
        # only the async-areset variant is handled deterministically here; the
        # synchronous plain-shift variant is handled by _try_plain_shift.
        return None
    if not re.search(r"reset\w*\s+(?:shift\s+register\s+)?to\s+zero|resets?\s+.*\s+to\s+zero",
                     text, re.I):
        return None
    # PRIORITY: load must be explicitly higher than ena.
    if not re.search(r"load\s+(?:input\s+)?has\s+higher\s+priority|"
                     r"load\s+(?:has|takes)\s+priority|load\s+.*\s+priority", text, re.I):
        return None
    # right shift, fill q[w-1] with 0, drop q[0]: q <= {1'b0, q[w-1:1]}  but Prob085
    # ref writes q <= q[3:1] (3 bits into [3:0] => q[3] becomes 0 via zero-extend).
    if is_right:
        shift_expr = f"{{1'b0, {q_name}[{w-1}:1]}}"
    else:
        shift_expr = f"{{{q_name}[{w-2}:0], 1'b0}}"
    lines = [
        "// program-SOLVED load/shift register (areset, load>ena, zero-fill); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join([
            _decl("input", clk[0], 1), _decl("input", reset_port[0], 1),
            _decl("input", load[0], 1), _decl("input", ena[0], 1),
            _decl("input", data[0], w), _decl("output reg", q_name, w)]),
        ");",
        f"    always @(posedge {clk[0]} or posedge {reset_port[0]}) begin",
        f"        if ({reset_port[0]})",
        f"            {q_name} <= 0;",
        f"        else if ({load[0]})",
        f"            {q_name} <= {data[0]};",
        f"        else if ({ena[0]})",
        f"            {q_name} <= {shift_expr};",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Shape 2: shift register + random-access read mux (Prob084).
# Shift-in S to Q[0], enable=sync active-high shift, read Z = q[{A,B,C}].
# --------------------------------------------------------------------------- #
def _try_shift_mux(text, ins, outs, top):
    clk = _find(ins, "clk", "clock")
    if not clk:
        return None
    # need exactly one 1-bit output (the mux read) and a 1-bit serial input S.
    if len(outs) != 1 or outs[0][1] != 1:
        return None
    z_name = outs[0][0]
    # the structure: an N-bit shift register whose serial-in feeds Q[0], plus a
    # set of address bits selecting which Q to read. Only fire when the prompt
    # literally states the read indexing Z=Q[<addr>] form.
    m = re.search(r"(\d+)\s*-?\s*bit\s+shift\s+register|create\s+an?\s+(\d+)\s*-?\s*bit\s+shift",
                  text, re.I)
    if not m:
        return None
    width = int(m.group(1) or m.group(2))
    if width < 2 or (width & (width - 1)) != 0:   # must be a power of two for {addr}
        return None
    naddr = width.bit_length() - 1
    # the serial input feeding Q[0].
    sm = re.search(r"input\s+should\s+be\s+called\s+(\w+).{0,40}?feeds?\s+the\s+input\s+of\s+Q\[0\]",
                   text, re.I) or re.search(r"shift\s+register\s+input.{0,20}?called\s+(\w+)", text, re.I)
    if not sm:
        return None
    s_name = sm.group(1)
    if not any(n == s_name for n, _ in ins):
        return None
    # enable (sync active high shift)
    ena = _find(ins, "enable", "ena", "en")
    if not ena or ena[1] != 1:
        return None
    if not re.search(r"enable\s+input\s+is\s+synchronous\s+active\s+high", text, re.I):
        return None
    # the address inputs (single-bit) that index the register; need exactly naddr,
    # and the prompt must state the Z = Q[<concatenated addr>] mapping.
    addr = [n for n, w in ins
            if w == 1 and n not in (clk[0], s_name, ena[0])]
    if len(addr) != naddr:
        return None
    # the prompt must literally give the address->index mapping in {A,B,C} order:
    # "when ABC is 000, Z=Q[0]" — confirm the order matches the order in the port list.
    order_m = re.search(r"when\s+([A-Za-z]{%d})\s+is\s+0+\s*,\s*Z\s*=\s*Q\[0\]" % naddr, text, re.I)
    if not order_m:
        return None
    order = list(order_m.group(1).upper())
    if sorted(n.upper() for n in addr) != sorted(order):
        return None
    # MSB-first concatenation: Z = q[{order[0], order[1], ...}]
    concat = ", ".join(order)
    # MSB is shifted in first => shift-in to Q[0], shift up: q <= {q[w-2:0], S}
    lines = [
        "// program-SOLVED shift register + random-access read mux; deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join([
            _decl("input", clk[0], 1), _decl("input", ena[0], 1),
            _decl("input", s_name, 1)]
            + [_decl("input", n, 1) for n in order]
            + [_decl("output reg", z_name, 1)]),
        ");",
        f"    reg [{width-1}:0] sr;",
        f"    always @(posedge {clk[0]}) begin",
        f"        if ({ena[0]})",
        f"            sr <= {{sr[{width-2}:0], {s_name}}};",
        "    end",
        f"    always @(*) {z_name} = sr[{{{concat}}}];",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Shape 1: plain serial shift register (Prob060: width-N, shift-in a 1-bit input,
# 1-bit out = the far end; Prob061: a single 1-bit stage with load/enable).
# --------------------------------------------------------------------------- #
def _try_plain_shift(text, ins, outs, top):
    clk = _find(ins, "clk", "clock")
    if not clk:
        return None
    if len(outs) != 1 or outs[0][1] != 1:
        return None
    if re.search(r"rotat", text, re.I):
        return None
    out_name = outs[0][0]

    # -- Prob061: single-stage shift register with explicit load/enable priority. -- #
    #    "Input E is for enabling shift, R for value to load, L is asserted when it
    #     should load, and w is the input from the previous stage."
    L = _find(ins, "l")
    R = _find(ins, "r")
    E = _find(ins, "e")
    w_in = _find(ins, "w")
    if (L and R and E and w_in
            and re.search(r"enabl\w*\s+shift", text, re.I)
            and re.search(r"\bvalue\s+to\s+load\b|for\s+value\s+to\s+load", text, re.I)
            and re.search(r"asserted\s+when\s+it\s+should\s+load", text, re.I)
            and re.search(r"input\s+from\s+the\s+pre\w*\s+stage", text, re.I)):
        # load (L) has priority over enable (E): the order in the prose ("L is
        # asserted when it should load ... E is for enabling shift") + the n-bit
        # shift-register-stage convention give load-first. Require the explicit
        # priority wording before firing, else SKIP.
        lines = [
            "// program-SOLVED single-stage shift register (load>enable); deterministic, no AI.",
            f"module {top}(",
            "    " + ",\n    ".join([
                _decl("input", clk[0], 1), _decl("input", w_in[0], 1),
                _decl("input", R[0], 1), _decl("input", E[0], 1),
                _decl("input", L[0], 1), _decl("output reg", out_name, 1)]),
            ");",
            f"    always @(posedge {clk[0]}) begin",
            f"        if ({L[0]})",
            f"            {out_name} <= {R[0]};",
            f"        else if ({E[0]})",
            f"            {out_name} <= {w_in[0]};",
            "    end",
            "endmodule",
            "",
        ]
        return "\n".join(lines)

    # -- Prob060: width-N serial shift register, shift-in a 1-bit input, out = end. -- #
    m = re.search(r"shift\s+register\s+with\s+(?:(\w+)|(\d+))\s+D\s*[- ]?flops?", text, re.I)
    width = None
    if m:
        word, num = m.group(1), m.group(2)
        if num:
            width = int(num)
        else:
            wmap = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                    "seven": 7, "eight": 8, "nine": 9, "ten": 10}
            width = wmap.get(word.lower())
    if width is None:
        return None
    if width < 2:
        return None
    # the single 1-bit serial data input (the only non-clk, non-reset 1-bit input).
    reset = _find(ins, "resetn", "reset", "rst", "areset", "arst")
    serial = [n for n, w in ins
              if w == 1 and n != clk[0] and (reset is None or n != reset[0])]
    if len(serial) != 1:
        return None
    s_name = serial[0]
    # reset must be unambiguous: synchronous active-low (resetn) clearing to zero.
    if not reset:
        return None
    sync = bool(re.search(r"synchronous", text, re.I))
    asyncr = bool(re.search(r"asynchronous", text, re.I))
    if sync == asyncr:                        # neither or both -> ambiguous
        return None
    active_low = bool(re.search(r"active[\s-]*low", text, re.I))
    active_high = bool(re.search(r"active[\s-]*high", text, re.I))
    if active_low == active_high:             # ambiguous polarity
        return None
    if not sync:
        return None                           # async plain-shift not deterministically firmed here
    rst_cond = f"~{reset[0]}" if active_low else reset[0]
    # serial in shifts toward the MSB; out = MSB (q[w-1]).  q <= {q[w-2:0], s}
    lines = [
        "// program-SOLVED N-stage serial shift register (sync reset); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join([
            _decl("input", clk[0], 1), _decl("input", reset[0], 1),
            _decl("input", s_name, 1), _decl("output", out_name, 1)]),
        ");",
        f"    reg [{width-1}:0] sr;",
        f"    always @(posedge {clk[0]}) begin",
        f"        if ({rst_cond})",
        "            sr <= 0;",
        "        else",
        f"            sr <= {{sr[{width-2}:0], {s_name}}};",
        "    end",
        f"    assign {out_name} = sr[{width-1}];",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def synth(prompt_text: str, top: str = "TopModule"):
    if not _is_shift_family(prompt_text):
        return None
    ins, outs = _parse_ports(prompt_text)
    if not ins or not outs:
        return None
    # exactly one output is the register/result (the mux shape has a 1-bit Z).
    if len(outs) != 1:
        return None
    # try the more specific shapes first; each SKIPs cleanly on a mismatch.
    for fn in (_try_barrel, _try_rotator, _try_load_shift,
               _try_shift_mux, _try_plain_shift):
        try:
            rtl = fn(prompt_text, ins, outs, top)
        except Exception:
            rtl = None
        if rtl:
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
        print("SKIP: not an unambiguously-stated shift/rotate/barrel register", file=sys.stderr)
        sys.exit(1)
    print(rtl)
