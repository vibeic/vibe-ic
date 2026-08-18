"""Tests for rtl_precheck_gate.py — pre-burn RTL auditor aggregator.

Motivation for this gate and its tests: v0.64 shipped
`timer_freeze_after_state_check` which could have statically flagged
the wake_ctrl bug, but the checker was never called during the burn
flow. v0.66 wires it (and 5 other static auditors) into a single
gate that the FPGA burn tool invokes BEFORE writing the SOF to the
board. These tests lock in that aggregation behaviour.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "rtl_precheck_gate.py"
assert SCRIPT.exists(), f"script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import rtl_precheck_gate as gate  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _clean_rtl(d: Path) -> None:
    """Write a small RTL tree that every auditor will PASS. No inouts,
    no counters, no dispatch, no OTP — just a trivial module."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "trivial.v").write_text("""\
module trivial (
    input  wire clk,
    input  wire porb,
    output reg  q
);
    always @(posedge clk or negedge porb) begin
        if (!porb) q <= 1'b0;
        else       q <= ~q;
    end
endmodule
""")


def _buggy_wake_ctrl(d: Path) -> None:
    """Write a module that timer_freeze_after_state_check will flag:
    has `input awake` AND a self-incrementing cnt with no `else if
    (awake) cnt <= 0;` freeze branch. Mirrors v052 wake_ctrl.v."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "wake_ctrl.v").write_text("""\
module wake_ctrl (
    input  wire       clk,
    input  wire       porb,
    input  wire       cmd_valid,
    input  wire [7:0] cmd_op,
    input  wire       awake,
    output reg        wake_req
);
    reg [23:0] cnt;
    always @(posedge clk or negedge porb) begin
        if (!porb) begin
            cnt <= 24'd0;
            wake_req <= 1'b0;
        end else begin
            wake_req <= 1'b0;
            if (cmd_valid) begin
                cnt <= 24'd0;
                if (!awake && cmd_op != 8'h74) wake_req <= 1'b1;
            end else begin
                if (cnt == 24'd25000) begin
                    wake_req <= 1'b1;
                    cnt <= 24'd0;
                end else cnt <= cnt + 24'd1;
            end
        end
    end
endmodule
""")


# ---------------------------------------------------------------------------
# Python API tests (direct call to run_gate)
# ---------------------------------------------------------------------------
def test_run_gate_clean_rtl_all_pass(tmp_path):
    """A clean minimal RTL tree passes every auditor."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    _clean_rtl(rtl)
    scripts = SCRIPT.parent
    report = gate.run_gate(rtl_dir=rtl, scripts_dir=scripts)
    assert report["summary"]["overall_pass"], (
        f"clean RTL should pass; got {report['summary']}"
    )
    assert report["summary"]["failed"] == 0
    # L12 auditor skipped because no --l12-json provided and it's non-required
    l12 = [a for a in report["auditors"]
           if a["name"] == "l12_sequence_implementation_check"][0]
    assert l12["skipped"] and l12["passed"]


def test_run_gate_catches_wake_ctrl_bug(tmp_path):
    """The v052 wake_ctrl bug MUST be caught by the gate. This is the
    regression test for the v0.66 motivating issue."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    _buggy_wake_ctrl(rtl)
    report = gate.run_gate(rtl_dir=rtl, scripts_dir=SCRIPT.parent)
    assert not report["summary"]["overall_pass"]
    tfs = [a for a in report["auditors"]
           if a["name"] == "timer_freeze_after_state_check"][0]
    assert not tfs["passed"]
    assert tfs["exit_code"] == 1


def test_run_gate_skip_flag(tmp_path):
    """--skip removes an auditor from the run; skipped ones count as PASS."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    _buggy_wake_ctrl(rtl)  # would fail timer_freeze_after_state_check
    report = gate.run_gate(
        rtl_dir=rtl, scripts_dir=SCRIPT.parent,
        skip=["timer_freeze_after_state_check"],
    )
    assert report["summary"]["overall_pass"], (
        "skipping the failing auditor should flip overall to PASS"
    )
    tfs = [a for a in report["auditors"]
           if a["name"] == "timer_freeze_after_state_check"][0]
    assert tfs["skipped"] and tfs["passed"]
    assert tfs["skip_reason"] == "--skip"


def test_run_gate_missing_rtl_dir_raises():
    with pytest.raises(FileNotFoundError):
        gate.run_gate(
            rtl_dir=Path("/does/not/exist/xyz"),
            scripts_dir=SCRIPT.parent,
        )


# ---------------------------------------------------------------------------
# CLI tests (main() + exit codes)
# ---------------------------------------------------------------------------
def test_cli_clean_rtl_exit_0(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    _clean_rtl(rtl)
    rc = gate.main(["--rtl-dir", str(rtl)])
    assert rc == 0


def test_cli_buggy_rtl_exit_1(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    _buggy_wake_ctrl(rtl)
    rc = gate.main(["--rtl-dir", str(rtl)])
    assert rc == 1


def test_cli_invalid_rtl_exit_2(tmp_path):
    rc = gate.main(["--rtl-dir", str(tmp_path / "does-not-exist")])
    assert rc == 2


def test_cli_unknown_skip_exit_2(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    _clean_rtl(rtl)
    rc = gate.main([
        "--rtl-dir", str(rtl),
        "--skip", "not_a_real_auditor",
    ])
    assert rc == 2


def test_cli_writes_json_report(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    _buggy_wake_ctrl(rtl)
    out = tmp_path / "report.json"
    rc = gate.main(["--rtl-dir", str(rtl), "--json", str(out)])
    assert rc == 1
    d = json.loads(out.read_text())
    assert d["summary"]["overall_pass"] is False
    assert any(
        a["name"] == "timer_freeze_after_state_check" and not a["passed"]
        for a in d["auditors"]
    )


def test_cli_help_exits_cleanly():
    with pytest.raises(SystemExit) as e:
        gate.main(["--help"])
    assert e.value.code == 0
