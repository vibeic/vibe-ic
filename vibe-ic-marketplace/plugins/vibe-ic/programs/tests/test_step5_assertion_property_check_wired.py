#!/usr/bin/env python3
"""DFT_FCC / 5-d1 — a program DECLARED in a step's `programs:` list must be
INVOKED by that step.

flow/phase1_phase2_phase3.yaml's own header states the contract:

    "When a step maps to a deterministic program, use `program:` …
     Multiple entries imply sequence; all must succeed."

`assertion_property_check` was listed under step 5's `programs:` while a
whole-tree grep found it in no runner, no gate and no MCP tool — an orphan
declaration.  On the reference run (spm × ihp-sg13g2) the program exits 1
(files_checked=4, valid_files=0, errors=9) while step 5's compliance verdict
was VACUOUS_PASS.

These tests pin the wiring so the gate cannot be silently dropped again, and
pin the exit-code contract that makes wiring it safe.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROGRAMS = Path(__file__).resolve().parent.parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
PROG = PROGRAMS / "assertion_property_check.py"


def _load_step(step_id):
    doc = yaml.safe_load(FLOW.read_text())
    for st in doc["steps"]:
        if st.get("id") == step_id:
            return st
    raise AssertionError(f"step {step_id} not found in {FLOW}")


def _gate_commands(step) -> list[str]:
    out: list[str] = []
    gate = step.get("gate") or {}
    for entry in gate.get("all_of") or []:
        if not isinstance(entry, dict):
            continue
        for key in ("program_exit_zero", "optional_program_exit_zero",
                    "advisory_program_exit_zero"):
            val = entry.get(key)
            if isinstance(val, str):
                out.append(val)
    return out


def test_step5_declares_assertion_property_check():
    """Guard on the declaration half — if someone deletes the declaration
    instead of wiring it, this test says so."""
    step5 = _load_step(5)
    assert "assertion_property_check" in (step5.get("programs") or [])


def test_step5_gate_actually_invokes_assertion_property_check():
    """The defect: DECLARED but never INVOKED."""
    cmds = _gate_commands(_load_step(5))
    matching = [c for c in cmds if c.split()[0] == "assertion_property_check"]
    assert matching, (
        "step 5 declares `assertion_property_check` under programs: but no "
        f"gate member invokes it. Gate members seen: {cmds}")


def test_step5_assertion_gate_is_unconditional_and_writes_evidence():
    """Wired UNCONDITIONALLY (`program_exit_zero`, not the
    condition_files_exist form the yaml itself calls the invisible-skip
    antipattern) and with a dereferenceable `--json <path>` artefact."""
    gate = (_load_step(5).get("gate") or {}).get("all_of") or []
    hits = [e for e in gate
            if isinstance(e, dict)
            and isinstance(e.get("program_exit_zero"), str)
            and e["program_exit_zero"].split()[0] == "assertion_property_check"]
    assert hits, "assertion_property_check must be a plain program_exit_zero member"
    cmd = hits[0]["program_exit_zero"]
    assert "--json" in cmd, cmd
    json_arg = cmd.split("--json", 1)[1].strip().split()[0]
    assert json_arg.endswith(".json"), (
        f"--json must carry an artefact PATH, got {json_arg!r} in {cmd!r}")


def test_gate_command_resolves_and_honours_the_rc_contract(tmp_path):
    """End-to-end on the literal yaml command string: run it with
    cwd=<project> exactly as `_check_program_exit_zero` does, over a project
    whose only assertion file is a stub.  Must be rc=1 (FAIL), and the
    declared evidence artefact must exist afterwards."""
    step5 = _load_step(5)
    cmd = next(c for c in _gate_commands(step5)
               if c.split()[0] == "assertion_property_check")
    argv = cmd.split()
    (tmp_path / "stub.sva").write_text("// stub\nassert property (p);\n")
    r = subprocess.run([sys.executable, str(PROG)] + argv[1:],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    json_rel = cmd.split("--json", 1)[1].strip().split()[0]
    assert (tmp_path / json_rel).is_file(), (
        f"gate evidence {json_rel} not written")


def test_gate_command_is_vacuous_when_project_has_no_assertion_candidate(tmp_path):
    """DIRECTION-1 GUARD for the #608 honest skip: a project with no
    assertion candidate at all must exit 2 (VACUOUS_PASS), never 1 — wiring
    this gate must not turn "no formal harness authored yet" into a FAIL."""
    step5 = _load_step(5)
    cmd = next(c for c in _gate_commands(step5)
               if c.split()[0] == "assertion_property_check")
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = subprocess.run([sys.executable, str(PROG)] + cmd.split()[1:],
                       cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
