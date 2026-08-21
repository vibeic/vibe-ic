#!/usr/bin/env python3
"""`_ppa/search.py` — the properties the rest of the PPA work may assume.

Each test is here because its OPPOSITE is a plausible implementation somebody
writes next week without noticing what it broke. The two that matter most:

  * `test_stub_feasibility_is_undetermined_never_eligible` — a missing
    feasibility lane must not manufacture eligibility.
  * `test_completed_stage_refuses_a_tuner_iteration` — ORFS's `step` is not
    progress, and the wrong version of that line typechecks.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import canonical_json as cj  # noqa: E402
from _ppa import search as S  # noqa: E402

DIGEST = "sha256:" + "0" * 64


def _cand(knobs=None):
    return S.Candidate(knobs=knobs or {}, space_digest=DIGEST)


def _metric(value, metric="area.design_um2", status="MEASURED"):
    rec = {"schema": "vibeic.ppa.metric.v1", "metric": metric,
           "status": status, "scope": {}, "source": {}}
    if status == "MEASURED":
        rec["value"] = value
    else:
        rec["reason"] = "fixture"
    return rec


def _all_pass(_c):
    return S.FeasibilityVerdict("ELIGIBLE", "all nine terms read",
                                {t: "PASS" for t in S.FEASIBILITY_TERMS})


# ---------------------------------------------------------------------------
# §11.2 the fidelity ladder, and ORFS trap 1
# ---------------------------------------------------------------------------
def test_completed_stage_refuses_a_tuner_iteration():
    """MUTATION TARGET. Drop the isinstance(int) guard in
    `Candidate.set_completed_stage` and this goes red.

    `completed_stage = row["step"]` is the one-line wrong implementation. It
    typechecks, it plots, and it makes every fidelity comparison in the
    manifest compare things that were never at the same point in the flow --
    a trial that died in floorplan and one that finished routing can carry the
    same Ray Tune `step`.
    """
    c = _cand()
    with pytest.raises(TypeError) as exc:
        c.set_completed_stage(7)
    assert "step" in str(exc.value)
    assert c.completed_stage is None, \
        "a refused assignment must leave no stage behind"


def test_completed_stage_refuses_a_bool_too():
    """`True` is an int in Python, so the guard must not be fooled by it."""
    with pytest.raises(TypeError):
        _cand().set_completed_stage(True)


def test_completed_stage_refuses_a_name_off_the_ladder():
    with pytest.raises(ValueError):
        _cand().set_completed_stage("route")   # near-miss for global_route


def test_completed_stage_accepts_a_real_rung_and_none():
    c = _cand()
    c.set_completed_stage("cts")
    assert c.completed_stage == "cts"
    c.set_completed_stage(None)
    assert c.completed_stage is None


def test_never_ran_does_not_rank_as_the_cheapest_success():
    """-1 rather than 0. `synth` is a real rung and "nothing completed" must
    not sort as if it were a cheap success."""
    assert S.stage_rank(None) == -1
    assert S.stage_rank("synth") == 0
    assert S.stage_rank("post_route_extracted") == len(S.FIDELITY_LADDER) - 1
    assert S.stage_rank("not-a-stage") == -1


# ---------------------------------------------------------------------------
# feasibility — the line that matters most
# ---------------------------------------------------------------------------
def test_stub_feasibility_is_undetermined_never_eligible():
    """MUTATION TARGET. Make `stub_feasibility` return ELIGIBLE and this reds.

    A missing feasibility lane must never manufacture eligibility: "nothing
    said this candidate was infeasible" and "this candidate was checked and is
    feasible" are opposite facts, and only one of them is a claim about
    silicon.
    """
    v = S.stub_feasibility(_cand())
    assert v.verdict == S.FEAS_UNDETERMINED
    assert v.verdict != S.FEAS_ELIGIBLE
    assert v.reason, "an UNDETERMINED verdict carries a reason, not a silence"


def test_stub_names_all_nine_terms_as_not_checked():
    """Explicitly NOT_CHECKED, not absent: a reader must see there are nine
    terms and that none was answered."""
    v = S.stub_feasibility(_cand())
    assert set(v.terms) == set(S.FEASIBILITY_TERMS)
    assert set(v.terms.values()) == {"NOT_CHECKED"}
    assert len(S.FEASIBILITY_TERMS) == 9


def test_drc_is_one_of_nine_terms_not_the_verdict():
    """The replacement for ORFS `num_drc` as an anti-cheating term."""
    assert "drc" in S.FEASIBILITY_TERMS
    assert len(S.FEASIBILITY_TERMS) > 1
    for t in ("setup", "hold", "drv", "lvs", "antenna", "ir", "em",
              "equivalence"):
        assert t in S.FEASIBILITY_TERMS


def test_a_candidate_that_never_ran_is_undetermined_with_its_own_reason():
    """No artefact exists to check, which is not the same as a clean check."""
    led = S.Ledger(S.Budget(max_trials=1), DIGEST)
    led.admit([_cand({"e": "a"}), _cand({"e": "b"})])
    led.evaluate_feasibility(_all_pass)
    unrun = [c for c in led.candidates if c.state == S.ST_BUDGET_EXHAUSTED]
    assert unrun, "budget 1 over 2 points must leave one unrun"
    for c in unrun:
        assert c.feasibility.verdict == S.FEAS_UNDETERMINED
        assert "no feasibility evidence" in c.feasibility.reason


# ---------------------------------------------------------------------------
# §11.6 budget — an input, and honest at 1
# ---------------------------------------------------------------------------
def test_default_budget_is_one_trial_and_is_usable():
    """MUTATION TARGET. Raise the default and this reds.

    Never require N runs to produce a result: the smallest useful budget is the
    one you get for free.
    """
    b = S.Budget()
    assert b.max_trials == 1
    assert b.problems() == []


def test_budget_of_one_still_publishes_every_proposed_point():
    """A budget that truncates must not truncate the ARTEFACT. A point dropped
    before publication and a point never proposed look identical otherwise."""
    led = S.Ledger(S.Budget(max_trials=1), DIGEST)
    led.admit([_cand({"e": v}) for v in ("a", "b", "c", "d")])
    assert len(led.candidates) == 4
    spent = led.budget_spent()
    assert spent["trials_proposed"] == 4
    assert spent["states"][S.ST_BUDGET_EXHAUSTED] == 3


def test_full_pnr_line_may_not_exceed_the_trial_line():
    assert S.Budget(max_trials=2, max_full_pnr_trials=5).problems()
    assert not S.Budget(max_trials=5, max_full_pnr_trials=5).problems()


def test_zero_trials_is_not_a_budget():
    assert S.Budget(max_trials=0).problems()


def test_failed_trial_policy_may_not_be_invented():
    assert S.Budget(failed_trial_policy="whatever").problems()
    assert not S.Budget(failed_trial_policy=S.FAILED_FREE).problems()


def test_budget_record_states_unbounded_as_null_rather_than_omitting_it():
    """"declared, and unbounded" and "the writer forgot" are different facts."""
    rec = S.Budget().as_record()
    for key in ("max_cpu_hours", "max_wall_seconds", "memory_limit_mb",
                "per_trial_timeout_s"):
        assert key in rec and rec[key] is None


def test_failed_policy_changes_what_is_charged():
    """The two defensible answers give DIFFERENT trial counts, which is why the
    policy may not be left implicit."""
    def build(policy):
        led = S.Ledger(S.Budget(max_trials=3, failed_trial_policy=policy),
                       DIGEST)
        led.admit([_cand({"e": v}) for v in ("a", "b", "c")])
        for c, st in zip(led.candidates,
                         [S.ST_COMPLETED, S.ST_FAILED, S.ST_COMPLETED]):
            c.state = st
            c.set_completed_stage("synth")
        return led.trials_charged()
    assert build(S.FAILED_COUNTS) == 3
    assert build(S.FAILED_FREE) == 2


def test_a_cache_hit_is_published_as_a_trial_but_costs_no_budget():
    led = S.Ledger(S.Budget(max_trials=2, cache_policy=S.CACHE_REUSE), DIGEST)
    led.admit([_cand({"e": "a"}), _cand({"e": "b"})])
    for c in led.candidates:
        c.state = S.ST_COMPLETED
        c.set_completed_stage("synth")
    led.candidates[0].cache_hit = True
    spent = led.budget_spent()
    assert spent["trials_ran"] == 2, "a cache hit is still a published trial"
    assert spent["trials_charged"] == 1, "a cache hit consumed no machine"
    assert spent["cache_hits"] == 1


def test_cpu_hours_is_none_not_zero_when_nothing_was_instrumented():
    """MUTATION TARGET. Return 0.0 instead of None and this reds.

    Contract §2: no numeric sentinels. "not instrumented" and "used no CPU"
    are opposite facts and 0.0 reads as the second.
    """
    led = S.Ledger(S.Budget(max_trials=1), DIGEST)
    led.admit([_cand({"e": "a"})])
    led.candidates[0].state = S.ST_COMPLETED
    led.candidates[0].set_completed_stage("synth")
    assert led.cpu_hours() is None
    led.candidates[0].cpu_seconds = 3600.0
    assert led.cpu_hours() == pytest.approx(1.0)


def test_wall_time_is_not_modelled_when_it_cannot_be_reconstructed():
    """At concurrency > 1 a sum is not the elapsed span, and dividing by the
    concurrency would publish a MODEL as a measurement."""
    def led_at(conc):
        led = S.Ledger(S.Budget(max_trials=2, concurrency=conc), DIGEST)
        led.admit([_cand({"e": "a"}), _cand({"e": "b"})])
        for c in led.candidates:
            c.state = S.ST_COMPLETED
            c.set_completed_stage("synth")
            c.wall_seconds = 10.0
        return led
    assert led_at(1).wall_seconds() == pytest.approx(20.0)
    assert led_at(4).wall_seconds() is None


# ---------------------------------------------------------------------------
# §11.1 lifecycle
# ---------------------------------------------------------------------------
def test_no_non_terminal_state_may_be_published():
    assert S.ST_PROPOSED not in S.TERMINAL_STATES
    assert S.ST_RUNNING not in S.TERMINAL_STATES
    for st in (S.ST_COMPLETED, S.ST_FAILED, S.ST_TIMEOUT,
               S.ST_BUDGET_EXHAUSTED, S.ST_DEDUPLICATED, S.ST_REJECTED_SPACE):
        assert st in S.TERMINAL_STATES


def test_states_that_never_ran_are_not_counted_as_trials():
    """Otherwise a search inflates its trial number without spending a second
    of CPU."""
    for st in (S.ST_REJECTED_SPACE, S.ST_DEDUPLICATED, S.ST_BUDGET_EXHAUSTED):
        assert st not in S.RAN_STATES


def test_identical_knobs_deduplicate_and_are_still_published():
    led = S.Ledger(S.Budget(max_trials=5), DIGEST)
    led.admit([_cand({"e": "a"}), _cand({"e": "a"}), _cand({"e": "b"})])
    states = [c.state for c in led.candidates]
    assert states.count(S.ST_DEDUPLICATED) == 1
    assert len(led.candidates) == 3, "a duplicate is recorded, never dropped"
    assert led.budget_spent()["trials_proposed"] == 3


def test_identity_is_the_one_serializer_over_space_and_knobs():
    a = S.Candidate(knobs={"x": 1, "y": 2}, space_digest=DIGEST)
    b = S.Candidate(knobs={"y": 2, "x": 1}, space_digest=DIGEST)
    assert a.identity == b.identity, "key order is not part of the fact"
    assert a.identity == cj.digest_of({"space": DIGEST,
                                       "knobs": {"x": 1, "y": 2}})
    c = S.Candidate(knobs={"x": 1, "y": 2}, space_digest="sha256:" + "1" * 64)
    assert a.identity != c.identity, "a different space is a different point"


# ---------------------------------------------------------------------------
# the space -> values, without inventing any (F3)
# ---------------------------------------------------------------------------
def test_a_pipe_list_of_plain_tokens_is_enumerable():
    space = {"levers": [{"lever": "state_encoding", "admitted": True,
                         "domain": "binary | gray | one-hot | johnson"}]}
    vals, notes = S.values_from_space(space)
    assert vals == {"state_encoding": ["binary", "gray", "one-hot", "johnson"]}
    assert notes == []


def test_a_pipe_list_of_RANGES_is_refused_rather_than_searched_as_two_points():
    """MUTATION TARGET. Delete the `..` check in `_tokens_from_domain` and this
    reds.

    `"AREA 0..3 | DELAY 0..4"` names two FAMILIES of four and five values. A
    naive split searches TWO points while reporting a nine-preset space, and
    nothing downstream can see the difference.
    """
    space = {"levers": [{"lever": "synthesis_strategy", "admitted": True,
                         "domain": "AREA 0..3 | DELAY 0..4"}]}
    vals, notes = S.values_from_space(space)
    assert vals == {}
    assert len(notes) == 1
    assert notes[0]["status"] == S.NOT_ENUMERABLE
    assert "AREA 0..3" in notes[0]["reason"]


def test_an_unenumerable_lever_is_published_not_dropped():
    """A lever that silently vanished from a search and a lever that was never
    searchable must not look the same in the artefact."""
    space = {"levers": [{"lever": "pipelining", "admitted": True,
                         "domain": "additional pipeline stages, 0..N"}]}
    _, notes = S.values_from_space(space)
    assert [n["lever"] for n in notes] == ["pipelining"]


def test_explicit_values_beat_the_prose_domain():
    space = {"levers": [{"lever": "synthesis_strategy", "admitted": True,
                         "domain": "AREA 0..3 | DELAY 0..4"}]}
    vals, notes = S.values_from_space(space, {"synthesis_strategy":
                                              ["AREA 0", "DELAY 2"]})
    assert vals == {"synthesis_strategy": ["AREA 0", "DELAY 2"]}
    assert notes == []


def test_a_lever_the_space_refused_is_never_searched():
    """The space decides what may be searched; supplying values does not
    promote a PINNED lever into the search."""
    space = {"levers": [{"lever": "pipelining", "admitted": False,
                         "status": "PINNED", "domain": "a | b"}]}
    vals, notes = S.values_from_space(space, {"pipelining": ["1", "2"]})
    assert vals == {}
    assert notes[0]["status"] == "NOT_ADMITTED"


# ---------------------------------------------------------------------------
# proposing — deterministic, baseline first
# ---------------------------------------------------------------------------
def test_the_same_seed_reproduces_the_same_sequence():
    vals = {"a": ["1", "2", "3"], "b": ["x", "y"]}
    one = [c.knobs for c in S.propose(vals, S.Budget(seed=42), DIGEST)]
    two = [c.knobs for c in S.propose(vals, S.Budget(seed=42), DIGEST)]
    assert one == two


def test_a_different_seed_moves_the_sequence():
    vals = {"a": ["1", "2", "3", "4"], "b": ["x", "y", "z"]}
    one = [c.knobs for c in S.propose(vals, S.Budget(seed=1), DIGEST)]
    two = [c.knobs for c in S.propose(vals, S.Budget(seed=2), DIGEST)]
    assert one != two
    assert sorted(map(cj.dumps, one)) == sorted(map(cj.dumps, two)), \
        "a different seed reorders the same grid, it does not change it"


def test_the_baseline_is_always_first():
    """A search whose first trial is random measures its improvement against
    whichever draw it happened to make."""
    vals = {"a": ["1", "2", "3"], "b": ["x", "y"]}
    for seed in range(5):
        first = S.propose(vals, S.Budget(seed=seed), DIGEST)[0]
        assert first.knobs == {"a": "1", "b": "x"}
        assert first.note == "baseline"


def test_module_level_random_cannot_move_the_sequence():
    """`random.Random(seed)` rather than the module-level `random`, so a caller
    elsewhere in the process cannot change what this search proposes."""
    import random as _r
    vals = {"a": ["1", "2", "3", "4"]}
    _r.seed(999)
    one = [c.knobs for c in S.propose(vals, S.Budget(seed=7), DIGEST)]
    [_r.random() for _ in range(50)]
    two = [c.knobs for c in S.propose(vals, S.Budget(seed=7), DIGEST)]
    assert one == two


def test_no_searchable_lever_still_gives_one_honest_candidate():
    cands = S.propose({}, S.Budget(), DIGEST)
    assert len(cands) == 1
    assert cands[0].knobs == {}
    assert "baseline" in cands[0].note


def test_propose_is_not_truncated_to_the_budget():
    """Truncating here would make a dropped point indistinguishable from a
    point that was never proposed. The scheduler marks them instead."""
    vals = {"a": ["1", "2", "3", "4", "5"]}
    assert len(S.propose(vals, S.Budget(max_trials=1), DIGEST)) == 5


# ---------------------------------------------------------------------------
# the frontier input — the three exclusion rules
# ---------------------------------------------------------------------------
def _ledger_of(stages, feas=_all_pass, values=None):
    led = S.Ledger(S.Budget(max_trials=len(stages),
                            max_full_pnr_trials=len(stages)), DIGEST)
    led.admit([_cand({"e": f"v{i}"}) for i in range(len(stages))])
    values = values or [100.0 + i for i in range(len(stages))]
    for c, st, v in zip(led.candidates, stages, values):
        c.state = S.ST_COMPLETED
        c.set_completed_stage(st)
        c.metrics = [_metric(v)]
    led.evaluate_feasibility(feas)
    return led


def test_undetermined_empties_the_frontier_and_says_so():
    """MUTATION TARGET. Treat UNDETERMINED as eligible in `frontier_input` and
    this reds. This is the whole lane in one assertion."""
    led = _ledger_of(["post_route_extracted", "post_route_extracted"],
                     feas=S.stub_feasibility)
    fi = S.frontier_input(led)
    assert fi["included_count"] == 0
    assert {e["code"] for e in fi["excluded"]} == {S.EXCL_UNDETERMINED}


def test_undetermined_never_folds_into_ineligible():
    """"we checked and it fails" and "we never checked" are different findings
    and the reader must be able to tell which emptied the frontier."""
    assert S.EXCL_UNDETERMINED != S.EXCL_NOT_ELIGIBLE
    def ineligible(_c):
        return S.FeasibilityVerdict("INELIGIBLE", "setup fails",
                                    {t: "FAIL" for t in S.FEASIBILITY_TERMS})
    fi = S.frontier_input(_ledger_of(["post_route_extracted"], ineligible))
    assert {e["code"] for e in fi["excluded"]} == {S.EXCL_NOT_ELIGIBLE}


def test_a_frontier_never_mixes_fidelity_stages():
    """MUTATION TARGET. Drop the stage comparison in `frontier_input` and this
    reds.

    Contract §2: synthesis area and post-route area are different metrics. A
    frontier over both is a category error with a plot -- and the cheap rung
    always looks better, so mixing them flatters the run.
    """
    led = _ledger_of(["post_route_extracted", "synth", "post_route_extracted"])
    fi = S.frontier_input(led)
    assert fi["frontier_stage"] == "post_route_extracted"
    assert fi["included_count"] == 2
    assert [e["code"] for e in fi["excluded"]] == [S.EXCL_SCOPE_MISMATCH]


def test_the_frontier_stage_can_be_pinned_by_the_caller():
    led = _ledger_of(["post_route_extracted", "synth"])
    fi = S.frontier_input(led, frontier_stage="synth")
    assert fi["frontier_stage"] == "synth"
    assert fi["included_count"] == 1


def test_only_measured_metrics_enter_a_comparison():
    led = _ledger_of(["post_route_extracted"])
    led.candidates[0].metrics = [_metric(None, status="ESTIMATED")]
    fi = S.frontier_input(led)
    assert [e["code"] for e in fi["excluded"]] == [S.EXCL_NO_MEASURED_METRIC]


def test_a_candidate_that_did_not_run_has_its_own_exclusion_code():
    led = S.Ledger(S.Budget(max_trials=1), DIGEST)
    led.admit([_cand({"e": "a"}), _cand({"e": "b"})])
    led.candidates[0].state = S.ST_COMPLETED
    led.candidates[0].set_completed_stage("synth")
    led.candidates[0].metrics = [_metric(1.0)]
    led.evaluate_feasibility(_all_pass)
    fi = S.frontier_input(led)
    codes = {e["code"] for e in fi["excluded"]}
    assert S.EXCL_DID_NOT_RUN in codes


def test_every_candidate_is_either_included_or_excluded_with_a_reason():
    """No candidate may simply be absent from the frontier accounting."""
    led = _ledger_of(["post_route_extracted", "synth"])
    fi = S.frontier_input(led)
    assert fi["included_count"] + fi["excluded_count"] == len(led.candidates)


def test_an_empty_frontier_is_a_complete_answer_not_an_error():
    led = _ledger_of([], feas=S.stub_feasibility)
    fi = S.frontier_input(led)
    assert fi["included_count"] == 0
    assert fi["frontier_stage"] is None


# ---------------------------------------------------------------------------
# the manifest audit — the negative fixtures
# ---------------------------------------------------------------------------
def _good_manifest():
    led = _ledger_of(["post_route_extracted", "post_route_extracted"])
    for c in led.candidates:
        c.cpu_seconds, c.wall_seconds = 60.0, 30.0
    return S.build_manifest(led, DIGEST)


def _codes(man):
    return {f["code"] for f in S.audit_manifest(man)}


def test_a_well_formed_manifest_audits_clean():
    """POSITIVE fixture. Without it every negative below could be passing for
    the wrong reason -- an audit that reds on everything discriminates nothing.
    """
    assert S.audit_manifest(_good_manifest()) == []


def test_audit_catches_a_truncated_ledger():
    """Publish every trial, not the best one."""
    man = _good_manifest()
    man["candidates"] = man["candidates"][:1]
    assert "LEDGER_TRUNCATED" in _codes(man)


def test_audit_catches_a_plan_published_as_a_result():
    man = _good_manifest()
    man["candidates"][0]["state"] = S.ST_PROPOSED
    assert "NON_TERMINAL_STATE" in _codes(man)


def test_audit_catches_a_tuner_step_recorded_as_a_stage():
    """MUTATION TARGET. Remove the STEP_LEAKED_AS_STAGE clause and this reds."""
    man = _good_manifest()
    man["candidates"][0]["completed_stage"] = 12
    assert "STEP_LEAKED_AS_STAGE" in _codes(man)


def test_audit_catches_eligibility_declared_on_a_partial_vector():
    """MUTATION TARGET. Remove the ELIGIBLE_ON_A_PARTIAL_VECTOR clause and this
    reds.

    This is the ORFS `num_drc` cheat in its final form: a verdict of ELIGIBLE
    whose evidence is the detailed-route violation count and nothing else.
    """
    man = _good_manifest()
    man["candidates"][0]["feasibility"] = {
        "verdict": "ELIGIBLE", "reason": "num_drc was 0",
        "terms": {"drc": "PASS"}}
    codes = _codes(man)
    assert "ELIGIBLE_ON_A_PARTIAL_VECTOR" in codes


def test_not_applicable_is_an_acceptable_term_state():
    """A term the contract PROVES does not apply is not a missing check."""
    man = _good_manifest()
    terms = {t: "PASS" for t in S.FEASIBILITY_TERMS}
    terms["em"] = "NOT_APPLICABLE"
    man["candidates"][0]["feasibility"]["terms"] = terms
    assert "ELIGIBLE_ON_A_PARTIAL_VECTOR" not in _codes(man)


def test_audit_catches_a_frontier_point_that_is_not_eligible():
    man = _good_manifest()
    man["candidates"][0]["feasibility"]["verdict"] = "UNDETERMINED"
    assert "FRONTIER_POINT_NOT_ELIGIBLE" in _codes(man)


def test_audit_catches_a_frontier_mixing_stages():
    man = _good_manifest()
    man["frontier_input"]["included"][0]["completed_stage"] = "synth"
    assert "FRONTIER_SCOPE_MIXED" in _codes(man)


def test_audit_catches_a_frontier_point_in_no_published_candidate():
    man = _good_manifest()
    man["frontier_input"]["included"][0]["identity"] = "sha256:" + "f" * 64
    assert "FRONTIER_POINT_NOT_IN_LEDGER" in _codes(man)


def test_audit_catches_an_unmeasured_metric_on_the_frontier():
    man = _good_manifest()
    man["frontier_input"]["included"][0]["metrics"][0]["status"] = "ESTIMATED"
    assert "FRONTIER_USES_UNMEASURED_METRIC" in _codes(man)


def test_audit_catches_more_full_pnr_trials_than_the_budget_declared():
    man = _good_manifest()
    man["budget"]["max_full_pnr_trials"] = 1
    assert "FULL_PNR_OVER_BUDGET" in _codes(man)


def test_audit_catches_a_budget_dimension_left_implicit():
    for key in S.Budget().as_record():
        man = _good_manifest()
        del man["budget"][key]
        assert "BUDGET_FIELD_MISSING" in _codes(man), \
            f"dropping budget.{key} must be a finding"


def test_audit_catches_cache_hits_undeclared_under_a_reuse_policy():
    man = _good_manifest()
    man["budget"]["cache_policy"] = S.CACHE_REUSE
    man["budget_spent"]["cache_hits"] = None
    assert "CACHE_HITS_NOT_DECLARED" in _codes(man)


def test_audit_catches_a_trial_that_ran_without_a_stage():
    man = _good_manifest()
    man["candidates"][0]["completed_stage"] = None
    assert "RAN_WITHOUT_A_STAGE" in _codes(man)


def test_audit_catches_the_wrong_schema_key():
    man = _good_manifest()
    man["schema"] = "vibeic.ppa.search_manifest.v2"
    assert "WRONG_SCHEMA" in _codes(man)


def test_audit_of_an_empty_document_is_findings_not_silence():
    """A manifest with nothing in it must not audit clean."""
    assert S.audit_manifest({}) != []


# ---------------------------------------------------------------------------
# the published sentence
# ---------------------------------------------------------------------------
def test_the_headline_sentence_carries_cost_beside_the_trial_count():
    """Comparing tuners on trial COUNT alone is meaningless, so the count never
    appears without CPU-hours and wall time in the same breath."""
    man = _good_manifest()
    s = man["what_the_budget_bought"]["sentence"]
    assert "trial" in s and "CPU-hours" in s and "wall" in s
    assert "full place-and-route" in s


def test_the_sentence_distinguishes_two_different_nones_for_wall_time():
    """F6: "nothing to add up" and "the sum is not the elapsed span" must not
    share a phrase."""
    led = S.Ledger(S.Budget(max_trials=1), DIGEST)
    led.admit([_cand({"e": "a"})])
    led.evaluate_feasibility(S.stub_feasibility)
    nothing_ran = S.build_manifest(led, DIGEST)["what_the_budget_bought"]

    led2 = S.Ledger(S.Budget(max_trials=2, concurrency=4), DIGEST)
    led2.admit([_cand({"e": "a"}), _cand({"e": "b"})])
    for c in led2.candidates:
        c.state = S.ST_COMPLETED
        c.set_completed_stage("synth")
        c.wall_seconds = 5.0
    led2.evaluate_feasibility(S.stub_feasibility)
    concurrent = S.build_manifest(led2, DIGEST)["what_the_budget_bought"]

    assert "not instrumented" in nothing_ran["sentence"]
    assert "not reconstructible" in concurrent["sentence"]
    assert nothing_ran["sentence"] != concurrent["sentence"]
