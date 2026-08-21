#!/usr/bin/env python3
"""Tests for doc_consistency_no_unresolved_conflicts_check.py (Wave 37 / A4)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "doc_consistency_no_unresolved_conflicts_check.py")


def _run(project: Path, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True, env=env,
    )


def _make_project(tmp_path: Path, docs: dict) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "input_doc").mkdir(parents=True)
    for name, text in docs.items():
        (proj / "phase1" / "input_doc" / name).write_text(text)
    return proj


def test_skip_when_no_addr_limits(tmp_path):
    proj = _make_project(tmp_path, {"a.txt": "no relevant content"})
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_only_one_value(tmp_path):
    proj = _make_project(tmp_path, {
        "a.txt": "位址不得超過 0x7F",
        "b.txt": "address must not exceed 0x7F.",
    })
    r = _run(proj)
    # one distinct value -> not a conflict -> SKIP
    assert r.returncode == 2


def test_warn_when_conflict_unresolved(tmp_path):
    proj = _make_project(tmp_path, {
        "FRS.txt": "合法的地址範圍為 0x00 到 0x2E",
        "SDS.txt": "EEPROM address range from 00h to 0x5F is accessible",
        "CMD.txt": "讀取長度+位址不得超過 0x80",
    })
    r = _run(proj)
    # WARN behavior: exit 0 with [WARN] on stdout
    assert r.returncode == 0
    assert "[WARN]" in r.stdout


def test_pass_when_resolution_doc_present(tmp_path):
    proj = _make_project(tmp_path, {
        "FRS.txt": "合法的地址範圍為 0x00 到 0x2E",
        "SDS.txt": "address range from 00h to 0x5F",
    })
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "doc_consistency_conflicts.md").write_text(
        "# Conflicts\n\nADDR resolved via vendor erratum X.\n"
    )
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_blocking_env_makes_it_fail(tmp_path):
    proj = _make_project(tmp_path, {
        "FRS.txt": "合法的地址範圍為 0x00 到 0x2E",
        "CMD.txt": "讀取長度+位址不得超過 0x80",
    })
    env = os.environ.copy()
    env["VIBE_IC_DOC_CONFLICT_BLOCKING"] = "1"
    r = _run(proj, env=env)
    assert r.returncode == 1
