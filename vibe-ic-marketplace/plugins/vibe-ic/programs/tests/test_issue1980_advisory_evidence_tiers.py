#!/usr/bin/env python3
"""Issue #1980: advisory executions must retain their real evidence tier."""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path

import yaml


_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)


def _write_program(programs: Path, name: str, body: str) -> None:
    programs.mkdir(parents=True, exist_ok=True)
    (programs / f"{name}.py").write_text(body)


def _step(gate=None, **extra):
    step = {"id": 1980, "name": "evidence tier probe", "stage": "test"}
    if gate is not None:
        step["gate"] = gate
    step.update(extra)
    return step


def test_rc1_advisory_refusal_blocks_and_preserves_the_real_exit_code(
        tmp_path, monkeypatch):
    programs = tmp_path / "programs"
    _write_program(
        programs,
        "live_refusal",
        "import sys\nprint('FAIL: live finding')\nsys.exit(1)\n",
    )
    monkeypatch.setattr(_flow, "PROGRAMS_DIR", programs)

    result = _flow.check_step(
        tmp_path,
        _step({"advisory_program_exit_zero": "live_refusal"}),
        {},
    )

    assert result.status == "FAIL", result.reasons
    assert getattr(result, "advisory_gate_records", []) == [{
        "gate": "live_refusal",
        "command": "live_refusal",
        "exit_code": 1,
        "verdict": "FAIL",
        "structured_verdict": None,
        "reason_class": None,
        "enforcement": "BLOCKING",
    }]


def test_unclassified_structured_skip_is_incomplete_not_a_plain_skip(
        tmp_path, monkeypatch):
    programs = tmp_path / "programs"
    _write_program(
        programs,
        "structured_skip",
        """import json
import pathlib
import sys

target = pathlib.Path(sys.argv[sys.argv.index('--json') + 1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({'verdict': 'SKIP', 'reason': 'no live input'}))
print('SKIP: no live input')
""",
    )
    monkeypatch.setattr(_flow, "PROGRAMS_DIR", programs)
    command = "structured_skip --json reports/structured_skip.json"

    result = _flow.check_step(
        tmp_path,
        _step({"advisory_program_exit_zero": command}),
        {},
    )

    assert result.status == "INCOMPLETE", result.reasons
    assert getattr(result, "advisory_gate_records", []) == [{
        "gate": "structured_skip",
        "command": command,
        "exit_code": 0,
        "verdict": "SKIP",
        "structured_verdict": "SKIP",
        "reason_class": "EXECUTION_ERROR",
        "enforcement": "DISCLOSED_INCOMPLETE",
    }]


def test_classified_design_na_reaches_the_skip_tier(tmp_path, monkeypatch):
    programs = tmp_path / "programs"
    _write_program(
        programs,
        "classified_skip",
        """import json
import pathlib
import sys

target = pathlib.Path(sys.argv[sys.argv.index('--json') + 1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({
    'verdict': 'SKIP',
    'reason': 'design declared no command protocol',
    'reason_class': 'DESIGN_DECLARED_NA',
}))
print('SKIP: design declared no command protocol')
""",
    )
    monkeypatch.setattr(_flow, "PROGRAMS_DIR", programs)
    command = "classified_skip --json reports/classified_skip.json"

    result = _flow.check_step(
        tmp_path,
        _step({"advisory_program_exit_zero": command}),
        {},
    )

    assert result.status == "SKIPPED-CONDITION", result.reasons
    assert result.advisory_gate_records == [{
        "gate": "classified_skip",
        "command": command,
        "exit_code": 0,
        "verdict": "SKIP",
        "structured_verdict": "SKIP",
        "reason_class": "DESIGN_DECLARED_NA",
        "enforcement": "DISCLOSED_SKIP",
    }]


def test_scoped_approved_step_waiver_prevents_the_refusal_from_running(
        tmp_path, monkeypatch):
    called = {"count": 0}

    def _must_not_run(_project, _command):
        called["count"] += 1
        return False, "live refusal"

    monkeypatch.setattr(_flow, "_check_program_exit_zero", _must_not_run)
    result = _flow.check_step(
        tmp_path,
        _step({"advisory_program_exit_zero": "live_refusal"}),
        {1980: {
            "reason": "Approved issue-1980 fixture waiver for this step only",
            "approver": "independent-reviewer",
        }},
    )

    assert result.status == "WAIVED"
    assert called["count"] == 0
    assert result.advisory_gate_records == []


def test_producer_only_output_is_visible_but_never_counted_as_a_gate(tmp_path):
    report = tmp_path / "reports" / "producer.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"verdict": "INCOMPLETE", "finding": "WELLTAP_GAP", '
        '"reason_class": "ZERO_DENOMINATOR"}')
    before = len(_flow._GATE_LEDGER)

    result = _flow.check_step(
        tmp_path,
        _step(
            programs=["producer_classifier"],
            required_outputs=["reports/producer.json"],
            program_outputs=[{
                "program": "producer_classifier",
                "path": "reports/producer.json",
                "verdict_field": "verdict",
            }],
        ),
        {},
    )

    assert result.status == "PASS", result.reasons
    assert getattr(result, "program_output_records", []) == [{
        "program": "producer_classifier",
        "path": "reports/producer.json",
        "produced": True,
        "verdict": "INCOMPLETE",
        "reason_class": "ZERO_DENOMINATOR",
        "role": "PRODUCER_OUTPUT",
        "enforcement": "NOT_A_GATE",
    }]
    assert len(_flow._GATE_LEDGER) == before


_MEASURED_FINDINGS = {
    "l8_sta_clock_period_design_owned_check":
        "l8_sta_clock_period_design_owned_check",
    "l8_clock_period_actionability_check":
        "l8_clock_period_actionability_check",
    "l_doc_cross_consistency_check": "l_doc_cross_consistency_check",
    "phase1_provenance_presence_check":
        "phase1_provenance_presence_check",
    "spec_review_lint": "spec_review_lint",
    "integration_spec_audit": "integration_spec_audit",
    "stage_phase1_compliance": "--stage-id stage_phase1",
    "spec_conformance_check": "spec_conformance_check",
    "behavioral_evidence_per_spec_item_check":
        "behavioral_evidence_per_spec_item_check",
    "dispatcher_awake_gate_check": "dispatcher_awake_gate_check",
    "rtl_unit_test_coverage_check": "rtl_unit_test_coverage_check",
    "stage1_compliance": "stage1_compliance . --json",
    "pdk_consistency_check": "pdk_consistency_check",
}


def _advisory_specs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "advisory_program_exit_zero":
                yield value
            else:
                yield from _advisory_specs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _advisory_specs(value)


def test_all_13_measured_findings_reach_typed_final_audit_dispositions(
        tmp_path, monkeypatch):
    flow_path = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
    flow = yaml.safe_load(flow_path.read_text())
    shipped = list(_advisory_specs(flow))
    selected = []
    for identity, needle in _MEASURED_FINDINGS.items():
        matches = [spec for spec in shipped
                   if needle in (spec if isinstance(spec, str)
                                 else str(spec.get("command", "")))]
        assert len(matches) == 1, (identity, matches)
        selected.append({
            "command": (matches[0] if isinstance(matches[0], str)
                        else matches[0]["command"]),
            "advisory_reason": "issue #1980 injected refusal control",
        })

    monkeypatch.setattr(
        _flow, "_check_program_exit_zero",
        lambda _project, _command: (False, "injected live refusal"),
    )
    result = _flow.check_step(
        tmp_path,
        _step({"all_of": [
            {"advisory_program_exit_zero": spec} for spec in selected
        ]}),
        {},
    )
    final_audit_step = asdict(result)
    records = final_audit_step["advisory_gate_records"]

    assert result.status == "FAIL", result.reasons
    assert len(records) == 13
    assert all(any(needle in record["command"] for record in records)
               for needle in _MEASURED_FINDINGS.values())
    assert {record["exit_code"] for record in records} == {1}
    assert {record["reason_class"] for record in records} == {None}
    assert {record["enforcement"] for record in records} == {"BLOCKING"}


def test_shipped_step31_keeps_perc_and_via_findings_out_of_gate_coverage(
        tmp_path):
    flow_path = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
    step31 = next(step for step in yaml.safe_load(flow_path.read_text())["steps"]
                  if step["id"] == 31)
    producers = {
        "pnr_via_stack_completeness_check",
        "perc_corpus_sweep",
        "lvs_triage_classify",
    }
    assert producers <= set(step31["programs"])
    assert not any(name in str(step31["gate"]) for name in producers)

    reports = tmp_path / "reports" / "phase3"
    reports.mkdir(parents=True)
    (reports / "pnr_via_stack_completeness.json").write_text(
        '{"verdict": "SKIP", "reason": "capability unavailable: no PDK '
        'layer table", "reason_class": "CAPABILITY_ABSENT"}')
    (reports / "perc_sweep.json").write_text(
        '{"rows": [{"welltap": {"status": "WELLTAP_GAP"}, '
        '"xdomain": {"status": "INCOMPLETE"}}], '
        '"reach": {"is_vacuous": false}}')
    (reports / "lvs_triage.json").write_text(
        '{"total": 1, "counts": {"unmatched_net": 1}}')
    before = len(_flow._GATE_LEDGER)

    result = _flow.check_step(tmp_path, step31, {})
    outputs = {record["program"]: record
               for record in result.program_output_records}

    assert outputs["pnr_via_stack_completeness_check"]["verdict"] == "SKIP"
    assert outputs["pnr_via_stack_completeness_check"]["reason_class"] == (
        "CAPABILITY_ABSENT")
    assert outputs["perc_corpus_sweep"]["findings"] == [
        "INCOMPLETE", "WELLTAP_GAP"]
    assert outputs["perc_corpus_sweep"]["verdict"] == "PRODUCED"
    assert all(record["enforcement"] == "NOT_A_GATE"
               for record in outputs.values())
    newly_run = _flow._GATE_LEDGER[before:]
    assert not any(record["gate"] in producers for record in newly_run)
