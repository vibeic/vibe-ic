#!/usr/bin/env python3
"""Step 4 actually RUNS `coverage_closure` — and runs it advisory.

THE DEFECT
==========
`coverage_closure` was named in Step 4's `programs:` list ("gap analysis from
coverage_verilator.json") and executed by nothing:

  * it is not a `gate:` entry in flow/phase1_phase2_phase3.yaml,
  * it is not in `flow_compliance_check._STRUCTURAL_RTL_GATES`,
  * no runner subprocesses or imports it,
  * the only two readers of a step's `programs:` list — `flow_dashboard_data`
    and `flow_step_executor_coverage_check` — read the tokens for
    dashboard/audit purposes and execute nothing.

A program nothing runs also stops being maintained against the artefact it
reads, which is exactly what happened (see test_coverage_closure.py).

WHAT THIS FILE ASSERTS
======================
The observable property, not the yaml text: evaluate Step 4's OWN gate spec,
as shipped, with the real `_evaluate_gate`, and require that

  * coverage_closure is reached (a result is RECORDED), and
  * it is reached through the ADVISORY slot, so it cannot change any verdict.

Both halves are needed. "Recorded" alone would also pass if it were wired
blocking; "does not block" alone is trivially satisfied by not running it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parent.parent
_FLOW_YAML = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)

_PROGRAM = "coverage_closure"


def _iter_steps(o):
    if isinstance(o, dict):
        if "id" in o and ("name" in o or "required_outputs" in o):
            yield o
        for v in o.values():
            yield from _iter_steps(v)
    elif isinstance(o, list):
        for v in o:
            yield from _iter_steps(v)


def _step4():
    doc = yaml.safe_load(_FLOW_YAML.read_text(encoding="utf-8"))
    for s in _iter_steps(doc):
        if str(s.get("id")) == "4":
            return s
    pytest.fail("no step id=4 in the flow definition")


def _command_of(sub):
    """The command string a gate sub-entry runs, whatever slot it uses."""
    for key in ("program_exit_zero", "optional_program_exit_zero",
                "advisory_program_exit_zero"):
        if key in sub:
            spec = sub[key]
            cmd = spec if isinstance(spec, str) else (spec or {}).get("command")
            return key, (cmd or "")
    return None, ""


def _subgates():
    return [s for s in (_step4().get("gate") or {}).get("all_of", [])
            if isinstance(s, dict)]


def _first_token(cmd: str) -> str:
    parts = cmd.split()
    return parts[0] if parts else ""


def _coverage_closure_subgate():
    for sub in _subgates():
        key, cmd = _command_of(sub)
        if key and _first_token(cmd) == _PROGRAM:
            return sub, key, cmd
    return None, None, None


def _project(tmp_path: Path, payload) -> Path:
    p = tmp_path / "proj"
    (p / "reports" / "phase2" / "coverage").mkdir(parents=True, exist_ok=True)
    if payload is not None:
        (p / "reports" / "phase2" / "coverage" /
         "coverage_verilator.json").write_text(json.dumps(payload))
    return p


def _measured_payload(project: Path, line, toggle, branch):
    dat = project / "coverage.dat"
    dat.write_text("# verilator coverage\n")
    return {"tool": "verilator", "coverage_dat": str(dat),
            "totals": {"line": {"covered": int(line), "total": 100, "pct": line},
                       "toggle": {"covered": int(toggle), "total": 100,
                                  "pct": toggle},
                       "branch": {"covered": int(branch), "total": 100,
                                  "pct": branch}}}


# ── DEFECT direction — fails on origin/main (no such sub-gate exists) ────────

def test_DEFECT_step4_gate_reaches_coverage_closure():
    sub, key, cmd = _coverage_closure_subgate()
    assert sub is not None, (
        "Step 4 declares coverage_closure in `programs:` but no gate entry "
        "runs it — `programs:` is read by nothing that executes")
    assert key == "advisory_program_exit_zero", (
        f"coverage_closure is wired in the {key!r} slot; it is a gap analysis "
        f"whose floor is verilator_coverage_measure, so it must be advisory")
    assert _flow._resolve_program_cmd(cmd, cwd=Path.cwd()), (
        f"the wired command does not resolve to a real program: {cmd!r}")


def test_DEFECT_finding_is_recorded_when_a_real_gap_exists(tmp_path):
    """A measured 65 % line coverage must produce a RECORDED finding."""
    proj = tmp_path / "proj"
    (proj / "reports" / "phase2" / "coverage").mkdir(parents=True)
    payload = _measured_payload(proj, 65.0, 90.0, 88.0)
    (proj / "reports" / "phase2" / "coverage" /
     "coverage_verilator.json").write_text(json.dumps(payload))

    sub, _key, _cmd = _coverage_closure_subgate()
    assert sub is not None, "not wired — see the previous test"
    passed, reasons = _flow._evaluate_gate(proj, sub)
    records = [r for r in reasons
               if r.startswith(_flow._ADVISORY_RECORD_HINT_PREFIX)]
    # RECORDED — the half this file calls load-bearing. The refusal exists, it
    # is carried on the structured channel, its rc-derived enforcement still
    # reads BLOCKING, and it names the measured number.
    assert records, f"nothing recorded; reasons={reasons}"
    assert '"enforcement": "BLOCKING"' in records[0]
    assert any("65" in r for r in reasons), (
        f"the finding must carry the measured number: {reasons}")
    assert any(r.startswith("advisory gate refusal:") for r in reasons), (
        f"a refusal that is not REPORTED is a refusal nobody can read: "
        f"{reasons}")
    # AND DOES NOT CHANGE THE VERDICT — the other half, and it cannot be
    # satisfied by not running the gate, because the three assertions above
    # already require the run and the finding.
    assert passed is True, (
        f"an advisory clause denied its step the tier: {reasons}")


def test_DEFECT_unclassified_absence_is_incomplete_not_ok(tmp_path):
    """No typed reason -> incomplete, never `ok:` or a plain skip.

    `ok:` would read as "audited and found clean" for a project where nothing
    was measured — the substitution the disclosed-skip tier exists to prevent.
    """
    proj = _project(tmp_path, None)
    sub, _key, _cmd = _coverage_closure_subgate()
    assert sub is not None, "not wired — see the first test"
    passed, reasons = _flow._evaluate_gate(proj, sub)
    records = [r for r in reasons
               if r.startswith(_flow._ADVISORY_RECORD_HINT_PREFIX)]
    assert passed is True
    assert records, f"nothing recorded; reasons={reasons}"
    assert '"reason_class": "EXECUTION_ERROR"' in records[0]
    assert '"enforcement": "DISCLOSED_INCOMPLETE"' in records[0]
    assert not any("ok:" in r for r in reasons)


# ── GUARD direction — must hold on BOTH trees ────────────────────────────────

def test_GUARD_coverage_closure_live_refusal_is_reported_not_swallowed(
        tmp_path):
    """A measured below-threshold result is a refusal, not advisory prose.

    WAS `assert passed is False`, under the name `..._blocks_step4`. That
    contradicted this file's OWN opening requirement — coverage_closure must be
    "reached through the ADVISORY slot, so it cannot change any verdict" — and
    it demanded the very promotion `test_GUARD_no_blocking_step4_subgate_
    invokes_coverage_closure` below forbids, whose docstring gives the reason:
    the blocking floor for Step-4 coverage is `verilator_coverage_measure
    check` on the SAME artefact, and a second higher threshold wired blocking
    "would fail the step twice for one root cause".

    Bisected: green at 182879111^, red at 182879111 (v1.15.43), which taught
    `_evaluate_gate` to stand a refusal down on TWO-SOURCE agreement — the
    gate module's own docstring saying `ENFORCEMENT: advisory` AND the
    canonical flow wiring it advisory and never blocking. `coverage_closure`
    is both. So the assertion, not the flow, is what moved out of line.

    What a refusal must still do is be REPORTED, and that is what is asserted
    here now — with the two-source premise pinned first, so this test cannot
    go quietly green by the gate ceasing to be advisory.
    """
    proj = tmp_path / "proj"
    (proj / "reports" / "phase2" / "coverage").mkdir(parents=True)
    payload = _measured_payload(proj, 5.0, 5.0, 5.0)   # catastrophically low
    (proj / "reports" / "phase2" / "coverage" /
     "coverage_verilator.json").write_text(json.dumps(payload))
    sub, key, _cmd = _coverage_closure_subgate()
    if sub is None:
        pytest.skip("not wired on this tree — the DEFECT tests cover that")
    # PREMISE. If this ever stops holding, the stand-down below is wrong and
    # this test must say so rather than pass.
    assert _flow._gate_is_two_source_advisory(_PROGRAM), (
        f"{_PROGRAM} is no longer two-source advisory (module docstring + "
        f"flow row); a refusal from it is not stood down and this guard's "
        f"expectation is inverted")
    passed, reasons = _flow._evaluate_gate(proj, sub)
    refusals = [r for r in reasons if r.startswith("advisory gate refusal:")]
    assert refusals, (
        f"a live below-threshold measurement produced no reported refusal: "
        f"{reasons}")
    assert any('"enforcement": "BLOCKING"' in r for r in reasons
               if r.startswith(_flow._ADVISORY_RECORD_HINT_PREFIX)), (
        f"the structured record must keep the rc-derived enforcement: "
        f"{reasons}")
    assert passed is True, (
        f"a two-source-advisory refusal denied its step the tier: {reasons}")


def test_GUARD_no_blocking_step4_subgate_invokes_coverage_closure():
    """It must not be promoted to blocking by a later edit.

    The floor for Step-4 coverage is `verilator_coverage_measure check`, with
    its own thresholds and its own capability-gap/defect split. A second,
    higher threshold on the same artefact wired blocking would fail the step
    twice for one root cause.
    """
    offenders = []
    for sub in _subgates():
        key, cmd = _command_of(sub)
        if key in ("program_exit_zero", "optional_program_exit_zero") \
                and _first_token(cmd) == _PROGRAM:
            offenders.append(cmd)
    assert not offenders, offenders


def test_GUARD_verilator_coverage_measure_is_still_the_blocking_floor():
    """Direction-1: the pre-existing blocking coverage gate is untouched.

    It must still be an UNCONDITIONAL `program_exit_zero` — not demoted to
    advisory or made conditional while the advisory gap analysis was added.
    """
    found = []
    for sub in _subgates():
        key, cmd = _command_of(sub)
        if _first_token(cmd) == "verilator_coverage_measure":
            found.append((key, cmd))
    assert found, "Step 4 no longer runs verilator_coverage_measure at all"
    keys = {k for k, _ in found}
    assert keys == {"program_exit_zero"}, (
        f"the coverage floor must stay unconditional + blocking: {found}")
