#!/usr/bin/env python3
"""SALVAGE #315 — the L22 coverage-goal emitter must be WIRED, not orphaned.

An emitter nothing runs is not a landing. `l22_coverage_goal_emit` closes
`l22_verification_plan_measurable_check`'s TARGET_OUTSIDE_CONSUMING_LAYER
finding only if the phase-1 runner actually invokes it on every run, AFTER
`L22_VERIFICATION_PLAN.json` exists on disk (the emitter SKIPs — never
fabricates — when the doc is absent).

Three things are pinned here, none of them a grep for a string:
  1. the runner exposes the wiring as a module-level helper, and calling
     that helper on a real fixture moves the REAL consumer gate FAIL -> PASS;
  2. the helper is invoked from the runner's `main()`, and the call sits
     AFTER the L19-L23 skeleton emit that creates the doc it writes into;
  3. the helper degrades to a no-op (never a crash, never a fabricated goal)
     when L22 is absent or when the design states no target.

All fixtures are synthesized neutral data — no design, PDK or vendor
literal. chip-AGNOSTIC.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_RUNNER_SRC = _PROGRAMS / "phase1_doc_one_shot_runner.py"
_GATE_PATH = _PROGRAMS / "l22_verification_plan_measurable_check.py"

import phase1_doc_one_shot_runner as R  # noqa: E402

HELPER = "_post_emit_l22_coverage_goals"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_gate = _load(_GATE_PATH, "l22_verification_plan_measurable_check") \
    if _GATE_PATH.is_file() else None
_needs_gate = pytest.mark.skipif(
    _gate is None, reason=f"consumer gate absent: {_GATE_PATH.name}")

_DOC_WITH_TARGET = (
    "# Verification\n"
    "The block must reach at least 95% branch coverage on the random run.\n"
)
_DOC_NO_TARGET = (
    "# Verification\n"
    "The block shall be verified against a golden model for all operands.\n"
)


def _mk(project: Path, doc_text: str, *, with_l22: bool = True) -> None:
    if with_l22:
        gd = project / "phase1" / "generated_docs"
        gd.mkdir(parents=True, exist_ok=True)
        (gd / "L22_VERIFICATION_PLAN.json").write_text(json.dumps({
            "doc_id": "L22",
            "doc_name": "L22_VERIFICATION_PLAN",
            "applicability": "APPLICABLE",
            "extraction_status": "NOT_YET_EXTRACTED",
            "fields": {
                "coverage_goals": [],
                "formal_properties": [],
                "verification_plan_present": "implicit",
                "verification_categories_derived_from_spec": ["a", "b"],
            },
        }, ensure_ascii=False), encoding="utf-8")
    d = project / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L7_verification.md").write_text(doc_text, encoding="utf-8")


# ─────────────────────────────── 1. the helper really closes the gate ──
def test_runner_exposes_the_wiring_helper():
    assert hasattr(R, HELPER), (
        f"phase1_doc_one_shot_runner.{HELPER} is missing — the emitter "
        f"would be an orphan program nothing runs")
    assert callable(getattr(R, HELPER))


@_needs_gate
def test_helper_moves_the_real_consumer_gate_fail_to_pass(tmp_path):
    """Bidirectional, through the RUNNER's own entry point."""
    _mk(tmp_path, _DOC_WITH_TARGET)
    before = _gate.inspect(tmp_path)
    assert before["verdict"] == "FAIL", before
    assert "TARGET_OUTSIDE_CONSUMING_LAYER" in [
        f["id"] for f in before["blocking_findings"]], before

    n = getattr(R, HELPER)(tmp_path)
    assert n == 1, f"runner wiring lifted {n} goals, expected 1"

    after = _gate.inspect(tmp_path)
    assert after["verdict"] == "PASS", after
    assert after["blocking_findings"] == [], after


# ───────────────────────────── 2. it is actually CALLED, in the right place ──
def _main_body():
    tree = ast.parse(_RUNNER_SRC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("phase1_doc_one_shot_runner.main() not found")


def _call_lines(fn: ast.AST, name: str):
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == name:
            out.append(node.lineno)
    return out


def test_main_calls_the_helper():
    lines = _call_lines(_main_body(), HELPER)
    assert lines, (
        f"{HELPER} is defined but NEVER CALLED from main() — an emitter "
        f"nothing runs is not wired")


def test_the_call_runs_after_the_l19_l23_skeleton_emit():
    """The emitter writes INTO L22_VERIFICATION_PLAN.json, so it must run
    after the step that creates it — otherwise it SKIPs on every run and the
    wiring is decorative."""
    body = _main_body()
    skeleton = _call_lines(body, "_emit_l19_to_l23_skeletons")
    ours = _call_lines(body, HELPER)
    assert skeleton, "_emit_l19_to_l23_skeletons is no longer called by main()"
    assert ours, f"{HELPER} is never called from main()"
    assert min(ours) > max(skeleton), (
        f"{HELPER} is called at line {min(ours)}, BEFORE the L19-L23 skeleton "
        f"emit at line {max(skeleton)} — L22 would not exist yet and the "
        f"emitter would SKIP on every run")


# ──────────────────────────────────────── 3. refuses rather than guesses ──
def test_no_stated_target_emits_nothing(tmp_path):
    _mk(tmp_path, _DOC_NO_TARGET)
    assert getattr(R, HELPER)(tmp_path) == 0
    doc = json.loads((tmp_path / "phase1" / "generated_docs"
                      / "L22_VERIFICATION_PLAN.json").read_text())
    assert doc["fields"]["coverage_goals"] == [], (
        "a goal was fabricated out of a document that states none")


def test_missing_l22_is_a_noop_not_a_crash(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET, with_l22=False)
    assert getattr(R, HELPER)(tmp_path) == 0


def test_rerun_is_idempotent(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET)
    assert getattr(R, HELPER)(tmp_path) == 1
    assert getattr(R, HELPER)(tmp_path) == 0, "re-run duplicated the goal"
    doc = json.loads((tmp_path / "phase1" / "generated_docs"
                      / "L22_VERIFICATION_PLAN.json").read_text())
    assert len(doc["fields"]["coverage_goals"]) == 1
