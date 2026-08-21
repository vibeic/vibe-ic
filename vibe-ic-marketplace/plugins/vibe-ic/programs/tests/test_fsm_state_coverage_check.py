#!/usr/bin/env python3
"""Tests for fsm_state_coverage_check.py (Wave 13)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = (Path(__file__).resolve().parent.parent
        / "fsm_state_coverage_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_enum_rtl(state_names: list[str]) -> str:
    body = ",\n        ".join(state_names)
    return (
        "module main_fsm(input logic clk);\n"
        f"  typedef enum logic [3:0] {{\n        {body}\n    }} st_t;\n"
        "  st_t state;\n"
        "endmodule\n"
    )


def _proj(tmp_path: Path,
          doc_states: list[str] | None,
          rtl_states: list[str] | None,
          waivers: dict | None = None,
          use_l11: bool = False) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if doc_states is not None:
        if use_l11:
            l11 = {
                "doc_id": "L11",
                "behavioral_sequences": [
                    {"name": "seq1", "state_sequence": doc_states}
                ],
            }
            (gd / "L11_TEST_CASES.json").write_text(json.dumps(l11))
        else:
            l9 = {
                "doc_id": "L9",
                "fsm_states": doc_states,
            }
            (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    if rtl_states is not None:
        (rtl / "main_fsm.sv").write_text(_make_enum_rtl(rtl_states))
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def test_full_coverage_pass(tmp_path):
    states = [
        "S_IDLE", "S_RX_FIRST_BIT", "S_RX_BIT_COLLECT", "S_RX_DONE_PROC",
        "S_RX_VALIDATE_CRC", "S_DISPATCH", "S_OTP_FETCH_REQ",
        "S_OTP_FETCH_WAIT", "S_TX_BUILD_PAYLOAD", "S_TX_CRC_FEED",
        "S_TX_CRC_WAIT", "S_FRAME_END",
    ]
    proj = _proj(tmp_path, states, states)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_missing_state_fail(tmp_path):
    doc = [
        "S_IDLE", "S_RX", "S_DISPATCH", "S_TX",
        "S_OTP_FETCH", "S_FRAME_END", "S_VALIDATE",
        "S_BUILD_PAYLOAD", "S_CRC_FEED", "S_CRC_WAIT",
        "S_SEND_TEST_REPLY", "S_IDENTIFY",
    ]
    rtl = doc[:10]  # missing 2: S_SEND_TEST_REPLY, S_IDENTIFY
    proj = _proj(tmp_path, doc, rtl)
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FSM_STATE_COVERAGE_MISSING" in r.stdout


def test_normalize_prefix_pass(tmp_path):
    """Doc says ``IDLE``, ``DISPATCH``; RTL says ``S_IDLE``,
    ``S_DISPATCH`` — must match after prefix strip."""
    doc = ["IDLE", "DISPATCH", "TX", "RX"]
    rtl = ["S_IDLE", "S_DISPATCH", "S_TX", "S_RX"]
    proj = _proj(tmp_path, doc, rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_extra_rtl_states_warn(tmp_path):
    doc = ["S_IDLE", "S_DISPATCH"]
    rtl = [
        "S_IDLE", "S_DISPATCH", "S_EXTRA1", "S_EXTRA2", "S_EXTRA3",
        "S_EXTRA4", "S_EXTRA5",
    ]
    proj = _proj(tmp_path, doc, rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" in r.stdout or "OVER_IMPLEMENTATION" in r.stdout


def test_no_doc_states_skip(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L9.json").write_text(
        json.dumps({"doc_id": "L9"}))
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "main_fsm.sv").write_text(
        _make_enum_rtl(["S_IDLE", "S_DISPATCH"]))
    r = _run(proj)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    doc = [
        "S_IDLE", "S_DISPATCH", "S_TX", "S_RX",
        "S_OTP_FETCH", "S_FRAME_END",
    ]
    rtl = ["S_IDLE", "S_DISPATCH"]
    proj = _proj(
        tmp_path, doc, rtl,
        waivers={
            "fsm_state_intentionally_collapsed": (
                "States S_TX/S_RX/S_OTP_FETCH/S_FRAME_END are "
                "intentionally collapsed onto S_DISPATCH per JIRA "
                "IC-9902 — pending architecture re-review next sprint."
            )
        },
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WAIVER" in r.stdout


def test_l11_state_sequence_pass(tmp_path):
    """L11.behavioral_sequences[].state_sequence is a synonym source."""
    states = ["S_IDLE", "S_RX", "S_DISPATCH", "S_TX"]
    proj = _proj(tmp_path, states, states, use_l11=True)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_help_works():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
