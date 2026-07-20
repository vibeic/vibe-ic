"""lfsr_synth — deterministic SOLVER for the Galois LFSR family.

POSITIVES: the two VerilogEval-Human Galois LFSRs (Prob082 lfsr32 taps 32/22/2/1,
Prob086 lfsr5 taps 5/3) FIRE and emit the canonical Galois-right next-state +
active-high synchronous reset. When iverilog + the real dataset are present, the
emitted RTL is ALSO host-scored against the official ref + testbench (0 mismatches).

§4.05 NO-LEAK (the load-bearing half): the solver MUST return None on ANY ambiguity.
The negative fixtures sit JUST OUTSIDE the intended boundary — a complete Galois
LFSR with exactly ONE fact mutated (taps removed / form unstated / shift-left /
reset async / reset active-low / reset unstated / tap out of range / width mismatch)
— and assert the solver STILL skips. A wrong-but-confident LFSR is far worse than a
skip, so each boundary mutation that breaks determinism must yield None.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parents[1]    # programs/ (the solver dir)
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import lfsr_synth as L  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

# --------------------------------------------------------------------------- #
# Canonical inline fixtures — faithful transcriptions of the REAL VE-Human
# Galois LFSR prompts (Prob082 / Prob086), so the no-leak boundary tests run
# self-contained (no dataset dependency). The host-score test below uses the
# real on-disk prompt+ref+testbench when available.
# --------------------------------------------------------------------------- #
_HDR = (
    "I would like you to implement a module named TopModule with the following\n"
    "interface. All input and output ports are one bit unless otherwise\n"
    "specified.\n\n"
)

# Prob082 lfsr32 — taps at positions 32, 22, 2, 1 (note the "bit\npositions" wrap).
LFSR32 = _HDR + (
    " - input  clk\n - input  reset\n - output q (32 bits)\n\n"
    "A linear feedback shift register is a shift register usually with a few\n"
    "XOR gates to produce the next state of the shift register. A Galois LFSR\n"
    "is one particular arrangement that shifts right, where a bit position with\n"
    'a "tap" is XORed with the LSB output bit (q[0]) to produce its next value,\n'
    "while bit positions without a tap shift right unchanged.\n\n"
    "The module should implement a 32-bit Galois LFSR with taps at bit\n"
    "positions 32, 22, 2, and 1. Reset should be active high synchronous, and\n"
    "should reset the output q to 32'h1. Assume all sequential logic is\n"
    "triggered on the positive edge of the clock.\n"
)

# Prob086 lfsr5 — taps at positions 5, 3 (note the "taps\nat bit positions" wrap,
# plus an explanatory "If the taps positions are carefully chosen ..." DECOY that
# the tap parser must NOT mistake for the real numeric tap list).
LFSR5 = _HDR + (
    " - input  clk\n - input  reset\n - output q (5 bits)\n\n"
    "A linear feedback shift register is a shift register usually with a few\n"
    "XOR gates to produce the next state of the shift register. A Galois LFSR\n"
    "is one particular arrangement that shifts right, where a bit position with\n"
    'a "tap" is XORed with the LSB output bit (q[0]) to produce its next value,\n'
    "while bit positions without a tap shift right unchanged.  If the taps positions\n"
    "are carefully chosen, the LFSR can be made to be \"maximum-length\". A maximum-length\n"
    "LFSR of n bits cycles through 2**n-1 states before repeating (the all-zero state is\n"
    "never reached).\n\n"
    "The module should implement a 5-bit maximal-length Galois LFSR with taps\n"
    "at bit positions 5 and 3. The active-high synchronous reset should reset\n"
    "the LFSR output to 1. Assume all sequential logic is triggered on the\n"
    "positive edge of the clock.\n"
)

_RST5 = "The active-high synchronous reset should reset\nthe LFSR output to 1."


# --------------------------------------------------------------------------- #
# POSITIVES — both Galois LFSRs fire and emit the canonical next-state.
# --------------------------------------------------------------------------- #
def test_pos_lfsr32_fires_canonical():
    rtl = L.synth(LFSR32)
    assert rtl is not None
    # 32-bit q bus + active-high synchronous reset to 32'h1
    assert "output reg [31:0] q" in rtl
    assert "if (reset)" in rtl
    assert "q <= 32'h1;" in rtl
    # Galois shift-right: MSB <- q[0] via the concat, XOR q[0] into NON-top taps
    # (positions 22/2/1 -> indices 21/1/0; position 32 is the MSB fill, no XOR term).
    assert "q_next = {q[0], q[31:1]};" in rtl
    assert "q_next[21] = q_next[21] ^ q[0];" in rtl
    assert "q_next[1] = q_next[1] ^ q[0];" in rtl
    assert "q_next[0] = q_next[0] ^ q[0];" in rtl
    # the MSB index must NOT get a separate XOR term (it is the shift-in fill)
    assert "q_next[31] = q_next[31] ^ q[0];" not in rtl
    assert "q <= q_next;" in rtl


def test_pos_lfsr5_fires_canonical():
    rtl = L.synth(LFSR5)
    assert rtl is not None
    assert "output reg [4:0] q" in rtl
    assert "q <= 5'h1;" in rtl
    assert "q_next = {q[0], q[4:1]};" in rtl
    # taps 5/3 -> index 4 is the MSB fill (no XOR), index 2 gets the XOR term.
    assert "q_next[2] = q_next[2] ^ q[0];" in rtl
    assert "q_next[4] = q_next[4] ^ q[0];" not in rtl


def test_pos_custom_top_name():
    rtl = L.synth(LFSR5, top="lfsr5")
    assert rtl is not None and rtl.startswith("module lfsr5 (")


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK — JUST-OUTSIDE-the-boundary negatives MUST return None.
# --------------------------------------------------------------------------- #
def test_neg_ambiguous_taps():
    # taps mentioned but NO numeric position list -> cannot place XOR terms -> SKIP
    bad = LFSR5.replace("taps\nat bit positions 5 and 3", "a carefully chosen set of taps")
    assert "taps" in bad and "positions 5 and 3" not in bad
    assert L.synth(bad) is None


def test_neg_unstated_form_no_galois():
    # arrangement not stated as Galois -> next-state function unknown -> SKIP
    bad = (LFSR5.replace("A Galois LFSR", "An LFSR")
                .replace("maximal-length Galois LFSR", "maximal-length LFSR"))
    assert "Galois" not in bad
    assert L.synth(bad) is None


def test_neg_shift_left_fibonacci():
    # a non-Galois / shift-LEFT / Fibonacci form has a DIFFERENT next state -> SKIP
    bad = (LFSR32.replace("shifts right", "shifts left")
                 .replace("32-bit Galois LFSR", "32-bit Fibonacci LFSR that shifts left"))
    assert L.synth(bad) is None


def test_neg_unstated_reset():
    # reset form + seed not stated -> SKIP (do not invent a reset)
    bad = LFSR5.replace(_RST5, "The reset behavior is left unspecified.")
    assert _RST5 not in bad
    assert L.synth(bad) is None


def test_neg_async_reset():
    # reset stated but ASYNCHRONOUS (this solver only emits synchronous) -> SKIP
    bad = LFSR5.replace(
        _RST5, "The active-high asynchronous reset should reset the LFSR output to 1.")
    assert L.synth(bad) is None


def test_neg_active_low_reset():
    # reset stated but ACTIVE-LOW (contradicts the emitted active-high) -> SKIP
    bad = LFSR5.replace(
        _RST5, "The active-low synchronous reset should reset the LFSR output to 1.")
    assert L.synth(bad) is None


def test_neg_tap_out_of_range():
    # a tap position beyond the register width is not a valid index -> SKIP
    bad = LFSR32.replace("positions 32, 22, 2, and 1", "positions 99, 22, 2, and 1")
    assert L.synth(bad) is None


def test_neg_width_mismatch():
    # stated width disagrees with the parsed output-bus width -> SKIP
    bad = LFSR32.replace("32-bit Galois LFSR", "16-bit Galois LFSR")
    assert L.synth(bad) is None


def test_neg_no_lfsr_at_all():
    # an ordinary (non-LFSR) shift register has no feedback taps -> SKIP
    sr = _HDR + (
        " - input  clk\n - input  reset\n - output q (8 bits)\n\n"
        "Implement an 8-bit shift register that shifts right by one bit each\n"
        "clock. Active-high synchronous reset clears q to 0.\n")
    assert L.synth(sr) is None


# --------------------------------------------------------------------------- #
# HOST-SCORE — when iverilog + the real dataset exist, the emitted RTL must
# simulate against the OFFICIAL ref + testbench with ZERO mismatches.
# --------------------------------------------------------------------------- #
_DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")


@pytest.mark.parametrize("prob", ["Prob082_lfsr32", "Prob086_lfsr5"])
def test_host_score_zero_mismatch(prob):
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.skip("iverilog/vvp not available")
    prompt = _DS / f"{prob}_prompt.txt"
    ref = _DS / f"{prob}_ref.sv"
    test = _DS / f"{prob}_test.sv"
    if not (prompt.exists() and ref.exists() and test.exists()):
        pytest.skip(f"dataset for {prob} not present")
    rtl = L.synth(prompt.read_text(errors="replace"))
    assert rtl is not None, f"solver SKIPped a real firing problem: {prob}"
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        dut.write_text(rtl)
        vvp = Path(d) / "a.vvp"
        comp = subprocess.run(
            ["iverilog", "-g2012", "-o", str(vvp), str(dut), str(ref), str(test)],
            capture_output=True, text=True)
        assert comp.returncode == 0, f"compile failed:\n{comp.stderr}"
        run = subprocess.run(["vvp", str(vvp)], capture_output=True, text=True)
        out = run.stdout + run.stderr
        assert "Total mismatched samples is 0 out of" in out, \
            f"host-score had mismatches for {prob}:\n{out}"
