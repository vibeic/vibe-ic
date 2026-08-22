"""Tests for ramp_waveform_oracle_check.py — the multi-bit ramp MEASUREMENT
layer that sits beside `spec_conformance_check`'s structural
`waveform-peak-hold-dropped` rule.

This is a BLOCKING gate, so the load-bearing half is the NEGATIVE no-leak: it
must SKIP unless the spec gives an unambiguous ramp contract, and it must never
block a correct ramp. `test_bounds_only_read_from_ramp_sentences` pins the
corpus-sweep defect: reading endpoints from the whole document derived a
contract from unrelated prose (a compliance-vector list's "6400 to 8533" data
rates) in 2 of 1158 repo documents.
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ramp_waveform_oracle_check as R  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

SPEC = ("Signal generator.\n\nThe block produces a triangle wave on a 6-bit "
        "output called wave. Starting from 0 the wave ramps up to 31 and back "
        "down to 0, incrementing by 1 each clock cycle. Reset is active high "
        "on rst.\n")

SPEC_HOLD = SPEC.replace("Reset is active high",
                         "The peak is held for 2 cycles before the wave turns "
                         "around. Reset is active high")

RTL_GOOD = """
module signal_gen(input clk, input rst, output reg [5:0] wave);
  reg dir;
  always @(posedge clk) if (rst) begin wave<=6'd0; dir<=1'b0; end
    else if (dir==1'b0) begin
      if (wave==6'd31) begin dir<=1'b1; wave<=wave-6'd1; end else wave<=wave+6'd1;
    end else begin
      if (wave==6'd0) begin dir<=1'b0; wave<=wave+6'd1; end else wave<=wave-6'd1;
    end
endmodule
"""
RTL_WRONG_BOUND = RTL_GOOD.replace("6'd31", "6'd30")
RTL_WRONG_STEP = (RTL_GOOD.replace("wave+6'd1", "wave+6'd2")
                          .replace("wave-6'd1", "wave-6'd2"))


# ── contract derivation (no iverilog needed) ───────────────────────────────
def test_contract_from_plain_prose():
    c = R.derive_contract(SPEC)
    assert c is not None
    assert (c.lo, c.hi, c.step) == (0, 31, 1)


def test_inflected_ramp_words_are_in_scope():
    """`ramps up to 31` must put that sentence in scope — a bare \\bramp\\b
    misses the inflected form and silently SKIPs every real ramp spec."""
    assert R.derive_contract(SPEC) is not None


def test_bounds_only_read_from_ramp_sentences():
    """Numbers elsewhere in the document must not become ramp bounds."""
    noise = ("The interface runs from 6400 to 8533 megatransfers per second.\n"
             "Unrelated: values from 12 to 99 appear in the register map.\n")
    assert R.derive_contract(noise) is None
    # a ramp sentence plus unrelated numbers elsewhere still reads correctly
    assert R.derive_contract(noise + SPEC).lo == 0


def test_no_contract_without_a_ramp_word():
    assert R.derive_contract("A counter that counts from 0 to 31.") is None


def test_ambiguous_bounds_skip():
    spec = ("A triangle wave that ramps from 0 to 31, and in another mode "
            "ramps from 0 to 63.")
    assert R.derive_contract(spec) is None


def test_output_choice_requires_a_unique_multibit_output():
    assert R.choose_output({"a": ("output", 8), "b": ("output", 8)}) is None
    assert R.choose_output({"a": ("output", 8), "b": ("output", 1)}) == "a"


# ── measurement (pure, no iverilog needed) ─────────────────────────────────
def test_measure_reads_bounds_step_and_dwell():
    trace = ([0, 1, 2, 3, 4, 5] + [5] + [4, 3, 2, 1, 0] + [0] +
             [1, 2, 3, 4, 5] + [5] + [4, 3, 2, 1, 0]) * 3
    m = R.measure(trace)
    assert m["min"] == 0 and m["max"] == 5
    assert m["steps"] == [1]
    assert 2 in m["dwells"]


def test_measure_rejects_a_trace_that_never_reverses():
    assert R.measure(list(range(200))) is None


# ── end to end (needs iverilog: the oracle simulates) ──────────────────────
@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle simulates")
def test_correct_ramp_passes():
    assert R.analyze(RTL_GOOD, SPEC)["verdict"] == "PASS"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle simulates")
def test_wrong_upper_bound_blocks():
    r = R.analyze(RTL_WRONG_BOUND, SPEC)
    assert r["verdict"] == "BLOCK"
    assert r["evidence"]["max"] == 30
    assert "31" in r["reason"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle simulates")
def test_wrong_step_blocks():
    r = R.analyze(RTL_WRONG_STEP, SPEC)
    assert r["verdict"] == "BLOCK"
    assert "step" in r["reason"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle simulates")
def test_dropped_peak_hold_blocks_when_the_spec_states_one():
    """The property the structural rule could only approximate: the dwell is
    MEASURED and compared to the spec-stated cycle count."""
    r = R.analyze(RTL_GOOD, SPEC_HOLD)
    assert r["verdict"] == "BLOCK"
    assert "dwell" in r["reason"]


@pytest.mark.skipif(not _HAS_IVERILOG, reason="oracle simulates")
def test_extra_driveable_input_skips():
    """An enable the TB cannot safely drive would float and mis-measure a
    correct design → SKIP, never BLOCK."""
    rtl = RTL_GOOD.replace("input rst,", "input rst, input en,")
    assert R.analyze(rtl, SPEC)["verdict"] == "SKIP"


def test_module_is_chip_agnostic():
    src = Path(R.__file__).read_text()
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    for tok in ("rtllm", "cvdp", "verilogeval", "signal_generator"):
        assert tok not in code.lower(), tok
