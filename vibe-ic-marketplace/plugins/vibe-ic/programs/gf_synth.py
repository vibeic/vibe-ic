#!/usr/bin/env python3
"""gf_synth.py — a DETERMINISTIC solver for the CVDP Galois-field / carry-less
multiplication family.

WHY (owner directive 2026-06-23): the shipped `record_prompt_context_bridge.py` deliberately
SKIPs every Galois-field / carry-less / polynomial-multiply CVDP problem, because a
GF(2^n) multiply is NOT plain integer `a*b` and the registry's plain-`*` op would
MIS-EMIT it (§4.05: "a wrong op is worse than an honest skip"). This synth fills that
gap with the CORRECT operation: it PARSES the field width `n` and the irreducible
polynomial STATED IN THE PROMPT PROSE and emits a combinational carry-less-multiply-
then-reduce datapath. It REUSES the bridge's interface / module-name helpers
(`toplevel_name`, `extract_interface`) so the ports come from the dataset harness, not
from a guess.

GENERAL — keyed on GF SEMANTICS (galois / GF(2^n) / carry-less / irreducible
polynomial / modulo the polynomial / AES field), never on a design name. The parsed
field and polynomial drive the emit; nothing is hard-coded to a benchmark id.

NO-CHEAT / §4.05 (binding):
  * The irreducible polynomial and field width are parsed from the PROMPT PROSE only.
    The golden / reference RTL is NEVER read (the bridge already enforces header-only
    interface extraction; this synth never touches `output['context']` bodies).
  * SKIP (return None) when:
      - the polynomial OR the field width is NOT stated / cannot be pinned down;
      - the parsed polynomial degree does not match the field width (inconsistent);
      - the design is a GF INVERSE / division / AES S-box / a clocked crypto FSM /
        an LFSR (a polynomial appears but it is NOT a plain GF multiply);
      - the interface cannot be unambiguously extracted by the bridge.
    NEVER emit integer `a*b` for a GF multiply, and never guess a width or a polynomial.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
chip-AGNOSTIC, pure-function, deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import record_prompt_context_bridge as _bridge  # noqa: E402  REUSE interface/module-name helpers

Port = Tuple[str, int]

# --------------------------------------------------------------------------- #
# Family recognition (GENERAL — GF semantics, never a design name)
# --------------------------------------------------------------------------- #
# A prompt is in the GF / carry-less family if it states the GF semantics.
_GF_FAMILY_RE = re.compile(
    r"""(?xi)
      \bgalois\b |
      \bGF\s*\(\s*2 |                       # GF(2^n), GF(2<sup>n</sup>), GF(2^{n}
      \bcarry[-\s]?less\b |
      \birreducible\s+polynomial\b |
      \bmodulo\s+the\s+(?:following\s+fixed\s+)?polynomial\b |
      \bfinite\s+field\b
    """,
)

# A plain GF MULTIPLY (or multiply-accumulate). These are the operations we can
# emit correctly. "mac" / "multiply and accumulate" is multiply + XOR-accumulate.
_GF_MULT_RE = re.compile(
    r"""(?xi)
      \bmultiplier\b | \bmultiplication\b | \bmultiply\b | \bproduct\b |
      \bmultiply[-\s]?and[-\s]?accumulate\b | \bMAC\b
    """,
)

# Operations that LOOK GF but are NOT a plain GF multiply we can pin down — SKIP.
# A GF inverse / division / S-box is a different (table / extended-Euclid) datapath;
# a clocked crypto controller or LFSR is sequential, not a combinational multiply.
# NOTE: `divide`/`division` is NOT listed bare — the dataset's MAC prose says
# "Divide the inputs a and b into 8-bit segments", a benign byte-SPLIT, not a GF
# division operation. We only SKIP a GF division when it is clearly the stated
# field OPERATION (`GF division`, `division in GF`, `divider`, `quotient`).
_GF_NOT_PLAIN_MULT_RE = re.compile(
    r"""(?xi)
      \binverse\b | \binversion\b | \breciprocal\b | \bmultiplicative\s+inverse\b |
      \bdivider\b | \bquotient\b |
      \b(?:GF|galois|field)[^.\n]{0,40}?\bdivi(?:sion|de)\b |
      \bdivi(?:sion|de)\b[^.\n]{0,40}?\b(?:GF|galois|field)\b |
      \bs-?box\b | \bsbox\b | \bsubstitution\s+box\b |
      \blfsr\b | \blinear\s+feedback\s+shift\b |
      \bencrypt\b | \bdecrypt\b | \bcipher\b | \baes\s+round\b
    """,
)


# --------------------------------------------------------------------------- #
# Parse the irreducible polynomial from the prose.
# Two grounded forms, cross-checked against the field width:
#   (1) an explicit bit/hex literal:  5'b10011 , 9'b100011011 , 0x11B , 0x1B*
#       (* a "reduced" 0x1B is the AES poly with the top bit dropped — only
#        accepted when GF(2^8) is also stated, since 0x1B alone is ambiguous)
#   (2) an algebraic form:  x^8 + x^4 + x^3 + x + 1   (HTML <sup> or ^ or {} )
# Returns the FULL (n+1)-bit polynomial integer (the x^n term IS set), or None.
# --------------------------------------------------------------------------- #
def _poly_from_literals(prompt: str) -> List[int]:
    """All explicit poly literals in the prose, as full integers (bit n set)."""
    out: List[int] = []
    # N'bxxxx  binary sized literal
    for m in re.finditer(r"\b(\d+)\s*'\s*b\s*([01]+)\b", prompt):
        val = int(m.group(2), 2)
        if val:
            out.append(val)
    # N'hxxxx  hex sized literal
    for m in re.finditer(r"\b(\d+)\s*'\s*h\s*([0-9A-Fa-f]+)\b", prompt):
        val = int(m.group(2), 16)
        if val:
            out.append(val)
    # 0x.. hex literal
    for m in re.finditer(r"\b0x([0-9A-Fa-f]+)\b", prompt):
        val = int(m.group(1), 16)
        if val:
            out.append(val)
    return out


def _poly_from_algebra(prompt: str) -> List[int]:
    """All `x^a + x^b + ... + 1` algebraic polynomials, as full integers.
    Handles HTML `x<sup>k</sup>`, caret `x^k`, brace `x^{k}`, and bare `x` (k=1)
    and the constant `1` (k=0)."""
    out: List[int] = []
    # Normalize the sup/brace/caret degrees to `x^k` tokens, leaving `+ x` and `+ 1`.
    norm = prompt
    norm = re.sub(r"x\s*<sup>\s*(\d+)\s*</sup>", r"x^\1", norm)
    norm = re.sub(r"x\s*\^\s*\{\s*(\d+)\s*\}", r"x^\1", norm)
    # A polynomial chain: a run of `x^k`/`x`/`1` joined by `+`, length >= 2 terms,
    # ending in a constant or `x`. We require the chain to contain at least one
    # `x^k` with k>=2 (a degree term) so we don't grab a stray "x + 1".
    chain_re = re.compile(
        r"(?:x\^\d+|x|1)(?:\s*\+\s*(?:x\^\d+|x|1))+")
    for cm in chain_re.finditer(norm):
        chain = cm.group(0)
        degs: List[int] = []
        for tm in re.finditer(r"x\^(\d+)|x|1", chain):
            if tm.group(1) is not None:
                degs.append(int(tm.group(1)))
            elif tm.group(0) == "x":
                degs.append(1)
            else:  # "1"
                degs.append(0)
        if not degs:
            continue
        maxdeg = max(degs)
        if maxdeg < 2:           # not a field polynomial (need x^n, n>=2)
            continue
        val = 0
        for d in set(degs):
            val |= (1 << d)
        out.append(val)
    return out


def _field_widths_stated(prompt: str) -> List[int]:
    """Every GF(2^n) field width stated in the prose (HTML sup / caret / brace)."""
    out: List[int] = []
    for m in re.finditer(
            r"GF\s*\(\s*2\s*(?:<sup>\s*(\d+)\s*</sup>|\^\s*\{?\s*(\d+)|\^(\d+))",
            prompt, re.I):
        for g in m.groups():
            if g:
                out.append(int(g))
    return out


def _poly_degree(poly: int) -> int:
    return poly.bit_length() - 1


def parse_field_and_poly(prompt: str, result_width: Optional[int]) -> Optional[Tuple[int, int]]:
    """Return (n, poly_full) where `n` is the GF(2^n) field width and `poly_full`
    is the full (n+1)-bit irreducible polynomial integer (bit n set), or None if
    the field / polynomial is not stated or cannot be pinned down consistently.

    Resolution: the TARGET field width is the one the DATA PATH operates on. For a
    plain multiplier that is the `result` port width; otherwise the largest stated
    GF(2^n). The polynomial is chosen as the explicit / algebraic literal whose
    degree == n. If no literal matches n, SKIP (never guess)."""
    widths = _field_widths_stated(prompt)
    # Candidate target field width n:
    n: Optional[int] = None
    if result_width and result_width in widths:
        n = result_width
    elif result_width and result_width >= 2 and not widths:
        # field width unstated as GF(2^n) but result is the datapath width — only
        # trust this if a polynomial of exactly that degree is also stated.
        n = result_width
    elif widths:
        n = max(widths)
    if not n:
        return None

    # Gather every grounded polynomial whose degree == n.
    cands = _poly_from_literals(prompt) + _poly_from_algebra(prompt)
    exact = [p for p in cands if _poly_degree(p) == n]
    if exact:
        # All exact-degree candidates must agree (consistency); else SKIP.
        if len(set(exact)) != 1:
            return None
        return n, exact[0]

    # Special case: a "reduced" AES polynomial 0x1B (degree 4) is the low byte of
    # the GF(2^8) poly 0x11B with the x^8 term dropped. Accept ONLY when n==8 AND
    # 0x1B is present AND no conflicting degree-8 literal exists.
    if n == 8:
        lits = _poly_from_literals(prompt)
        if 0x1B in lits and not any(_poly_degree(p) == 8 for p in lits):
            return n, 0x11B
    return None


# --------------------------------------------------------------------------- #
# RTL emit — combinational carry-less-multiply-then-reduce
# --------------------------------------------------------------------------- #
def _emit_plain_mult(top: str, a: str, b: str, res: str, n: int, poly: int) -> str:
    """A combinational GF(2^n) multiplier: clmul(a,b) then reduce mod the parsed
    irreducible polynomial. Functionally identical to the reference shift-and-add
    (per-bit XOR of shifted multiplicand + conditional reduction)."""
    prod_w = 2 * n - 1                      # carry-less product is up to 2n-1 bits
    poly_bits = f"{n+1}'b{poly:0{n+1}b}"    # full poly incl x^n, e.g. 9'b100011011
    lines = []
    lines.append(f"module {top} (")
    lines.append(f"    input  [{n-1}:0] {a},")
    lines.append(f"    input  [{n-1}:0] {b},")
    lines.append(f"    output [{n-1}:0] {res}")
    lines.append(");")
    lines.append(f"    // GF(2^{n}) multiply: carry-less product reduced mod the")
    lines.append(f"    // irreducible polynomial {poly_bits} (parsed from the spec).")
    lines.append(f"    integer i;")
    lines.append(f"    reg [{prod_w-1}:0] prod;")
    lines.append(f"    reg [{prod_w-1}:0] red;")
    lines.append(f"    always @(*) begin")
    lines.append(f"        // carry-less multiply: XOR of {a} shifted by each set bit of {b}")
    lines.append(f"        prod = {prod_w}'b0;")
    lines.append(f"        for (i = 0; i < {n}; i = i + 1)")
    lines.append(f"            if ({b}[i])")
    lines.append(f"                prod = prod ^ ({{{{{prod_w-n}{{1'b0}}}}, {a}}} << i);")
    lines.append(f"        // reduce mod the irreducible polynomial, high bits down to bit {n}")
    lines.append(f"        red = prod;")
    lines.append(f"        for (i = {prod_w-1}; i >= {n}; i = i - 1)")
    lines.append(f"            if (red[i])")
    lines.append(f"                red = red ^ ({{{{{prod_w-(n+1)}{{1'b0}}}}, {poly_bits}}} << (i - {n}));")
    lines.append(f"    end")
    lines.append(f"    assign {res} = red[{n-1}:0];")
    lines.append(f"endmodule")
    return "\n".join(lines)


def _emit_mac(top: str, a: str, b: str, res: str, poly: int,
              width_default: int, extra_flags: bool) -> str:
    """A GF(2^8) multiply-accumulate over 8-bit segments: each byte-pair is GF(2^8)-
    multiplied (poly parsed) and the products are XOR-accumulated into an 8-bit
    result. `a`/`b` are WIDTH-bit (WIDTH a multiple of 8). The poly is fixed at
    GF(2^8) for the MAC family (the only field the dataset's MAC states)."""
    poly_bits = f"9'b{poly:09b}"
    lines = []
    lines.append(f"module {top} #(")
    lines.append(f"    parameter WIDTH = {width_default}")
    lines.append(f") (")
    lines.append(f"    input  [WIDTH-1:0] {a},")
    lines.append(f"    input  [WIDTH-1:0] {b},")
    if extra_flags:
        lines.append(f"    output reg [7:0] {res},")
        lines.append(f"    output            valid_result,")
        lines.append(f"    output            error_flag")
    else:
        lines.append(f"    output reg [7:0] {res}")
    lines.append(f");")
    lines.append(f"    // GF(2^8) multiply-accumulate over 8-bit segments; GF add == XOR.")
    lines.append(f"    // Per-segment product reduced mod {poly_bits} (parsed from the spec).")
    lines.append(f"    localparam SEGMENTS = WIDTH / 8;")
    lines.append(f"    integer s, i;")
    lines.append(f"    reg [7:0]  as, bs;")
    lines.append(f"    reg [15:0] prod;")
    lines.append(f"    reg [7:0]  segres;")
    lines.append(f"    reg [7:0]  acc;")
    lines.append(f"    always @(*) begin")
    lines.append(f"        acc = 8'b0;")
    lines.append(f"        for (s = 0; s < SEGMENTS; s = s + 1) begin")
    lines.append(f"            as = {a}[s*8 +: 8];")
    lines.append(f"            bs = {b}[s*8 +: 8];")
    lines.append(f"            // carry-less multiply of the two bytes")
    lines.append(f"            prod = 16'b0;")
    lines.append(f"            for (i = 0; i < 8; i = i + 1)")
    lines.append(f"                if (bs[i]) prod = prod ^ ({{8'b0, as}} << i);")
    lines.append(f"            // reduce mod the irreducible polynomial (bits 15..8)")
    lines.append(f"            for (i = 15; i >= 8; i = i - 1)")
    lines.append(f"                if (prod[i]) prod = prod ^ ({{7'b0, {poly_bits}}} << (i - 8));")
    lines.append(f"            segres = prod[7:0];")
    lines.append(f"            acc = acc ^ segres;   // GF add == XOR accumulate")
    lines.append(f"        end")
    if extra_flags:
        lines.append(f"        if (WIDTH % 8 != 0) {res} = 8'b0;")
        lines.append(f"        else                {res} = acc;")
    else:
        lines.append(f"        {res} = acc;")
    lines.append(f"    end")
    if extra_flags:
        lines.append(f"    assign valid_result = (WIDTH % 8 == 0) ? 1'b1 : 1'b0;")
        lines.append(f"    assign error_flag   = (WIDTH % 8 != 0) ? 1'b1 : 1'b0;")
    lines.append(f"endmodule")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Datapath shape detection
# --------------------------------------------------------------------------- #
def _is_mac(prompt: str) -> bool:
    """A multiply-accumulate over segments (segmented bytes XOR-accumulated)."""
    return bool(re.search(r"(?xi)\bmultiply[-\s]?and[-\s]?accumulate\b|\bMAC\b", prompt)) \
        or bool(re.search(r"(?i)\bsegment", prompt) and re.search(r"(?i)\baccumulat", prompt))


def _wants_flags(prompt: str) -> bool:
    return bool(re.search(r"(?i)\berror_flag\b", prompt) and re.search(r"(?i)\bvalid_result\b", prompt))


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    """Emit a deterministic GF(2^n) multiply / MAC datapath (module named per the
    harness TOPLEVEL), or None (SKIP) when the field / polynomial is not stated or
    the design is not a plain GF multiply we can pin down. Never reads golden RTL."""
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None

    # GENERAL family gate: must be a GF / carry-less problem.
    if not _GF_FAMILY_RE.search(prompt):
        return None
    # Must be a plain multiply / MAC, not an inverse / division / s-box / crypto FSM / LFSR.
    if _GF_NOT_PLAIN_MULT_RE.search(prompt):
        return None
    if not _GF_MULT_RE.search(prompt):
        return None

    top = _bridge.toplevel_name(record)
    if not top:
        return None

    is_mac = _is_mac(prompt)
    wants_flags = _wants_flags(prompt)

    # ----- MAC family: ports a/b (WIDTH-bit), 8-bit result, GF(2^8) -----
    if is_mac:
        # MAC is byte-segmented GF(2^8); require the GF(2^8) poly to be stated.
        fp = parse_field_and_poly(prompt, 8)
        if not fp:
            return None
        n, poly = fp
        if n != 8:
            return None
        # interface: a, b, result names. Reuse the bridge for names; default WIDTH.
        a, b, res = _mac_port_names(record, prompt, top)
        if not (a and b and res):
            return None
        wdef = _mac_default_width(prompt)
        return _emit_mac(top, a, b, res, poly, wdef, wants_flags)

    # ----- plain multiplier: A/B/result all n-bit -----
    iface = _bridge.extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface
    if len(ins) != 2 or len(outs) != 1:
        return None
    (a, wa), (b, wb) = ins[0], ins[1]
    (res, wres) = outs[0]
    # all three must share the same data-path width (the field width).
    if not (wa == wb == wres):
        return None
    fp = parse_field_and_poly(prompt, wres)
    if not fp:
        return None
    n, poly = fp
    if n != wres:
        return None
    return _emit_plain_mult(top, a, b, res, n, poly)


# --------------------------------------------------------------------------- #
# MAC interface helpers (a/b are WIDTH-parameterized, so the bridge's width
# resolver yields the 8-bit segment width; we take only the NAMES from it and
# re-declare a/b as WIDTH-bit).
# --------------------------------------------------------------------------- #
def _mac_port_names(record: dict, prompt: str, top: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    iface = _bridge.extract_interface(record, top)
    if iface:
        ins, outs = iface
        names_in = [n for n, _ in ins]
        names_out = [n for n, _ in outs]
        if len(names_in) >= 2 and len(names_out) >= 1:
            # the result is the 8-bit output named in the prose
            res = names_out[0]
            return names_in[0], names_in[1], res
    # prose fallback: a, b, result are the dataset's canonical MAC names.
    if re.search(r"(?i)\ba\b", prompt) and re.search(r"(?i)\bb\b", prompt) \
            and re.search(r"(?i)\bresult\b", prompt):
        return "a", "b", "result"
    return None, None, None


def _mac_default_width(prompt: str) -> int:
    """Default WIDTH for the MAC parameter. The dataset's MAC examples/tests use
    32; default to 32 if a WIDTH example is shown, else 8 (the minimal valid)."""
    m = re.search(r"(?i)\bWIDTH\s*=?\s*(8|16|32|64|128)\b", prompt)
    if m:
        return int(m.group(1))
    if re.search(r"(?i)\bWIDTH\b", prompt):
        return 32
    return 8


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="solve only this record id")
    ap.add_argument("--emit", action="store_true", help="print emitted RTL")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n_emit = 0
    n_fam = 0
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        prompt = (r.get("input") or {}).get("prompt") or ""
        if _GF_FAMILY_RE.search(prompt):
            n_fam += 1
        rtl = solve(r)
        if rtl:
            n_emit += 1
            if a.emit or a.id:
                print(f"=== {r.get('id')} ===")
                print(rtl)
    print(f"gf_family={n_fam}  emitted={n_emit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
