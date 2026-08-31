"""Regression for #1951: interrupt pending/selection/ACK identity capture.

The test is candidate-owned but accepts ``VIBE_PROGRAMS`` so the exact same
assertions can run against an immutable BASE or a reverted scratch worktree.
Only a generic input specification is used; no scorer-side artefact is read.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


PROGRAMS = Path(os.environ.get(
    "VIBE_PROGRAMS", Path(__file__).resolve().parents[1])).resolve()
PLUGIN = PROGRAMS.parent
AGENT = PLUGIN / "agents" / "ic-expert-agent.md"
DB = PLUGIN / "agents" / "ic_expert_db" / "ic_expert_db.json"
sys.path.insert(0, str(PROGRAMS))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


DETECT = _load("issue1951_selftb", "spec_selftb_coverage_detect.py")
PACK = _load("issue1951_pack", "ic_expert_backup_pack.py")
DIGEST = _load("issue1951_digest", "_lesson_digest.py")
DB_CHECK = _load("issue1951_db_check", "ic_expert_db_consistency_check.py")

INTERRUPT_SPEC = (
    "Implement a parameterized priority interrupt controller. Capture request "
    "inputs as pending, present an interrupt identity to the CPU, and clear the "
    "serviced request when cpu_ack is asserted. The priority policy may permit "
    "a higher-priority pending request to preempt the current presentation."
)


def _ids(items):
    return [item["id"] for item in items]


def test_program_emits_complete_interrupt_lifecycle_contract():
    result = DETECT.detect_selftb_coverage(INTERRUPT_SPEC)

    assert "interrupt_controller" in result["shapes"]
    assert _ids(result["authoring_invariants"]) == [
        "identity_separation",
        "registered_strict_preemption",
        "ack_active_identity",
        "held_request_suppression",
        "minimum_index_width",
    ]
    assert _ids(result["self_tb_scenarios"]) == [
        "arrival_during_service",
        "ack_plus_new_request",
        "held_request_through_ack",
        "recovery_tail_timing",
    ]
    assert result["parameter_sweeps"] == [{
        "id": "single_interrupt",
        "parameters": {"NUM_INTERRUPTS": 1},
        "requirement": "Compile and simulate the full ACK/re-arm path at N=1.",
    }]
    requirement = result["requirement"]
    for marker in ("PENDING", "SELECTED/PRESENTED", "ACTIVE/ACK",
                   "REGISTERED pending", "STRICTLY HIGHER", "NUM_INTERRUPTS=1"):
        assert marker in requirement


def test_backup_handoff_preserves_structured_interrupt_contract(tmp_path):
    handoff = PACK.assemble(
        INTERRUPT_SPEC, None, None, [], [], tmp_path, k=1)
    requirements = [r for r in handoff["spec_requirements"]
                    if r["kind"] == "self_tb_coverage"]

    assert len(requirements) == 1
    requirement = requirements[0]
    assert _ids(requirement["authoring_invariants"])[0:3] == [
        "identity_separation",
        "registered_strict_preemption",
        "ack_active_identity",
    ]
    assert _ids(requirement["self_tb_scenarios"]) == [
        "arrival_during_service",
        "ack_plus_new_request",
        "held_request_through_ack",
        "recovery_tail_timing",
    ]
    assert requirement["parameter_sweeps"][0]["parameters"] == {
        "NUM_INTERRUPTS": 1}


def test_expert_skill_and_rendered_digest_distinguish_all_three_roles(tmp_path):
    source = AGENT.read_text()
    title = (
        "### Skill: priority arbiter — keep PENDING, SELECTED, and ACTIVE/ACK "
        "identities distinct")
    lifecycle = (
        "### Skill: interrupt service lifecycle — preemption is "
        "spec-controlled, ACK identity is latched, and held levels do not requeue")

    assert title in source
    assert lifecycle in source
    source_lower = source.lower()
    for marker in ("registered pending state", "strictly higher priority",
                   "ack plus a new request", "num_interrupts=1",
                   "no stale identity replay"):
        assert marker in source_lower

    assert DIGEST.render_lesson_digest(tmp_path, expert_md=AGENT) > 0
    rendered = (tmp_path / "lessons.md").read_text()
    assert title in rendered
    assert lifecycle in rendered


def test_expert_db_replaces_unconditional_live_winner_advice():
    database = json.loads(DB.read_text())
    entry = next(e for e in database["entries"]
                 if e["ic_class"] == "fsm-register-interface")
    lessons = " ".join(entry["lessons"])

    assert "three distinct roles: registered pending state" in lessons
    assert "strictly higher-priority request" in lessons
    assert "ACK clears the latched active identity" in lessons
    assert "level held through ACK cannot requeue" in lessons
    assert "max(1, clog2(NUM_INTERRUPTS))" in lessons
    assert "takes over the one in service" not in lessons
    assert DB_CHECK.check(DB)["pass"]


def test_non_interrupt_prompt_has_no_interrupt_contract():
    result = DETECT.detect_selftb_coverage(
        "Design a purely combinational two-input multiplexer with a select pin.")
    assert result["authoring_invariants"] == []
    assert result["self_tb_scenarios"] == []
    assert result["parameter_sweeps"] == []
