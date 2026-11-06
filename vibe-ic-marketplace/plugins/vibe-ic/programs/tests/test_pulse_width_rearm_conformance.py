#!/usr/bin/env python3
"""Focused Issue 2856 tests.

The two RTL variants consume the same source contract and the same generated
waveform.  The compliant design passes; the level-sensitive re-acquire control
fails on the overlong active suffix.  A plain pulse protocol without an
explicit maximum/rearm declaration remains outside this rule.
"""
from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
SPEC = Path(__file__).resolve().parent / "fixtures" / "pulse_width_rearm" / "contract.json"
GOOD = SPEC.parent / "compliant.sv"
BAD = SPEC.parent / "level_reacquire_bad.sv"
BOUNDARY_BAD = SPEC.parent / "max_plus_one_bad.sv"
STUCK_BAD = SPEC.parent / "stuck_accept_bad.sv"
RESET_BAD = SPEC.parent / "reset_polarity_bad.sv"
ZERO_BAD = SPEC.parent / "zero_negative.sv"
REGRESSION_SV = Path(__file__).resolve().parent / "pulse_width_rearm_regression.sv"
sys.path.insert(0, str(PROGRAMS))

import pulse_width_rearm_contract as contract  # noqa: E402
import spec_coverage_check as coverage  # noqa: E402


def test_regression_waveform_artifact_exists():
    assert REGRESSION_SV.exists()
    text = REGRESSION_SV.read_text()
    assert "OVERLONG_CYCLES" in text and "new rising edge" in text


def test_explicit_source_contract_keeps_quote_and_hash():
    parsed = contract.extract_contract(SPEC.read_text())
    assert parsed.declared and parsed.contract is not None
    c = parsed.contract
    assert c.input_signal == "pulse_i"
    assert c.accept_output == "accept_o"
    assert c.max_width_cycles == 4
    assert c.rearm_requires_inactive and c.rearm_requires_new_start_edge
    assert len(c.source_sha256) == 64 and len(c.source_quote_sha256) == 64
    assert c.source_quote and c.source_format == "json"


def test_no_contract_is_not_charged_as_a_pulse_rule(tmp_path):
    parsed = contract.extract_contract(
        "A pulse input is sampled by a clock. No maximum width or rearm policy is specified.\n")
    assert parsed.contract is None and not parsed.declared
    plain = tmp_path / "no_contract.txt"
    plain.write_text("A pulse input is sampled by a clock; timing is implementation-defined.\n")


def test_normal_coverage_path_requires_bound_native_receipt():
    source = SPEC.read_text()
    full_tb = (
        "pulse_i accept_o max_width overlong timeout; inactive=0 then a new "
        "rising edge / posedge; assert(accept_o === 1'b1);\n")
    report = coverage.run({"user_prompt": source}, GOOD.read_text(),
                          full_tb, None, True)
    item = next(i for i in report["items"] if i["kind"] == "pulse_width_rearm")
    assert report["blocked"] and item["covered"] is False


def test_spec_coverage_extracts_and_requires_complete_waveform():
    source = SPEC.read_text()
    items = coverage.extract_chain({"user_prompt": source})
    item = next(i for i in items if i.kind == "pulse_width_rearm")
    assert item.pulse_input_signal == "pulse_i"
    assert item.pulse_max_width_cycles == 4
    assert item.source_quote_sha256
    incomplete = coverage.run({"user_prompt": source}, GOOD.read_text(),
                              "pulse_i toggles once; accept_o is checked.\n",
                              None, True)
    assert incomplete["blocked"]
    full_tb = (
        "pulse_i accept_o max_width overlong timeout; inactive=0 then a new "
        "rising edge / posedge; assert(accept_o === 1'b1);\n")
    complete = coverage.run({"user_prompt": source}, GOOD.read_text(), full_tb,
                            None, True, _synthetic_receipt(source, GOOD.read_text()))
    pitem = next(i for i in complete["items"] if i["kind"] == "pulse_width_rearm")
    assert pitem["covered"] is True


def test_spec_coverage_does_not_pass_a_tampered_source_hash(tmp_path):
    obj = json.loads(SPEC.read_text())
    obj["pulse_width_rearm_contract"]["source_sha256"] = "0" * 64
    source = tmp_path / "bad_hash.json"
    source.write_text(json.dumps(obj))
    full_tb = (
        "pulse_i accept_o max_width overlong timeout; inactive=0 then a new "
        "rising edge / posedge; assert(accept_o === 1'b1);\n")
    report = coverage.run({"user_prompt": source.read_text()}, GOOD.read_text(),
                          full_tb, None, True)
    assert report["blocked"]
    item = next(i for i in report["items"] if i["kind"] == "pulse_width_rearm")
    assert item["covered"] is False and "source_sha256" in item["coverage_note"]


def test_strict_contract_rejects_duplicates_negation_and_guesses(tmp_path):
    obj = json.loads(SPEC.read_text())
    body = obj["pulse_width_rearm_contract"]
    body.pop("reset_active_low")
    missing_polarity = tmp_path / "missing_polarity.json"
    missing_polarity.write_text(json.dumps(obj))
    parsed = contract.extract_contract(missing_polarity.read_text())
    assert parsed.declared and parsed.contract is None

    negated = tmp_path / "negated.txt"
    negated.write_text(
        "Pulse input `pulse_i` is at most 4 cycles; timeout is not rejected and "
        "rearm does not require inactive or a new rising edge; accept output is `accept_o` on clock `clk`.\n")
    parsed = contract.extract_contract(negated.read_text())
    assert parsed.declared and parsed.contract is None

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"pulse_width_rearm_contract":{"source_quote":"q",'
        '"input_signal":"pulse_i","input_signal":"other",'
        '"accept_output":"accept_o","clock_signal":"clk",'
        '"max_width_cycles":4,"start_edge":"rising",'
        '"timeout_action":"reject","rearm_requires_inactive":true,'
        '"rearm_requires_new_start_edge":true}}')
    parsed = contract.extract_contract(duplicate.read_text())
    assert parsed.declared and parsed.contract is None

    wrong_role = json.loads(SPEC.read_text())
    wrong_role["pulse_width_rearm_contract"]["accept_output"] = "pulse_i"
    role_source = tmp_path / "wrong_role.json"
    role_source.write_text(json.dumps(wrong_role))


def _synthetic_receipt(source_text, rtl_text):
    parsed = contract.extract_contract(source_text)
    assert parsed.contract is not None
    c = parsed.contract
    return {
        "program": "pulse_width_rearm_conformance_check",
        "verdict": "PASS", "measured": True,
        "source_file_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
        "rtl_sha256": hashlib.sha256(rtl_text.encode()).hexdigest(),
        "contract": c.to_dict(),
        "counts": {"legal": 1, "boundary_bad": 0, "bad": 0,
                    "final": 1, "max": c.max_width_cycles},
        "stimulus": {"tb_sha256": "synthetic"},
        "result_channel_sha256": "synthetic",
        "raw_simulation_tail": ["PWR_COUNTS legal=1 boundary_bad=0 bad=0 final=1 max=4"],
    }


@pytest.mark.parametrize('state',['progressing','failed','stalled'])
@pytest.mark.parametrize('with_record',[False,True])
def test_allocated_pulse_run_preserves_progress_and_launch_record(tmp_path,monkeypatch,state,with_record):
    import _watchdog as wd
    calls=[]
    def observed(argv,**kw):
        calls.append((argv,kw))
        kw['popen_factory'](argv)
        return wd.SupervisedResult(0 if state=='progressing' else (7 if state=='failed' else wd.RC_STALLED),
            'retained stdout','WATCHDOG_STALLED' if state=='stalled' else 'retained stderr',
            'stalled' if state=='stalled' else 'natural',elapsed_s=50,
            supervision={'pid':321,'watched':'output+cpu'})
    monkeypatch.setattr(wd,'run_host_supervised',observed)
    class Raw:
        pid=321;returncode=7
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def communicate(self,**kw):return 'raw','raw'
    record={} if with_record else None
    argv=['neutral-tool','argument']
    assert len(calls)==1 and calls[0][0]==argv and calls[0][1]['hard_ceiling_s']==2
    assert calls[0][1]['cwd']==str(tmp_path)
    if with_record:
        assert record['supervision']['watched']=='output+cpu'


@pytest.mark.parametrize("text", [
    "Keep the clock inactive when the storage latches are not written.",
    "The active-low reset must not toggle near the rising edge of the clock.",
])
def test_unrelated_inactive_clock_or_reset_prose_is_not_a_pulse_contract(text):
    result = contract.extract_contract(text)
    assert result.declared is False
    assert result.contract is None
