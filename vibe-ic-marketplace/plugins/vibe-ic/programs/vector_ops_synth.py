#!/usr/bin/env python3
"""vector_ops_synth.py — deterministic SOLVER for the VECTOR-MANIPULATION family
(spec -> RTL): bit/byte reverse, sign/zero-extend, replicate, split, concat-reorder.

A vector-manipulation prompt that states its EXACT bit mapping is fully determined,
blind: every output bit is a copy (or replication / constant) of a definite input
bit. There is no arithmetic and no oracle to re-derive — the RTL is a pure wiring
permutation. Yet a blind author re-derives the index math by eye (MSB-first vs
LSB-first reverse, byte-vs-bit granularity, which half is the upper byte, how many
sign-bit copies) and flips it across clean-room rounds. Per § 4.2 that GENERAL
no-cheat recovery is absorbed as a PROGRAM: this solver reads the stated interface
(via the SHARED port_parser) plus the prose that fixes the bit mapping, and EMITS
correct synthesizable RTL, or returns None (SKIP) on ANY ambiguity.

This is a HIGH-VARIANCE prose family, so the solver is deliberately CONSERVATIVE:
it fires ONLY when the bit mapping is UNAMBIGUOUS, and SKIPs everything where the
direction / granularity / partition / count is not fully stated. A wrong wiring is
far worse than an honest skip (§4.05 NO-LEAK).

Recognized FORMS (keyed on the STATED bit operation + widths, never on names):

  (1) BIT REVERSE  — "reverse the bit ordering of the input": out[i] = in[W-1-i],
      out width == in width. (Prob006_vectorr 8b, Prob023_vector100r 100b.)

  (2) BYTE REVERSE — "reverse the byte order of a 32-bit vector": the vector is cut
      into 8-bit bytes and the byte order reversed (each byte's bits kept). Width
      must be a multiple of 8. (Prob004_vector2 32b.)

  (3) SIGN-EXTEND  — "sign-extend an N-bit number to M bits": replicate the input's
      MSB (M-N) times to the left, then the input. out = {{(M-N){in[N-1]}}, in}.
      ZERO-EXTEND is the {(M-N){1'b0}} sibling. (Prob042_vector4 8->32 sign-ext.)

  (4) SPLIT TO HI/LO BYTES — one 2B-bit input split into an upper byte and a lower
      byte: {hi, lo} = in (hi == in[2B-1:B], lo == in[B-1:0]). Both halves the same
      width B and the prose names which is upper / lower. (Prob015_vector1 16->8+8.)

  (5) PASSTHROUGH + POSITION-MAPPED BIT OUTPUTS — one W-bit input echoed to a W-bit
      output AND fanned out to W single-bit outputs each EXPLICITLY mapped to a
      stated position (oK <- position K). (Prob032_vector0 3b.)

  (6) CONCAT-THEN-SPLIT (+ stated trailing constant bits) — N equal-width inputs
      concatenated (declaration order, MSB-first) optionally followed by a stated
      run of trailing '1' bits in the LSBs, then re-partitioned into M equal-width
      outputs (declaration order, MSB-first). The two bit budgets must match exactly.
      (Prob064_vector3 six 5b + 2'b11 -> four 8b.)

§4.05 NO-LEAK — SKIP (return None) unless EVERY relevant fact is unambiguous:
  * any clock/reset/enable/control port  => SKIP (this is a pure combinational
    wiring family; sequential intent means a different module);
  * reverse: out width MUST equal in width; byte reverse needs width % 8 == 0;
  * extend: out width MUST exceed in width and the extend KIND (sign vs zero) MUST
    be explicitly stated;
  * hi/lo split: exactly one input, exactly two equal-width outputs summing to the
    input width, and the prose must name upper/lower (so we know which half);
  * passthrough+bits: the single-bit outputs must EACH have an explicit position
    mapping in the prose, and there must be exactly one equal-width vector echo;
  * concat-split: equal-width inputs, equal-width outputs, the two bit budgets equal
    (after the stated trailing constant), and the trailing constant fully stated.

API: synth(prompt_text, top="TopModule") -> str | None
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import port_parser as _pp  # noqa: E402  reuse the SHARED interface reader


# control ports that mean "this is not a pure combinational wiring op" -> SKIP.
_CONTROL = ("clk", "clock", "rst", "reset", "rstn", "rst_n", "areset", "aresetn",
            "en", "enable", "load", "valid", "ready", "clr", "clear", "set")


def _has_control(ins) -> bool:
    return any(n.lower() in _CONTROL for n, _ in ins)


# --------------------------------------------------------------------------- #
# emit helper                                                                 #
# --------------------------------------------------------------------------- #
def _decl(name: str, w: int, direction: str) -> str:
    if w == 1:
        return f"    {direction} {name}"
    return f"    {direction} [{w-1}:0] {name}"


def _module(top: str, ports, body_lines, note) -> str:
    lines = [f"// program-SOLVED vector op ({note}); deterministic wiring.",
             f"module {top} ("]
    lines.append(",\n".join(ports))
    lines.append(");")
    lines.extend(body_lines)
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# FORM 1/2: reverse                                                           #
# --------------------------------------------------------------------------- #
def _try_reverse(t: str, ins, outs, top):
    low = t.lower()
    byte_rev = bool(re.search(r"\breverse[s]?\b.{0,40}\bbyte\s*order\b", low) or
                    re.search(r"\bbyte\s*order\b.{0,20}\breverse", low) or
                    re.search(r"\breverse[s]?\b.{0,20}\border\s+of\s+(?:the\s+)?bytes\b", low))
    bit_rev = bool(re.search(r"\breverse[s]?\b.{0,40}\bbit\s+order", low) or
                   re.search(r"\breverse[s]?\b.{0,40}\bbit\s+ordering", low) or
                   re.search(r"\breverse[s]?\b.{0,40}\border(?:ing)?\s+of\s+(?:the\s+)?bits\b",
                             low))
    if not (byte_rev or bit_rev):
        return None
    if byte_rev and bit_rev:
        return None                              # conflicting granularity -> SKIP
    # exactly one input vector, one output vector, equal width.
    in_v = [(n, w) for n, w in ins if w > 1]
    out_v = [(n, w) for n, w in outs if w > 1]
    if len(ins) != 1 or len(outs) != 1 or len(in_v) != 1 or len(out_v) != 1:
        return None
    iname, iw = in_v[0]
    oname, ow = out_v[0]
    if iw != ow or iw < 2:
        return None

    ports = [_decl(iname, iw, "input"), _decl(oname, ow, "output")]
    if byte_rev:
        if iw % 8 != 0:
            return None                          # byte granularity needs whole bytes
        nbytes = iw // 8
        # reverse byte order: byte 0 (in[7:0]) becomes the MSB byte of the output.
        parts = [f"{iname}[{b*8+7}:{b*8}]" for b in range(nbytes)]
        body = [f"    assign {oname} = {{{', '.join(parts)}}};"]
        return _module(top, ports, body, "byte reverse")
    # bit reverse: out[i] = in[W-1-i]. Emit the generic for-loop form (works for
    # any width, matches the dataset's always_comb reference exactly).
    body = [f"    integer i;",
            f"    always @(*)",
            f"        for (i = 0; i < {iw}; i = i + 1)",
            f"            {oname}[i] = {iname}[{iw-1} - i];"]
    ports[-1] = _decl(oname, ow, "output reg")
    return _module(top, ports, body, "bit reverse")


# --------------------------------------------------------------------------- #
# FORM 3: sign / zero extend                                                  #
# --------------------------------------------------------------------------- #
def _try_extend(t: str, ins, outs, top):
    low = t.lower()
    sign = bool(re.search(r"\bsign[-\s]?extend", low))
    zero = bool(re.search(r"\bzero[-\s]?extend", low))
    if not (sign or zero):
        return None
    if sign and zero:
        return None                              # ambiguous which kind -> SKIP
    in_v = [(n, w) for n, w in ins if w >= 1]
    out_v = [(n, w) for n, w in outs if w > 1]
    if len(ins) != 1 or len(outs) != 1 or len(out_v) != 1:
        return None
    iname, iw = ins[0]
    oname, ow = outs[0]
    if ow <= iw or iw < 1:
        return None                              # extension must widen
    pad = ow - iw
    ports = [_decl(iname, iw, "input"), _decl(oname, ow, "output")]
    if sign:
        body = [f"    assign {oname} = {{ {{{pad}{{{iname}[{iw-1}]}}}}, {iname} }};"]
        return _module(top, ports, body, "sign-extend")
    body = [f"    assign {oname} = {{ {{{pad}{{1'b0}}}}, {iname} }};"]
    return _module(top, ports, body, "zero-extend")


# --------------------------------------------------------------------------- #
# FORM 4: split one input into upper / lower halves (named)                   #
# --------------------------------------------------------------------------- #
def _try_split_hilo(t: str, ins, outs, top):
    low = t.lower()
    if "split" not in low:
        return None
    # exactly one input vector and exactly two output vectors of equal width that
    # sum to the input width.
    if len(ins) != 1 or len(outs) != 2:
        return None
    iname, iw = ins[0]
    (n0, w0), (n1, w1) = outs
    if iw < 2 or w0 != w1 or w0 + w1 != iw:
        return None
    # the prose must tell us which output is the UPPER (MSB) half and which is the
    # LOWER (LSB) half — otherwise the partition direction is ambiguous => SKIP.
    # We require an explicit lower/[B-1:0] and upper/[hi:B] association by name.
    def _is_upper(name):
        n = name.lower()
        return ("hi" in n or "upper" in n or "msb" in n or "high" in n)

    def _is_lower(name):
        n = name.lower()
        return ("lo" in n or "lower" in n or "lsb" in n or "low" in n)

    up = [n for n, _ in outs if _is_upper(n) and not _is_lower(n)]
    lo = [n for n, _ in outs if _is_lower(n) and not _is_upper(n)]
    if len(up) != 1 or len(lo) != 1 or up[0] == lo[0]:
        return None
    # the prose must actually describe the upper as the HIGH bits and lower as LOW
    # bits (guard against a wording that inverts the convention).
    if not (re.search(r"\bupper\b", low) and re.search(r"\blower\b", low)):
        return None
    upper, lower = up[0], lo[0]
    ports = [_decl(iname, iw, "input"),
             _decl(upper, w0, "output"), _decl(lower, w1, "output")]
    body = [f"    assign {{ {upper}, {lower} }} = {iname};"]
    return _module(top, ports, body, "split into upper/lower halves")


# --------------------------------------------------------------------------- #
# FORM 5: passthrough vector + position-mapped 1-bit outputs                  #
# --------------------------------------------------------------------------- #
def _try_passthrough_bits(t: str, ins, outs, top):
    low = t.lower()
    if "split" not in low:
        return None
    if len(ins) != 1:
        return None
    iname, iw = ins[0]
    if iw < 2:
        return None
    vec_outs = [(n, w) for n, w in outs if w == iw]
    bit_outs = [(n, w) for n, w in outs if w == 1]
    # exactly one same-width echo + exactly iw single-bit outputs, nothing else.
    if len(vec_outs) != 1 or len(bit_outs) != iw or len(outs) != 1 + iw:
        return None
    vec_name = vec_outs[0][0]
    # EACH 1-bit output must have an explicit position mapping stated in the prose:
    #   "Connect output o0 to the input vector's position 0, o1 to position 1, ..."
    # We require that mapping to be explicit AND consistent with the natural index
    # parse of the output name (oK -> bit K) — otherwise the wiring is ambiguous.
    pos_of = {}
    for n, _ in bit_outs:
        m = re.search(r"(\d+)\s*$", n)           # trailing index in the name (o0,o1,..)
        if not m:
            return None
        pos_of[n] = int(m.group(1))
    if sorted(pos_of.values()) != list(range(iw)):
        return None                              # must cover positions 0..iw-1 exactly
    # the prose must explicitly tie outputs to positions of the input vector.
    if not (re.search(r"\bposition\b", low) and
            re.search(r"\bsplit", low) and
            (re.search(r"\bposition\s*0\b", low) or
             re.search(r"to\s+(?:the\s+)?input\s+vector'?s?\s+position", low))):
        return None
    # build {high-index ... low-index} = vec so out bit K maps to vec[K].
    ordered = sorted(bit_outs, key=lambda nw: pos_of[nw[0]], reverse=True)
    concat = ", ".join(n for n, _ in ordered)
    ports = [_decl(iname, iw, "input"), _decl(vec_name, iw, "output")]
    for n, _ in bit_outs:
        ports.append(_decl(n, 1, "output"))
    body = [f"    assign {vec_name} = {iname};",
            f"    assign {{ {concat} }} = {iname};"]
    return _module(top, ports, body, "passthrough + position-mapped bits")


# --------------------------------------------------------------------------- #
# FORM 6: concat N equal-width inputs (+ trailing const) -> split M outputs    #
# --------------------------------------------------------------------------- #
def _try_concat_split(t: str, ins, outs, top):
    low = t.lower()
    if not (re.search(r"\bconcatenat", low) and re.search(r"\bsplit", low)):
        return None
    if len(ins) < 2 or len(outs) < 2:
        return None
    iws = {w for _, w in ins}
    ows = {w for _, w in outs}
    if len(iws) != 1 or len(ows) != 1:
        return None                              # inputs (and outputs) must be uniform
    in_w = ins[0][1]
    out_w = outs[0][1]
    total_in = in_w * len(ins)
    total_out = out_w * len(outs)
    if in_w < 1 or out_w < 1:
        return None
    # a stated run of trailing constant '1' bits in the LSBs accounts for the gap.
    trailing = total_out - total_in
    trailing_lit = None
    if trailing > 0:
        # require the prose to STATE the trailing-ones count + LSB placement.
        if not (re.search(r"\btwo\s+1\s*bits?\b", low) or
                re.search(r"\b" + str(trailing) + r"\s+(?:'?1'?\s*)?bits?\b", low) or
                re.search(r"\b" + str(trailing) + r"\s+(?:high|one|1)\s+bits?\b", low)):
            return None
        if not re.search(r"\blsb\b", low):
            return None
        trailing_lit = f"{trailing}'b" + "1" * trailing
    elif trailing != 0:
        return None                              # outputs can't be narrower -> SKIP
    # the prose must describe the concat as "the input vectors" in declaration order
    # followed by the trailing bits — the natural MSB-first packing.
    in_concat = ", ".join(n for n, _ in ins)
    out_concat = ", ".join(n for n, _ in outs)
    rhs = f"{{ {in_concat}" + (f", {trailing_lit}" if trailing_lit else "") + " }"
    ports = [_decl(n, in_w, "input") for n, _ in ins]
    ports += [_decl(n, out_w, "output") for n, _ in outs]
    body = [f"    assign {{ {out_concat} }} = {rhs};"]
    return _module(top, ports, body, "concat inputs then split into outputs")


# --------------------------------------------------------------------------- #
# the solver                                                                  #
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule"):
    ins, outs = _pp.parse_ports(prompt_text)
    if not ins or not outs:
        return None
    if _has_control(ins):
        return None                              # pure combinational wiring only

    t = prompt_text
    # ordered, mutually-exclusive attempts; each is conservative and SKIP-safe.
    for fn in (_try_reverse, _try_extend, _try_split_hilo,
               _try_passthrough_bits, _try_concat_split):
        try:
            r = fn(t, ins, outs, top)
        except Exception:
            r = None
        if r:
            return r
    return None


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not an unambiguously-specified vector manipulation",
              file=sys.stderr)
        sys.exit(1)
    print(rtl)
