#!/usr/bin/env python3
"""A LibreLane tool stopped INSIDE the pnr session is not a finding either.

Steps 19/20 (`librelane_cts_hold.execute`) and 21 (`librelane_route.execute`)
run inside step_pnr's session and answer it like `_docker_exec`: `(rc, out,
err)`. Every contract refusal became rc 1, and step_pnr books any nonzero rc
FAIL. So a stalled step 19/21 (`LL_TOOL_STALLED`), or a probe past its deadline
(`LL_TOOL_DEADLINE`), read as a red pnr: a finding about the design from a tool
that never answered (the same class FX_STALL_AND_PADRING_RC fixed for phase 3's
`_fail` and A6/A7).

The chains now return the session's own stop codes for a stop (the watchdog's
RC_STALLED, the ceiling's 124), and step_pnr books those NOT_MEASURED with the
contract's reason (STALLED / BUDGET_EXHAUSTED). A tool that ran and failed
stays rc 1 and FAIL.

The analog runner booked every rc-69 (environment) row with the fixed class
input_absent. The A6 LibreLane arm and A7 write the reason in their block
record; the runner now carries the record's own reason_class.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import _plugin_tree  # noqa: F401 -- puts programs/ on sys.path
import _analog_producer_common as _pc
import _watchdog as W
import verdict as _V


import librelane_contract as contract

STOPS = [('LL_TOOL_STALLED', W.RC_STALLED, _V.ReasonClass.STALLED.value),
         ('LL_TOOL_DEADLINE', 124, _V.ReasonClass.BUDGET_EXHAUSTED.value)]


# ── the contract's one mapping, extended to the session rc ─────────────────

def test_the_contract_names_the_session_rc_of_every_stop():
    assert {c: contract.tool_stop_session_rc(c) for c, _, _ in STOPS} == {
        c: rc for c, rc, _ in STOPS}
    assert contract.tool_stop_session_rc('LL_STEP_FAILED') is None
    assert contract.session_stop_reason(124, '') is None
    assert contract.session_stop_reason(W.RC_STALLED, '') is None
    assert contract.session_stop_reason(124, 'PNR_ROUTE_REFUSED LL_TOOL_DEADLINE: stopped') == (
        _V.ReasonClass.BUDGET_EXHAUSTED.value)


# ── step 21: librelane_route.execute ─────────────────────────────────────────


# ── steps 19/20: librelane_cts_hold.execute ─────────────────────────────────


# ── step_pnr: the session's stop code is NOT_MEASURED, never FAIL ────────────


# ── the analog runner carries the block record's own reason ─────────────────

def _a6_runner(tmp_path, monkeypatch, arm):
    import analog_one_shot_runner as R
    import test_analog_a6_librelane_drc as T6
    T6.state_the_image(monkeypatch)
    project = T6._project(tmp_path)
    (project / "phase3/analog/analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "blk", "type": "ldo"}]}))
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"A6": "librelane"}}))
    rec = project / "phase3/analog/blk/a6_librelane_drc.json"
    if arm.get("reason_class"):
        rec.write_text(json.dumps({"result": "NOT_MEASURED", "rule": arm["rule"],
                                   "reason_class": arm["reason_class"]}))
    monkeypatch.setattr(R, "_a6_librelane_arm", lambda *a: {
        "rc": arm["rc"], "blocking": True, "record": str(rec) if rec.is_file() else None,
        "detail": arm["detail"]})
    real = R._pr.run
    monkeypatch.setattr(R._pr, "run", lambda cmd, *a, **k: (
        SimpleNamespace(returncode=2, stdout="", stderr="")
        if any("drc_attribute" in str(x) for x in cmd) else real(cmd, *a, **k)))
    return R.step_for_block(project, {"name": "blk", "type": "ldo"},
                            "A6_block_pv", None)


@pytest.mark.parametrize('code,_rc,reason', STOPS)
def test_runner_books_a_stopped_a6_arm_with_the_records_reason(tmp_path, monkeypatch,
                                                               code, _rc, reason):
    res = _a6_runner(tmp_path, monkeypatch, {
        "rc": _pc.EX_ENV_REFUSED, "rule": code, "reason_class": reason,
        "detail": f"{_pc.ENV_REFUSED_TOKEN} analog_a6_librelane_drc {code}: stopped"})
    assert (res.status, res.reason_class) == ('NOT_MEASURED', reason)
    assert code in res.detail


def test_runner_keeps_a_blocking_a6_arm_red(tmp_path, monkeypatch):
    """Control: the arm ran and named a blocking rule."""
    res = _a6_runner(tmp_path, monkeypatch, {
        "rc": 1, "rule": None, "detail": "blocking={'magic:U.2': 4}"})
    assert res.status == 'FAIL' and 'magic:U.2' in res.detail


def _a7_runner(tmp_path, monkeypatch, rc, stderr, reason=None):
    import analog_one_shot_runner as R
    import test_analog_a7_post_layout_emit as T7
    T7.state_the_image(monkeypatch)
    stub = T7.stub.__wrapped__(tmp_path, monkeypatch)
    project = T7._project(stub)
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"A7": "librelane"}}))
    rec = project / "phase3/analog/blk/a7_post_layout.json"
    real_run = R._pr.run

    def fake_run(cmd, *a, **k):
        if any(str(x).endswith("analog_a7_post_layout_emit.py") for x in cmd):
            if reason:
                rec.write_text(json.dumps({"result": "NOT_MEASURED",
                                           "reason_class": reason}))
            return SimpleNamespace(returncode=rc, stdout="", stderr=stderr)
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(R._pr, "run", fake_run)
    monkeypatch.setattr(R._pin, "container_image_digest",
                        lambda c: (T7.PIN.IMAGE_DIGEST, ""))
    return R.step_for_block(project, {"name": "blk", "type": "ldo"},
                            "A7_post_layout_resim", None)


@pytest.mark.parametrize('code,_rc,reason', STOPS)
def test_runner_books_a_stopped_a7_with_the_records_reason(tmp_path, monkeypatch,
                                                           code, _rc, reason):
    res = _a7_runner(tmp_path, monkeypatch, _pc.EX_ENV_REFUSED,
                     f"{_pc.ENV_REFUSED_TOKEN} analog_a7_post_layout_emit {code}: stopped",
                     reason)
    assert (res.status, res.reason_class) == ('NOT_MEASURED', reason)


def test_runner_keeps_input_absent_when_the_record_names_no_reason(tmp_path, monkeypatch):
    """Control: an environment refusal whose record carries no reason keeps the
    runner's own class, as before."""
    res = _a7_runner(tmp_path, monkeypatch, _pc.EX_ENV_REFUSED,
                     f"{_pc.ENV_REFUSED_TOKEN} container is not the pinned image")
    assert (res.status, res.reason_class) == (
        'NOT_MEASURED', _V.ReasonClass.INPUT_ABSENT.value)


def test_runner_keeps_a_failed_a7_red(tmp_path, monkeypatch):
    res = _a7_runner(tmp_path, monkeypatch, 1, "FAIL: analog_a7 A7_RCX_PARASITIC_FREE")
    assert res.status == 'FAIL'
