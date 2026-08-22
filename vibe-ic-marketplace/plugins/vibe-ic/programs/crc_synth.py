#!/usr/bin/env python3
"""crc_synth.py — a DETERMINISTIC solver for the CVDP CRC family.

WHY: a CRC generator/checker is a closed-form shift-register datapath fully
determined by FOUR convention parameters — the CRC WIDTH, the generator
POLYNOMIAL, the INIT (seed) value, and the reflect-in / reflect-out / final-XOR
conventions. When those are STATED in the CVDP prose, the RTL is deterministic:
there is exactly one correct serial (bit-by-bit) shift-register CRC, and exactly
one correct unrolled parallel form. This module parses the stated convention from
the prompt and emits that datapath, named per the harness TOPLEVEL with ports
taken from the shipped `cvdp_atomic_bridge` interface extractor.

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding):
  CRC is *extremely* convention-sensitive: a wrong reflect or a wrong init
  SILENTLY produces a plausible-but-wrong checksum that no smoke test catches.
  So this solver SKIPS (returns None) unless the polynomial AND the width are
  BOTH unambiguously stated, and unless the reflect/init conventions are either
  explicitly stated or unambiguous by the cited algorithm. It never guesses a
  polynomial, never guesses a width, never guesses a reflect convention. A wrong
  CRC is far worse than an honest skip.

  Recognized SKIP triggers:
    * no polynomial stated, or the polynomial is parameterized/unknown        -> SKIP
    * no CRC width stated (and not derivable from the stated polynomial width) -> SKIP
    * reflect-in / reflect-out mentioned but not pinned to a definite value    -> SKIP
    * the design is a COMPOSITE (CRC is one sub-module of a larger top whose
      other sub-modules — ECC/SIPO/FSM/checksum-FSM — the harness also drives)  -> SKIP

GENERAL: keyed on CRC SEMANTICS (polynomial / shift-register / reflect / init),
never on a design name. chip-AGNOSTIC, pure-function, deterministic.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
Also exposes pure helpers used by the solver and the tests:
    parse_crc_spec(prompt) -> Optional[CrcSpec]
    python_crc(spec, data, data_width) -> int       # the golden reference value
    emit_crc_rtl(spec, top, data_port, out_port, ...) -> str
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cvdp_atomic_bridge as _bridge  # noqa: E402  INTERFACE + module-name source

from _prose_polarity import LINE_END_BREAKS, is_denied, sentence_scope

Port = Tuple[str, int]


# --------------------------------------------------------------------------- #
# Composite SKIP — a CRC that is ONE sub-module of a larger top (the harness
# drives the WHOLE top: SIPO + ECC + checksum-FSM + ...) is NOT a stand-alone
# CRC datapath this solver can emit. Keyed on co-resident sub-function vocabulary,
# never on a design name.
# --------------------------------------------------------------------------- #
_COMPOSITE_CRC_RE = re.compile(
    r"""(?xi)
      \bhamming\b | \becc\b | \bsyndrome\b |
      \bsipo\b | \bserial[-\s]?in[-\s]?parallel | \bpiso\b |
      \bfsm\b | \bstate\s+machine\b | \bpacket\b | \bopcode\b |
      \buart\b | \bspi\b | \bi2c\b | \baxi\b | \bfifo\b |
      \bconsists?\s+of\s+\d+\s+modules? | \bsub-?modules?\b | \btop\s+module\b
    """,
)

# CRC recognition — must name CRC AND show shift-register / polynomial semantics.
_CRC_NOUN_RE = re.compile(r"(?i)\bcrc\b|cyclic\s+redundancy")
_CRC_DATAPATH_RE = re.compile(
    r"(?i)crc_reg|crc\s*register|<<\s*1|polynomial|\bpoly\b|x\s*\^|generator\s+poly")


# --------------------------------------------------------------------------- #
# CRC convention spec
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CrcSpec:
    width: int          # CRC register width in bits
    poly: int           # generator polynomial (low `width` bits; non-reflected form)
    init: int           # initial CRC register value (seed)
    reflect_in: bool    # reflect each input bit-group LSB-first
    reflect_out: bool   # reflect the final CRC
    xor_out: int        # final XOR applied to the CRC


# --------------------------------------------------------------------------- #
# numeric-literal parse (Verilog `W'bxxxx` / `W'hxx` / `0x..` / `x^..+1` form)
# --------------------------------------------------------------------------- #
def _verilog_literal(tok: str) -> Optional[Tuple[int, Optional[int]]]:
    """Parse a Verilog-style sized literal -> (value, declared_width|None)."""
    m = re.fullmatch(r"\s*(\d+)?'\s*([bBhHdHoO])\s*([0-9a-fA-F_]+)\s*", tok)
    if not m:
        return None
    wdec = int(m.group(1)) if m.group(1) else None
    base = m.group(2).lower()
    digits = m.group(3).replace("_", "")
    try:
        val = int(digits, {"b": 2, "o": 8, "d": 10, "h": 16}[base])
    except ValueError:
        return None
    return val, wdec


def _poly_from_powers(expr: str) -> Optional[Tuple[int, int]]:
    """Parse `x^16 + x^12 + x^5 + 1` -> (poly_value, degree).
    The leading x^N sets the degree; the generator value used in the W-bit shift
    register is the polynomial WITHOUT the top x^N term (the implicit msb)."""
    powers = []
    for m in re.finditer(r"x\s*\^?\s*(\d+)|(?<![\w^])\b1\b", expr):
        if m.group(1) is not None:
            powers.append(int(m.group(1)))
        else:
            powers.append(0)
    if not powers:
        return None
    deg = max(powers)
    if deg < 1:
        return None
    val = 0
    for p in powers:
        if p < deg:            # drop the implicit top x^deg term
            val |= (1 << p)
    return val, deg


# --------------------------------------------------------------------------- #
# parse the CRC convention from the prompt (PARSE-OR-SKIP)
# --------------------------------------------------------------------------- #
_WIDTH_RE = re.compile(
    r"(?i)\bCRC[_\s-]*WIDTH\b\s*[:=]?\s*\(?\s*(\d+)|"
    r"\bCRC[-_\s]?(\d+)\b|"
    r"\b(\d+)\s*-?\s*bit\s+CRC\b")


def _parse_width(prompt: str) -> Optional[int]:
    m = _WIDTH_RE.search(prompt)
    if not m:
        return None
    for g in m.groups():
        if g:
            return int(g)
    return None


def _first_live(pattern: str, prompt: str):
    """The first match of `pattern` in `prompt` that is NOT denied, or None.

    ONE HELPER FOR EVERY READ IN THIS FILE (vibe-ic#712). The polynomial was
    guarded first and its siblings were not, which is the divergence this whole
    class of repair exists to answer: two readers of one document disagreeing
    about a denial. A prompt states a retired CRC convention as readily as a
    live one --

        "The init value 0xFFFFFFFF is no longer used; use 0x0000."  -> 0xFFFFFFFF
        "reflect_in = true is no longer used."                      -> reflect_in

    -- and each of those builds a CRC that computes a different remainder and
    does not interoperate with the thing it exists to talk to.

    A denied match does not END the search: a prompt that retires one convention
    and states another must yield the second, not nothing.
    """
    for m in re.finditer(pattern, prompt):
        lo, hi = sentence_scope(prompt, m.start(), m.end(),
                                extra_breaks=LINE_END_BREAKS)
        if is_denied(prompt[lo:hi]):
            continue
        return m
    return None


def _parse_poly(prompt: str) -> Optional[Tuple[int, Optional[int]]]:
    """Return (poly_value, implied_width|None) or None. Tries, in order:
    a stated `POLY[=:] <literal>`, a `polynomial 0x..`, an `x^..+..+1` form."""
    # POLY = 8'b10101010  /  POLY: 0xAA  /  generator polynomial = 16'h1021
    # POLARITY (vibe-ic#712). A prompt is written by a person, and a person
    # retires a polynomial as readily as they state one:
    #
    #     "The polynomial 0x04C11DB7 is no longer used; use 0x1021."
    #
    # returned 0x04C11DB7. A CRC built on the retired polynomial computes a
    # different remainder and will not interoperate with the thing it is for.
    #
    # `finditer`, not `search`: a denied statement must not END the search, or a
    # prompt that retires one polynomial and gives another yields nothing.
    m = _first_live(
        r"(?i)\b(?:POLY|polynomial|generator\s+poly\w*)\b[^\n]*?"
        r"((?:\d+)?'[bBhHdHoO][0-9a-fA-F_]+|0x[0-9a-fA-F]+|\bx\s*\^[^\n]*?\b1\b)",
        prompt)
    if not m:
        return None
    tok = m.group(1).strip()
    # x^.. power form
    if tok.lower().startswith("x") or "x^" in tok.lower():
        pf = _poly_from_powers(tok)
        if pf:
            return pf[0], pf[1]
        return None
    # 0x.. plain hex
    hm = re.fullmatch(r"0x([0-9a-fA-F]+)", tok)
    if hm:
        return int(hm.group(1), 16), len(hm.group(1)) * 4
    # Verilog sized literal
    vl = _verilog_literal(tok)
    if vl:
        val, wdec = vl
        return val, wdec
    return None


def _parse_init(prompt: str) -> Optional[int]:
    """Init/seed value. A clearly stated 'init=', 'initial value', or the cited
    algorithm's 'crc_reg = 0' / 'when reset crc_out will be zero' => 0."""
    m = _first_live(
        r"(?i)\b(?:init(?:ial)?(?:\s+value)?|seed)\b\s*[:=]?\s*"
        r"((?:\d+)?'[bBhHdHoO][0-9a-fA-F_]+|0x[0-9a-fA-F]+|\d+)",
        prompt)
    if m:
        tok = m.group(1)
        vl = _verilog_literal(tok)
        if vl:
            return vl[0]
        if tok.lower().startswith("0x"):
            return int(tok, 16)
        if tok.isdigit():
            return int(tok)
    # the sipo-style cited algorithm: crc_reg starts at 0 (reset => crc zero, the
    # iteration table starts the register at all-zeros).
    if re.search(r"(?i)crc[_\s]*(?:reg|out)\b[^\n]*?\b(?:zero|0+)\b", prompt) and \
       re.search(r"(?i)\bcrc_reg\b\s*(?:\(before\)|=)\s*0", prompt):
        return 0
    if re.search(r"(?i)when\s+(?:high|reset).{0,40}?crc_out\s+will\s+be\s+zero", prompt):
        return 0
    return None


def _parse_reflect_xor(prompt: str) -> Optional[Tuple[bool, bool, int]]:
    """Return (reflect_in, reflect_out, xor_out) or None if reflect is mentioned
    but ambiguous. If reflect/xor are NOT mentioned at all, the cited MSB-first
    shift-register algorithm has reflect=False and xor_out=0 (unambiguous)."""
    mentions_reflect = re.search(r"(?i)\breflect|\brefin\b|\brefout\b|\bmirror", prompt)
    if mentions_reflect:
        # reflect mentioned -> require an explicit boolean pin for BOTH or SKIP.
        rin = _first_live(r"(?i)\b(?:reflect[_\s]?in|refin)\b\s*[:=]?\s*"
                        r"(true|false|1|0|yes|no)", prompt)
        rout = _first_live(r"(?i)\b(?:reflect[_\s]?out|refout)\b\s*[:=]?\s*"
                         r"(true|false|1|0|yes|no)", prompt)
        if not (rin and rout):
            return None  # ambiguous reflect -> SKIP
        truthy = {"true", "1", "yes"}
        ri = rin.group(1).lower() in truthy
        ro = rout.group(1).lower() in truthy
    else:
        ri = ro = False
    # final XOR
    xo = 0
    xm = re.search(r"(?i)\b(?:xor[_\s]?out|final[_\s]?xor)\b\s*[:=]?\s*"
                   r"((?:\d+)?'[bBhHdHoO][0-9a-fA-F_]+|0x[0-9a-fA-F]+|\d+)", prompt)
    if xm:
        tok = xm.group(1)
        vl = _verilog_literal(tok)
        if vl:
            xo = vl[0]
        elif tok.lower().startswith("0x"):
            xo = int(tok, 16)
        elif tok.isdigit():
            xo = int(tok)
    return ri, ro, xo


def parse_crc_spec(prompt: str) -> Optional[CrcSpec]:
    """Parse a fully-determined CRC convention from the prompt, or None (SKIP).
    Requires: it READS as a CRC, width + poly BOTH stated, init stated/zero,
    reflect unambiguous."""
    if not prompt or not _CRC_NOUN_RE.search(prompt):
        return None
    if not _CRC_DATAPATH_RE.search(prompt):
        return None
    pp = _parse_poly(prompt)
    if pp is None:
        return None
    poly, poly_w = pp
    width = _parse_width(prompt)
    if width is None:
        width = poly_w               # derive from a sized polynomial literal
    if width is None or width <= 0 or width > 256:
        return None
    # the generator value must fit in `width` bits (drop an implicit msb if the
    # x^.. form gave the full degree+1 representation).
    poly &= (1 << width) - 1
    if poly == 0:
        return None
    init = _parse_init(prompt)
    if init is None:
        return None
    init &= (1 << width) - 1
    rx = _parse_reflect_xor(prompt)
    if rx is None:
        return None
    reflect_in, reflect_out, xor_out = rx
    xor_out &= (1 << width) - 1
    return CrcSpec(width=width, poly=poly, init=init,
                   reflect_in=reflect_in, reflect_out=reflect_out, xor_out=xor_out)


# --------------------------------------------------------------------------- #
# golden reference (Python) — the SAME serial MSB-first shift-register CRC the
# RTL implements; used to cross-check.
# --------------------------------------------------------------------------- #
def _reflect(val: int, width: int) -> int:
    out = 0
    for i in range(width):
        if val & (1 << i):
            out |= 1 << (width - 1 - i)
    return out


def python_crc(spec: CrcSpec, data: int, data_width: int) -> int:
    """Compute the CRC of `data` (data_width bits) under `spec`, the canonical
    serial MSB-first shift register:
        for each data bit (MSB first):
            top = crc[width-1] ^ data_bit
            crc <<= 1
            if top: crc ^= poly
    with optional input reflection (process bits LSB-first), output reflection,
    and final XOR. This mirrors the emitted RTL exactly."""
    mask = (1 << spec.width) - 1
    crc = spec.init & mask
    bit_order = range(data_width) if spec.reflect_in else range(data_width - 1, -1, -1)
    for i in bit_order:
        dbit = (data >> i) & 1
        top = ((crc >> (spec.width - 1)) & 1) ^ dbit
        crc = (crc << 1) & mask
        if top:
            crc ^= spec.poly
    if spec.reflect_out:
        crc = _reflect(crc, spec.width)
    crc ^= spec.xor_out
    return crc & mask


# --------------------------------------------------------------------------- #
# RTL emit — purely combinational unrolled serial CRC over `data_width` bits.
# --------------------------------------------------------------------------- #
def emit_crc_rtl(spec: CrcSpec, top: str, data_port: str, out_port: str,
                 data_width: int, extra_ins: Optional[List[Port]] = None) -> str:
    mask_hex_w = (spec.width + 3) // 4
    poly_lit = f"{spec.width}'h{spec.poly:0{mask_hex_w}x}"
    init_lit = f"{spec.width}'h{spec.init:0{mask_hex_w}x}"
    xor_lit = f"{spec.width}'h{spec.xor_out:0{mask_hex_w}x}"
    w = spec.width

    lines: List[str] = []
    lines.append(f"// Auto-emitted deterministic CRC datapath (crc_synth).")
    lines.append(f"// width={w} poly={poly_lit} init={init_lit} "
                 f"reflect_in={int(spec.reflect_in)} reflect_out={int(spec.reflect_out)} "
                 f"xor_out={xor_lit}")
    lines.append(f"module {top} (")
    lines.append(f"    input  wire [{data_width-1}:0] {data_port},")
    if extra_ins:
        for n, bw in extra_ins:
            rng = f"[{bw-1}:0] " if bw > 1 else ""
            lines.append(f"    input  wire {rng}{n},")
    lines.append(f"    output wire [{w-1}:0] {out_port}")
    lines.append(");")
    lines.append(f"    function [{w-1}:0] crc_calc;")
    lines.append(f"        input [{data_width-1}:0] d;")
    lines.append(f"        reg [{w-1}:0] crc;")
    lines.append(f"        integer i;")
    lines.append(f"        reg top_bit;")
    lines.append(f"        begin")
    lines.append(f"            crc = {init_lit};")
    if spec.reflect_in:
        rng_for = f"i = 0; i < {data_width}; i = i + 1"
    else:
        rng_for = f"i = {data_width-1}; i >= 0; i = i - 1"
    lines.append(f"            for ({rng_for}) begin")
    lines.append(f"                top_bit = crc[{w-1}] ^ d[i];")
    lines.append(f"                crc = crc << 1;")
    lines.append(f"                if (top_bit) crc = crc ^ {poly_lit};")
    lines.append(f"            end")
    if spec.reflect_out:
        lines.append(f"            begin : refl")
        lines.append(f"                reg [{w-1}:0] r; integer j;")
        lines.append(f"                r = {w}'d0;")
        lines.append(f"                for (j = 0; j < {w}; j = j + 1) r[{w-1}-j] = crc[j];")
        lines.append(f"                crc = r;")
        lines.append(f"            end")
    if spec.xor_out:
        lines.append(f"            crc = crc ^ {xor_lit};")
    lines.append(f"            crc_calc = crc;")
    lines.append(f"        end")
    lines.append(f"    endfunction")
    lines.append(f"    assign {out_port} = crc_calc({data_port});")
    lines.append(f"endmodule")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# interface — reuse the shipped bridge extractor; pick the data-in / crc-out port
# --------------------------------------------------------------------------- #
def _pick_ports(ins: List[Port], outs: List[Port], width: int
                ) -> Optional[Tuple[str, int, str, List[Port]]]:
    """Choose (data_port, data_width, out_port, extra_ins). The CRC OUT port is
    the output whose width == the CRC width; the DATA port is the widest input
    that is not a clock/reset/control. SKIP (None) if either can't be pinned."""
    seq = _bridge._SEQ_PORTS
    data_candidates = [(n, w) for n, w in ins
                       if n.lower() not in seq and w > 1]
    if not data_candidates:
        return None
    data_port, data_w = max(data_candidates, key=lambda nw: nw[1])
    out_match = [(n, w) for n, w in outs if w == width]
    if not out_match:
        out_match = [(n, w) for n, w in outs if w > 1]
    if not out_match:
        return None
    out_port = out_match[0][0]
    extra = [(n, w) for n, w in ins
             if n != data_port and n.lower() not in seq]
    return data_port, data_w, out_port, extra


# --------------------------------------------------------------------------- #
# solve()
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    """Emit a deterministic CRC datapath (module named per harness TOPLEVEL) for
    a stand-alone CRC generator/checker whose convention is fully stated, else
    None (SKIP)."""
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    # must read as a CRC at all
    if not _CRC_NOUN_RE.search(prompt):
        return None
    # §4.05: a CRC embedded in a larger composite top is not a stand-alone CRC.
    if _COMPOSITE_CRC_RE.search(prompt):
        return None
    spec = parse_crc_spec(prompt)
    if spec is None:
        return None
    top = _bridge.toplevel_name(record)
    if not top:
        return None
    iface = _bridge.extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface
    picked = _pick_ports(ins, outs, spec.width)
    if picked is None:
        return None
    data_port, data_w, out_port, extra = picked
    return emit_crc_rtl(spec, top, data_port, out_port, data_w, extra_ins=extra)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--id")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    found = emitted = 0
    ids: List[str] = []
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        prompt = (r.get("input") or {}).get("prompt") or ""
        if _CRC_NOUN_RE.search(prompt):
            found += 1
        rtl = solve(r)
        if rtl:
            emitted += 1
            ids.append(r.get("id"))
            if a.emit or a.id:
                print(f"=== {r.get('id')} ===")
                print(rtl)
    print(f"found={found}  emitted={emitted}  ids={ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
