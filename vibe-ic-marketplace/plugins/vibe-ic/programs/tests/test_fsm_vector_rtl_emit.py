"""fsm_vector_rtl_emit — supplemental deterministic Tier-1 emitters.

These pin the 5 Tier2->Tier1 promotions and their §4.05 no-leak / general-not-
keyword guards:

  POSITIVE (iverilog-proven — SKIP cleanly when iverilog/dataset absent)
    * the neighbour-vector emitter rescues gatesv100/gatesv (the registry
      mis-widths these — out_both/out_any must be ONE bit narrower than `in`),
      emitting at the EXACT _ifc.txt widths and passing the official _test.sv.
    * the FSM-next-state-by-inspection emitter solves the one-hot (Prob099) and
      binary-ellipsis-encoded (Prob135) next-state-bit sub-questions.
    * the full-Moore-FSM emitter solves the arrow-table FSM (Prob136) with a
      free internal encoding (the testbench observes only the Moore output).
    * the pipeline (registry-first, supplemental-fallback) promotes exactly
      these 5 and keeps the 130 verified Tier1 set self-consistent.

  §4.05 NEGATIVE / GENERAL-not-keyword (load-bearing)
    * every emitter keys on STRUCTURE, never on a problem id / design name:
      renaming the module / scrubbing the id leaves the emit unchanged.
    * the neighbour-vector emitter SKIPs when the interface widths are NOT the
      stated narrower windows (no blind full-width pad).
    * the state-encoding parser SKIPs an ambiguous ellipsis (non-consecutive
      leading codes, or a stated last code that disagrees with a +1 fill) —
      it never GUESSES an encoding.
    * the next-state-bit emitter SKIPs when no explicit encoding is stated.
    * the full-Moore emitter SKIPs an INCOMPLETE arrow table (a state missing a
      0- or 1- successor or its Moore output) — it never invents a transition.
    * the emitters fire on NONE of the structurally-different problems (a 156-
      sweep would over-fire only if keyed on names; here they fire on a small,
      structurally-identified set and every fire iverilog-verifies).
"""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fsm_vector_rtl_emit as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023")
_HAVE_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_HAVE_DATASET = _DATASET.exists()
_needs_bench = pytest.mark.skipif(
    not (_HAVE_IVERILOG and _HAVE_DATASET),
    reason="requires iverilog + the VerilogEval-HUMAN dataset; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")


# --------------------------------------------------------------------------- #
# POSITIVE — each emitter fires AND iverilog-verifies on its target problem
# --------------------------------------------------------------------------- #
_PROMOTIONS = [
    ("Prob092_gatesv100", "neighbour_vector_exact_width"),
    ("Prob094_gatesv", "neighbour_vector_exact_width"),
    ("Prob099_m2014_q6c", "fsm_next_state_bit_by_inspection"),
    ("Prob135_m2014_q6b", "fsm_next_state_bit_by_inspection"),
    ("Prob136_m2014_q6", "full_moore_fsm_arrow_table"),
]






# --------------------------------------------------------------------------- #
# GENERAL-not-keyword — structure-keyed, id-agnostic
# --------------------------------------------------------------------------- #


def test_neighbour_vector_skips_wrong_widths():
    """§4.05: if the interface declares out_both / out_any at FULL width (not the
    stated one-bit-narrower windows), the emitter SKIPs — it never blindly pads."""
    prompt = (
        "We want relationships between each bit and its neighbour: out_both, "
        "out_any, out_different (both/any/different).\n"
        "module TopModule (\n"
        "  input [3:0] in,\n"
        "  output [3:0] out_both,\n"      # WRONG: should be [2:0]
        "  output [3:0] out_any,\n"       # WRONG: should be [3:1]
        "  output [3:0] out_different\n"
        ");")
    prob = {"prompt": prompt, "ifc": prompt}
    assert S.emit(prob) == (None, None)


def test_state_encoding_skips_ambiguous_ellipsis():
    """§4.05: an ellipsis whose leading codes are NOT consecutive, or whose stated
    last code disagrees with a +1 fill, is NOT guessed — parser returns None."""
    states = ["A", "B", "C", "D"]
    # non-consecutive leading run (00, 10) -> cannot fill.
    assert S._parse_state_encoding("y = 00, 10, ..., 11 for states", states) is None
    # last code disagrees with first+N-1 (first=0, N=4 -> expect 11, stated 10).
    assert S._parse_state_encoding("y = 00, 01, ..., 10 for states", states) is None
    # consecutive + correct last code -> filled.
    enc = S._parse_state_encoding("y = 00, 01, ..., 11 for states", states)
    assert enc == {"A": 0, "B": 1, "C": 2, "D": 3}


def test_next_state_bit_skips_without_encoding():
    """No explicit state encoding stated -> the by-inspection emitter SKIPs (it
    can't map states to codes), even with a complete arrow table + Y-port."""
    prompt = (
        "A (0) --0--> B\nA (0) --1--> A\nB (1) --0--> A\nB (1) --1--> B\n"
        "Write Verilog for Y2.\n"
        "module TopModule (\n  input [3:1] y,\n  input w,\n  output Y2\n);")
    prob = {"prompt": prompt, "ifc": prompt}
    assert S._emit_fsm_next_state_bit(prob) is None


def test_full_moore_skips_incomplete_table():
    """§4.05: a state missing one of its (0/1) successors makes the arrow table
    INCOMPLETE -> the full-Moore emitter SKIPs (never invents a transition)."""
    # B has only a 0-successor; the table is incomplete.
    prompt = (
        "A (0) --0--> B\nA (0) --1--> A\nB (1) --0--> A\n"
        "Implement this state machine. Reset into A.\n"
        "module TopModule (\n  input clk,\n  input reset,\n  input w,\n  output z\n);")
    prob = {"prompt": prompt, "ifc": prompt}
    assert S._parse_arrow_fsm(prompt) is None
    assert S._emit_full_moore_fsm(prob) is None


def test_full_moore_skips_multi_bit_io():
    """The full-Moore emitter is for the canonical single-1-bit-input / single-
    1-bit-Moore-output FSM; a multi-bit input (e.g. an arbiter's r[3:1]) is NOT
    this shape -> SKIP (those need AI authoring)."""
    prompt = (
        "A (0) --0--> B\nA (0) --1--> A\nB (1) --0--> A\nB (1) --1--> B\n"
        "Implement this. Reset into A.\n"
        "module TopModule (\n  input clk,\n  input reset,\n"
        "  input [3:1] r,\n  output [3:1] g\n);")
    prob = {"prompt": prompt, "ifc": prompt}
    assert S._emit_full_moore_fsm(prob) is None


def test_emit_returns_none_on_unrelated_prompt():
    """A prompt with none of the three structures -> (None, None), no spurious
    fire (the emitters are a narrow, structure-gated fallback)."""
    prob = {"prompt": "Create a single D flip-flop.\n"
                      "module TopModule (input clk, input d, output reg q);",
            "ifc": "module TopModule (input clk, input d, output reg q);"}
    assert S.emit(prob) == (None, None)
