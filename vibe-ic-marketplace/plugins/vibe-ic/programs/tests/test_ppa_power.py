#!/usr/bin/env python3
"""Tests for `_ppa/power.py` — the power split and, the part that decides
whether any of it means anything, the ACTIVITY BASIS.

THE PROPERTY THIS FILE EXISTS FOR, in one sentence: a vectorless estimate and a
VCD-driven measurement are both "total power", they are not the same number, and
a comparison across them is UNDETERMINED and not a winner.

The negative fixture the lane brief asks for by name is
`test_a_vectorless_candidate_does_not_beat_a_vcd_baseline`. It is the cheapest
possible way to fake a power improvement — run the candidate vectorless, run the
baseline against a VCD, report the difference — and it must be refused.

Fixtures are SYNTHETIC and carry no process, foundry or chip token. The two
transcript lines they reproduce (`READ_VCD_FAIL:` and `Annotated 0 pin
activities.`) are quoted from the published corpus, where 8 of the 17 power
reports carry one or the other under a `POWER_ANALYSIS_MODE: vector_vcd` label.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
from _ppa import power as pw          # noqa: E402
from _ppa import canonical_json as cj  # noqa: E402


# ── the artefact shapes, quoted from the corpus ───────────────────────────
_TABLE = """\
Group                  Internal  Switching    Leakage      Total
                          Power      Power      Power      Power (Watts)
----------------------------------------------------------------
Sequential             1.42e-03   4.19e-05   2.57e-08   1.46e-03  88.3%
Combinational          1.48e-04   4.43e-05   2.60e-08   1.92e-04  11.7%
Clock                  0.00e+00   0.00e+00   0.00e+00   0.00e+00   0.0%
----------------------------------------------------------------
Total                  1.56e-03   8.63e-05   5.17e-08   1.65e-03 100.0%
"""

_BANNER = "OpenSTA 2.7.0 f21d4a3878 Copyright (c) 2026, Parallax Software\n"


def _rpt(mode=None, *, annotated=None, fail=None, table=_TABLE):
    parts = [_BANNER]
    if fail:
        parts.append(fail + "\n")
    if annotated is not None:
        parts.append(f"Annotated {annotated} pin activities.\n")
    if mode is not None:
        parts.append(f"POWER_ANALYSIS_MODE: {mode}\n")
    parts.append(table)
    return "".join(parts)


# ── POSITIVE: the split is read, and read correctly ───────────────────────
def test_the_split_is_read_per_group_and_for_the_total():
    r = pw.parse_power_report(_rpt("vectorless_sdc"))
    assert [g["group"] for g in r["rows"]] == \
        ["Sequential", "Combinational", "Clock"]
    t = r["total_row"]
    assert (t["internal_w"], t["switching_w"], t["leakage_w"], t["total_w"]) \
        == (1.56e-03, 8.63e-05, 5.17e-08, 1.65e-03)
    # §3: the token the tool wrote is kept beside the float, so a consumer can
    # hash what was PARSED rather than what a float round-tripped to.
    assert t["total_raw"] == "1.65e-03"


def test_a_declared_vectorless_report_is_vectorless_and_measured():
    r = pw.parse_power_report(_rpt("vectorless_sdc"))
    assert r["activity"]["basis"] == pw.BASIS_VECTORLESS
    rec = pw.total_record(r, stage="post_route", scenario="functional")
    assert rec["status"] == pw.STATUS_MEASURED
    assert rec["scope"]["activity_basis"] == pw.BASIS_VECTORLESS
    assert rec["value"] == 1.65e-03 and rec["unit"] == "W"


def test_a_corroborated_vcd_report_is_vcd():
    """`Annotated N pin activities` with N > 0 is the only POSITIVE evidence in
    the artefact that a vector basis is real, so it is what corroborates one."""
    r = pw.parse_power_report(_rpt("vector_vcd", annotated=4211))
    assert r["activity"]["basis"] == pw.BASIS_VCD
    assert r["activity"]["corroboration"] == pw.CORROBORATED


def test_two_records_on_the_same_basis_do_compare():
    """The positive half of comparability. Without this, a check that refuses
    everything would look identical to one that discriminates."""
    a = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                        stage="post_route", scenario="functional")
    lower = _TABLE.replace("1.65e-03 100.0%", "1.20e-03 100.0%")
    b = pw.total_record(
        pw.parse_power_report(_rpt("vectorless_sdc", table=lower)),
        stage="post_route", scenario="functional")
    out = pw.compare_total_power(a, b)
    assert out["verdict"] == pw.V_B_LOWER, out
    assert out["activity_basis"] == pw.BASIS_VECTORLESS


# ── NEGATIVE: the comparisons that must be REFUSED ────────────────────────
def test_a_vectorless_candidate_does_not_beat_a_vcd_baseline():
    """THE FIXTURE THE LANE EXISTS FOR.

    The candidate's number is genuinely lower. It is still not a win, because
    the two numbers were produced by different activity models and are
    therefore different metrics (`PPA_INTERFACES.md` §2). A gate that answered
    "candidate wins" here would be certifying the cheapest available fake.
    """
    baseline = pw.total_record(
        pw.parse_power_report(_rpt("vector_vcd", annotated=4211)),
        stage="post_route", scenario="functional")
    lower = _TABLE.replace("1.65e-03 100.0%", "9.90e-04 100.0%")
    candidate = pw.total_record(
        pw.parse_power_report(_rpt("vectorless_sdc", table=lower)),
        stage="post_route", scenario="functional")

    assert candidate["value"] < baseline["value"]      # it really is lower
    out = pw.compare_total_power(baseline, candidate)
    assert out["verdict"] == pw.V_UNDETERMINED, out
    assert out["code"] == "NOT_COMPARABLE"
    assert "activity_basis" in out["reason"]
    assert pw.BASIS_VCD in out["reason"] and pw.BASIS_VECTORLESS in out["reason"]


def test_a_declared_vcd_basis_its_own_transcript_falsifies_is_contradicted():
    """8 of the 17 published reports are this. The label says the number came
    from observed activity; the same file carries the failure of the read that
    would have produced it."""
    r = pw.parse_power_report(_rpt(
        "vector_vcd",
        fail="READ_VCD_FAIL: Wrong number of arguments :sta::read_vcd_file"))
    assert r["activity"]["basis"] == pw.BASIS_CONTRADICTED
    rec = pw.total_record(r, stage="post_route", scenario="functional")
    # §2: "the artefact exists but cannot support the metric".
    assert rec["status"] == pw.STATUS_INVALID
    assert "READ_VCD_FAIL" in rec["reason"]


def test_zero_annotated_activities_contradicts_a_vector_label():
    """The other three. OpenSTA states its own count and it is zero."""
    r = pw.parse_power_report(_rpt("vector_vcd", annotated=0))
    assert r["activity"]["basis"] == pw.BASIS_CONTRADICTED
    assert "0 pin activities" in r["activity"]["reason"]


def test_the_mirror_case_is_also_a_contradiction():
    """A report claiming vectorless while the tool annotated activities is just
    as wrong about itself. Checking only one direction would make the rule
    depend on which way the label happened to lie."""
    r = pw.parse_power_report(_rpt("vectorless_sdc", annotated=4211))
    assert r["activity"]["basis"] == pw.BASIS_CONTRADICTED


def test_an_invalid_record_may_not_enter_a_comparison():
    bad = pw.total_record(
        pw.parse_power_report(_rpt("vector_vcd", fail="READ_VCD_FAIL: boom")),
        stage="post_route", scenario="functional")
    good = pw.total_record(pw.parse_power_report(_rpt("vector_vcd",
                                                      annotated=99)),
                           stage="post_route", scenario="functional")
    out = pw.compare_total_power(bad, good)
    assert out["verdict"] == pw.V_UNDETERMINED
    assert "INVALID" in out["reason"]


def test_two_unstated_bases_are_not_a_match():
    """The rule that is easiest to get wrong and costs the most.

    Two numbers whose activity models are both UNKNOWN are not known to share
    an activity model. Letting UNSTATED match UNSTATED would make "not measured"
    a value that participates in arithmetic — the numeric-sentinel defect §2
    forbids, one level up.
    """
    a = pw.total_record(pw.parse_power_report(_rpt(None)),
                        stage="post_route", scenario="functional")
    lower = _TABLE.replace("1.65e-03 100.0%", "1.20e-03 100.0%")
    b = pw.total_record(pw.parse_power_report(_rpt(None, table=lower)),
                        stage="post_route", scenario="functional")
    assert a["scope"]["activity_basis"] == pw.BASIS_UNSTATED
    out = pw.compare_total_power(a, b)
    assert out["verdict"] == pw.V_UNDETERMINED, out
    assert "unknown" in out["reason"]


def test_a_different_stage_is_a_different_metric():
    """Synthesis power and post-route power are not one comparison either. The
    basis is the axis this lane owns, but it is not the only scope key."""
    a = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                        stage="synth", scenario="functional")
    b = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                        stage="post_route", scenario="functional")
    out = pw.compare_total_power(a, b)
    assert out["verdict"] == pw.V_UNDETERMINED
    assert "scope.stage differs" in out["reason"]


def test_an_unknown_mode_token_is_unstated_and_not_guessed():
    r = pw.parse_power_report(_rpt("statistical_montecarlo"))
    assert r["activity"]["basis"] == pw.BASIS_UNSTATED
    assert "does not recognise" in r["activity"]["reason"]


# ── VACUOUS: no input must never look like a clean read ───────────────────
def test_an_empty_artefact_states_no_total_and_never_zero_power():
    """`0 W` is the sentinel §2 forbids. An artefact with no rows produces
    NOT_MEASURED records carrying a reason, and `total_record` returns None."""
    r = pw.parse_power_report("")
    assert r["rows"] == [] and r["total_row"] is None
    assert pw.total_record(r) is None
    recs = pw.metric_records(r)
    assert recs and all(x["status"] == pw.STATUS_NOT_MEASURED for x in recs)
    assert all("value" not in x for x in recs)          # no numeric sentinel
    assert all(x["reason"] for x in recs)


def test_a_file_that_cannot_be_read_is_not_a_file_that_was_empty(tmp_path):
    """`read_power_report` returns None for "I could not open it" and a parsed
    document for "I opened it and it held nothing". Collapsing the two is the
    defect that bit three separate systems in one day."""
    assert pw.read_power_report(tmp_path / "absent.rpt") is None
    empty = tmp_path / "empty.rpt"
    empty.write_text("")
    got = pw.read_power_report(empty)
    assert got is not None and got["total_row"] is None
    assert got["sha256"].startswith("sha256:")


def test_a_judgement_without_a_measurement_is_undetermined_not_a_pass():
    assert pw.judge_against_requirement(None, {"max_w": 1.0, "max_uw": 1e6})[
        "verdict"] == pw.J_UNDETERMINED
    rec = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                          stage="s", scenario="d")
    assert pw.judge_against_requirement(rec, None)["verdict"] == \
        pw.J_UNDETERMINED


# ── the REQUIREMENT side: a budget is a contract term ─────────────────────
def _proj(tmp_path, *, l19=None, contract=None):
    p = tmp_path / "run"
    (p / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    if l19 is not None:
        d = p / "phase1" / "generated_docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
            {"doc_id": "L19", "fields": {"power_budget_uw": l19}}))
    if contract is not None:
        (p / "ppa_contract.json").write_text(json.dumps(contract))
    return p


def test_the_contract_outranks_l19_and_the_superseded_value_is_disclosed(
        tmp_path):
    """A contract exists so that it can override the flow's default. Treating a
    disagreement with the lower document as fatal would make declaring one
    impossible; discarding it silently would hide which ruler was used."""
    proj = _proj(tmp_path, l19=1000.0, contract={
        "schema": pw.CONTRACT_SCHEMA,
        "requirements": [{"metric": "power.total_w", "unit": "W",
                          "limit": {"max": 2.0e-03},
                          "scope": {"activity_basis": "VECTORLESS"},
                          "authority": "SPEC-POWER-1"}]})
    res = pw.resolve_power_requirement(proj)
    assert res["refusal"] is None
    assert res["requirement"]["authority"] == pw.AUTHORITY_CONTRACT
    assert res["requirement"]["max_w"] == 2.0e-03
    assert [s["max_uw"] for s in res["superseded"]] == [1000.0]


def test_l19_is_the_fallback_when_no_contract_declares_one(tmp_path):
    res = pw.resolve_power_requirement(_proj(tmp_path, l19=1000.0))
    assert res["requirement"]["authority"] == pw.AUTHORITY_L19
    assert res["requirement"]["max_uw"] == 1000.0     # the value PARSED


def test_no_authority_at_all_refuses_and_names_what_it_lacks(tmp_path):
    res = pw.resolve_power_requirement(_proj(tmp_path, l19=None))
    assert res["requirement"] is None
    assert "power_budget_uw" in res["refusal"]


def test_a_json_document_without_the_schema_key_is_not_a_contract(tmp_path):
    """Guessing that some other JSON "looks like" a contract is how an
    authority nobody declared gets invented."""
    proj = _proj(tmp_path, l19=None, contract={
        "requirements": [{"metric": "power.total_w", "unit": "W",
                          "limit": {"max": 2.0e-03}}]})
    assert pw.resolve_power_requirement(proj)["requirement"] is None


def test_a_requirement_written_for_a_different_basis_cannot_judge(tmp_path):
    """The requirement side of the same rule. A limit declared against observed
    activity does not bound a vectorless estimate, however comfortably the
    number fits under it."""
    rec = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                          stage="post_route", scenario="functional")
    req = {"authority": "ppa_contract", "max_w": 1.0, "max_uw": 1.0e6,
           "scope": {"activity_basis": pw.BASIS_VCD}}
    out = pw.judge_against_requirement(rec, req)
    assert out["verdict"] == pw.J_UNDETERMINED
    assert out["code"] == "ACTIVITY_BASIS_MISMATCH"


def test_a_basis_free_requirement_still_bounds_but_says_it_is_blind(tmp_path):
    """L19 states no activity basis. That is not a reason to refuse — it is a
    reason to disclose that the threshold does not know what it is judging."""
    rec = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                          stage="post_route", scenario="functional")
    out = pw.judge_against_requirement(
        rec, {"authority": pw.AUTHORITY_L19, "max_w": 1.0, "max_uw": 1.0e6,
              "scope": {}})
    assert out["verdict"] == pw.J_PASS
    assert out["basis_policed"] is False


def test_a_contradicted_measurement_is_undetermined_even_under_a_budget():
    """The branch that matters most on real data: a run that DOES declare a
    budget, whose power number claims a VCD basis its transcript falsifies. The
    answer is UNDETERMINED — not a PASS, and not a FAIL either, because rc 1 is
    a claim about the design and this is a claim about the measurement."""
    rec = pw.total_record(
        pw.parse_power_report(_rpt("vector_vcd", fail="READ_VCD_FAIL: boom")),
        stage="post_route", scenario="functional")
    out = pw.judge_against_requirement(
        rec, {"authority": pw.AUTHORITY_L19, "max_w": 1.0, "max_uw": 1.0e6,
              "scope": {}})
    assert out["verdict"] == pw.J_UNDETERMINED
    assert out["code"] == "TOTAL_NOT_MEASURED"


# ── identity ───────────────────────────────────────────────────────────────
def test_records_hash_through_the_one_serializer():
    rec = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                          stage="post_route", scenario="functional")
    assert pw.digest(rec) == cj.digest_of(rec)
    assert pw.digest(rec).startswith("sha256:")


def test_the_basis_is_part_of_the_records_identity():
    """Two runs with identical watt figures and different activity models are
    different facts, so they must not share an identity."""
    a = pw.total_record(pw.parse_power_report(_rpt("vectorless_sdc")),
                        stage="post_route", scenario="functional")
    b = pw.total_record(pw.parse_power_report(_rpt("vector_vcd",
                                                   annotated=4211)),
                        stage="post_route", scenario="functional")
    assert a["value"] == b["value"]
    assert pw.digest(a) != pw.digest(b)


# ── the disclosure the mutation cannot move, stated as such ───────────────
def test_the_sum_disclosure_is_a_disclosure_and_not_a_verdict():
    """ART-POWER-FIGURES-X1000 multiplies every non-zero figure by 1000 and
    therefore preserves both sums exactly. This test records that the property
    is worth publishing and worthless as a gate."""
    mutated = _TABLE
    for frm, to in (("e-03", "e+00"), ("e-04", "e-01"), ("e-05", "e-02"),
                    ("e-08", "e-05")):
        mutated = mutated.replace(frm, to)
    clean = pw.parse_power_report(_rpt("vectorless_sdc"))
    dirty = pw.parse_power_report(_rpt("vectorless_sdc", table=mutated))
    assert clean["split_consistency"]["consistent"] is True
    assert dirty["split_consistency"]["consistent"] is True   # unmoved
    assert dirty["total_row"]["total_w"] == 1000 * clean["total_row"]["total_w"]


@pytest.mark.parametrize("basis", [pw.BASIS_UNSTATED, pw.BASIS_CONTRADICTED])
def test_an_unusable_basis_is_never_silently_treated_as_vectorless(basis):
    assert basis not in pw.KNOWN_BASES


# ── the document, and the schema it is written against ────────────────────
def _schema():
    return json.loads((_HERE.parent.parent / pw.SCHEMA_PATH).read_text())


def test_the_document_carries_what_its_schema_requires():
    doc = pw.power_document(pw.parse_power_report(_rpt("vectorless_sdc")),
                            stage="post_route", scenario="functional")
    sch = _schema()
    assert doc["schema"] == sch["properties"]["schema"]["const"]
    for key in sch["required"]:
        assert key in doc, key
    for key in sch["properties"]["activity"]["required"]:
        assert key in doc["activity"], key
    mreq = sch["properties"]["metrics"]["items"]["required"]
    for rec in doc["metrics"]:
        for key in mreq:
            assert key in rec, (key, rec["metric"])


def test_the_code_and_the_schema_share_one_basis_vocabulary():
    """The two would otherwise drift the first time a basis is added, and a
    document would then validate against a schema that does not know the value
    it carries."""
    sch = _schema()
    declared = set(sch["properties"]["activity"]["properties"]["basis"]["enum"])
    in_code = {pw.BASIS_VCD, pw.BASIS_SAIF, pw.BASIS_VECTORLESS,
               pw.BASIS_UNSTATED, pw.BASIS_CONTRADICTED}
    assert declared == in_code
    scoped = set(sch["properties"]["metrics"]["items"]["properties"]["scope"]
                 ["properties"]["activity_basis"]["enum"])
    assert scoped == in_code
    corr = set(sch["properties"]["activity"]["properties"]
               ["corroboration"]["enum"])
    assert corr == {pw.CORROBORATED, pw.UNCORROBORATED, pw.CONTRADICTED,
                    pw.NO_CORROBORATION_NEEDED}
    metrics = set(sch["properties"]["metrics"]["items"]["properties"]
                  ["metric"]["enum"])
    assert metrics == {f"power.{c}_w" for c in pw.CATEGORIES}


def test_a_not_measured_record_carries_no_value_key_the_schema_forbids():
    doc = pw.power_document(pw.parse_power_report(""))
    assert doc["metrics"]
    for rec in doc["metrics"]:
        assert rec["status"] == pw.STATUS_NOT_MEASURED
        assert "value" not in rec and rec["reason"]


def test_a_requested_mode_line_is_not_mistaken_for_the_resolved_one():
    """FORWARD COMPATIBILITY with the runner fix this lane requested.

    `phase3_one_shot_runner` decides `vector_vcd` from the EXISTENCE of a .vcd,
    before the read is attempted, and the requested fix is to print the request
    and the outcome as two lines. `POWER_ANALYSIS_MODE_REQUESTED:` must not be
    read as `POWER_ANALYSIS_MODE:` — a parser that matched the prefix would
    resolve the basis from the intention again, which is the whole defect.
    """
    text = (_BANNER + "POWER_ANALYSIS_MODE_REQUESTED: vector_vcd\n"
            + "READ_VCD_FAIL: boom\n"
            + "POWER_ANALYSIS_MODE: vectorless_sdc\n" + _TABLE)
    act = pw.parse_power_report(text)["activity"]
    assert act["declared_mode"] == "vectorless_sdc"
    assert act["basis"] == pw.BASIS_VECTORLESS
    # The failure is still disclosed, because it is still a fact about the run.
    assert act["read_failures"] == ["READ_VCD_FAIL: boom"]


def test_a_requirement_whose_metric_and_unit_disagree_is_unreadable(tmp_path):
    """`metric: power.total_w` with `unit: uW` is off by a million, and either
    reading is defensible. A parser that picked one would state a limit nobody
    wrote; this one says it cannot read the requirement and names why."""
    proj = _proj(tmp_path, l19=None, contract={
        "schema": pw.CONTRACT_SCHEMA,
        "requirements": [{"metric": "power.total_w", "unit": "uW",
                          "limit": {"max": 1000.0}}]})
    reqs = pw.contract_power_requirements(proj)
    assert len(reqs) == 1 and reqs[0]["max_w"] is None
    assert "imply different scales" in reqs[0]["unreadable"]
    res = pw.resolve_power_requirement(proj)
    assert res["requirement"] is None
    assert "unreadable" in res["refusal"]


def test_a_requirement_stated_in_uw_against_the_uw_metric_is_read(tmp_path):
    """The paired positive, so the rule above cannot pass by refusing every
    unit that is not Watts."""
    proj = _proj(tmp_path, l19=None, contract={
        "schema": pw.CONTRACT_SCHEMA,
        "requirements": [{"metric": "power.total_uw", "unit": "uW",
                          "limit": {"max": 1000.0}}]})
    req = pw.resolve_power_requirement(proj)["requirement"]
    assert req["max_uw"] == 1000.0 and req["max_w"] == 1000.0 * 1e-6


def test_a_requirements_identity_is_its_limit_AND_its_basis(tmp_path):
    """Two requirements at the SAME limit written against two activity bases
    are two requirements, not one stated twice. This gate applies one limit and
    refuses to choose between them rather than taking whichever the glob
    happened to yield first."""
    proj = _proj(tmp_path, l19=None, contract={
        "schema": pw.CONTRACT_SCHEMA,
        "requirements": [
            {"metric": "power.total_w", "unit": "W", "limit": {"max": 2.0e-03},
             "scope": {"activity_basis": pw.BASIS_VCD}},
            {"metric": "power.total_w", "unit": "W", "limit": {"max": 2.0e-03},
             "scope": {"activity_basis": pw.BASIS_VECTORLESS}}]})
    res = pw.resolve_power_requirement(proj)
    assert res["requirement"] is None
    assert "2 distinct" in res["refusal"]


def test_the_same_requirement_stated_twice_is_still_one_authority(tmp_path):
    """The paired positive: Phase 1 publishing one contract into two places
    must not be mistaken for two requirements."""
    req = {"metric": "power.total_w", "unit": "W", "limit": {"max": 2.0e-03},
           "scope": {"activity_basis": pw.BASIS_VECTORLESS}}
    proj = _proj(tmp_path, l19=None, contract={
        "schema": pw.CONTRACT_SCHEMA, "requirements": [req, dict(req)]})
    res = pw.resolve_power_requirement(proj)
    assert res["refusal"] is None
    assert res["requirement"]["max_w"] == 2.0e-03
