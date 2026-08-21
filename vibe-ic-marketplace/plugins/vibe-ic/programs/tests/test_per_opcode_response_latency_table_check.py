#!/usr/bin/env python3
"""Tests for per_opcode_response_latency_table_check.py (LL-33)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "per_opcode_response_latency_table_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _put_doc(tmp_path: Path, name: str, body: str):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(body)


def _put_l(tmp_path: Path, data: dict, name: str = "L11_OTP_CONTENT.json"):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(json.dumps(data))


# 1. Silent-skip: no docs.
def test_no_docs_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


# 2. Silent-skip: docs without RSP_xx table.
def test_no_rsp_table_silent_pass(tmp_path):
    _put_doc(tmp_path, "spec.txt", "Some prose. No latency table.")
    r = _run(tmp_path)
    assert r.returncode == 0


# 3. Silent-skip: doc has only 2 RSP entries (below trigger threshold of 3).
def test_below_trigger_threshold_silent_pass(tmp_path):
    _put_doc(tmp_path, "tiny.txt", "RSP_70[91] RSP_74[91]")
    r = _run(tmp_path)
    assert r.returncode == 0


# 4. PASS — table in doc, response_latency_ticks in L11.
def test_doc_and_l11_aligned_pass(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "RSP_70[91] RSP_74[91] RSP_78[91] RSP_E0[15917]")
    _put_l(tmp_path, {
        "response_latency_ticks": {
            "0x70": 91, "0x74": 91, "0x78": 91, "0xE0": 15917,
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


# 5. FAIL — table in doc but no L doc has any latency entry.
def test_no_l_table_fails(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "RSP_70[91] RSP_74[91] RSP_78[91]")
    _put_l(tmp_path, {"some_other_key": [1, 2]})
    r = _run(tmp_path)
    assert r.returncode == 1


# 6. FAIL — coverage <75% (only 1 of 4 opcodes covered).
def test_low_coverage_fails(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "RSP_70[91] RSP_74[91] RSP_78[91] RSP_E0[15917]")
    _put_l(tmp_path, {
        "response_latency_ticks": {"0x70": 91}
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "coverage" in r.stdout.lower() or "75%" in r.stdout


# 7. Waiver allows missing table.
def test_waiver_allows(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "RSP_70[91] RSP_74[91] RSP_78[91]")
    _put_l(tmp_path, {})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "rsp_latency_table_extracted_elsewhere":
            "Latency lives in dedicated L8 protocol_specific_timing block",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# 8. Per-entry shape: command_table list with response_latency_ticks each.
def test_per_entry_command_table_pass(tmp_path):
    _put_doc(tmp_path, "20230103-3.txt",
             "RSP_70[91] RSP_74[91] RSP_78[91]")
    _put_l(tmp_path, {
        "command_table": [
            {"opcode": "0x70", "response_latency_ticks": 91},
            {"opcode": "0x74", "response_latency_ticks": 91},
            {"opcode": "0x78", "response_latency_ticks": 91},
        ]
    }, name="L3_PROTOCOL.json")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
