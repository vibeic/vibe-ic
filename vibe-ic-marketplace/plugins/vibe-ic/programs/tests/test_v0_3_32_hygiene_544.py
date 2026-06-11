"""ORGANIC #544 — rtl_hygiene_lint undriven-wire false positives on
instance-output concat connections and 2-D / multi-subscript slice assigns.
NEGATIVE no-leak: a genuinely undriven wire is still reported.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import rtl_hygiene_lint as H  # noqa: E402


def _undriven(src):
    return {f.symbol for f in H.rule_undriven_and_unread(src, "t.v")
            if f.rule == "undriven-wire"}


def test_544a_instance_output_concat_not_undriven():
    src = (
        "module top(input clk, output [7:0] y);\n"
        "  wire [3:0] w_hi;\n"
        "  wire [3:0] w_lo;\n"
        "  splitter u_s(.clk(clk), .o({w_hi, w_lo}));\n"
        "  assign y = {w_hi, w_lo};\n"
        "endmodule\n")
    assert "w_hi" not in _undriven(src)
    assert "w_lo" not in _undriven(src)


def test_544b_2d_slice_assign_not_undriven():
    src = (
        "module m(input [1:0] i, input [3:0] d, output [3:0] o);\n"
        "  wire [3:0] arr [0:3];\n"
        "  assign arr[i][3] = d[3];\n"
        "  assign arr[i][2:0] = d[2:0];\n"
        "  assign o = arr[i];\n"
        "endmodule\n")
    assert "arr" not in _undriven(src)


def test_544_negative_genuinely_undriven_still_reported():
    src = (
        "module m(output o);\n"
        "  wire never_driven;\n"     # no driver at all
        "  wire [3:0] used;\n"
        "  assign used = 4'b0;\n"
        "  assign o = used[0];\n"
        "endmodule\n")
    und = _undriven(src)
    assert "never_driven" in und
    assert "used" not in und
