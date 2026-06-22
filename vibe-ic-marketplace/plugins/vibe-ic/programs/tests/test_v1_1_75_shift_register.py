#!/usr/bin/env python3
"""Tests for programs/shift_register_synth.py — the shift-register / rotate /
barrel-shift deterministic SOLVER.

POSITIVE: each of the six VE-Human target prompts FIRES and the emitted RTL
contains the load-bearing structural lines (we pin the exact shift/rotate/fill
expressions and the control-priority ladder, since a subtly-wrong one would still
pass lint/synth — the §4.05 silent-leak failure mode).

NEGATIVE (§4.05 NO-LEAK): six boundary cases, each one stated-fact removed from a
real firing prompt (unstated reset polarity / unstated reset sync-vs-async /
ambiguous arithmetic-vs-logical / unstated load>ena priority / unstated shift-in /
incomplete rotate direction map) MUST return None. A wrong shift register is far
worse than a skip.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.normpath(os.path.join(_HERE, ".."))   # programs/ (solver dir)
sys.path.insert(0, _PROGRAMS)

import shift_register_synth as S   # noqa: E402


# --------------------------------------------------------------------------- #
# The six real VE-Human target prompts (verbatim structure-bearing text).
# --------------------------------------------------------------------------- #
PROB060 = """
 - input  clk
 - input  resetn
 - input  in
 - output out

The module should implement a shift register with four D flops. Assume
all sequential logic is triggered on the positive edge of the clock.
Reset is active-low synchronous resettable.
"""

PROB061 = """
 - input  clk
 - input  w
 - input  R
 - input  E
 - input  L
 - output Q

The module will be one stage in a larger n-bit shift register circuit.
Input E is for enabling shift, R for value to load, L is asserted when it
should load, and w is the input from the prevous stage of the shift
register. Assume all sequential logic is triggered on the positive edge
of the clock.
"""

PROB084 = """
 - input  clk
 - input  enable
 - input  S
 - input  A
 - input  B
 - input  C
 - output Z

The module should implement a circuit for an 8x1 memory, where writing to
the memory is accomplished by shifting-in bits, and reading is "random
access", as in a typical RAM. First, create an 8-bit shift register with 8
D-type flip-flops. Label the flip-flop outputs from Q[0]...Q[7]. The
shift register input should be called S, which feeds the input of Q[0]
(MSB is shifted in first). The enable input is synchronous active high
and controls whether to shift. Extend the circuit to have 3 additional
inputs A,B,C and an output Z. The circuit's behaviour should be as
follows: when ABC is 000, Z=Q[0], when ABC is 001, Z=Q[1], and so on.
"""

PROB085 = """
 - input  clk
 - input  areset
 - input  load
 - input  ena
 - input  data (4 bits)
 - output q (4 bits)

The module should implement a 4-bit shift register (right shift), with
asynchronous positive edge triggered areset, synchronous active high
signals load, and enable.

  (1) areset: Resets shift register to zero.
  (2) load: Loads shift register with data[3:0] instead of shifting.
  (3) ena: Shift right (q[3] becomes zero, q[0] is shifted out and
       disappears).
  (4) q: The contents of the shift register. If both the load and ena
       inputs are asserted (1), the load input has higher priority.
"""

PROB105 = """
 - input  clk
 - input  load
 - input  ena  (  2 bits)
 - input  data (100 bits)
 - output q    (100 bits)

The module should implement a 100-bit left/right rotator, with
synchronous load and left/right enable. A rotator shifts-in the
shifted-out bit from the other end of the register.

  (1) load: Loads shift register with data[99:0] instead of rotating.
      Synchronous active high.
  (2) ena[1:0]: Synchronous. Chooses whether and which direction to
      rotate:
      (a) 2'b01 rotates right by one bit,
      (b) 2'b10 rotates left by one bit,
      (c) 2'b00 and 2'b11 do not rotate.
"""

PROB115 = """
 - input  clk
 - input  load
 - input  ena
 - input  amount (2 bits)
 - input  data (64 bits)
 - output q (64 bits)

The module should implement a 64-bit arithmetic shift register, with
synchronous load. The shifter can shift both left and right, and by 1 or
8 bit positions, selected by "amount." Assume the right shit is an
arithmetic right shift.

  (1) load: Loads shift register with data[63:0] instead of shifting.
       Active high.
  (2) ena: Chooses whether to shift. Active high.
  (3) amount: Chooses which direction and how much to shift.
      (a) 2'b00: shift left by 1 bit.
      (b) 2'b01: shift left by 8 bits.
      (c) 2'b10: shift right by 1 bit.
      (d) 2'b11: shift right by 8 bits.
"""


def _ok(rtl):
    assert rtl is not None
    assert "module TopModule(" in rtl
    assert "endmodule" in rtl
    return rtl


def test_prob060_plain_serial_shift_fires():
    rtl = _ok(S.synth(PROB060))
    # width-4 register, sync active-low reset, serial-in toward MSB, out = MSB.
    assert "reg [3:0] sr;" in rtl
    assert "if (~resetn)" in rtl
    assert "sr <= {sr[2:0], in};" in rtl
    assert "assign out = sr[3];" in rtl


def test_prob061_single_stage_load_over_enable_fires():
    rtl = _ok(S.synth(PROB061))
    # load (L) before enable (E); priority ladder is load-first.
    i_load = rtl.index("if (L)")
    i_ena = rtl.index("else if (E)")
    assert i_load < i_ena
    assert "Q <= R;" in rtl
    assert "Q <= w;" in rtl


def test_prob084_shift_register_plus_read_mux_fires():
    rtl = _ok(S.synth(PROB084))
    assert "reg [7:0] sr;" in rtl
    assert "if (enable)" in rtl
    assert "sr <= {sr[6:0], S};" in rtl
    # random-access read mux, MSB-first concat A,B,C.
    assert "sr[{A, B, C}]" in rtl


def test_prob085_load_shift_areset_priority_fires():
    rtl = _ok(S.synth(PROB085))
    # async areset in the sensitivity list, areset > load > ena priority.
    assert "posedge clk or posedge areset" in rtl
    i_rst = rtl.index("if (areset)")
    i_load = rtl.index("else if (load)")
    i_ena = rtl.index("else if (ena)")
    assert i_rst < i_load < i_ena
    # right shift, zero shift-in into q[3].
    assert "q <= {1'b0, q[3:1]};" in rtl


def test_prob105_rotator_fires():
    rtl = _ok(S.synth(PROB105))
    assert "if (load)" in rtl
    # rotate right (code 1): LSB wraps to MSB.  rotate left (code 2): MSB wraps to LSB.
    assert "{q[0], q[99:1]}" in rtl
    assert "{q[98:0], q[99]}" in rtl
    assert "ena == 2'd1" in rtl
    assert "ena == 2'd2" in rtl


def test_prob115_arithmetic_barrel_shifter_fires():
    rtl = _ok(S.synth(PROB115))
    assert "case (amount)" in rtl
    # left by 1 / left by 8 (logical zero-fill on the vacated low bits).
    assert "2'b00: q <= {q[62:0], 1'b0};" in rtl
    assert "2'b01: q <= {q[55:0], 8'b0};" in rtl
    # arithmetic right shift: sign-extend with q[63].
    assert "2'b10: q <= {{1{q[63]}}, q[63:1]};" in rtl
    assert "2'b11: q <= {{8{q[63]}}, q[63:8]};" in rtl


def test_all_six_targets_fire():
    for txt in (PROB060, PROB061, PROB084, PROB085, PROB105, PROB115):
        assert S.synth(txt) is not None


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK negatives — each removes exactly one stated fact; MUST skip.
# --------------------------------------------------------------------------- #
NEG_UNSTATED_RESET_POLARITY = """
 - input  clk
 - input  resetn
 - input  in
 - output out
The module should implement a shift register with four D flops, with
synchronous reset.
"""

NEG_UNSTATED_RESET_SYNC = """
 - input  clk
 - input  resetn
 - input  in
 - output out
The module should implement a shift register with four D flops, with
active-low reset.
"""

NEG_AMBIGUOUS_ARITH_VS_LOGICAL = """
 - input  clk
 - input  load
 - input  ena
 - input  amount (2 bits)
 - input  data (64 bits)
 - output q (64 bits)
The module should implement a 64-bit shifter, with synchronous load. The
shifter can shift both left and right, by 1 or 8 bit positions.
  (a) 2'b00: shift left by 1 bit.
  (b) 2'b01: shift left by 8 bits.
  (c) 2'b10: shift right by 1 bit.
  (d) 2'b11: shift right by 8 bits.
"""

NEG_UNSTATED_LOAD_VS_SHIFT_PRIORITY = """
 - input  clk
 - input  areset
 - input  load
 - input  ena
 - input  data (4 bits)
 - output q (4 bits)
The module should implement a 4-bit shift register (right shift), with
asynchronous positive edge triggered areset. Resets shift register to zero.
  load: Loads shift register with data[3:0] instead of shifting.
  ena: Shift right (q[3] becomes zero).
"""

NEG_UNSTATED_SHIFT_IN = """
 - input  clk
 - input  areset
 - input  load
 - input  ena
 - input  data (4 bits)
 - output q (4 bits)
The module should implement a 4-bit shift register (right shift), with
asynchronous positive edge triggered areset. Resets shift register to zero.
  load: Loads shift register with data[3:0] instead of shifting.
  ena: Shift right.
  If both load and ena are asserted, load has higher priority.
"""

NEG_INCOMPLETE_ROTATE_MAP = """
 - input  clk
 - input  load
 - input  ena  (  2 bits)
 - input  data (100 bits)
 - output q    (100 bits)
The module should implement a 100-bit left/right rotator, with synchronous load.
  load: Loads shift register with data[99:0] instead of rotating.
  ena[1:0]: 2'b01 rotates right by one bit, 2'b10 rotates left by one bit.
"""


@pytest.mark.parametrize("name,txt", [
    ("unstated_reset_polarity", NEG_UNSTATED_RESET_POLARITY),
    ("unstated_reset_sync_async", NEG_UNSTATED_RESET_SYNC),
    ("ambiguous_arith_vs_logical", NEG_AMBIGUOUS_ARITH_VS_LOGICAL),
    ("unstated_load_vs_shift_priority", NEG_UNSTATED_LOAD_VS_SHIFT_PRIORITY),
    ("unstated_shift_in_value", NEG_UNSTATED_SHIFT_IN),
    ("incomplete_rotate_direction_map", NEG_INCOMPLETE_ROTATE_MAP),
])
def test_noleak_negatives_must_skip(name, txt):
    assert S.synth(txt) is None, f"§4.05 LEAK: {name} fired but is ambiguous"


def test_non_shift_prompt_skips():
    assert S.synth("Implement a 4-bit binary up counter.") is None
    assert S.synth("") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
