#!/usr/bin/env python3
"""The step-13 gate read the equiv_simple ENTRY count as "what is still
unproven", and never read the one line that says so.

Yosys prints three different numbers next to the word `unproven`:

    equiv_simple ENTRY    "Found 3396 unproven $equiv cells (3396 groups) in
                           equiv:"                     the pass's INPUT
    equiv_induct residual "Found 35 unproven $equiv cells in module equiv:"
    equiv_status FINAL    "Of those cells 830 are proven and 3242 are
                           unproven."                  the run's ANSWER

`parse_rpt` took `max()` over every match of a pattern that matches the first
two and NOT the third — so the number it published was structurally the entry
line, the largest of the three and the only one that says nothing about what
remains. It feeds `LEC_UNPROVEN_POINTS`, so on a log whose equiv_simple then
proved everything, a PASS is turned into a FAIL out of a pass's own input.

MEASURED (the shapes below are the real ones): opentitan_aes x chip_top logged
entry 3396 against a status line of 830 proven / 3242 unproven — the gate
published 3396.

Both halves are pinned here: the reading itself, and the gate-level
consequence (a project whose lec.json carries no unproven field and whose .rpt
is a completed PASS).
"""
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import lec_equivalence_check as gate     # noqa: E402
import lec_run                           # noqa: E402


# --- the real log shapes ---------------------------------------------------

_ENTRY = "Found 3396 unproven $equiv cells (3396 groups) in equiv:\n"

_INCONCLUSIVE_LOG = (
    "8. Executing EQUIV_SIMPLE pass.\n"
    + _ENTRY
    + "Proved 830 previously unproven $equiv cells.\n"
    "9. Executing EQUIV_INDUCT pass.\n"
    "10. Executing EQUIV_STATUS pass.\n"
    "Found 4072 $equiv cells in equiv:\n"
    "  Of those cells 830 are proven and 3242 are unproven.\n"
)

_PASS_LOG = (
    "8. Executing EQUIV_SIMPLE pass.\n"
    "Found 33 unproven $equiv cells (33 groups) in equiv:\n"
    "Proved 33 previously unproven $equiv cells.\n"
    "9. Executing EQUIV_STATUS pass.\n"
    "Found 33 $equiv cells in equiv:\n"
    "  Of those cells 33 are proven and 0 are unproven.\n"
    "Equivalence successfully proven!\n"
)

_KILLED_MID_LADDER_LOG = (
    "8. Executing EQUIV_SIMPLE pass.\n"
    "Found 1838 unproven $equiv cells (1838 groups) in equiv:\n"
    "Proved 1 previously unproven $equiv cells.\n"
    "9. Executing EQUIV_INDUCT pass.\n"
    "Found 1837 unproven $equiv cells in module equiv:\n"
    "Proved 1834 previously unproven $equiv cells.\n"
    "10. Executing EQUIV_INDUCT pass.\n"
    "Found 3 unproven $equiv cells in module equiv:\n"
)

_ENTRY_ONLY_LOG = (
    "8. Executing EQUIV_SIMPLE pass.\n" + _ENTRY
)


# --- 1. the reading --------------------------------------------------------

def test_the_final_status_line_wins_over_the_entry_count():
    """The defect, in the direction that over-reports."""
    got = gate.parse_rpt(_INCONCLUSIVE_LOG)
    assert got["rpt_unproven_points"] == 3242, got
    assert got["rpt_proven_points"] == 830, got
    assert got["rpt_points_source"] == "equiv_status", got
    # and it is NOT the entry count, which is what `max()` returned
    assert got["rpt_unproven_points"] != 3396, got


def test_a_completed_pass_reads_zero_unproven():
    """The direction that manufactures a FAIL: everything the entry line
    counted was then proven, and the run's own status line says 0."""
    got = gate.parse_rpt(_PASS_LOG)
    assert got["rpt_unproven_points"] == 0, got
    assert got["rpt_proven_points"] == 33, got
    assert got["rpt_success_line"] is True, got


def test_a_killed_run_reads_the_last_residual_and_the_cumulative_proved():
    """No equiv_status at all. The furthest state the run reached is the LAST
    residual line, and proven is the SUM over the passes — not the first of
    either, and never the entry line."""
    got = gate.parse_rpt(_KILLED_MID_LADDER_LOG)
    assert got["rpt_unproven_points"] == 3, got
    assert got["rpt_proven_points"] == 1 + 1834, got
    assert got["rpt_points_source"] == "yosys_pass_lines", got


def test_an_entry_line_alone_is_not_measured():
    """`could not read it` is not `read it and it was 3396`."""
    got = gate.parse_rpt(_ENTRY_ONLY_LOG)
    assert got["rpt_unproven_points"] is None, got
    assert "equiv_simple" in got.get("rpt_unproven_not_measured", ""), got


def test_an_echoed_source_comment_is_not_this_runs_residual():
    """The residual pattern is anchored at line start, as lec_run's is: a
    design comment a tool echoes into its log is not a measurement."""
    spoof = (_ENTRY_ONLY_LOG
             + "  // Found 999 unproven $equiv cells in module equiv:\n")
    got = gate.parse_rpt(spoof)
    assert got["rpt_unproven_points"] is None, got


def test_a_generic_non_yosys_report_is_unchanged():
    """The gate still reads a tool that is not yosys. No yosys shape appears
    here, so the generic branch is the one that answers."""
    got = gate.parse_rpt(
        "Proved 128 equiv points\n12 unproven equiv points remain\n")
    assert got["rpt_proven_points"] == 128, got
    assert got["rpt_unproven_points"] == 12, got
    assert got["rpt_points_source"] == "generic", got


# --- 2. the two readings agree --------------------------------------------

def test_lec_rpt_reading_matches_the_producer():
    """The gate is deliberately an INDEPENDENT reader of the artefacts (a
    producer bug has to stay visible to it), so it does not import lec_run's
    parser. That independence is only worth having if the two readings agree
    on the same bytes, which is what this asserts — on every log shape above.
    """
    for name, log in (("inconclusive", _INCONCLUSIVE_LOG),
                      ("pass", _PASS_LOG),
                      ("killed", _KILLED_MID_LADDER_LOG)):
        mine = gate.parse_rpt(log)
        theirs = lec_run.parse_equiv_output(log)
        assert mine["rpt_proven_points"] == theirs["proven"], (name, mine,
                                                               theirs)
        assert mine["rpt_unproven_points"] == theirs["unproven"], (name, mine,
                                                                   theirs)


# --- 3. the gate-level consequence ----------------------------------------

def _project(tmp_path, lec_json: dict, rpt: str) -> Path:
    proj = tmp_path / "proj"
    (proj / "reports").mkdir(parents=True)
    (proj / gate.LEC_JSON_REL).write_text(json.dumps(lec_json))
    (proj / gate.LEC_RPT_REL).write_text(rpt)
    return proj


def test_a_completed_pass_is_not_failed_by_the_entry_count(tmp_path):
    """The whole point. lec.json declares a PASS and carries no unproven
    field, so the .rpt is the only source for it; the .rpt is a completed
    proof with 0 unproven. Reading the entry count instead published 33
    unproven points and the gate refused a design that was proven."""
    proj = _project(tmp_path, {
        "equivalent": True,
        "compared_points": 33,
        "non_equivalent_points": 0,
    }, _PASS_LOG)
    res = gate.audit(proj)
    assert res.unproven_points == 0, res.summary
    assert res.passed is True, [f.rule for f in res.findings]
    assert "LEC_UNPROVEN_POINTS" not in [f.rule for f in res.findings]


def test_an_honest_unproven_count_still_fails(tmp_path):
    """The other direction, so the fix is not a way to stop seeing unproven
    points: the same shape with a status line that leaves 3242 unproven is
    still refused, and by the number the run itself reported."""
    proj = _project(tmp_path, {
        "equivalent": True,
        "compared_points": 4072,
        "non_equivalent_points": 0,
    }, _INCONCLUSIVE_LOG)
    res = gate.audit(proj)
    assert res.unproven_points == 3242, res.summary
    assert res.passed is False
    assert "LEC_UNPROVEN_POINTS" in [f.rule for f in res.findings], \
        [f.rule for f in res.findings]
