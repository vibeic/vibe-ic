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

_GATE = "stage_on_pass_review"
_DECLARATION = "ENFORCEMENT: advisory"








# ─────────────────────────────────────────────────────────────────────────
# THE RULE-ID SET. Five stages now declare an on-pass review, and two PAIRS
# of them share an `emit_test_dir`:
#
#     reports/phase2/gates/on_pass_review   stage1, stage2
#     reports/phase3/gates/on_pass_review   stage3, stage4
#     reports/analog/on_pass_review         stage_analog
#
# The only thing keeping two rejections in one directory from overwriting
# each other is the emit filename, `emit_dir / f"test_{rule_id.lower()}.py"`,
# so the rule ids have to be distinct AFTER `.lower()`.
#
# MEASURED that they are, and MEASURED what happens when they are not. With a
# duplicate id planted into `_RULES` in-process, both rules RAN and both
# rejections were recorded — and exactly ONE file was emitted, the second
# rejection silently overwriting the first. `_EMITTERS` is a dict keyed by
# rule id, so the duplicate also collapses to one emitter. Nothing in the
# program refuses that; this is what does.
# ─────────────────────────────────────────────────────────────────────────
def _rule_ids():
    import stage_on_pass_review as S  # noqa: PLC0415
    return [(stage, rid) for stage, rules in S._RULES.items() for rid, _ in rules]


def test_every_rule_id_is_unique_after_lowercasing():
    """`.lower()` is the key that reaches the filesystem, so it is the key
    that has to be unique — `R1_X` and `r1_x` would pass a case-sensitive
    check and collide on disk."""
    ids = _rule_ids()
    assert ids, "no rule is registered; empty denominator"
    lowered = [rid.lower() for _, rid in ids]
    dupes = sorted({x for x in lowered if lowered.count(x) > 1})
    assert not dupes, (
        f"{dupes} appear more than once in `_RULES`. Two rules sharing an id "
        f"share one `_EMITTERS` entry and one emitted filename, so the second "
        f"rejection overwrites the first and nothing says so.")


def test_no_two_rules_emit_to_the_same_path():
    """The property the ids exist to give, asserted where it actually bites:
    the full path, `emit_test_dir` included, because two stages sharing a
    directory is now the normal case and not the exception."""
    import yaml  # noqa: PLC0415
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    dirs = {}

    def walk(node, sid=None):
        if isinstance(node, dict):
            here = str(node["id"]) if "id" in node else sid
            if "on_pass_review" in node:
                dirs[here] = node["on_pass_review"].get("emit_test_dir")
            for v in node.values():
                walk(v, here)
        elif isinstance(node, list):
            for v in node:
                walk(v, sid)

    walk(doc)
    paths = {}
    for stage, rid in _rule_ids():
        assert stage in dirs, f"`_RULES` has {stage!r}, the flow does not"
        paths.setdefault(f"{dirs[stage]}/test_{rid.lower()}.py", []).append(stage)
    assert paths, "empty denominator"
    collisions = {p: s for p, s in paths.items() if len(s) > 1}
    assert not collisions, collisions
    # AND the shared directories are real, so this test is not passing for
    # want of a pair to collide. If every stage got its own directory this
    # assertion would fire and the test above would be the whole guard.
    shared = [d for d in set(dirs.values()) if list(dirs.values()).count(d) > 1]
    assert shared, ("no two stages share an `emit_test_dir` any more, so this "
                    "test no longer exercises the case it was written for")
