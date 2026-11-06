#!/usr/bin/env python3
"""FX_P2 (1) — a declared case the design INPUT cannot run is NOT_MEASURED,
not FAIL; a case that ran and failed stays FAIL; a case THIS FLOW could have
run and did not stays blocking.

MEASURED on subservient (reused serv 1.4.0, 8HD-4, 2026-09-28, D3 stacked):
step4_functional_evidence FAILed "only 1 of 6 declared L10 case(s) EXECUTED
their own oracle", and the run halted in phase 2. The five split two ways:

  THIS FLOW'S GAP   reset_n_cycle_instruction, i_rst_glitch_instruction_fetch_race
                    Their oracle families (boot latency, reset glitch) claim
                    them, but could not observe the top: its outputs are an
                    SRAM port, and the bus-activity vocabulary had no
                    read-enable. With `*_ren` recognised both run in Verilator
                    and PASS (first read at cycle 1 of the declared 10; no
                    read inside a one-cycle reset glitch).
  THE INPUT'S GAP   blinky_hex / hello_hex name `blinky.hex` / `hello.hex`,
                    which are nowhere in the design input; zifencei states its
                    stimulus as "Zifencei 指令" and its expected half as
                    "PASS", and no program is delivered. The rv32i_40 coverage
                    goal binds the instruction dimension, whose instrument can
                    only read a program that ran — and none is delivered.
                    Nothing in this flow may author those programs (§4.05).

Owner rule (2026-09-28): only a plain FAIL is red. The input's gap is
NOT_MEASURED with the case and the missing input named.

Driven through the real gate (`_evaluate`, `main --json`) and the real runner
step; only the testbench EXECUTION record is planted, in the shape
`testbench_gen.run_unit_tbs` writes it.

chip-AGNOSTIC: synthetic ports and case texts; the file names are formats.
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cpu_boot_latency_oracle_tb_gen as CLG      # noqa: E402
import reset_invariant_oracle_tb_gen as RIV        # noqa: E402
import testbench_gen as TBG                        # noqa: E402

TOP = "core_top"

#: Asked through `getattr` so a tree without the classifier ANSWERS (None:
#: "not the input's gap") rather than raising — the teeth below must run on
#: both trees.

#: The case texts are subservient's own, as its L10 carries them.
BOOT = {"name": "reset_n_cycle_instruction", "kind": "functional_vector",
        "stimulus": "Reset 解除後 N cycle 內取得第一條 instruction",
        "expected": "N ≤ 策略決定的最大 boot latency(典型 < 10 cycle)"}
HEX = {"name": "blinky_hex", "kind": "functional_vector",
       "stimulus": "blinky.hex", "expected": "GPIO 輸出規則性 toggle"}
PROSE = {"name": "zifencei", "kind": "functional_vector",
         "stimulus": "Zifencei 指令", "expected": "PASS"}
GOAL = {"name": "rv32i_40", "kind": "functional_vector",
        "stimulus": "整套 RV32I 指令(40+ 條)單元測試",
        "expected": "100% PASS(可用 compliance suite 或內附 testbench)"}

#: An SRAM-port top: the surface the bus-activity vocabulary could not see.
SRAM_INPUTS = [("i_clk", ""), ("i_rst", ""), ("i_sram_rdata", "[7:0]")]
SRAM_OUTPUTS = [("o_sram_waddr", "[8:0]"), ("o_sram_wdata", "[7:0]"),
                ("o_sram_wen", ""), ("o_sram_raddr", "[8:0]"),
                ("o_sram_ren", ""), ("o_gpio", "")]






# ---------------------------------------------------------------------------
# the measured case, through the gate
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# TEETH — what must stay red
# ---------------------------------------------------------------------------














def test_a_denied_image_name_is_not_a_named_stimulus():
    assert TBG.named_stimulus_images("load blinky.hex") == ["blinky.hex"]
    assert TBG.named_stimulus_images("no blinky.hex is used") == []


# ---------------------------------------------------------------------------
# THIS FLOW'S GAP — the read-enable is bus activity
# ---------------------------------------------------------------------------
def test_boot_latency_oracle_observes_an_sram_read_enable():
    text = CLG.emit_case_oracle_from_ports(BOOT, TOP, SRAM_INPUTS,
                                           SRAM_OUTPUTS, [])
    assert text and "o_sram_ren" in text


def test_reset_glitch_oracle_observes_an_sram_read_enable():
    glitch = {"name": "i_rst_glitch_instruction_fetch_race",
              "kind": "functional_vector",
              "stimulus": "i_rst glitch 不應導致 instruction fetch race",
              "expected": "holds: i_rst glitch 不應導致 instruction fetch race"}
    text = RIV.emit_case_oracle_from_ports(glitch, TOP, SRAM_INPUTS,
                                           SRAM_OUTPUTS, [])
    assert text and "o_sram_ren" in text


def test_a_write_enable_or_a_lookalike_is_not_a_read():
    """Only a read strobe is the first fetch; `wen` and a name that merely ends
    in the letters (`o_green`) are not."""
    outs = [("o_sram_wen", ""), ("o_green", "")]
    assert CLG._pick_bus_activity_output(outs) is None
