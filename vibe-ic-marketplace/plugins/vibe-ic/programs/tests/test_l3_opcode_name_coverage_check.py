#!/usr/bin/env python3
"""Tests for l3_opcode_name_coverage_check.py.

Pins the #51-Fix-6 false-PASS closure: L3.opcodes with ANY placeholder
name (ratio > 0%) must FAIL — structural presence (len > 0) is not
enough. Verdict tiers:
  * every opcode real-named            → PASS (rc 0)
  * any placeholder name               → FAIL (rc 1)
  * empty opcodes (no protocol)        → VACUOUS_PASS (rc 0)
  * L3 file absent                     → SILENT_SKIP (rc 2)
  * project dir absent                 → rc 2
RESERVED is NOT a placeholder (#51 Fix 12).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "l3_opcode_name_coverage_check.py"

_spec = importlib.util.spec_from_file_location(
    "l3_opcode_name_coverage_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _gen_dir(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_l3(project: Path, opcodes):
    d = _gen_dir(project)
    (d / "L3_CMD_PROTOCOL.json").write_text(json.dumps({"opcodes": opcodes}))


def _run(project: Path):
    out = project / "l3.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


# ----------------------------------------------------------------------
# PASS — every opcode carries a real name
# ----------------------------------------------------------------------
def test_pass_all_named(tmp_path):
    _write_l3(tmp_path, [
        {"hex": "0x01", "name": "READ"},
        {"hex": "0x02", "name": "WRITE"},
        {"hex": "0x03", "name": "RESERVED"},  # NOT a placeholder
    ])
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["placeholders"] == 0


# ----------------------------------------------------------------------
# FAIL — the v1.6.130 half-placeholder defect
# ----------------------------------------------------------------------
def test_fail_placeholder_names(tmp_path):
    _write_l3(tmp_path, [
        {"hex": "0x01", "name": "READ"},
        {"hex": "0x02", "name": "OPCODE_NAME_UNKNOWN"},
        {"hex": "0x03", "name": "WRITE"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert rep["placeholders"] == 1
    assert "0x02" in rep["placeholder_hexes"]


def test_fail_on_null_and_empty_names(tmp_path):
    _write_l3(tmp_path, [
        {"hex": "0x01", "name": None},
        {"hex": "0x02", "name": ""},
        {"hex": "0x03", "name": "TODO"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert rep["placeholders"] == 3


# ----------------------------------------------------------------------
# VACUOUS_PASS — no opcodes (non-protocol IP)
# ----------------------------------------------------------------------
def test_vacuous_pass_empty_opcodes(tmp_path):
    _write_l3(tmp_path, [])
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["total"] == 0


# ----------------------------------------------------------------------
# Edge — L3 file absent → SILENT_SKIP rc 2
# ----------------------------------------------------------------------
def test_silent_skip_when_l3_absent(tmp_path):
    _gen_dir(tmp_path)  # dir exists but no L3 file
    rc, _ = _run(tmp_path)
    assert rc == 2


def test_rc2_when_project_dir_absent(tmp_path):
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2
