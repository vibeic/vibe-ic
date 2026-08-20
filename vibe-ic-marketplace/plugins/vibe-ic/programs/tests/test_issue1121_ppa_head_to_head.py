#!/usr/bin/env python3
"""A PPA head-to-head record must not be able to carry a claim it cannot support.
vibe-ic#1121.

Every refusal below is tested DIFFERENTIALLY: the same record, with and without
the one offending field. That is what distinguishes "this record is refused
because of X" from "this record is refused", which is all a single-arm assertion
can ever say — and a checker that refuses everything is a ban, not a check.

`test_a_clean_record_passes` is the paired half that keeps every refusal test
from passing vacuously: if the checker refused everything, each refusal test
would still be green and the whole file would mean nothing.
"""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "_pphth", PROGRAMS / "ppa_head_to_head_check.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

from _ppa import benchmark as B          # noqa: E402  the fairness conditions
from _ppa import canonical_json as cj    # noqa: E402  the only serializer


#: The shape v2 asks for: one contract proven by hash, identical scope on every
#: axis, both arms feasible over the same question, and an opponent that was
#: allowed to tune. Numbers are arbitrary and carry no design meaning -- the
#: checker never interprets them beyond the three better-is directions.
#:
#: `design` is declared PER ARM and not once at the top level, deliberately: a
#: shared block would ASSERT that both arms ran the same problem, whereas two
#: independent declarations let the checker COMPARE them and refuse when they
#: differ. The identity has to be evidence, not a heading. The same argument is
#: why `contract` is per arm.
_DESIGN = {
    "spec_sha256": "a" * 64,
    "pdk": "PDK_UNDER_TEST",
    "clock_target_ns": 10.0,
    "corners": ["c_slow", "c_typ"],
}

#: The contract carries MORE than `design` does, on purpose: the two extra keys
#: are the ones a v1 record could differ on while passing C1, which is the whole
#: reason the hash exists beside the four declared fields.
_CONTRACT_BODY = {
    "spec_sha256": "a" * 64,
    "pdk": "PDK_UNDER_TEST",
    "clock_target_ns": 10.0,
    "corners": ["c_slow", "c_typ"],
    "floorplan": {"utilisation_target": 0.55},
    "permitted_cells": "the PDK's own default set, unmodified",
}
_CONTRACT_SHA = cj.digest_of(_CONTRACT_BODY)

_PHYS = "post_route_extracted"
_AREA_SCOPE = {"stage": _PHYS}
_TIMING_SCOPE = {"stage": _PHYS, "mode": "functional", "process": "PROC_SLOW",
                 "voltage_v": 1.62, "temperature_c": 125.0,
                 "rc_corner": "max", "check": "setup", "clock": "clk"}
_POWER_SCOPE = {"stage": _PHYS, "mode": "functional", "process": "PROC_SLOW",
                "voltage_v": 1.62, "temperature_c": 125.0,
                "activity_basis": "vectorless"}


def _metric(value, unit, scope):
    return {"status": "MEASURED", "value": value, "unit": unit,
            "scope": copy.deepcopy(scope)}


def _ppa(area, wns, power):
    return {"area_um2": _metric(area, "um^2", _AREA_SCOPE),
            "timing_wns_ns": _metric(wns, "ns", _TIMING_SCOPE),
            "power_mw": _metric(power, "mW", _POWER_SCOPE)}


#: Every floor check, clean, in both arms. The SET matters as much as the
#: values: an arm asked fewer questions looks exactly as good as one asked more.
def _feasible():
    return {"checks": {name: {"violations": 0, "source": f"<{name} report>"}
                       for name in B.FEASIBILITY_FLOOR}}


#: The SUBJECT may search a space it wrote -- it is our flow. The BASELINE may
#: not, and it gets a budget no smaller than ours. Equal budgets here so that a
#: test which shrinks one is measuring only that.
def _subject_tuning():
    return {"supported": True, "performed": True,
            "budget": {"trials": 200, "cpu_hours": 96.0},
            "search_space": {"source": "authored_for_this_comparison",
                             "ref": "this project's own search space",
                             "authored_by_this_project": True}}


def _baseline_tuning():
    return {"supported": True, "performed": True,
            "budget": {"trials": 200, "cpu_hours": 96.0},
            "search_space": {"source": "official",
                             "ref": "the opponent's own published search space",
                             "authored_by_this_project": False}}


CLEAN = {
    "schema": "vibeic.ppa.comparison.v2",
    "arms": [
        {
            "flow": "subject-flow", "role": "subject", "version": "x",
            "design": dict(_DESIGN),
            "contract": {"sha256": _CONTRACT_SHA,
                         "body": copy.deepcopy(_CONTRACT_BODY)},
            "measurement_basis": "signed_off_gds",
            "config_source": "this repo",
            "tuned_by_this_project": True,
            "ppa": _ppa(1000.0, -0.10, 5.00),
            "feasibility": _feasible(),
            "tuning": _subject_tuning(),
        },
        {
            "flow": "baseline-flow", "role": "baseline", "version": "y",
            "design": dict(_DESIGN),
            "contract": {"sha256": _CONTRACT_SHA,
                         "body": copy.deepcopy(_CONTRACT_BODY)},
            "measurement_basis": "signed_off_gds",
            "config_source": "upstream default config, unmodified",
            "tuned_by_this_project": False,
            "ppa": _ppa(1200.0, -0.30, 6.00),
            "feasibility": _feasible(),
            "tuning": _baseline_tuning(),
        },
    ],
}


def _rec(tmp_path, doc, name="rec.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _run(tmp_path, doc):
    return C.evaluate(_rec(tmp_path, doc))


def _mut(**design_or_arm):
    return copy.deepcopy(CLEAN)


# ---------------------------------------------------------------------------
# The paired half. Without this, every refusal test below is satisfied by a
# checker that refuses unconditionally.
# ---------------------------------------------------------------------------
def test_a_clean_record_passes(tmp_path):
    rc, rep = _run(tmp_path, CLEAN)
    assert rc == C.RC_OK, rep
    assert rep["ok"] is True


# ---------------------------------------------------------------------------
# C1 — #1121 constraint 4: the same problem, or it is not a comparison
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("pdk", "A_DIFFERENT_PDK"),
    ("clock_target_ns", 5.0),
    ("spec_sha256", "b" * 64),
    ("corners", ["c_typ"]),
])
def test_a_diverging_problem_field_is_refused(tmp_path, field, value):
    doc = copy.deepcopy(CLEAN)
    doc["arms"][1]["design"] = dict(doc["arms"][1]["design"])
    doc["arms"][1]["design"][field] = value
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert rep["refusal"]["code"] == "DIFFERENT_PROBLEM"
    assert field in rep["refusal"]["message"]


def test_corner_ORDER_is_not_part_of_the_problem_identity(tmp_path):
    """A set, not a list. Refusing on order would be a false positive, and a
    check that fires on legitimate records is worse than no check."""
    doc = copy.deepcopy(CLEAN)
    doc["arms"][1]["design"] = dict(doc["arms"][1]["design"])
    doc["arms"][1]["design"]["corners"] = ["c_typ", "c_slow"]
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_OK, rep


# ---------------------------------------------------------------------------
# C2 — #1121 constraint 3: the triple, never a proxy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("axis", sorted(C.AXES))
def test_an_unmeasured_axis_is_UNDETERMINED_not_a_win(tmp_path, axis):
    doc = copy.deepcopy(CLEAN)
    del doc["arms"][0]["ppa"][axis]
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_UNDETERMINED, rep
    assert rep["refusal"]["code"] == "AXIS_UNMEASURED"
    # and the wording must not let a reader take it for a pass
    text = C.format_report(rc, rep)
    assert "not a win" in text


@pytest.mark.parametrize("bad", C.COLLAPSED_SCALAR_FIELDS)
def test_a_collapsed_scalar_is_refused_for_existing(tmp_path, bad):
    doc = copy.deepcopy(CLEAN)
    doc["arms"][0]["ppa"][bad] = 42
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert rep["refusal"]["code"] == "COLLAPSED_SCALAR"


def test_the_report_emits_no_overall_figure(tmp_path):
    """#1121: 'Report the triple with the constraints that produced it, or do
    not report it.' There must be nothing to quote instead of the triple."""
    rc, rep = _run(tmp_path, CLEAN)
    assert rc == C.RC_OK
    blob = json.dumps(rep).lower()
    for word in ("figure_of_merit", "ppa_score", "composite"):
        assert word not in blob
    assert "overall" not in blob
    per = rep["derived_verdict"]["per_baseline"]["baseline-flow"]
    assert set(per) == set(C.AXES) | {"pareto"}, (
        "the verdict is a triple plus a RELATION, and never a word to quote")
    # `pareto` is the one non-axis key, and it must be a relation from a closed
    # set -- never a number. A numeric Pareto rank would be the collapsed
    # figure this record refuses to CARRY, re-entering through the verdict.
    assert per["pareto"] in {"SUBJECT_DOMINATES", "BASELINE_DOMINATES",
                             "EQUAL", "INCOMPARABLE"}
    assert not isinstance(per["pareto"], (int, float))


# ---------------------------------------------------------------------------
# C3 — #1121 constraint 2: a baseline we tuned is an oracle we wrote
# ---------------------------------------------------------------------------
def test_a_baseline_this_project_tuned_is_refused(tmp_path):
    doc = copy.deepcopy(CLEAN)
    doc["arms"][1]["tuned_by_this_project"] = True
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert rep["refusal"]["code"] == "BASELINE_TUNED_BY_US"


def test_a_tuned_baseline_is_refused_even_when_we_would_have_won(tmp_path):
    """The refusal is about provenance, not about the outcome. If it fired only
    when the numbers were awkward it would be an excuse, not a rule."""
    doc = copy.deepcopy(CLEAN)
    doc["arms"][1]["tuned_by_this_project"] = True
    doc["arms"][1]["ppa"]["area_um2"]["value"] = 99999.0   # baseline made to look awful
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED
    assert rep["refusal"]["code"] == "BASELINE_TUNED_BY_US"


def test_a_baseline_with_no_config_source_is_refused(tmp_path):
    doc = copy.deepcopy(CLEAN)
    del doc["arms"][1]["config_source"]
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert rep["refusal"]["code"] == "BASELINE_CONFIG_UNSOURCED"


def test_the_subject_may_be_tuned_by_us(tmp_path):
    """Only the BASELINE has to be untouched. Refusing a tuned subject would
    refuse the entire point of the exercise."""
    assert CLEAN["arms"][0]["tuned_by_this_project"] is True
    rc, _ = _run(tmp_path, CLEAN)
    assert rc == C.RC_OK


# ---------------------------------------------------------------------------
# C4 — #1121 constraint 1: simulated is not silicon
# ---------------------------------------------------------------------------
def test_a_silicon_claim_without_evidence_is_refused(tmp_path):
    doc = copy.deepcopy(CLEAN)
    doc["arms"][0]["measurement_basis"] = "silicon"
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert rep["refusal"]["code"] == "SILICON_UNEVIDENCED"


def test_a_simulated_pass_says_in_words_that_it_is_not_silicon(tmp_path):
    rc, rep = _run(tmp_path, CLEAN)
    assert rc == C.RC_OK
    text = C.format_report(rc, rep)
    assert "NOT SILICON" in text
    assert "not a wafer" in text


# ---------------------------------------------------------------------------
# C5 — the verdict is derived, and LOSS is derived by the same code as WIN
# ---------------------------------------------------------------------------
def test_a_loss_is_derived_and_does_not_fail_the_gate(tmp_path):
    """#1121: 'say plainly which is better and by how much — including if
    theirs is better.' A gate that only passes when we win would make the
    honest outcome unpublishable."""
    doc = copy.deepcopy(CLEAN)
    doc["arms"][0]["ppa"]["area_um2"]["value"] = 2000.0        # ours worse
    doc["arms"][0]["ppa"]["power_mw"]["value"] = 9.0           # ours worse
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    per = rep["derived_verdict"]["per_baseline"]["baseline-flow"]
    assert per["area_um2"]["verdict"] == "BASELINE_BETTER"
    assert per["power_mw"]["verdict"] == "BASELINE_BETTER"
    assert per["timing_wns_ns"]["verdict"] == "SUBJECT_BETTER"


def test_an_asserted_verdict_that_contradicts_the_numbers_is_refused(tmp_path):
    doc = copy.deepcopy(CLEAN)
    doc["arms"][0]["ppa"]["area_um2"]["value"] = 2000.0        # ours worse on area
    doc["verdict"] = {"baseline-flow": {"area_um2": "SUBJECT_BETTER"}}
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED, rep
    assert rep["refusal"]["code"] == "VERDICT_CONTRADICTED"


def test_an_asserted_verdict_that_agrees_is_accepted(tmp_path):
    """The differential half of the test above: same record, verdict corrected.
    Without this, the refusal could be 'any asserted verdict is refused'."""
    doc = copy.deepcopy(CLEAN)
    doc["arms"][0]["ppa"]["area_um2"]["value"] = 2000.0
    doc["verdict"] = {"baseline-flow": {"area_um2": "BASELINE_BETTER"}}
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_OK, rep


def test_direction_of_better_is_not_uniform(tmp_path):
    """Timing is the axis where HIGHER is better. A checker that treated all
    three the same would pass every test above and still be wrong."""
    doc = copy.deepcopy(CLEAN)
    doc["arms"][0]["ppa"]["timing_wns_ns"]["value"] = -0.90    # ours worse
    doc["arms"][1]["ppa"]["timing_wns_ns"]["value"] = -0.05
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    per = rep["derived_verdict"]["per_baseline"]["baseline-flow"]
    assert per["timing_wns_ns"]["verdict"] == "BASELINE_BETTER"


# ---------------------------------------------------------------------------
# Shape refusals
# ---------------------------------------------------------------------------
def test_one_arm_is_not_a_head_to_head(tmp_path):
    doc = copy.deepcopy(CLEAN)
    doc["arms"] = doc["arms"][:1]
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_REFUSED
    assert rep["refusal"]["code"] == "TOO_FEW_ARMS"


def test_a_missing_record_is_UNDETERMINED_not_a_pass(tmp_path):
    rc, rep = C.evaluate(tmp_path / "does_not_exist.json")
    assert rc == C.RC_UNDETERMINED
    assert rep["refusal"]["code"] == "NO_RECORD"


def test_two_baselines_are_allowed(tmp_path):
    """#1121 names three possible opponents (human, LibreLane, OpenECOS). A
    schema that allowed only one would force three records for one problem."""
    doc = copy.deepcopy(CLEAN)
    second = copy.deepcopy(doc["arms"][1])
    second["flow"] = "other-baseline"
    second["ppa"]["area_um2"]["value"] = 900.0                 # this one beats us
    doc["arms"].append(second)
    rc, rep = _run(tmp_path, doc)
    assert rc == C.RC_OK, rep
    per = rep["derived_verdict"]["per_baseline"]
    assert set(per) == {"baseline-flow", "other-baseline"}
    assert per["other-baseline"]["area_um2"]["verdict"] == "BASELINE_BETTER"
    assert per["baseline-flow"]["area_um2"]["verdict"] == "SUBJECT_BETTER"


def test_cli_returns_the_same_code_as_evaluate(tmp_path, capsys):
    p = _rec(tmp_path, CLEAN)
    assert C.main([str(p)]) == C.RC_OK
    out = capsys.readouterr().out
    assert "[PASS] ppa_head_to_head_check" in out
    doc = copy.deepcopy(CLEAN)
    doc["arms"][1]["tuned_by_this_project"] = True
    p2 = _rec(tmp_path, doc, "bad.json")
    assert C.main([str(p2)]) == C.RC_REFUSED
    assert "[FAIL] ppa_head_to_head_check" in capsys.readouterr().out


def test_the_checker_is_chip_and_pdk_agnostic():
    """No design, PDK, vendor or process literal may steer the logic. The PDK
    string is compared to the other arm's and never interpreted."""
    src = (PROGRAMS / "ppa_head_to_head_check.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]          # strip the module docstring
    for literal in ("sky130", "gf180", "asap7", "nangate", "ihp", "tsmc",
                    "samsung", "globalfoundries", "intel"):
        assert literal not in body.lower(), (
            f"{literal!r} appears in the logic; this gate must not know any "
            "PDK, vendor or process name")


# ---------------------------------------------------------------------------
# CORPUS MODE. Two defects lived here, and both made the gate non-discriminating
# in the direction that matters — a refusal reaching the flow as a pass.
# ---------------------------------------------------------------------------
def _corpus(tmp_path, name, *docs):
    """A corpus directory holding `docs` under the checker's own record glob."""
    d = tmp_path / name
    d.mkdir()
    for i, doc in enumerate(docs):
        (d / f"run{i}_head_to_head.json").write_text(
            json.dumps(doc), encoding="utf-8")
    return d


def _undetermined_doc():
    """A record the checker can read and cannot decide: one axis unmeasured."""
    doc = copy.deepcopy(CLEAN)
    doc["arms"][0]["ppa"].pop("power_mw")
    return doc


def _refused_doc():
    """A record the checker REFUSES: C3, a baseline this project tuned."""
    doc = copy.deepcopy(CLEAN)
    doc["arms"][1]["tuned_by_this_project"] = True
    return doc


def test_an_absent_corpus_does_not_report_an_empty_one(tmp_path, capsys,
                                                       monkeypatch):
    """Hard rule: "I could not read it" and "I read it and it was empty" must
    not come out as the same answer.

    `Path.glob` yields nothing for a directory that does not exist, so before
    this the two printed the SAME denominator (0) and the same rc — a zero
    asserted over a population nobody searched. Not hypothetical: the checker's
    only caller pointed at `<repo>/benchmark-data`, which moved to its own
    repository in v1.10.56, so the gate certified a clean empty population over
    an absent path on every run.
    """
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)

    missing = tmp_path / "no_such_corpus"
    assert not missing.exists()
    C.check_corpus(missing)
    absent = capsys.readouterr()

    empty = tmp_path / "empty_corpus"
    empty.mkdir()
    C.check_corpus(empty)
    present = capsys.readouterr()

    # THE DENOMINATOR IS THE TELL. A corpus that was opened may state its zero;
    # one that was never found may not, because it never took the measurement.
    assert "0 head-to-head record(s) found" in present.out
    assert "0 head-to-head record(s) found" not in absent.out
    assert "no corpus at" in absent.err
    assert "no corpus at" not in present.err


def test_the_absent_corpus_opt_in_states_the_zero_it_did_not_take(
        tmp_path, capsys, monkeypatch):
    """vibe-ic#1710's NO_CORPUS: rc 0, and it must never read as a scan."""
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    rc = C.check_corpus(tmp_path / "gone", may_be_absent=True)
    err = capsys.readouterr().err
    assert rc == 0
    assert "NO_CORPUS" in err and "NOTHING WAS SCANNED" in err
    assert "published head-to-head record(s)" in err


def test_a_pointer_that_is_set_and_wrong_is_never_excused(tmp_path, capsys,
                                                          monkeypatch):
    """SET AND WRONG IS NOT ABSENT — a mistyped path, a failed clone or a no-op
    CI fetch must not become a green gate over nothing, opt-in or not."""
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(tmp_path / "never_cloned"))
    rc = C.check_corpus(tmp_path / "gone", may_be_absent=True)
    assert rc == C.RC_UNDETERMINED
    assert "is set and" in capsys.readouterr().err


def test_the_pointer_actually_aims_the_gate(tmp_path, monkeypatch):
    """The gate's own promise: "the day a record lands the gate starts deciding
    with no further change". Before the corpus was resolved through the shared
    seam it could not — the pointer was never consulted and the named path had
    left the repository, so a RIGGED record in the published corpus was never
    opened at all.
    """
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    clone = tmp_path / "external_clone"
    clone.mkdir()
    (clone / "run_head_to_head.json").write_text(
        json.dumps(_refused_doc()), encoding="utf-8")
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(clone))
    assert C.check_corpus(tmp_path / "gone") == C.RC_REFUSED

    (clone / "run_head_to_head.json").write_text(
        json.dumps(CLEAN), encoding="utf-8")
    assert C.check_corpus(tmp_path / "gone") == C.RC_OK


def test_adding_an_undetermined_record_cannot_subtract_a_refusal(tmp_path):
    """The masking defect, stated as the property it violates.

    `flow_compliance_check` maps rc 2 -> VACUOUS_PASS (the step passes) and
    rc 1 -> FAIL, so rc 2 is the larger integer and the WEAKER verdict.
    Aggregating the corpus with `max()` therefore promoted a refusal to a pass:
    a corpus holding one refused record returned rc 1, and dropping one further
    record with an unmeasured axis beside it returned rc 2. Adding a record must
    never be able to subtract a refusal.
    """
    only_refused = _corpus(tmp_path, "a", _refused_doc())
    assert C.check_corpus(only_refused) == C.RC_REFUSED

    masked = _corpus(tmp_path, "b", _refused_doc(), _undetermined_doc())
    assert C.check_corpus(masked) == C.RC_REFUSED, (
        "an undetermined record beside a refused one softened the refusal into "
        "a vacuous pass — a defeat-the-gate primitive in the aggregator of the "
        "one gate whose subject is claims that cannot be checked afterwards")


def test_corpus_severity_order_is_refused_then_undetermined_then_ok(tmp_path):
    """All three orderings, so the fix is not just 'always red'."""
    assert C.check_corpus(_corpus(tmp_path, "ok", CLEAN)) == C.RC_OK
    assert C.check_corpus(
        _corpus(tmp_path, "u", CLEAN, _undetermined_doc())) == C.RC_UNDETERMINED
    assert C.check_corpus(
        _corpus(tmp_path, "r", CLEAN, _undetermined_doc(),
                _refused_doc())) == C.RC_REFUSED
    # order of discovery must not decide the verdict
    assert C.check_corpus(
        _corpus(tmp_path, "r2", _refused_doc(), _undetermined_doc(),
                CLEAN)) == C.RC_REFUSED


def test_worst_rc_is_severity_ordered_not_integer_ordered():
    """The unit behind the corpus verdict, stated without files.

    `max()` returns 2 here, and 2 is the verdict that PASSES. That single
    substitution is the whole defect.
    """
    assert C.worst_rc([C.RC_REFUSED, C.RC_UNDETERMINED]) == C.RC_REFUSED
    assert max([C.RC_REFUSED, C.RC_UNDETERMINED]) == C.RC_UNDETERMINED
    assert C.worst_rc([C.RC_OK, C.RC_UNDETERMINED]) == C.RC_UNDETERMINED
    assert C.worst_rc([C.RC_OK, C.RC_OK]) == C.RC_OK
    assert C.worst_rc([]) == C.RC_OK
    # An unknown code is not a pass: it is treated as the most severe thing.
    assert C.worst_rc([7]) == C.RC_REFUSED


def test_a_corpus_holding_only_good_records_still_passes(tmp_path):
    """The paired half: the corpus fix must leave a clean corpus green, or the
    four tests above are satisfied by a gate that refuses unconditionally."""
    assert C.check_corpus(_corpus(tmp_path, "clean", CLEAN, CLEAN)) == C.RC_OK
