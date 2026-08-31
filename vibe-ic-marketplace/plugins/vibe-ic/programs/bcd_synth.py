#!/usr/bin/env python3
"""bcd_synth.py — a DETERMINISTIC solver for the CVDP binary-coded-decimal
(BCD) family of "code generation" problems.

WHY: a BCD datapath is NOT a plain binary datapath. A BCD adder is per-nibble
`a + b`, then a `> 9` decimal correction (`+6` and a decimal carry); a
binary->BCD converter is the Double-Dabble shift-add-3; a BCD->binary converter
is the positional `100*d2 + 10*d1 + d0` weighted sum; a BCD counter is a chain
of mod-10 digits with ripple carry. The shipped registry's plain `+`/`-`/`*`
ops would MIS-EMIT every one of these (a plain 4-bit add of 9+9 is 18, not the
BCD `sum=8, cout=1`). So this solver emits the CORRECT decimal-arithmetic RTL
deterministically, recognizing the variant + the digit-count/bit-width from the
prompt prose or the embedded test-case table.

REUSE: the shipped `record_prompt_context_bridge` supplies the INTERFACE, sourced ONLY from
the model-visible surface (`input.prompt` + `input.context`) — `toplevel_name` (the
module name stated in the prompt) and `extract_interface` (the port set from the
skeleton header in `input.context` / a prose port block / a test-case table). We
import + reuse it; we never re-derive the interface plumbing, and we NEVER read the
hidden harness (cocotb `dut.<sig>`, `.env`) or golden — those are OFF-LIMITS oracle.

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding):
  * Recognize EXACTLY one of: BCD adder (per-digit add + +6 correction),
    binary->BCD (double-dabble), BCD->binary, BCD up/down counter (mod-10 digits).
  * SKIP (return None) when the variant is ambiguous OR the digit-count/bit-width
    is not pinned down from the prose/table. Never guess a width, never emit a
    plain binary add in place of a BCD add.
  * SKIP composite / extra-feature variants the canonical RTL cannot honestly
    cover (parity/error-code side outputs, dual-mode bidirectional converters,
    seven-segment/elevator wrappers, code converters like Excess-3 that are NOT
    one of the four BCD primitives). A wrong emit is worse than an honest skip.
  * Never read the golden/reference RTL. The skeleton header is parsed for PORTS
    ONLY (via the bridge), never the body/logic.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
chip-AGNOSTIC (no design-name keys), pure-function, deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import record_prompt_context_bridge as _bridge  # noqa: E402  INTERFACE + module-name extraction

Port = Tuple[str, int]


# --------------------------------------------------------------------------- #
# §4.05 up-front SKIP cues — extra-feature / non-primitive / composite BCD shapes
# the canonical RTL would NOT functionally cover. Keyed on stated SEMANTICS, never
# on a design name.
# --------------------------------------------------------------------------- #
# A code converter that is NOT one of the four BCD arithmetic primitives (e.g.
# BCD<->Excess-3, BCD<->Gray, seven-segment decode).
_NON_PRIMITIVE_RE = re.compile(
    r"""(?xi)
      excess-?3 | \bexcess\s+3\b | \bgray\b | seven-?segment | seven\s+seg |
      \bsegment\b | \belevator\b | \banode\b | \bcathode\b
    """,
)
# Extra side-band outputs / dual-mode the bare primitive does not have.
_EXTRA_FEATURE_RE = re.compile(
    r"""(?xi)
      \bparity\b | \berror[_\s-]?code\b | \berror\s+report | \binvalid\b |
      \bbidirectional\b | \btwo-?way\b | \bdual-?mode\b | \bswitch\b
    """,
)


# --------------------------------------------------------------------------- #
# variant recognition (mutually-exclusive; positive-signature wins)
# --------------------------------------------------------------------------- #
def _classify(prompt: str) -> Optional[str]:
    """Return one of 'bcd_adder' | 'bin2bcd' | 'bcd2bin' | 'bcd_counter', or None.
    Recognition is from the stated OPERATION; ambiguity returns None (SKIP)."""
    p = prompt.lower()
    has_bcd = bool(re.search(r"\bbcd\b|binary[-\s]?coded[-\s]?decimal", p))
    if not has_bcd:
        return None

    double_dabble = bool(re.search(r"double[-\s]?dabble", p))
    # direction cues
    bin2bcd = bool(re.search(r"binary[-\s]?(?:in|input|number|value)?\s*(?:to|->|2)\s*bcd"
                             r"|\bbinary[-\s]?to[-\s]?bcd\b", p)) or double_dabble
    bcd2bin = bool(re.search(r"bcd\s*(?:to|->|2)\s*binary|\bbcd[-\s]?to[-\s]?binary\b", p))
    is_adder = bool(re.search(r"\bbcd\b[^\n]*\badder\b|\badder\b[^\n]*\bbcd\b"
                              r"|add(?:ing|ition)?[^\n]*\bbcd\b", p)) and not (bin2bcd or bcd2bin)
    is_counter = bool(re.search(r"\bbcd\b[^\n]*\bcounter\b|\bcounter\b[^\n]*\bbcd\b"
                                r"|\bup[-\s]?down\b[^\n]*\bbcd\b", p))

    # A bidirectional converter mentions BOTH directions -> ambiguous primitive.
    if bin2bcd and bcd2bin:
        return None
    votes = []
    if is_adder:
        votes.append("bcd_adder")
    if bin2bcd:
        votes.append("bin2bcd")
    if bcd2bin:
        votes.append("bcd2bin")
    if is_counter:
        votes.append("bcd_counter")
    if len(votes) != 1:
        return None
    return votes[0]


# --------------------------------------------------------------------------- #
# deterministic RTL emitters (module named per the prompt TOPLEVEL)
# --------------------------------------------------------------------------- #
def _emit_bcd_adder(top: str, ins: List[Port], outs: List[Port]) -> Optional[str]:
    """Per-digit BCD add: out_sum = (a+b)%10, carry = (a+b) >= 10.
    Supports an optional carry-in input and N concatenated 4-bit BCD digits."""
    # data inputs: the two operands (4-bit each, or N*4 for multi-digit).
    cin = next((n for n, _ in ins if re.fullmatch(r"(?i)c_?in|carry_?in|cin", n)), None)
    data_in = [(n, w) for n, w in ins if n != cin]
    if len(data_in) != 2:
        return None
    (a, wa), (b, wb) = data_in
    if wa != wb or wa % 4 != 0:
        return None
    ndig = wa // 4
    if ndig < 1:
        return None
    # outputs: a sum bus (== operand width) + an optional 1-bit carry-out.
    cout = next((n for n, w in outs if w == 1
                 and re.search(r"(?i)c_?out|carry_?out|cout|carry", n)), None)
    sums = [(n, w) for n, w in outs if n != cout]
    if len(sums) != 1:
        return None
    sname, sw = sums[0]
    if sw != wa:
        return None

    lines = [f"module {top} (",
             f"    input  [{wa-1}:0] {a},",
             f"    input  [{wb-1}:0] {b},"]
    if cin:
        lines.append(f"    input  {cin},")
    lines.append(f"    output reg [{sw-1}:0] {sname}" + ("," if cout else ""))
    if cout:
        lines.append(f"    output reg {cout}")
    lines.append(");")
    lines.append("    integer i;")
    lines.append("    reg [4:0] digsum;")
    lines.append("    reg carry;")
    lines.append("    always @(*) begin")
    carry_init = cin if cin else "1'b0"
    lines.append(f"        carry = {carry_init};")
    for d in range(ndig):
        hi, lo = d * 4 + 3, d * 4
        lines.append(f"        digsum = {a}[{hi}:{lo}] + {b}[{hi}:{lo}] + carry;")
        lines.append("        if (digsum > 5'd9) begin")
        lines.append(f"            {sname}[{hi}:{lo}] = digsum[3:0] + 4'd6;")
        lines.append("            carry = 1'b1;")
        lines.append("        end else begin")
        lines.append(f"            {sname}[{hi}:{lo}] = digsum[3:0];")
        lines.append("            carry = 1'b0;")
        lines.append("        end")
    if cout:
        lines.append(f"        {cout} = carry;")
    lines.append("    end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def _emit_bin2bcd(top: str, ins: List[Port], outs: List[Port]) -> Optional[str]:
    """Binary -> BCD via Double-Dabble. Input is W-bit binary; output is
    ceil-decimal-digits * 4 BCD. The BCD width is taken from the output port."""
    data_in = [(n, w) for n, w in ins
               if not re.fullmatch(r"(?i)clk|clock|rst|reset|rst_n|resetn|enable|en", n)]
    if len(data_in) != 1:
        return None
    bname, bw = data_in[0]
    data_out = [(n, w) for n, w in outs if w > 1]
    if len(data_out) != 1:
        return None
    oname, ow = data_out[0]
    if ow % 4 != 0:
        return None
    ndig = ow // 4
    # The shift register holds [BCD | binary]; total = ow + bw.
    total = ow + bw

    lines = [f"module {top} (",
             f"    input  [{bw-1}:0] {bname},",
             f"    output reg [{ow-1}:0] {oname}",
             ");",
             "    integer i, j;",
             f"    reg [{total-1}:0] shift_reg;",
             "    always @(*) begin",
             f"        shift_reg = {{{ow}'d0, {bname}}};",
             f"        for (i = 0; i < {bw}; i = i + 1) begin",
             f"            for (j = 0; j < {ndig}; j = j + 1) begin",
             f"                if (shift_reg[{bw} + j*4 +: 4] >= 4'd5)",
             f"                    shift_reg[{bw} + j*4 +: 4] = shift_reg[{bw} + j*4 +: 4] + 4'd3;",
             "            end",
             f"            shift_reg = shift_reg << 1;",
             "        end",
             f"        {oname} = shift_reg[{total-1}:{bw}];",
             "    end",
             "endmodule"]
    return "\n".join(lines) + "\n"


def _emit_bcd2bin(top: str, ins: List[Port], outs: List[Port]) -> Optional[str]:
    """BCD -> binary via positional weighting: sum_{k} d_k * 10^k.
    Input is N*4-bit BCD; output is the binary value."""
    data_in = [(n, w) for n, w in ins
               if not re.fullmatch(r"(?i)clk|clock|rst|reset|rst_n|resetn|enable|en", n)]
    if len(data_in) != 1:
        return None
    bname, bw = data_in[0]
    if bw % 4 != 0:
        return None
    ndig = bw // 4
    data_out = [(n, w) for n, w in outs if w > 1]
    if len(data_out) != 1:
        return None
    oname, ow = data_out[0]

    terms = []
    weight = 1
    for d in range(ndig):
        hi, lo = d * 4 + 3, d * 4
        if weight == 1:
            terms.append(f"{bname}[{hi}:{lo}]")
        else:
            terms.append(f"{bname}[{hi}:{lo}] * {weight}")
        weight *= 10
    expr = " + ".join(terms)
    lines = [f"module {top} (",
             f"    input  [{bw-1}:0] {bname},",
             f"    output [{ow-1}:0] {oname}",
             ");",
             f"    assign {oname} = {expr};",
             "endmodule"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    """Emit deterministic BCD RTL (module named per harness TOPLEVEL) for a
    recognizable single-primitive BCD problem, or None (SKIP)."""
    if not isinstance(record, dict):
        return None
    top = _bridge.toplevel_name(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None

    variant = _classify(prompt)
    if not variant:
        return None

    # §4.05: SKIP non-primitive code converters / extra-feature / dual-mode shapes.
    if _NON_PRIMITIVE_RE.search(prompt) or _EXTRA_FEATURE_RE.search(prompt):
        return None

    # BCD counter (mod-10 digit chain) is a sequential, design-specific shape
    # (24h clock, configurable rollover, up/down). It is NOT a single pinned-down
    # combinational primitive here — SKIP rather than guess the rollover policy.
    if variant == "bcd_counter":
        return None

    # Interface (port names + widths) from input.prompt + input.context ONLY —
    # never the hidden harness (cocotb dut.<sig> / .env) or golden (OFF-LIMITS
    # oracle). If the interface is not prompt-derivable -> honest §4.05 SKIP.
    iface = _bridge.extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface
    if not ins or not outs:
        return None

    if variant == "bcd_adder":
        return _emit_bcd_adder(top, ins, outs)
    if variant == "bin2bcd":
        return _emit_bin2bcd(top, ins, outs)
    if variant == "bcd2bin":
        return _emit_bcd2bin(top, ins, outs)
    return None


def variant_of(record: dict) -> Optional[str]:
    """The BCD variant this solver would emit for the record (for reporting)."""
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    v = _classify(prompt)
    if not v:
        return None
    if _NON_PRIMITIVE_RE.search(prompt) or _EXTRA_FEATURE_RE.search(prompt):
        return None
    if v == "bcd_counter":
        return None
    return v if solve(record) else None


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
    fam: Dict[str, int] = {}
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n_emit += 1
            k = variant_of(r)
            fam[k] = fam.get(k, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  variant={k} ===")
                print(rtl)
    print(f"emitted={n_emit}/{len(recs)}  variants={fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
