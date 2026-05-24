#!/usr/bin/env python3
"""Tests for backlog_sanitize_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "programs" / "backlog_sanitize_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_pass_clean_yaml(tmp_path):
    bf = tmp_path / "backlog.yaml"
    bf.write_text("type: enhancement\ncomponent: skill:spec-to-rtl\ntitle: Add SPI timeout\npattern: SPI clock recovery should handle jitter\nplugin_version: '0.115'\n")
    r = _run(["--file", str(bf)])
    assert r.returncode == 0

def test_empty_dir(tmp_path):
    r = _run(["--dir", str(tmp_path)])
    assert r.returncode == 0
