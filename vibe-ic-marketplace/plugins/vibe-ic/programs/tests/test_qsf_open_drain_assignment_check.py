#!/usr/bin/env python3
"""Tests for qsf_open_drain_assignment_check.py (DEPRECATED in v0.119.29).

The gate's v0.119.27 prescription (`set_instance_assignment -name
OPEN_DRAIN ON -to <pad>`) caused Quartus error 125048 in the v0.119.27
vendor run — the assignment name doesn't exist on MAX10 / Cyclone.
v0.119.29 deprecates the gate to a silent-PASS stub so any
flow_compliance call importing it doesn't break, but the gate is no
longer registered in the structural-RTL gate set.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "qsf_open_drain_assignment_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def test_deprecated_silent_pass(tmp_path):
    """v0.119.29: the gate now PASSes unconditionally with a
    deprecation notice."""
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "deprecated" in r.stdout.lower()


def test_deprecation_explains_why(tmp_path):
    r = _run(tmp_path)
    assert "125048" in r.stdout, \
        "deprecation notice must reference the actual Quartus error"
    assert "auto-infer" in r.stdout.lower() or "ternary" in r.stdout.lower()


def test_not_in_structural_gate_registry():
    """The gate must NOT be in flow_compliance_check._STRUCTURAL_RTL_GATES.
    Inclusion would re-introduce the false-alert."""
    flow_path = (
        Path(__file__).resolve().parent.parent / "flow_compliance_check.py"
    )
    text = flow_path.read_text()
    # Find the tuple body and verify the deprecated name is absent
    lines = text.splitlines()
    in_tuple = False
    seen = False
    for line in lines:
        if "_STRUCTURAL_RTL_GATES" in line and "=" in line:
            in_tuple = True
            continue
        if in_tuple:
            if line.strip().startswith(")"):
                break
            if "qsf_open_drain_assignment_check" in line and \
               not line.strip().startswith("#"):
                # Found OUTSIDE a comment — that's a regression
                seen = True
    assert not seen, \
        "qsf_open_drain_assignment_check must NOT be registered in " \
        "_STRUCTURAL_RTL_GATES — see v0.119.29 deprecation notice"


def test_bad_dir_returns_1(tmp_path):
    """Negative: still rejects non-existent dirs cleanly."""
    r = subprocess.run(
        [sys.executable, str(PROG), "/nonexistent/path/xyz"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1


def test_no_args_returns_2():
    r = subprocess.run(
        [sys.executable, str(PROG)],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
