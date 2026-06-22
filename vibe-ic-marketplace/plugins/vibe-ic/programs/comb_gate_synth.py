#!/usr/bin/env python3
"""comb_gate_synth.py — deterministic SOLVER for the COMBINATIONAL GATE / WIRE /
BOOLEAN-EXPRESSION family (spec -> RTL).

A prompt in this family states a purely combinational boolean function with NO
hidden information: a single named logic gate over its declared operands, a plain
wire pass-through, a per-output bank of N-input reductions or 2-input gates, or an
EXPLICIT boolean equation written out in the prose. When the function is stated
UNAMBIGUOUSLY this solver reads the declared interface (via the SHARED port_parser)
plus the function-fixing prose and EMITS correct synthesizable RTL; on ANY ambiguity
it returns None (SKIP). A wrong gate is far worse than an honest skip — this family
has the HIGHEST false-fire risk in the benchmark because the prose is so varied, so
every recognizer below demands an explicit, structural signature and bails the moment
the prose turns descriptive (read-the-waveform / read-the-K-map / "the circuit does
X" / neighbour-relationship / chip-number) rather than function-exact.

This is NOT the truth-table / K-map / waveform path (those tables encode the function
as ROWS and are owned by oracle_table_synth / kmap_*_synth / waveform_truth_table_synth).
This solver fires ONLY on prompts WITHOUT such a table — direct gate / equation prose.

FORMS recognized (keyed on stated STRUCTURE, never on chip names):

  (A) single named gate — the whole module is one gate. "implement a NOT gate"
      (1 input, 1 output, out = ~in); "implement a 2-input AND/OR/NAND/NOR/XOR/XNOR
      gate" (exactly the declared 1-bit scalar inputs are the operands, 1 output).
      An N-input gate may instead be stated over a SINGLE N-bit input bus -> reduction.

  (B) wire / buffer pass-through — "behave like a wire" / "assign the output to the
      same value as the input combinationally". Exactly 1 input, 1 output, equal width.

  (C) per-output gate BANK — several outputs, each fixed by its OWN explicit line:
        "out_and : output of a 4-input AND gate"   (reduction over the one input bus)
        "out_and: a and b"                          (2-input gate over named scalars)
      Every output must be covered by exactly one such line; any output left to prose
      => SKIP.

  (D) explicit boolean equation — the prose literally writes the function:
        "implement the boolean function z = (x^y) & x".
      The RHS is emitted VERBATIM after proving it references only declared ports and
      contains only safe boolean/operator tokens. One equation per output; every
      output must have one.

§4.05 NO-LEAK — return None unless EVERY relevant condition holds:
  * the prompt must NOT carry a truth/timing/waveform table or a K-map (those are a
    different, table-owning path) — a stray time/header row => SKIP;
  * the prose must NOT be descriptive ("read the waveform", "determine what the
    circuit does", "the 7458 is a chip", neighbour-to-the-left, place-in-upper-half,
    parity/adder/counter/encoder/decoder/mux behavioral words) — those => SKIP;
  * a single named gate fires only with the EXACT operand count it needs (NOT=1;
    2-input gate=2 scalars, or one N-bit bus for an N-input reduction);
  * a bank fires only when EVERY declared output is covered by exactly one explicit
    line and the inputs/operands referenced are all declared;
  * an equation fires only when it parses to declared-port references + a closed set
    of safe operators (& | ^ ~ ! && || ^~ ~^ () and bare port names), one per output;
  * mixed / partially-specified / contradictory specs => SKIP.

API: synth(prompt_text, top="TopModule") -> str | None ; plus a __main__ CLI.
chip-AGNOSTIC, pure regex + a tiny safe-token equation validator. Deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import port_parser as _pp  # noqa: E402  reuse the SHARED interface reader


# --------------------------------------------------------------------------- #
# global descriptiveness / table guards — if ANY trip, the whole prompt SKIPs  #
# --------------------------------------------------------------------------- #

# A simulation/timing/truth table or a K-map encodes the function as ROWS; that is a
# DIFFERENT path (oracle_table_synth / waveform_truth_table_synth / kmap_*). Their
# presence means the prose alone does NOT fix the function here -> SKIP.
_TABLE_OR_WAVEFORM = re.compile(
    r"""(?xi)
      \bkarnaugh\b | \bk-?map\b | \btruth\s+table\b |
      \bwaveform\b | \bsimulation\s+waveform\b |
      ^\s*time\b .* \b(ns|ps)\b |                 # a 'time ... ns' table header/row
      \bdetermine\s+what\s+the\s+circuit\s+does\b |
      \bread\s+the\s+(?:simulation\s+)?waveforms?\b
    """,
    re.M,
)

# Behavioral / descriptive language that does NOT pin an exact boolean function. If
# the prose leans on any of these the function is not gate-exact from the words alone.
_DESCRIPTIVE = re.compile(
    r"""(?xi)
      \bneighbour\b | \bneighbor\b |
      \bupper\s+half\b | \blower\s+half\b |
      \bparity\b | \bpopcount\b | \bpopulation\s+count\b |
      \badder\b | \bsubtract\b | \bsubtractor\b |
      \bcounter\b | \bencoder\b | \bdecoder\b | \bmultiplexer\b |
      \b7\d{3}\b |                                # 7400-series chip number (7458/7420)
      \bsame\s+functionality\s+as\b |             # "...as the 7420 chip"
      \bbubble\b |                                # bubble-notation structural prose
      \bsubmodule\b | \binstantiat                # structural network of submodules
    """,
    re.X,
)

# a clock / sequential cue means this is not a pure combinational gate at all.
_SEQUENTIAL_PORTS = {"clk", "clock", "rst", "reset", "rstn", "rst_n", "en",
                     "enable", "load", "valid", "ready", "clken", "clk_en"}

# word/symbol -> a builder taking the operand sub-expression string.
_GATE_OPS: Dict[str, Tuple[str, bool]] = {
    # name        : (verilog reduction/binary op, is_inverting)
    "and":  ("&", False),
    "or":   ("|", False),
    "xor":  ("^", False),
    "nand": ("&", True),
    "nor":  ("|", True),
    "xnor": ("^", True),
}


def _has_blocking_guard(text: str) -> bool:
    return bool(_TABLE_OR_WAVEFORM.search(text) or _DESCRIPTIVE.search(text))


def _port_names(ports: List[Tuple[str, int]]) -> List[str]:
    return [n for n, _ in ports]


def _is_sequential(ins: List[Tuple[str, int]]) -> bool:
    return any(n.lower() in _SEQUENTIAL_PORTS for n, _ in ins)


def _decl(name: str, w: int, direction: str) -> str:
    if w == 1:
        return f"    {direction} {name}"
    return f"    {direction} [{w-1}:0] {name}"


def _module_header(top: str, ins, outs) -> List[str]:
    lines = [f"module {top} ("]
    port_lines = [_decl(n, w, "input") for n, w in ins]
    port_lines += [_decl(n, w, "output") for n, w in outs]
    lines.append(",\n".join(port_lines))
    lines.append(");")
    return lines


# --------------------------------------------------------------------------- #
# FORM A — a single named gate that IS the whole module                       #
# --------------------------------------------------------------------------- #
def _single_named_gate(text: str, ins, outs, top: str) -> Optional[str]:
    if len(outs) != 1:
        return None
    out_name, out_w = outs[0]
    low = text.lower()

    # NOT gate / inverter — exactly one input, equal width.
    # The function-fixing verb appears as "implement" (VE-human imperative/modal) or
    # "implements" (VE-v2 "a module that implements ..."); accept both 3rd-person forms.
    if re.search(r"\bimplements?\s+(?:a|an)\s+(?:1-?input\s+)?not\s+gate\b", low) or \
       re.search(r"\bimplements?\s+(?:a|an)\s+inverter\b", low):
        if len(ins) != 1:
            return None
        in_name, in_w = ins[0]
        if in_w != out_w:
            return None
        body = f"    assign {out_name} = ~{in_name};"
        return "\n".join(
            ["// program-SOLVED single NOT gate; deterministic."]
            + _module_header(top, ins, outs) + [body, "endmodule", ""]
        )

    # 2-input (or N-input) AND/OR/NAND/NOR/XOR/XNOR gate.
    m = re.search(
        r"\bimplements?\s+(?:a|an)\s+(?:(\d+)\s*-?\s*input\s+)?"
        r"(and|or|nand|nor|xnor|xor)\s+gate\b",
        low,
    )
    if not m:
        return None
    stated_n = int(m.group(1)) if m.group(1) else None
    gate = m.group(2)
    op, inv = _GATE_OPS[gate]

    if out_w != 1:
        return None  # a single named logic gate drives one 1-bit output

    # Operands: either N scalar (1-bit) inputs, or ONE N-bit input bus (reduction).
    scalars = [(n, w) for n, w in ins if w == 1]
    buses = [(n, w) for n, w in ins if w > 1]

    if len(buses) == 1 and not scalars:
        bus_name, bus_w = buses[0]
        if stated_n is not None and stated_n != bus_w:
            return None  # the stated fan-in must match the bus width exactly
        if bus_w < 2:
            return None
        inner = f"{op}{bus_name}"
        expr = f"~({inner})" if inv else inner
        body = f"    assign {out_name} = {expr};"
        kind = f"{bus_w}-input reduction {gate.upper()}"
    elif scalars and not buses:
        names = [n for n, _ in scalars]
        if stated_n is None:
            # an unqualified "AND gate" is taken as exactly the declared scalars
            # only when there are at least 2 of them (a gate needs >=2 operands,
            # except NOT which was handled above).
            if len(names) < 2:
                return None
        else:
            if stated_n != len(names):
                return None
            if stated_n < 2:
                return None
        inner = f" {op} ".join(names)
        expr = f"~({inner})" if inv else inner
        body = f"    assign {out_name} = {expr};"
        kind = f"{len(names)}-input {gate.upper()}"
    else:
        return None  # mixed scalar+bus operands for a single named gate => ambiguous

    return "\n".join(
        [f"// program-SOLVED single {kind} gate; deterministic."]
        + _module_header(top, ins, outs) + [body, "endmodule", ""]
    )


# --------------------------------------------------------------------------- #
# FORM B — wire / buffer pass-through                                         #
# --------------------------------------------------------------------------- #
def _wire_passthrough(text: str, ins, outs, top: str) -> Optional[str]:
    low = text.lower()
    # "behave like a wire" (VE-human modal) or "behaves like a wire" (VE-v2 "a module
    # that behaves like a wire"); accept both 3rd-person verb forms.
    is_wire = bool(re.search(r"\bbehaves?\s+like\s+a\s+wire\b", low))
    is_same = bool(
        re.search(
            r"\bassign\s+the\s+output\s+port\s+to\s+the\s+same\s+value\s+as\s+the\s+"
            r"input\s+port\s+combinationally\b",
            low,
        )
        or re.search(
            r"\boutput\b[^.]{0,40}\bsame\s+value\s+as\b[^.]{0,40}\binput\b"
            r"[^.]{0,40}\bcombinationally\b",
            low,
        )
    )
    if not (is_wire or is_same):
        return None
    # a single wire pass-through: exactly one input and one output of equal width.
    if len(ins) != 1 or len(outs) != 1:
        return None
    (in_name, in_w), (out_name, out_w) = ins[0], outs[0]
    if in_w != out_w:
        return None
    body = f"    assign {out_name} = {in_name};"
    return "\n".join(
        ["// program-SOLVED wire pass-through; deterministic."]
        + _module_header(top, ins, outs) + [body, "endmodule", ""]
    )


# --------------------------------------------------------------------------- #
# FORM C — per-output gate BANK                                               #
# --------------------------------------------------------------------------- #
# reduction line:  "out_and : output of a 4-input AND gate"
_RED_LINE = re.compile(
    r"""(?xi)
      ^\s*\(?\d*\)?\s*
      (?P<out>\w+)\s*[:\-]\s*
      output\s+of\s+(?:a|an)\s+(?:\d+\s*-?\s*input\s+)?
      (?P<gate>and|or|nand|nor|xnor|xor)\s+gate\b
    """,
    re.M,
)

# 2-input scalar gate line:  "out_and: a and b"  /  "out_anotb: a and-not b"
_BIN_LINE = re.compile(
    r"""(?xi)
      ^\s*\(?\d*\)?\s*
      (?P<out>\w+)\s*[:\-]\s*
      (?P<lhs>\w+)\s+
      (?P<gate>and-?not|and|or|xnor|xor|nand|nor)\s+
      (?P<rhs>\w+)\s*$
    """,
    re.M,
)


def _gate_bank(text: str, ins, outs, top: str) -> Optional[str]:
    if len(outs) < 2:
        return None
    out_names = {n for n, _ in outs}
    in_names = {n for n, _ in ins}

    # Each output must be the sole 1-bit output driven by exactly one explicit line.
    if any(w != 1 for _, w in outs):
        return None

    assigns: Dict[str, str] = {}

    # (a) reduction-over-the-single-input-bus bank (gates4 / gates100).
    red_hits = list(_RED_LINE.finditer(text))
    if red_hits:
        buses = [(n, w) for n, w in ins if w > 1]
        scalars = [(n, w) for n, w in ins if w == 1]
        # the reduction bank operates on exactly one input bus (in[N-1:0]).
        if len(buses) != 1 or scalars:
            return None
        bus_name, bus_w = buses[0]
        if bus_w < 2:
            return None
        for m in red_hits:
            out = m.group("out")
            if out not in out_names or out in assigns:
                return None
            op, inv = _GATE_OPS[m.group("gate").lower()]
            inner = f"{op}{bus_name}"
            assigns[out] = f"~({inner})" if inv else inner

    # (b) 2-input named-scalar gate bank (Prob087_gates).
    bin_hits = list(_BIN_LINE.finditer(text))
    if bin_hits:
        for m in bin_hits:
            out = m.group("out")
            if out not in out_names or out in assigns:
                # a duplicate / unknown output target makes the bank ambiguous.
                return None
            lhs, rhs = m.group("lhs"), m.group("rhs")
            if lhs not in in_names or rhs not in in_names:
                return None
            gate = m.group("gate").lower().replace("-", "")
            if gate == "andnot":
                expr = f"{lhs} & ~{rhs}"
            else:
                op, inv = _GATE_OPS[gate]
                expr = f"~({lhs} {op} {rhs})" if inv else f"{lhs} {op} {rhs}"
            assigns[out] = expr

    # Every declared output must be covered exactly once; none left to prose.
    if set(assigns.keys()) != out_names:
        return None

    body = [f"    assign {n} = {assigns[n]};" for n, _ in outs]
    return "\n".join(
        ["// program-SOLVED combinational gate bank; deterministic."]
        + _module_header(top, ins, outs) + body + ["endmodule", ""]
    )


# --------------------------------------------------------------------------- #
# FORM D — explicit boolean equation written out in the prose                 #
# --------------------------------------------------------------------------- #
# capture "boolean function <lhs> = <rhs>" (rhs ends at sentence/line boundary).
_EQ_LINE = re.compile(
    r"(?i)\bboolean\s+function\b[^\n.]*?(?P<lhs>\w+)\s*=\s*(?P<rhs>[^\n.]+)"
)

# the closed set of characters a safe combinational equation may contain (after the
# port identifiers are removed): operators, parens, brackets, whitespace, bit-literals.
_SAFE_EQ_TOKEN = re.compile(r"[~^&|!()\s']|<<|>>|\bx\b")


def _validate_eq_rhs(rhs: str, in_names: set, out_names: set) -> Optional[str]:
    """Return a cleaned RHS if it references ONLY declared input ports and a closed
    set of safe boolean operators; else None. (Conservative: bit-selects / replication
    / arithmetic are rejected — that is the table/arith path, not this one.)"""
    rhs = rhs.strip().rstrip(";.").strip()
    if not rhs:
        return None
    # identifiers used in the RHS
    idents = set(re.findall(r"[A-Za-z_]\w*", rhs))
    # every identifier must be a declared INPUT port (outputs may not appear on a
    # combinational RHS — that would be a latch/loop), and at least one must appear.
    if not idents:
        return None
    if idents & out_names:
        return None
    if not idents.issubset(in_names):
        return None
    # only the boolean operator/paren character set is permitted between idents.
    stripped = re.sub(r"[A-Za-z_]\w*", "", rhs)
    # allowed: ~ ^ & | ! ( ) whitespace, and the doubled forms && || ^~ ~^
    if re.search(r"[^~^&|!()\s]", stripped):
        return None
    return rhs


def _boolean_equation(text: str, ins, outs, top: str) -> Optional[str]:
    if len(outs) != 1:
        return None  # one explicit equation per output; keep single-output here
    out_name, out_w = outs[0]
    if out_w != 1:
        return None
    in_names = {n for n, _ in ins}
    out_names = {out_name}
    m = _EQ_LINE.search(text)
    if not m:
        return None
    lhs = m.group("lhs")
    if lhs != out_name:
        return None  # the equation must drive the declared output
    rhs = _validate_eq_rhs(m.group("rhs"), in_names, out_names)
    if rhs is None:
        return None
    body = f"    assign {out_name} = {rhs};"
    return "\n".join(
        ["// program-SOLVED explicit boolean equation; deterministic."]
        + _module_header(top, ins, outs) + [body, "endmodule", ""]
    )


# --------------------------------------------------------------------------- #
# the solver                                                                  #
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    if not prompt_text or not prompt_text.strip():
        return None
    if _has_blocking_guard(prompt_text):
        return None

    ins, outs = _pp.parse_ports(prompt_text)
    if not ins or not outs:
        return None
    if _is_sequential(ins):
        return None

    # try the forms in order of decreasing specificity; the FIRST to fire wins.
    for builder in (_single_named_gate, _wire_passthrough, _gate_bank,
                    _boolean_equation):
        rtl = builder(prompt_text, ins, outs, top)
        if rtl is not None:
            return rtl
    return None


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="path to the spec prompt .txt")
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not an unambiguously-specified combinational gate/wire/equation",
              file=sys.stderr)
        sys.exit(1)
    print(rtl)
