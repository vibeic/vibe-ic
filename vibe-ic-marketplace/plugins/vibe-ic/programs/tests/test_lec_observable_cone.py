"""Native controls for the emitted model, including future observable state."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import lec_run


@pytest.mark.skipif(shutil.which("yosys") is None, reason="native Yosys required")
@pytest.mark.parametrize("case,equivalent", [
    ("unused_upper_bits", True),
    ("corrupt_top_output", False),
    ("merged_state_alias", True),
    ("corrupt_future_state", False),
])
def test_native_observable_model_keeps_ports_and_future_state(tmp_path, case, equivalent):
    if case in ("unused_upper_bits", "corrupt_top_output"):
        gold = ("module neutral(input [7:0] d, output [3:0] y); "
                "wire [7:0] wide = d ^ 8'h96; assign y = wide[3:0]; endmodule\n")
        mask = "7" if case == "corrupt_top_output" else "6"
        gate = ("module neutral(input [7:0] d, output [3:0] y); "
                f"wire [7:0] wide = {{4'b0, d[3:0] ^ 4'h{mask}}}; "
                "assign y = wide[3:0]; endmodule\n")
        expected_ports = {"d": ("input", 8), "y": ("output", 4)}
    elif case == "merged_state_alias":
        gold = ("module neutral(input clk, rst, d, output reg a, b); "
                "always @(posedge clk) begin a <= rst ? 0 : d; "
                "b <= rst ? 0 : d; end endmodule\n")
        gate = ("module neutral(input clk, rst, d, output wire a, output reg b); "
                "always @(posedge clk) b <= rst ? 0 : d; assign a = b; endmodule\n")
        expected_ports = {"clk": ("input", 1), "rst": ("input", 1),
                          "d": ("input", 1), "a": ("output", 1), "b": ("output", 1)}
    else:
        gold = ("module neutral(input clk, d, output y); reg [7:0] state; "
                "always @(posedge clk) state <= {d, state[7:1]}; "
                "assign y = state[0]; endmodule\n")
        gate = gold.replace("{d, state[7:1]}", "{~d, state[7:1]}")
        expected_ports = {"clk": ("input", 1), "d": ("input", 1), "y": ("output", 1)}
    rtl, netlist = tmp_path / "rtl.v", tmp_path / "netlist.v"
    rtl.write_text(gold)
    netlist.write_text(gate)
    # The gate arm's public contract is a netlist. Legalize the independent
    # fixture's processes before handing it to that arm, as synthesis does.
    if case in ("merged_state_alias", "corrupt_future_state"):
        lowered = tmp_path / "lowered.v"
        prepare = subprocess.run(
            ["yosys", "-Q", "-T", "-p",
             f"read_verilog {netlist}; proc; opt_clean; write_verilog -noattr -noexpr {lowered}"],
            capture_output=True, text=True, timeout=60)
        assert prepare.returncode == 0, prepare.stdout + prepare.stderr
        netlist = lowered
    model = tmp_path / "model.json"
    script = tmp_path / "proof.ys"
    script.write_text(lec_run.build_equiv_script([str(rtl)], str(netlist), "neutral", None,
                                                gate_is_generic=True)
                      + f"write_json {model}\nequiv_status -assert\n")
    result = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == (0 if equivalent else 1), result.stdout + result.stderr
    assert "ERROR:" not in result.stderr or "unproven $equiv cells" in result.stderr
    module = json.loads(model.read_text())["modules"]["equiv"]
    actual_ports = {}
    for name, port in module["ports"].items():
        base = name.split("[")[0]
        direction, width = actual_ports.get(base, (port["direction"], 0))
        actual_ports[base] = (direction, width + len(port["bits"]))
    assert actual_ports == expected_ports
    if case == "corrupt_future_state":
        # The high bits reach y only in future cycles. A combinational cone
        # or a ports-only proof would lose these named state obligations.
        assert all(f"state[{bit}]" in module["netnames"] for bit in range(8))
        assert "Equivalence successfully proven!" not in result.stdout
