#!/usr/bin/env python3
r"""test_organic_20260703_cvdp_complete_extract_phantom_and_widths.py

ORGANIC-20260703-cvdp-complete-extract-phantom-output-port-and-wrong-widths.

`cvdp_complete_extract.extract` built the Tier-2/3 CONFORMANCE-GATE port list from
a prose parser that (a) latched a bare Verilog keyword (`output`, `bit`, `wire`,
`reg`) as a PHANTOM port name and (b) read a port width from an adjacent token
(a 66-bit `decoder_data_in` sized to 2 from a `2-bit sync header` sentence), and
that (c) IGNORED the design's own module header. A gate built from a phantom port
or a 2-vs-66 width would false-reject a correct emit / false-pass a wrong one.

The fix, chip-AGNOSTIC, in the CVDP adapter:
  * drop any parsed port whose NAME is a Verilog reserved word;
  * PREFER the authoritative module header — the PROMPT ```verilog module <top>(
    ANSI skeleton UNION the input.context header — for names + dirs + widths, and
    override a prose-guessed width with the header width (context wins on conflict);
  * MERGE prose-only ports the header does not declare (never drop a real port).

Run: python3 -m pytest programs/tests/test_organic_20260703_cvdp_complete_extract_phantom_and_widths.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cvdp_complete_extract as C          # noqa: E402


def _rec(rid, prompt, ctx=None):
    inp = {"prompt": prompt}
    if ctx is not None:
        inp["context"] = ctx
    return {"id": rid, "input": inp}


# ── decoder_0001 shape: a clean prompt ANSI skeleton + prose that mis-sizes ──
_DECODER_PROMPT = """\
Complete the given partial SystemVerilog code for a 64b66b decoder.
The decoder processes a 66-bit input word (`decoder_data_in`) and extracts a
**2-bit sync header** and a **64-bit data word**.

```verilog
module decoder_64b66b (
    input  logic         clk_in,
    input  logic         rst_in,
    input  logic [65:0]  decoder_data_in,
    output logic [63:0]  decoder_data_out,
    output logic         sync_error
);
endmodule
```
"""


def test_prompt_skeleton_header_is_authoritative_no_phantom_no_wrong_width():
    spec = C.extract(_rec("cvdp_copilot_64b66b_decoder_0001", _DECODER_PROMPT))
    ports = {p["name"]: p["width"] for p in spec.get("interface", [])}
    # no Verilog keyword ever survives as a port NAME
    assert not (set(ports) & {"output", "input", "inout", "bit", "wire", "reg",
                              "logic"})
    # the ANSI skeleton header widths are authoritative (prose "2-bit sync header"
    # must NOT shrink the 66-bit decoder_data_in)
    assert ports.get("decoder_data_in") == 66
    assert ports.get("decoder_data_out") == 64
    assert ports.get("sync_error") == 1
    assert ports.get("clk_in") == 1 and ports.get("rst_in") == 1
    # the real outputs are PRESENT (the phantom `output` used to replace them)
    assert {"decoder_data_out", "sync_error"} <= set(ports)


# ── encoder shape: context RTL header is authoritative over a mis-parsing prose ──
_ENCODER_CTX = {
    "rtl/encoder_64b66b.sv": (
        "module encoder_64b66b (\n"
        "    input  wire        clk_in,\n"
        "    input  wire        rst_in,\n"
        "    input  wire [63:0] encoder_data_in,\n"
        "    input  wire [7:0]  encoder_control_in,\n"
        "    output reg  [65:0] encoder_data_out\n"
        ");\n"
        "endmodule\n")
}
# a prose block that (a) invents a phantom `bit` output and (b) mis-sizes ports
_ENCODER_PROMPT = """\
Modify the 64b66b encoder. Inputs: `encoder_data_in` and an `encoder_control_in`.
Output: encoder_data_out. Also mentions a stray `output bit` and a 64-bit field.
"""


def test_context_header_width_beats_prose_and_drops_phantom():
    spec = C.extract(_rec("cvdp_copilot_64b66b_encoder_0009",
                          _ENCODER_PROMPT, ctx=_ENCODER_CTX))
    ports = {p["name"]: p["width"] for p in spec.get("interface", [])}
    assert "bit" not in ports and "output" not in ports
    # context header widths win (control_in=8, data_out=66), not a prose guess
    assert ports.get("encoder_control_in") == 8
    assert ports.get("encoder_data_out") == 66
    assert ports.get("encoder_data_in") == 64


# ── §4.05 guard: a prose-only port the header omits is NOT dropped ──
_ACC_PROMPT = """Design the module named `acc`. An accumulator.

### Inputs:
- clk: clock.
- din: input sample to accumulate.

### Outputs:
- acc_o [31:0]: the running total.
"""
_ACC_CTX = {"rtl/acc.sv": "module acc (input clk, input [11:0] din);\nendmodule\n"}


def test_prose_only_port_not_dropped_when_partial_context_header():
    # the context header declares clk + din only (width 12 for din); the prompt
    # declares an OUTPUT `acc_o [31:0]` the context omits. The header-preference
    # must NOT drop the prose-only port: din keeps the authoritative context
    # width (12), acc_o is MERGED in with its prompt-stated width (32).
    spec = C.extract(_rec("cvdp_copilot_acc_0001", _ACC_PROMPT, ctx=_ACC_CTX))
    by = {p["name"]: p for p in spec.get("interface", [])}
    assert by.get("din", {}).get("width") == 12        # context width preserved
    assert "acc_o" in by                               # prose-only port kept
    assert by.get("acc_o", {}).get("width") == 32      # its prompt-stated width


def test_reserved_word_set_is_chip_agnostic():
    # the guard is a pure Verilog-keyword set — no chip / vendor / SKU literal
    assert {"output", "input", "inout", "bit", "wire", "reg", "logic"} \
        <= C._RESERVED_PORT_WORDS
