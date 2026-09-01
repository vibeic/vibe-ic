#!/usr/bin/env python3
"""The advisory-declaration gate slot (vibe-ic#306 / #1980).

Before this slot existed, EVERY gate key in the flow definition blocked once
it ran. `optional_program_exit_zero` is conditional-on-inputs, not advisory:
once its condition holds it runs and a non-zero exit FAILS the step. So a
gate that DECLARES itself advisory could not be wired at all — wiring it
silently promoted it to blocking, which is #306's complaint in reverse
("claims not to block, and does").

Issue #1980 closes the later loophole: the slot may retain a program-authored
warning policy, but it may not flatten an unstructured non-zero exit or a
structured refusal into a nonblocking finding. Every execution is typed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)


def _adv(cmd="some_check --flag", **kw):
    return {"advisory_program_exit_zero": dict(command=cmd, **kw)}


def _records(reasons):
    return [json.loads(reason[len(_flow._ADVISORY_RECORD_HINT_PREFIX):])
            for reason in reasons
            if reason.startswith(_flow._ADVISORY_RECORD_HINT_PREFIX)]


def _shipped_advisory_commands():
    flow = yaml.safe_load((_PROGRAMS.parent / "flow"
                           / "phase1_phase2_phase3.yaml").read_text())
    commands = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "advisory_program_exit_zero":
                    commands.append(value if isinstance(value, str)
                                    else value.get("command", ""))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(flow)
    return commands


# ---------------------------------------------------------------- gate level

def test_unstructured_advisory_failure_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "found 3 problems"))
    passed, reasons = _flow._evaluate_gate(tmp_path, _adv())
    assert passed is False
    assert _records(reasons) == [{
        "command": "some_check --flag", "enforcement": "BLOCKING",
        "exit_code": 1, "gate": "some_check", "structured_verdict": None,
        "verdict": "FAIL", "reason_class": None,
    }]


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
    assert _records(reasons)[0]["enforcement"] == "PASSED"
    assert _records(reasons)[0]["exit_code"] == 0


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


def test_condition_absent_means_not_applicable_and_DECLARED(tmp_path,
                                                            monkeypatch):
    """W4 renamed the property in this test's own title.

    It used to end `..._and_silent` and assert that an unmet condition emitted
    NO advisory record at all. That silence was the defect: this slot's whole
    contract, three lines below it in `_evaluate_gate`, is "advisory: never
    blocks, ALWAYS RECORDED", and it already refuses to let an rc-2 disclosed
    skip read as a clean result because "recorded nothing must never be
    indistinguishable from found nothing". An unmet condition recorded nothing
    at all, with the program not even started.

    So the program STILL does not run — that half is unchanged and is asserted
    below — and what it leaves behind now depends on whether the clause
    declared why an absent input is a genuine not-applicable.
    """
    called = {"n": 0}

    def _never(p, c):
        called["n"] += 1
        return False, "should not run"

    monkeypatch.setattr(_flow, "_check_program_exit_zero", _never)

    # UNDECLARED: a gate-authoring defect, and this branch already treats a
    # malformed advisory spec as a real FAIL rather than an advisory one.
    passed, reasons = _flow._evaluate_gate(
        tmp_path, _adv(condition_files_exist=["never_exists.json"]))
    assert passed is False and called["n"] == 0
    assert "never_exists.json" in " ".join(reasons)

    # DECLARED: passes, does not run, and says both on the advisory channel.
    why = ("Fixture clause: the trigger is a board-only artefact a headless "
           "run legitimately never produces.")
    passed, reasons = _flow._evaluate_gate(
        tmp_path, _adv(condition_files_exist=["never_exists.json"],
                       absent_condition_reason=why))
    assert passed is True and called["n"] == 0
    adv = [r for r in reasons if r.startswith(_flow._ADVISORY_HINT_PREFIX)]
    assert len(adv) == 1 and why in adv[0], (
        f"the advisory slot must RECORD the declared not-applicable: {reasons}")


def test_condition_present_means_it_runs(tmp_path, monkeypatch):
    (tmp_path / "trigger.json").write_text("{}")
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "finding"))
    passed, reasons = _flow._evaluate_gate(
        tmp_path, _adv(condition_files_exist=["trigger.json"]))
    assert passed is False
    assert _records(reasons)[0]["enforcement"] == "BLOCKING"


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


def test_step_fails_and_the_refusal_is_visible(tmp_path, monkeypatch):
    """Visibility is the load-bearing half: a gate that runs and reports
    nothing makes the run LOOK audited while having said nothing."""
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda p, c: (False, "3 unwired declarations"))
    res = _check(tmp_path, _adv())
    assert res.status == "FAIL"
    assert res.advisory_gate_records[0]["enforcement"] == "BLOCKING"
    assert any("3 unwired declarations" in reason for reason in res.reasons)
    assert any("GATE EVIDENCE" in reason for reason in res.reasons)


def test_structured_advisory_counts_as_a_substantive_nonblocking_run(
        tmp_path, monkeypatch):
    """A program-authored warning remains nonblocking and fully recorded."""
    report = tmp_path / "advisory.json"
    report.write_text('{"verdict": "PASS_WITH_ADVISORIES"}')

    def _run(project, cmd):
        if "advisory" in cmd:
            return False, "finding"
        return True, f"{_flow._VACUOUS_HINT_PREFIX}{cmd}"

    monkeypatch.setattr(_flow, "_check_program_exit_zero", _run)
    res = _check(tmp_path, {"all_of": [
        {"program_exit_zero": "blocking_check --x"},
        {"advisory_program_exit_zero": {
            "command": "advisory_check --json advisory.json"}},
    ]})
    assert res.status == "PARTIALLY-VACUOUS", res.reasons
    assert any(r.startswith("ADVISORY (non-blocking") for r in res.reasons)
    assert res.advisory_gate_records[0]["structured_verdict"] == \
        "PASS_WITH_ADVISORIES"


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
    assert res.status == "FAIL"
    assert res.advisory_gate_records[0]["enforcement"] == "BLOCKING"


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
    assert passed is False
    assert _records(reasons)[0]["enforcement"] == "BLOCKING"


def test_the_two_real_gates_are_wired_in_the_flow_definition():
    """End-to-end: the two gates #306 recorded as un-wireable are now in the
    canonical flow, in the advisory slot, in the INLINE form the enforcement
    audit reads. Asserted against the shipped definition, not a fixture."""
    commands = _shipped_advisory_commands()
    for gate in ("route_congestion_trade_disclosure",
                 "phase1_expert_track_evidence_check"):
        assert any(command.startswith(gate + " ") for command in commands), gate


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
    records = _records(reasons)
    assert any(r["gate"] == "disclosure_check" for r in records), \
        "the advisory execution record must survive the short-circuit"


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
    records = _records(reasons)
    assert len(records) == 2, records
    assert len([r for r in records if r["gate"] == "first_check"]) == 1


def test_unclassified_rc2_is_incomplete_not_recorded_as_ok(
        tmp_path, monkeypatch):
    """An untyped rc=2 is EXECUTION_ERROR, never a clean or plain skip."""
    monkeypatch.setattr(
        _flow, "_check_program_exit_zero",
        lambda p, c: (True, f"{_flow._VACUOUS_HINT_PREFIX}{c}"))
    _p, reasons = _flow._evaluate_gate(tmp_path, _adv())
    records = _records(reasons)
    assert records[0]["exit_code"] == 2
    assert records[0]["reason_class"] == "EXECUTION_ERROR"
    assert records[0]["enforcement"] == "DISCLOSED_INCOMPLETE"
    assert any(r.startswith(_flow._INCOMPLETE_HINT_PREFIX) for r in reasons)


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
    commands = _shipped_advisory_commands()
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
        assert any(command.startswith(g + " ") for command in commands), g

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
