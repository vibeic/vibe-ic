#!/usr/bin/env python3
"""test_cvdp_context_interface_recover.py — pins the CONVERGE Tier4->Tier3 lever:
recover the TARGET module's PORT INTERFACE from the PROVIDED input.context RTL
header (interface = spec, header-only; never the body, never the golden output).

POSITIVES — ANSI header, signed range, param-expression width, non-ANSI body
declarations all recover the correct {name,dir,width}.
NEGATIVES (§4.05 / no-cheat) — target module absent from context -> [] (SKIP, no
fabrication); a HELPER/sub-module in context is NOT pulled when it isn't the
harness TOPLEVEL target; the parser NEVER returns body logic (only the header).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cvdp_context_interface_recover as R  # noqa: E402


def _rec(top, ctx_files):
    """Minimal record: harness .env names TOPLEVEL=<top>; input.context holds the
    provided RTL files."""
    return {
        "id": f"test_{top}",
        "input": {"prompt": f"Implement `{top}`.", "context": ctx_files},
        "output": {"response": "", "context": {}},
        "harness": {"files": {
            "src/.env": (
                "SIM=icarus\nTOPLEVEL_LANG=verilog\n"
                f"VERILOG_SOURCES=/code/rtl/{top}.sv\nTOPLEVEL={top}\nMODULE=test_{top}\n"),
            f"src/test_{top}.py": "import cocotb\n",
        }},
    }


# --------------------------------------------------------------------------- #
# POSITIVES
# --------------------------------------------------------------------------- #
def test_ansi_header_widths_and_dirs():
    ctx = {"rtl/iir.sv": (
        "module iir (\n"
        "    input logic clk,\n"
        "    input logic rst,\n"
        "    input logic signed [15:0] x,\n"
        "    output logic signed [15:0] y\n"
        ");\n"
        "  // body the recover must NOT read\n"
        "  assign y = x;\n"
        "endmodule\n")}
    ports = R.recover_interface(_rec("iir", ctx))
    by = {p["name"]: p for p in ports}
    assert set(by) == {"clk", "rst", "x", "y"}
    assert by["clk"]["dir"] == "input" and by["clk"]["width"] == 1
    assert by["x"]["dir"] == "input" and by["x"]["width"] == 16
    assert by["y"]["dir"] == "output" and by["y"]["width"] == 16


def test_param_expression_width_resolved():
    ctx = {"rtl/buf.sv": (
        "module buf #(parameter WIDTH = 8) (\n"
        "    input  [WIDTH-1:0] d,\n"
        "    output [WIDTH-1:0] q\n"
        ");\nendmodule\n")}
    ports = R.recover_interface(_rec("buf", ctx))
    by = {p["name"]: p for p in ports}
    assert by["d"]["width"] == 8 and by["q"]["width"] == 8


def test_ansi_direction_inheritance():
    # `output a, b` — b inherits output (Verilog ANSI rule).
    ctx = {"rtl/m.sv": (
        "module m (\n"
        "    input  [3:0] x,\n"
        "    output [3:0] a, b\n"
        ");\nendmodule\n")}
    ports = R.recover_interface(_rec("m", ctx))
    by = {p["name"]: p for p in ports}
    assert by["a"]["dir"] == "output" and by["b"]["dir"] == "output"
    assert by["b"]["width"] == 4


def test_nonansi_body_declarations():
    ctx = {"rtl/n.sv": (
        "module n (clk, d, q);\n"
        "  input clk;\n"
        "  input [7:0] d;\n"
        "  output [7:0] q;\n"
        "  reg [7:0] q;\n"
        "  always @(posedge clk) q <= d;  // body must NOT leak\n"
        "endmodule\n")}
    ports = R.recover_interface(_rec("n", ctx))
    by = {p["name"]: p for p in ports}
    assert set(by) == {"clk", "d", "q"}
    assert by["d"]["dir"] == "input" and by["d"]["width"] == 8
    assert by["q"]["dir"] == "output" and by["q"]["width"] == 8


# --------------------------------------------------------------------------- #
# NEGATIVES — §4.05 / no-cheat
# --------------------------------------------------------------------------- #
def test_target_absent_from_context_returns_empty():
    # The provided context declares a DIFFERENT module — recover nothing rather
    # than fabricate an interface (SKIP). We pass the target EXPLICITLY (the
    # compliant regime: toplevel_name derives from prompt+context, never the
    # off-limits .env TOPLEVEL) so this test controls the target-matching axis
    # directly: target `the_target` is absent from the context -> [].
    ctx = {"rtl/other.sv": "module other (input a, output b);\nendmodule\n"}
    assert R.recover_interface(_rec("the_target", ctx), target="the_target") == []


def test_helper_submodule_not_pulled_as_target():
    # The target is `top`, which INSTANTIATES helper `leaf`. Only `leaf`'s header
    # is in context (top is what the AI must write). We must NOT pass off leaf's
    # ports as the target interface. Target passed EXPLICITLY so the assertion
    # pins recover_interface's own helper-exclusion: only `top` may be recovered,
    # and `top` is not declared in context -> [] (leaf's ports are never pulled).
    ctx = {"rtl/leaf.sv": (
        "module leaf (input [2:0] in_l, output [1:0] out_l);\nendmodule\n")}
    assert R.recover_interface(_rec("top", ctx), target="top") == []


def test_word_boundary_no_prefix_match():
    # `module adder` must not be matched by target `add`. Target passed EXPLICITLY
    # so the assertion pins recover_interface's word-boundary match directly:
    # `add` is a strict prefix of `adder`, so it must NOT resolve -> [].
    ctx = {"rtl/a.sv": "module adder (input [7:0] a, output [7:0] s);\nendmodule\n"}
    assert R.recover_interface(_rec("add", ctx), target="add") == []


def test_body_signals_never_recovered_as_ports():
    # Internal regs/wires declared in the BODY must never appear as ports.
    ctx = {"rtl/c.sv": (
        "module c (input clk, output done);\n"
        "  reg [7:0] internal_counter;\n"
        "  wire secret_wire;\n"
        "  assign done = &internal_counter;\n"
        "endmodule\n")}
    ports = R.recover_interface(_rec("c", ctx))
    names = {p["name"] for p in ports}
    assert names == {"clk", "done"}
    assert "internal_counter" not in names and "secret_wire" not in names


def test_no_context_files_returns_empty():
    assert R.recover_interface(_rec("x", {})) == []
    assert R.recover_interface({"input": {}}) == []
    assert R.recover_interface(None) == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── prompt "Updated Interfaces" priority (ORGANIC 2026-07-13, CVDP oracle-RCA) ──
def _load_cir():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "cvdp_context_interface_recover.py"
    spec = importlib.util.spec_from_file_location("cir", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


_MODIFY_PROMPT = """Modify the `foo` module to add features.

### **Updated Input/Output Interfaces**
- **Inputs**:
  1. `pclk`: Clock signal.
  2. `preset_n`: Active-low reset.
  3. `pwdata[31:0]`: Write data bus.
  4. `gpio[GPIO_WIDTH-1:0]`: Bidirectional GPIO pins.
- **Outputs**:
  1. `prdata[31:0]`: Read data bus.
  2. `irq`: Interrupt.
"""


def test_prompt_iface_recovers_bidirectional_as_inout():
    m = _load_cir()
    ports = m.recover_interface_from_prompt(_MODIFY_PROMPT)
    by = {p["name"]: p for p in ports}
    assert by["gpio"]["dir"] == "inout"          # under Inputs, but 'Bidirectional' -> inout
    assert by["pclk"]["dir"] == "input"
    assert by["prdata"]["dir"] == "output"
    assert by["pwdata"]["width"] == 32           # [31:0] resolved
    # the legacy trio must NOT appear (it was replaced by the single gpio port)
    assert not any(n in by for n in ("gpio_in", "gpio_out", "gpio_enable"))


def test_prompt_iface_takes_priority_over_stale_context_header():
    """A modify-task record: the context RTL still has the OLD interface (legacy
    trio); the prompt's Updated Interfaces re-declares a single gpio inout. The
    prompt table must win (the hidden TB binds the new interface)."""
    m = _load_cir()
    stale_ctx = ("module foo(input pclk, input preset_n, input [31:0] pwdata,\n"
                 "  input [7:0] gpio_in, output [7:0] gpio_out, output [7:0] gpio_enable,\n"
                 "  output [31:0] prdata, output irq); endmodule\n")
    rec = {"id": "x", "input": {"prompt": _MODIFY_PROMPT, "context": {"rtl/foo.sv": stale_ctx}},
           "harness": {"files": {}}}
    # force target=foo (bypass the toplevel bridge for the unit test)
    ports = m.recover_interface(rec, target="foo")
    names = {p["name"]: p["dir"] for p in ports}
    assert names.get("gpio") == "inout"
    assert "gpio_in" not in names and "gpio_out" not in names
    # a context-resolved width backfills onto a symbolic prompt range
    by = {p["name"]: p for p in ports}
    assert by["pwdata"]["width"] == 32


def test_no_iface_section_falls_back_to_context():
    """A prompt with NO 'Updated Interfaces' section must not disturb the
    existing context-RTL parse (no regression on the 224 non-modify records)."""
    m = _load_cir()
    ctx = "module bar(input clk, input rst_n, output [3:0] q); endmodule\n"
    rec = {"id": "y", "input": {"prompt": "Complete the bar counter.", "context": {"rtl/bar.sv": ctx}},
           "harness": {"files": {}}}
    ports = m.recover_interface(rec, target="bar")
    assert {p["name"] for p in ports} == {"clk", "rst_n", "q"}
    assert next(p for p in ports if p["name"] == "q")["width"] == 4
