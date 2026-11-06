#!/usr/bin/env python3
"""FX_P2 review fix (6c, 6d) — two MINORs.

(6c) 065ef1c45 appended the read-enable tokens (ren/rden/rd_en/read_en) to the
     same bus-activity list the boot-latency and reset-glitch oracles pick the
     FIRST matching output from, in port order. A CPU top that exposes both a
     handshake and a data-port read-enable (`o_dmem_ren` listed before
     `o_ibus_cyc`) switched from observing its instruction fetch to observing a
     data read: a false red for boot latency, a missed fetch race for the
     glitch oracle. Handshake tokens now win; a read-enable is the fallback for
     a top with no handshake (the SRAM-only top the change was measured on).

(6d) The branch dated phase-3 records against this run's phase-2 netlist only
     to excuse a missing reading; `_requirements_backed` still credited an
     older phase-3 PASS as this run's measurement. Now a phase-3 record older
     than the netlist backs nothing (it reads as absent). A stale FAILING
     record stays failing -- dating never turns a red into an absence.

Driven through the real generators and the real gate (as a subprocess).
chip-AGNOSTIC: synthetic ports and project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import cpu_boot_latency_oracle_tb_gen as CLG    # noqa: E402
import reset_invariant_oracle_tb_gen as RIV     # noqa: E402
import phase1_post_process as P                 # noqa: E402

TOP = "core_top"
INPUTS = [("i_clk", ""), ("i_rst", ""), ("i_ibus_rdt", "[31:0]")]
#: The data-port read-enable is listed FIRST.
BOTH = [("o_dmem_ren", ""), ("o_ibus_cyc", ""), ("o_ibus_adr", "[31:0]")]
SRAM_ONLY = [("o_sram_waddr", "[8:0]"), ("o_sram_wen", ""),
             ("o_sram_ren", ""), ("o_gpio", "")]
BOOT = {"name": "boot", "kind": "functional_vector",
        "stimulus": "Reset 解除後 N cycle 內取得第一條 instruction",
        "expected": "N ≤ 10 cycle"}
GLITCH = {"name": "glitch", "kind": "functional_vector",
          "stimulus": "i_rst glitch 不應導致 instruction fetch race",
          "expected": "holds: i_rst glitch 不應導致 instruction fetch race"}


def _observes(text: str, port: str) -> bool:
    """The oracle's activity comparison is on `port` (every DUT wire is
    declared, so a bare substring says nothing)."""
    return f"(({port}) === 1'b1" in text or f"if (({port}) === 1'b1" in text


# ---- (6c) --------------------------------------------------------------
def test_a_handshake_wins_over_a_read_enable_listed_first():
    assert CLG._pick_bus_activity_output(BOTH) == "o_ibus_cyc"


def test_the_boot_oracle_still_observes_the_fetch_handshake():
    text = CLG.emit_case_oracle_from_ports(BOOT, TOP, INPUTS, BOTH, [])
    assert text and _observes(text, "o_ibus_cyc"), text
    assert not _observes(text, "o_dmem_ren")


def test_the_glitch_oracle_still_observes_the_fetch_handshake():
    text = RIV.emit_case_oracle_from_ports(GLITCH, TOP, INPUTS, BOTH, [])
    assert text and _observes(text, "o_ibus_cyc"), text
    assert not _observes(text, "o_dmem_ren")


def test_a_top_with_only_a_read_enable_falls_back_to_it():
    """The measured SRAM-only top keeps what the branch fixed."""
    assert CLG._pick_bus_activity_output(SRAM_ONLY) == "o_sram_ren"
    text = RIV.emit_case_oracle_from_ports(GLITCH, TOP, INPUTS, SRAM_ONLY, [])
    assert text and _observes(text, "o_sram_ren")


# ---- (6d) --------------------------------------------------------------
