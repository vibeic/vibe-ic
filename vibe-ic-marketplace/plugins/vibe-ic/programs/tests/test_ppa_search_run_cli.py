#!/usr/bin/env python3
"""`ppa_search_run.py` — the exit-code contract, and the audit that gates.

The clause this file exists for is the VACUOUS one. A gate whose declared
invocation exits 2 on absent input can never fail, and this repository has
shipped that twice — so "missing input gives rc=2 WITH A PRINTED MARKER, and a
present-but-wrong input gives rc=1" is asserted directly, both ways, for both
modes.
"""
import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import ppa_search_run as R  # noqa: E402
from _ppa import search as S  # noqa: E402

SCHEMA_PATH = (_PROGRAMS.parent / "schemas" / "ppa"
               / "search_manifest.v1.schema.json")

SPACE = {
    "program": "crosslayer_search_space",
    "levers": [
        {"lever": "state_encoding", "admitted": True, "status": "FREE",
         "domain": "binary | gray | one-hot | johnson"},
        {"lever": "synthesis_strategy", "admitted": True,
         "status": "NO_DESIGN_CHANGE", "domain": "AREA 0..3 | DELAY 0..4"},
        {"lever": "pipelining", "admitted": False, "status": "PINNED",
         "domain": "additional pipeline stages, 0..N"},
    ],
}


@pytest.fixture
def space(tmp_path):
    p = tmp_path / "space.json"
    p.write_text(json.dumps(SPACE))
    return p


def _trial(enc, stage="post_route_extracted", value=100.0, state="COMPLETED"):
    return {
        "knobs": {"state_encoding": enc}, "state": state,
        "completed_stage": stage,
        "metrics": [{"schema": "vibeic.ppa.metric.v1",
                     "metric": "area.design_um2", "status": "MEASURED",
                     "value": value, "unit": "um^2", "scope": {},
                     "source": {}}],
        "cost": {"cpu_seconds": 60.0, "wall_seconds": 30.0,
                 "peak_rss_mb": 512.0},
    }


# ---------------------------------------------------------------------------
# VACUOUS — the fixture that is not paperwork
# ---------------------------------------------------------------------------
def test_absent_space_is_rc2_with_a_marker(tmp_path, capsys):
    rc = R.main([str(tmp_path / "nope.json")])
    err = capsys.readouterr().err
    assert rc == R.RC_UNDETERMINED
    assert R.MARK_CANNOT_CHECK in err
    assert rc != R.RC_PASS and rc != R.RC_REFUSED


def test_absent_manifest_to_verify_is_rc2_with_a_marker(tmp_path, capsys):
    rc = R.main(["--verify", str(tmp_path / "nope.json")])
    err = capsys.readouterr().err
    assert rc == R.RC_UNDETERMINED
    assert R.MARK_CANNOT_CHECK in err
    assert "No clause was evaluated" in err


def test_an_empty_file_is_rc2_not_an_empty_search(tmp_path, capsys):
    """"I read it and it was empty" must not become "a space with no levers",
    which would be published as a legitimate zero-lever search."""
    p = tmp_path / "space.json"
    p.write_text("")
    rc = R.main([str(p)])
    assert rc == R.RC_UNDETERMINED
    assert "carries no document" in capsys.readouterr().err


def test_unparseable_json_is_rc2(tmp_path, capsys):
    p = tmp_path / "space.json"
    p.write_text("{not json")
    assert R.main([str(p)]) == R.RC_UNDETERMINED
    assert R.MARK_CANNOT_CHECK in capsys.readouterr().err


def test_a_directory_where_a_document_belongs_is_rc2(tmp_path):
    d = tmp_path / "space.json"
    d.mkdir()
    assert R.main([str(d)]) == R.RC_UNDETERMINED


def test_a_declared_trials_file_that_cannot_be_read_is_rc2_not_a_plan(
        space, tmp_path, capsys):
    """MUTATION TARGET. Fall through to a plan when --trials cannot be read and
    this reds: it would report zero measured trials as a completed search."""
    rc = R.main([str(space), "--trials", str(tmp_path / "missing.json")])
    assert rc == R.RC_UNDETERMINED
    assert R.MARK_CANNOT_CHECK in capsys.readouterr().err


# ---------------------------------------------------------------------------
# BAD INVOCATION is rc=3 and never a design FAIL
# ---------------------------------------------------------------------------
def test_no_arguments_is_rc3(capsys):
    assert R.main([]) == R.RC_BAD_INVOCATION


def test_both_modes_at_once_is_rc3(space):
    assert R.main([str(space), "--verify", str(space)]) == R.RC_BAD_INVOCATION


def test_a_frontier_stage_off_the_ladder_is_rc3_not_rc1(space):
    """rc=1 is a claim about silicon; a typo in a flag is not one."""
    rc = R.main([str(space), "--frontier-stage", "route"])
    assert rc == R.RC_BAD_INVOCATION


def test_malformed_values_flag_is_rc3(space):
    assert R.main([str(space), "--values", "no-equals-sign"]) == \
        R.RC_BAD_INVOCATION


# ---------------------------------------------------------------------------
# POSITIVE — budget 1, with no flags, is a complete bundle
# ---------------------------------------------------------------------------
<<<<<<< HEAD
def test_budget_one_needs_no_flags_and_produces_a_full_manifest(space,
                                                                tmp_path):
=======
def test_budget_one_needs_no_flags_and_produces_a_full_bundle(space, tmp_path):
>>>>>>> origin/jppa-search/ppa-search-layer
    """MUTATION TARGET. Raise the `--max-trials` default and this reds.
    Never require N runs to produce a result."""
    out = tmp_path / "m.json"
    rc = R.main([str(space), "--json", str(out)])
    assert rc == R.RC_PASS
    man = json.loads(out.read_text())
    assert man["budget"]["max_trials"] == 1
<<<<<<< HEAD
    assert man["schema"] == S.SCHEMA
=======
>>>>>>> origin/jppa-search/ppa-search-layer
    assert len(man["candidates"]) == 4, \
        "every proposed point is published even at budget 1"
    assert man["budget_spent"]["states"]["BUDGET_EXHAUSTED"] == 3


<<<<<<< HEAD
=======
def test_a_plan_declares_the_plan_schema_not_the_manifest_schema(space,
                                                                 tmp_path):
    """MUTATION TARGET. Pass `is_plan=False` in `build` and this reds.

    A plan's candidates are PROPOSED, which `search_manifest.v1` forbids, so a
    plan labelled `search_manifest.v1` is a document declaring a schema it
    cannot satisfy — the exact defect this lane exists to refuse, and one this
    file shipped until it was caught. The FIRST KEY says what the document IS.
    """
    out = tmp_path / "plan.json"
    R.main([str(space), "--json", str(out)])
    plan = json.loads(out.read_text())
    assert plan["schema"] == S.PLAN_SCHEMA
    assert plan["schema"] != S.SCHEMA


def test_a_plan_does_not_validate_as_a_manifest(space, tmp_path):
    """And the schema file agrees: a plan is not an instance of it."""
    jsonschema = pytest.importorskip("jsonschema")
    out = tmp_path / "plan.json"
    R.main([str(space), "--json", str(out)])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(
            json.loads(SCHEMA_PATH.read_text())).validate(
                json.loads(out.read_text()))


def test_supplying_trials_promotes_the_document_to_a_real_manifest(space,
                                                                   tmp_path):
    """The positive half: the plan schema must not be what this program always
    emits, or the distinction would be decoration."""
    t = tmp_path / "trials.json"
    t.write_text(json.dumps([_trial("binary")]))
    out = tmp_path / "m.json"
    assert R.main([str(space), "--trials", str(t), "--json", str(out)]) == \
        R.RC_PASS
    assert json.loads(out.read_text())["schema"] == S.SCHEMA


>>>>>>> origin/jppa-search/ppa-search-layer
def test_the_budget_sentence_names_what_the_budget_bought(space, tmp_path,
                                                          capsys):
    R.main([str(space), "--json", str(tmp_path / "m.json")])
    out = capsys.readouterr().out
    assert "budget 1 trial(s)" in out
    assert "CPU" in out and "wall" in out


def test_a_prose_domain_lever_is_reported_as_not_searched(space, tmp_path):
    """F3. Silently searching two points of a nine-preset space would be
    invisible; the manifest names the lever instead."""
    out = tmp_path / "m.json"
    R.main([str(space), "--json", str(out)])
    notes = json.loads(out.read_text())["lever_notes"]
    assert [n["lever"] for n in notes] == ["synthesis_strategy"]
    assert notes[0]["status"] == "NOT_ENUMERABLE"


def test_a_pinned_lever_is_never_searched(space, tmp_path):
    out = tmp_path / "m.json"
    R.main([str(space), "--json", str(out)])
    man = json.loads(out.read_text())
    for c in man["candidates"]:
        assert "pipelining" not in c["knobs"]


def test_explicit_values_open_a_prose_lever(space, tmp_path):
    out = tmp_path / "m.json"
    rc = R.main([str(space), "--values", "synthesis_strategy=AREA 0,DELAY 2",
                 "--max-trials", "8", "--json", str(out)])
    assert rc == R.RC_PASS
    man = json.loads(out.read_text())
    assert man["lever_notes"] == []
    assert len(man["candidates"]) == 8, "4 encodings x 2 strategies"


# ---------------------------------------------------------------------------
# POSITIVE with trials — and the empty frontier that proves the stub is honest
# ---------------------------------------------------------------------------
@pytest.fixture
def ran(space, tmp_path):
    t = tmp_path / "trials.json"
    t.write_text(json.dumps([_trial("binary", value=120.0),
                             _trial("gray", value=110.0)]))
    out = tmp_path / "m.json"
    rc = R.main([str(space), "--trials", str(t), "--max-trials", "2",
                 "--max-full-pnr-trials", "2", "--json", str(out)])
    return rc, json.loads(out.read_text()), out


def test_observed_trials_are_recorded_with_their_cost(ran):
    rc, man, _ = ran
    assert rc == R.RC_PASS
    assert man["budget_spent"]["trials_ran"] == 2
    assert man["budget_spent"]["full_pnr_trials"] == 2
    assert man["budget_spent"]["cpu_hours"] == pytest.approx(120.0 / 3600.0)
    assert man["budget_spent"]["wall_seconds"] == pytest.approx(60.0)


def test_a_completed_full_pnr_run_STILL_has_an_empty_frontier_under_the_stub(
        ran):
    """MUTATION TARGET, and the single most important assertion in this lane.
    Make `stub_feasibility` return ELIGIBLE and this goes red.

    Two trials completed a full place-and-route with real numbers. The frontier
    is still empty, because nothing has read setup, hold, DRV, DRC, LVS,
    antenna, IR, EM or equivalence for them. A search that published these two
    as a frontier would be asserting silicon it never examined.
    """
    _, man, _ = ran
    fi = man["frontier_input"]
    assert fi["included_count"] == 0
    assert S.EXCL_UNDETERMINED in {e["code"] for e in fi["excluded"]}
    assert man["toolchain"]["feasibility_source"] == "STUB"


def test_every_candidate_appears_in_the_frontier_accounting(ran):
    _, man, _ = ran
    fi = man["frontier_input"]
    assert fi["included_count"] + fi["excluded_count"] == \
        len(man["candidates"])


def test_a_manifest_this_program_built_verifies_clean(ran):
    """POSITIVE for the audit. Without it every negative below could be passing
    because the audit reds on everything."""
    _, _, path = ran
    assert R.main(["--verify", str(path)]) == R.RC_PASS


def test_the_built_manifest_validates_against_its_own_schema(ran):
    jsonschema = pytest.importorskip("jsonschema")
    _, man, _ = ran
    schema = json.loads(SCHEMA_PATH.read_text())
    jsonschema.Draft7Validator(schema).validate(man)


def test_the_schema_itself_is_a_valid_draft7_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft7Validator.check_schema(json.loads(SCHEMA_PATH.read_text()))


def test_the_schema_refuses_an_integer_completed_stage(ran):
    """The ORFS `step` trap, enforced at the document layer as well as the
    code layer — a manifest written by some other producer is still refused."""
    jsonschema = pytest.importorskip("jsonschema")
    _, man, _ = ran
    man["candidates"][0]["completed_stage"] = 7
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(
            json.loads(SCHEMA_PATH.read_text())).validate(man)


def test_the_schema_refuses_a_non_terminal_state(ran):
    jsonschema = pytest.importorskip("jsonschema")
    _, man, _ = ran
    man["candidates"][0]["state"] = "RUNNING"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(
            json.loads(SCHEMA_PATH.read_text())).validate(man)


def test_the_schema_refuses_a_budget_missing_a_dimension(ran):
    jsonschema = pytest.importorskip("jsonschema")
    _, man, _ = ran
    del man["budget"]["cache_policy"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft7Validator(
            json.loads(SCHEMA_PATH.read_text())).validate(man)


# ---------------------------------------------------------------------------
# NEGATIVE — the audit is red when it should be red
# ---------------------------------------------------------------------------
<<<<<<< HEAD
def test_a_plan_published_as_a_result_is_rc1(space, tmp_path, capsys):
    """A plan's candidates are PROPOSED. Publishing them as a search RESULT is
    a finding, and the audit is what makes the distinction cost something."""
    out = tmp_path / "plan.json"
    assert R.main([str(space), "--json", str(out)]) == R.RC_PASS
    assert R.main(["--verify", str(out)]) == R.RC_REFUSED
=======
def test_a_plan_audited_as_a_result_is_rc1_with_ONE_clear_finding(space,
                                                                  tmp_path,
                                                                  capsys):
    """A plan is not a search RESULT, and the audit is what makes the
    distinction cost something.

    ONE finding, not one `NON_TERMINAL_STATE` per candidate: the document is
    honest about being a plan, so the audit names that rather than burying it
    under a per-candidate complaint the reader has to diagnose.
    """
    out = tmp_path / "plan.json"
    assert R.main([str(space), "--json", str(out)]) == R.RC_PASS
    assert R.main(["--verify", str(out)]) == R.RC_REFUSED
    err = capsys.readouterr().err
    assert "PLAN_NOT_A_RESULT" in err
    assert err.count("NON_TERMINAL_STATE") == 0
    assert S.audit_manifest(json.loads(out.read_text())) != []
    assert len(S.audit_manifest(json.loads(out.read_text()))) == 1


def test_a_result_whose_candidates_are_PROPOSED_is_still_caught(space,
                                                                tmp_path,
                                                                capsys):
    """The plan-schema clause must not become an escape hatch: a document that
    CLAIMS to be a manifest and carries an unfinished trial is still red."""
    t = tmp_path / "trials.json"
    t.write_text(json.dumps([_trial("binary")]))
    out = tmp_path / "m.json"
    R.main([str(space), "--trials", str(t), "--json", str(out)])
    man = json.loads(out.read_text())
    assert man["schema"] == S.SCHEMA
    man["candidates"][0]["state"] = "PROPOSED"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(man))
    assert R.main(["--verify", str(bad)]) == R.RC_REFUSED
>>>>>>> origin/jppa-search/ppa-search-layer
    assert "NON_TERMINAL_STATE" in capsys.readouterr().err


def test_a_truncated_ledger_is_rc1(ran, tmp_path, capsys):
    _, man, _ = ran
    man["candidates"] = man["candidates"][:1]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(man))
    assert R.main(["--verify", str(p)]) == R.RC_REFUSED
    assert "LEDGER_TRUNCATED" in capsys.readouterr().err


def test_eligibility_from_num_drc_alone_is_rc1(ran, tmp_path, capsys):
    """The ORFS `num_drc` cheat in its final form, refused at the CLI."""
    _, man, _ = ran
    man["candidates"][0]["feasibility"] = {
        "verdict": "ELIGIBLE", "reason": "num_drc was 0",
        "terms": {"drc": "PASS"}}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(man))
    assert R.main(["--verify", str(p)]) == R.RC_REFUSED
    assert "ELIGIBLE_ON_A_PARTIAL_VECTOR" in capsys.readouterr().err


def test_more_full_pnr_than_declared_is_rc1_at_build_time(space, tmp_path,
                                                          capsys):
    """The run that happened must be the run the budget describes."""
    t = tmp_path / "trials.json"
    t.write_text(json.dumps([_trial("binary"), _trial("gray")]))
    rc = R.main([str(space), "--trials", str(t), "--max-trials", "2",
                 "--max-full-pnr-trials", "1"])
    assert rc == R.RC_REFUSED
    assert R.MARK_REFUSE in capsys.readouterr().err


def test_a_budget_that_is_not_a_budget_is_rc1(space, capsys):
    rc = R.main([str(space), "--max-trials", "0"])
    assert rc == R.RC_REFUSED
    assert "not a budget" in capsys.readouterr().err


def test_a_trials_file_carrying_a_tuner_step_is_refused_at_the_boundary(
        space, tmp_path, capsys):
    """MUTATION TARGET. Assign `completed_stage` directly instead of calling
    `set_completed_stage` in `_apply_trial` and this reds — the integer would
    be written straight into a published manifest."""
    t = tmp_path / "trials.json"
    bad = _trial("binary")
    bad["completed_stage"] = 5
    t.write_text(json.dumps([bad]))
    rc = R.main([str(space), "--trials", str(t)])
    assert rc == R.RC_REFUSED
    assert "iteration counter" in capsys.readouterr().err


def test_a_malformed_trials_document_is_rc1_not_a_silent_zero(space, tmp_path,
                                                              capsys):
    t = tmp_path / "trials.json"
    t.write_text(json.dumps([{"no_knobs": True}]))
    assert R.main([str(space), "--trials", str(t)]) == R.RC_REFUSED
    assert "no `knobs`" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# determinism and reporting hygiene
# ---------------------------------------------------------------------------
def test_the_same_seed_reproduces_the_same_manifest(space, tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    R.main([str(space), "--max-trials", "4", "--seed", "5", "--json", str(a)])
    R.main([str(space), "--max-trials", "4", "--seed", "5", "--json", str(b)])
    assert a.read_text() == b.read_text()


def test_refusals_go_to_stderr_and_the_summary_to_stdout(space, tmp_path,
                                                         capsys):
    R.main([str(space), "--json", str(tmp_path / "m.json")])
    cap = capsys.readouterr()
    assert cap.out.strip() and not cap.err.strip()
    R.main([str(space), "--max-trials", "0"])
    cap = capsys.readouterr()
    assert cap.err.strip() and not cap.out.strip()


def test_the_json_report_is_written_even_when_the_verdict_is_a_refusal(
        space, tmp_path):
    out = tmp_path / "r.json"
    assert R.main([str(space), "--max-trials", "0", "--json", str(out)]) == \
        R.RC_REFUSED
    assert json.loads(out.read_text())["budget_problems"]
