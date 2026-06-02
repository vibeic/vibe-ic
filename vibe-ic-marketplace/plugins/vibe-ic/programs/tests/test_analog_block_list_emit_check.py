#!/usr/bin/env python3
"""Tests for analog_block_list_emit_check.py.

Covers:
  - well-formed list → PASS
  - block_count mismatch → FAIL
  - missing name/type/spec_file → FAIL
  - spec_file not ending in spec.json → FAIL
  - absent list (project mode) → VACUOUS_PASS
  - garbage JSON → FAIL (honest)
  - --project spec_file-on-disk resolution PASS / FAIL
  - missing file (file mode) → rc=2 honest
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent /
        "analog_block_list_emit_check.py")


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), *args],
        capture_output=True, text=True,
    )


def _well_formed() -> dict:
    return {
        "blocks": [
            {"name": "ldo_1v8", "type": "LDO",
             "spec_file": "analog/ldo_1v8/spec.json"},
            {"name": "por", "type": "POR",
             "spec_file": "analog/por/spec.json"},
        ],
        "block_count": 2,
    }


def test_well_formed_pass(tmp_path):
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(_well_formed()))
    r = _run(str(bl))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_block_count_mismatch_fail(tmp_path):
    d = _well_formed()
    d["block_count"] = 5  # wrong
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(d))
    r = _run(str(bl))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "BLOCK_COUNT_MISMATCH" in r.stdout


def test_missing_name_fail(tmp_path):
    d = _well_formed()
    del d["blocks"][0]["name"]
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(d))
    r = _run(str(bl))
    assert r.returncode == 1, r.stdout + r.stderr


def test_missing_type_fail(tmp_path):
    d = _well_formed()
    d["blocks"][0]["type"] = ""
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(d))
    r = _run(str(bl))
    assert r.returncode == 1, r.stdout + r.stderr


def test_spec_file_wrong_suffix_fail(tmp_path):
    d = _well_formed()
    d["blocks"][0]["spec_file"] = "analog/ldo_1v8/topology.md"
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(d))
    r = _run(str(bl))
    assert r.returncode == 1, r.stdout + r.stderr


def test_absent_list_project_mode_vacuous_pass(tmp_path):
    """No analog_block_list.json under project → VACUOUS_PASS."""
    (tmp_path / "analog").mkdir()
    r = _run(str(tmp_path), "--project")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VACUOUS_PASS" in r.stdout


def test_garbage_json_fails_honestly(tmp_path):
    bl = tmp_path / "bl.json"
    bl.write_text("{ not valid json")
    r = _run(str(bl))
    assert r.returncode == 1, r.stdout + r.stderr


def test_missing_file_mode_rc2(tmp_path):
    r = _run(str(tmp_path / "nope.json"))
    assert r.returncode == 2, r.stdout + r.stderr


def test_project_specfile_on_disk_pass(tmp_path):
    """--project: every spec_file resolves to a real file → PASS."""
    analog = tmp_path / "analog"
    (analog / "ldo_1v8").mkdir(parents=True)
    (analog / "por").mkdir(parents=True)
    (analog / "ldo_1v8" / "spec.json").write_text("{}")
    (analog / "por" / "spec.json").write_text("{}")
    (analog / "analog_block_list.json").write_text(
        json.dumps(_well_formed()))
    r = _run(str(tmp_path), "--project")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_project_specfile_missing_on_disk_fail(tmp_path):
    """--project: a spec_file that does not resolve → FAIL."""
    analog = tmp_path / "analog"
    (analog / "ldo_1v8").mkdir(parents=True)
    (analog / "ldo_1v8" / "spec.json").write_text("{}")
    # 'por' spec.json deliberately NOT created.
    (analog / "analog_block_list.json").write_text(
        json.dumps(_well_formed()))
    r = _run(str(tmp_path), "--project")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "does not resolve" in r.stdout


def test_json_report_written(tmp_path):
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(_well_formed()))
    out = tmp_path / "rep.json"
    r = _run(str(bl), "--json", str(out))
    assert r.returncode == 0
    rep = json.loads(out.read_text())
    assert rep["status"] == "PASS"
    assert rep["block_count"] == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
