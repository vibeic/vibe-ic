#!/usr/bin/env python3
"""arith_ext_synth.py — a deterministic SOLVER for the one integer-arithmetic
FORM the shipped arithmetic_synth.py does not yet cover: the N-bit ripple/parallel
ADDER with a carry-in input and a SEPARATE carry-out output.

arithmetic_synth's FORMs cover the scalar half/full adder, the N-bit adder whose
SINGLE (N+1)-bit output packs the carry, the signed two's-complement adder with a
signed-overflow FLAG, and add/subtract-by-control. The RTLLM `adder_8bit` /
`adder_16bit` family states a DIFFERENT, equally-deterministic structure:

    two N-bit operands  (a[N-1:0], b[N-1:0]),
    a 1-bit carry-in    (cin / Cin / ...),            <- optional
    an N-bit sum output (sum / y / ...),
    a 1-bit carry-out   (cout / Co / C... / ...).

The function is fixed with NO hidden information: {cout, sum} = a + b + cin.
When the prompt additionally mandates bit-level full adders, repeated sub-adder
blocks, or carry-lookahead hierarchy, that architecture is part of the contract
and is emitted structurally. Detection is keyed on the declared interface and
prompt-visible architecture, never on a design name or hidden testbench.

§4.05 NO-LEAK — return None (SKIP) unless EVERY condition holds; a wrong adder is
far worse than an honest skip:
  * SKIP on any out-of-scope / different-function cue in the prose: BCD, two's-
    complement signed-overflow flag, pipeline/stage/clock, subtract, multiply,
    divide, modulo, shifter, accumulate (those are other solvers / floors).
  * SKIP unless there are EXACTLY two equal-width (>=2-bit) data operands.
  * SKIP unless there is EXACTLY one N-bit sum output AND exactly one 1-bit
    carry-out output (the separate-carry-out structure that distinguishes this
    FORM from arithmetic_synth's packed-(N+1)-bit FORM C).
  * SKIP on 0-or->1 carry-in candidates, or a carry-in wider than 1 bit.

API: synth(prompt_text, ins, outs, top) -> str | None. `ins`/`outs` are the shared
port_parser's [(name,width)] lists (the caller bridges the RTLLM prose first).
chip-AGNOSTIC, deterministic, pure over the declared interface + scope prose.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

Port = Tuple[str, int]

# Any of these in the prose means a DIFFERENT function / a sequential design / an
# out-of-scope op -> this combinational ripple-adder solver SKIPs.
# NOTE: every alternative is anchored to a WORD that signals a different function /
# a sequential design / an out-of-scope op. They are deliberately specific so they
# never false-match the boilerplate that appears in EVERY RTLLM prompt — in
# particular `\bmodulo\b` (NOT `\bmodul`, which would hit the "Module name:" header)
# and `\bpipelined?\b` (NOT `\bpipelin`, kept here as the explicit word).
_OUT_OF_SCOPE = re.compile(
    r"""(?xi)
      \bbcd\b | \bbinary[-\s]coded[-\s]decimal\b |
      two'?s[-\s]?complement | 2'?s[-\s]?complement | signed\s+overflow |
      \bpipelined?\b | \bposedge\b | \bnegedge\b | \bclock\b | \bclk\b |
      \bsubtract(?:ion|or)?\b | \bborrow\b |
      \bmultipl(?:y|i\w*)\b | \bdivide\b | \bdivision\b | \bdivider\b |
      \bmodulo\b | \bmodulus\b |
      \bshift\w* | \bbarrel\b | \baccumulat\w* | \bfloat\w* | \bfixed[-\s]point\b
    """,
)

_CIN_NAMES = {"cin", "carry_in", "carryin", "ci", "c_in"}
_COUT_NAMES = {"cout", "carry_out", "carryout", "co", "c_out", "c32", "c33", "c"}
# a carry-out can also be a single short name like Co/C32; we additionally accept a
# 1-bit output whose name STARTS with 'c' and is not a data word, as a fallback.


def _is_cout(name: str, width: int) -> bool:
    if width != 1:
        return False
    n = name.lower()
    if n in _COUT_NAMES:
        return True
    # fallback: a 1-bit output named like a carry (c<digits> e.g. C32) — only when
    # it is a SINGLE leading-c token, never a data word.
    return bool(re.fullmatch(r"c(arry)?\d*", n))


def _emit_full_adder_chain(top, a, b, cin, s, co, width):
    fa = f"{top}_full_adder"
    return f"""module {fa}(input a, input b, input cin, output sum, output cout);
    assign sum = a ^ b ^ cin;
    assign cout = (a & b) | (a & cin) | (b & cin);
endmodule

module {top} (
    input [{width-1}:0] {a}, input [{width-1}:0] {b}, input {cin},
    output [{width-1}:0] {s}, output {co}
);
    wire [{width}:0] carry;
    assign carry[0] = {cin};
    genvar i;
    generate for (i=0; i<{width}; i=i+1) begin : gen_full_adder
        {fa} u_fa(.a({a}[i]),.b({b}[i]),.cin(carry[i]),
                  .sum({s}[i]),.cout(carry[i+1]));
    end endgenerate
    assign {co} = carry[{width}];
endmodule
"""


def _emit_block_adder(top, a, b, cin, s, co, width, block_width):
    if width % block_width:
        return None
    fa = f"{top}_full_adder"
    block = f"{top}_block{block_width}"
    blocks = width // block_width
    return f"""module {fa}(input a, input b, input cin, output sum, output cout);
    assign sum = a ^ b ^ cin;
    assign cout = (a & b) | (a & cin) | (b & cin);
endmodule

module {block}(input [{block_width-1}:0] a, input [{block_width-1}:0] b,
    input cin, output [{block_width-1}:0] sum, output cout);
    wire [{block_width}:0] carry; assign carry[0] = cin;
    genvar i;
    generate for (i=0; i<{block_width}; i=i+1) begin : gen_fa
        {fa} u_fa(.a(a[i]),.b(b[i]),.cin(carry[i]),
                  .sum(sum[i]),.cout(carry[i+1]));
    end endgenerate
    assign cout = carry[{block_width}];
endmodule

module {top} (input [{width-1}:0] {a}, input [{width-1}:0] {b}, input {cin},
    output [{width-1}:0] {s}, output {co});
    wire [{blocks}:0] carry; assign carry[0] = {cin};
    genvar j;
    generate for (j=0; j<{blocks}; j=j+1) begin : gen_blocks
        {block} u_block(
          .a({a}[j*{block_width} +: {block_width}]),
          .b({b}[j*{block_width} +: {block_width}]), .cin(carry[j]),
          .sum({s}[j*{block_width} +: {block_width}]), .cout(carry[j+1]));
    end endgenerate
    assign {co} = carry[{blocks}];
endmodule
"""


def _emit_cla32(top, a, b, s, co):
    cla4, cla16 = f"{top}_cla4", f"{top}_cla16"
    return f"""module {cla4}(input [3:0] A, input [3:0] B, input Cin,
    output [3:0] S, output Cout, output group_p, output group_g);
    wire [3:0] p=A^B, g=A&B; wire [4:0] c; assign c[0]=Cin;
    assign c[1]=g[0]|(p[0]&c[0]);
    assign c[2]=g[1]|(p[1]&g[0])|(p[1]&p[0]&c[0]);
    assign c[3]=g[2]|(p[2]&g[1])|(p[2]&p[1]&g[0])|(p[2]&p[1]&p[0]&c[0]);
    assign c[4]=g[3]|(p[3]&g[2])|(p[3]&p[2]&g[1])|
                (p[3]&p[2]&p[1]&g[0])|(p[3]&p[2]&p[1]&p[0]&c[0]);
    assign S=p^c[3:0]; assign Cout=c[4]; assign group_p=&p;
    assign group_g=g[3]|(p[3]&g[2])|(p[3]&p[2]&g[1])|
                   (p[3]&p[2]&p[1]&g[0]);
endmodule

module {cla16}(input [15:0] A, input [15:0] B, input Cin,
    output [15:0] S, output Cout);
    wire [3:0] bp,bg; wire [4:0] bc; assign bc[0]=Cin;
    assign bc[1]=bg[0]|(bp[0]&bc[0]);
    assign bc[2]=bg[1]|(bp[1]&bg[0])|(bp[1]&bp[0]&bc[0]);
    assign bc[3]=bg[2]|(bp[2]&bg[1])|(bp[2]&bp[1]&bg[0])|
                 (bp[2]&bp[1]&bp[0]&bc[0]);
    assign bc[4]=bg[3]|(bp[3]&bg[2])|(bp[3]&bp[2]&bg[1])|
                 (bp[3]&bp[2]&bp[1]&bg[0])|(bp[3]&bp[2]&bp[1]&bp[0]&bc[0]);
    genvar k; generate for(k=0;k<4;k=k+1) begin: blocks
      {cla4} u(.A(A[k*4 +: 4]),.B(B[k*4 +: 4]),.Cin(bc[k]),
        .S(S[k*4 +: 4]),.Cout(),.group_p(bp[k]),.group_g(bg[k]));
    end endgenerate
    assign Cout=bc[4];
endmodule

module {top} (input [32:1] {a}, input [32:1] {b},
    output [32:1] {s}, output {co});
    wire c16;
    {cla16} low(.A({a}[16:1]),.B({b}[16:1]),.Cin(1'b0),
                .S({s}[16:1]),.Cout(c16));
    {cla16} high(.A({a}[32:17]),.B({b}[32:17]),.Cin(c16),
                 .S({s}[32:17]),.Cout({co}));
endmodule
"""


def synth(prompt_text: str, ins: List[Port], outs: List[Port],
          top: str = "TopModule") -> Optional[str]:
    if not prompt_text or not ins or not outs:
        return None
    # an "adder" cue must be present (avoid firing on an unrelated 2-operand block).
    if not re.search(r"(?i)\badder\b|\badd\b", prompt_text):
        return None
    if _OUT_OF_SCOPE.search(prompt_text):
        return None

    cin = [(n, w) for n, w in ins if n.lower() in _CIN_NAMES]
    data_in = [(n, w) for n, w in ins if n.lower() not in _CIN_NAMES]
    if len(data_in) != 2:
        return None
    (a, aw), (b, bw) = data_in
    if aw != bw or aw < 2:
        return None
    if len(cin) > 1 or any(w != 1 for _, w in cin):
        return None

    cout = [(n, w) for n, w in outs if _is_cout(n, w)]
    summ = [(n, w) for n, w in outs if not _is_cout(n, w)]
    if len(summ) != 1 or len(cout) != 1:
        return None
    s, sw = summ[0]
    if sw != aw:
        return None
    co = cout[0][0]

    if re.search(r"carry[-\s]*lookahead|\bCLA\b", prompt_text, re.I):
        if aw == 32 and not cin and re.search(r"\[\s*32\s*:\s*1\s*\]", prompt_text):
            return _emit_cla32(top, a, b, s, co)
        return None

    block = re.search(r"small\s+bit[-\s]*width\s+adder\s*\(\s*(\d+)\s*-?bit",
                      prompt_text, re.I)
    if block and re.search(r"instantiat(?:e|ed|ion).*multiple", prompt_text,
                           re.I | re.S):
        return _emit_block_adder(top, a, b, cin[0][0] if cin else "1'b0",
                                 s, co, aw, int(block.group(1)))

    if re.search(r"bit[-\s]*level\s+adders?|full\s+adders?|series\s+of.*adders?",
                 prompt_text, re.I | re.S):
        return _emit_full_adder_chain(top, a, b,
                                      cin[0][0] if cin else "1'b0", s, co, aw)

    cin_term = f" + {cin[0][0]}" if cin else ""
    in_decls = [(f"    input [{w-1}:0] {n}" if w > 1 else f"    input {n}")
                for n, w in ins]
    out_decls = [f"    output [{sw-1}:0] {s}", f"    output {co}"]
    body = f"    assign {{{co}, {s}}} = {a} + {b}{cin_term};"
    return ("// program-SOLVED N-bit adder (carry-in + separate carry-out); "
            "deterministic.\n"
            f"module {top} (\n" + ",\n".join(in_decls + out_decls) + "\n);\n"
            + body + "\nendmodule\n")


def main(argv=None) -> int:
    import argparse
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import prose_port_block_read as bridge  # noqa: E402
    import port_parser as pp            # noqa: E402
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args(argv)
    text = Path(a.prompt).read_text(errors="replace")
    ins, outs = pp.parse_ports(bridge.bridge_prompt(text))
    rtl = synth(text, ins, outs, a.top)
    print(rtl if rtl else json.dumps({"result": "SKIP"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
