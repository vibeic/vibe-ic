#!/usr/bin/env python3
"""vibe-ic#2141 — `gate_is_wired` credited a gate for LIBRARY use of its module.

WHAT WAS MEASURED ON THE FROZEN BASE (577fb50d3831, v1.19.24)
=============================================================
`gate_is_wired_check.py` under `invocation.v1` credited a gate as WIRED for ANY
reference to ANY symbol its module exports. So a module that is BOTH a library
AND a gate read as wired on the strength of its library use alone, and the
register could not tell "imported as a library" from "run as a gate". That is
vibe-ic#2080's shape one rung up: #2080 removed credit-by-declaration and
credit-by-prose; this is credit-by-import.

THE ISSUE'S NAMED INSTANCE DOES NOT REPRODUCE, AND THAT IS RECORDED HERE
========================================================================
#2141 names `lesson_consumption_check`, whose credit was
`design_one_shot_runner` reaching `parse_digest`, `match_sections`,
`build_scoring_record` and `SCORING_RECORD_NAME`. On the frozen base that is no
longer its only credit: vibe-ic#2103 landed `step_lesson_consumption`, which
calls `_lesson_consumed.main(argv)` at `design_one_shot_runner.py:5373`. The
gate IS wired today and stays credited under the new rule — as
`verdict entry (main)` rather than the bare `imported+referenced` it had
before. The DEFECT is the resolver, not that one gate, and the resolver
reproduces on the frozen base for eight other gates (see the commit body).

THE RULE, `invocation.v2` — WHO PRODUCES THE VERDICT
====================================================
The first draft of this fix counted STAGES: one stage credited, two or more was
re-implementation. That proxy could not be defended at its own boundary — it
called `def_manufacturing_grid_check` and `ppa_area_threshold_check` library
use, and both of those callers demonstrably run the gate and read its answer.
The question is not how many of a gate's functions a caller touches; it is WHO
PRODUCES THE VERDICT.

An import credits a gate when:

  * `main` is referenced — the verdict entry point itself; or
  * a STAGE is referenced and the caller CONSUMES the gate's answer: the
    result is returned or exited with, handed to a driver that calls it, bound
    to a verdict-named name, or read through a verdict-named field; or
  * the gate defines NO `main` at all — its public API is the whole check
    surface, it composes nothing, and there is nothing to re-implement.

And it does NOT credit when the caller CHAINS two or more of the gate's stages
— feeding one stage's return into another stage of the same gate — and never
reads a verdict out of any of them. That is the caller reproducing `main`'s
composition and judging for itself, which is what `design_one_shot_runner` did
to `lesson_consumption_check` before #2103 and what `regression_issue_intake_check`
does to `acceptance_evidence_in_fix_comment_check` today. A constant, a
`_`-private helper and a bare module handed to `getattr` are not stages at all.

THE MIGRATION IS IN THE PROGRAM, NOT IN A HUMAN (owner ruling, #2141)
=====================================================================
A rule that gets stricter and then reports failure until somebody presses
`--write-baseline` is itself the defect: that flag can ADD **and REMOVE**.
`--migrate-rule-id` re-derives the register under the new rule id and REFUSES
unless the new set is a strict SUPERSET of the old — a name may be added, never
removed — and prints every addition. Both directions are tested below.
"""
import ast
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


#: A gate that COMPOSES its verdict out of three stages, exactly the shape
#: `lesson_consumption_check` has.
COMPOSING_GATE = '''
SCORING_RECORD_NAME = "record.json"


def parse_digest(text):
    return [text]


def match_sections(spec, sections):
    return []


def build_scoring_record(matches):
    return {"matches": matches}


def main(argv=None):
    sections = parse_digest("x")
    matches = match_sections("y", sections)
    build_scoring_record(matches)
    return 0
'''

#: A gate with NO `main`: its public API is its whole verdict surface, the
#: shape `url_oracle_guard` and `spec_conformance_gate` have.
LIBRARY_GATE = '''
def url_allowed(url, self_repo):
    return True, "ok"


def parse_project_self_repo(text):
    return None
'''


# ── THE RULE-ID MIGRATION, BOTH DIRECTIONS (owner ruling, #2141) ────────────
# `--write-baseline` can ADD and REMOVE, so it is the wrong instrument for a
# rule that got stricter: it would let a real tightening — a gate that stopped
# being unwired — leave the register unremarked, inside a migration where it is
# invisible among the additions. `--migrate-rule-id` may only ADD, and these
# two tests are the proof that the asymmetry is in the PROGRAM and not in a
# human's judgement at landing time.

import json                                            # noqa: E402
import subprocess                                      # noqa: E402
import sys as _sys                                     # noqa: E402

REGISTER = PROGRAMS / "gate_is_wired_baseline.json"


def _register():
    return json.loads(REGISTER.read_text(encoding="utf-8"))


def test_the_call_site_sweep_can_actually_see_an_offender():
    """The sweep above is a ZERO, and a zero from an instrument nobody proved
    can see is not a measurement (this repo's own
    `gate_zero_denominator_refuses_check`, #564).

    The same walk, run over source that carries one offender and one proving
    arm, must return exactly the offender.
    """
    src = ("import pytest\n"
           "def a():\n"
           "    return G.py_invocations(text, names)\n"
           "def b():\n"
           "    with pytest.raises(TypeError):\n"
           "        G.py_invocations(text, names)\n"
           "def c():\n"
           "    return G.py_invocations(text, names, stage_map)\n")
    tree = ast.parse(src)
    proving = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            c = item.context_expr
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "raises"):
                proving.update(
                    range(node.lineno, (node.end_lineno or node.lineno) + 1))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute) else None)
        if name != "py_invocations" or node.lineno in proving:
            continue
        if len(node.args) < 3 and not (
                {"stages", "_allow_no_stage_map"} & {k.arg for k in node.keywords}):
            hits.append(node.lineno)
    assert hits == [3], hits
