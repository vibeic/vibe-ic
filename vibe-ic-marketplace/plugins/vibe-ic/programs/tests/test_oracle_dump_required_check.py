#!/usr/bin/env python3
"""Tests for oracle_dump_required_check.py (LL-22)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "oracle_dump_required_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def test_no_waivers_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no waivers.json" in r.stdout


def test_waivers_without_oracle_ref_passes(tmp_path):
    """Waivers exist but don't reference oracle_referenced_fix."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "frame_end_idle_reset_alternative": "...",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0


def test_oracle_ref_without_dump_fails(tmp_path):
    """waivers reference oracle_referenced_fix but no dump artifact → FAIL."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "oracle_referenced_fix": [{
            "opcode": "0xE6", "field": "tx_len",
            "spec": 22, "silicon": 18,
        }],
    }))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "no captured oracle dump" in r.stdout


def test_oracle_ref_with_json_dump_passes(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "oracle_referenced_fix": [{"opcode": "0xE6"}],
    }))
    oracle = tmp_path / "input" / "oracle"
    oracle.mkdir(parents=True)
    (oracle / "myproj_bytewise_dump.json").write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_oracle_ref_with_csv_dump_passes(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "oracle_referenced_fix": [{"opcode": "0xE6"}],
    }))
    oracle = tmp_path / "input" / "oracle"
    oracle.mkdir(parents=True)
    (oracle / "myproj_bytewise_dump.csv").write_text("byte0,byte1\n")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_oracle_ref_with_docs_oracle_dump_md_passes(tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps({
        "oracle_referenced_fix": [{"opcode": "0xE6"}],
    }))
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "oracle_dump.md").write_text("# Oracle bytewise dump")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_oracle_ref_unrelated_file_in_oracle_dir_fails(tmp_path):
    """A random README in input/oracle/ doesn't count — must contain
    `bytewise_dump` in the filename."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "oracle_referenced_fix": [{"opcode": "0xE6"}],
    }))
    oracle = tmp_path / "input" / "oracle"
    oracle.mkdir(parents=True)
    (oracle / "README.md").write_text("notes")
    r = _run(tmp_path)
    assert r.returncode == 1
