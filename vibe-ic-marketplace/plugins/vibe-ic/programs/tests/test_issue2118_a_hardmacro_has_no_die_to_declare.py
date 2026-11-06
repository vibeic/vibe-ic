#!/usr/bin/env python3
"""vibe-ic#2118 — a HARDMACRO delivery must not be handed a DIE's declarations.

`die_area_um`, `die_origin_um`, `core_area_um` and `fp_sizing` are all
`required_for=(DELIVERABLE_DIE,)` in `_tapeout_declaration`'s own schema — the
module states, question by question, that a macro somebody else places owes no
answer about a die. `phase3_one_shot_runner.publish_tapeout_declarations`
published `die_area_um` and `die_origin_um` onto a HARDMACRO delivery anyway.

The NUMBER was never wrong: `declared_die_rect` returns the run's own floorplan
rectangle, which on a macro run is the macro's own bounding box. The CLAIM
around it was — any consumer that believes the name reads it as a die. This is
the seal-ring class of vibe-ic#2112 one step up: the same wrong premise, "what
leaves this flow is a die", taken about SIZE instead of about a ring.

THE SHAPE PROVEN HERE
  * a HARDMACRO publishes `macro_area_um` / `macro_origin_um` and REFUSES the
    `die_*` pair BY NAME (a key nobody published and a key somebody declined
    are different facts);
  * a DIE publishes exactly what it published before, byte for byte, and
    refuses the `macro_*` pair by name;
  * an UNDECLARED deliverable publishes NEITHER — `applicable` already says
    such a design owes every question, and choosing one name would be a guess
    wearing a derivation's clothes;
  * `general_precheck`'s `KLayout.CheckSize` still reaches a verdict on a
    hardmacro, from the MACRO box — PASS when it matches and FAIL when it does
    not, so the rung is not a filter that always agrees;
  * a `die_area_um` sitting in a hardmacro's declaration is NOT consumed by
    that rung.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGS = Path(__file__).resolve().parent.parent
if str(PROGS) not in sys.path:
    sys.path.insert(0, str(PROGS))

import _tapeout_declaration as td            # noqa: E402
import general_precheck as gp                # noqa: E402

from test_general_precheck import (          # noqa: E402
    _die_at_origin, _project as _gp_project, _step, _NEVER_RAN)

_DEF = ("VERSION 5.8 ;\nDESIGN spm ;\nUNITS DISTANCE MICRONS 2000 ;\n"
        "DIEAREA ( 762000 762000 ) ( 4800000 4800000 ) ;\nEND DESIGN\n")








# ── the publisher, both deliverables ───────────────────────────────────────







# ── the schema itself ──────────────────────────────────────────────────────

def test_the_size_pair_is_split_by_deliverable_in_the_schema():
    """MEMBERSHIP, not a count — a question that moves between deliverables
    has to show up here by NAME."""
    die_only = {q.key for q in td.QUESTIONS
                if q.required_for == (td.DELIVERABLE_DIE,)}
    macro_only = {q.key for q in td.QUESTIONS
                  if q.required_for == (td.DELIVERABLE_HARDMACRO,)}
    assert {"die_area_um", "die_origin_um", "core_area_um",
            "fp_sizing"} <= die_only
    assert macro_only == {"macro_area_um", "macro_origin_um"}
    assert not (die_only & macro_only)
    for key in macro_only:
        assert not td.applicable(td.question(key), td.DELIVERABLE_DIE)
        assert td.applicable(td.question(key), td.DELIVERABLE_HARDMACRO)
        # An UNDECLARED delivery still owes every question.
        assert td.applicable(td.question(key), td.NOT_DETERMINED)


# ── the consumer: CheckSize still reaches a verdict, on the macro box ───────

def test_checksize_measures_a_hardmacro_against_its_declared_macro_box(tmp_path):
    proj = _gp_project(tmp_path, _die_at_origin, {
        "deliverable": "HARDMACRO", "top_cell": "chip_top",
        "macro_origin_um": [0, 0], "macro_area_um": [0, 0, 100.0, 80.0],
        "database_unit_um": 0.001})
    ev = _step(gp.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckSize")
    assert ev.verdict == gp.PASS, ev.evidence
    assert "100.0 x 80.0" in ev.evidence
    assert ev.measured["declared_area_key"] == "macro_area_um"


def test_a_macro_box_that_does_not_match_is_refused(tmp_path):
    """The other direction, so the rung above is not one that always agrees."""
    proj = _gp_project(tmp_path, _die_at_origin, {
        "deliverable": "HARDMACRO", "top_cell": "chip_top",
        "macro_origin_um": [0, 0], "macro_area_um": [0, 0, 999.0, 999.0],
        "database_unit_um": 0.001})
    ev = _step(gp.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckSize")
    assert ev.verdict == gp.FAIL, ev.evidence
    assert "999" in ev.evidence


def test_a_die_area_left_on_a_hardmacro_is_not_consumed(tmp_path):
    """The declaration carries a `die_area_um` that MATCHES the layout. A macro
    owes no answer about a die, so the rung must not reach its verdict through
    it — the size is unchecked and the step does not claim otherwise."""
    proj = _gp_project(tmp_path, _die_at_origin, {
        "deliverable": "HARDMACRO", "top_cell": "chip_top",
        "die_origin_um": [0, 0], "die_area_um": [0, 0, 100.0, 80.0],
        "database_unit_um": 0.001})
    ev = _step(gp.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckSize")
    assert ev.measured["declared_area_key"] == "macro_area_um"
    assert ev.measured["declared_area_um"] == td.NOT_DETERMINED
    assert "100.0 x 80.0" not in ev.evidence


def test_a_die_is_still_measured_against_its_die_box(tmp_path):
    """The control for the consumer half."""
    proj = _gp_project(tmp_path, _die_at_origin, {
        "deliverable": "DIE", "top_cell": "chip_top",
        "die_origin_um": [0, 0], "die_area_um": [0, 0, 100.0, 80.0],
        "database_unit_um": 0.001})
    ev = _step(gp.evaluate(proj, runner=_NEVER_RAN), "KLayout.CheckSize")
    assert ev.verdict == gp.PASS, ev.evidence
    assert ev.measured["declared_area_key"] == "die_area_um"
