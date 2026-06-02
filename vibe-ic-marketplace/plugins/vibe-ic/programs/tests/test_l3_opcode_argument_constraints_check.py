#!/usr/bin/env python3
"""Tests for l3_opcode_argument_constraints_check.py (Wave 37 / A3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l3_opcode_argument_constraints_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_project(tmp_path: Path, l3_obj=None,
                  doc_text="讀取長度+位址不得超過 0x80") -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "input_doc" / "CMD整理.txt").write_text(doc_text)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    if l3_obj is not None:
        (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
            json.dumps(l3_obj)
        )
    return proj


def test_skip_when_no_constraint_mention(tmp_path):
    proj = _make_project(tmp_path, l3_obj=None,
                         doc_text="A normal opcode description.")
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_constraint_but_l3_missing(tmp_path):
    proj = _make_project(tmp_path, l3_obj=None)
    r = _run(proj)
    assert r.returncode == 1
    assert "L3_CMD_PROTOCOL.json missing" in r.stdout


def test_fail_when_l3_no_constraints(tmp_path):
    proj = _make_project(tmp_path, l3_obj={
        "opcodes": [{"hex": "0xE0", "name": "WRITE_OTP"}]
    })
    r = _run(proj)
    assert r.returncode == 1
    assert "argument_constraints" in r.stdout or "constraint" in r.stdout


def test_pass_with_argument_constraints_array(tmp_path):
    proj = _make_project(tmp_path, l3_obj={
        "opcodes": [{
            "hex": "0xE0",
            "argument_constraints": [
                {"name": "addr", "max_hex": "0x7F",
                 "evidence": "CMD整理:14"},
                {"name": "len", "max_hex": "0x1F",
                 "evidence": "CMD整理:13"},
            ],
        }]
    })
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_with_addr_max_field(tmp_path):
    proj = _make_project(tmp_path, l3_obj={
        "opcodes": [{
            "hex": "0xE0",
            "addr_max": "0x7F",
            "len_max": "0x1F",
        }]
    })
    r = _run(proj)
    assert r.returncode == 0


def test_english_constraint_pattern(tmp_path):
    proj = _make_project(tmp_path, l3_obj=None,
                         doc_text="The address must not exceed 0x7F.")
    r = _run(proj)
    # constraint mention exists but no L3 → FAIL
    assert r.returncode == 1
