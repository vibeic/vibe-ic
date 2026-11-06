#!/usr/bin/env python3
"""FX_P2 review fix (3, 4) — a declared case or coverage goal is booked as the
design INPUT's gap only on positive evidence; everything the flow could have
run stays blocking.

Owner rule: only a plain FAIL is red, and a FAIL must never be relabelled
NOT_MEASURED when the flow could have run the check. At 065ef1c45 two
classifiers moved runnable work out of FAIL:

(3) `testbench_gen.case_input_gap`'s no-image branch booked ANY case no family
    claimed as `input_absent`. The stated-vector family "claimed" a case only
    when its driver could EXTRACT a value, so a case whose input states both
    halves in a shape the driver cannot read (two expected outputs, an odd-
    length hex, a decimal) was called the input's gap. A family detector that
    raised, and the reset family's refusal of an ambiguous case (both of its
    detectors fire), also read as "no family"; and a case this run HAD a
    testbench for (sim/tb/<case>.v) was never asked about.

(4) `cpu_functional_oracle_waiver_check._coverage_goal_summary` booked a goal
    as the input's gap whenever its dimension bound and its number was absent
    -- which is also what a coverage instrument that never ran, timed out or
    crashed leaves behind.

Driven through the real gate (`_evaluate`) and the real classifier; only the
testbench EXECUTION record (the shape `testbench_gen.run_unit_tbs` writes) and
the instrument receipt (through the instrument's own `measure`/`write_receipt`)
are planted. chip-AGNOSTIC: synthetic cases; file names are formats.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import testbench_gen as TBG                        # noqa: E402

TOP = "core_top"

#: A case whose stimulus and expected halves are both stated, but whose shape
#: no driver of this flow reads -- none of them names an image.
PASSING = {"name": "boot", "kind": "functional_vector",
           "stimulus": "Reset 解除後 N cycle 內取得第一條 instruction",
           "expected": "N ≤ 10 cycle"}
TWO_OUTPUTS = {"name": "rw_pair", "kind": "functional_vector",
               "stimulus": "write 0xA5 to DATA, pulse START",
               "expected_outputs": {"dout": "0x5a", "valid": "0x01"}}
ODD_HEX = {"name": "odd_hex", "kind": "functional_vector",
           "stimulus": "load ACC then shift once", "expected": "0x5"}
DECIMAL = {"name": "add_regs", "kind": "functional_vector",
           "stimulus": "x1=5, x2=7 後執行 ADD x3,x1,x2", "expected": "x3 = 12"}
LIST_OUTPUTS = {"name": "list_out", "kind": "functional_vector",
                "stimulus": "strobe the port once",
                "expected_outputs": ["0xA5"]}
BOTH_RESET = {"name": "hold_and_glitch", "kind": "functional_vector",
              "stimulus": "reset 期間 SRAM 內容保持，reset glitch 不應造成 race",
              "expected": "SRAM 內容保持，reset glitch 不應造成 race"}
#: The measured input gap: no image, no delivered program, expected "PASS".
PROSE = {"name": "zifencei", "kind": "functional_vector",
         "stimulus": "Zifencei 指令", "expected": "PASS"}
HEX = {"name": "hello_hex", "kind": "functional_vector",
       "stimulus": "hello.hex", "expected": "UART 輸出 hello"}
GOAL = {"name": "rv32i_40", "kind": "functional_vector",
        "stimulus": "整套 RV32I 指令(40+ 條)單元測試",
        "expected": "100% PASS(可用 compliance suite 或內附 testbench)"}
LINE_GOAL = {"name": "line_cov", "kind": "coverage_goal",
             "stimulus": "line coverage over all RTL", "expected": ">= 90%"}








# ---------------------------------------------------------------------------
# (3) the input stated both halves: a driver gap, never the input's
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", [TWO_OUTPUTS, ODD_HEX, DECIMAL, LIST_OUTPUTS],
                         ids=lambda c: c["name"])
def test_the_stated_vector_family_claims_what_it_cannot_extract(case):
    assert TBG.oracle_family_claiming(case) == "stated_vector"














# ---------------------------------------------------------------------------
# (4) a coverage goal: the instrument's own receipt, or it stays a refusal
# ---------------------------------------------------------------------------
