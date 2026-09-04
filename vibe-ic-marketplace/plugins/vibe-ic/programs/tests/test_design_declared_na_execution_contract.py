#!/usr/bin/env python3
"""Executable A/B contract for non-protocol arithmetic Step-4 questions.

The fixture is derived from the input contract, not from a benchmark name:
L3 explicitly says whether command opcodes exist and L9 explicitly declares
the per-item behavioural population.  The real shipped gate programs execute;
no mocked verdict, report, waiver, threshold, oracle, or harness is involved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as T  # noqa: E402
import flow_compliance_check as F  # noqa: E402


STATE_CMD = (
    "functional_state_transition_coverage_check "
    "phase2/stage1/sim/tb --coverage "
    "reports/phase2/coverage/coverage_actual.json --json "
    "reports/phase2/gates/functional_state_transition_coverage.json"
)
BEHAVIOR_CMD = (
    "behavioral_evidence_per_spec_item_check . --json "
    "reports/phase2/gates/behavioral_evidence_per_spec_item.json"
)


def _seed(tmp_path: Path, *, opcodes: list, requirements: list) -> Path:
    project = tmp_path / "arithmetic_input"
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "command_protocol_applicable": bool(opcodes),
        "no_opcodes_in_input": not opcodes,
        "opcodes": opcodes,
    }))
    l9 = {
        "top_module": "arithmetic_core",
        "top_level_ports": [
            {"name": "clk", "direction": "input"},
            {"name": "data_in", "direction": "input"},
            {"name": "data_out", "direction": "output"},
        ],
    }
    if requirements:
        l9["behavioral_requirements"] = requirements
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))

    tb = project / "phase2" / "stage1" / "sim" / "tb"
    tb.mkdir(parents=True)
    (tb / "tb_arithmetic_core.v").write_text(
        "module tb_arithmetic_core; initial begin #1; $finish; end endmodule\n")
    coverage = project / "reports" / "phase2" / "coverage"
    coverage.mkdir(parents=True)
    # This is deliberately empty for the A/B discriminator. It is not a fake
    # passing report: A's design declaration makes the protocol population N/A;
    # B's declared opcode must turn the same bytes into a refusal.
    (coverage / "coverage_actual.json").write_text("[]\n")
    return project


def _step() -> dict:
    return {
        "id": "contract-a-b",
        "name": "prompt-derived applicability contract",
        "stage": "stage1",
        "gate": {"all_of": [
            {"program_exit_zero": STATE_CMD},
            {"program_exit_zero": BEHAVIOR_CMD},
        ]},
    }


def test_a_explicit_empty_design_populations_do_not_deduct_the_step(tmp_path):
    project = _seed(tmp_path, opcodes=[], requirements=[])
    F._GATE_LEDGER.clear()

    result = F.check_step(project, _step(), {})

    assert result.status == "PASS", result.reasons
    assert result.partial_vacuity_disclosed is False
    assert result.executed_declared_not_applicable == [STATE_CMD, BEHAVIOR_CMD]
    rows = F._GATE_LEDGER[-2:]
    assert [(r["gate"], r["exit_code"], r["verdict"], r["reason_class"])
            for r in rows] == [
        ("functional_state_transition_coverage_check", 2,
         "NOT_APPLICABLE", T.DESIGN_DECLARED_NA),
        ("behavioral_evidence_per_spec_item_check", 2,
         "NOT_APPLICABLE", T.DESIGN_DECLARED_NA),
    ]


def test_b_declared_opcode_without_transition_evidence_fails(tmp_path):
    project = _seed(
        tmp_path,
        opcodes=[{"opcode": "0x31", "name": "START"}],
        requirements=[],
    )

    result = F.check_step(project, _step(), {})

    assert result.status == "FAIL", result.reasons
    assert any("declares 1 command opcode" in reason for reason in result.reasons)


def test_b_declared_behavior_without_evidence_fails(tmp_path):
    project = _seed(
        tmp_path,
        opcodes=[],
        requirements=[{"id": "result_becomes_valid"}],
    )

    result = F.check_step(project, _step(), {})

    assert result.status == "FAIL", result.reasons
    assert any("behavioral_evidence_per_spec_item_check" in reason
               for reason in result.reasons)
    assert result.executed_declared_not_applicable == [STATE_CMD]


def test_consumer_reloads_the_declaration_and_binds_the_executed_program(tmp_path):
    project = _seed(tmp_path, opcodes=[], requirements=[])

    execution = F._check_program_exit_zero(project, STATE_CMD)
    assert execution.verdict == "NOT_APPLICABLE"
    report_path = (
        project / "reports/phase2/gates/functional_state_transition_coverage.json")
    report = json.loads(report_path.read_text())
    assert F._report_proves_executed_design_na(project, report, STATE_CMD)

    wrong_program = dict(report)
    wrong_program["program"] = "behavioral_evidence_per_spec_item_check"
    assert not F._report_proves_executed_design_na(
        project, wrong_program, STATE_CMD)

    l3_path = project / "phase1/generated_docs/L3_CMD_PROTOCOL.json"
    l3 = json.loads(l3_path.read_text())
    l3["opcodes"] = [{"opcode": "0x31", "name": "START"}]
    l3["no_opcodes_in_input"] = False
    l3_path.write_text(json.dumps(l3))
    assert not F._report_proves_executed_design_na(project, report, STATE_CMD)
