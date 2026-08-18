#!/usr/bin/env python3
"""test_cvdp_context_param_defaults.py — pins verilog_width_resolve.context_param_defaults:
the CONVERGE lever that closes `param_expression_width` extraction gaps by reading a
parameter's DECLARED DEFAULT from the PROVIDED input.context RTL (§3.9 spec chain;
header-level config, never the functional body; merged BELOW prompt/tb defaults).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import verilog_width_resolve as W  # noqa: E402


def _rec(ctx_files):
    return {"id": "t", "input": {"prompt": "Implement it.", "context": ctx_files}}


def test_reads_parameter_and_localparam_defaults():
    ctx = {"rtl/m.sv": (
        "module m #(parameter WIDTH = 4) (\n"
        "  input [WIDTH-1:0] d, output [WIDTH-1:0] q\n"
        ");\n"
        "  localparam DEPTH = 16;\n"
        "endmodule\n")}
    out = W.context_param_defaults(_rec(ctx))
    assert out.get("WIDTH") == 4
    assert out.get("DEPTH") == 16


def test_only_reads_rtl_files_not_other_context():
    # a non-RTL context entry (e.g. a docs/readme) is ignored.
    ctx = {"docs/readme.md": "parameter SECRET = 99;"}
    assert W.context_param_defaults(_rec(ctx)) == {}


def test_body_assignments_are_not_params():
    # `assign`/reg initialisation in the body must NOT be harvested as a param
    # default — only `parameter`/`localparam` declarations are read.
    ctx = {"rtl/b.sv": (
        "module b (input clk, output reg [7:0] cnt);\n"
        "  always @(posedge clk) cnt = 8'd5;  // NOT a param\n"
        "  wire foo = 42;                      // NOT a param\n"
        "endmodule\n")}
    out = W.context_param_defaults(_rec(ctx))
    assert "cnt" not in out and "foo" not in out
    assert out == {}


def test_merge_does_not_override_prompt_default():
    # context fills BELOW prompt/tb — a prompt-stated default wins. Verify via the
    # merge contract: param_defaults(prompt) ∪ setdefault(context) keeps the prompt
    # value when both name it.
    prompt = "parameter WIDTH = 8;"
    pd = W.param_defaults(prompt)
    assert pd.get("WIDTH") == 8
    ctx = {"rtl/m.sv": "module m #(parameter WIDTH = 4)(input x); endmodule\n"}
    for nm, v in W.context_param_defaults(_rec(ctx)).items():
        pd.setdefault(nm, v)
    assert pd["WIDTH"] == 8  # prompt's 8 NOT overridden by context's 4


def test_empty_and_malformed_records():
    assert W.context_param_defaults(_rec({})) == {}
    assert W.context_param_defaults({"input": {}}) == {}
    assert W.context_param_defaults(None) == {}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
