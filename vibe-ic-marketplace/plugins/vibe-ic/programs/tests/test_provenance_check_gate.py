#!/usr/bin/env python3
"""Tests for provenance_check.py."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "provenance_check.py"

def _run(*args):
    return subprocess.run([sys.executable, str(PROG)] + list(args),
                          capture_output=True, text=True)

def test_help():
    r = _run("--help")
    assert r.returncode == 0

def test_no_provenance_file(tmp_path):
    r = _run(str(tmp_path), "--require-entries", "0")
    assert r.returncode == 2

def test_with_provenance(tmp_path):
    entries = [{"tool": "eda_lint", "output": "reports/lint.json", "sha256": "abc123", "step": "lint"}]
    (tmp_path / "provenance.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "lint.json").write_text("{}")
    r = _run(str(tmp_path), "--output", "reports/lint.json", "--tool", "eda_lint")
    assert r.returncode == 1
