#!/usr/bin/env python3
"""The review task self-describes every envelope field its validator enforces.

The 2026-09-01 failure shape: ``_validate_ai_review`` rejected all 41/41 AI
reviews of a run with the same five envelope reasons (missing top-level
hashes, ``reviewer: null``, ``blind: null``) because the reviewer wrote what
``review_requirements`` described -- and that self-description omitted the
fields the validator enforces.  This module pins producer and consumer to one
contract: fields the validator names in a rejection reason must be described
inside ``review_requirements``, and a review assembled from the task's own
``required_envelope`` must be ACCEPTED.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd                         # noqa: E402
import benchmark_io_adapter as bio                      # noqa: E402

ROUTING = {
    "nature": "spec_generation",
    "route": "SPEC_TO_RTL",
    "source": "no_context_heuristic",
    "needs_ai_parse": True,
}


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "input" / "phase1_prompt.md").write_text(
        "Design module dut with input a and output y; assign y = a.\n")
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    report = project / "reports" / "orchestrator"
    report.mkdir(parents=True)
    (report / "phase2_one_shot.json").write_text(json.dumps({
        "verdict": "PASS",
        "steps": [{
            "name": "rtl_gen", "status": "PASS", "detail": "fixture",
            "extras": {"deterministic_generator": "fixture_emitter"},
        }],
    }))
    return project


def _task(tmp_path: Path) -> dict:
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    got = bio.collect("rtllm", "p1", project)
    return bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")


def _rejection_reasons(task: dict, review: dict) -> list[str]:
    review_path = Path(task["review_path"])
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review))
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert verdict["reasons"]
    return [str(r) for r in verdict["reasons"]]


#: Field-shaped vocabulary inside a rejection reason: dotted paths and schema
#: ids, snake_case field names, and ALL-CAPS enum values.  Anything the
#: validator names this way is part of the envelope contract and must be
#: self-described by the task.
_FIELD_TOKEN = re.compile(
    r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+"
    r"|[a-z][a-z0-9]*_[a-z0-9_]+"
    r"|\b[A-Z][A-Z_]+\b")


def _has_path(node, parts: list[str]) -> bool:
    if not parts:
        return True
    if isinstance(node, dict):
        for key, value in node.items():
            if key == parts[0] and _has_path(value, parts[1:]):
                return True
            if _has_path(value, parts):
                return True
    elif isinstance(node, list):
        return any(_has_path(value, parts) for value in node)
    return False


def _undescribed(requirements: dict, reasons: list[str]) -> list[str]:
    blob = json.dumps(requirements)
    missing = []
    for reason in reasons:
        for token in _FIELD_TOKEN.findall(reason):
            described = (token in blob
                         or ("." in token
                             and _has_path(requirements, token.split("."))))
            if not described:
                missing.append(f"{token!r} (from reason: {reason})")
    return missing


def test_every_empty_envelope_rejection_is_self_described(tmp_path):
    task = _task(tmp_path)
    reasons = _rejection_reasons(task, {})
    assert not _undescribed(task["review_requirements"], reasons)


def test_every_override_and_fail_rejection_is_self_described(tmp_path):
    task = _task(tmp_path)
    reasons = _rejection_reasons(task, {
        "schema": bd._AI_REVIEW_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "rtl_sha256": task["rtl_sha256"],
        "reviewer": {"kind": "AI", "model": "test-review-model"},
        "blind": {"oracle_accessed": False},
        "routing": {"verdict": "OVERRIDE_PROGRAM"},
        "override": {"prompt_evidence": "not-a-list"},
        "semantic_review": {
            "verdict": "FAIL",
            "findings": ["output y is inverted versus the prompt"],
            "rationale": "The RTL contradicts the prompt's assignment.",
        },
        "verification_test": {},
    })
    assert not _undescribed(task["review_requirements"], reasons)


def test_required_envelope_carries_the_tasks_own_binding_values(tmp_path):
    task = _task(tmp_path)
    envelope = task["review_requirements"]["required_envelope"]
    assert envelope["schema"] == bd._AI_REVIEW_SCHEMA
    assert envelope["id"] == task["id"]
    assert envelope["prompt_sha256"] == task["prompt_sha256"]
    assert envelope["rtl_sha256"] == task["rtl_sha256"]
    assert envelope["reviewer"]["kind"] == "AI"
    assert envelope["blind"]["oracle_accessed"] is False
    assert envelope["verification_test"]["schema"] == bd._CHALLENGE_SCHEMA
    assert envelope["verification_test"]["path"] == task["challenge_path"]
    assert (envelope["verification_test"]["top_module"]
            == "vibeic_ai_challenge_tb")


def test_a_review_assembled_from_the_envelope_is_accepted(tmp_path):
    task = _task(tmp_path)
    envelope = task["review_requirements"]["required_envelope"]
    review = {
        "schema": envelope["schema"],
        "id": envelope["id"],
        "prompt_sha256": envelope["prompt_sha256"],
        "rtl_sha256": envelope["rtl_sha256"],
        "reviewer": {"kind": envelope["reviewer"]["kind"],
                     "model": "test-review-model"},
        "blind": {"oracle_accessed": envelope["blind"]["oracle_accessed"]},
        "routing": {"verdict": "AGREE",
                    "ai_nature": task["program_routing"]["nature"]},
        "semantic_review": {
            "verdict": "PASS", "findings": [],
            "rationale": "Ports and combinational behavior match the prompt.",
        },
    }
    review_path = Path(task["review_path"])
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review))
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED", verdict["reasons"]
