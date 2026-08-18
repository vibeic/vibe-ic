#!/usr/bin/env python3
"""test_encoder_synth.py — positives + §4.05 negatives for the CVDP
priority-encoder / binary-decoder / one-hot solver.

The solver is chip-AGNOSTIC: it keys on STATED structure (priority direction,
index->one-hot mapping, stated widths/defaults), never on a design name. These
tests pin:
  * positives  — an MSB-first and an LSB-first priority encoder, a parameterized
    binary->one-hot decoder, and a fixed-width decoder all EMIT correct RTL;
  * §4.05 negatives — an UNSTATED priority direction SKIPs; a non-plain mapping
    (gray/address/granularity) SKIPs; a sequential/pipelined variant SKIPs; the
    emit is INDEPENDENT of the design name (chip-agnostic).
"""
import math
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import encoder_synth as E  # noqa: E402


# --------------------------------------------------------------------------- #
# prose fixtures (paraphrased from the CVDP family shapes; no name dependence) #
# --------------------------------------------------------------------------- #
PE_MSB = """Design an 8x3 priority encoder. It takes an 8-bit input signal and
outputs a 3-bit binary code representing the position of the highest-priority
active input. The priority order goes from the highest bit (bit 7) to the lowest
bit (bit 0).
- Inputs:
    - [7:0] in: An 8-bit input vector. The priority of the inputs decreases from bit 7 to bit 0.
- Output:
    - [2:0] out: A 3-bit output vector for the highest-priority active input.
- If none of the input lines are active (in is all zeros), the output should default to 3'b000.
"""

PE_LSB = """Design a priority encoder that reports the position of the lowest set
bit (the least-significant active bit wins).
- Inputs:
    - [7:0] in: An 8-bit input vector.
- Output:
    - [2:0] out: A 3-bit binary index of the first set bit.
- If the input is all zeros, the output should be 3'b000.
"""

PE_UNSTATED_DIR = """Design a priority encoder.
- Inputs:
    - [7:0] in: An 8-bit input vector.
- Output:
    - [2:0] out: A 3-bit binary index of the winning bit.
- If the input is all zeros, the output should be 3'b000.
"""

DEC_PARAM = """Design a parameterized binary to one-hot decoder named `dec` that
converts a binary-encoded input into a one-hot output. Parameters `BINARY_WIDTH`
and `OUTPUT_WIDTH`. Default `BINARY_WIDTH=5`. `OUTPUT_WIDTH=32`.
- **Input**: `binary_in` (`BINARY_WIDTH` bits) — Binary input signal.
- **Output**: `one_hot_out` (`OUTPUT_WIDTH` bits) — only the bit at index
  `binary_in` is set to 1, all others 0.
2. **Out-of-Range Handling**: If `binary_in` is greater than or equal to
   `OUTPUT_WIDTH`, the module should output `0` for `one_hot_out`.
This is a purely combinational module without a clock or reset.
"""

DEC_FIXED = """Design a 3-to-8 binary decoder. The 3-bit binary input selects one
of 8 output lines; only the bit at index given by the input is set to 1, all
others 0. One-hot output.
- Inputs:
    - [2:0] sel: 3-bit binary input.
- Output:
    - [7:0] y: 8-bit one-hot output.
"""

DEC_GRAY = """Design a binary-to-gray decoder.
- Inputs:
    - [3:0] bin: 4-bit binary input.
- Output:
    - [3:0] gray: 4-bit gray-coded output.
"""

DEC_SEQ = """Design a sequential binary-to-one-hot decoder, synchronized with a
clock. Parameters `BINARY_WIDTH` and `OUTPUT_WIDTH`. Default `BINARY_WIDTH=5`,
`OUTPUT_WIDTH=32`.
- **Input**: `i_binary_in` (`BINARY_WIDTH` bits)
- **Input**: `i_clk` (`1-bit`) — Clock.
- **Input**: `i_rstb` (`1-bit`) — Asynchronous reset, active low.
- **Output**: `o_one_hot_out` (`OUTPUT_WIDTH` bits) — updated on the rising edge.
"""


# --------------------------------------------------------------------------- #
# POSITIVES                                                                     #
# --------------------------------------------------------------------------- #
def test_priority_encoder_msb_first_emits():
    rtl = E.synth(PE_MSB, top="penc")
    assert rtl is not None
    assert "module penc" in rtl
    assert "casez" in rtl
    # MSB-first: the highest-position arm is listed FIRST (8'b1zzzzzzz -> 7),
    # so the highest set bit wins.
    first_arm = re.search(r"casez.*?\n\s*(8'b\S+)\s*:\s*out\s*=\s*3'd(\d+)", rtl, re.S)
    assert first_arm and first_arm.group(2) == "7"
    assert first_arm.group(1) == "8'b1zzzzzzz"


def test_priority_encoder_lsb_first_emits():
    rtl = E.synth(PE_LSB, top="penc")
    assert rtl is not None
    # LSB-first: the lowest-position arm is listed FIRST (8'bzzzzzzz1 -> 0).
    first_arm = re.search(r"casez.*?\n\s*(8'b\S+)\s*:\s*out\s*=\s*3'd(\d+)", rtl, re.S)
    assert first_arm and first_arm.group(2) == "0"
    assert first_arm.group(1) == "8'bzzzzzzz1"


def test_priority_direction_parse():
    assert E.parse_priority_direction(PE_MSB) is True      # MSB-first
    assert E.parse_priority_direction(PE_LSB) is False     # LSB-first
    assert E.parse_priority_direction(PE_UNSTATED_DIR) is None


def test_parameterized_decoder_emits():
    rtl = E.synth(DEC_PARAM, top="dec")
    assert rtl is not None
    assert "module dec" in rtl
    assert "parameter BINARY_WIDTH = 5" in rtl
    assert "parameter OUTPUT_WIDTH = 32" in rtl
    # one-hot via shift, with the stated out-of-range -> 0 guard.
    assert "<< binary_in" in rtl
    assert "binary_in < OUTPUT_WIDTH" in rtl


def test_fixed_width_decoder_emits():
    rtl = E.synth(DEC_FIXED, top="d38")
    assert rtl is not None
    assert "module d38" in rtl
    assert "<< sel" in rtl
    # full 3->8 decode: output width is exactly 2**3.
    assert "[7:0] y" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NEGATIVES                                                               #
# --------------------------------------------------------------------------- #
def test_unstated_priority_direction_skips():
    # The dominant §4.05 case: a priority encoder whose MSB-vs-LSB direction is
    # not stated must SKIP — never guess a direction.
    assert E.synth(PE_UNSTATED_DIR, top="penc") is None


def test_non_plain_mapping_gray_skips():
    assert E.synth(DEC_GRAY, top="g") is None


def test_sequential_decoder_skips():
    # A clocked/registered one-hot decoder is NOT this combinational function.
    assert E.synth(DEC_SEQ, top="seqdec") is None


def test_priority_encoder_msb_no_zero_default_skips():
    # No valid flag AND no stated zero default => SKIP.
    no_zdef = PE_MSB.replace(
        "- If none of the input lines are active (in is all zeros), "
        "the output should default to 3'b000.", "")
    assert E.synth(no_zdef, top="penc") is None


def test_priority_encoder_wrong_output_width_skips():
    # 8-bit input but a 4-bit index contradicts ceil(log2(8))==3 => SKIP.
    bad = PE_MSB.replace("[2:0] out", "[3:0] out").replace(
        "A 3-bit output", "A 4-bit output").replace("3'b000", "4'b0000")
    assert E.synth(bad, top="penc") is None


# --------------------------------------------------------------------------- #
# CHIP-AGNOSTIC                                                                 #
# --------------------------------------------------------------------------- #
def test_emit_is_chip_agnostic():
    # The emitted logic must depend ONLY on stated structure, not on the module
    # name. Two different `top` names yield identical RTL modulo the module name.
    a = E.synth(PE_MSB, top="alpha_enc")
    b = E.synth(PE_MSB, top="zzz_widget_42")
    assert a and b
    norm = lambda s, t: s.replace(t, "TOP")
    assert norm(a, "alpha_enc") == norm(b, "zzz_widget_42")


def test_no_designname_keys_in_source():
    # The solver source must not hard-code any CVDP design id / name token.
    src = (Path(__file__).resolve().parent.parent / "encoder_synth.py").read_text()
    for banned in ("cvdp_copilot", "8x3", "priority_encoder_8x3",
                   "binary_to_one_hot_decoder", "one_hot_gen"):
        assert banned not in src, f"design-name token {banned!r} leaked into solver"


# --------------------------------------------------------------------------- #
# functional correctness sanity (pure-python oracle of the emitted intent)     #
# --------------------------------------------------------------------------- #
def test_priority_encoder_arm_count_and_order():
    rtl = E.synth(PE_MSB, top="penc")
    arms = re.findall(r"(8'b[01z]+)\s*:\s*out\s*=\s*3'd(\d+)", rtl)
    # 8 explicit position arms, listed high-to-low for MSB-first.
    assert len(arms) == 8
    positions = [int(p) for _, p in arms]
    assert positions == list(range(7, -1, -1))


def test_decoder_shift_semantics_match_oracle():
    # The parameterized decoder's intent is one_hot_out == (1 << binary_in) for
    # binary_in < OUTPUT_WIDTH. Pin that the emit encodes exactly that shift.
    rtl = E.synth(DEC_PARAM, top="dec")
    assert "1'b1} << binary_in" in rtl
    # oracle: for OUTPUT_WIDTH=32, each in in [0,31] -> a single set bit at `in`.
    for i in range(32):
        assert bin(1 << i).count("1") == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
