"""Unit tests for spec_conformance_check.py (Spec↔RTL contract gate).

Anchored to two real misses this gate exists to catch:
  • CVDP arbiter: spec "synchronous reset" vs reference async reset.
  • VerilogEval-v2: port-interface mismatch with an auto-extracted expected
    port list from the natural-language prompt ("- input d (8 bits)").
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_conformance_check.py'
assert SCRIPT.exists()


def run(tmp_path, spec_text, sv, spec_ext='.md', *extra):
    spec = tmp_path / f'spec{spec_ext}'
    spec.write_text(spec_text)
    rtl = tmp_path / 'dut.sv'
    rtl.write_text(sv)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--spec', str(spec),
         '--json', str(jf), *extra, str(rtl)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, findings


def rules(findings):
    return {f['rule'] for f in findings}


# ---- reset conformance (the CVDP lesson) ----------------------------------
SPEC_SYNC = "The module has an active-high synchronous reset that clears outputs."
SPEC_ASYNC = "The module has an asynchronous active-high reset."

RTL_ASYNC = """
module m(input clk, input reset, input [7:0] d, output reg [7:0] q);
  always @(posedge clk or posedge reset)
    if (reset) q <= 0; else q <= d;
endmodule
"""
RTL_SYNC = """
module m(input clk, input reset, input [7:0] d, output reg [7:0] q);
  always @(posedge clk)
    if (reset) q <= 0; else q <= d;
endmodule
"""


def test_spec_sync_rtl_async_is_error(tmp_path):
    res, f = run(tmp_path, SPEC_SYNC, RTL_ASYNC)
    assert res.returncode == 1
    assert 'reset-mode-spec-mismatch' in rules(f)


def test_spec_sync_rtl_sync_passes(tmp_path):
    res, f = run(tmp_path, SPEC_SYNC, RTL_SYNC)
    assert res.returncode == 0
    assert 'reset-mode-spec-mismatch' not in rules(f)


def test_spec_async_rtl_sync_is_error(tmp_path):
    res, f = run(tmp_path, SPEC_ASYNC, RTL_SYNC)
    assert res.returncode == 1
    assert 'reset-mode-spec-mismatch' in rules(f)


def test_reset_polarity_mismatch(tmp_path):
    spec = "Active-low synchronous reset."
    rtl = """
module m(input clk, input rst_n, output reg q);
  always @(posedge clk) if (rst_n) q <= 0; else q <= 1;
endmodule
"""
    res, f = run(tmp_path, spec, rtl)
    # rst_n tested active-high in RTL (`if(rst_n)`) but spec says active-low
    assert 'reset-polarity-spec-mismatch' in rules(f)
    assert res.returncode == 1


# ---- port conformance with NL extraction (the VerilogEval lesson) ---------
NL_SPEC = """
Implement a module named TopModule with the following interface.
 - input  clk
 - input  resetn
 - input  in
 - output out
Reset is active-low synchronous.
"""


def test_nl_port_extraction_mismatch(tmp_path):
    # RTL has the wrong interface (different ports) -> missing + extra.
    rtl = """
module TopModule(input clk, input w, input R, output reg Q);
  always @(posedge clk) Q <= w;
endmodule
"""
    res, f = run(tmp_path, NL_SPEC, rtl, '.txt')
    assert res.returncode == 1
    assert 'port-missing' in rules(f) and 'port-extra' in rules(f)


def test_nl_port_extraction_match_passes(tmp_path):
    rtl = """
module TopModule(input clk, input resetn, input in, output out);
  reg [3:0] sr;
  always @(posedge clk) if(!resetn) sr<=0; else sr<={sr[2:0],in};
  assign out = sr[3];
endmodule
"""
    res, f = run(tmp_path, NL_SPEC, rtl, '.txt')
    assert 'port-missing' not in rules(f)
    assert 'port-extra' not in rules(f)
    assert res.returncode == 0


def test_nl_width_annotation_parsed(tmp_path):
    spec = """
 - input  clk
 - input  d   (8 bits)
 - output q   (8 bits)
"""
    rtl_wrong = """
module TopModule(input clk, input [3:0] d, output reg [7:0] q);
  always @(posedge clk) q <= d;
endmodule
"""
    res, f = run(tmp_path, spec, rtl_wrong, '.txt')
    assert 'port-width-mismatch' in rules(f)   # spec d=8 vs RTL d=4
    assert res.returncode == 1


# ---- markdown module header spec must not leak prose ports ----------------
def test_markdown_header_no_prose_false_ports(tmp_path):
    spec = """
# Spec
The arbiter provides valid and grant index outputs and scans inputs.

```verilog
module arb(
    input clk,
    input reset,
    input [7:0] req,
    output reg [7:0] grant
);
```
Active-high synchronous reset.
"""
    rtl = """
module arb(input clk, input reset, input [7:0] req, output reg [7:0] grant);
  always @(posedge clk) if(reset) grant<=0; else grant<=req;
endmodule
"""
    res, f = run(tmp_path, spec, rtl)
    # "provides"/"scans" prose must NOT become ports; exact match -> PASS.
    assert rules(f) == set() or 'port-missing' not in rules(f)
    assert res.returncode == 0


# ---- latency advisory is INFO (never fails) -------------------------------
def test_latency_mismatch_is_advisory(tmp_path):
    spec = "Registered output with one clock cycle latency. Asynchronous reset."
    rtl = """
module m(input a, input b, output y);
  assign y = a & b;
endmodule
"""
    res, f = run(tmp_path, spec, rtl)
    # combinational output vs spec's registered expectation -> INFO, exit 0
    assert res.returncode == 0
    assert 'latency-mismatch' in rules(f)


def test_json_contract_spec(tmp_path):
    spec = json.dumps({
        "module": "m",
        "ports": [{"name": "clk", "direction": "input", "width": 1},
                  {"name": "rst", "direction": "input", "width": 1},
                  {"name": "q", "direction": "output", "width": 8}],
        "reset": {"mode": "synchronous", "polarity": "active-high"},
    })
    # spec declares ports clk/q + a sync active-high reset; RTL must match both
    rtl = """
module m(input clk, input rst, output reg [7:0] q);
  always @(posedge clk) if (rst) q <= 0; else q <= q + 1;
endmodule
"""
    res, f = run(tmp_path, spec, rtl, '.json')
    assert res.returncode == 0
    assert rules(f) == set()


# ---- function/task argument declarations are NOT module ports -------------
# Regression for the VerilogEval-v2 v0.1.10 false-positive (Prob141/149/153):
# `input`/`output` inside a function/task body were parsed as phantom module
# ports, raising spurious port-extra ERRORs and forcing needless RTL rewrites.
def test_function_task_args_not_counted_as_ports(tmp_path):
    spec = (
        "Implement a module named TopModule with the following interface.\n"
        " - input  a (8 bits)\n"
        " - output q (8 bits)\n"
    )
    rtl = """
module TopModule(input [7:0] a, output [7:0] q);
  function [7:0] inc;
    input [7:0] v;
    input       c;
    begin inc = v + (c ? 8'd1 : 8'd0); end
  endfunction
  task drive; input x; begin end endtask
  assign q = inc(a, 1'b1);
endmodule
"""
    res, f = run(tmp_path, spec, rtl)
    # No phantom v/c/x ports → no port-extra; spec a/q match RTL a/q.
    assert 'port-extra' not in rules(f)
    assert res.returncode == 0


# ---- FSM output-style conformance (sibling of reset-mode; semantic detection) ----
# Mealy-vs-Moore is a valid design choice, so this fires ONLY when the spec
# semantically DECLARES a Moore requirement (negation/possessive-aware), never on
# a bare keyword. Anchored to VerilogEval-v2 Prob089.
_RTL_MEALY = """
module TopModule(input clk, input areset, input x, output z);
  reg state;
  always @(posedge clk or posedge areset) if(areset) state<=0; else state<=x?1:state;
  assign z = (state==0) ? x : ~x;
endmodule
"""
_RTL_MOORE = """
module TopModule(input clk, input areset, input x, output z);
  reg c, z_reg;
  always @(posedge clk or posedge areset) if(areset) begin c<=0; z_reg<=0; end
    else begin z_reg <= x ^ c; c <= c | x; end
  assign z = z_reg;
endmodule
"""


def test_moore_spec_flags_mealy_output(tmp_path):
    spec = "Implement a Moore state machine.\n - input clk\n - input areset\n - input x\n - output z\n"
    res, f = run(tmp_path, spec, _RTL_MEALY)
    assert 'fsm-output-style-mismatch' in rules(f)


def test_moore_spec_clears_registered_moore(tmp_path):
    spec = "Implement a Moore state machine.\n - input clk\n - input areset\n - input x\n - output z\n"
    res, f = run(tmp_path, spec, _RTL_MOORE)
    assert 'fsm-output-style-mismatch' not in rules(f)


def test_no_fsm_declaration_does_not_flag_mealy(tmp_path):
    # No Moore/Mealy declaration → Mealy is a valid choice → no finding.
    spec = "Implement a serial 2's complementer.\n - input clk\n - input areset\n - input x\n - output z\n"
    res, f = run(tmp_path, spec, _RTL_MEALY)
    assert 'fsm-output-style-mismatch' not in rules(f)


def test_moore_possessive_and_negation_not_misread(tmp_path):
    # "Moore's law" + "not a Moore machine" must NOT be read as a Moore requirement.
    spec = ("Recall Moore's law. This is not a Moore machine.\n"
            " - input clk\n - input areset\n - input x\n - output z\n")
    res, f = run(tmp_path, spec, _RTL_MEALY)
    assert 'fsm-output-style-mismatch' not in rules(f)


# ---- multi-module-header spec: contract must come from the TopModule target ----
# Code-completion / bug-fix prompts embed a reference or buggy module before the real
# `module TopModule(...)` header. The contract extractor must take ports from TopModule,
# not the embedded example. Regression for VerilogEval-Human Prob062/104.
def test_multi_module_header_prefers_topmodule(tmp_path):
    spec = (
        "Find the bug and fix this 8-bit wide 2-to-1 mux.\n\n"
        "  module top_module ( input sel, input [7:0] a, input [7:0] b, output out );\n"
        "      assign out = (~sel & a) | (sel & b);\n"
        "  endmodule\n\n"
        "module TopModule (\n  input sel,\n  input [7:0] a,\n  input [7:0] b,\n"
        "  output reg [7:0] out\n);\n"
    )
    rtl = """
module TopModule(input sel, input [7:0] a, input [7:0] b, output reg [7:0] out);
  always @(*) out = sel ? a : b;
endmodule
"""
    res, f = run(tmp_path, spec, rtl)
    # out is 8-bit per the TopModule header — NOT 1-bit from the embedded buggy module.
    assert 'port-width-mismatch' not in rules(f)
    assert 'port-extra' not in rules(f)


# ---- JSON `dir` key + parameterized width (defects #3 / #4) ----------------
_RTL_WB = """
module wb_if #(parameter WB_AW = 32, parameter WB_DW = 16)(
    input  wire              clk,
    input  wire [WB_AW-1:0]  adr,
    input  wire [WB_DW-1:0]  dat_i,
    output wire [WB_DW-1:0]  dat_o
);
    assign dat_o = dat_i;
endmodule
"""


def test_json_spec_dir_key_no_false_direction_mismatch(tmp_path):
    """A JSON L-doc spec using the `dir` port key must not mis-flag outputs
    (previously every port defaulted to 'input')."""
    spec = json.dumps({"module": "wb_if", "ports": [
        {"name": "clk", "dir": "input", "width": 1},
        {"name": "adr", "dir": "input", "width": 32},
        {"name": "dat_i", "dir": "input", "width": 16},
        {"name": "dat_o", "dir": "output", "width": 16}]})
    res, findings = run(tmp_path, spec, _RTL_WB, '.json', '--top', 'wb_if')
    assert 'port-direction-mismatch' not in rules(findings), findings
    assert 'port-width-mismatch' not in rules(findings), findings


def test_json_spec_dir_key_still_catches_real_direction_error(tmp_path):
    """Proven-negative: a genuinely wrong direction is still flagged."""
    spec = json.dumps({"module": "wb_if", "ports": [
        {"name": "clk", "dir": "input", "width": 1},
        {"name": "adr", "dir": "output", "width": 32},   # WRONG (RTL: input)
        {"name": "dat_i", "dir": "input", "width": 16},
        {"name": "dat_o", "dir": "output", "width": 16}]})
    res, findings = run(tmp_path, spec, _RTL_WB, '.json', '--top', 'wb_if')
    assert 'port-direction-mismatch' in rules(findings), findings


def test_unresolvable_param_width_skips_assertion(tmp_path):
    """RTL bound references a param not declared in-module -> width UNKNOWN ->
    the width assertion is skipped, not fired as a false mismatch."""
    rtl = ("module u(input clk, input [EXT_W-1:0] adr, output [7:0] stat);\n"
           "  assign stat = adr[7:0];\nendmodule\n")
    spec = json.dumps({"module": "u", "ports": [
        {"name": "clk", "dir": "input", "width": 1},
        {"name": "adr", "dir": "input", "width": 32},
        {"name": "stat", "dir": "output", "width": 8}]})
    res, findings = run(tmp_path, spec, rtl, '.json', '--top', 'u')
    assert 'port-width-mismatch' not in rules(findings), findings
