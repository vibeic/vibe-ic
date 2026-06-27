#!/usr/bin/env python3
"""Tests for vibe_ic_entry_guard.py.

Covers:
- PASS when any runner evidence file is present.
- FAIL when no evidence is present.
- --allow-direct-agent turns FAIL into WARN rc=0.
- --strict rc=1 vs default rc=0 on FAIL.
- missing project dir returns rc=2.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GUARD = PROGRAMS / "vibe_ic_entry_guard.py"


def run(args, cwd=None):
    cp = subprocess.run([sys.executable, str(GUARD), *args],
                        capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return cp.returncode, cp.stdout, cp.stderr


def test_pass_with_orchestrator_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        (rep / "vibe_ic_one_shot.json").write_text(json.dumps({"verdict": "PASS"}))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0
        assert "PASS" in out


def test_pass_with_phase1_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports"
        rep.mkdir()
        (rep / "phase1_one_shot.json").write_text(json.dumps({"verdict": "PASS"}))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0


def test_pass_with_l1_datasheet():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "x"}))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0


def test_fail_strict():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1
        assert "no Vibe-IC runner evidence" in err


def test_fail_default_warn_rc0():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td)])
        assert rc == 0
        assert "FAIL" in err


def test_allow_direct_agent_warn_rc0():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td), "--allow-direct-agent"])
        assert rc == 0
        assert "WARN(direct-agent)" in out


def test_missing_dir_rc2():
    rc, out, err = run(["/tmp/nonexistent_vibe_ic_entry_guard_test"])
    assert rc == 2


def test_json_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        json_out = td / "report.json"
        rc, out, err = run([str(td), "--strict", "--json", str(json_out)])
        assert rc == 1
        data = json.loads(json_out.read_text())
        assert data["gate"] == "vibe_ic_entry_guard"
        assert data["verdict"] == "FAIL"
        assert data["findings_count"] == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
