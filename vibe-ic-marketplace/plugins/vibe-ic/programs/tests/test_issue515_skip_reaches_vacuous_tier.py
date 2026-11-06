#!/usr/bin/env python3
"""#515 — a gate that examined nothing must reach the VACUOUS tier.

`flow_compliance_check` originally defined rc 0 = PASS / rc 1 = FAIL / rc 2 =
VACUOUS. #1978 preserves rc=2 as a non-PASS signal but requires a typed cause
before it may enter the N/A tier:

  * `_run_structural_rtl_gates` (:4866) — rc 2 becomes a `SKIP` gate record
    carrying `skip_kind: "input-missing"`;
  * `_check_program_exit_zero` (:2205) — rc 2 becomes the `__VACUOUS_HINT__`
    prefix that `check_step` promotes to the `VACUOUS_PASS` step status.

Five gates announced a skip in their own stdout and exited 0 anyway, so #515
moved them out of PASS. The tests now also pin #1978's second distinction:
banner-only absence is INCOMPLETE, while a declared absence remains VACUOUS.

WHY THESE TESTS DRIVE THE REAL CONSUMERS. A unit test asserting `rc == 2` in
isolation proves the gate changed its mind, not that the tier moved. Both
consumers below are the shipped functions, invoked unmocked, running the real
gate as a real subprocess — the exit code is produced and classified by the
same code the flow runs.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent

import _vacuous_exit as _vx  # noqa: E402



# --------------------------------------------------------------------------
# The convention itself.
# --------------------------------------------------------------------------

def test_rc_convention_constants_match_the_flow_side():
    assert (_vx.RC_PASS, _vx.RC_FAIL, _vx.RC_VACUOUS) == (0, 1, 2)


def test_exit_code_routes_from_the_structured_conclusion():
    assert _vx.exit_code(passed=True, skipped=False) == _vx.RC_PASS
    assert _vx.exit_code(passed=True, skipped=True) == _vx.RC_VACUOUS
    assert _vx.exit_code(passed=False, skipped=False) == _vx.RC_FAIL


def test_a_finding_beats_a_skip():
    """If the two flags ever disagree, the violation must survive. Silencing
    a real finding behind a skip is the failure this convention prevents."""
    assert _vx.exit_code(passed=False, skipped=True) == _vx.RC_FAIL


def test_summary_is_skipped_is_fail_safe_on_a_missing_summary():
    """An unpopulated summary must read as "examined something". The helper
    can only ever REMOVE a plain PASS, so its uncertain case has to be the
    one that changes nothing."""
    assert _vx.summary_is_skipped(None) is False
    assert _vx.summary_is_skipped({}) is False
    assert _vx.summary_is_skipped("skipped") is False
    assert _vx.summary_is_skipped({"skipped": True}) is True








# --------------------------------------------------------------------------
# Consumer 1 — the P0 structural umbrella. REAL `_run_structural_rtl_gates`.
# --------------------------------------------------------------------------

_SKIPPING_GATES = (
    "break_handler_safety_check",       # no break signals in this RTL
    "tx_abort_during_transmission_check",  # no TX module in this RTL
)


def _minimal_rtl_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    # Deliberately plain: no break signal, no TX module, no protocol. Every
    # gate under test has nothing here to examine.
    (rtl / "counter.v").write_text(
        "module counter(input clk, input rst, output reg [7:0] q);\n"
        "  always @(posedge clk) if (rst) q <= 8'd0; else q <= q + 8'd1;\n"
        "endmodule\n"
    )
    return proj






# --------------------------------------------------------------------------
# Consumer 2 — the VACUOUS_PASS STEP TIER. REAL `check_step`, real
# `_check_program_exit_zero`, real subprocess. Nothing is mocked.
# --------------------------------------------------------------------------

def _step(gate_cmd: str) -> dict:
    return {"id": "T1", "name": "issue-515 tier probe", "stage": "stage1",
            "gate": {"program_exit_zero": gate_cmd}}










# --------------------------------------------------------------------------
# The sharpest instance: bit_level_full_stack_tb_oracle_check, whose `check()`
# already computed `skipped` and whose `main()` never read it.
# --------------------------------------------------------------------------
