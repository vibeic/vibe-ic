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


# ---- Moore output discipline (the VerilogEval-v2 Prob089 lesson) ----------
_SPEC_MOORE = (
    "Implement a Moore state machine.\n"
    " - input clk\n - input areset\n - input x\n - output z\n")
_SPEC_PLAIN = (
    "Implement a serial 2's complementer.\n"
    " - input clk\n - input areset\n - input x\n - output z\n")
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
    res, f = run(tmp_path, _SPEC_MOORE, _RTL_MEALY)
    assert 'moore-output-mealy' in rules(f)


def test_moore_spec_clears_registered_moore_output(tmp_path):
    res, f = run(tmp_path, _SPEC_MOORE, _RTL_MOORE)
    assert 'moore-output-mealy' not in rules(f)


def test_no_moore_keyword_does_not_flag_mealy(tmp_path):
    # Conservative: without the word "Moore" in the spec, a Mealy output is fine.
    res, f = run(tmp_path, _SPEC_PLAIN, _RTL_MEALY)
    assert 'moore-output-mealy' not in rules(f)
