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
sys.path.insert(0, str(_PROGRAMS))

import _vacuous_exit as _vx  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)


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


def test_the_sentinel_is_the_token_the_flow_scans_for():
    assert _flow._stdout_signals_vacuous(
        f"{_vx.VACUOUS_STDOUT_SENTINEL} gate examined nothing") is True


def test_the_helper_never_emits_the_waiver_exit_code():
    """rc 3 is PASS_WITH_WAIVERS (#651) and belongs to a different gate
    family. The two conventions must not collide."""
    codes = {_vx.exit_code(p, s)
             for p in (True, False) for s in (True, False)}
    assert codes == {0, 1, 2}
    assert _flow._WAIVER_EXIT_CODE == 3
    assert _flow._WAIVER_EXIT_CODE not in codes


def test_the_vacuous_sentinel_is_not_the_waiver_sentinel():
    assert not _flow._stdout_signals_waiver(
        f"{_vx.VACUOUS_STDOUT_SENTINEL} gate examined nothing")


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


def test_p0_umbrella_requires_a_declared_absence_basis(tmp_path, monkeypatch):
    """#1978: a banner-only rc-2 is incomplete, not an unearned N/A."""
    proj = _minimal_rtl_project(tmp_path)
    monkeypatch.setattr(_flow, "_STRUCTURAL_RTL_GATES", _SKIPPING_GATES)
    records: list = []
    passed, _fails, _skips, _waivers = _flow._run_structural_rtl_gates(
        proj, records_out=records)
    assert passed is True
    by_name = {r["name"]: r for r in records}
    assert set(by_name) == set(_SKIPPING_GATES)
    for gate in _SKIPPING_GATES:
        rec = by_name[gate]
        assert rec["verdict"] == "INCOMPLETE", rec
        assert rec["reason_class"] == "EXECUTION_ERROR", rec
        assert rec["evidence"]["exit_code"] == _vx.RC_VACUOUS, rec
        assert rec["evidence"]["skip_kind"] == "input-missing", rec
    # and the umbrella's passed-gate count no longer counts them
    assert _flow._p0_passed_count(records) == 0


def test_p0_umbrella_still_records_a_real_pass_as_PASS(tmp_path, monkeypatch):
    """The paired half. If a gate that DOES examine the RTL also came back
    SKIP, the fix would have broken the gates instead of the accounting."""
    proj = _minimal_rtl_project(tmp_path)
    rtl = proj / "phase2" / "stage1" / "rtl"
    # A TX module with no break-driven abort — tx_abort has something to
    # examine here and finds it correct.
    (rtl / "tx_ser.v").write_text(
        "module tx_ser(input clk, input tx_start, output reg tx_done,\n"
        "              output reg tx_bit);\n"
        "  reg [1:0] state;\n"
        "  always @(posedge clk) begin\n"
        "    case (state)\n"
        "      2'd0: if (tx_start) state <= 2'd1;\n"
        "      2'd1: begin tx_bit <= 1'b1; state <= 2'd2; end\n"
        "      2'd2: begin tx_done <= 1'b1; state <= 2'd0; end\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    monkeypatch.setattr(_flow, "_STRUCTURAL_RTL_GATES",
                        ("tx_abort_during_transmission_check",))
    records: list = []
    _flow._run_structural_rtl_gates(proj, records_out=records)
    rec = records[0]
    assert rec["verdict"] == "PASS", rec
    assert rec["evidence"]["exit_code"] == _vx.RC_PASS, rec
    assert _flow._p0_passed_count(records) == 1


# --------------------------------------------------------------------------
# Consumer 2 — the VACUOUS_PASS STEP TIER. REAL `check_step`, real
# `_check_program_exit_zero`, real subprocess. Nothing is mocked.
# --------------------------------------------------------------------------

def _step(gate_cmd: str) -> dict:
    return {"id": "T1", "name": "issue-515 tier probe", "stage": "stage1",
            "gate": {"program_exit_zero": gate_cmd}}


def test_check_step_routes_an_unclassified_skip_to_INCOMPLETE(tmp_path):
    proj = _minimal_rtl_project(tmp_path)
    result = _flow.check_step(
        proj, _step("break_handler_safety_check ."), waivers={})
    assert result.status == "INCOMPLETE", (result.status, result.reasons)
    assert any("INCOMPLETE" in r for r in result.reasons), result.reasons


def test_check_step_keeps_an_examined_gate_in_the_plain_PASS_tier(tmp_path):
    """The paired half at the step level: a gate that examined the design and
    found it correct must stay a plain PASS, not follow its neighbours into
    the vacuous tier."""
    proj = _minimal_rtl_project(tmp_path)
    (proj / "phase2" / "stage1" / "rtl" / "tx_ser.v").write_text(
        "module tx_ser(input clk, input tx_start, output reg tx_done);\n"
        "  reg [1:0] state;\n"
        "  always @(posedge clk) begin\n"
        "    case (state)\n"
        "      2'd0: if (tx_start) state <= 2'd1;\n"
        "      2'd1: begin tx_done <= 1'b1; state <= 2'd0; end\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    result = _flow.check_step(
        proj, _step("tx_abort_during_transmission_check ."), waivers={})
    assert result.status == "PASS", (result.status, result.reasons)


def test_check_step_still_FAILs_a_gate_that_found_a_violation(tmp_path):
    """Third leg: the vacuous tier must not have swallowed real failures."""
    proj = _minimal_rtl_project(tmp_path)
    (proj / "phase2" / "stage1" / "rtl" / "tx_ser.v").write_text(
        "module tx_ser(input clk, input rx_break, input tx_start,\n"
        "              output reg tx_done);\n"
        "  reg [1:0] state;\n"
        "  always @(posedge clk) begin\n"
        "    case (state)\n"
        "      2'd0: if (tx_start) state <= 2'd1;\n"
        "      S_TX_DATA: if (rx_break) state <= S_IDLE;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    result = _flow.check_step(
        proj, _step("tx_abort_during_transmission_check ."), waivers={})
    assert result.status == "FAIL", (result.status, result.reasons)


# --------------------------------------------------------------------------
# The sharpest instance: bit_level_full_stack_tb_oracle_check, whose `check()`
# already computed `skipped` and whose `main()` never read it.
# --------------------------------------------------------------------------

def test_bit_level_oracle_na_declaration_reaches_the_vacuous_tier(tmp_path):
    proj = tmp_path / "proj"
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "results.json").write_text(
        json.dumps({"command_oracle_applicable": False}))
    result = _flow.check_step(
        proj, _step("bit_level_full_stack_tb_oracle_check ."), waivers={})
    assert result.status == "VACUOUS_PASS", (result.status, result.reasons)
