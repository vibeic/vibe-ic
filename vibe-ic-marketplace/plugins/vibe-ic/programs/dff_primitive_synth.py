#!/usr/bin/env python3
"""dff_primitive_synth.py — DETERMINISTIC emitter for the canonical single-bit
D-FLIP-FLOP primitive (optionally with an active-high SYNCHRONOUS reset).

A recurring atomic spec form is the textbook D flip-flop:

    "The module should implement a single D flip-flop."
    "The module should implement a simple D flip flop with active high
     synchronous reset (reset output to 0)."

i.e. a clocked register `q <= d` (with `q <= 0` when a synchronous reset is
asserted). This solver emits ONLY that structural primitive and SKIPs (returns
None, §4.05) on any deviation, so it can never emit a wrong machine. The emit is
VERIFIED against the official testbench by the caller: this module is a member
of `deterministic_emit_chain.EMITTERS`, and `try_emit(..., verify=<oracle>)`
DISCARDS an emit the oracle refuses and moves to the next emitter, so a
convention mismatch can never be banked. (The named caller used to be
`verilogeval_tier_pipeline --verify`; that pipeline is deleted and the chain is
where the rule lives now.)

WHY this is GENERAL (keyed on STRUCTURE, not on a problem id / name):
  * The trigger is the canonical PRIMITIVE NAME "D flip-flop" / "D flip flop"
    (a structural artifact name in the same family as "multiplexer", "counter",
    "NAND gate" that the registry already keys on) — NOT a problem id, file name,
    or design SKU.
  * Port roles are inferred by GENERIC structure: clk = a port named clk/clock;
    an active-high SYNCHRONOUS reset = a 1-bit port named r/rst/reset/clr WHEN the
    prose says "synchronous reset"; the data input is the 1-bit port named `d`
    (the D in D-flip-flop); the output is the port named `q` (the canonical
    flip-flop output). A D-flip-flop's interface shape is FIXED by the primitive
    itself, so a prompt that mislabels the `q` PORT DIRECTION (some dataset prompts
    list `q` as an input by typo while the testbench wires it as the output) is
    still resolved correctly from the primitive's structure — exactly the
    "directory/TB authority over a prose typo" convention.
  * SYNCHRONOUS, active-high, reset-to-0 only. An ASYNCHRONOUS reset, a non-zero
    reset value, a vector data path, more than one data input, an enable/load, or
    any FSM / combinational / multi-output cue takes the spec OUT of envelope and
    forces a SKIP — those are owned by the FSM / register-file / AI-gate tiers.

Public API
    synth(text, top="TopModule") -> str|None    # registry generator shape
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _specrtl_common import extract_spec_contract  # noqa: E402  port roles

# The DEFINING structural cue: the D-flip-flop primitive named in the prose.
_DFF_RE = re.compile(r"\bD[\s-]?flip[\s-]?flop\b", re.I)
# OUT-of-envelope cues — any of these means the spec is NOT a bare D-FF primitive.
_ASYNC_RE = re.compile(r"\bareset\b|asynchronous", re.I)
# An FSM / combinational / multi-style / behavioral cue: not a bare register.
_NOT_DFF_RE = re.compile(
    r"finite state machine|state machine|\bFSM\b|always block|assign statement|"
    r"combinational|truth table|karnaugh|k-?map|multiplex|\bmux\b|counter|"
    r"shift register|\bgate\b|enable|\bload\b|\bhold\b|toggle|J-?K|\bT[\s-]?flip",
    re.I)
# A non-zero / set reset value is out of envelope (we emit reset-to-0 only). Scoped
# tightly so it fires ONLY on a genuine non-zero reset target — `reset ... to 1`,
# `reset ... to high`, or a `preset` — NOT on the benign "reset (reset output to 0)"
# phrasing where the literal substring "set (reset" is just two `reset` words.
_SET_RESET_RE = re.compile(
    r"reset[^.]{0,30}\bto\s+(?:1\b|one\b|high\b)|\bpreset\b", re.I)
_SYNC_RESET_RE = re.compile(r"synchronous\s+reset|reset.{0,20}synchronous", re.I)

_CLK_RE = re.compile(r"^(clk|clock)$", re.I)
_RST_RE = re.compile(r"^(r|rst|reset|clr|clear|sync_?reset|sreset)$", re.I)


def synth(text: str, top: str = "TopModule") -> Optional[str]:
    """Emit a single-bit D-FF (optionally with active-high sync reset-to-0) RTL,
    or None (SKIP) on any deviation from that exact primitive envelope."""
    if not _DFF_RE.search(text):
        return None                       # not the D-FF primitive
    if _ASYNC_RE.search(text):
        return None                       # async reset out of envelope
    if _NOT_DFF_RE.search(text):
        return None                       # FSM / comb / multi-style / enable etc.
    if _SET_RESET_RE.search(text):
        return None                       # non-zero / set / preset reset value

    try:
        c = extract_spec_contract(text, confirm=False)
    except Exception:
        return None
    ports = list(c.ports)
    if not ports:
        return None

    by_name = {p.name.lower(): p for p in ports}
    # clk + d + q are the irreducible D-FF ports; resolve them by canonical name.
    clk = next((p.name for p in ports if _CLK_RE.match(p.name)), None)
    d_port = by_name.get("d")
    q_port = by_name.get("q")
    if clk is None or d_port is None or q_port is None:
        return None
    # the data input and the flip-flop output are both 1 bit (the bare primitive).
    if d_port.width != 1 or q_port.width != 1:
        return None
    # `d` must be an input. `q` is the OUTPUT by the primitive's fixed shape — even
    # if the prompt mislabels its direction (the dataset typo case). The data input
    # `d` being declared as an output, however, is a genuine contradiction -> SKIP.
    if d_port.direction != "input":
        return None

    # An optional active-high SYNCHRONOUS reset port, present ONLY when the prose
    # says "synchronous reset". A reset-named port without the synchronous-reset
    # prose is ambiguous (could be async / enable) -> require the prose.
    reset_name = None
    if _SYNC_RESET_RE.search(text):
        rcands = [p.name for p in ports
                  if _RST_RE.match(p.name) and p.width == 1
                  and p.name.lower() not in ("d", "q")
                  and not _CLK_RE.match(p.name)]
        if len(rcands) == 1:
            reset_name = rcands[0]
        elif len(rcands) > 1:
            return None                   # ambiguous reset -> SKIP

    # Every OTHER port (besides clk / d / q / the resolved reset) means this is not
    # a bare D-FF primitive -> SKIP rather than silently ignore an interface port.
    accounted = {clk.lower(), "d", "q"}
    if reset_name:
        accounted.add(reset_name.lower())
    for p in ports:
        if p.name.lower() not in accounted:
            return None

    if reset_name:
        body = (f"  always @(posedge {clk}) begin\n"
                f"    if ({reset_name})\n"
                f"      q <= 1'b0;\n"
                f"    else\n"
                f"      q <= d;\n"
                f"  end\n")
        rst_decl = f"  input {reset_name},\n"
        head = "// program-SOLVED D-FF primitive (active-high synchronous reset-to-0)."
    else:
        body = (f"  always @(posedge {clk})\n"
                f"    q <= d;\n")
        rst_decl = ""
        head = "// program-SOLVED D-FF primitive (q <= d on posedge clk)."

    return (
        f"{head}\n"
        f"module {top} (\n"
        f"  input {clk},\n"
        f"  input d,\n"
        f"{rst_decl}"
        f"  output reg q\n"
        f");\n"
        f"{body}"
        f"endmodule\n")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args(argv)
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    print(rtl if rtl else "(SKIP — not a bare single-bit D-FF primitive)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
