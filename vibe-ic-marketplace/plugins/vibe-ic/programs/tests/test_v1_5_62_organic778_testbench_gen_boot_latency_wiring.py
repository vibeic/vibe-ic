#!/usr/bin/env python3
"""ORGANIC #778 companion — testbench_gen.py wiring of
cpu_boot_latency_oracle_tb_gen (the CPU-core / clocked-core BOOT-LATENCY
convention), mirroring how arith_oracle_tb_gen is already wired for the
datapath convention.

Verifies the per-case dispatch: a `functional_vector` case matching the
boot-latency SHAPE (and whose DUT exposes a bus-activity output) gets the
REAL oracle (no ORACLE_NONE marker); a sibling case that does NOT match
either the datapath or boot-latency convention still gets the honest
substance-floor scaffold (ORACLE_NONE present) — never silently upgraded to
"covered" without a real oracle behind it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "testbench_gen.py"
sys.path.insert(0, str(PROG.parent))
import testbench_gen as T  # noqa: E402

# Chip-AGNOSTIC synthetic DUT: a clocked core exposing a generic Wishbone-
# family bus-activity output (`o_cyc`) — no chip/vendor/SKU literal.
DUT_MODULE = "test_cpu_core"
DUT_RTL = """\
module test_cpu_core (
    input        i_clk,
    input        i_rst,
    output       o_cyc,
    output [7:0] o_data
);
  reg cyc_q;
  always @(posedge i_clk) cyc_q <= !i_rst;
  assign o_cyc = cyc_q;
  assign o_data = 8'hAA;
endmodule
"""

_L10 = {
    "test_cases": [
        {"name": "reset_n_cycle_instruction", "kind": "functional_vector",
         "stimulus": "Reset 解除後 N cycle 內取得第一條 instruction",
         "expected": "N ≤ boot latency(典型 < 10 cycle)"},
        {"name": "unrelated_case", "kind": "functional_vector",
         "stimulus": "some other behaviour", "expected": "PASS"},
    ]
}


def _make_project(tmp_path) -> Path:
    project = tmp_path / "p"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / f"{DUT_MODULE}.v").write_text(DUT_RTL)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps(_L10))
    return project


def test_boot_latency_case_gets_real_oracle_sibling_stays_stub(tmp_path):
    project = _make_project(tmp_path)
    report: dict = {}
    emitted = T.emit_unit_tbs(project, top=DUT_MODULE,
                             kind="functional_vector", report=report)
    assert emitted == 2, report

    boot_tb = (project / "phase2" / "stage1" / "sim" / "tb"
              / "reset_n_cycle_instruction.v").read_text()
    assert T.ORACLE_NONE_MARKER not in boot_tb
    assert f"{DUT_MODULE} u_dut (" in boot_tb
    assert "o_cyc" in boot_tb
    assert "$fatal(1);" in boot_tb
    assert "reset_n_cycle_instruction" in report.get(
        "boot_latency_oracle_cases", [])

    other_tb = (project / "phase2" / "stage1" / "sim" / "tb"
               / "unrelated_case.v").read_text()
    assert T.ORACLE_NONE_MARKER in other_tb
    assert "unrelated_case" not in report.get("boot_latency_oracle_cases", [])
    assert "unrelated_case" not in report.get("golden_oracle_cases", [])


def test_boot_latency_case_falls_back_to_stub_when_no_bus_activity_output(tmp_path):
    """§4.05 fail-closed: a DUT with NO recognised bus-activity output gets
    the honest substance floor even for a boot-latency-shaped case."""
    project = tmp_path / "p2"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "plain_core.v").write_text(
        "module plain_core (\n"
        "    input        i_clk,\n"
        "    input        i_rst,\n"
        "    output [7:0] o_data\n"
        ");\n  assign o_data = 8'h00;\nendmodule\n")
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L10_TEST_CASES.json").write_text(json.dumps({
        "test_cases": [_L10["test_cases"][0]]
    }))
    report: dict = {}
    emitted = T.emit_unit_tbs(project, top="plain_core",
                             kind="functional_vector", report=report)
    assert emitted == 1, report
    tb = (project / "phase2" / "stage1" / "sim" / "tb"
         / "reset_n_cycle_instruction.v").read_text()
    assert T.ORACLE_NONE_MARKER in tb
    assert not report.get("boot_latency_oracle_cases")
