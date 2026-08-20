#!/usr/bin/env python3
"""`_ppa/backends/orfs.py` — the two lies an ORFS result row tells, refused.

Both are invisible defects: they typecheck, they plot, and they are wrong in a
direction that flatters the run. Every test here names the one-line wrong
implementation it prevents.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import search as S  # noqa: E402
from _ppa.backends import orfs  # noqa: E402


def _by_name(records):
    return {r["metric"]: r for r in records}


# ---------------------------------------------------------------------------
# TRAP 1 — `step` is a Ray Tune training iteration, not flow progress
# ---------------------------------------------------------------------------
def test_step_never_becomes_a_stage():
    """MUTATION TARGET. Add "step" to `STAGE_KEYS` and this goes red.

    The wrong implementation is `completed_stage = row["step"]`. A trial that
    died in floorplan and one that finished routing can carry the same `step`.
    """
    stage, why = orfs.completed_stage_of({"step": 42, "num_drc": 0})
    assert stage is None
    assert "step" in why and "flow progress" in why


def test_training_iteration_is_refused_the_same_way():
    stage, why = orfs.completed_stage_of({"training_iteration": 9})
    assert stage is None
    assert "iteration counter" in why


def test_a_numeric_value_in_a_stage_key_is_refused_not_stringified():
    """A tuner counter written into a field called `stage` is still a tuner
    counter, and `str(3)` would make it look like a stage name."""
    stage, why = orfs.completed_stage_of({"stage": 3})
    assert stage is None
    assert "not a stage name" in why


def test_an_explicitly_stated_stage_is_used_and_its_source_recorded():
    stage, why = orfs.completed_stage_of({"flow_stage": "cts", "step": 5})
    assert stage == "cts"
    assert "flow_stage" in why


def test_no_stage_anywhere_says_so_rather_than_guessing():
    stage, why = orfs.completed_stage_of({"num_drc": 0})
    assert stage is None
    assert "states no flow stage" in why


def test_a_row_with_no_stage_yields_no_MEASURED_ordinary_metric():
    """A number without a scope cannot enter a comparison (contract §2), so it
    is NOT_MEASURED rather than MEASURED-with-a-blank-scope."""
    out = orfs.parse_row({"step": 3, "worst_slack": -0.1, "design_area": 10.0})
    recs = _by_name(out["records"])
    assert recs["timing.worst_slack_ns"]["status"] == "NOT_MEASURED"
    assert recs["area.design_um2"]["status"] == "NOT_MEASURED"
    assert "step" in recs["area.design_um2"]["reason"]


def test_a_scoped_row_does_yield_MEASURED_metrics():
    """The positive half: without it the NOT_MEASURED tests above could be
    passing because the parser measures nothing at all."""
    out = orfs.parse_row({"worst_slack": -0.1, "design_area": 10.0},
                         stage="post_route_extracted")
    recs = _by_name(out["records"])
    assert recs["timing.worst_slack_ns"]["status"] == "MEASURED"
    assert recs["timing.worst_slack_ns"]["value"] == -0.1
    assert recs["area.design_um2"]["value"] == 10.0
    assert recs["area.design_um2"]["scope"]["stage"] == "post_route_extracted"


def test_a_caller_stage_and_a_row_stage_that_disagree_are_recorded():
    out = orfs.parse_row({"flow_stage": "cts"}, stage="post_route_extracted")
    assert out["completed_stage"] == "post_route_extracted"
    assert "disagreement is recorded" in out["completed_stage_reason"]


def test_the_stage_the_parser_returns_survives_the_candidate_guard():
    """End-to-end: whatever `parse_row` calls a stage must be assignable, and
    whatever it refuses must stay refused."""
    good = orfs.parse_row({"flow_stage": "cts"})
    c = S.Candidate(knobs={}, space_digest="sha256:" + "0" * 64)
    c.set_completed_stage(good["completed_stage"])
    assert c.completed_stage == "cts"

    bad = orfs.parse_row({"step": 11})
    c2 = S.Candidate(knobs={}, space_digest="sha256:" + "0" * 64)
    c2.set_completed_stage(bad["completed_stage"])   # None, not 11
    assert c2.completed_stage is None


# ---------------------------------------------------------------------------
# TRAP 2 — `num_drc` is detailed-route DRC only
# ---------------------------------------------------------------------------
def test_num_drc_produces_two_records_not_one():
    """MUTATION TARGET. Make `_drc_records` return only the detailed-route
    record and this goes red.

    With one record a manifest holds a row saying `drc: 0` and every reader,
    human and program, takes it for a sign-off result.
    """
    recs = _by_name(orfs.parse_row({"num_drc": 0},
                                   stage="post_route_extracted")["records"])
    assert "drc.detailed_route.violations" in recs
    assert "drc.signoff.violations" in recs


def test_the_signoff_record_is_NOT_MEASURED_with_the_reason():
    recs = _by_name(orfs.parse_row({"num_drc": 0})["records"])
    signoff = recs["drc.signoff.violations"]
    assert signoff["status"] == "NOT_MEASURED"
    assert "value" not in signoff, \
        "NOT_MEASURED carries a reason, never a value — not even a null"
    for term in ("LVS", "antenna", "IR", "EM", "equivalence"):
        assert term in signoff["reason"]


def test_zero_violations_still_produces_the_NOT_MEASURED_signoff_row():
    """`num_drc: 0` is the exact value that reads as "clean", so it is the
    value the refusal has to survive."""
    recs = _by_name(orfs.parse_row({"num_drc": 0})["records"])
    assert recs["drc.detailed_route.violations"]["value"] == 0
    assert recs["drc.signoff.violations"]["status"] == "NOT_MEASURED"


def test_the_detailed_route_record_is_scoped_to_detailed_route():
    """Not to whatever stage the row belongs to: the number IS a
    detailed-route number, and scoping it to `post_route_extracted` would let
    it be compared with a sign-off count."""
    recs = _by_name(orfs.parse_row({"num_drc": 7},
                                   stage="post_route_extracted")["records"])
    assert recs["drc.detailed_route.violations"]["scope"]["stage"] == \
        "detailed_route"
    assert recs["drc.signoff.violations"]["scope"]["stage"] == "signoff"


def test_the_detailed_route_record_warns_against_its_own_misuse():
    recs = _by_name(orfs.parse_row({"num_drc": 0})["records"])
    note = recs["drc.detailed_route.violations"]["note"]
    assert "not a sign-off verdict" in note
    assert "eligibility term" in note


def test_a_non_numeric_num_drc_is_INVALID_not_zero():
    recs = _by_name(orfs.parse_row({"num_drc": "N/A"})["records"])
    assert recs["drc.detailed_route.violations"]["status"] == "INVALID"
    assert "value" not in recs["drc.detailed_route.violations"]
    assert "drc.signoff.violations" in recs, \
        "the sign-off refusal survives a broken detailed-route number"


def test_drc_key_is_not_reachable_through_the_plain_numeric_table():
    """Structural: a future editor adding a metric must not be able to give
    `num_drc` the ordinary treatment by adding one line."""
    assert orfs.DRC_KEY not in orfs.NUMERIC_METRICS


# ---------------------------------------------------------------------------
# version honesty and the parse contract
# ---------------------------------------------------------------------------
def test_an_unrecognised_key_is_named_not_dropped():
    """An ORFS field rename must surface as a named unread key, not as a report
    that quietly got shorter."""
    out = orfs.parse_row({"some_new_metric": 1.0, "design_area": 2.0},
                         stage="synth")
    assert out["unmapped_keys"] == ["some_new_metric"]


def test_tuner_bookkeeping_is_ignored_but_listed_separately():
    """An ignored key and an unrecognised key are different facts."""
    out = orfs.parse_row({"step": 1, "trial_id": "abc", "time_total_s": 9.0},
                         stage="synth")
    assert out["unmapped_keys"] == []
    assert set(out["tuner_keys"]) == {"step", "trial_id", "time_total_s"}
    assert out["records"] == [], "no tuner key is a design metric"


def test_worst_slack_does_not_claim_setup_or_hold():
    """The tool key does not say which check it is, so the parser does not
    either. `scope.check` is a declared null, not a missing key a consumer
    might treat as a wildcard."""
    rec = _by_name(orfs.parse_row({"worst_slack": 0.4},
                                  stage="post_route_extracted")["records"])
    ws = rec["timing.worst_slack_ns"]
    assert "check" in ws["scope"] and ws["scope"]["check"] is None
    assert "setup or hold" in ws["note"]


def test_a_non_numeric_metric_is_INVALID_not_silently_skipped():
    rec = _by_name(orfs.parse_row({"design_area": "unknown"},
                                  stage="synth")["records"])
    assert rec["area.design_um2"]["status"] == "INVALID"


def test_a_boolean_is_not_a_number():
    rec = _by_name(orfs.parse_row({"design_area": True},
                                  stage="synth")["records"])
    assert rec["area.design_um2"]["status"] == "INVALID"


def test_every_record_carries_the_parser_and_tool_identity():
    for r in orfs.parse_row({"num_drc": 0, "design_area": 1.0},
                            stage="synth")["records"]:
        assert r["source"]["tool"] == "orfs"
        assert r["source"]["parser"] == orfs.PARSER
        assert r["schema"] == "vibeic.ppa.metric.v1"


def test_the_caller_source_is_preserved_alongside_the_parser_identity():
    r = orfs.parse_row({"design_area": 1.0}, stage="synth",
                       source={"path": "flow/logs/metrics.json"})["records"][0]
    assert r["source"]["path"] == "flow/logs/metrics.json"
    assert r["source"]["parser"] == orfs.PARSER


def test_a_row_that_is_not_an_object_yields_nothing_and_says_why():
    out = orfs.parse_row(["not", "a", "row"])
    assert out["records"] == []
    assert out["completed_stage"] is None
    assert "not an object" in out["completed_stage_reason"]


def test_parse_rows_over_a_non_list_is_empty_never_a_guess():
    assert orfs.parse_rows({"num_drc": 0}) == []
    assert len(orfs.parse_rows([{"num_drc": 0}, {"num_drc": 1}])) == 2


# ---------------------------------------------------------------------------
# the backend holds no policy (PPA_INTERFACES §4)
# ---------------------------------------------------------------------------
def test_the_backend_emits_no_verdict_vocabulary():
    """MUTATION TARGET for the §4 rule. A backend that says PASS/FAIL/ELIGIBLE
    has moved a threshold into a parser, and the next tool added will either
    duplicate it or contradict it."""
    out = orfs.parse_row({"num_drc": 0, "worst_slack": 0.5},
                         stage="post_route_extracted")
    for rec in out["records"]:
        assert rec["status"] in ("MEASURED", "NOT_MEASURED", "NOT_APPLICABLE",
                                "INVALID", "ESTIMATED", "DERIVED")
        assert "verdict" not in rec
        assert "eligible" not in str(rec).lower().replace(
            "eligibility term", "")
