#!/usr/bin/env python3
"""Tests for pad_drive_high_active_check.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest
PROG = Path(__file__).resolve().parent.parent / "pad_drive_high_active_check.py"
def _run(args, **kw): return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)
def test_help():
    r = _run(["--help"]); assert r.returncode == 0
def test_empty_project(tmp_path):
    r = _run([str(tmp_path)]); assert r.returncode == 0


# --- the exit code, and the argv that made it undrivable

def test_main_takes_argv_at_all():
    """`gate_cli_mutation_probe` reported this gate SILENT: `def main():` read
    `sys.argv` unconditionally, so no test could drive it with arguments."""
    import inspect
    import pad_drive_high_active_check as P
    assert "argv" in inspect.signature(P.main).parameters


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import pad_drive_high_active_check as P
    assert P.main([str(tmp_path / "nope")]) == 2


def test_no_synth_top_is_a_documented_skip(tmp_path, monkeypatch):
    """A project with no synthesised top has no pads to classify. Pinned as a
    SKIP rather than invented as a failure — the mistake I made on
    `dispatcher_awake_gate_check` this morning."""
    import pad_drive_high_active_check as P
    monkeypatch.setattr(P, "_find_synth_top", lambda p: None)
    assert P.main([str(tmp_path)]) == 0
