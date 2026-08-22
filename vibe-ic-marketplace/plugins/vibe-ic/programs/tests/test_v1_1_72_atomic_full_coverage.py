"""v1.1.72 — close the last atomic-benchmark baseline gaps (directive-2 enhancement
loop on the real benchmark corpus). Broadened sequence_detector (the 'when the input
is 10011' phrasing) + shift_register ('right shift' word order); added edge_detector,
pulse_detector, clock_generator, signal_generator, timekeeping. ATOMIC (VE-v2 +
VE-human + RTLLM) deterministic baseline coverage is now 100% (was 98%); full DB 81.6%.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import parametric_spec_extractor as P    # noqa: E402


def test_sequence_detector_when_input_is_phrasing():
    # the RTLLM 'fsm' problem: "When the input is 10011, output MATCH"
    assert P.extract_sequence_detector_v2("When the input is 10011, output MATCH is 1")["pattern"] == "10011"
    assert P.extract_sequence_detector_v2("detects the sequence 1101")["pattern"] == "1101"
    assert P.extract_sequence_detector_v2("a plain counter") is None


def test_shift_register_right_shift_word_order():
    # RTLLM 'right_shifter': "performs an 8-bit right shift"
    d = P.extract_shift_register("performs an 8-bit right shift on a 1-bit input")
    assert d["direction"] == "right" and d["width"] == 8
    assert P.extract_shift_register("a left shifter") ["direction"] == "left"


def test_edge_detector():
    assert P.extract_edge_detector("When a changes from 0 to 1, set out")["edge"] == "rising"
    assert P.extract_edge_detector("detect the falling edge")["edge"] == "falling"
    assert P.extract_edge_detector("just an adder") is None


def test_pulse_clock_signal_timekeeping():
    assert P.extract_pulse_detector("a module for pulse detection")["detect"] == "pulse"
    assert P.extract_clock_generator("a clock generator producing a periodic clock")["kind"] == "clock_generator"
    assert P.extract_clock_generator("divide-by-8 clock divider")["divisor"] == 8
    assert P.extract_signal_generator("a Triangle Wave signal generator")["wave"] == "triangle"
    assert P.extract_timekeeping("perpetual calendar with seconds, minutes, hours")["fields"]
    assert P.extract_pulse_detector("an adder") is None


def test_new_types_registered():
    for k in ("edge_detector", "pulse_detector", "clock_generator",
              "signal_generator", "timekeeping"):
        assert k in P.EXTRACTORS
