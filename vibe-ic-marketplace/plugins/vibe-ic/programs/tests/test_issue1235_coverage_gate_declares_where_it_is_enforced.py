#!/usr/bin/env python3
"""The coverage-report gate must STATE where its verdict is enforced.

THE DEFECT (vibe-ic#886's class, hit by the gate #1219/#1235 wires).
`flow_gate_enforcement_audit` returned rc=1 on the #1235 branch with:

    [FAIL] 1 NEW gate(s) are AUDIT_ONLY and declare no intent at all —
    nothing invokes them where they could block, and nothing in the gate says
    that was the decision:
       undeclared::phase1_coverage_report_present_check

This was found by MEASUREMENT, not review: an 8-PR candidate batch returned
rc=1 from `repo_hygiene_gates.sh` and the failure attributed two-arm to #1235
alone (`flow_gate_enforcement_audit` rc=0 on main, rc=1 on #1235; the gate name
appears 8x in its diff and 0x on main). Wiring a NEW gate into the flow is what
creates the obligation — the audit's ratchet is bidirectional, so a new
audit-only gate that declares nothing is new debt and fails.

WHY `advisory` AND NOT `blocking` — settled by measurement, not preference.
The audit has two failing registers, and `blocking` would merely move the red
from one to the other:

    AUDIT_ONLY + declares blocking   -> "declares an intent it is not wired
                                        for"        0 gates do this
    AUDIT_ONLY + declares advisory   -> clean       25 gates do this

Every `phase1_*` gate in the flow that declares at all declares `advisory`
(`phase1_expert_track_evidence_check`, `phase1_planned_consumer_starved_check`,
and `phase1_expert_parse_track`). There is no counter-example anywhere in the
flow. Declaring `blocking` here would be asserting a wiring that does not
exist, and the audit would correctly say so.

`advisory` IS NOT A DEMOTION. It answers only "does a runner spawn this inline"
— no `_RUNNERS` entry does. The flow SLOT is a separate axis and is unchanged:
the clause stays in D1's `program_exit_zero`, where `flow_compliance_check`
fails the step on rc=1, and the gate still exits 1 on a violation. Both halves
are pinned below, because the failure mode of this kind of fix is that
`advisory` gets read as permission — either to move the clause to
`advisory_program_exit_zero` (finding recorded, step passes anyway) or to
soften the gate's own verdict.

EVERY ASSERTION IS ON A RETURNED VALUE, AN EXIT CODE OR EMITTED JSON — never on
the presence of a string in a source file. A test that greps for
`ENFORCEMENT: advisory` would pass on a file where the audit cannot see it (the
declaration must OPEN a line and sit in the first 4000 characters), which is
the #886 defect wearing a test's clothing.

PAIRED, because "the audit does not report this gate" is trivially satisfied by
an audit that reports nothing. The two synthetic controls prove the same code
path still flags an undeclared audit-only gate and still stays silent for one
that declares.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

_GATE = "phase1_coverage_report_present_check"
_STEP = "D1"


def _audit_mod():
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the program this file measures."""
    spec = importlib.util.spec_from_file_location(
        "_fgea_cov_report", _PROGRAMS / "flow_gate_enforcement_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_gate_declares_an_intent_the_audit_can_read():
    """RETURNED VALUE, not a grep. `declared_intent` is the exact function the
    audit uses to decide DECLARED vs UNDECLARED, so this cannot pass on a
    declaration the audit would not see."""
    mod = _audit_mod()
    assert mod.declared_intent(_PROGRAMS, _GATE) == "advisory", (
        f"{_GATE} must state where its verdict is enforced; the audit reads "
        f"`ENFORCEMENT:` opening a line in the first 4000 characters, or a "
        f"lone `\"verdict_mode\"` literal")


def test_the_declaration_did_not_move_the_gate_out_of_the_blocking_slot():
    """THE PAIRED HALF. `advisory` answers "no runner spawns this inline"; it
    is not a statement that the finding may be ignored.

    Read from `clauses_in_flow` — the audit's own structural walk — so the
    assertion is about what the flow engine would dispatch, not about the text
    of a YAML line."""
    mod = _audit_mod()
    slots = sorted({c["slot"] for c in mod.clauses_in_flow(_FLOW)
                    if c["gate"] == _GATE})
    assert slots == ["program_exit_zero"], (
        f"{_GATE} (step {_STEP}) is wired in {slots}; its rc=1 is a real "
        f"defect and must decide the step's verdict")


def test_the_audit_exits_zero_and_names_this_gate_as_neither_kind_of_debt(
        tmp_path):
    """END TO END, on EXIT CODE and EMITTED JSON.

    The failing runner is `tools/ci/repo_hygiene_gates.sh`, which invokes this
    program and reads its exit status, so the exit status is what this asserts.
    The JSON half is there because rc 0 alone would also be satisfied by an
    audit that had stopped looking at this gate.

    60s is the per-call ceiling `ci_harness_timeout_ceiling_check` enforces
    (180s harness session bound // 3); a bound above it can outlive the session
    and take every other file in the subset down with it."""
    out = tmp_path / "audit.json"
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "flow_gate_enforcement_audit.py"),
         "--json", str(out)],
        capture_output=True, text=True)
    assert cp.returncode == 0, (
        f"rc={cp.returncode}\n{cp.stdout[-4000:]}\n{cp.stderr[-2000:]}")
    rep = json.loads(out.read_text())
    rows = {r["gate"]: r for r in rep["gates"]}
    assert _GATE in rows, f"{_GATE} is not in the flow definition at all"
    assert rows[_GATE]["declared"] == "advisory"
    assert rows[_GATE]["slots"] == ["program_exit_zero"]
    assert _GATE not in {u["gate"] for u in rep["undeclared_audit_only"]}
    assert _GATE not in {c["gate"] for c in rep["contradictions"]}


# --------------------------------------------------------------------------
# `advisory` did not soften the gate itself — the severity axis, unchanged
# --------------------------------------------------------------------------
def test_the_gate_still_exits_nonzero_when_the_report_is_missing(tmp_path):
    """The declaration is about WIRING. If it ever coincided with the gate
    going quiet on a real violation, the fix would have defanged the thing it
    was documenting — so this measures the exit code directly.

    Mirrors `test_wired_clause_can_block` in the #1219 file deliberately: that
    one guards the flow wiring, this one guards it against the DECLARATION."""
    p = tmp_path / "proj"
    (p / "input" / "docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec_a.md").write_text("# spec a\nthe widget counts.\n")
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text('{"x": 1}')
    rc = _pr.run(
        [sys.executable, str(_PROGRAMS / f"{_GATE}.py"), str(p)],
        capture_output=True, text=True).returncode
    assert rc != 0, (
        "Phase 1 ran and the coverage report is absent, yet the gate passed — "
        "`ENFORCEMENT: advisory` describes the wiring; it must not soften the "
        "verdict")


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
    """Without this, the tests above would pass on an audit that had gone
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
