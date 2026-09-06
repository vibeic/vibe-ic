"""RB2-06 (#2063) — `cdc_async_input_check` called a signal an async input from
its NAME alone, without checking it is a PORT.

MEASURED on the subservient cell (lane rbsub2, 8HD-8, 2026-09-06): the internal
`wire b_raw = op2sr[0];` was reported `[ERROR] ASYNC_INPUT_NO_SYNC` and was the
ENTIRE failed-gate list of the phase-2/3 completion audit; renaming it `b_lsb`,
with the logic byte-identical, turned the same tree PASS. A verdict that moves
with a spelling and not with the design is not a verdict about the design.

This TIGHTENS the classifier's premise and does not loosen the rule — the
second test below is the control that says so.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'cdc_async_input_check.py'

INTERNAL_WIRE = """
module dut(input i_clk, input i_rst, input [7:0] i_d, output reg o_q);
  wire b_raw = i_d[0];
  always @(posedge i_clk) begin
    if (i_rst) o_q <= 1'b0; else o_q <= b_raw;
  end
endmodule
"""

REAL_ASYNC_PORT = """
module dut(input i_clk, input i_rst, input x_raw, output reg o_q);
  always @(posedge i_clk) begin
    if (i_rst) o_q <= 1'b0; else o_q <= x_raw;
  end
endmodule
"""

SYNCHRONIZED_PORT = """
module dut(input i_clk, input i_rst, input x_raw, output reg o_q);
  reg s1, s2;
  always @(posedge i_clk) begin
    s1 <= x_raw; s2 <= s1;
    if (i_rst) o_q <= 1'b0; else o_q <= s2;
  end
endmodule
"""


def _run(tmp_path, rtl):
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True)
    (d / "dut.v").write_text(rtl)
    return subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)],
                          capture_output=True, text=True)


def test_an_internal_wire_is_never_an_async_input(tmp_path):
    res = _run(tmp_path, INTERNAL_WIRE)
    assert res.returncode == 0, res.stdout
    assert 'ASYNC_INPUT_NO_SYNC' not in res.stdout


def test_a_real_async_input_PORT_is_still_flagged(tmp_path):
    """The control. Same suffix, same use, one difference: it is a declared
    input of the module, so it genuinely crosses into this clock domain."""
    res = _run(tmp_path, REAL_ASYNC_PORT)
    assert res.returncode == 1, res.stdout
    assert "async input 'x_raw'" in res.stdout


def test_a_synchronized_async_input_port_passes(tmp_path):
    res = _run(tmp_path, SYNCHRONIZED_PORT)
    assert res.returncode == 0, res.stdout
