#!/usr/bin/env python3
"""Tests for l3_opcode_response_template_check.py (Wave 37 / A2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l3_opcode_response_template_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_project(tmp_path: Path, l3_obj=None,
                  override_doc_name="opcode_detail.txt",
                  override_text="response: 73 80 00 F8 00 DC") -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    (proj / "phase1" / "input_doc" / override_doc_name).write_text(override_text)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    if l3_obj is not None:
        (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
            json.dumps(l3_obj)
        )
    return proj


def test_skip_when_no_override_doc(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_override_doc_has_no_byte_pattern(tmp_path):
    proj = _make_project(tmp_path, l3_obj=None,
                         override_text="just a paragraph, no hex bytes here")
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_override_doc_but_l3_missing(tmp_path):
    proj = _make_project(tmp_path, l3_obj=None)
    r = _run(proj)
    assert r.returncode == 1
    assert "L3_CMD_PROTOCOL.json missing" in r.stdout


def test_fail_when_l3_no_template(tmp_path):
    proj = _make_project(tmp_path, l3_obj={
        "opcodes": [{"hex": "0x73", "name": "GET_STATE_RESP"}]
    })
    r = _run(proj)
    assert r.returncode == 1
    assert "response_payload_template" in r.stdout


def test_fail_when_template_unstructured(tmp_path):
    proj = _make_project(tmp_path, l3_obj={
        "opcodes": [{
            "hex": "0x73",
            "response_payload_template": ["73", "XX", "00", "F8"],
        }]
    })
    r = _run(proj)
    assert r.returncode == 1
    assert "byte_offset" in r.stdout


def test_pass_with_structured_template(tmp_path):
    proj = _make_project(tmp_path, l3_obj={
        "opcodes": [{
            "hex": "0x73",
            "response_payload_template": [
                {"byte_offset": 0, "value": "0x73"},
                {"byte_offset": 1, "source": "state_register"},
                {"byte_offset": 2, "value": "0x00"},
                {"byte_offset": 3, "value": "0xF8"},
            ],
        }]
    })
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_pass_with_chinese_filename(tmp_path):
    proj = _make_project(tmp_path,
                         override_doc_name="70指令控制說明.txt",
                         l3_obj={"opcodes": [{
                             "hex": "0x73",
                             "response_payload_template": [
                                 {"byte_offset": 0, "value": "0x73"},
                             ]}]})
    r = _run(proj)
    assert r.returncode == 0
