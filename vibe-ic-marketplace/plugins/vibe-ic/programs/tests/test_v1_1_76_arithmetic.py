#!/usr/bin/env python3
"""test_v1_1_76_arithmetic.py — pins arithmetic_synth.py (the integer-ARITHMETIC
family deterministic solver: half/full adder, N-bit adder w/ carry-in-MSB, signed
two's-complement adder + signed-overflow flag, add/subtract by a STATED control bit
with an optional zero flag).

POSITIVES — each firing benchmark prompt emits the correct host-verified RTL (key
emitted lines asserted). NEGATIVES (§4.05 NO-LEAK) — ≥5 fixtures just OUTSIDE the
boundary that MUST return None: unstated signedness for overflow, ambiguous /
unstated add-vs-subtract control polarity, unstated carry convention, a
non-arithmetic prompt (Prob132's lying "adder-subtractor" header over pure
conditional logic), and a multiplier (explicitly out of scope).

Every positive is the EXACT VerilogEval-v2 spec-to-rtl prompt text, so the test
pins the real reproduction, not a paraphrase.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import arithmetic_synth as A  # noqa: E402


# --------------------------------------------------------------------------- #
# the REAL prompt texts (verbatim from dataset_spec-to-rtl)                    #
# --------------------------------------------------------------------------- #
HADD = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  a
 - input  b
 - output sum
 - output cout

The module should implement a half adder. A half adder adds two bits
(with no carry-in) and produces a sum and carry-out.
"""

FADD = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  a
 - input  b
 - input  cin
 - output cout
 - output sum

The module should impement a full adder. A full adder adds three bits
(including carry-in) and produces a sum and carry-out.
"""

ADDER4_OVF = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  x   (4 bits)
 - input  y   (4 bits)
 - output sum (5 bits)

Implement a 4-bit adder with full adders. The output sum should include
the overflow bit.
"""

SIGNED_OVF = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  a (8 bits)
 - input  b (8 bits)
 - output s (8 bits)
 - output overflow

Assume that you have two 8-bit 2's complement numbers, a[7:0] and b[7:0].
The module should add these numbers to produce s[7:0]. Also compute
whether a (signed) overflow has occurred.
"""

ADDSUBZ = """
Consider the following adder-subtractor with a zero flag:

  synthesis verilog_input_version verilog_2001
  module TopModule (
      input do_sub,
      input [7:0] a,
      input [7:0] b,
      output reg [7:0] out,
      output reg result_is_zero
  );

      always @(*) begin
          case (do_sub)
            0: out = a+b;
            1: out = a-b;
          endcase

          if (~out)
              result_is_zero = 1;
      end

  endmodule

Unfortunately, this module has a bug. Implement a new version of this
module that fixes the bug.
"""


# --------------------------------------------------------------------------- #
# POSITIVES                                                                    #
# --------------------------------------------------------------------------- #
def test_half_adder_fires_with_carry_concat():
    rtl = A.synth(HADD, "TopModule")
    assert rtl is not None
    assert "module TopModule (" in rtl
    # canonical half adder: {cout, sum} = a + b
    assert "assign {cout, sum} = a + b;" in rtl
    assert "input a" in rtl and "input b" in rtl
    assert "output sum" in rtl and "output cout" in rtl


def test_full_adder_fires_with_three_addends():
    rtl = A.synth(FADD, "TopModule")
    assert rtl is not None
    assert "assign {cout, sum} = a + b + cin;" in rtl
    assert "input cin" in rtl


def test_nbit_unsigned_adder_carry_in_msb():
    rtl = A.synth(ADDER4_OVF, "TopModule")
    assert rtl is not None
    # 5-bit output = 4-bit operands + carry; out = x + y
    assert "output [4:0] sum" in rtl
    assert "input [3:0] x" in rtl and "input [3:0] y" in rtl
    assert "assign sum = x + y;" in rtl


def test_signed_adder_overflow_flag():
    rtl = A.synth(SIGNED_OVF, "TopModule")
    assert rtl is not None
    assert "assign s = a + b;" in rtl
    # signed overflow = same-sign operands but differing result sign
    assert "(~(a[7] ^ b[7]))" in rtl
    assert "(a[7] ^ s[7])" in rtl
    assert "output overflow" in rtl


def test_add_sub_control_with_zero_flag():
    rtl = A.synth(ADDSUBZ, "TopModule")
    assert rtl is not None
    # control polarity taken EXACTLY from the stated case arms
    assert "case (do_sub)" in rtl
    assert "0: out = a + b;" in rtl
    assert "1: out = a - b;" in rtl
    # the bug-fixed zero flag (== 0), not the buggy `if (~out)`
    assert "result_is_zero = (out == 0);" in rtl
    assert "output reg [7:0] out" in rtl
    assert "output reg result_is_zero" in rtl


def test_all_positive_emits_are_well_formed():
    for txt in (HADD, FADD, ADDER4_OVF, SIGNED_OVF, ADDSUBZ):
        rtl = A.synth(txt, "TopModule")
        assert rtl and rtl.rstrip().endswith("endmodule")
        assert rtl.count("module TopModule (") == 1


# --------------------------------------------------------------------------- #
# NEGATIVES — §4.05 NO-LEAK (>=5). Each is just OUTSIDE the firing boundary.   #
# --------------------------------------------------------------------------- #
def test_neg_overflow_requested_but_signedness_unstated():
    # An overflow flag is asked for but the prompt NEVER states signed/unsigned —
    # signed-overflow logic differs from unsigned-carry logic, so we must NOT guess.
    txt = """
 - input  a (8 bits)
 - input  b (8 bits)
 - output s (8 bits)
 - output overflow

Add a and b to produce s. Also compute whether an overflow has occurred.
"""
    assert A.synth(txt, "TopModule") is None


def test_neg_add_sub_polarity_unstated():
    # An add/subtract block whose control polarity is NOT explicitly mapped to
    # add vs subtract (no case arms, prose leaves which value does which) -> SKIP.
    txt = """
 - input  op
 - input  a (8 bits)
 - input  b (8 bits)
 - output out (8 bits)

The module adds or subtracts a and b depending on op.
"""
    assert A.synth(txt, "TopModule") is None


def test_neg_add_sub_ambiguous_duplicate_polarity():
    # An embedded case whose arms are contradictory / don't cover exactly {0,1}
    # with one '+' and one '-' must not fire.
    txt = """
  module TopModule (
      input sel,
      input [7:0] a,
      input [7:0] b,
      output reg [7:0] out
  );
      always @(*) begin
          case (sel)
            0: out = a + b;
            1: out = a + b;   // both arms ADD -> not a genuine add/sub
          endcase
      end
  endmodule
Fix this module.
"""
    assert A.synth(txt, "TopModule") is None


def test_neg_carry_convention_unstated():
    # Two 4-bit operands and a 5-bit output but the prompt NEVER says the extra
    # bit is the carry/overflow (could be a sign-extended result, padding, etc.)
    # -> the carry convention is unstated, SKIP.
    txt = """
 - input  x   (4 bits)
 - input  y   (4 bits)
 - output sum (5 bits)

Implement a circuit that combines x and y into sum.
"""
    assert A.synth(txt, "TopModule") is None


def test_neg_non_arithmetic_lying_header():
    # Prob132_always_if2: the header SAYS "adder-subtractor" but the body is pure
    # conditional latch logic with NO +/- at all. The recognizers demand the real
    # arithmetic structure, so the lying header never fires this path.
    txt = """
Consider the following adder-subtractor with a zero flag:

  module TopModule (
      input      cpu_overheated,
      output reg shut_off_computer,
      input      arrived,
      input      gas_tank_empty,
      output reg keep_driving
  );
      always @(*) begin
          if (cpu_overheated)
             shut_off_computer = 1;
      end
      always @(*) begin
          if (~arrived)
             keep_driving = ~gas_tank_empty;
      end
  endmodule

Unfortunately, this module has a bug. Implement a new version of this
module that fixes the bug.
"""
    assert A.synth(txt, "TopModule") is None


def test_combinational_multiplier_now_solved_by_prose_dialect():
    # v1.1.84 fold: a COMBINATIONAL multiplier is solved deterministically (p = a*b),
    # host-verified by the RTLLM multi_8bit testbench. (A *sequential* multiplier whose
    # cycle protocol is guessed remains DEFERRED -> SKIP; see _dialect_synth's drop set.)
    txt = """
 - input  a (4 bits)
 - input  b (4 bits)
 - output p (8 bits)

Implement a 4-bit unsigned multiplier: p = a * b.
"""
    rtl = A.synth(txt, "TopModule")
    assert rtl is not None and "a * b" in rtl and "endmodule" in rtl


def test_neg_serial_2s_complementer_is_fsm_not_arith():
    # The serial "2's complementer" is a Moore/Mealy FSM (one bit per clock cycle),
    # owned by the FSM path — must NOT be claimed by the arithmetic solver.
    txt = """
 - input  clk
 - input  areset
 - input  x
 - output z

The module should implement a one-input one-output serial 2's
complementer Moore state machine. The input (x) is a series of bits (one
per clock cycle) beginning with the least-significant bit of the number.
Assume all sequential logic is triggered on the positive edge of the clock.
"""
    assert A.synth(txt, "TopModule") is None


def test_neg_truth_table_owned_elsewhere():
    # A function disclosed as a truth table is a different (table-owning) path.
    txt = """
 - input  a
 - input  b
 - output sum

Implement the half adder sum bit. Truth table:
  a b | sum
  0 0 |  0
  0 1 |  1
  1 0 |  1
  1 1 |  0
"""
    assert A.synth(txt, "TopModule") is None


def test_neg_empty_and_garbage():
    assert A.synth("", "TopModule") is None
    assert A.synth("   \n  ", "TopModule") is None
    assert A.synth("this prompt has no ports and no operation at all", "TopModule") is None


# --------------------------------------------------------------------------- #
# determinism                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("txt", [HADD, FADD, ADDER4_OVF, SIGNED_OVF, ADDSUBZ])
def test_deterministic(txt):
    assert A.synth(txt, "TopModule") == A.synth(txt, "TopModule")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
