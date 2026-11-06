#!/usr/bin/env python3
"""A LibreLane tool the contract STOPPED is not a finding about the design.

`librelane_contract.run_container` (llv1 W16a) refuses `LL_TOOL_STALLED` when
a supervised tool step made no progress (container CPU and output flat for the
stall grace) and `LL_TOOL_DEADLINE` when a probe passed its deadline. Neither
says anything about the design: the tool never answered. Their consumers
booked every refusal alike: phase 3's `_fail` as a plain FAIL, analog A6 and
A7 as rc 1 with the `FAIL:` token (review wave5, W16a). Only a plain FAIL is
red; a step that did not measure is NOT_MEASURED with its reason
(`_outcome_states.py`): STALLED for a stall, BUDGET_EXHAUSTED for a probe
deadline, and the refusal's own text. A tool that ran and failed
(`LL_STEP_FAILED`) stays FAIL.
"""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

import _plugin_tree  # noqa: F401 -- puts programs/ on sys.path
import _analog_producer_common as _pc
import verdict as _V

import test_librelane_state_bridge as SB
import test_analog_a6_librelane_drc as T6
import test_analog_a7_post_layout_emit as T7

contract = importlib.import_module('librelane_contract')

STOPS = [('LL_TOOL_STALLED', _V.ReasonClass.STALLED.value),
         ('LL_TOOL_DEADLINE', _V.ReasonClass.BUDGET_EXHAUSTED.value)]


def _refusing(code):
    def run_chain(*_a, **_k):
        raise contract.Refusal(code, f'probe tool: {code} detail, partial output kept')
    return run_chain


# ── analog A6: LibreLane DRC arm ─────────────────────────────────────────────

@pytest.mark.parametrize('code,reason', STOPS)
def test_a6_books_a_stopped_tool_not_measured(tmp_path, monkeypatch, capsys, code, reason):
    T6.state_the_image(monkeypatch)
    stub = T6.stub.__wrapped__(tmp_path, monkeypatch)
    project = T6._project(stub)
    monkeypatch.setattr(contract, 'run_chain', _refusing(code))
    rc = T6.A6.run(project, 'blk', T6.IMAGE, None)
    assert rc == _pc.EX_ENV_REFUSED
    rec = json.loads((project / 'phase3/analog/blk/a6_librelane_drc.json').read_text())
    assert (rec['result'], rec['rule'], rec['reason_class']) == ('NOT_MEASURED', code, reason)
    err = capsys.readouterr().err
    assert err.startswith(_pc.ENV_REFUSED_TOKEN) and 'partial output kept' in err


def test_a6_keeps_a_tool_that_ran_and_failed_red(tmp_path, monkeypatch, capsys):
    T6.state_the_image(monkeypatch)
    stub = T6.stub.__wrapped__(tmp_path, monkeypatch)
    project = T6._project(stub)
    monkeypatch.setattr(contract, 'run_chain', _refusing('LL_STEP_FAILED'))
    assert T6.A6.run(project, 'blk', T6.IMAGE, None) == 1
    assert capsys.readouterr().err.startswith('FAIL:')


@pytest.mark.parametrize('code,reason', STOPS)
def test_a6_runner_keeps_the_arms_stop_reason(tmp_path, monkeypatch, code, reason):
    import analog_one_shot_runner as analog
    T6.state_the_image(monkeypatch)
    project = T6._project(tmp_path)
    (project / 'phase3/analog/analog_block_list.json').write_text(
        json.dumps({'blocks': [{'name': 'blk', 'type': 'ldo'}]}))
    SB.put(project / 'phase3/librelane_switch.json',
           {'steps': {'A6': 'librelane'}})
    record = project / 'phase3/analog/blk/a6_librelane_drc.json'
    record.write_text(json.dumps({'result': 'NOT_MEASURED', 'rule': code,
                                  'reason_class': reason}))
    monkeypatch.setattr(analog, '_a6_librelane_arm', lambda *a: {
        'rc': _pc.EX_ENV_REFUSED, 'blocking': True, 'record': str(record),
        'detail': f'{_pc.ENV_REFUSED_TOKEN} {code}: stopped'})
    real_run = analog._pr.run
    monkeypatch.setattr(analog._pr, 'run', lambda cmd, *a, **k: (
        SimpleNamespace(returncode=2, stdout='', stderr='')
        if any('drc_attribute' in str(x) for x in cmd)
        else real_run(cmd, *a, **k)))
    result = analog.step_for_block(project, {'name': 'blk', 'type': 'ldo'},
                                   'A6_block_pv', None)
    assert (result.status, result.reason_class) == ('NOT_MEASURED', reason)
    assert code in result.detail


# ── analog A7: post-layout extraction ────────────────────────────────────────

@pytest.mark.parametrize('code,reason', STOPS)
def test_a7_books_a_stopped_tool_not_measured(tmp_path, monkeypatch, capsys, code, reason):
    T7.state_the_image(monkeypatch)
    stub = T7.stub.__wrapped__(tmp_path, monkeypatch)
    project = T7._project(stub)
    monkeypatch.setattr(contract, 'run_chain', _refusing(code))
    rc = T7.A7.run(project, 'blk', 'vibeic-eda', T7.IMAGE)
    assert rc == _pc.EX_ENV_REFUSED
    rec = json.loads((project / 'phase3/analog/blk/a7_post_layout.json').read_text())
    assert (rec['result'], rec['rule'], rec['reason_class']) == ('NOT_MEASURED', code, reason)
    err = capsys.readouterr().err
    assert err.startswith(_pc.ENV_REFUSED_TOKEN) and 'partial output kept' in err


def test_a7_keeps_a_tool_that_ran_and_failed_red(tmp_path, monkeypatch, capsys):
    T7.state_the_image(monkeypatch)
    stub = T7.stub.__wrapped__(tmp_path, monkeypatch)
    project = T7._project(stub)
    monkeypatch.setattr(contract, 'run_chain', _refusing('LL_STEP_FAILED'))
    assert T7.A7.run(project, 'blk', 'vibeic-eda', T7.IMAGE) == 1
    assert capsys.readouterr().err.startswith('FAIL:')


# ── the one mapping ──────────────────────────────────────────────────────────

def test_the_contract_names_every_stop_it_raises_and_nothing_else():
    assert contract.TOOL_STOP_REASONS == dict(STOPS)
    assert contract.TIME_REFUSALS == frozenset(dict(STOPS))
    assert {c: contract.tool_stop_reason(c) for c, _ in STOPS} == dict(STOPS)
    assert contract.tool_stop_reason('LL_STEP_FAILED') is None
    assert contract.tool_stop_reason(None) is None
