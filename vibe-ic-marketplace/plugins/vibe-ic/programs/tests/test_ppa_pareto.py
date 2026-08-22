#!/usr/bin/env python3
"""The frontier: positive, negative, vacuous — and no collapsed scalar anywhere.

The properties under test are the lane's definition of done:

    an infeasible candidate NEVER appears in frontier.json
    a NOT_MEASURED candidate is never judged "better"
    the relation is recomputable from the raw triple by a third party
    the public report contains NO collapsed scalar
"""
import json
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F  # noqa: E402
from _ppa import pareto as P  # noqa: E402
from test_ppa_feasibility import (VIEW, candidate, clean_metrics,  # noqa: E402
                                  metric, policy)

CHECK = _PROGRAMS / "ppa_pareto_check.py"

AREA_SCOPE = {"stage": "post_route_extracted"}
POWER_SCOPE = {"stage": "post_route_extracted", "activity_basis": "vcd"}

OBJECTIVES = (P.Objective("area", "area.total_um2", P.SENSE_MIN, AREA_SCOPE),
              P.Objective("power", "power.total_w", P.SENSE_MIN, POWER_SCOPE),
              P.Objective("timing", "timing.setup.wns_ns", P.SENSE_MAX,
                          dict(VIEW)))

CONTRACT = {
    "required_views": [VIEW],
    "objectives": [
        {"key": "area", "metric": "area.total_um2", "sense": "min",
         "scope": AREA_SCOPE},
        {"key": "power", "metric": "power.total_w", "sense": "min",
         "scope": POWER_SCOPE},
        {"key": "timing", "metric": "timing.setup.wns_ns", "sense": "max",
         "scope": dict(VIEW)},
    ],
}


def cand(cid, area, power, wns, lvs="CLEAN",
         area_scope=None, power_scope=None):
    ms = clean_metrics()
    ms[0]["value"] = wns
    ms[4]["value"] = lvs
    ms.append(metric("area.total_um2", area, "um2",
                     dict(area_scope or {**VIEW, **AREA_SCOPE})))
    ms.append(metric("power.total_w", power, "W",
                     dict(power_scope or {**VIEW, **POWER_SCOPE})))
    return candidate(cid, ms)


def build(cands, objectives=OBJECTIVES):
    results = F.adjudicate_set(cands, policy())
    return results, P.build_frontier(cands, results, objectives)


def run(tmp_path, cands, frontier=None, contract=None):
    cpath = tmp_path / "candidates.json"
    cpath.write_text(json.dumps({"candidates": cands}), encoding="utf-8")
    kpath = tmp_path / "contract.json"
    kpath.write_text(json.dumps(contract or CONTRACT), encoding="utf-8")
    argv = [sys.executable, str(CHECK), "--candidates", str(cpath),
            "--contract", str(kpath), "--json", str(tmp_path / "out.json")]
    if frontier is not None:
        fpath = tmp_path / "frontier.json"
        fpath.write_text(json.dumps(frontier), encoding="utf-8")
        argv += ["--frontier", str(fpath)]
    r = subprocess.run(argv, capture_output=True, text=True)
    out = tmp_path / "out.json"
    return r, (json.loads(out.read_text()) if out.exists() else None)


# --- POSITIVE ---------------------------------------------------------------
def test_positive_the_frontier_is_the_non_dominated_set():
    """A is best on area and power, B is best on timing: both are on it.

    C is worse than A on every objective, so it is dominated and named as such
    rather than quietly dropped -- a reader has to be able to see why.
    """
    cands = [cand("A", 100.0, 0.010, 0.05),
             cand("B", 140.0, 0.014, 0.30),
             cand("C", 150.0, 0.020, 0.01)]
    _, doc = build(cands)
    assert doc["frontier"] == ["A", "B"]
    assert [d["candidate_id"] for d in doc["dominated"]] == ["C"]
    # both frontier members dominate C, and the document names both --
    # "dominated" without "by what" is not a reviewable statement
    assert doc["dominated"][0]["dominated_by"] == ["A", "B"]


def test_positive_cli_exits_zero_and_the_document_is_self_consistent(tmp_path):
    cands = [cand("A", 100.0, 0.010, 0.05), cand("B", 140.0, 0.014, 0.30)]
    r, doc = run(tmp_path, cands)
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "VALID"
    assert doc["frontier"] == ["A", "B"]


def test_positive_the_relation_is_recomputable_from_what_is_published():
    """A third party redoes the domination relation from the raw triple only.

    This is the property, written as the check: nothing below reads the
    published `frontier` list. It reads the objective senses and the per
    candidate values and rebuilds the answer.
    """
    cands = [cand("A", 100.0, 0.010, 0.05), cand("B", 140.0, 0.014, 0.30),
             cand("C", 150.0, 0.020, 0.01)]
    _, doc = build(cands)

    rows = {r["candidate_id"]: r for r in doc["considered"]}
    senses = {o["key"]: o["sense"] for o in doc["objectives"]}
    live = [c for c in rows if rows[c]["comparable"]]

    def better(x, y, key):
        vx = rows[x]["values"][key]["value"]
        vy = rows[y]["values"][key]["value"]
        return vx < vy if senses[key] == "min" else vx > vy

    def dom(x, y):
        return (not any(better(y, x, k) for k in senses)
                and any(better(x, y, k) for k in senses))

    independent = sorted(c for c in live
                         if not any(dom(o, c) for o in live if o != c))
    assert independent == doc["frontier"]


def test_positive_every_frontier_value_carries_its_scope_and_its_source():
    """A number without its scope and its artefact is not recomputable."""
    _, doc = build([cand("A", 100.0, 0.010, 0.05)])
    row = doc["considered"][0]
    for key in ("area", "power", "timing"):
        v = row["values"][key]
        assert v["status"] == "MEASURED"
        assert v["scope"] and v["unit"] is not None
        assert v["source"]["sha256"].startswith("sha256:")


# --- NEGATIVE ---------------------------------------------------------------
def test_negative_an_infeasible_candidate_never_enters_the_frontier():
    """The best candidate on every axis, and it is not on the frontier."""
    cands = [cand("A", 100.0, 0.010, 0.05),
             cand("BEST", 50.0, 0.005, 0.40, lvs="MISMATCH")]
    results, doc = build(cands)
    assert {r.candidate_id: r.verdict for r in results}["BEST"] == F.INFEASIBLE
    assert doc["frontier"] == ["A"]
    assert "BEST" not in json.dumps(doc["frontier"])
    assert doc["excluded_infeasible"] == [
        {"candidate_id": "BEST", "feasibility": "INFEASIBLE",
         "code": "PARETO_INFEASIBLE_EXCLUDED"}]


def test_negative_a_published_frontier_holding_an_infeasible_member_is_refused(tmp_path):
    cands = [cand("A", 100.0, 0.010, 0.05),
             cand("BEST", 50.0, 0.005, 0.40, lvs="MISMATCH")]
    r, doc = run(tmp_path, cands, frontier={"schema": P.PARETO_SCHEMA,
                                            "frontier": ["A", "BEST"]})
    assert r.returncode == F.RC_FAIL, r.stdout + r.stderr
    assert "[REFUSE]" in r.stderr
    codes = {f["code"] for f in doc["findings"]}
    assert "PARETO_INFEASIBLE_IN_FRONTIER" in codes
    assert "PARETO_FRONTIER_DISAGREES" in codes


def test_negative_a_not_measured_candidate_is_never_judged_better():
    """It is not unbeatable for being unreadable.

    The tempting implementation says `nobody could show it was worse, so it
    stays on the frontier`. That is exactly how an unmeasured candidate gets
    published as a winner.
    """
    blind = cand("BLIND", 10.0, 0.001, 0.90)
    for m in blind["metrics"]:
        if m["metric"] == "power.total_w":
            m["status"] = "NOT_MEASURED"
            m.pop("value")
            m["reason"] = "power analysis did not run"
    cands = [cand("A", 100.0, 0.010, 0.05), blind]
    _, doc = build(cands)
    assert doc["frontier"] == ["A"]
    assert [u["candidate_id"] for u in doc["undetermined"]] == ["BLIND"]
    assert "PARETO_NOT_MEASURED" in doc["undetermined"][0]["codes"]


def test_negative_publishing_an_unmeasured_candidate_as_a_winner_is_refused(tmp_path):
    blind = cand("BLIND", 10.0, 0.001, 0.90)
    for m in blind["metrics"]:
        if m["metric"] == "power.total_w":
            m["status"] = "NOT_MEASURED"
            m.pop("value")
    r, doc = run(tmp_path, [cand("A", 100.0, 0.010, 0.05), blind],
                 frontier={"frontier": ["BLIND"]})
    assert r.returncode != F.RC_PASS
    assert "PARETO_UNDETERMINED_JUDGED_BETTER" in {f["code"] for f in doc["findings"]}


def test_negative_a_collapsed_scalar_in_a_public_document_is_refused(tmp_path):
    """One weighted number is a proxy for the property, and it gets quoted."""
    cands = [cand("A", 100.0, 0.010, 0.05), cand("B", 140.0, 0.014, 0.30)]
    _, honest = build(cands)
    dishonest = dict(honest)
    dishonest["ppa_score"] = {"A": 0.81, "B": 0.79}
    r, doc = run(tmp_path, cands, frontier=dishonest)
    assert r.returncode == F.RC_FAIL, r.stdout + r.stderr
    assert "PARETO_COLLAPSED_SCALAR" in {f["code"] for f in doc["findings"]}


def test_the_collapsed_scalar_detector_matches_keys_exactly_not_by_substring():
    """`scope` is not `cost`, and `scorecard` is not `score`.

    A substring rule teaches authors to rename the field rather than to stop
    collapsing, which is worse than no rule.
    """
    assert P.assert_no_collapsed_scalar(
        {"scope": {"stage": "x"}, "scorecard_note": "", "unweighted": 1}) == []
    assert P.assert_no_collapsed_scalar({"a": [{"Weighted-Score": 1}]}) == \
        ["a[0].Weighted-Score"]
    for key in ("score", "fom", "figure_of_merit", "cost", "rank", "penalty"):
        assert P.assert_no_collapsed_scalar({key: 1}) == [key]


def test_the_emitted_frontier_carries_no_collapsed_scalar_of_its_own():
    """The producer is held to the rule it enforces."""
    _, doc = build([cand("A", 100.0, 0.010, 0.05),
                    cand("B", 140.0, 0.014, 0.30)])
    assert P.assert_no_collapsed_scalar(doc) == []


# --- VACUOUS ----------------------------------------------------------------
def test_vacuous_absent_candidates_file_is_rc2_with_a_marker(tmp_path):
    out = tmp_path / "out.json"
    r = subprocess.run([sys.executable, str(CHECK), "--candidates",
                        str(tmp_path / "nope.json"), "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == F.RC_UNDETERMINED, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stderr
    assert json.loads(out.read_text())["exit_code"] == 2


def test_vacuous_no_declared_objective_is_rc2_not_an_empty_frontier(tmp_path):
    """Nothing to trade off is not `everything is on the frontier`."""
    r, doc = run(tmp_path, [cand("A", 100.0, 0.010, 0.05)],
                 contract={"required_views": [VIEW]})
    assert r.returncode == F.RC_UNDETERMINED
    assert doc["findings"][0]["code"] == "PARETO_NO_OBJECTIVES"


def test_vacuous_an_undeclared_objective_scope_is_rc2(tmp_path):
    """Without a reference scope the answer would depend on input order."""
    contract = json.loads(json.dumps(CONTRACT))
    for o in contract["objectives"]:
        o.pop("scope")
    r, doc = run(tmp_path, [cand("A", 100.0, 0.010, 0.05),
                            cand("B", 140.0, 0.014, 0.30)],
                 contract=contract)
    assert r.returncode == F.RC_UNDETERMINED
    assert doc["frontier"] == []
    assert "PARETO_SCOPE_NOT_DECLARED" in doc["undetermined"][0]["codes"]


def test_vacuous_empty_candidate_list_is_rc2(tmp_path):
    r, _ = run(tmp_path, [])
    assert r.returncode == F.RC_UNDETERMINED


def test_vacuous_unreadable_frontier_is_rc2_not_a_disagreement(tmp_path):
    cpath = tmp_path / "c.json"
    cpath.write_text(json.dumps({"candidates": [cand("A", 1.0, 0.1, 0.1)]}))
    kpath = tmp_path / "k.json"
    kpath.write_text(json.dumps(CONTRACT))
    fpath = tmp_path / "f.json"
    fpath.write_text("{broken")
    r = subprocess.run([sys.executable, str(CHECK), "--candidates", str(cpath),
                        "--contract", str(kpath), "--frontier", str(fpath)],
                       capture_output=True, text=True)
    assert r.returncode == F.RC_UNDETERMINED
    assert "[CANNOT CHECK]" in r.stderr


def test_bad_invocation_is_rc3():
    assert __import__("ppa_pareto_check").main([]) == F.RC_BAD_INVOCATION


# --- an empty frontier is never a pass --------------------------------------
def test_an_all_infeasible_set_gives_an_empty_frontier_and_rc1_not_rc0(tmp_path):
    """Every invariant holds and there is still no winner.

    This is the empty-tree lie at frontier level and the first implementation
    of `frontier_exit_code` shipped it: the document was internally consistent,
    so it returned 0 while naming no promotable design at all. A promoter
    reading only the exit code would have proceeded with nothing.
    """
    cands = [cand("A", 100.0, 0.010, 0.05, lvs="MISMATCH"),
             cand("B", 140.0, 0.014, 0.30, lvs="MISMATCH")]
    r, doc = run(tmp_path, cands)
    assert r.returncode == F.RC_FAIL, r.stdout + r.stderr
    assert doc["frontier"] == []
    assert "PARETO_EMPTY_FRONTIER" in {f["code"] for f in doc["findings"]}
    assert "[REFUSE]" in r.stderr


def test_an_all_unadjudicated_set_gives_rc2_not_rc1(tmp_path):
    """Nobody looked is not the same finding as everybody failed."""
    cands = [cand("A", 100.0, 0.010, 0.05), cand("B", 140.0, 0.014, 0.30)]
    for c in cands:
        for m in c["metrics"]:
            if m["metric"] == "physical.drc.violations":
                m["status"] = "NOT_MEASURED"
                m.pop("value")
    r, doc = run(tmp_path, cands)
    assert r.returncode == F.RC_UNDETERMINED, r.stdout + r.stderr
    assert doc["frontier"] == []
    assert {e["code"] for e in doc["excluded_infeasible"]} == \
        {"PARETO_FEASIBILITY_UNDETERMINED"}
    assert "[CANNOT CHECK]" in r.stderr


def test_the_empty_frontier_finding_is_printed_not_only_returned(tmp_path):
    """An exit code nobody can explain is an exit code somebody overrides."""
    cands = [cand("A", 100.0, 0.010, 0.05, lvs="MISMATCH")]
    r, _ = run(tmp_path, cands)
    assert "PARETO_EMPTY_FRONTIER" in r.stdout


def test_emptiness_has_exactly_one_route_to_a_non_zero_exit_code():
    """Pins the consolidation the mutation probe forced.

    The rule was implemented twice -- a branch in `frontier_exit_code` and a
    finding appended by the CLI -- and reverting either left the rc unchanged,
    so neither could be shown to be doing the work. Now the finding is derived
    from the same predicate as the code: a `PARETO_EMPTY_FRONTIER` entry in
    `findings` does NOT by itself make the run fail, and a genuinely empty
    frontier does even when `findings` is empty.
    """
    full = {"considered": [{"candidate_id": "A"}], "frontier": ["A"]}
    empty = {"considered": [{"candidate_id": "A"}], "frontier": []}
    assert P.frontier_exit_code(full, [{"code": P.P_EMPTY_FRONTIER}]) == F.RC_PASS
    assert P.frontier_exit_code(empty, []) == F.RC_FAIL
    assert P.empty_frontier_finding(full) is None
    assert P.empty_frontier_finding(empty)["code"] == P.P_EMPTY_FRONTIER
