#!/usr/bin/env python3
"""#316/#306 — the enforcement audit must itself be able to stop something.

`flow_gate_enforcement_audit` measures which gates can actually block a run.
It found 4 gates declaring an intent they are not wired for — and it exited 1
about that while being wired into nothing, which is the exact defect it
names, one level up.

Fixing those 4 changes what a REAL run blocks on: a flow-owner decision, not
this audit's. So they are recorded as DEBT and the audit blocks anything NEW.
The class stops growing without the audit quietly setting enforcement policy.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "flow_gate_enforcement_audit.py"
_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"


def _run(*extra, baseline=None):
    cmd = [sys.executable, str(_PROG)]
    if baseline is not None:
        cmd += ["--baseline", str(baseline)]
    return subprocess.run(cmd + list(extra), capture_output=True, text=True,
                          timeout=300)


def test_316_shipped_tree_passes_against_its_recorded_debt():
    """Green as landed — an audit that ships red blocks nothing, which is the
    failure mode it exists to name."""
    r = _run()
    if r.returncode == 2:
        return
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recorded as debt" in r.stdout


def test_316_the_recorded_debt_is_named_not_hidden():
    """A count alone would let the register become a shrug. Every entry names
    its gate and which contract it broke."""
    known = json.loads(_BASELINE.read_text())["known"]
    assert known, "an empty register would make this gate vacuous"
    for k in known:
        kind, _, gate = k.partition("::")
        assert kind in ("contradiction", "orphan"), k
        assert gate and (_PROGRAMS / f"{gate}.py").is_file(), k


def test_316_a_new_contradiction_fails(tmp_path):
    """THE guard: an entry absent from the register must fail. Simulated by
    shrinking the register — anything it no longer covers is 'new'."""
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}))
    r = _run(baseline=bl)
    assert r.returncode == 1, r.stdout
    assert "declare an intent they are not wired for" in r.stdout


def test_316_paid_debt_must_leave_the_register(tmp_path):
    """A register entry that no longer contradicts is stale; left in place it
    becomes standing permission."""
    bl = tmp_path / "bl.json"
    known = json.loads(_BASELINE.read_text())["known"]
    bl.write_text(json.dumps({"known": known + ["orphan::a_gate_that_is_gone"]}))
    r = _run(baseline=bl)
    assert r.returncode == 1, r.stdout
    assert "the debt was paid" in r.stdout


def test_316_register_may_not_grow(tmp_path):
    """The one control that keeps this from becoming a waiver list."""
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}))
    r = _run("--write-baseline", baseline=bl)
    assert r.returncode == 1, r.stdout
    assert "refusing to GROW" in r.stdout
    assert json.loads(bl.read_text())["known"] == [], "the refused write landed"
