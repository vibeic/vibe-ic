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
from ppa_search import (BASELINE, DEFAULT_SPACE, KNOB_FLAGS, _expand,
                        config_id, report_md, step_progress)


def test_the_default_space_actually_reaches_fifty():
    configs = _expand(DEFAULT_SPACE)
    assert len(configs) >= 50, (
        "the declared bar is >=50 CONFIGURATIONS; a space smaller than that "
        "cannot meet it however many times it is run")
    assert len({config_id(c) for c in configs}) == len(configs), (
        "50 records means 50 DISTINCT configurations, not 50 attempts")


def test_the_baseline_is_inside_the_space_and_uses_runner_defaults():
    assert BASELINE in _expand(DEFAULT_SPACE), (
        "the thing the search has to beat must be one of the things it ran, "
        "or the comparison is against a number from a different measurement")
    assert set(BASELINE) == set(KNOB_FLAGS)


def test_config_id_is_decodable_without_the_record():
    cid = config_id({"util": 0.4, "die_um": "100x100", "spare_density": 0.02})
    for fragment in ("util-0p4", "die_um-100x100", "spare_density-0p02"):
        assert fragment in cid


def test_every_searched_knob_is_a_flag_the_runner_already_exposes():
    """A search that needs a private channel into the runner is a search whose
    records cannot be reproduced from the records."""
    runner = (Path(__file__).resolve().parent.parent
              / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    for flag in KNOB_FLAGS.values():
        assert f'p.add_argument("{flag}"' in runner, flag


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
    assert "**3**" in md and "**1**" in md


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
    assert "Ray" in md and "flow progress" in md


def test_an_empty_ranking_does_not_render_as_a_result():
    md = report_md(_search(ranking=[], scored=0, not_measured=2))
    assert "| 1 |" not in md
