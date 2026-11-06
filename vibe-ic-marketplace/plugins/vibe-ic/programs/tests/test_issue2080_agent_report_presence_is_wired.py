#!/usr/bin/env python3
"""vibe-ic#2080 — `agent_report_presence_check` was credited by an error message.

WHAT WAS MEASURED ON THE PRE-FIX TIP (94617408759e)
===================================================
`gate_is_wired_check` moved from the NAME rule to `invocation.v1` and made ten
gates visible as unwired. This is one of them. Its only credit anywhere in the
tree was a token inside a string another program PRINTS:

    programs/agent_report_sha256_attestation_check.py:351
        "; agent_report_presence_check owns that failure mode."

`checker_execution_wiring_baseline.json` had recorded exactly that since
vibe-ic#1347 — "Never wired; it only LOOKED wired because
`agent_report_sha256_attestation_check` names it in an error message".

WHY IT MATTERS, AND IT IS NOT AN ABSTRACT LEDGER GAP
====================================================
That sibling **is** wired (registered in
`flow_compliance_check._STRUCTURAL_RTL_GATES`), and it DEFERS by name:

    "AGENT_REPORT.md missing — `agent_report_presence_check` handles that as
     FAIL; this gate stays out of the way and emits VACUOUS."

So a project that finished with NO final report card at any canonical location
reached no verdict at all: the wired gate declined on the ground that the
unwired one owned it.

WHAT THE FIX IS, AND WHAT IT DELIBERATELY IS NOT
================================================
`design_one_shot_runner.step_agent_report_presence` runs the gate right after
the final audit and records its verdict, ADVISORY (vibe-ic#2080's rule: BLOCKING
only where the gate's own docstring says so; vibe-ic#1253: making a red gate
blocking is a different repair). Its row is removed from
`gate_is_wired_baseline.json` and from `checker_execution_wiring_baseline.json`
in the same commit.

The gate's POPULATION is untouched. It asks about `AGENT_REPORT.md` only, and
nothing in the shipped flow writes that file — the canonical report card moved
to `reports/final_summary.md` in v1.6.32 and this gate was never re-pointed —
so on a real run the row reports FINDING. That is the honest verdict and it is
recorded as one; the row carries the canonical report's presence as a SEPARATE
field so a reader can tell "no report card at all" from "the v1.6.32 one, and
this gate has not been re-pointed at it". Widening the gate is a decision about
what a report card IS and is not made here.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as DOSR                      # noqa: E402

_DISPATCH = "plan.append(step_agent_report_presence(project))"
_GATE = "agent_report_presence_check"

_GOOD_REPORT = """# AGENT_REPORT

## Verdict
PASS.

## Acceptance evidence
Everything below.

## Waivers list
None.

## Discoveries
None.

## Iteration log
One wave.
"""




def test_the_runner_dispatches_the_gate_at_a_real_call_site() -> None:
    src = Path(DOSR.__file__).read_text(errors="replace")
    assert _DISPATCH in src, (
        f"design_one_shot_runner no longer dispatches {_GATE} ({_DISPATCH!r} "
        f"absent). Under invocation.v1 the gate goes back to being credited by "
        f"nothing but an error message — vibe-ic#2080.")


def test_the_gate_left_both_unwired_registers() -> None:
    """The register shrinks in the commit that wires the gate, in BOTH places.

    Two registers recorded this gate, measured under different rules, and
    leaving either one behind turns a paid debt into standing permission.
    """
    wired = json.loads(
        (_PROGRAMS / "gate_is_wired_baseline.json").read_text())
    assert _GATE not in wired["unwired"], (
        "gate_is_wired_baseline.json still records this gate as unwired; a "
        "register that outlives the debt it names is permission, not a ratchet.")
    assert _GATE not in wired.get("skill_only", [])
    checkers = json.loads(
        (_PROGRAMS / "checker_execution_wiring_baseline.json").read_text())
    assert _GATE + ".py" not in checkers["known"], (
        "checker_execution_wiring_baseline.json still records this checker as "
        "test-only; its own audit FAILs on a recorded checker that has gained a "
        "runner, precisely so the shrink cannot be skipped.")
    assert _GATE + ".py" not in (checkers.get("triage") or {}), (
        "the triage note for this checker outlived its `known` row; the writer "
        "drops triage entries that leave `known`, and a note about an entry "
        "that is gone is a statement about a state that no longer exists.")


def test_the_step_can_never_move_the_run_verdict() -> None:
    src = Path(DOSR.__file__).read_text(errors="replace")
    step = next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef)
                and n.name == "step_agent_report_presence")
    statuses = {c.args[1].value for c in ast.walk(step)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "StepResult" and len(c.args) >= 2
                and isinstance(c.args[1], ast.Constant)}
    # R-0915-85 — `ADVISORY` was a VERDICT meaning "this row may never move the
    # run's". It is `PASS` carrying `Disclosure.ADVISORY` now, and the property
    # stops being a special case: `run_verdict`'s precedence means a PASS row
    # cannot move the run word in either direction.
    assert statuses == {"PASS"}, (
        f"step_agent_report_presence returns {sorted(statuses)}; vibe-ic#2080 "
        f"wires a recorded-unwired gate a row carrying the advisory disclosure unless its docstring declares "
        f"it BLOCKING, and this gate's does not.")


# ---------------------------------------------------------------------------
# THE VERDICT MOVES ON THE SUBJECT — BOTH DIRECTIONS
# ---------------------------------------------------------------------------
