"""v1.1.69 — parametric_spec_extractor: deterministic BASELINE for the prose
parametric tier (arithmetic / memory / counter / shift / boolean / sequence /
number-format / PDK / timing-constraints / CRC). The AI pass still leads the full
understanding; this lifts the defining parameters a regex can get with confidence,
taking the program baseline from 47.9% -> 69.4% of the 1234-prompt corpus.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import parametric_spec_extractor as P    # noqa: E402
import spec_artifact_dual_pass as DP       # noqa: E402


def test_arithmetic():
    d = P.extract_arithmetic("Implement a 16-bit signed adder with saturation.")
    assert d == {"op": "adder", "width": 16, "signed": True, "overflow": "saturate"}
    assert P.extract_arithmetic("a plain shift register") is None


def test_memory():
    d = P.extract_memory("an asynchronous FIFO, depth 16, width 8")
    assert d["kind"] == "FIFO" and d["depth"] == 16 and d["width"] == 8


def test_counter():
    d = P.extract_counter("a 4-bit counter that counts up modulo 10")
    assert d == {"width": 4, "direction": "up", "modulo": 10}
    assert P.extract_counter("down-counter, 8-bit")["direction"] == "down"


def test_shift_register():
    d = P.extract_shift_register("a 32-bit LFSR shifting right with parallel load")
    assert d["direction"] == "right" and d["lfsr"] and d["load"] and d["width"] == 32


def test_boolean_expression():
    d = P.extract_boolean_expression("assign out = a & b | ~c;")
    assert d["assignments"][0] == {"output": "out", "expr": "a & b | ~c"}
    assert P.extract_boolean_expression("just prose, no expression") is None


def test_sequence_detector():
    d = P.extract_sequence_detector('detect the sequence "1101", overlapping, Mealy')
    assert d["pattern"] == "1101" and d["overlap"] and d["mealy"]


def test_number_format():
    assert P.extract_number_format("uses Q4.4 fixed-point")["frac_bits"] == 4
    assert P.extract_number_format("IEEE-754 floating point")["format"] == "floating_point"
    assert P.extract_number_format("BCD encoded")["format"] == "bcd"


def test_pdk_and_timing_and_crc():
    assert P.extract_pdk_target("targets the sky130 PDK")["pdk"].lower().startswith("sky130")
    assert P.extract_timing_constraints("clock period 10 ns")["period"] == "10ns"
    assert P.extract_timing_constraints("running at 100 MHz")["frequency"] == "100MHz"
    crc = P.extract_crc("CRC-32 with polynomial 0x04c11db7 and init 0xffffffff")
    assert crc["width"] == 32 and crc["poly"] == "0x04c11db7"


def test_parametric_in_dual_pass_baseline():
    doc = " - input clk\n - output [7:0] sum\n\nImplement an 8-bit signed adder.\n"
    base = DP.program_baseline(doc)
    types = {e["element_type"] for e in base}
    assert "pinout_table" in types and "arithmetic_spec" in types     # both baseline tiers fire
    arith = next(e for e in base if e["element_type"] == "arithmetic_spec")
    assert arith["data"]["op"] == "adder" and arith["data"]["signed"] is True
