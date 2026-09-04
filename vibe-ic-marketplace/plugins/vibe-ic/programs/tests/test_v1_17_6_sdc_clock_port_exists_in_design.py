#!/usr/bin/env python3
"""The auto-SDC named a clock port the design does not have, and every timing
number in the run became 0.00 without anything saying so.

`_resolve_clock_spec` reads, among other sources, `L8.clock_domains[].name`.
That field is the DOMAIN's name, extracted from document prose; the port is
whatever the RTL declares. Nothing compared the two.

MEASURED, subservient x gf180mcuD, 2026-09-04, plugin v1.17.5 / image 0.3.41:

    L8_RTL_CONSTANTS.json  clock_domains[0].name = "clk"
                           evidence: "100 MHz" in L1_product_metadata.md
    constraint.sdc         create_clock -name clk -period 10.0 [get_ports clk]
    chip_top_synth.v       input i_clk;

    sta_SS.log             Warning 366: constraint.sdc line 2,
                                        port 'clk' not found.
    sta_SS.rpt             No paths found.
                           tns max 0.00
                           wns max 0.00

The sign-off gate could only report `STA_VALUE_UNDETERMINED` -- the symptom,
not the cause. Re-running the SAME deck against the SAME netlist with the port
corrected to `i_clk` gives `wns max -84.28`, `tns max -80517.09`. A WNS of 0.00
from a deck that constrained no clock is the most dangerous shape a timing
number can have, and it is indistinguishable from a design that closes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

_NETLIST = (
    "module chip_top (i_clk, i_rst, o_q);\n"
    "  input i_clk;\n"
    "  input i_rst;\n"
    "  output o_q;\n"
    "endmodule\n"
)


def _project(tmp_path: Path, netlist: str = _NETLIST) -> Path:
    import _path_layout as pl
    d = pl.synth_dir(tmp_path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "chip_top_synth.v").write_text(netlist)
    return tmp_path


def test_the_ports_are_read_from_the_design(tmp_path):
    assert R._design_top_input_ports(_project(tmp_path), "chip_top") == [
        "i_clk", "i_rst"]


def test_a_domain_name_is_remapped_onto_the_port_that_exists(tmp_path):
    port, note = R._clock_port_against_the_design(
        _project(tmp_path), "chip_top", "clk")
    assert port == "i_clk"
    assert "VIBEIC_SDC_CLOCK_PORT_REMAPPED" in note
    assert "'clk'" in note and "'i_clk'" in note


def test_a_name_that_is_already_a_port_is_left_alone(tmp_path):
    """NEGATIVE CONTROL. A design whose clock port IS `clk` must emit exactly
    what it emitted before, with no disclosure."""
    proj = _project(tmp_path, "module chip_top (clk, d);\n"
                             "  input clk;\n  input d;\nendmodule\n")
    assert R._clock_port_against_the_design(proj, "chip_top", "clk") \
        == ("clk", "")


def test_no_readable_netlist_changes_nothing(tmp_path):
    """NEGATIVE CONTROL. Not seeing the design is not evidence about it: the
    resolved name is kept and nothing is claimed."""
    assert R._clock_port_against_the_design(tmp_path, "chip_top", "clk") \
        == ("clk", "")


def test_two_candidate_ports_are_refused_not_guessed(tmp_path):
    """`i_clk` and `clk_i` both reduce to `clk`; picking one would be a coin
    toss, so the deck keeps the resolved name and says what it found."""
    proj = _project(tmp_path, "module chip_top (i_clk, clk_i, d);\n"
                              "  input i_clk;\n  input clk_i;\n"
                              "  input d;\nendmodule\n")
    port, note = R._clock_port_against_the_design(proj, "chip_top", "clk")
    assert port == "clk"
    assert "VIBEIC_SDC_CLOCK_PORT_NOT_IN_DESIGN" in note
    assert "2 candidates" in note and "clk_i" in note and "i_clk" in note


def test_an_absent_port_with_no_candidate_is_disclosed(tmp_path):
    proj = _project(tmp_path, "module chip_top (aclk, d);\n"
                              "  input aclk;\n  input d;\nendmodule\n")
    port, note = R._clock_port_against_the_design(proj, "chip_top", "clk")
    assert port == "clk"
    assert "VIBEIC_SDC_CLOCK_PORT_NOT_IN_DESIGN" in note
    assert "aclk" in note


def test_affix_stripping_is_one_affix_only():
    assert R._strip_port_affixes("i_clk") == "clk"
    assert R._strip_port_affixes("clk_i") == "clk"
    assert R._strip_port_affixes("clk") == "clk"
    assert R._strip_port_affixes("i_") == "i_"      # nothing left to strip
