"""The coverage build must look in the directory this flow's own gate demands a
testbench in.

MEASURED 2026-09-15 (lane icsub2) on `subservient` x gf180mcuD. Two programs in
one flow, disagreeing about where a testbench lives::

    rtl_unit_test_coverage_check   ->  rc 1
        missing_unit_tb  subservient.v
        expected_tb      sim_unit/tb_subservient.v
        reasons          FSM pattern `case (state)`, `reg [N:0] state`
        message          "See rtl-unit-testbench-gen SKILL.md"

    verilator_coverage_measure._TB_DISCOVERY_ORDER
        phase2/stage1/sim_full_stack/tb_*_oracle.v
        phase2/stage1/sim_full_stack/tb_*_full.v
        phase2/stage1/sim/tb/*.v            <-- and nothing else

so the flow ASKED FOR the one testbench that could move the design and then
looked everywhere except where it had asked for it. What the coverage build
found instead, in `verilator_coverage_measure check`'s own words::

    NO FUNCTIONAL STIMULUS IN THE COVERAGE BUILD -- this run measured no
    coverage of the design ... of the signal(s) it binds to the design and
    declares drivable it assigns only ['i_clk','i_rst'] -- the clock and reset.
    It never drives ['i_sram_data'], so the design's inputs were never moved.
    ... the recorded percentages (line 45.19%, toggle 34.76%, branch 43.75%)
    describe that testbench, NOT the RTL.

Every candidate the three entries could reach was inert: the `sim_full_stack`
harness declares itself connectivity-only and all ten `sim/tb/*.v` are the
generator's SUBSTANCE FLOOR shape, each carrying `VIBEIC_TB_ORACLE: NONE`.

WHAT IT COST, end to end, and what it buys once the two lists are one list --
measured over the real design with `verilator --binary --timing --coverage-*`
in the pinned image and parsed by this module's own `parse_coverage_dat`::

    scoped to the RTL        before          after
    line                     45.19 %         80.74 %   (109/135)
    toggle                   34.76 %         93.55 %   (1639/1752)
    branch                   43.75 %         91.67 %   (44/48)

    verilator_coverage_measure check   blocking floor 70/60/70   FAIL -> PASS
    coverage_closure                   goal 80 %                 FAIL -> PASS

THE ENTRY IS LAST, AND THAT IS THE DESIGN. `_TB_DISCOVERY_ORDER` is
most-authoritative-first and a per-module unit TB is not what the flow
simulates for its functional verdict, so it must not displace an oracle. It is
reachable because the selection already prefers whichever candidate
DEMONSTRABLY DRIVES A FUNCTIONAL INPUT -- this change adds a place to look, not
a new preference rule, and the two tests below pin both halves of that.

chip-AGNOSTIC: generic `dut` / `tb_*` fixtures, no design, PDK or vendor token.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import verilator_coverage_measure as V  # noqa: E402

_INERT_TB = """\
// A connectivity-only harness: it moves the clock and the reset and nothing
// else, which is the shape the flow's own generator emits by default.
module tb_top_full;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  reg [7:0] data_i = 8'h00;
  wire [7:0] data_o;
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .data_i(data_i),
             .data_o(data_o));
  initial begin rst_ni <= 1'b1; #100 $finish; end
endmodule
"""

_DRIVING_UNIT_TB = """\
// A per-module unit testbench that actually moves the design's data input.
module tb_dut;
  reg clk_i = 1'b0;
  always #5 clk_i = ~clk_i;
  reg rst_ni = 1'b0;
  reg [7:0] data_i = 8'h00;
  wire [7:0] data_o;
  dut u_dut (.clk_i(clk_i), .rst_ni(rst_ni), .data_i(data_i),
             .data_o(data_o));
  initial begin
    rst_ni <= 1'b1;
    data_i <= 8'hA5;
    #20 data_i <= 8'h5A;
    #100 $finish;
  end
endmodule
"""


def _project(tmp_path: Path, unit_rel: str = "sim_unit") -> Path:
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase2/stage1/rtl/dut.v").write_text(
        "module dut(input clk_i, input rst_ni, input [7:0] data_i,\n"
        "           output [7:0] data_o);\n"
        "  assign data_o = data_i;\n"
        "endmodule\n")
    fs = tmp_path / "phase2/stage1/sim_full_stack"
    fs.mkdir(parents=True, exist_ok=True)
    (fs / "tb_dut_full.v").write_text(_INERT_TB)
    unit = tmp_path / unit_rel
    unit.mkdir(parents=True, exist_ok=True)
    (unit / "tb_dut.v").write_text(_DRIVING_UNIT_TB)
    return tmp_path


# ── the defect, and its repair ────────────────────────────────────────────

def test_the_inert_harness_really_is_inert():
    """The fixture is the measured shape, not a hypothetical: the flow's own
    audit is what calls it inert, and this file does not maintain a second
    definition of stimulus."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tb = Path(td) / "tb_top_full.v"
        tb.write_text(_INERT_TB)
        a = V.functional_stimulus_audit(tb)
        assert a["decidable"] and a["driven"] == []
        assert "data_i" in a["inert"]


def test_discovery_finds_the_unit_tb_the_flow_asked_for(tmp_path):
    """THE DEFECT. Pre-fix, `sim_unit/` was not in the search at all, so the
    only driving stimulus in the project was invisible and the inert harness
    was instrumented instead."""
    _rtl, tb = V.discover_measure_inputs(_project(tmp_path))
    assert tb and Path(tb).name == "tb_dut.v", (
        f"the coverage build chose {tb!r} over the unit testbench the flow's "
        f"own rtl_unit_test_coverage_check demands")


def test_the_phase2_spelling_of_the_unit_dir_is_searched_too(tmp_path):
    _rtl, tb = V.discover_measure_inputs(
        _project(tmp_path, unit_rel="phase2/stage1/sim_unit"))
    assert tb and Path(tb).name == "tb_dut.v"




# ── the guards: the order and the preference rule are unchanged ───────────

def test_an_oracle_still_outranks_a_unit_tb_when_both_drive(tmp_path):
    """MOST-AUTHORITATIVE-FIRST IS NOT WEAKENED. The oracle TB is the one the
    flow simulates for its functional verdict; instrumenting it measures the
    run that was BELIEVED. A unit TB may only win when nothing above it
    drives."""
    p = _project(tmp_path)
    (p / "phase2/stage1/sim_full_stack/tb_dut_oracle.v").write_text(
        _DRIVING_UNIT_TB.replace("module tb_dut;", "module tb_dut_oracle;"))
    _rtl, tb = V.discover_measure_inputs(p)
    assert tb and Path(tb).name == "tb_dut_oracle.v", tb


def test_a_driving_sim_tb_still_outranks_a_unit_tb(tmp_path):
    p = _project(tmp_path)
    d = p / "phase2/stage1/sim/tb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tb_vec.v").write_text(
        _DRIVING_UNIT_TB.replace("module tb_dut;", "module tb_vec;"))
    _rtl, tb = V.discover_measure_inputs(p)
    assert tb and Path(tb).name == "tb_vec.v", tb


def test_an_inert_unit_tb_does_not_displace_the_declared_first_hit(tmp_path):
    """Adding a place to look must not add a preference. When NOTHING drives,
    the historical first hit is still what is chosen."""
    p = _project(tmp_path)
    (p / "sim_unit/tb_dut.v").write_text(
        _INERT_TB.replace("module tb_top_full;", "module tb_dut;"))
    _rtl, tb = V.discover_measure_inputs(p)
    assert tb and Path(tb).name == "tb_dut_full.v", tb


def test_a_project_with_no_unit_dir_is_unaffected(tmp_path):
    p = _project(tmp_path)
    for f in (p / "sim_unit").glob("*"):
        f.unlink()
    (p / "sim_unit").rmdir()
    _rtl, tb = V.discover_measure_inputs(p)
    assert tb and Path(tb).name == "tb_dut_full.v", tb
