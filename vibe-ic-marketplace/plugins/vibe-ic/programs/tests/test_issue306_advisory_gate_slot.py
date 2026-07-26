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
