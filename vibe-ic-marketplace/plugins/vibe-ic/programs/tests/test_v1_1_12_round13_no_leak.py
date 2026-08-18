"""Step-2.7 §4.05 guards for PR #7 (CVDP round-13) — two reproduced HIGH/MED
leaks remediated.

(A) spec_coverage_check `_tb_exercises_byte_order_region` reported a CORROBORATED
    byte_order requirement COVERED whenever the TB merely had a loop + ANY `vec[i]`
    + ANY `==` — so an incidental `for(i) scratch[i]=i; if(i==4)` (or a self-compare
    `if(junk[i]==8'h00)`) masked a real ordering coverage gap. FIX: require a real
    ordering ASSERTION — a vector===vector equality (never counter==literal or
    bit==literal) whose operand is the bit-driven vector (and a DUT port when known).

(B) fsm_error_invariant `_signal_is_error` dropped GLUED all-lowercase error flags
    (rxfailure / txaborted / pktrejected / parityfailure / crcfailure) because the
    error word is internal to the segment. FIX: match unambiguous multi-letter
    error substrings (failure/abort/reject/error/timeout) anywhere, while keeping
    the `interrupt` family exempt.

chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import spec_coverage_check as SCC  # noqa: E402
import fsm_error_invariant as FEI  # noqa: E402


# ── (A) byte_order: incidental loop/index/eq must NOT count as ordering ───────
_INCIDENTAL_SCRATCH = (
    "module tb; integer i; reg [7:0] scratch [0:3];\n"
    "  initial begin\n"
    "    for (i=0;i<4;i=i+1) begin scratch[i]=i; end\n"
    "    if (i==4) $display(\"warmup done\");\n"
    "  end endmodule\n")
_INCIDENTAL_SELFCMP = (
    "module tb; integer i; reg [7:0] junk [0:3];\n"
    "  initial for (i=0;i<4;i=i+1) begin junk[i]=i; if (junk[i]==8'h00) $display(\"z\"); end\n"
    "endmodule\n")
# a genuine ordering TB: per-bit drive of `frame`, asserted against DUT port out.
_FAITHFUL_ORDER = (
    "module tb; integer i; reg [11:0] frame;\n"
    "  initial begin\n"
    "    frame = 12'h456;\n"
    "    for (i=0;i<12;i++) send_bit(frame[i]);\n"
    "    if (ir_frame_out !== frame) $display(\"ORDER MISMATCH\");\n"
    "  end endmodule\n")


def test_incidental_scratch_loop_is_not_byte_order_coverage():
    assert SCC._tb_exercises_byte_order_region(_INCIDENTAL_SCRATCH) is False


def test_incidental_self_compare_is_not_byte_order_coverage():
    assert SCC._tb_exercises_byte_order_region(_INCIDENTAL_SELFCMP) is False


def test_faithful_ordering_tb_is_byte_order_coverage():
    # with the DUT port known, the vector===vector assertion ties to the DUT.
    assert SCC._tb_exercises_byte_order_region(
        _FAITHFUL_ORDER, {"ir_frame_out", "ir_frame_valid"}) is True
    # even without the port set, the vector===vector assertion on the driven
    # vector still qualifies (degraded tie).
    assert SCC._tb_exercises_byte_order_region(_FAITHFUL_ORDER) is True


# ── (B) fsm error signal: glued forms fire, interrupt family stays exempt ─────
@pytest.mark.parametrize("name", [
    "rxfailure", "txaborted", "pktrejected", "parityfailure", "crcfailure",
    "rxtimeout", "dataerror"])
def test_glued_error_forms_fire(name):
    assert FEI._signal_is_error(name) is True


@pytest.mark.parametrize("name", [
    "cpu_interrupt", "interrupt_valid", "interrupt_idx", "interrupt_requests",
    "nvic_interrupt", "merrily"])
def test_interrupt_family_stays_exempt(name):
    assert FEI._signal_is_error(name) is False


@pytest.mark.parametrize("name", [
    "err_o", "o_error", "timeout_err", "rx_error", "fail_flag", "pslverr",
    "errorFlag", "rx_failure", "tx_aborted"])
def test_existing_error_forms_preserved(name):
    assert FEI._signal_is_error(name) is True


def test_glued_error_rtl_fires_end_to_end(tmp_path):
    rtl = ("module rx_phy(input clk, input bad, output logic rxfailure,\n"
           "  output logic txaborted, output logic pktrejected);\n"
           "  always_ff @(posedge clk) begin if(bad) begin\n"
           "    rxfailure<=1'b1; txaborted<=1'b1; pktrejected<=1'b1; end end\nendmodule\n")
    assert len(FEI.find_error_assertions(rtl, "rx.sv")) >= 1


def test_interrupt_rtl_does_not_fire_end_to_end(tmp_path):
    rtl = ("module m(input clk, input ev, output logic cpu_interrupt,\n"
           "  output logic interrupt_valid);\n"
           "  always_ff @(posedge clk) begin if(ev) begin\n"
           "    cpu_interrupt<=1'b1; interrupt_valid<=1'b1; end end\nendmodule\n")
    assert FEI.find_error_assertions(rtl, "m.sv") == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
