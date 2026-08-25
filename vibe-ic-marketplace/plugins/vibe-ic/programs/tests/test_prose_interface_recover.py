#!/usr/bin/env python3
r"""Tests for prose_interface_recover — the RTLLM header DIALECTS the base
`prose_port_block_read` returns ([],[]) on.

Every positive arm asserts the CONTRAST that is the whole reason this module
exists: the base reader finds nothing, the recoverer finds the interface. An
arm that only asserted the recovered ports would stay green if the base reader
grew to read the dialect and this module were deleted.

Pinned behaviours:
  * dialect (1) bare `Inputs:` / `Outputs:` section headers;
  * dialect (2) PAREN-DIRECTION lines `name (input [31:0]): desc`, whose own
    keyword fixes the direction regardless of the enclosing section;
  * dialect (3) PARAMETER-EXPRESSION widths recovered as width=None — PRESENT
    but unknown, never a guessed integer (§4.05: a parameterized port must not
    be frozen to a literal);
  * an AMBIGUOUS width DROPS that port rather than guessing;
  * a following labelled section ENDS the port block, so prose below it is not
    read as ports;
  * `inout` is not modelled and is dropped.
"""
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import prose_interface_recover as R      # noqa: E402
import prose_port_block_read as BASE     # noqa: E402


BARE_SECTIONS = """Implement a traffic light controller.

Inputs:
    clk: 1-bit clock signal.
    rst_n: active-low reset, one bit.
    pass_request [3:0]: 4-bit request bus.
Outputs:
    clock: one bit output.
    red: single-bit red lamp.
    count [7:0]: 8-bit countdown.

Implementation:
    The FSM cycles through the lamp states. green_time is 60 cycles.
    yellow_time is 5 cycles. red_time is 10 cycles.
"""

PAREN_DIRECTION = """Implement a floating point multiplier.

a (input [31:0]): the first operand.
b (input [31:0]): the second operand.
result (output reg [31:0]): the product.
enable (input): one bit enable.
bus (inout [7:0]): a bidirectional line.
"""

PARAM_WIDTHS = """Implement a fixed point adder.

Input ports:
    a [N-1:0]: first operand.
    b [WIDTH-1:0]: second operand.
Output ports:
    c [Q-1:0]: the sum.
"""

AMBIGUOUS = """Implement something with a badly stated interface.

Inputs:
    contradictory: this is a 8-bit port and also a 16-bit port.
    unclassifiable [oops]: a bracket that is neither a range nor a parameter.
    ok: one bit.
Outputs:
    z: one bit.
"""


def _base_is_blind(text):
    assert BASE.parse_rtllm_ports(text) == ([], []), (
        "the BASE reader now reads this dialect — this fixture no longer shows "
        "what prose_interface_recover recovers")


def test_bare_input_output_section_headers_are_recovered():
    _base_is_blind(BARE_SECTIONS)
    ins, outs = R.recover_ports(BARE_SECTIONS)
    assert ins == [("clk", 1), ("rst_n", 1), ("pass_request", 4)]
    assert outs == [("clock", 1), ("red", 1), ("count", 8)]


def test_a_following_labelled_section_ends_the_port_block():
    """`Implementation:` closes the Outputs block; the prose under it names
    green_time / yellow_time / red_time in `word: value` shape and NONE of them
    may be recovered as a port."""
    ins, outs = R.recover_ports(BARE_SECTIONS)
    names = {n for n, _w in ins + outs}
    assert names.isdisjoint({"green_time", "yellow_time", "red_time",
                             "Implementation"})


def test_paren_direction_lines_carry_their_own_direction():
    _base_is_blind(PAREN_DIRECTION)
    ins, outs = R.recover_ports(PAREN_DIRECTION)
    # no section header at all — every direction came from the parenthetical.
    assert ins == [("a", 32), ("b", 32), ("enable", 1)]
    assert outs == [("result", 32)]


def test_inout_is_dropped_rather_than_guessed_into_a_direction():
    ins, outs = R.recover_ports(PAREN_DIRECTION)
    assert "bus" not in {n for n, _w in ins + outs}


def test_parameter_expression_width_is_present_but_unknown():
    """§4.05: the port EXISTS (presence + direction are enforceable) and its
    width is None. A guessed integer here would false-reject a legal design."""
    _base_is_blind(PARAM_WIDTHS)
    ins, outs = R.recover_ports(PARAM_WIDTHS)
    assert ins == [("a", None), ("b", None)]
    assert outs == [("c", None)]


@pytest.mark.parametrize("dropped", ["contradictory", "unclassifiable"])
def test_an_ambiguous_width_drops_the_port(dropped):
    ins, outs = R.recover_ports(AMBIGUOUS)
    assert dropped not in {n for n, _w in ins + outs}


def test_the_unambiguous_ports_of_a_partly_ambiguous_block_survive():
    ins, outs = R.recover_ports(AMBIGUOUS)
    assert ins == [("ok", 1)]
    assert outs == [("z", 1)]


def test_an_integer_range_wins_over_a_width_word_in_the_description():
    """The `[hi:lo]` range is the declaration's own width; a description that
    mentions the OPERAND widths is prose, not a contradiction."""
    text = ("Output ports:\n"
            "    prod [15:0]: 16-bit product of two 8-bit inputs.\n")
    _ins, outs = R.recover_ports(text)
    assert outs == [("prod", 16)]


def test_prose_with_no_port_block_recovers_nothing():
    assert R.recover_ports("Just a paragraph about a design.\n") == ([], [])
