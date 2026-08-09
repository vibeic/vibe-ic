#!/usr/bin/env python3
"""Tests for pre_awake_silence_check.py"""
from __future__ import annotations
import json
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "pre_awake_silence_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_rtl(tmp_path):
    # #521 — RTL with no wake/sleep signal at all is VACUOUS (rc 2), not a
    # PASS over wake gating that this design does not have.
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run(["--rtl-dir", str(tmp_path)]); assert r.returncode == 2


# ---------------------------------------------------------------------------
# The clear-path audit used to draw its subject list from `awake_clear_paths`,
# whose keys are born of `setdefault(sig, []).append(...)`. A signal with ZERO
# clear paths was therefore never a key and never examined, so the gate's
# `len(paths) < 2` predicate could only ever observe len == 1 and NO_CLEAR_PATH
# was unreachable. These four fixtures pin both verdicts and both polarities.
# Synthetic RTL only — no design, PDK or part number anywhere.
# ---------------------------------------------------------------------------

_DISPATCH_BODY = """
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            resp <= 8'h00;
        end else if (cmd_valid) begin
            if (!{flag}) begin
                resp <= 8'h00;
            end else begin
                case (cmd_op)
                    8'h01: resp <= 8'hA1;
                    8'h02: resp <= 8'hA2;
                    8'h03: resp <= 8'hA3;
                    default: resp <= 8'hFF;
                endcase
            end
        end
    end
"""


def _module(flag: str, flag_writes: str) -> str:
    """A guarded opcode dispatcher plus whatever writes the caller wants.

    The `if (!<flag>)` guard is always present so NO_AWAKE_GUARD can never be
    the reason a fixture fails — the only verdict under test is the clear-path
    one.
    """
    return (
        "module dut (\n"
        "    input  wire       clk,\n"
        "    input  wire       rst_n,\n"
        "    input  wire [7:0] cmd_op,\n"
        "    input  wire       cmd_valid,\n"
        "    input  wire       idle_timeout,\n"
        "    output reg  [7:0] resp\n"
        ");\n"
        f"    reg {flag};\n"
        + _DISPATCH_BODY.format(flag=flag)
        + flag_writes
        + "endmodule\n"
    )


def _report(tmp_path: Path, source: str):
    (tmp_path / "dut.v").write_text(source)
    r = _run(["--rtl-dir", str(tmp_path)])
    return r, json.loads(r.stdout)


def _categories(report) -> list:
    return [f["category"] for f in report["findings"]]


def test_awake_flag_driven_awake_and_never_cleared_is_a_finding(tmp_path):
    """The missing verdict.

    `awake <= 1'b1` with no write of `awake <= 1'b0` anywhere: the device wakes
    and never returns to the non-awake state. Against the unfixed program this
    is rc 0 with `clear_paths: {}` and zero findings, because the signal never
    became a key of the clear-path store and so left the audit's subject list.
    """
    r, report = _report(tmp_path, _module("awake", """
    always @(posedge clk) begin
        if (cmd_valid && cmd_op == 8'h7F) begin
            awake <= 1'b1;
        end
    end
"""))
    assert r.returncode == 1
    assert report["summary"]["pass"] is False
    assert "NO_CLEAR_PATH" in _categories(report)
    # The verdict must rest on a measured zero, not on the signal's absence.
    assert report["summary"]["clear_paths"]["awake"] == []
    assert len(report["summary"]["enter_paths"]["awake"]) == 1
    assert report["summary"]["denominator"]["examined"] == 1
    # And it must name real evidence — the site that drives the flag awake.
    finding = next(f for f in report["findings"] if f["category"] == "NO_CLEAR_PATH")
    assert finding["file"].endswith("dut.v")
    assert finding["line"] > 0


def test_wake_write_under_sleep_polarity_is_not_counted_as_a_clear_path(tmp_path):
    """Same defect reached through the sleep-active-high polarity.

    Two `sleep_mode <= 1'b0` writes are two WAKE events and zero clear paths.
    The unfixed SLEEP_SET_RE alternation `(?:1'b1|1|1'd1)` let the bare `1`
    match the size field of `1'b0`, so both were banked as clear paths and the
    design scored "2 clear paths -> PASS" while having none.
    """
    r, report = _report(tmp_path, _module("sleep_mode", """
    always @(posedge clk) begin
        if (cmd_valid && cmd_op == 8'h7F) sleep_mode <= 1'b0;
        else if (!rst_n) sleep_mode <= 1'b0;
    end
"""))
    assert r.returncode == 1
    assert "NO_CLEAR_PATH" in _categories(report)
    assert report["summary"]["clear_paths"]["sleep_mode"] == []
    assert len(report["summary"]["enter_paths"]["sleep_mode"]) == 2


def test_two_clear_paths_still_pass(tmp_path):
    """The OTHER direction: the gate is not always-fail.

    Reset and idle-timeout both clear the flag, so there is nothing to report.
    Asserted as a NON-VACUOUS pass — a green rc 0 obtained by examining nothing
    would satisfy the exit code and prove nothing about the predicate.
    """
    r, report = _report(tmp_path, _module("awake", """
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            awake <= 1'b0;
        end else if (idle_timeout) begin
            awake <= 1'b0;
        end else if (cmd_valid && cmd_op == 8'h7F) begin
            awake <= 1'b1;
        end
    end
"""))
    assert r.returncode == 0
    assert report["summary"]["pass"] is True
    assert report["findings"] == []
    assert report["summary"].get("skipped") is not True
    assert report["summary"]["denominator"]["examined"] == 1
    assert len(report["summary"]["clear_paths"]["awake"]) == 2
    assert len(report["summary"]["enter_paths"]["awake"]) == 1


def test_single_clear_path_still_fails(tmp_path):
    """The pre-existing verdict is preserved, and still distinct from the new
    one — a fix that collapsed both into one category would erase the
    difference between "cleared once" and "never cleared"."""
    r, report = _report(tmp_path, _module("awake", """
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            awake <= 1'b0;
        end else if (cmd_valid && cmd_op == 8'h7F) begin
            awake <= 1'b1;
        end
    end
"""))
    assert r.returncode == 1
    assert _categories(report) == ["SINGLE_CLEAR_PATH"]
    assert len(report["summary"]["clear_paths"]["awake"]) == 1


def test_gate_is_monotonic_in_clear_path_count(tmp_path):
    """Zero clear paths must never score better than one.

    This is the property the unfixed program violated outright: with one clear
    path it exited 1, with none it exited 0.
    """
    writes = {
        0: "    always @(posedge clk) begin\n"
           "        if (cmd_valid) awake <= 1'b1;\n"
           "    end\n",
        1: "    always @(posedge clk) begin\n"
           "        if (!rst_n) awake <= 1'b0;\n"
           "        else if (cmd_valid) awake <= 1'b1;\n"
           "    end\n",
        2: "    always @(posedge clk) begin\n"
           "        if (!rst_n) awake <= 1'b0;\n"
           "        else if (idle_timeout) awake <= 1'b0;\n"
           "        else if (cmd_valid) awake <= 1'b1;\n"
           "    end\n",
    }
    rcs = {}
    for n, body in writes.items():
        d = tmp_path / f"n{n}"
        d.mkdir()
        rcs[n] = _report(d, _module("awake", body))[0].returncode
    assert rcs[0] == 1 and rcs[1] == 1 and rcs[2] == 0
    assert rcs[0] >= rcs[2], "fewer clear paths must never score better"
