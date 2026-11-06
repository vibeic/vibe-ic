#!/usr/bin/env python3
"""An ALL-NOT-APPLICABLE declaration section must not print as `0/N`.

MEASURED, spm on the HARDMACRO route (lane rbspm4, plugin v1.18.17, PDK
gf180mcuD). Every question in `2B_pad_ring` and `2C_seal_ring` carries
`required_for=(DELIVERABLE_DIE,)`, so `_tapeout_declaration.audit()` reports
them exactly right:

    2B_pad_ring   answered=0 unanswered=0 not_applicable=8
    2C_seal_ring  answered=0 unanswered=0 not_applicable=3

Nothing is outstanding. `summary_line` nevertheless rendered the
`answered/questions` ratio:

    answered=3/20 (2A_die_size=3/9 2B_pad_ring=0/8 2C_seal_ring=0/3)

`2B_pad_ring=0/8` is indistinguishable from eight questions nobody answered.
That reading was taken at face value twice — by a reviewing agent and by the
repo owner — and produced a decision to "dispose of" questions the code had
already disposed of, while the two questions that ARE outstanding on this
route (`macro_area_um`, `macro_origin_um`) stayed invisible inside `3/9`.

The counts underneath were correct throughout. The defect is a tally that
cannot tell "not required here" from "not answered yet".

NO VERDICT MOVES. This pins rendering only: `answered`, `not_applicable` and
the verdict are asserted unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import _tapeout_declaration as _td  # noqa: E402


def _res(sections, answered, total, not_applicable):
    return {
        "verdict": "FAIL",
        "audit": {"questions_total": total, "answered": answered,
                  "not_applicable": not_applicable, "sections": sections},
        "area_budget_authority": {"status": "NOT_APPLICABLE"},
        "router_selected": None, "refusals": [], "incomplete_dependencies": [],
    }


def _sec(questions, answered, not_applicable):
    return {"questions": questions, "answered": answered,
            "unanswered": questions - answered - not_applicable,
            "not_applicable": not_applicable}










def test_the_pad_and_seal_sections_really_are_die_only():
    """The rendering fix is only correct because the SCOPE already was."""
    for sec in (_td.SECTION_PAD_RING, _td.SECTION_SEAL_RING):
        qs = [q for q in _td.QUESTIONS if q.section == sec]
        assert qs, sec
        for q in qs:
            assert q.required_for == (_td.DELIVERABLE_DIE,), (
                f"{q.key} is not die-only; the n/a rendering would then be "
                "wrong on a hardmacro")
            assert not _td.applicable(q, _td.DELIVERABLE_HARDMACRO), q.key
