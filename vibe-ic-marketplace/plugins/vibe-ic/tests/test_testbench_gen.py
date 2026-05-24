#!/usr/bin/env python3
"""Tests for testbench_gen.py — emits unit TB skeletons from L10_TEST_CASES.

Wave 83 — coverage for previously untested wired program.

Cases:
  1. POSITIVE_PASS — L10 with two cases → two .v TBs in sim/tb/.
  2. POSITIVE_PASS_ALT_KEY — `cases` key fallback works (when `test_cases`
                              is absent).
  3. SKIP_NO_L10 — L10 missing → SKIP exit 0.
  4. POSITIVE_FAIL_BAD_JSON — malformed L10 → exit 1.
  5. EDGE_NON_DICT_ENTRIES — non-dict entries silently skipped.
  6. EDGE_OUTPUT_SCHEMA — emitted .v contains stimulus / expected comments
                           and `module <name>` declaration.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "programs" / \
    "testbench_gen.py"


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _write_l10(project: Path, body: dict | str) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    target = gd / "L10_TEST_CASES.json"
    if isinstance(body, str):
        target.write_text(body)
    else:
        target.write_text(json.dumps(body, indent=2))


def test_positive_pass_two_cases(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "test_cases": [
            {"name": "tb_get_id", "opcode_hex": "0x01",
             "expected": "byte0=0xA5", "kind": "happy_path",
             "polarity": "positive",
             "stimulus": "issue GET_ID frame"},
            {"name": "tb_bad_crc", "opcode_hex": "0x02",
             "expected": "no response", "kind": "negative",
             "polarity": "negative",
             "stimulus": "issue frame with bad CRC"},
        ]
    })
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] testbench_gen" in cp.stdout
    assert "2 unit TB" in cp.stdout
    tbs = list((project / "phase2" / "stage1" / "sim" / "tb").glob("*.v"))
    assert len(tbs) == 2
    names = sorted(t.name for t in tbs)
    assert names == ["tb_bad_crc.v", "tb_get_id.v"]


def test_positive_pass_alt_cases_key(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "cases": [
            {"name": "tb_alt", "opcode_hex": "0x10"},
        ]
    })
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "1 unit TB" in cp.stdout
    assert (project / "phase2" / "stage1" / "sim" / "tb" / "tb_alt.v").is_file()


def test_skip_no_l10(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP] testbench_gen" in cp.stdout


def test_positive_fail_bad_json(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, "{not valid")
    cp = _run([str(project)])
    assert cp.returncode == 1
    assert "[FAIL]" in cp.stdout


def test_edge_non_dict_entries_skipped(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "test_cases": [
            "string-not-a-case",
            42,
            {"name": "tb_only_dict", "opcode_hex": "0xAA"},
        ]
    })
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "1 unit TB" in cp.stdout
    files = list((project / "phase2" / "stage1" / "sim" / "tb").glob("*.v"))
    assert [f.name for f in files] == ["tb_only_dict.v"]


def test_edge_output_schema(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _write_l10(project, {
        "test_cases": [
            {"name": "tb_schema_check", "opcode_hex": "0x55",
             "expected": "byte0=0xZZ", "kind": "happy_path",
             "stimulus": "stimulate and observe"},
        ]
    })
    cp = _run([str(project), "--top", "test_chip_top"])
    assert cp.returncode == 0
    text = (project / "phase2" / "stage1" / "sim" / "tb" / "tb_schema_check.v").read_text()
    assert "module tb_schema_check" in text
    assert "stimulate and observe" in text
    assert "byte0=0xZZ" in text
    assert "test_chip_top" in text  # commented dut instantiation
