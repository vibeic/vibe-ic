#!/usr/bin/env python3
"""The ADVISORY gate slot (vibe-ic#306).

Before this slot existed, EVERY gate key in the flow definition blocked once
it ran. `optional_program_exit_zero` is conditional-on-inputs, not advisory:
once its condition holds it runs and a non-zero exit FAILS the step. So a
gate that DECLARES itself advisory could not be wired at all — wiring it
silently promoted it to blocking, which is #306's complaint in reverse
("claims not to block, and does").

Every test here is paired, because each half alone would pass for the wrong
reason: "does not block" is trivially satisfiable by not running at all, and
"is recorded" is trivially satisfiable by a gate that also blocks.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)


def _adv(cmd="some_check --flag", **kw):
    return {"advisory_program_exit_zero": dict(command=cmd, **kw)}


# ---------------------------------------------------------------- gate level

def test_advisory_failure_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "found 3 problems"))
    passed, reasons = _flow._evaluate_gate(tmp_path, _adv())
    assert passed is True, "an advisory gate must never fail its step"
    assert any(r.startswith(_flow._ADVISORY_HINT_PREFIX) and "FINDING" in r
               for r in reasons), "the finding must be RECORDED, not dropped"


def test_the_same_program_in_the_blocking_slot_still_blocks(tmp_path,
                                                            monkeypatch):
    """The paired half. If this ever passes, the advisory slot has weakened
    the blocking one and every gate in the flow is advisory."""
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "found 3 problems"))
    passed, _ = _flow._evaluate_gate(
        tmp_path, {"program_exit_zero": "some_check --flag"})
    assert passed is False


def test_advisory_success_is_recorded_too(tmp_path, monkeypatch):
    """A clean advisory run must leave a trace. Recording only failures makes
    'ran and found nothing' indistinguishable from 'never ran'."""
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (True, "clean"))
    passed, reasons = _flow._evaluate_gate(tmp_path, _adv())
    assert passed is True
    assert any(r.startswith(_flow._ADVISORY_HINT_PREFIX) and "ok:" in r
               for r in reasons)


def test_malformed_advisory_spec_is_a_real_failure(tmp_path):
    """An advisory gate that CANNOT RUN records nothing, and 'recorded
    nothing' must never read as 'found nothing'. That is an authoring error,
    so it blocks — the one case where this slot does fail a step."""
    for bad in ({"advisory_program_exit_zero": ""},
                {"advisory_program_exit_zero": ["a", "list"]},
                {"advisory_program_exit_zero": 7},
                {"advisory_program_exit_zero": {}},
                {"advisory_program_exit_zero": {"command": "x",
                                                "condition_files_exist": []}}):
        passed, reasons = _flow._evaluate_gate(tmp_path, bad)
        assert passed is False, bad
        assert any("advisory_program_exit_zero" in r for r in reasons)


def test_condition_absent_means_not_applicable_and_silent(tmp_path,
                                                          monkeypatch):
    called = {"n": 0}

    def _never(p, c):
        called["n"] += 1
        return False, "should not run"

    monkeypatch.setattr(_flow, "_check_program_exit_zero", _never)
    passed, reasons = _flow._evaluate_gate(
        tmp_path, _adv(condition_files_exist=["never_exists.json"]))
    assert passed is True and called["n"] == 0
    assert not [r for r in reasons
                if r.startswith(_flow._ADVISORY_HINT_PREFIX)]


def test_condition_present_means_it_runs(tmp_path, monkeypatch):
    (tmp_path / "trigger.json").write_text("{}")
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "finding"))
    passed, reasons = _flow._evaluate_gate(
        tmp_path, _adv(condition_files_exist=["trigger.json"]))
    assert passed is True
    assert any("FINDING" in r for r in reasons)


def test_no_condition_key_means_it_runs_unconditionally(tmp_path, monkeypatch):
    seen = {"n": 0}
    monkeypatch.setattr(
        _flow, "_check_program_exit_zero",
        lambda p, c: (seen.__setitem__("n", seen["n"] + 1), (True, "ok"))[1])
    _flow._evaluate_gate(tmp_path, _adv())
    assert seen["n"] == 1


# ---------------------------------------------------------------- step level

def _step(gate):
    return {"id": 99, "name": "advisory probe", "stage": "test", "gate": gate}


def _check(tmp_path, gate):
    return _flow.check_step(tmp_path, _step(gate), {})


def test_step_stays_PASS_and_the_finding_is_visible(tmp_path, monkeypatch):
    """Visibility is the load-bearing half: a gate that runs and reports
    nothing makes the run LOOK audited while having said nothing."""
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "3 unwired declarations"))
    res = _check(tmp_path, _adv())
    assert res.status == "PASS"
    shown = [r for r in res.reasons if r.startswith("ADVISORY (non-blocking")]
    assert shown, res.reasons
    assert "3 unwired declarations" in shown[0]
    assert not [r for r in res.reasons
                if r.startswith(_flow._ADVISORY_HINT_PREFIX)], \
        "the internal marker must be stripped before display"


def test_advisory_does_not_disturb_the_vacuous_promotion(tmp_path,
                                                         monkeypatch):
    """An advisory finding must not demote a tier. It does not block, so it
    has no business turning a VACUOUS_PASS into a bare PASS either."""
    def _run(project, cmd):
        if "advisory" in cmd:
            return False, "finding"
        return True, f"{_flow._VACUOUS_HINT_PREFIX}{cmd}"

    monkeypatch.setattr(_flow, "_check_program_exit_zero", _run)
    res = _check(tmp_path, {"all_of": [
        {"program_exit_zero": "blocking_check --x"},
        {"advisory_program_exit_zero": {"command": "advisory_check --y"}},
    ]})
    assert res.status == "VACUOUS_PASS", res.reasons
    assert any(r.startswith("ADVISORY (non-blocking") for r in res.reasons)


def test_a_blocking_sibling_still_fails_the_step(tmp_path, monkeypatch):
    """Paired with the above: an advisory sibling must not rescue a real
    blocking failure."""
    monkeypatch.setattr(
        _flow, "_check_program_exit_zero",
        lambda p, c: (True, "ok") if "advisory" in c else (False, "real bug"))
    res = _check(tmp_path, {"all_of": [
        {"program_exit_zero": "blocking_check --x"},
        {"advisory_program_exit_zero": {"command": "advisory_check --y"}},
    ]})
    assert res.status == "FAIL", res.reasons


def test_stray_step_level_key_is_promoted_like_the_others(tmp_path,
                                                          monkeypatch):
    """A hand-slip that puts the key at STEP level instead of under `gate:`
    must not silently void it — the same protection the other predicate keys
    already had (#470)."""
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "finding"))
    step = {"id": 99, "name": "n", "stage": "s",
            "advisory_program_exit_zero": {"command": "advisory_check --y"}}
    res = _flow.check_step(tmp_path, step, {})
    assert any("gate-shaped predicate key" in r for r in res.reasons)
    assert any(r.startswith("ADVISORY (non-blocking") for r in res.reasons)


def test_bare_command_string_is_accepted(tmp_path, monkeypatch):
    """The blocking slot takes a bare command string, so this one does too —
    and the enforcement audit reads that inline form. A dict-only slot was
    wired into the flow and the audit still called both gates ORPHANED,
    because the command sat on the next line where its regex could not see
    it."""
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "finding"))
    passed, reasons = _flow._evaluate_gate(
        tmp_path, {"advisory_program_exit_zero": "some_check ."})
    assert passed is True
    assert any("FINDING" in r for r in reasons)


def test_the_two_real_gates_are_wired_in_the_flow_definition():
    """End-to-end: the two gates #306 recorded as un-wireable are now in the
    canonical flow, in the advisory slot, in the INLINE form the enforcement
    audit reads. Asserted against the shipped definition, not a fixture."""
    yaml_text = (_PROGRAMS.parent / "flow"
                 / "phase1_phase2_phase3.yaml").read_text()
    for gate in ("route_congestion_trade_disclosure",
                 "phase1_expert_track_evidence_check"):
        assert f'advisory_program_exit_zero: "{gate} .' in yaml_text, gate


def test_advisory_inside_any_of_is_an_authoring_error(tmp_path, monkeypatch):
    """An advisory gate ALWAYS passes, so one inside `any_of` makes the group
    pass unconditionally and its siblings are never consulted — a sign-off
    predicate silently voided. That must fail loudly."""
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "real bug"))
    passed, reasons = _flow._evaluate_gate(tmp_path, {"any_of": [
        {"advisory_program_exit_zero": {"command": "advisory_check"}},
        {"program_exit_zero": "blocking_check"},
    ]})
    assert passed is False
    assert any("any_of contains an `advisory_program_exit_zero`" in r
               for r in reasons)


def test_advisory_still_runs_after_a_blocking_sibling_fails(tmp_path,
                                                            monkeypatch):
    """REGRESSION, found end-to-end on a real cell (#297).

    `all_of` short-circuits on the first failing sub-gate. The advisory
    disclosure sits after the blocking ones, so on EVERY failing route it was
    skipped — and a failing route is exactly the run whose disclosure matters
    most. An advisory gate cannot change the verdict, so running it after a
    failure costs only its runtime.
    """
    def _run(project, cmd):
        return (False, "real bug") if "blocking" in cmd else (True, "clean")

    monkeypatch.setattr(_flow, "_check_program_exit_zero", _run)
    passed, reasons = _flow._evaluate_gate(tmp_path, {"all_of": [
        {"program_exit_zero": "blocking_check --x"},
        {"advisory_program_exit_zero": "disclosure_check ."},
    ]})
    assert passed is False, "the blocking failure must still fail the gate"
    assert any(r.startswith(_flow._ADVISORY_HINT_PREFIX) for r in reasons), \
        "the advisory verdict must survive the short-circuit"


def test_advisory_before_the_failure_is_not_recorded_twice(tmp_path,
                                                           monkeypatch):
    """The paired half. Advisory sub-gates ahead of the failing one already
    ran in the main loop; re-running the whole list would duplicate them."""
    monkeypatch.setattr(
        _flow, "_check_program_exit_zero",
        lambda p, c: (False, "real bug") if "blocking" in c else (True, "ok"))
    _p, reasons = _flow._evaluate_gate(tmp_path, {"all_of": [
        {"advisory_program_exit_zero": "first_check ."},
        {"program_exit_zero": "blocking_check --x"},
        {"advisory_program_exit_zero": "second_check ."},
    ]})
    adv = [r for r in reasons if r.startswith(_flow._ADVISORY_HINT_PREFIX)]
    assert len(adv) == 2, adv
    assert len([r for r in adv if "first_check" in r]) == 1, adv


def test_vacuous_skip_is_not_recorded_as_ok(tmp_path, monkeypatch):
    """rc=2 is the disclosed-skip tier, not a clean result. Recording it as
    `ok` would make "this project has no such input" read as "this project
    was audited and found clean"."""
    monkeypatch.setattr(
        _flow, "_check_program_exit_zero",
        lambda p, c: (True, f"{_flow._VACUOUS_HINT_PREFIX}{c}"))
    _p, reasons = _flow._evaluate_gate(tmp_path, _adv())
    adv = [r for r in reasons if r.startswith(_flow._ADVISORY_HINT_PREFIX)]
    assert adv and "n/a (input not present)" in adv[0], adv


# ------------------------------------------- declared-intent second channel

def _audit_mod():
    spec = importlib.util.spec_from_file_location(
        "flow_gate_enforcement_audit",
        _PROGRAMS / "flow_gate_enforcement_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runtime_verdict_mode_counts_as_a_declaration(tmp_path):
    """Some gates state their intent in the JSON they EMIT, not in an
    `ENFORCEMENT:` docstring line. Reading only the docstring reported them
    as UNDECLARED, so a wiring decision could be taken without ever seeing
    what the gate said about itself."""
    m = _audit_mod()
    (tmp_path / "a_check.py").write_text(
        '"""doc"""\nout = {"verdict_mode": "BLOCKS"}\n')
    (tmp_path / "b_check.py").write_text(
        '"""doc"""\nout = {"verdict_mode": "ADVISES"}\n')
    assert m.declared_intent(tmp_path, "a_check") == "blocking"
    assert m.declared_intent(tmp_path, "b_check") == "advisory"


def test_a_conditional_verdict_mode_is_not_a_declaration(tmp_path):
    """REGRESSION. `"BLOCKS" if strict else "ADVISES"` says the intent depends
    on a flag; claiming either invents a declaration the program never made.

    The first version of this guard failed on exactly the case it was written
    for: matching only the string VALUE after the key saw `"BLOCKS"` and
    nothing else, so a gate whose DEFAULT mode is ADVISES was reported as
    declaring blocking — and would then have been treated as an un-wireable
    blocking orphan.
    """
    m = _audit_mod()
    (tmp_path / "c_check.py").write_text(
        '"""doc"""\nout = {"verdict_mode": "BLOCKS" if strict else "ADVISES"}\n')
    assert m.declared_intent(tmp_path, "c_check") is None


def test_docstring_declaration_still_wins(tmp_path):
    m = _audit_mod()
    (tmp_path / "d_check.py").write_text(
        '"""ENFORCEMENT: advisory"""\nout = {"verdict_mode": "BLOCKS"}\n')
    assert m.declared_intent(tmp_path, "d_check") == "advisory"


def test_the_ten_layer_gates_are_wired_advisory_and_the_blocking_two_are_not():
    """Every per-layer contract gate is wired to the advisory slot, and its
    own declaration agrees with that slot.

    HISTORY (#316). This test used to assert the OPPOSITE for two of them:
    l16/l17 declared `verdict_mode: BLOCKS`, so wiring them advisory would
    contradict their own declaration, and this test pinned them OUT of the
    flow. What it actually pinned was a gate that ran NOWHERE — the #306
    defect, held in place by a test. `flow_gate_enforcement_audit` recorded
    both as ORPHANS for exactly that reason.

    The resolution is not to wire a BLOCKS gate into an advisory slot; it is
    to make the declaration true. Both were measured on the published corpus
    (l17 fires on 11 of 12 cells — a real finding, but one producer defect
    reproduced corpus-wide, so blocking would fail every run; l16 fires on
    none, so its clean record was vacuous), both now declare ADVISES, and both
    are wired. So the invariant this test defends is stronger than before and
    has no exception list: NO per-layer gate may sit outside the flow, and
    none may be wired to a slot its own declaration contradicts.
    """
    yaml_text = (_PROGRAMS.parent / "flow"
                 / "phase1_phase2_phase3.yaml").read_text()
    layer_gates = (
        "l7_debug_access_grounding_check",
        "l8_clock_period_actionability_check",
        "l9_floorplan_contract_check",
        "l10_test_case_oracle_anchor_check",
        "l11_otp_content_consumer_contract_check",
        "l12_sequences_in_consumed_layer_check",
        "l13_bringup_contract_check",
        "l14_protocol_versioning_contract_check",
        "l15_encoding_tables_contract_check",
        "l16_compliance_properties_actionable_check",
        "l17_channel_catalog_consumer_contract_check",
        "l18_interconnect_topology_factuality_check",
        "l21_macro_supply_rail_declared_check",
        "l8_sta_clock_period_design_owned_check",
    )
    for g in layer_gates:
        assert f'advisory_program_exit_zero: "{g} .' in yaml_text, g

    # The declaration must AGREE with the slot: nothing wired advisory may
    # claim blocking. Read it the same way the enforcement audit does.
    spec = importlib.util.spec_from_file_location(
        "flow_gate_enforcement_audit",
        _PROGRAMS / "flow_gate_enforcement_audit.py")
    fga = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fga)
    for g in layer_gates:
        assert fga.declared_intent(_PROGRAMS, g) != "blocking", (
            f"{g} is wired to the ADVISORY slot while declaring blocking — "
            "that contradiction is #306/#316 exactly. Either wire it where a "
            "runner invokes it inline, or declare what it does.")


def test_advisory_is_not_a_backing_checker_for_a_self_asserted_gate():
    """`gate_self_assertion_check` requires a json_field_true (which trusts an
    artifact's own PASS) to be backed by a BLOCKING program. An advisory one
    cannot fail anything, so it must not satisfy that requirement.

    Asserted on BEHAVIOUR (the module's own extractor), not on the presence
    of a comment: a grep for prose passes whatever the code does.
    """
    spec = importlib.util.spec_from_file_location(
        "gate_self_assertion_check", _PROGRAMS / "gate_self_assertion_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = next((getattr(mod, n) for n in dir(mod)
               if n.startswith("_") and "predicate" in n.lower()), None)
    gate = {"all_of": [
        {"json_field_true": {"file": "x.json", "field": "passed"}},
        {"advisory_program_exit_zero": {"command": "some_check"}},
    ]}
    if fn is None:
        fn = next(getattr(mod, n) for n in dir(mod)
                  if callable(getattr(mod, n)) and n.startswith("_extract"))
    _jft, has_blocking = fn(gate)
    assert has_blocking is False, \
        "an advisory gate must not count as the blocking checker behind a " \
        "self-asserted json_field_true"
