#!/usr/bin/env python3
"""test_v1_1_76_residual_combinational.py — residual_combinational_synth.

Covers the three deterministic residual sub-shapes (constant output / explicit
Boolean equation / equality comparator) with:
  * POSITIVES that reproduce the REAL VerilogEval spec-to-rtl prompts and assert
    the emitted RTL is the correct, host-verifiable circuit.
  * >=5 §4.05 NEGATIVE no-leak fixtures that MUST return None.

The authoritative correctness gate is host-scoring (iverilog -g2012 dut.sv
ref.sv test.sv && vvp -> 0 mismatches); those runs are reproduced in the field
sweep and summarised in the PR. These pytest cases pin the deterministic
shape/text-pattern contract and the conservative §4.05 envelope.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROG = os.path.dirname(_HERE)
if _PROG not in sys.path:
    sys.path.insert(0, _PROG)

import residual_combinational_synth as M  # noqa: E402


# --------------------------------------------------------------------------- #
# Real VerilogEval prompt bodies (verbatim behaviour text).
# --------------------------------------------------------------------------- #
P_ZERO = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise specified.

 - output zero

The module should always outputs a LOW.
"""

P_ONE = """
I would like you to implement a module named TopModule.

 - output one

The module should always drive 1 (or logic high).
"""

P_OUT0 = """
I would like you to implement a module named TopModule.

 - output out

The module should always drive 0 (or logic low).
"""

P_BOOL = """
I would like you to implement a module named TopModule.

 - input  x
 - input  y
 - output z

The module should implement the boolean function z = (x^y) & x.
"""

P_EQ = """
I would like you to implement a module named TopModule.

 - input  A (2 bits)
 - input  B (2 bits)
 - output z

The module should implement a circuit that has two 2-bit inputs A[1:0]
and B[1:0], and produces an output z. The value of z should be 1 if A =
B, otherwise z should be 0.
"""


# --------------------------------------------------------------------------- #
# POSITIVES
# --------------------------------------------------------------------------- #
def _norm(s):
    return " ".join(s.split())


def test_constant_low_zero():
    rtl = M.synth(P_ZERO, "TopModule")
    assert rtl is not None
    assert "module TopModule" in rtl
    assert "output zero" in rtl
    assert "assign zero = 1'b0;" in _norm(rtl)


def test_constant_high_one():
    rtl = M.synth(P_ONE, "TopModule")
    assert rtl is not None
    assert "assign one = 1'b1;" in _norm(rtl)
    # no inputs on a constant
    assert "input" not in rtl


def test_constant_low_out():
    rtl = M.synth(P_OUT0, "TopModule")
    assert rtl is not None
    assert "assign out = 1'b0;" in _norm(rtl)


def test_boolean_equation_now_owned_by_comb_gate():
    # v1.1.76 integration: a literal Boolean equation is owned by comb_gate_synth
    # (the dedicated gate/boolean family). residual deliberately SKIPs every
    # boolean-equation prompt now, so exactly ONE solver fires on the real Prob010
    # (the registry mutual-exclusion test pins that comb_gate is the one). Here we
    # only assert the residual SKIP — comb_gate's emit is verified end-to-end on
    # the real dataset prompt, not on this synthetic fixture.
    assert M.synth(P_BOOL, "TopModule") is None


def test_equality_comparator_2bit():
    rtl = M.synth(P_EQ, "TopModule")
    assert rtl is not None
    n = _norm(rtl)
    assert "input [1:0] A" in n and "input [1:0] B" in n
    assert "assign z = (A == B);" in n


def test_top_name_is_honored():
    rtl = M.synth(P_ZERO, "MyTop")
    assert rtl is not None and "module MyTop (" in rtl


def test_at_most_one_subshape_fires():
    # signatures are mutually exclusive — a constant prompt must NOT also be
    # read as an equation/comparator, etc. Each positive yields exactly one
    # 'assign'.
    for txt in (P_ZERO, P_ONE, P_OUT0, P_EQ):   # P_BOOL now owned by comb_gate
        rtl = M.synth(txt, "TopModule")
        assert rtl is not None
        assert rtl.count("assign ") == 1


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVE NO-LEAK FIXTURES — every one MUST return None.
# --------------------------------------------------------------------------- #
NEG_SEQUENTIAL = """
 - input  clk
 - input  d
 - output q

Implement a D flip-flop: on every positive clock edge q should capture d.
"""

NEG_EQUATION_UNDECLARED_TOKEN = """
 - input  x
 - input  y
 - output z

The module should implement the boolean function z = (x ^ w) & y.
"""
# 'w' is NOT a declared input -> ambiguous -> SKIP.

NEG_EQUATION_NONLINEAR_OP = """
 - input  a (4 bits)
 - input  b (4 bits)
 - output s (4 bits)

The module should implement the boolean function s = a + b.
"""
# '+' is arithmetic, outside the bitwise grammar; also output is wide -> SKIP.

NEG_NAMED_GATE_PROSE_ONLY = """
 - input  a
 - input  b
 - output out

The module should implement a 2-input NAND gate.
"""
# no explicit equation, no constant, no equality -> AI floor -> SKIP.

NEG_INEQUALITY = """
 - input  A (2 bits)
 - input  B (2 bits)
 - output z

The value of z should be 1 if A is not equal to B, otherwise z should be 0.
"""
# negated comparator -> we only emit the ==, so SKIP rather than emit wrong.

NEG_CONSTANT_AMBIGUOUS = """
 - output out

The module drives a value depending on the configuration register.
"""
# 'register' (sequential/struct) + no clean constant prose -> SKIP.

NEG_COMPARATOR_THREE_INPUTS = """
 - input  A (2 bits)
 - input  B (2 bits)
 - input  C (2 bits)
 - output z

The value of z should be 1 if A = B, otherwise z should be 0.
"""
# 3 inputs — does not match the exact 2-input equality signature -> SKIP.

NEG_CONSTANT_WIDE_OUTPUT = """
 - output out (8 bits)

The module should always drive 0.
"""
# wide output is not a clean 1-bit constant in this sub-shape -> SKIP.

NEG_EMPTY = "   \n  "


@pytest.mark.parametrize("txt", [
    NEG_SEQUENTIAL,
    NEG_EQUATION_UNDECLARED_TOKEN,
    NEG_EQUATION_NONLINEAR_OP,
    NEG_NAMED_GATE_PROSE_ONLY,
    NEG_INEQUALITY,
    NEG_CONSTANT_AMBIGUOUS,
    NEG_COMPARATOR_THREE_INPUTS,
    NEG_CONSTANT_WIDE_OUTPUT,
    NEG_EMPTY,
])
def test_no_leak_negatives_return_none(txt):
    assert M.synth(txt, "TopModule") is None


def test_equation_lhs_must_be_the_output():
    # equation drives 'q', but the declared output is 'z' -> SKIP (no mis-wire).
    txt = """
 - input  x
 - input  y
 - output z

The module should implement the boolean function q = x ^ y.
"""
    assert M.synth(txt, "TopModule") is None


def test_inequality_keyword_blocks_even_with_equals_match():
    # The phrase contains 'A = B ... otherwise ... 0' AND 'not equal' -> the
    # inequality guard must win and SKIP.
    txt = """
 - input  A (2 bits)
 - input  B (2 bits)
 - output z

z is 1 if A = B but the requirement is they must not be equal; otherwise 0.
"""
    assert M.synth(txt, "TopModule") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
