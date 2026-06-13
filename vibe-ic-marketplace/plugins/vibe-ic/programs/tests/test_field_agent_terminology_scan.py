#!/usr/bin/env python3
"""Tests for field_agent_terminology_scan.py — enforce 'field agent',
reject 'debug agent' (chip-AGNOSTIC)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "field_agent_terminology_scan.py"
_spec = importlib.util.spec_from_file_location("field_agent_terminology_scan", _PROG)
fats = importlib.util.module_from_spec(_spec)
sys.modules["field_agent_terminology_scan"] = fats
_spec.loader.exec_module(fats)


# ---- PASS cases ---------------------------------------------------------
def test_pass_canonical_term():
    assert fats.main(["--text", "請 field agent 在實機 benchmark 驗證"]) == 0


def test_pass_no_role_mention():
    assert fats.main(["--text", "Bumped patch version and pushed to main."]) == 0


def test_pass_debugging_word_is_not_debug_agent():
    # 'debugging agentless flow' must NOT match (\bdebug\s+agent\b).
    assert fats.main(["--text", "the debugging step ran; agentless mode off"]) == 0


# ---- FAIL cases ---------------------------------------------------------
def test_fail_debug_agent_lowercase():
    assert fats.main(["--text", "ask the debug agent to verify on hardware"]) == 1


def test_fail_debug_agent_titlecase():
    assert fats.main(["--text", "Debug Agent will pick this up next tick"]) == 1


def test_fail_debug_agent_multispace():
    assert fats.main(["--text", "the debug   agent files issues"]) == 1


# ---- file scan + JSON + edge --------------------------------------------
def test_file_scan_reports_line(tmp_path):
    f = tmp_path / "comment.md"
    f.write_text(
        "Core agent 已推送修復：abc1234\n"
        "請 debug agent 驗證\n"          # offender on line 2
    )
    out = tmp_path / "r.json"
    rc = fats.main([str(f), "--json", str(out)])
    assert rc == 1
    rep = json.loads(out.read_text())
    assert rep["passed"] is False
    assert rep["forbidden_hits"][0]["line_no"] == 2


def test_canonical_presence_advisory(tmp_path):
    f = tmp_path / "c.md"
    f.write_text("請 field agent 在實機 benchmark 驗證\n")
    out = tmp_path / "r.json"
    assert fats.main([str(f), "--json", str(out)]) == 0
    rep = json.loads(out.read_text())
    assert rep["canonical_present"] is True


def test_missing_file_is_honest_error(tmp_path):
    assert fats.main([str(tmp_path / "nope.md")]) == 2


def test_empty_input_is_vacuous_not_verified(tmp_path):
    f = tmp_path / "empty.md"
    f.write_text("\n   \n")
    out = tmp_path / "r.json"
    rc = fats.main([str(f), "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["vacuous"] is True
    assert rep["scanned_lines"] == 0


def test_no_args_is_error():
    assert fats.main([]) == 2
