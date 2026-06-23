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
    # than fabricate an interface (SKIP).
    ctx = {"rtl/other.sv": "module other (input a, output b);\nendmodule\n"}
    assert R.recover_interface(_rec("the_target", ctx)) == []


def test_helper_submodule_not_pulled_as_target():
    # The target is `top`, which INSTANTIATES helper `leaf`. Only `leaf`'s header
    # is in context (top is what the AI must write). We must NOT pass off leaf's
    # ports as the target interface.
    ctx = {"rtl/leaf.sv": (
        "module leaf (input [2:0] in_l, output [1:0] out_l);\nendmodule\n")}
    assert R.recover_interface(_rec("top", ctx)) == []


def test_word_boundary_no_prefix_match():
    # `module adder` must not be matched by target `add`.
    ctx = {"rtl/a.sv": "module adder (input [7:0] a, output [7:0] s);\nendmodule\n"}
    assert R.recover_interface(_rec("add", ctx)) == []


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
