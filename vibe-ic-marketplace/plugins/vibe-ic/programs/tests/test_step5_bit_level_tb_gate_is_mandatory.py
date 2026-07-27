#!/usr/bin/env python3
"""Step 5's bit-level full-stack TB gate blocks, as Step 5 declares it does.

THE DEFECT
==========
`flow/phase1_phase2_phase3.yaml` wires `bit_level_full_stack_tb_check` into
Step 5 as a plain `program_exit_zero` inside an `all_of`, with the inline
comment "Bit-level full-stack tb is mandatory before FPGA compile" — i.e.
declared MANDATORY, no optional/waiver marker.

`flow_compliance_check.INFORMATIONAL_GATES` listed the same program. A step
whose only FAIL reason cites a gate in that set is stripped out of `failing`
before the aggregate verdict is computed, so a genuine FAIL of a gate the flow
calls mandatory did not reach Overall (outside `--strict-structural`, whose
Phase-2 verdict is scoped to the P0 umbrella and never saw Step 5 either).

The declaration and the behaviour disagreed, and the behaviour was the looser
of the two. This fixes the behaviour, not the declaration.

WHY THAT IS SAFE, MEASURED
==========================
The entry's stated rationale was that a non-protocol IC "hard-failed on a
single-wire bit-level TB gate that does not apply to it". That is now handled
INSIDE the gate: it self-reports `VACUOUS_PASS` + rc=2 for an IC with no
command protocol / opcodes. Across all 38 real runs carrying a
`reports/phase2/gates/bit_level_full_stack.json` on the reference machine:
5 PASS (rc=0), 33 VACUOUS_PASS (rc=2), 0 FAIL (rc=1) — the exemption was
protecting no real run.

TEST FAMILIES
=============
  test_DEFECT_*  fail on origin/main (where the gate is still exempt).
  test_GUARD_*   pass on BOTH trees — the suppression machinery itself, and
                 the honest rc=2 disclosure, must keep working.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parent.parent
_FLOW_YAML = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
fcc = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = fcc
_spec.loader.exec_module(fcc)

GATE = "bit_level_full_stack_tb_check"


def _iter_steps(o):
    if isinstance(o, dict):
        if "id" in o and ("name" in o or "required_outputs" in o):
            yield o
        for v in o.values():
            yield from _iter_steps(v)
    elif isinstance(o, list):
        for v in o:
            yield from _iter_steps(v)


def _step(sid: str):
    doc = yaml.safe_load(_FLOW_YAML.read_text(encoding="utf-8"))
    for s in _iter_steps(doc):
        if str(s.get("id")) == sid:
            return s
    pytest.fail(f"no step id={sid} in the flow definition")


def _slot_of(sub):
    for key in ("program_exit_zero", "optional_program_exit_zero",
                "advisory_program_exit_zero"):
        if key in sub:
            spec = sub[key]
            cmd = spec if isinstance(spec, str) else (spec or {}).get("command")
            return key, (cmd or "")
    return None, ""


def _step5_slot_for(program: str):
    for sub in (_step("5").get("gate") or {}).get("all_of", []):
        if not isinstance(sub, dict):
            continue
        key, cmd = _slot_of(sub)
        if key and cmd.split() and cmd.split()[0] == program:
            return key, cmd
    return None, None


def _step5_fail(reason_gate: str = GATE):
    """A StepResult shaped exactly as `_evaluate_gate` produces for a failing
    `program_exit_zero` sub-gate of Step 5."""
    return fcc.StepResult(
        id=5, name="Formal verification", stage="stage1", status="FAIL",
        reasons=[f"program failed: {reason_gate} . "
                 f"--json reports/phase2/gates/bit_level_full_stack.json"])


# ── premise ─────────────────────────────────────────────────────────────────

def test_premise_step5_declares_the_gate_mandatory():
    """If the flow ever demotes it, the rest of this file is testing nothing."""
    slot, cmd = _step5_slot_for(GATE)
    assert slot == "program_exit_zero", (
        f"Step 5 no longer wires {GATE} as a mandatory blocking sub-gate "
        f"(slot={slot!r}, cmd={cmd!r}); the exemption question is moot and "
        f"this file must be revisited")


# ── DEFECT direction ────────────────────────────────────────────────────────

def test_DEFECT_step5_failure_counts_toward_the_verdict():
    """A genuine FAIL of the mandatory gate must NOT be filtered out."""
    assert fcc._step_failure_is_informational_only(_step5_fail()) is False, (
        f"{GATE} is declared mandatory by Step 5 but a FAIL of it is still "
        f"excluded from the aggregate verdict")


def test_DEFECT_gate_is_not_in_the_informational_set():
    assert GATE not in fcc.INFORMATIONAL_GATES


def test_DEFECT_strict_structural_p0_filter_no_longer_drops_it():
    """The P0 strict-structural count uses the same set via a substring scan.

    Asserted as the observable property that scan implements: no member of
    INFORMATIONAL_GATES is a substring of a Step-5 bit-level failure line.
    """
    line = (f"FAIL: {GATE} — [FAIL] {GATE}: tb does not drive the pad")
    assert not any(g in line for g in fcc.INFORMATIONAL_GATES), (
        "the strict-structural P0 filter would still swallow this line")


# ── GUARD direction — must hold on BOTH trees ───────────────────────────────

def test_GUARD_the_suppression_machinery_still_works():
    """Removing one member must not disable the mechanism for the others."""
    assert fcc.INFORMATIONAL_GATES, "the set must not have been emptied"
    for gate in sorted(fcc.INFORMATIONAL_GATES):
        r = fcc.StepResult(id=14, name="Synthesis", stage="stage2",
                           status="FAIL",
                           reasons=[f"program failed: {gate} . --json x.json"])
        assert fcc._step_failure_is_informational_only(r) is True, gate


def test_DEFECT_every_informational_entry_states_a_promotion_criterion():
    """An exemption with no way out is how a gate stops counting forever.

    Checks the shipped comment block, which is the only place the rationale
    lives — an entry added without one is exactly how this defect was created.
    Fails on origin/main: `bit_level_full_stack_tb_check` was exempted with a
    rationale and no promotion criterion, and stayed exempt after the gate
    itself learned to disclose the case the rationale was about.
    """
    src = (_PROGRAMS / "flow_compliance_check.py").read_text(encoding="utf-8")
    start = src.index("INFORMATIONAL_GATES: frozenset[str] = frozenset({")
    block = src[start:src.index("})", start)]
    for gate in sorted(fcc.INFORMATIONAL_GATES):
        seg = block[:block.index(f'"{gate}"')]
        seg = seg[seg.rindex("\n\n") if "\n\n" in seg else 0:]
        assert "PROMOTION" in seg.upper(), (
            f"{gate} is exempted with no promotion criterion in reach of its "
            f"entry — say what would make it count again")


def test_GUARD_non_protocol_ic_disclosure_is_rc2_not_rc1():
    """The honest answer for an IC the gate does not apply to is a DISCLOSED
    skip from the gate itself, which is what makes the exemption unnecessary.

    Asserted against the gate program's own contract rather than a run.
    """
    src = (_PROGRAMS / "bit_level_full_stack_tb_check.py").read_text(
        encoding="utf-8")
    assert "VACUOUS_PASS" in src, (
        "the gate no longer self-discloses the not-applicable case; without "
        "that, removing it from INFORMATIONAL_GATES would hard-fail "
        "non-protocol ICs")


def test_GUARD_a_real_gate_failure_in_step5_still_counts():
    """Direction-1: nothing about non-informational reasons changed."""
    assert fcc._step_failure_is_informational_only(
        _step5_fail("formal_proof_evidence_check")) is False
