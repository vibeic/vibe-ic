#!/usr/bin/env python3
"""The command-opcode-dispatcher predicate, written ONCE.

`packet_length_check_present` fired an ERROR on `aes_ctrl_reg_shadowed.sv`,
which decodes a two-value `aes_op_e` field with `unique case (op)` over
AES_ENC / AES_DEC. No command, no packet, no length. That was corrected there
in place, by requiring the AMBIGUOUS selector names (`cmd`, `op`) to be
corroborated by a byte-wide opcode literal in the same file.

`dispatcher_awake_gate_check` carried the SAME predicate, UNCORRECTED, and one
round later reached the same wrong conclusion about the same file — MEASURED on
opentitan_aes at plugin v1.15.66:

    [ERROR] NO_AWAKE_SIGNAL: Dispatcher RTL
    (phase2/stage1/rtl/aes_ctrl_reg_shadowed.sv) has a command opcode case but
    references no awake/wake state register

— in a run that declares `command_protocol_applicable=false`, and where eight
sibling gates skip on exactly that fact.

A rule with two copies and no owner gets corrected in one of them. These tests
pin the rule AND that there is now one implementation of it.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _opcode_dispatch_predicate as P  # noqa: E402
import dispatcher_awake_gate_check as D  # noqa: E402
import packet_length_check_present as L  # noqa: E402


# The measured false positive, reduced: an enum decode over a bare `op`.
ENUM_DECODE = """
module aes_ctrl_reg_shadowed;
  typedef enum logic { AES_ENC, AES_DEC } aes_op_e;
  aes_op_e op;
  always_comb begin
    unique case (op)
      AES_ENC: mode = 1'b0;
      AES_DEC: mode = 1'b1;
      default: mode = 1'b0;
    endcase
  end
endmodule
"""

# The same ambiguous selector, CORROBORATED — a real received-command dispatch.
REAL_DISPATCH_AMBIGUOUS = """
module rx;
  always_comb begin
    case (op)
      8'h01: r = 1;
      8'hA5: r = 2;
      default: r = 0;
    endcase
  end
endmodule
"""

# A command-specific selector keeps its standalone force, byte literal or not.
REAL_DISPATCH_UNAMBIGUOUS = """
module rx;
  always_comb begin
    case (cmd_op)
      CMD_PING: r = 1;
      CMD_READ: r = 2;
      default:  r = 0;
    endcase
  end
endmodule
"""

# A processor instruction opcode is not a received packet.  The 7-bit width
# supplies the decisive structural evidence without naming an ISA or design.
INSTRUCTION_OPCODE_DECODE = """
module core(input [31:0] instruction, output reg action);
  wire [6:0] opcode = instruction[6:0];
  always @* begin
    case (opcode)
      OP_LOAD:  action = 1'b1;
      OP_STORE: action = 1'b0;
      default:  action = 1'b0;
    endcase
  end
endmodule
"""

# Symbolic packet opcode arms remain detectable when the selector's declaration
# proves it is byte-wide; a literal in every case arm is not required.
BYTE_WIDE_SYMBOLIC_DISPATCH = """
module rx(input [7:0] opcode, output reg action);
  always @* begin
    case (opcode)
      CMD_PING: action = 1'b1;
      CMD_READ: action = 1'b0;
      default:  action = 1'b0;
    endcase
  end
endmodule
"""

IF_CASCADE = """
module rx;
  always_comb begin
    if (cmd_byte == 8'h01) r = 1;
    if (cmd_byte == 8'h02) r = 2;
    if (cmd_byte == 8'h03) r = 3;
  end
endmodule
"""


def test_an_enum_decode_over_a_bare_op_is_not_a_dispatcher():
    """The measured false positive."""
    assert P.is_opcode_dispatcher(ENUM_DECODE) is False


def test_an_ambiguous_selector_with_a_byte_opcode_literal_is_a_dispatcher():
    """VACUITY CONTROL. Without this the correction would read "never credit
    `op`", and every real dispatcher named that way would go unchecked."""
    assert P.is_opcode_dispatcher(REAL_DISPATCH_AMBIGUOUS) is True


def test_an_unambiguous_selector_keeps_its_standalone_force():
    """REGRESSION CONTROL. Every dispatcher the gates caught before is still
    caught, byte literal or not."""
    assert P.is_opcode_dispatcher(REAL_DISPATCH_UNAMBIGUOUS) is True


def test_a_seven_bit_instruction_opcode_is_not_a_packet_dispatcher():
    """BIDIRECTIONAL CONTROL: FAILS on the pre-fix predicate."""
    assert P.is_opcode_dispatcher(INSTRUCTION_OPCODE_DECODE) is False


def test_an_explicit_byte_wide_opcode_with_symbolic_arms_is_a_dispatcher():
    """Narrowing must not hide a byte packet whose arms use symbols."""
    assert P.is_opcode_dispatcher(BYTE_WIDE_SYMBOLIC_DISPATCH) is True


def test_the_if_cascade_is_still_a_dispatcher():
    assert P.is_opcode_dispatcher(IF_CASCADE) is True


def test_empty_and_non_string_input_are_not_dispatchers():
    assert P.is_opcode_dispatcher("") is False
    assert P.is_opcode_dispatcher(None) is False       # type: ignore[arg-type]


def test_both_gates_ask_the_same_question_of_the_same_text():
    """The point of the module. Two gates over one artefact cannot disagree,
    because there is one rule and they both call it."""
    for text in (ENUM_DECODE, REAL_DISPATCH_AMBIGUOUS,
                 REAL_DISPATCH_UNAMBIGUOUS, INSTRUCTION_OPCODE_DECODE,
                 BYTE_WIDE_SYMBOLIC_DISPATCH, IF_CASCADE):
        assert L._is_dispatcher(text) is P.is_opcode_dispatcher(text)
        assert D._is_opcode_dispatcher(text) is P.is_opcode_dispatcher(text)


def test_the_awake_gate_finds_no_dispatcher_in_an_enum_decode(tmp_path):
    """End to end: the gate no longer demands an awake register of a design
    that has no command protocol."""
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "aes_ctrl_reg_shadowed.sv").write_text(ENUM_DECODE)
    assert D._find_dispatcher(proj) is None


def test_the_awake_gate_still_finds_a_real_dispatcher(tmp_path):
    """DIRECTIONAL CONTROL. Narrowing the selector must not turn this into a
    gate that can no longer find its subject."""
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "rx.sv").write_text(REAL_DISPATCH_AMBIGUOUS)
    found = D._find_dispatcher(proj)
    assert found is not None and found.name == "rx.sv"
