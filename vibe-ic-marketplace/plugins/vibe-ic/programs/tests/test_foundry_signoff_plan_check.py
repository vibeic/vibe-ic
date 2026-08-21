#!/usr/bin/env python3
"""Tests for foundry_signoff_plan_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "foundry_signoff_plan_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_skip_no_plan(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_with_plan(tmp_path):
    plan = {"foundry_signoff_plan": {"closures": [
        {"waiver_id": 14, "tool": "Innovus", "proof_artefact": "step14.rpt"}
    ]}}
    (tmp_path / "foundry_signoff_plan.json").write_text(json.dumps(plan))
    r = _run([str(tmp_path)])
    assert r.returncode == 0


# --- main() ignored its arguments, so no test could drive it

def test_main_takes_argv_at_all():
    """`gate_cli_mutation_probe` reported this gate SILENT, and the cause was
    that no test COULD drive it: `def main():` read `sys.argv` unconditionally.

    Second instance of this exact shape today (`dispatcher_awake_gate_check` was
    the first), out of the 48 gates here that declare `main()` with no argv.
    """
    import inspect
    import foundry_signoff_plan_check as F
    assert "argv" in inspect.signature(F.main).parameters


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import foundry_signoff_plan_check as F
    assert F.main([str(tmp_path / "nope")]) == 2


def test_a_project_with_waivers_and_no_plan_exits_non_zero(tmp_path):
    """The real failure path, from the program's own contract: waivers present
    and no `foundry_signoff_plan.yaml` is the defect this gate exists for.

    My first version asserted `rc in (0, 1)` on an empty project, which is a
    weak assertion in the exact way this whole sweep is about — it passes
    whether the gate works or not. Measured: an empty project is rc 0 by design
    ("skip — no waivers"), so it could never have failed.
    """
    import json
    import foundry_signoff_plan_check as F
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"waived_steps": [{"id": 20, "reason": "x"}]}))
    rc = F.main([str(tmp_path)])
    assert rc == 1, f"waivers with no signoff plan exited {rc}"


def test_a_project_with_no_waivers_is_a_documented_skip(tmp_path):
    """…and the other direction, pinned as a SKIP rather than invented as a
    pass: "no waivers in project — no signoff plan required"."""
    import foundry_signoff_plan_check as F
    assert F.main([str(tmp_path)]) == 0
