"""ORGANIC #575 — sv2v mixed-driver fixup missed begin-less
single-statement always blocks: the procedural-lvalue collector only
matched `always ... begin ... end`, so `always @(posedge clk) if (we)
q <= d;` was not collected, mixed_driver_nets() returned empty, the
fixup was a silent no-op and iverilog kept rejecting the file.

Fix: _beginless_proc_bodies() captures the single statement after the
event control (extending across `else` continuations) and harvests its
lvalues.  The byte-identical-no-op guarantee for clean files holds.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sv2v_mixed_driver_fixup as FX  # noqa: E402


_BEGINLESS_MIXED = """\
module t (input wire clk, input wire we, input wire d, output wire q_o);
  reg q;
  assign q = 1'b0;
  always @(posedge clk) if (we) q <= d;
  assign q_o = q;
endmodule
"""

_BLOCK_MIXED = """\
module t (input wire clk, input wire we, input wire d, output wire q_o);
  reg q;
  assign q = 1'b0;
  always @(posedge clk) begin
    if (we) q <= d;
  end
  assign q_o = q;
endmodule
"""


def test_beginless_always_mixed_driver_detected():
    """The issue's exact shape: begin-less always + continuous assign."""
    nets = FX.mixed_driver_nets(_BEGINLESS_MIXED)
    assert "q" in nets


def test_beginless_always_fixup_removes_assign(tmp_path):
    (tmp_path / "t.v").write_text(_BEGINLESS_MIXED)
    rc = FX.main([str(tmp_path / "t.v")])
    assert rc == 0
    fixed = (tmp_path / "t.v").read_text()
    assert "assign q =" not in fixed          # mixed-driver assign removed
    assert "assign q_o = q;" in fixed          # unrelated assign kept
    assert "always @(posedge clk) if (we) q <= d;" in fixed


def test_beginless_if_else_collects_both_branches():
    txt = (
        "module t(input wire clk, input wire c);\n"
        "  reg a;\n"
        "  assign a = 1'b0;\n"
        "  always @(posedge clk)\n"
        "    if (c)\n"
        "      a <= 1'b1;\n"
        "    else\n"
        "      a <= 1'b0;\n"
        "endmodule\n"
    )
    assert "a" in FX.mixed_driver_nets(txt)
    fixed = FX.fixup(txt)
    assert "assign a =" not in fixed


def test_block_shape_still_fixed_regression(tmp_path):
    """#546's original begin/end shape keeps working."""
    (tmp_path / "b.v").write_text(_BLOCK_MIXED)
    rc = FX.main([str(tmp_path / "b.v")])
    assert rc == 0
    fixed = (tmp_path / "b.v").read_text()
    assert "assign q =" not in fixed
    assert "assign q_o = q;" in fixed


def test_clean_file_byte_identical_noop():
    clean = (
        "module t(input wire clk, input wire d, output reg q);\n"
        "  always @(posedge clk) q <= d;\n"
        "endmodule\n"
    )
    assert FX.fixup(clean) == clean
    assert FX.mixed_driver_nets(clean) == frozenset()


def test_beginless_initial_collected():
    txt = (
        "module t;\n"
        "  reg r;\n"
        "  assign r = 1'b1;\n"
        "  initial r = 1'b0;\n"
        "endmodule\n"
    )
    assert "r" in FX.mixed_driver_nets(txt)
