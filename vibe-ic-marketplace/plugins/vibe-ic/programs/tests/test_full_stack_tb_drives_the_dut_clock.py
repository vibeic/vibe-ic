"""The full-stack TB hard-coded the clock's NAME, so it clocked nothing.

`step_full_stack_tb_gen` opened every testbench it wrote with

    reg clk = 0;
    reg reset_n = 0;
    always #10 clk = ~clk;   // 50 MHz default

and then bound the DUT's ports by name, skipping only the two literals
`clk` and `reset_n`. The clock generator therefore drove the port `clk`
and nothing else. A DUT whose clock is called `i_clk` / `clk_i` /
`sys_clk` / `aclk` got `reg i_clk = 0;` out of the ordinary-input branch,
and NOTHING ever toggled it: the design was simulated with a flat clock
for the entire run. The TB still reached `$finish`, so the step reported
success and wrote `pass.flag`.

MEASURED (subservient x gf180mcuD, clock `i_clk`, reset `i_rst`, plugin
1.14.39, verilator --coverage over the same 700-line DUT and the same
container image):

                        before            after
    line       9.09%  (10/110)     28.18%  (31/110)
    toggle     0.63%  ( 7/1110)    19.01%  (211/1110)
    branch     3.03%  ( 2/66)      13.64%  (  9/66)

The 0.63% toggle figure is the signature: seven nets moved in a 1110-net
design, which is a reset state and then nothing. Step 4's coverage gate
FAILing was the first thing in the whole flow to notice that the design
had never been started.

BIDIRECTIONAL, and each direction is a different way to get this wrong:

  * a DUT clocked on a non-`clk` port MUST get a generator bound to its
    own port (before the fix: no generator reached any DUT port);
  * a DUT clocked on `clk` MUST keep the legacy binding (a fix that only
    moved the hard-coded name would break these);
  * a DUT with NO clock port at all MUST say so in the TB text — a
    testbench that cannot start its DUT must not be indistinguishable
    from one that did.

chip-AGNOSTIC: port-name grammar and Verilog edge keywords only.
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import design_one_shot_runner as R  # noqa: E402


def _mk(tmp_path: Path, rtl: str, ports, top="dut_top") -> Path:
    """A project tree with just enough for `step_full_stack_tb_gen`."""
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / f"{top}.v").write_text(rtl)
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": top, "top_ports": ports}))
    (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({"no_opcodes_in_input": True, "opcodes": []}))
    return proj


def _tb(proj: Path, top="dut_top") -> str:
    R.step_full_stack_tb_gen(proj, top_name=top)
    return (proj / "phase2" / "stage1" / "sim_full_stack"
            / f"tb_{top}_full.v").read_text()


I_CLK_RTL = """
module dut_top(input i_clk, input i_rst, output reg o_q);
  always @(posedge i_clk) begin
    if (i_rst) o_q <= 1'b0; else o_q <= ~o_q;
  end
endmodule
"""
I_CLK_PORTS = [{"name": "i_clk", "direction": "input"},
               {"name": "i_rst", "direction": "input"},
               {"name": "o_q", "direction": "output"}]


def test_a_dut_clocked_on_i_clk_gets_a_generator_on_i_clk(tmp_path):
    """RED direction. Before the fix the emitted TB contained
    `always #10 clk = ~clk;` and `reg i_clk = 0;` — i_clk never moved."""
    tb = _tb(_mk(tmp_path, I_CLK_RTL, I_CLK_PORTS))
    assert "always #10 i_clk = ~i_clk;" in tb, tb
    assert ".i_clk(i_clk)" in tb, tb


def test_the_dut_runs_for_its_own_cycles_not_a_wall_clock_delay(tmp_path):
    """`#1000` is a different number of cycles at every period, and at a
    slow one it is almost none. The post-reset window is a CYCLE COUNT."""
    tb = _tb(_mk(tmp_path, I_CLK_RTL, I_CLK_PORTS))
    assert f"repeat ({R._FS_TB_RUN_CYCLES}) @(posedge i_clk);" in tb, tb


def test_active_high_reset_is_asserted_high(tmp_path):
    """`i_rst` is sampled on the RTL's `if (i_rst)` and its name carries
    no `_n`: driving it the legacy `reset_n` way (0 then 1) would RELEASE
    it at time 0 and then hold the design in reset for the whole run."""
    tb = _tb(_mk(tmp_path, I_CLK_RTL, I_CLK_PORTS))
    assert "i_rst = 1; #100;" in tb, tb
    assert "i_rst = 0; #100;" in tb, tb


ACTIVE_LOW_RTL = """
module dut_top(input clk_i, input rst_ni, output reg o_q);
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) o_q <= 1'b0; else o_q <= ~o_q;
  end
endmodule
"""
ACTIVE_LOW_PORTS = [{"name": "clk_i", "direction": "input"},
                    {"name": "rst_ni", "direction": "input"},
                    {"name": "o_q", "direction": "output"}]


def test_reset_polarity_comes_from_the_rtl_edge_not_a_guess(tmp_path):
    tb = _tb(_mk(tmp_path, ACTIVE_LOW_RTL, ACTIVE_LOW_PORTS))
    assert "always #10 clk_i = ~clk_i;" in tb, tb
    assert "rst_ni = 0; #100;" in tb, tb
    assert "rst_ni = 1; #100;" in tb, tb
    assert "DUT RTL edge sensitivity" in tb, tb


LEGACY_RTL = """
module dut_top(input clk, input reset_n, output reg o_q);
  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) o_q <= 1'b0; else o_q <= ~o_q;
  end
endmodule
"""
LEGACY_PORTS = [{"name": "clk", "direction": "input"},
                {"name": "reset_n", "direction": "input"},
                {"name": "o_q", "direction": "output"}]


def test_a_dut_named_clk_reset_n_keeps_the_legacy_binding(tmp_path):
    """No regression: the shape that already worked must still work, and
    must not grow a second generator on the same net."""
    tb = _tb(_mk(tmp_path, LEGACY_RTL, LEGACY_PORTS))
    assert tb.count("always #10 clk = ~clk;") == 1, tb
    assert ".clk(clk)" in tb and ".reset_n(reset_n)" in tb, tb
    assert "reset_n = 0; #100;" in tb, tb


COMB_RTL = """
module dut_top(input [3:0] a, input [3:0] b, output [4:0] y);
  assign y = a + b;
endmodule
"""
COMB_PORTS = [{"name": "a", "direction": "input", "width_decl": " [3:0]"},
              {"name": "b", "direction": "input", "width_decl": " [3:0]"},
              {"name": "y", "direction": "output", "width_decl": " [4:0]"}]


def test_a_dut_with_no_clock_port_says_so(tmp_path):
    """The unresolved case must DISCLOSE. A TB that cannot start its DUT
    and does not say so is the same defect wearing a passing verdict."""
    tb = _tb(_mk(tmp_path, COMB_RTL, COMB_PORTS))
    assert "NO DUT CLOCK PORT RESOLVED" in tb, tb
    assert "UNEXERCISED" in tb, tb


def test_a_bus_input_is_never_mistaken_for_the_clock(tmp_path):
    """A clock and a reset are single wires. Admitting a bus here is how
    a data port ends up toggled at the clock rate."""
    ports = [{"name": "clk_data", "direction": "input",
              "width_decl": " [7:0]"}] + COMB_PORTS
    tb = _tb(_mk(tmp_path, COMB_RTL, ports))
    assert "always #10 clk_data" not in tb, tb


def test_results_json_records_whether_the_dut_was_clocked(tmp_path):
    """The gap has to be legible without opening the .v."""
    proj = _mk(tmp_path, COMB_RTL, COMB_PORTS)
    R.step_full_stack_tb_gen(proj, top_name="dut_top")
    res = json.loads((proj / "phase2" / "stage1" / "sim_full_stack"
                      / "results.json").read_text())
    sb = res.get("stimulus_binding")
    assert sb is not None, res
    assert sb["dut_is_clocked_by_this_tb"] is False, sb
    assert "UNEXERCISED" in sb["note"], sb

    proj2 = _mk(tmp_path / "b", I_CLK_RTL, I_CLK_PORTS)
    R.step_full_stack_tb_gen(proj2, top_name="dut_top")
    res2 = json.loads((proj2 / "phase2" / "stage1" / "sim_full_stack"
                       / "results.json").read_text())
    sb2 = res2["stimulus_binding"]
    assert sb2["dut_is_clocked_by_this_tb"] is True, sb2
    assert sb2["clock_port"] == "i_clk", sb2
