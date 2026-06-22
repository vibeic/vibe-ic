"""v1.1.60 — harness_exact_selfverify GATE B must NOT false-block on the
assignment-operator STYLE warnings COMBDLY (`<=` in a combinational always) and
BLKSEQ (`=` in a sequential always): iverilog accepts both, the VerilogEval/RTLLM
scorer runs only iverilog+vvp and never lints, so blocking emit on them silently
drops a host-passing design (Prob028_m2014_q4a's correct D-latch tripped this).

§4.05 no-leak: a GENUINE verilator %Error and an ACCIDENTAL inferred latch
(non-clock guard, missing branch) must STILL BLOCK.
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import harness_exact_selfverify as h  # noqa: E402

_HAS_VERILATOR = shutil.which("verilator") is not None

# the Prob028 shape: a correct transparent D latch using `<=` in always @(*)
RTL_COMBDLY_LATCH = """
module TopModule(input d, input ena, output reg q);
  always @(*) q <= ena ? d : q;
  initial q = 1'b0;
endmodule
"""

# BLKSEQ: blocking `=` in a clocked always (style, iverilog-accepted)
RTL_BLKSEQ = """
module TopModule(input clk, input d, output reg q);
  always @(posedge clk) q = d;
  initial q = 1'b0;
endmodule
"""

# genuine %Error: reference to an undeclared signal (must still BLOCK)
RTL_REAL_ERROR = """
module TopModule(output reg q);
  always @(*) q = undeclared_signal_xyz & 1'b1;
endmodule
"""

# accidental inferred latch: data-enable guard, no else (must still BLOCK)
RTL_ACCIDENTAL_LATCH = """
module TopModule(input sel, input a, input b, output reg y);
  always @(*) if (sel) y = a & b;
endmodule
"""


def _gateB(rtl):
    import tempfile
    d = Path(tempfile.mkdtemp())
    p = d / "TopModule.sv"; p.write_text(rtl)
    return h.gate_b_verilator_lint(p, "TopModule", d, False)


def test_combdly_in_style_suppress_list():
    assert "COMBDLY" in h._LINT_STYLE_SUPPRESS
    assert "BLKSEQ" in h._LINT_STYLE_SUPPRESS


@pytest.mark.skipif(not _HAS_VERILATOR, reason="verilator unavailable")
def test_combdly_latch_does_not_block():
    assert _gateB(RTL_COMBDLY_LATCH)["verdict"] == "PASS"


@pytest.mark.skipif(not _HAS_VERILATOR, reason="verilator unavailable")
def test_blkseq_does_not_block():
    assert _gateB(RTL_BLKSEQ)["verdict"] == "PASS"


@pytest.mark.skipif(not _HAS_VERILATOR, reason="verilator unavailable")
def test_real_error_still_blocks():  # no-leak
    assert _gateB(RTL_REAL_ERROR)["verdict"] == "BLOCK"


@pytest.mark.skipif(not _HAS_VERILATOR, reason="verilator unavailable")
def test_accidental_latch_still_blocks():  # no-leak
    assert _gateB(RTL_ACCIDENTAL_LATCH)["verdict"] == "BLOCK"
