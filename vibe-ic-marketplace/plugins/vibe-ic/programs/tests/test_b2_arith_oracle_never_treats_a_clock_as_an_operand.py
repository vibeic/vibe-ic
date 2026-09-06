"""A closed-form arithmetic oracle may not be built over a design's clocks.

MEASURED 2026-09-06 on the frozen RTLLM asyn_fifo, host 8HD-6: the generator
emitted a "closed-form" oracle asserting `wfull == wclk ^ rclk` -- the two CLOCKS
of an asynchronous FIFO driven as arithmetic operands -- and failed 2 of its 4
vectors against RTL that passes its own dataset testbench. The design was then
sent to repair, the repair was inert, and the emitter's output was waived to AI
backup. A false REJECTION costs exactly what a false certificate costs.

The sequential guard that should have caught this was already there and already
said the right thing -- "a clock input is present ... defer" -- but it recognised
clocks from an exact-name ALLOW-LIST (`clk`, `clock`, `clk_i`, `i_clk`,
`sysclk`), and a design that names its clocks by domain walks straight past it.
The allow-list is the defect, not the guard.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import arith_oracle_tb_gen as G  # noqa: E402


def test_domain_named_clocks_and_resets_are_recognised():
    for name in ("wclk", "rclk", "clk_a", "clk_b", "CLK_in", "Clk",
                 "wrstn", "rrstn", "arstn", "brstn", "rst_n", "RST", "rstn"):
        assert G.is_clock_or_reset_port(name), name


def test_real_operands_are_not_mistaken_for_clocks():
    # The no-leak direction: excluding a genuine operand would turn a sound
    # oracle into a DEFER, so the token rule must not fire on ordinary names.
    for name in ("a", "b", "A", "B", "sum", "product", "result", "c",
                 "data_in", "wdata", "rdata", "mul_a", "in", "out",
                 "freq", "count", "clocks_per_bit"):
        assert not G.is_clock_or_reset_port(name), name


#: the class asyn_fifo was registered under when the misfire was measured; it is
#: what opens the arithmetic-oracle path at all.
_ARITH_CLASS = "digital_arithmetic_primitive"


def _spec(tmp_path, ports, doc):
    import json
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "dut", "top_ports": ports}))
    (proj / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "dut", "overview": doc}))
    return G.extract_arith_spec(proj, _ARITH_CLASS)


def _p(name, d, w):
    return {"name": name, "mode": d, "direction": d, "io": None, "width": w}


def test_a_clocked_design_defers_however_its_clocks_are_named(tmp_path):
    spec, why = _spec(tmp_path, [
        _p("wclk", "input", 1), _p("rclk", "input", 1),
        _p("wrstn", "input", 1), _p("rrstn", "input", 1),
        _p("winc", "input", 1), _p("rinc", "input", 1),
        _p("wdata", "input", 1), _p("wfull", "output", 1),
        _p("rdata", "output", 1),
    ], "The full flag is the exclusive or ^ of the pointers.")
    assert spec is None, spec
    # The port widths here are the ones the real L9 carried -- every port 1 bit,
    # because the data buses are parameter-wide and no numeric width survives --
    # so the serial-mix guards ahead of it stay silent and the CLOCK guard is the
    # one that has to do the work. That is exactly the case that misfired.
    assert "clock input is present" in why


def test_a_combinational_adder_still_gets_its_oracle(tmp_path):
    # The direction that proves the guard is not simply refusing everything:
    # a purely combinational primitive with no clock must still be oracled.
    spec, why = _spec(tmp_path, [
        _p("a", "input", 8), _p("b", "input", 8), _p("cin", "input", 1),
        _p("sum", "output", 8), _p("cout", "output", 1),
    ], "Implement an 8-bit adder. sum = a + b.")
    assert spec is not None, why
    assert spec["operator"] == "+"
    assert {spec["operand_a"], spec["operand_b"]} == {"a", "b"}
    assert spec["result"] == "sum"
