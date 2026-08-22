#!/usr/bin/env python3
"""Bidirectional tests for `_step_failure_is_informational_only` on the P0 umbrella.

THE DEFECT
==========
`INFORMATIONAL_GATES` exists so a step whose ONLY failures cite an informational
gate does not drive the campaign verdict. `_step_failure_is_informational_only`
implemented that by scanning reasons that ``startswith("program failed:")``.

The P0 umbrella does not use that shape. `_run_structural_rtl_gates` composes
``FAIL: <gate> — <msg>`` (and ``  - <gate> — <msg>`` when >=2 gates fail); the
literal ``program failed:`` never appears on that path. So the scan skipped every
P0 reason and the function returned False for every P0 result — disabling the
exclusion for the three informational gates that can ONLY run inside P0.

Measured on `spm x sky130A` (campaign_v164, plugin 1.6.4) before the fix, spying
on the live StepResult rather than a hand-typed string::

    step id = P0 ; n reasons = 81 ; reasons starting with 'program failed:' = 0/81
    first reason = "FAIL: l22_verification_plan_measurable_check — [FAIL] ..."
    _step_failure_is_informational_only(real P0 result) -> False
    same gate name with the 'program failed:' prefix    -> True

These tests drive the REAL `INFORMATIONAL_GATES` / `_STRUCTURAL_RTL_GATES` sets,
not local fixtures, so they stay coupled to the shipped policy rather than
restating the fix.

#497 STEP 2 — THE PREDICATE NO LONGER PARSES PROSE
==================================================
`_step_failure_is_informational_only` used to recover the failing sub-gate
names by scraping `reasons`, via `_parse_p0_failing_subgates`. It now reads
them out of the umbrella's structured `gate_records`. The defect these tests
pin is unchanged and so are the assertions; what changed is that a P0 fixture
must now state its outcomes the way the umbrella states them — as records —
because that is what the shipped consumer reads. The prose is still built, by
the REAL producer, from the same records, so a fixture cannot say one thing in
its records and another in its reasons.

BIDIRECTIONALITY
================
* `test_DEFECT_*`   FAIL when the P0 branch is removed (the defect is present).
* `test_GUARD_*`    FAIL if the fix over-suppresses (a real gate FAIL must still
                    block, and non-P0 steps must be byte-identical in behaviour).
Either family alone would be a rubber stamp.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
fcc = importlib.import_module("flow_compliance_check")


def _p0(fails=(), skips=(), status="FAIL"):
    """A StepResult shaped exactly like the P0 umbrella's.

    `fails` / `skips` are (gate, message) pairs. Both the records AND the
    prose come from them, the prose through the umbrella's REAL producer, so
    the two sides of the fixture cannot disagree.
    """
    records = [fcc._p0_gate_record(g, "FAIL", m, {"exit_code": 1})
               for g, m in fails]
    records += [fcc._p0_gate_record(g, "SKIP", "",
                                    {"exit_code": 2,
                                     "skip_kind": "input-missing"})
                for g, _m in skips]
    reasons = fcc._compose_p0_reasons(
        [f"FAIL: {fcc._p0_fail_line_body(r)}"
         for r in records if r["verdict"] == "FAIL"],
        [r["name"] for r in records if r["verdict"] == "SKIP"], [])
    return fcc.StepResult(id="P0", name="Structural-RTL gates (P0 umbrella)",
                          stage="stage1", status=status, reasons=reasons,
                          gate_records=records)


# ── the gates that can only ever run inside the P0 umbrella ──────────────────
P0_ONLY_INFORMATIONAL = sorted(
    g for g in fcc.INFORMATIONAL_GATES if g in fcc._STRUCTURAL_RTL_GATES
)


def test_premise_p0_only_informational_gates_exist():
    """If this ever empties, the defect is moot and the tests below are vacuous.

    Guards against a silently-passing suite: the whole point is that some
    informational gates are reachable ONLY through the umbrella.
    """
    assert P0_ONLY_INFORMATIONAL, (
        "no INFORMATIONAL_GATES run inside the P0 umbrella — the rest of this "
        "module would be testing nothing")


def test_premise_p0_reasons_never_use_the_program_failed_prefix():
    """The root cause, asserted directly: the two shapes do not overlap.

    The P0 branch exists because the `program failed:` scan matched NOTHING the
    umbrella writes. That is still true of the prose the umbrella produces, and
    it is now beside the point: the P0 branch reads records.
    """
    gate = "l22_verification_plan_measurable_check"
    r = _p0(fails=[(gate, "[FAIL] TARGET_OUTSIDE_CONSUMING_LAYER — ...")])
    assert not any(x.startswith("program failed:") for x in r.reasons)
    assert fcc._p0_failing_gate_names(fcc._p0_gate_records(r)) == [gate]


# ── DEFECT direction: these FAIL when the P0 branch is removed ───────────────
@pytest.mark.parametrize("gate", P0_ONLY_INFORMATIONAL)
def test_DEFECT_single_informational_subgate_is_suppressed(gate):
    r = _p0(fails=[(gate, f"[FAIL] {gate}: SOME_FINDING — detail text")])
    assert fcc._step_failure_is_informational_only(r) is True, (
        f"P0 failing only on informational gate {gate!r} must be excluded from "
        f"the verdict; INFORMATIONAL_GATES says so in its own comment block")


def test_DEFECT_informational_subgate_amid_skip_lines_is_suppressed():
    """The real shape measured on spm: one FAIL line, then ~80 SKIP lines."""
    gate = P0_ONLY_INFORMATIONAL[0]
    r = _p0(fails=[(gate, "[FAIL] TARGET_OUTSIDE_CONSUMING_LAYER — ...")],
            skips=[(f"some_other_check_{i}", "") for i in range(80)])
    assert len(r.reasons) == 81, "premise: 1 FAIL line + 80 SKIP lines"
    assert fcc._step_failure_is_informational_only(r) is True


def test_DEFECT_multi_gate_dash_form_is_suppressed():
    """The >=2-failure shape: a `Failed gates (N):` header + indented dashes."""
    gates = P0_ONLY_INFORMATIONAL[:2]
    if len(gates) < 2:
        pytest.skip("needs >=2 P0-only informational gates")
    r = _p0(fails=[(g, "detail") for g in gates])
    assert r.reasons[0].startswith("Failed gates ("), (
        "premise: >=2 failures must reach the Form-2 shape")
    assert fcc._step_failure_is_informational_only(r) is True


# ── GUARD direction: these FAIL if the fix over-suppresses ───────────────────
def test_GUARD_real_gate_failure_still_blocks():
    """A non-informational sub-gate in the mix must keep P0 in `failing`."""
    real = next(g for g in fcc._STRUCTURAL_RTL_GATES
                if g not in fcc.INFORMATIONAL_GATES)
    r = _p0(fails=[("l22_verification_plan_measurable_check", "detail"),
                   (real, "a genuine structural defect")])
    assert fcc._step_failure_is_informational_only(r) is False, (
        "informational suppression must never mask a real gate's FAIL")


def test_GUARD_only_real_gate_failure_blocks():
    real = next(g for g in fcc._STRUCTURAL_RTL_GATES
                if g not in fcc.INFORMATIONAL_GATES)
    assert fcc._step_failure_is_informational_only(
        _p0(fails=[(real, "a genuine structural defect")])) is False


def test_GUARD_p0_with_no_failing_subgate_is_not_suppressed():
    """Only SKIP records: assert nothing rather than claim informational."""
    r = _p0(skips=[("some_check", "")])
    assert fcc._step_failure_is_informational_only(r) is False


def test_GUARD_a_p0_that_published_no_records_is_not_suppressed():
    """#497 fail-safe: no structured payload -> no claim.

    A P0 StepResult that carries reasons but no records (a stale artefact, a
    stub that was not updated) must not be silently treated as
    informational-only. The predicate says nothing, exactly as it did for an
    unparseable reasons list before the cut-over.
    """
    r = fcc.StepResult(id="P0", name="P0", stage="stage1", status="FAIL",
                       reasons=["FAIL: l22_verification_plan_measurable_check "
                                "— detail"])
    assert r.gate_records is None
    assert fcc._step_failure_is_informational_only(r) is False


def test_GUARD_non_p0_step_behaviour_is_unchanged():
    """The step-level `program failed:` path must be untouched."""
    ok = fcc.StepResult(id=14, name="Synthesis", stage="stage2", status="FAIL",
                        reasons=["program failed: "
                                 "bit_level_full_stack_tb_check . --json x.json"])
    bad = fcc.StepResult(id=14, name="Synthesis", stage="stage2", status="FAIL",
                         reasons=["program failed: some_real_gate . --json x.json"])
    assert fcc._step_failure_is_informational_only(ok) is True
    assert fcc._step_failure_is_informational_only(bad) is False


def test_GUARD_non_fail_status_is_never_suppressed():
    for status in ("PASS", "MISSING", "SKIPPED-CONDITION"):
        r = _p0(fails=[("l22_verification_plan_measurable_check", "d")],
                status=status)
        assert fcc._step_failure_is_informational_only(r) is False
