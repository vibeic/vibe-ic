#!/usr/bin/env python3
"""Tests for crc_vector_gen.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "crc_vector_gen.py"

def _run(*extra):
    return subprocess.run(
        [sys.executable, str(PROG)] + list(extra),
        capture_output=True, text=True)


def test_preset_crc8_ccitt(tmp_path):
    """CRC-8-CCITT preset generates vectors."""
    r = _run("--preset", "crc8_CCITT", "--out-dir", str(tmp_path), "--count", "10")
    assert r.returncode == 0


def test_missing_outdir(tmp_path):
    """Missing --out-dir errors."""
    r = _run("--preset", "crc8_CCITT")
    assert r.returncode != 0
