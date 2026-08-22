#!/usr/bin/env python3
"""mux_synth.py — deterministic SOLVER for the MULTIPLEXER family (spec -> RTL).

A multiplexer prompt that states its structure unambiguously is fully determined,
blind: the number of data sources, the select width, the data width, and — when the
select space is wider than the source count — the explicit out-of-range default.
This solver reads the stated interface (via the SHARED port_parser) plus the prose
that fixes the select->source mapping, and EMITS correct synthesizable RTL, or
returns None (SKIP) on ANY ambiguity. It never guesses an unstated default.

Two structural FORMS are recognized (keyed on stated STRUCTURE, not on names):

  (A) individual-port mux — N separate data ports of equal width D, one select
      port of width S, one output of width D. sel=0 picks the 1st port, sel=1 the
      2nd, etc. (declaration order). Examples: 2:1 (`sel ? b : a`), a 6:1 with a
      stated default of 0, a 9:1 with a stated all-ones default for sel 9..15.

  (B) packed-bus mux — ONE wide data input of width N*D, one select port of width
      S, one output of width D. Source k occupies in[k*D +: D]; out = in[sel*D +: D]
      (the dataset's bit-reverse-free packed form). Example: a 256:1 1-bit and a
      256:1 4-bit packed mux.

§4.05 NO-LEAK — SKIP (return None) unless EVERY one of these is unambiguous:
  * exactly one select port (a >1-bit bus, OR a 1-bit sel for a 2-source mux);
  * a single, consistent data width D across all data ports / the bus slice;
  * a definite source count N (== number of data ports for form A; == declared
    bus_width/D for form B, and that division must be exact);
  * if the select space (2**S) exceeds N, the out-of-range default MUST be stated
    explicitly in the prose (all-zeros / all-ones); an UNSTATED default => SKIP;
  * the prose must actually describe a multiplexer / select-one-of-N behavior
    (not some other select-shaped function), and the sel->source order must be the
    natural ascending one.

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


# --------------------------------------------------------------------------- #
# prose helpers — all chip-AGNOSTIC, keyed on stated structure                #
# --------------------------------------------------------------------------- #
def _is_mux_prose(text: str) -> bool:
    """True iff the prose describes selecting ONE source of several (a multiplexer).

    Requires an explicit multiplexer signature. We do NOT fire on a bare 'select'
    token, which can describe non-mux functions (priority encoder, decoder, ...).
    """
    t = text.lower()
    if re.search(r"\bmultiplexer\b", t):
        return True
    # 'N-to-1' / 'N:1' / 'N-1' selecting form, with a choose/select verb nearby.
    if re.search(r"\b\d+\s*[-:]\s*(?:to\s*[-]?\s*)?1\b", t) and re.search(
        r"\b(choose|chooses|select|selects)\b", t
    ):
        return True
    return False


def _has_non_mux_select(text: str) -> bool:
    """True iff the prose is a DIFFERENT select-shaped function (must SKIP)."""
    t = text.lower()
    return bool(
        re.search(
            r"\b(priority\s+encoder|priority\s+mux|decoder|demultiplex|demux|"
            r"arbiter|round[-\s]?robin|barrel\s+shift|encoder)\b",
            t,
        )
    )


def _stated_default(text: str, dwidth: int):
    """Return the out-of-range default literal, or None if not unambiguously stated.

    Recognizes the dataset's two explicit defaults, keyed on prose only:
      * all-ones  : "set all output bits to '1'", "all ones", "output all 1s", ...
      * all-zeros : "output 0", "output all zeros", "outputs 0", ...
    Returns a Verilog literal string sized to dwidth, or None.
    """
    t = text.lower()
    # all-ones forms
    if re.search(r"all\s+output\s+bits?\s+to\s*['\"]?1", t) or re.search(
        r"\ball\s+(?:1s|ones)\b", t
    ) or re.search(r"output\s+all\s+1", t):
        return f"{{{dwidth}{{1'b1}}}}"
    # all-zeros forms — "output 0", "output zero", "set ... to 0", "all zeros"
    if re.search(r"\ball\s+(?:0s|zeros)\b", t) or re.search(
        r"\b(?:output|outputs|set\s+.{0,20}?to)\s+(?:all\s+)?(?:0|zero)\b", t
    ):
        return f"{dwidth}'b0"
    return None


# --------------------------------------------------------------------------- #
# the solver                                                                  #
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule"):
    if not _is_mux_prose(prompt_text):
        return None
    if _has_non_mux_select(prompt_text):
        return None

    ins, outs = _pp.parse_ports(prompt_text)
    if not ins or len(outs) != 1:
        return None
    # No clock / reset / enable etc. — a pure combinational mux has none.
    if any(n.lower() in ("clk", "clock", "rst", "reset", "rstn", "rst_n", "en",
                          "enable", "load", "valid", "ready") for n, _ in ins):
        return None

    out_name, dwidth = outs[0]

    # --- identify the select port ------------------------------------------- #
    buses = [(n, w) for n, w in ins if w > 1]
    scalars = [(n, w) for n, w in ins if w == 1]

    sel = None
    sel_by_name = [(n, w) for n, w in ins if n.lower() in ("sel", "select", "s")]
    if len(sel_by_name) == 1:
        sel = sel_by_name[0]
    elif len(scalars) == 1 and not sel_by_name:
        # a lone 1-bit input among wider data ports could be the select; only
        # trust it when nothing is named sel and exactly one scalar exists.
        sel = scalars[0]
    if sel is None:
        return None
    sel_name, swidth = sel

    data = [(n, w) for n, w in ins if (n, w) != sel]
    if not data:
        return None

    # ===================================================================== #
    # FORM B: single packed data bus.                                       #
    # ===================================================================== #
    if len(data) == 1 and data[0][1] > 1 and data[0][1] != dwidth:
        bus_name, bus_w = data[0]
        if dwidth <= 0 or bus_w % dwidth != 0:
            return None
        n_src = bus_w // dwidth
        if n_src < 2:
            return None
        # The packed map must be the natural ascending one: source k at k*D +: D
        # (dataset prose: "sel=0 selects in[D-1:0], sel=1 selects ..."). Require
        # the prose to actually describe selecting from the packed vector.
        if not re.search(r"\bpacked\b|\bin\[", prompt_text.lower()) and \
           not re.search(r"single\s+\d+-bit\s+input\s+vector", prompt_text.lower()):
            return None
        return _emit_packed(top, out_name, dwidth, sel_name, swidth,
                            bus_name, n_src)

    # ===================================================================== #
    # FORM A: N individual equal-width data ports.                          #
    # ===================================================================== #
    widths = {w for _, w in data}
    if len(widths) != 1:
        return None                       # inconsistent data width -> ambiguous
    if data[0][1] != dwidth:
        return None                       # data width must equal output width
    n_src = len(data)
    if n_src < 2:
        return None

    default_lit = None
    if (1 << swidth) > n_src:
        # select space exceeds the number of sources: a default is REQUIRED.
        default_lit = _stated_default(prompt_text, dwidth)
        if default_lit is None:
            return None                   # unstated out-of-range default -> SKIP

    return _emit_individual(top, out_name, dwidth, sel_name, swidth,
                            [n for n, _ in data], default_lit)


# --------------------------------------------------------------------------- #
# emitters                                                                    #
# --------------------------------------------------------------------------- #
def _decl(name: str, w: int, direction: str, reg: bool = False) -> str:
    kw = f"{direction} reg" if reg else direction
    if w == 1:
        return f"    {kw} {name}"
    return f"    {kw} [{w-1}:0] {name}"


def _emit_individual(top, out_name, dwidth, sel_name, swidth, data_names,
                     default_lit):
    lines = [
        "// program-SOLVED multiplexer (individual data ports); deterministic.",
        f"module {top} (",
    ]
    port_lines = [_decl(sel_name, swidth, "input")]
    for n in data_names:
        port_lines.append(_decl(n, dwidth, "input"))
    port_lines.append(_decl(out_name, dwidth, "output", reg=True))
    lines.append(",\n".join(port_lines))
    lines.append(");")
    lines.append("    always @(*) begin")
    lines.append(f"        case ({sel_name})")
    for k, n in enumerate(data_names):
        lines.append(f"            {swidth}'d{k}: {out_name} = {n};")
    dflt = default_lit if default_lit is not None else f"{dwidth}'b0"
    lines.append(f"            default: {out_name} = {dflt};")
    lines.append("        endcase")
    lines.append("    end")
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


def _emit_packed(top, out_name, dwidth, sel_name, swidth, bus_name, n_src):
    bus_w = n_src * dwidth
    lines = [
        "// program-SOLVED multiplexer (packed data bus); deterministic.",
        f"module {top} (",
        _decl(bus_name, bus_w, "input") + ",",
        _decl(sel_name, swidth, "input") + ",",
        _decl(out_name, dwidth, "output"),
        ");",
    ]
    if dwidth == 1:
        lines.append(f"    assign {out_name} = {bus_name}[{sel_name}];")
    else:
        # source k at k*D +: D.  Use the explicit *D form so it matches the
        # dataset's packed convention exactly.
        lines.append(
            f"    assign {out_name} = {bus_name}[{sel_name}*{dwidth} +: {dwidth}];"
        )
    lines.append("endmodule")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not an unambiguously-specified multiplexer", file=sys.stderr)
        sys.exit(1)
    print(rtl)
