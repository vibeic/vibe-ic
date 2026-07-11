"""ORGANIC reset-alias (#518/#792) additive dual-spelling wrapper vs reg-driven
TBs — reproduction (PR #115) + the fixed contract.

THE DEFECT (reproduced on stock Ubuntu 22.04 iverilog 11.0 with the REAL RTLLM
up_down_counter testbench): the additive wrapper used to put the tri0/tri1
net-type pull on BOTH port faces, including the ORIGINAL spec port the TB
drives. tri0/tri1 are resolved net types, so iverilog 11 coerces the input
port to inout and rejects the procedural drive:

    testbench.v:11: warning: input port reset is coerced to inout.
    testbench.v:24: error: reset Unable to assign to unresolved wires.

(iverilog 12+ tolerates the drive, which is why the defect only bites on
stock-iverilog-11 hosts — a platform the public plugin targets.)

THE FIX (empirically validated on iverilog 11.0 / 12.0 / fork 14-devel AND
Verilator 5.x, 6 bind x polarity cases each): both faces are PLAIN inputs; the
inactive-default pull moves to INTERNAL tri0/tri1 nets (an undriven face
floats z, the continuous assign transfers it, the pull resolves it INACTIVE —
IEEE 1364 net resolution). Verilator alone keeps the pull on the PORT behind
`ifdef VERILATOR (it ties an unbound plain input to 0, never z, so an
internal pull cannot fire there — and it accepts reg-driven tri ports without
iverilog's coercion error). Yosys sees plain inputs + the plain combine,
unchanged.
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


def test_792_wrapper_keeps_tri_off_the_iverilog_port_faces():
    """White-box (the fixed contract): NO tri0/tri1 on any port face outside the
    `ifdef VERILATOR guard; the pull lives on INTERNAL __rcvar_pull nets; the
    combine exists in the VERILATOR/YOSYS arms (port-direct) AND the default arm
    (via the pull nets)."""
    R = _load()
    ports = [("input", "", "clk"), ("input", "", "reset"), ("output", "[7:0]", "count")]
    w = R.emit_variant_alias_wrapper(
        "dut__rcvar_inner", ports, {}, wrapper_name="dut",
        additive_reset_map={"reset": "rst"})
    # the OR-combine both port-direct (VERILATOR/YOSYS arms) and pull-net based
    assert "wire reset__rcvar_net = reset | rst;" in w
    assert "wire reset__rcvar_net = reset__rcvar_pull | rst__rcvar_pull;" in w
    assert "tri0 reset__rcvar_pull;" in w and "tri0 rst__rcvar_pull;" in w
    # every tri token in the PORT LIST is wrapped by `ifdef VERILATOR — verify by
    # checking the header (up to the port-list close) has tri only right after
    # an `ifdef VERILATOR line
    header = w.split(");", 1)[0]
    hlines = header.splitlines()
    for i, ln in enumerate(hlines):
        if ln.strip().startswith(("tri0", "tri1")):
            assert i > 0 and hlines[i - 1].strip() == "`ifdef VERILATOR", (
                f"port-face tri outside `ifdef VERILATOR at header line {i}:\n{w}")
    # and the old `ifndef YOSYS port-face guard is gone
    assert "`ifndef YOSYS\n    tri" not in w


def test_additive_reset_wrapper_accepts_reg_driven_original_port(tmp_path):
    """The load-bearing reproduction (xfail REMOVED — fixed): a TB that
    procedurally drives the ORIGINAL reset port (as RTLLM/VerilogEval TBs do)
    elaborates against the wrapper."""
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


@pytest.mark.parametrize("bind_face", ["orig", "alias", "both"])
@pytest.mark.parametrize("pol", ["ah", "al"])
def test_additive_wrapper_reset_matrix_behaves(tmp_path, bind_face, pol):
    """Functional matrix on the host iverilog: whichever face the TB reg-drives
    (original / canonical alias / both), reset asserts AND deasserts correctly
    for both polarities. The undriven face must default INACTIVE via the
    internal pull (never freeze the design in reset, never float x into it)."""
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not on PATH")
    R = _load()
    active_low = pol == "al"
    orig, canon = ("rst_n", "resetn") if active_low else ("reset", "rst")
    ports = [("input", "", "clk"), ("input", "", orig), ("output", "[7:0]", "count")]
    wrapper = R.emit_variant_alias_wrapper(
        "dut__rcvar_inner", ports, {}, wrapper_name="dut",
        additive_reset_map={orig: canon})
    cond = f"!{orig}" if active_low else orig
    core = (f"module dut__rcvar_inner(input clk, input {orig}, output reg [7:0] count);\n"
            f"  always @(posedge clk) if ({cond}) count<=8'd0; else count<=count+1'b1;\n"
            f"endmodule\n")
    conns = {"orig": f".{orig}(r)", "alias": f".{canon}(r)",
             "both": f".{orig}(r), .{canon}(r)"}[bind_face]
    a, d = ("0", "1") if active_low else ("1", "0")
    tb = (f"module tb;\n"
          f"  reg clk=0, r; wire [7:0] count; reg [7:0] snap;\n"
          f"  dut u({conns}, .clk(clk), .count(count));\n"
          f"  always #1 clk = ~clk;\n"
          f"  initial begin\n"
          f"    r = {a}; #5;\n"
          f"    if (count !== 8'd0) $display(\"BAD_reset_ineffective\");\n"
          f"    else begin r = {d}; #6; snap = count;\n"
          f"      if (snap === 8'd0 || snap === 8'hxx) $display(\"BAD_not_counting\");\n"
          f"      else $display(\"OKAY\"); end\n"
          f"    $finish;\n"
          f"  end\n"
          f"endmodule\n")
    (tmp_path / "w.sv").write_text(wrapper)
    (tmp_path / "c.sv").write_text(core)
    (tmp_path / "tb.sv").write_text(tb)
    binp = str(tmp_path / "bin")
    c = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", binp,
         str(tmp_path / "w.sv"), str(tmp_path / "c.sv"), str(tmp_path / "tb.sv")],
        capture_output=True, text=True)
    assert c.returncode == 0, c.stderr
    r = subprocess.run(["vvp", binp], capture_output=True, text=True, timeout=60)
    assert "OKAY" in r.stdout, (bind_face, pol, r.stdout, r.stderr)
