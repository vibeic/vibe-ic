#!/usr/bin/env python3
"""The two obstruction gates must STATE where their verdict is enforced.

THE DEFECT (vibe-ic#886's class, hit by two gates that landed after it).
`flow_gate_enforcement_audit` failed on pristine `origin/main` with:

    [FAIL] 2 NEW gate(s) are AUDIT_ONLY and declare no intent at all —
    nothing invokes them where they could block, and nothing in the gate says
    that was the decision:
       undeclared::macro_obs_geometry_intersect_check
       undeclared::macro_obs_load_parity_check

Both gates were wired into the flow's BLOCKING slot and both said "THIS GATE
BLOCKS (rc=1)" in prose, which is a claim about VERDICT SEVERITY. Neither said
anything about the axis the audit measures — whether a RUNNER spawns it inline
so the verdict can stop the step it guards. Silence on that axis is not a
decision, and the audit is right to refuse it.

WHAT WAS RECORDED, and why `advisory` is not a demotion. No runner spawns
either gate, so neither can stop its step as it happens; `advisory` is the
audit's token for that answer. The flow slot is a SEPARATE axis and is
unchanged: both remain in `program_exit_zero`, where `flow_compliance_check`
fails the step on rc=1. Conflating the two is how a gate gets moved to
`advisory_program_exit_zero` and silently defanged, so the second test below
pins the slot and would fail if the declaration were ever read as permission.

EVERY ASSERTION IS ON A RETURNED VALUE, AN EXIT CODE OR EMITTED JSON — never on
the presence of a string in a source file. A test that greps for
`ENFORCEMENT: advisory` would pass on a file where the audit cannot see it (the
declaration must OPEN a line and sit in the first 4000 characters), which is the
#886 defect in a test's clothing.

PAIRED, because "the audit reports neither gate" is trivially satisfiable by an
audit that reports nothing. The synthetic control proves the same code path
still flags an undeclared audit-only gate, and still stays silent for one that
declares.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

#: The two gates this file is about, with the flow step each one guards.
_GATES = (
    ("macro_obs_load_parity_check", "15"),
    ("macro_obs_geometry_intersect_check", "21"),
)


def _audit_mod():
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the program this file measures."""
    spec = importlib.util.spec_from_file_location(
        "_fgea_macro_obs", _PROGRAMS / "flow_gate_enforcement_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("gate,_step", _GATES)
def test_the_gate_declares_an_intent_the_audit_can_read(gate, _step):
    """RETURNED VALUE, not a grep. `declared_intent` is the exact function the
    audit uses to decide DECLARED vs UNDECLARED, so this cannot pass on a
    declaration the audit would not see."""
    mod = _audit_mod()
    assert mod.declared_intent(_PROGRAMS, gate) == "advisory", (
        f"{gate} must state where its verdict is enforced; the audit reads "
        f"`ENFORCEMENT:` opening a line in the first 4000 characters, or a "
        f"lone `\"verdict_mode\"` literal")


@pytest.mark.parametrize("gate,step", _GATES)
def test_the_declaration_did_not_move_the_gate_out_of_the_blocking_slot(
        gate, step):
    """THE PAIRED HALF, and the one that matters most.

    `advisory` answers "no runner spawns this inline". It is NOT a statement
    that the finding may be ignored, and it must never be used to justify
    moving the clause to `advisory_program_exit_zero`, where
    `_evaluate_gate` records the finding and passes the step anyway.

    Read from `clauses_in_flow` — the audit's own structural walk of the flow
    definition — so the assertion is about what the flow engine would dispatch,
    not about the text of a YAML line.
    """
    mod = _audit_mod()
    slots = sorted({c["slot"] for c in mod.clauses_in_flow(_FLOW)
                    if c["gate"] == gate})
    assert slots == ["program_exit_zero"], (
        f"{gate} (step {step}) is wired in {slots}; its rc=1 is a real defect "
        f"and must decide the step's verdict")


def test_the_audit_exits_zero_and_names_neither_gate_as_debt(tmp_path):
    """END TO END, on EXIT CODE and EMITTED JSON.

    The failing runner is `tools/ci/repo_hygiene_gates.sh`, which invokes this
    program and reads its exit status, so the exit status is what this asserts.
    The JSON half is there because rc 0 alone would also be satisfied by an
    audit that had stopped looking at these gates.
    """
    out = tmp_path / "audit.json"
    # 60s is the per-call ceiling `ci_harness_timeout_ceiling_check` enforces
    # (180s harness session bound // 3). A bound above it can outlive the
    # session and take every other file in the subset down with it, so the
    # number is not free to choose. Measured cost of this exact call on a
    # loaded build host (load avg 13.9): 17.2-21.2s over 5 runs, so 60s is
    # ~3x the observed worst case.
    cp = subprocess.run(
        [sys.executable, str(_PROGRAMS / "flow_gate_enforcement_audit.py"),
         "--json", str(out)],
        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, (
        f"rc={cp.returncode}\n{cp.stdout[-4000:]}\n{cp.stderr[-2000:]}")
    rep = json.loads(out.read_text())
    undeclared = {u["gate"] for u in rep["undeclared_audit_only"]}
    contradicting = {c["gate"] for c in rep["contradictions"]}
    rows = {r["gate"]: r for r in rep["gates"]}
    for gate, step in _GATES:
        assert gate in rows, f"{gate} is not in the flow definition at all"
        assert rows[gate]["declared"] == "advisory"
        assert rows[gate]["slots"] == ["program_exit_zero"], step
        assert gate not in undeclared
        assert gate not in contradicting


# --------------------------------------------------------------- the control

_SILENT = '''"""A gate that says nothing about where its verdict is enforced."""
'''
_DECLARING = '''"""A gate that says so.

ENFORCEMENT: advisory
"""
'''
_FLOW_DOC = textwrap.dedent("""\
    steps:
      - id: 1
        name: "synthetic"
        gate:
          all_of:
            - program_exit_zero: "{gate} . --json out.json"
    """)


def _synthetic(tmp_path: Path, name: str, body: str):
    progs = tmp_path / "programs"
    progs.mkdir(exist_ok=True)
    (progs / f"{name}.py").write_text(body)
    flow = tmp_path / f"{name}.yaml"
    flow.write_text(_FLOW_DOC.format(gate=name))
    return flow, progs


def test_the_control_an_undeclared_audit_only_gate_is_still_reported(tmp_path):
    """Without this, the two tests above would pass on an audit that had gone
    blind. Same `audit()` entry point, a tree where nothing invokes the gate."""
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path, "synthetic_silent_check", _SILENT)
    rep = mod.audit(flow, progs)
    assert [u["gate"] for u in rep["undeclared_audit_only"]] == [
        "synthetic_silent_check"]


def test_the_control_a_declaring_audit_only_gate_is_not_reported(tmp_path):
    """The other half: declaring `advisory` is what clears the finding, and it
    does not merely disable the check for everything."""
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path, "synthetic_declaring_check", _DECLARING)
    rep = mod.audit(flow, progs)
    assert rep["undeclared_audit_only"] == []
    assert rep["contradictions"] == []
    assert rep["gates"][0]["declared"] == "advisory"


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
