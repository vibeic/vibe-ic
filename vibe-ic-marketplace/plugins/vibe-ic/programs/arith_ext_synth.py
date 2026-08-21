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

The function is fixed with NO hidden information: {cout, sum} = a + b + cin. The
"with multiple bit-level / full adders" prose is an IMPLEMENTATION hint, not a
behavioural variable — the I/O behaviour the testbench checks is exactly the above
sum+carry. This solver EMITS that, keyed ENTIRELY on the declared interface
STRUCTURE (two equal-width operands + a separate 1-bit carry-out), never on a
design name. Every fire in this repo is iverilog-proven against the design's own
RTLLM testbench (adder_8bit, adder_16bit PASS; everything else SKIPs).

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
    import rtllm_port_bridge as bridge  # noqa: E402
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
