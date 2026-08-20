#!/usr/bin/env python3
"""The search's RECORD discipline — the part that has to be right whether or not
any EDA tool is available.

A configuration search is a machine for producing numbers faster than anyone can
check them, so the properties tested here are the ones that let somebody who was
not present read the result afterwards:

  * `n of N` is never rounded up. `scored`, `not_measured` and `refused` are
    counted separately and sum to what was attempted, and a limited run still
    prints the size of the space it did not cover.
  * A configuration that could not be scored is NAMED with its reason, not
    dropped and not given a large number that still ranks it.
  * `step` — the quantity the anti-cheating term consumes — comes from the run's
    OWN declared step ladder, and a run that declared none yields "unknown",
    which is not the same as "got nowhere".
  * An inherited weight ratio prints the words "inherited, not chosen" in the
    human-readable report, not only in the JSON.

None of these needs a container, a PDK or a design, which is why they are here
rather than only inside a campaign nobody re-runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import ppa_objective as _obj
from ppa_search import (BASELINE, DEFAULT_SPACE, KNOB_FLAGS,
                        axis_discrimination, _expand, config_id, report_md,
                        resumable as ppa_search_resumable, step_progress)


def test_the_default_space_actually_reaches_fifty():
    configs = _expand(DEFAULT_SPACE)
    assert len(configs) >= 50, (
        "the declared bar is >=50 CONFIGURATIONS; a space smaller than that "
        "cannot meet it however many times it is run")
    assert len({config_id(c) for c in configs}) == len(configs), (
        "50 records means 50 DISTINCT configurations, not 50 attempts")


def test_the_baseline_is_inside_the_space():
    assert BASELINE in _expand(DEFAULT_SPACE), (
        "the thing the search has to beat must be one of the things it ran, "
        "or the comparison is against a number from a different measurement")
    assert set(BASELINE) == set(DEFAULT_SPACE), (
        "the reference must pin EVERY knob the space varies; a knob left "
        "unpinned would make the reference a different measurement from the "
        "configurations it anchors")


def test_config_id_is_decodable_without_the_record():
    cid = config_id({"util": 0.4, "die_um": "100x100", "spare_density": 0.02})
    for fragment in ("util-0p4", "die_um-100x100", "spare_density-0p02"):
        assert fragment in cid


# --------------------------------------------------------------------------
# which axes actually moved — the disclosure ORFS does not have
# --------------------------------------------------------------------------
def _rec(perf, power, area, drc_penalty=0.0):
    return {"objective": {"terms": {"performance": perf, "power": power,
                                    "area": area},
                          "drc_penalty": drc_penalty}}


def test_an_axis_that_took_one_value_is_reported_INERT():
    got = axis_discrimination([_rec(0.0, 0.0, -8.9), _rec(0.0, 0.0, -11.5),
                               _rec(0.0, 0.0, 2.0)])
    assert got["performance"]["status"] == "INERT"
    assert got["performance"]["constant_value"] == 0.0
    assert got["power"]["status"] == "INERT"
    assert got["area"]["status"] == "DISCRIMINATING"
    assert got["area"]["distinct"] == 3


def test_no_scored_configuration_is_NO_SAMPLES_not_inert():
    got = axis_discrimination([])
    for axis in ("performance", "power", "area"):
        assert got[axis]["status"] == "NO_SAMPLES", (
            "an axis nobody sampled must not read as an axis that did not "
            "move — that is the same collapse as ABSENT vs UNREADABLE")


def test_the_report_says_which_axes_were_inert():
    md = report_md(_search(axis_discrimination=axis_discrimination(
        [_rec(0.0, 0.0, -8.9), _rec(0.0, 0.0, 2.0)])))
    assert "INERT" in md
    assert "contributed nothing to the ranking" in md, (
        "a reader who assumed the 10000-weight axis did the work would be "
        "wrong, and the report is where they find that out")


def test_a_fully_discriminating_search_carries_no_inert_warning():
    md = report_md(_search(axis_discrimination=axis_discrimination(
        [_rec(1.0, 2.0, 3.0, drc_penalty=0.0),
         _rec(4.0, 5.0, 6.0, drc_penalty=7.5)])))
    assert "INERT" not in md
    assert "contributed nothing to the ranking" not in md


def test_every_searched_knob_is_a_flag_the_runner_already_exposes():
    """A search that needs a private channel into the runner is a search whose
    records cannot be reproduced from the records."""
    runner = (Path(__file__).resolve().parent.parent
              / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    for flag in KNOB_FLAGS.values():
        assert f'p.add_argument("{flag}"' in runner, flag
    # Everything the space varies is either such a flag or the one declared
    # design-input rewrite. A knob reaching the flow by any other route would
    # not be reproducible from the record.
    for knob in DEFAULT_SPACE:
        assert knob in KNOB_FLAGS, (
            f"{knob} reaches the flow by some other route, so a record naming "
            "it cannot be reproduced from the record")


# --------------------------------------------------------------------------
# step — from the run's own declaration, and "unknown" is its own answer
# --------------------------------------------------------------------------
def test_step_counts_the_passed_stages_of_the_declared_ladder(tmp_path):
    d = tmp_path / "reports" / "orchestrator"
    d.mkdir(parents=True)
    (d / "phase3_one_shot.json").write_text(json.dumps({"steps": [
        {"name": "synth", "status": "PASS"},
        {"name": "pnr", "status": "PASS"},
        {"name": "drc", "status": "FAIL"},
    ]}))
    passed, total, why = step_progress(tmp_path)
    assert (passed, total, why) == (2, 3, None)


def test_a_run_that_declared_no_ladder_is_unknown_not_zero(tmp_path):
    passed, total, why = step_progress(tmp_path)
    assert passed is None and total is None
    assert why, "an unreadable ladder must say so rather than report progress 0"


def test_an_unparseable_ladder_names_itself(tmp_path):
    d = tmp_path / "reports" / "orchestrator"
    d.mkdir(parents=True)
    (d / "phase3_one_shot.json").write_text("{broken")
    passed, _, why = step_progress(tmp_path)
    assert passed is None
    assert "phase3_one_shot.json" in why


def test_an_empty_ladder_is_unknown_not_a_completed_run_of_size_zero(tmp_path):
    d = tmp_path / "reports" / "orchestrator"
    d.mkdir(parents=True)
    (d / "phase3_one_shot.json").write_text(json.dumps({"steps": []}))
    passed, total, why = step_progress(tmp_path)
    assert passed is None and total is None and why


# --------------------------------------------------------------------------
# the report a human reads
# --------------------------------------------------------------------------
def _search(**over):
    base = {
        "design_name": "d", "weights": _obj.resolve_weights(None, None),
        "attempted": 3, "scored": 1, "not_measured": 1, "refused": 1,
        "space_size": 50,
        "reference": {"config_id": "REF", "knobs": dict(BASELINE),
                      "metrics": {"final_util": 22.0}},
        "ranking": [{"config_id": "a", "wall_s": 100.0, "objective": {
            "score": 5.0, "ppa": 4.0, "num_drc": 0, "drc_penalty": 0.0,
            "step": 14, "stages_total": 14}}],
        "unscored": [
            {"config_id": "b", "verdict": "NOT_MEASURED",
             "not_scored_because": {"code": "METRIC_NOT_MEASURED",
                                    "detail": "total_power"}},
            {"config_id": "c", "verdict": "REFUSED",
             "not_scored_because": {"code": "STEP_ZERO", "detail": "no stage"}},
        ],
        "verdict_line": "**x**",
    }
    base.update(over)
    return base


def test_the_report_names_every_configuration_it_could_not_score():
    md = report_md(_search())
    assert "`b`" in md and "METRIC_NOT_MEASURED" in md
    assert "`c`" in md and "STEP_ZERO" in md, (
        "a silent cap reads as 'we covered everything' when it did not")


def test_the_counts_sum_to_what_was_attempted():
    s = _search()
    assert s["scored"] + s["not_measured"] + s["refused"] == s["attempted"]
    md = report_md(s)
    assert "**3 of 50**" in md and "**1**" in md


def test_a_partial_run_shows_its_denominator():
    """`n of N`, never rounded up. A silent cap reads as 'we covered
    everything' when it did not."""
    md = report_md(_search(attempted=3, space_size=50))
    assert "covered 3 of 50" in md


def test_a_complete_run_carries_no_partial_warning():
    md = report_md(_search(attempted=50, scored=48, not_measured=1,
                           refused=1, space_size=50))
    assert "covered 50 of 50" not in md
    assert "**50 of 50**" in md


def test_an_inherited_ratio_says_so_in_the_human_report():
    md = report_md(_search())
    assert _obj.INHERITED_PHRASE in md, (
        "the JSON saying `source: inherited` is not enough — the report is "
        "what gets read, and an inherited weight shown as a choice is a lie "
        "about who made the value judgement")


def test_a_declared_ratio_is_not_labelled_inherited():
    w = _obj.resolve_weights(
        {"fields": {"ppa_weights": {"performance": 1, "power": 1, "area": 1}}},
        "L19")
    md = report_md(_search(weights=w))
    assert _obj.INHERITED_PHRASE not in md
    assert "DECLARED" in md


def test_the_step_semantics_deviation_is_in_the_report():
    md = report_md(_search())
    assert "Ray" in md and "completed/declared" in md


def test_an_empty_ranking_does_not_render_as_a_result():
    md = report_md(_search(ranking=[], scored=0, not_measured=2))
    assert "| 1 |" not in md


def test_the_report_is_reproducible_from_the_record_alone(tmp_path):
    """`--rerender` exists because the report is a VIEW. A report that can only
    be produced by re-running the search is a report nobody can check after the
    renderer changes — and the renderer DID change mid-campaign here."""
    import subprocess
    import sys as _sys

    search = _search()
    (tmp_path / "search.json").write_text(json.dumps(search))
    prog = Path(__file__).resolve().parent.parent / "ppa_search.py"
    proc = subprocess.run(
        [_sys.executable, str(prog), str(tmp_path), "--out", str(tmp_path),
         "--rerender"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    # Compared against the record AS REWRITTEN: `--rerender` recomputes the
    # derived disclosure from the ranking (see the test below), so the fixed
    # point is "report == report_md(record on disk)", which is the property
    # that actually matters — a reader with the record can reproduce the page.
    on_disk = json.loads((tmp_path / "search.json").read_text())
    assert (tmp_path / "SEARCH_REPORT.md").read_text() == report_md(on_disk)
    assert on_disk["ranking"] == search["ranking"], (
        "re-rendering must not touch the measured half of the record")


def test_rerender_without_a_record_refuses_rather_than_writing_an_empty_one(
        tmp_path):
    import subprocess
    import sys as _sys
    prog = Path(__file__).resolve().parent.parent / "ppa_search.py"
    proc = subprocess.run(
        [_sys.executable, str(prog), str(tmp_path), "--out", str(tmp_path),
         "--rerender"], capture_output=True, text=True)
    assert proc.returncode != 0
    assert not (tmp_path / "SEARCH_REPORT.md").exists()


def test_a_search_record_is_not_offered_as_a_head_to_head_arm():
    """`ppa_head_to_head_check` refuses any arm carrying a collapsed scalar,
    and every search record carries one BY DESIGN — a search has to rank. The
    two artefacts answer different questions with opposite rules, and the only
    thing that keeps them apart is that nobody confuses them. Pin the warning
    where a future author will read it."""
    src = (Path(__file__).resolve().parent.parent
           / "ppa_search.py").read_text(encoding="utf-8")
    assert "ppa_head_to_head_check" in src
    assert "COLLAPSED_SCALAR" in src or "collapsed scalar" in src

    h2h = (Path(__file__).resolve().parent.parent
           / "ppa_head_to_head_check.py").read_text(encoding="utf-8")
    assert '"score"' in h2h, (
        "premise: the head-to-head checker really does refuse `score`; if it "
        "stops doing so this warning is stale and must be re-read")


def test_a_clean_sweep_is_not_offered_as_proof_the_drc_penalty_works():
    """Every configuration coming back with zero violations means the
    anti-cheating term never fired. A report that stayed silent would let a
    clean sweep read as a demonstration of the refusal."""
    got = axis_discrimination([_rec(0.0, 0.0, 1.0), _rec(0.0, 0.0, 2.0)])
    assert got["drc_penalty"]["status"] == "INERT"
    md = report_md(_search(axis_discrimination=got))
    assert "never fired" in md
    assert "NOT evidence the" in md


def test_a_search_that_did_hit_violations_carries_no_such_disclaimer():
    recs = [_rec(0.0, 0.0, 1.0), _rec(0.0, 0.0, 2.0)]
    recs[1]["objective"]["drc_penalty"] = 12.5
    got = axis_discrimination(recs)
    assert got["drc_penalty"]["status"] == "DISCRIMINATING"
    assert "never fired" not in report_md(_search(axis_discrimination=got))


def test_rerender_recomputes_the_derived_disclosure_and_touches_no_run_tree(
        tmp_path):
    """A record written before `axis_discrimination` covered a term must not
    render a half-empty table — the report would be a view of two different
    things at once. The disclosure is a pure function of the ranking, so it is
    recomputed; the MEASURED values are not, and nothing re-reads a run tree."""
    import subprocess
    import sys as _sys

    search = _search()
    search.pop("axis_discrimination", None)
    search["ranking"][0]["objective"]["terms"] = {
        "performance": 0.0, "power": 0.0, "area": -3.0}
    (tmp_path / "search.json").write_text(json.dumps(search))
    prog = Path(__file__).resolve().parent.parent / "ppa_search.py"
    proc = subprocess.run(
        [_sys.executable, str(prog), str(tmp_path), "--out", str(tmp_path),
         "--rerender"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    rewritten = json.loads((tmp_path / "search.json").read_text())
    assert rewritten["axis_discrimination"]["performance"]["status"] == "INERT"
    assert "INERT" in (tmp_path / "SEARCH_REPORT.md").read_text()
    # the measured half is untouched
    assert rewritten["reference"]["metrics"] == search["reference"]["metrics"]


def test_a_record_missing_a_term_is_counted_not_crashed_on_or_dropped():
    """Degrade loudly. An older-schema or hand-edited record must not take the
    disclosure down, and must not vanish from the denominator either — dropping
    it silently could turn a DISCRIMINATING axis into an INERT one on the
    strength of the records that happened to parse."""
    recs = [_rec(1.0, 2.0, 3.0), {"objective": {"score": 5.0}},
            _rec(4.0, 5.0, 6.0)]
    got = axis_discrimination(recs)
    assert got["performance"]["samples"] == 2
    assert got["performance"]["unreadable"] == 1
    assert got["performance"]["status"] == "DISCRIMINATING"
    md = report_md(_search(axis_discrimination=got))
    assert "carried no such term" in md


def test_a_complete_disclosure_does_not_claim_missing_records():
    got = axis_discrimination([_rec(1.0, 2.0, 3.0), _rec(4.0, 5.0, 6.0)])
    assert all(got[a]["unreadable"] == 0 for a in got)
    assert "carried no such term" not in report_md(
        _search(axis_discrimination=got))


# --------------------------------------------------------------------------
# --resume must not publish an interruption as a measurement
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rec,fragment", [
    ({"rc": -15, "verdict": "NOT_MEASURED"}, "signal 15"),
    ({"rc": -9, "verdict": "SCORED"}, "signal 9"),
    ({"rc": 0, "timed_out": True, "verdict": "SCORED"}, "TIMED OUT"),
    ({"rc": None, "verdict": "SCORED"}, "no exit status"),
    ({"rc": 1, "verdict": "NOT_MEASURED"}, "carries no score"),
    ({"rc": 1, "verdict": "REFUSED"}, "carries no score"),
])
def test_an_interrupted_record_is_not_resumable(rec, fragment):
    """MEASURED, and it cost six configurations of a fifty-configuration
    campaign: stopping the search SIGTERM'd its children, the loop wrote six
    `rc: -15` records with NOT_MEASURED metrics, and `--resume` reused them —
    publishing an interruption as a measurement of those configurations."""
    why = ppa_search_resumable(rec)
    assert why is not None
    assert fragment in why


def test_a_completed_scored_record_is_resumable():
    assert ppa_search_resumable(
        {"rc": 1, "timed_out": False, "verdict": "SCORED"}) is None


def test_a_completed_record_with_no_verdict_yet_is_resumable():
    """The reference record is written before it is scored; rc=1 is the phase-3
    runner's normal completion-audit exit and must not be read as a failure."""
    assert ppa_search_resumable({"rc": 1, "timed_out": False}) is None
