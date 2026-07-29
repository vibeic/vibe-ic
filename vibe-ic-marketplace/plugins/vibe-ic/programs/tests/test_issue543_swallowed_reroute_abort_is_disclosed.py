"""test_issue543_swallowed_reroute_abort_is_disclosed.py

A swallowed routing abort must not leave a number named POSTROUTE behind it,
and a residual violation must not be published as a floor nobody established.

WHAT WENT WRONG (vibe-ic#543)
=============================
`detailed_route` is wrapped in `catch` so a routing abort cannot kill the repair
step. That is right. What was wrong is what happened next: the abort was
swallowed, and the step still emitted

    SHIP_WNS_POSTROUTE: -37.08

from a design whose reroute never completed — four DRT-0085 aborts on an
unroutable probe cell, once pre-reroute and once per convergence iteration. The
promotion gate did refuse the route, but by `route_violations != 0` being None:
it refused because a number was MISSING, not because the route was known broken.
A refusal that rests on an absent marker is one log-format change away from
becoming a promotion.

Downstream, `eco_log.json` recorded the surviving violation as "a genuine
process-corner floor" — a cause nobody had established, from a string literal
that could not have said anything else.

TWO PROPERTIES PINNED HERE
==========================
1. When any reroute aborts, the slack is published under a name that says the
   route is not there (`SHIP_WNS_UNROUTED`) with the abort count beside it, and
   `wns_postroute` is absent BY CONSTRUCTION.
2. The residual note is derived from the repair log, never asserted. It names
   the reroute when the log shows one failed, and otherwise says the cause is
   not established rather than reaching for the most final-sounding one.

Each has a control: a clean-reroute log must still promote (or the gate is
merely always-False), and a pre-fix log must parse exactly as it used to (or the
change silently reinterprets every archived run).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

_TCL_ARGS = dict(top="t", tech_lef_c="/a.tlef", cell_lef_c="/b.lef",
                 ss_liberty_c="/ss.lib", pnr_dir_c="/pnr", max_captable_c="/cap",
                 metal_prefix="met", thread_count=8, filler_masters=[])

_CLEAN_TAIL = "SHIP_WNS_POSTROUTE: -0.0005\n"
_FAILED_TAIL = "SHIP_REROUTE_INCOMPLETE: 4\nSHIP_WNS_UNROUTED: -37.08\n"


def _log(tail: str) -> str:
    """A repair log that satisfies every OTHER promotion condition, so the only
    thing under test is the reroute-completion one."""
    return ("SHIP_WNS_BEFORE: -72.07\n"
            "SHIP_WNS_AFTER_REPAIR: 0.5\n"
            "Number of violations = 0\n"
            "Found 10 slew violations.\nFound 10 slew violations.\n"
            "Found 5 capacitance violations.\nFound 5 capacitance violations.\n"
            + tail)


def test_the_emitted_tcl_counts_every_swallowed_abort_before_it_can_happen():
    tcl = R._ship_signoff_spef_repair_tcl(**_TCL_ARGS)
    decl = tcl.find("set _ship_dr_failed 0")
    first_use = tcl.find("incr _ship_dr_failed")
    assert decl >= 0, "the abort counter is not declared"
    assert first_use >= 0, "no detailed_route catch increments the counter"
    assert decl < first_use, (
        "the counter is declared after its first use — Tcl would error and the "
        "catch would hide that too")
    assert tcl.count("incr _ship_dr_failed") == 2, (
        "both reroute sites (pre-reroute and the convergence loop) must count; "
        "counting one of two is how the loop's four aborts stayed invisible")
    assert "SHIP_REROUTE_INCOMPLETE" in tcl and "SHIP_WNS_UNROUTED" in tcl


def test_a_failed_reroute_publishes_no_postroute_number():
    parsed = R._parse_ship_repair_log(_log(_FAILED_TAIL))
    assert parsed["reroute_incomplete"] == 4
    assert parsed["wns_postroute"] is None, (
        "a slack from a design that was never rerouted is still readable as a "
        "post-reroute number — the exact confusion this issue is about")
    assert parsed["wns_unrouted"] == pytest.approx(-37.08)


def test_the_promotion_gate_refuses_on_the_fact_not_on_a_missing_number():
    parsed = R._parse_ship_repair_log(_log(_FAILED_TAIL))
    assert R._ship_repair_should_promote(parsed, True, True) is False


def test_control_a_clean_reroute_still_promotes():
    """Without this the refusal above proves nothing: a gate that always says
    False refuses a broken route and a good one alike."""
    parsed = R._parse_ship_repair_log(_log(_CLEAN_TAIL))
    assert parsed["reroute_incomplete"] == 0
    assert R._ship_repair_should_promote(parsed, True, True) is True


def test_control_a_pre_fix_log_parses_exactly_as_it_used_to():
    """Archived logs carry no SHIP_REROUTE_INCOMPLETE. They must keep their old
    meaning: absent marker is 'not stated', never 'reroute failed'."""
    parsed = R._parse_ship_repair_log(_log(_CLEAN_TAIL))
    assert parsed["reroute_incomplete"] == 0
    assert parsed["wns_postroute"] == pytest.approx(-0.0005)


def test_the_residual_note_never_asserts_a_floor_it_cannot_evidence(tmp_path):
    note = R._eco_residual_note(tmp_path, True)
    assert "genuine process-corner floor" not in note, (
        "the note still asserts a floor with no evidence for one")
    assert "not establish" in note or "NOT establish" in note


def test_the_residual_note_names_the_reroute_when_the_log_shows_one_failed(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "signoff_spef_repair.log").write_text(_log(_FAILED_TAIL),
                                                 encoding="utf-8")
    note = R._eco_residual_note(tmp_path, True)
    assert "reroute aborted 4 time(s)" in note
    assert "NOT a process-corner floor" in note, (
        "a residual with a named upstream cause must say it is not a floor — "
        "otherwise the fixable case and the unfixable one read the same")


def test_a_closed_corner_says_so(tmp_path):
    assert R._eco_residual_note(tmp_path, False) == (
        "multi-corner OCV closed after the ECO.")


# --- #552: repair_timing has the same catch and had no counter --------------

def test_a_refused_setup_repair_is_counted_and_disclosed_before_the_number():
    """MEASURED on ibex x sky130A: five consecutive `repair_timing -setup` calls
    failed (GRT-0703 x4, GRT-0013), every one swallowed as SHIP_RT_NONFATAL, and
    `SHIP_WNS_AFTER_REPAIR` was published straight after them. That number is
    labelled a wire-load estimate so nothing downstream is wrong today, but it
    reads as though the repairs happened.

    Order is asserted, not just presence: the disclosure has to precede the
    number it qualifies, or a reader meets the slack first and the caveat after.
    """
    tcl = R._ship_signoff_spef_repair_tcl(**_TCL_ARGS)
    lines = tcl.splitlines()

    def at(tok):
        return next((n for n, l in enumerate(lines) if tok in l), None)

    decl, incr = at("set _ship_rt_failed 0"), at("incr _ship_rt_failed")
    assert decl is not None, "no counter for refused setup repairs"
    assert incr is not None, "the repair_timing catch does not count anything"
    assert decl < incr, (
        f"the counter is declared at {decl}, AFTER its first use at {incr} — "
        f"Tcl would error and the surrounding catch would swallow that too, so "
        f"the count would read 0 for exactly the runs it exists to count")

    assert tcl.count("incr _ship_rt_failed") == 2, (
        "both repair_timing sites (pre-reroute and convergence loop) must count")

    refused, after = at("SHIP_SETUP_REPAIR_REFUSED"), at("SHIP_WNS_AFTER_REPAIR")
    assert refused is not None and after is not None
    assert refused < after, (
        "the refusal count is emitted after the slack it qualifies")


def test_the_refusal_count_is_parsed_and_an_archived_log_still_means_not_stated():
    d = R._parse_ship_repair_log("SHIP_SETUP_REPAIR_REFUSED: 5\n"
                                 "SHIP_WNS_AFTER_REPAIR: -20.16\n")
    assert d["setup_repair_refused"] == 5
    assert d["wns_after_repair"] == pytest.approx(-20.16)

    old = R._parse_ship_repair_log("SHIP_WNS_AFTER_REPAIR: -20.16\n")
    assert old["setup_repair_refused"] == 0, (
        "an archived log with no marker must mean 'not stated', never "
        "'none failed' — reinterpreting old runs is the defect one level up")
