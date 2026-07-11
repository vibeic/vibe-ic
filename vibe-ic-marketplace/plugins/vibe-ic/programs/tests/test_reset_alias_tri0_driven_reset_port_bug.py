"""BUG REPRODUCTION — ORGANIC reset-alias (#518/#792) additive dual-spelling
wrapper puts the tri0/tri1 net-type pull on the ORIGINAL, TB-DRIVEN reset port,
which breaks any iverilog testbench that procedurally drives that port with a reg.

`emit_variant_alias_wrapper(..., additive_reset_map={"reset": "rst"})` emits (for an
active-high reset):

    input `ifndef YOSYS tri0 `endif reset,   <-- ORIGINAL spec port (the TB drives this)
    input `ifndef YOSYS tri0 `endif rst,     <-- added canonical alias
    ...
    wire reset__rcvar_net = reset | rst;

Because tri0/tri1 are RESOLVED net types, a TB doing
`reg reset; ... dut(.reset(reset)); ... reset = 1;` fails elaboration under iverilog:

    testbench.v: warning: input port reset is coerced to inout.
    testbench.v: error: reset Unable to assign to unresolved wires.

Evidence (v1.3.79 RTLLM clean-room run): confirmed on THREE designs —
up_down_counter, sequence_detector (rst_n), synchronizer (arstn). Each recovers ONLY
by dropping the wrapper and shipping a FLAT module (verified: the flat up_down_counter
prints "Your Design Passed"; the shipped wrapper errors "Unable to assign to
unresolved wires").

WHY IT IS NON-TRIVIAL (left to the maintainer, not hand-fixed here): the #792 intent
is that EITHER spelling may be the one the hidden TB binds, so BOTH default INACTIVE
when undriven. Naively moving tri0/tri1 to the alias-only port (leaving the original a
plain `input`) fixes the drive-the-original case but re-breaks the drive-the-alias case
(the original then floats to X and corrupts `reset | rst`). A correct fix needs a
different mechanism (e.g. a compile-probe of which port the TB actually binds, or
emitting a flat spec-spelling module when only one binding is live).

This test asserts the CORRECT end state: the additive-reset wrapper must elaborate
against a TB that procedurally drives the ORIGINAL spec reset port. It is
xfail(strict=True) TODAY (bug present); when the generator is fixed it will xpass and
strict-xfail flags it → remove the marker.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "reset_clock_variant_alias.py"


def _load():
    spec = importlib.util.spec_from_file_location("reset_clock_variant_alias", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_792_wrapper_puts_tri0_on_the_original_driven_port():
    """White-box: document that the CURRENT generator applies the tri0 pull to the
    ORIGINAL spec port `reset` (not only the added alias). This is the defect root;
    it is NOT xfail (it asserts current behavior so the report stays truthful)."""
    R = _load()
    ports = [("input", "", "clk"), ("input", "", "reset"), ("output", "[7:0]", "count")]
    w = R.emit_variant_alias_wrapper(
        "dut__rcvar_inner", ports, {}, wrapper_name="dut",
        additive_reset_map={"reset": "rst"})
    # the OR-combine + tri0 pull both present (active-high additive reset)
    assert "wire reset__rcvar_net = reset | rst;" in w
    assert "tri0" in w
    # the tri0 qualifier sits on BOTH port faces (the bug): count the guarded pulls
    assert w.count("tri0") >= 2, (
        "expected tri0 on both the original and the alias port face (the defect); "
        f"got:\n{w}")


@pytest.mark.xfail(strict=True, reason=(
    "ORGANIC #518/#792 reset-alias defect: tri0/tri1 on the procedurally-driven "
    "spec reset port breaks iverilog TBs (reset coerced to inout / unable to assign "
    "to unresolved wires). Remove this marker when the generator is fixed."))
def test_additive_reset_wrapper_accepts_reg_driven_original_port(tmp_path):
    """The load-bearing reproduction: a TB that procedurally drives the ORIGINAL
    reset port (as RTLLM/VerilogEval TBs do) must elaborate against the wrapper."""
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not on PATH")
    R = _load()
    ports = [("input", "", "clk"), ("input", "", "reset"), ("output", "[7:0]", "count")]
    wrapper = R.emit_variant_alias_wrapper(
        "dut__rcvar_inner", ports, {}, wrapper_name="dut",
        additive_reset_map={"reset": "rst"})
    core = ("module dut__rcvar_inner(input clk, input reset, output reg [7:0] count);\n"
            "  always @(posedge clk) if (reset) count<=8'd0; else count<=count+1'b1;\n"
            "endmodule\n")
    tb = ("module tb;\n"
          "  reg clk=0, reset; wire [7:0] count;\n"
          "  dut u(.clk(clk), .reset(reset), .count(count));\n"
          "  always #1 clk = ~clk;\n"
          "  initial begin reset=1; #4 reset=0; #10 $display(\"OK\"); $finish; end\n"
          "endmodule\n")
    (tmp_path / "w.sv").write_text(wrapper)
    (tmp_path / "c.sv").write_text(core)
    (tmp_path / "tb.sv").write_text(tb)
    binp = str(tmp_path / "bin")
    c = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", binp,
         str(tmp_path / "w.sv"), str(tmp_path / "c.sv"), str(tmp_path / "tb.sv")],
        capture_output=True, text=True)
    assert c.returncode == 0, (
        "additive-reset wrapper must elaborate against a TB that procedurally drives "
        f"the ORIGINAL spec reset port; iverilog said:\n{c.stderr}")
