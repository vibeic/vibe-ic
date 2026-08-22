#!/usr/bin/env python3
"""ORGANIC #300 [CRITICAL] — the clock port was chosen by NAME, so a netlist
carrying a clock-looking port with ZERO sinks bound the whole timing sign-off
to a decoy.

Field evidence (`edge_llm_matmul_accel`): two clock-looking top ports. The
resolver took the first name match, `clk` — a decoy with 0 sinks. The real
clock is `wb_clk_i`, carrying 14625/14625 clock pins across all 8385 flops.
Binding the SDC to the decoy gave CTS `found 0 clock nets` (1.15 s), a setup
analysis with ZERO endpoint violations, and a reported timing MET.

This is the worst false-certificate class in the campaign so far: the earlier
ones measured the WRONG thing or were optimistic by N ns. This one measured
NOTHING and was indistinguishable from clean at the verdict.

NOT design-specific: any netlist with a clock-looking but unconnected port
trips it.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402


def _netlist(n_flops: int = 200, clock_net: str = "wb_clk_i") -> str:
    flops = "\n".join(
        f"  sky130_fd_sc_hd__dfxtp_1 _{i}_ (.CLK({clock_net}), .D(d{i}), .Q(q{i}));"
        for i in range(n_flops))
    return (f"module edge_llm_matmul_accel(clk, wb_clk_i, rst, d, q);\n"
            f"  input clk;\n  input wb_clk_i;\n  input rst;\n"
            f"  input d;\n  output q;\n{flops}\nendmodule\n")


def test_300_sink_count_separates_the_decoy_from_the_real_clock():
    net = _netlist()
    assert p3._clock_port_sink_count(net, "clk") == 0
    assert p3._clock_port_sink_count(net, "wb_clk_i") == 200


def test_300_resolver_picks_the_connected_clock_not_the_first_name_match():
    """`clk` is declared FIRST and matches the clock-name regex, so the old
    name-first rule returned it. Connectivity must win."""
    got = p3._v1_6_623_clock_port_in_netlist_text(
        _netlist(), top="edge_llm_matmul_accel")
    assert got == "wb_clk_i", f"bound the 0-sink decoy: {got!r}"


def test_300_holds_when_the_decoy_is_declared_first_or_last():
    """Order must not decide it — only connectivity."""
    net = _netlist().replace("module edge_llm_matmul_accel(clk, wb_clk_i,",
                             "module edge_llm_matmul_accel(wb_clk_i, clk,")
    assert p3._v1_6_623_clock_port_in_netlist_text(
        net, top="edge_llm_matmul_accel") == "wb_clk_i"


def test_300_single_candidate_design_is_unchanged():
    """No regression for the overwhelmingly common one-clock case."""
    net = ("module t(clk, d, q);\n input clk;\n input d;\n output q;\n"
           "  dff u (.CLK(clk), .D(d), .Q(q));\nendmodule\n")
    assert p3._v1_6_623_clock_port_in_netlist_text(net, top="t") == "clk"


def test_300_tie_falls_back_to_declaration_order():
    """When NO clock pins are parseable (e.g. an RTL-ish netlist), every
    candidate scores 0 and we must reproduce the OLD behaviour exactly — the
    change can only improve on name-first, never pick something worse."""
    net = ("module t(clk, wb_clk_i, d);\n input clk;\n input wb_clk_i;\n"
           " input d;\nendmodule\n")
    assert p3._v1_6_623_clock_port_in_netlist_text(net, top="t") == "clk"


def test_300_sink_count_is_pdk_agnostic():
    """Clock pin naming differs across libraries; the count must not be tied
    to one PDK's spelling."""
    for pin in ("CLK", "CK", "CP", "GCLK", "CLKIN"):
        net = f"module t(a);\n  cell u (.{pin}(w_clk), .D(d));\nendmodule\n"
        assert p3._clock_port_sink_count(net, "w_clk") == 1, pin


def test_300_sink_count_does_not_match_data_pins():
    """A data pin whose name merely contains the letters must not count."""
    net = "module t(a);\n  cell u (.D(w_clk), .Q(z), .SCLKEN(w_clk));\nendmodule\n"
    assert p3._clock_port_sink_count(net, "w_clk") == 0
