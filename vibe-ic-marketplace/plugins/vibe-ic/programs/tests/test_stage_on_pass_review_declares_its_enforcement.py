#!/usr/bin/env python3
"""`stage_on_pass_review` says which kind of gate it is, and says it truly.

WHAT WENT WRONG
===============
The program arrived in the flow (stage 1 at v1.12.87, stage 2 at v1.13.2) with
no `ENFORCEMENT:` line, and `flow_gate_enforcement_audit` refused the tree for
it:

    [FAIL] 1 NEW gate(s) are AUDIT_ONLY and declare no intent at all
       undeclared::stage_on_pass_review

That refusal is the audit's whole point, stated in its own docstring: until a
gate says which, "wired where it cannot block" and "nobody decided" are the
same record. AUDIT_ONLY was the true wiring — the flow's two clauses are
`program_exit_zero`, read in `final_audit` and not inline, so nothing invokes
this where its rc could stop a step — and advisory was the true intention, and
neither was written down.

WHY THREE TESTS AND NOT ONE
===========================
A declaration can fail three different ways and only the first is obvious.

  1. It can be ABSENT.
  2. It can be PRESENT AND UNREAD. `declared_intent` searches only the first
     `DECL_WINDOW_BYTES` (4000); two paragraphs of prose added above a
     declaration moved one to byte 4371 and silently undid it on 2026-08-22.
     A gate that has been silently un-declared reads exactly like one that
     never declared. This one sits at byte 2093 today — measured, and the
     figure is reported by the assertion rather than pinned by it.
  3. It can be PRESENT, READ, AND FALSE — the flow saying one thing at the
     site that owns the decision (`on_pass_review: verdict:`) while the
     program says another. Two records of one fact drift, and this repo has
     the measurement to prove it.

Every one of the three asks `flow_gate_enforcement_audit` itself rather than
re-typing its regex: a re-typed pattern is a fourth copy of the rule and would
pass while the audit failed.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
PROG = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))
import flow_gate_enforcement_audit as A  # noqa: E402

_GATE = "stage_on_pass_review"
_DECLARATION = "ENFORCEMENT: advisory"


def test_the_audit_reads_an_advisory_declaration():
    """RETURNED VALUE, not a grep — `declared_intent` is the function the
    audit calls, so this cannot pass while the audit reports UNDECLARED."""
    assert A.declared_intent(PROGRAMS, _GATE) == "advisory", (
        f"{PROG.name} declares no intent the audit can read. It is AUDIT_ONLY "
        f"— the flow's clauses are `program_exit_zero`, which is read in "
        f"final_audit and not inline — so `flow_gate_enforcement_audit` "
        f"refuses the tree until the gate says whether that was the decision.")


def test_the_declaration_is_inside_the_window_the_audit_reads():
    """PRESENT AND UNREAD is the failure mode a plain grep cannot see."""
    idx = PROG.read_text(encoding="utf-8").index(_DECLARATION)
    # ONE ASSERTION, AND IT IS THE AUDIT'S OWN RULE. A second one pinning a
    # minimum headroom was drafted and removed: any threshold for "enough room
    # left" is a number invented here, unrelated to anything the audit reads,
    # and a test that fails on a number nobody derived is the failure mode this
    # repo has measured seven times in `test_liar_census`. The margin is
    # REPORTED instead, in the message, where it is useful to whoever has just
    # pushed the declaration further down.
    assert idx < A.DECL_WINDOW_BYTES, (
        f"the declaration sits at byte {idx}; `declared_intent` reads only "
        f"the first {A.DECL_WINDOW_BYTES}, so it is present and UNREAD and "
        f"the gate now reports as UNDECLARED with the line still in the file. "
        f"Prose added ABOVE it is what moves it. Move the declaration up.")
    assert idx >= 0


def test_the_program_and_the_flow_do_not_disagree_about_the_verdict():
    """The two records of one fact, compared.

    The flow's `on_pass_review:` block is the site that OWNS the decision —
    the program's own docstring says so ("THE DECLARATION LIVES IN THE FLOW,
    NOT HERE") — and its `verdict:` is what the program prints back on a
    rejection. The `ENFORCEMENT:` line is a second copy of that fact for a
    reader (the audit) that does not read the flow per stage. Two copies
    drift; this is the comparison that makes them not."""
    text = FLOW.read_text(encoding="utf-8")
    verdicts = []
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("on_pass_review:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("verdict:"):
                verdicts.append(stripped.split(":", 1)[1].strip().strip('"\''))
                in_block = False
            elif stripped and not line.startswith(" " * 6):
                in_block = False
    assert verdicts, (
        "no `on_pass_review:` block in the flow declares a `verdict:`, so "
        "this comparison has an empty denominator and proves nothing")
    assert set(verdicts) == {A.declared_intent(PROGRAMS, _GATE)}, (
        f"the flow declares {sorted(set(verdicts))} for the on-pass review "
        f"and {PROG.name} declares "
        f"{A.declared_intent(PROGRAMS, _GATE)!r}. One of the two moved.")
