#!/usr/bin/env python3
"""Tests for layer_extension_presence_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "layer_extension_presence_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_empty_docs(tmp_path):
    # Empty docs against the default class (any-ic) carry no floor, so the
    # gate exits 0 with `"pass": true` and no findings.
    r = _run([str(tmp_path)])
    assert r.returncode == 0
    assert '"pass": true' in r.stdout
    assert '"findings": []' in r.stdout
