#!/usr/bin/env python3
"""Tests for lvs_report_check.py — wrapper for eda_report_audit --mode lvs"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "lvs_report_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_empty_project(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 1


# An AUTHENTIC netgen sign-off report: a tool signature ("netgen"/"Circuits
# match"), a mismatch-category keyword ("Device"), the terminal MATCH token, and
# enough per-cell transcript to clear the 1536 B netgen byte floor.
_PRIMARY_MATCH = (
    "netgen 1.5.257 compare\n"
    "Contents of circuit 1:  Circuit: 'user_project_wrapper'\n"
    "Contents of circuit 2:  Circuit: 'user_project_wrapper'\n"
    + "".join(
        f"Device classes sky130_fd_sc_hd__inst{i} and "
        f"sky130_fd_sc_hd__inst{i} are equivalent.\n" for i in range(60))
    + "Cell pin lists are equivalent.\n"
    "Device classes user_project_wrapper and user_project_wrapper "
    "are equivalent.\n"
    "Final result: Circuits match uniquely.\n"
)
# The ADVISORY power-aware report: a real netgen MISMATCH (pad-ring top has
# top-level VPWR/VGND ports the rails-as-wires reference lacks).
_POWER_AWARE_MISMATCH = (
    "netgen 1.5.257 compare\n"
    + "".join(
        f"Net: input{i}/VPB | (no matching net)\n" for i in range(60))
    + "Subcircuit pins:\n"
    "Circuit 1: user_project_wrapper | Circuit 2: user_project_wrapper\n"
    "VGND | VPWR **Mismatch**\n"
    "Netlists do not match.\n"
    "Final result: Top level cell failed pin matching.\n"
)


def _mk_reports(tmp_path, *, primary=True, power_aware=True):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    if primary:
        (d / "lvs.rpt").write_text(_PRIMARY_MATCH)
    if power_aware:
        (d / "lvs_power_aware.rpt").write_text(_POWER_AWARE_MISMATCH)
    return tmp_path


def test_advisory_power_aware_does_not_override_primary_match(tmp_path):
    """The advisory `*power_aware*.rpt` (which the runner leaves on disk but
    never signs off on) must NOT drag a matching primary LVS to FAIL. Before the
    fix, _check_lvs concatenated both reports into one verdict blob and the
    power-aware 'Netlists do not match.' token overrode 'Circuits match
    uniquely.' — a false Step-31 LVS FAIL (caravel_user_project x sky130A)."""
    _mk_reports(tmp_path, primary=True, power_aware=True)
    r = _run([str(tmp_path), "--mode", "lvs"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_only_power_aware_report_does_not_pass(tmp_path):
    """No-leak: a run that produced ONLY the advisory report is not silently
    turned into a clean PASS — with no authoritative sign-off report, the
    advisory mismatch is judged and the gate FAILs."""
    _mk_reports(tmp_path, primary=False, power_aware=True)
    r = _run([str(tmp_path), "--mode", "lvs"])
    assert r.returncode == 1, r.stdout + r.stderr
