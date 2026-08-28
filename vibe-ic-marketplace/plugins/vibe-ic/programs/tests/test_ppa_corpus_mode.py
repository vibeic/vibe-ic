#!/usr/bin/env python3
"""The corpus mode of the five PPA record gates, and the three ways it can lie.

WHAT THIS FILE IS DEFENDING
===========================
`ppa_head_to_head_check` took `--corpus` and resolved it through
`_corpus_location`; its five siblings took an EXACT document path, so a record
filed under any other name was simply not judged. Closing that asymmetry is
easy to do badly, and there are exactly three ways:

    an EMPTY corpus becomes rc 0        the gate now certifies a scan that
                                        never happened -- a vacuous 100%
                                        coverage, a frontier nobody
                                        recomputed, "every candidate feasible"
                                        over an empty list. Every one of those
                                        is the sentence its gate exists to
                                        refuse.
    an exact path AND a corpus          the caller named a document and got a
      are both accepted silently        verdict about a different population.
    two records for one identity        the walk takes `records[0]` and buries
      become a pick                     the disagreement, which is exactly what
                                        `_ppa.contract` refuses to do with two
                                        sources that disagree about a key.

So every gate below gets a POSITIVE corpus (one good record -> rc 0), a
NEGATIVE corpus (one bad record -> rc 1), a VACUOUS corpus (nothing -> rc 2
with the corpus root NAMED), a CONFLICT corpus, and a both-given refusal.

WHY THE RECORD IS FOUND BY CONTENT AND NOT BY NAME
==================================================
Several positives below deliberately file their record under a name no glob
would guess (`whatever-name.json`, `nested/deep/x.json`). The complaint that
produced the corpus mode is that a record under an unexpected name went
unjudged; a filename glob answers that complaint with a smaller version of
itself, so the selection is on the document's declared schema or shape.

chip-AGNOSTIC: synthetic bytes and declared policy only.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(TESTS))

from _ppa import metrics as M  # noqa: E402
from test_ppa_contract_fixtures import (  # noqa: E402
    base_declaration, build_contract,
)
from test_ppa_feasibility import (  # noqa: E402
    VIEW, candidate, clean_metrics, metric,
)
from test_ppa_pareto import CONTRACT as PARETO_CONTRACT, cand  # noqa: E402

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

CONTRACT_GATE = PROGRAMS / "ppa_contract_check.py"
MEASUREMENT_GATE = PROGRAMS / "ppa_measurement_check.py"
FEASIBILITY_GATE = PROGRAMS / "ppa_feasibility_check.py"
PARETO_GATE = PROGRAMS / "ppa_pareto_check.py"
INTEGRITY_GATE = PROGRAMS / "ppa_problem_integrity_check.py"

def gate(program, *args, env=None):
    """Drive the REAL entry point. Deliberately not `main(argv)` in-process:
    the flow acts on the EXIT CODE, and a test that calls a function leaves the
    verdict-to-exit-code mapping unmeasured."""
    return _pr.run([sys.executable, str(program), *args],
                          capture_output=True, text=True,
                          env=env)


def put(path: pathlib.Path, obj) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def corpus(tmp_path, name) -> pathlib.Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Fixture documents
# ---------------------------------------------------------------------------
SCOPE = {"stage": "post_route_extracted", "process": "ss"}
SRC = {"path": "sta.rpt", "tool": "opensta"}
EXPECT_TWO = [
    {"metric": "area.die_um2", "scope": SCOPE},
    {"metric": "timing.setup.wns_ns", "scope": SCOPE},
]


def complete_bundle():
    idx = M.MetricIndex()
    idx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE, SRC))
    idx.add(M.measured("timing.setup.wns_ns", -0.124, "ns", SCOPE, SRC))
    return M.bundle(idx, expected=EXPECT_TWO)


def bundle_missing_a_row():
    """One expected row has NO RECORD AT ALL -- the invisible hole, rc 1."""
    idx = M.MetricIndex()
    idx.add(M.measured("area.die_um2", 12000.0, "um^2", SCOPE, SRC))
    return M.bundle(idx, expected=EXPECT_TWO)


def candidate_set(*cands, **extra):
    doc = {"candidates": list(cands), "required_views": [dict(VIEW)]}
    doc.update(extra)
    return doc


def infeasible_candidate(cid="bad"):
    ms = clean_metrics()
    ms[4]["value"] = "MISMATCH"          # LVS dirty -- one measured violation
    return candidate(cid, ms)


@pytest.fixture(scope="module")
def contract_doc(tmp_path_factory):
    """One clean contract, built once by the real builder."""
    root = tmp_path_factory.mktemp("contract_build")
    built = build_contract(root, base_declaration())
    assert built.returncode == 0, built.stderr
    return json.loads((root / "contract.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def second_contract_doc(tmp_path_factory):
    """A second CLEAN contract over the SAME run tree, differing only in a
    metric value. Its `identities` are therefore byte-identical to the first
    one's while the document is not -- which is the corpus conflict, isolated
    from any per-record finding."""
    root = tmp_path_factory.mktemp("contract_build_2")
    decl = base_declaration()
    decl["metrics"][0]["value"] = -0.250
    built = build_contract(root, decl)
    assert built.returncode == 0, built.stderr
    return json.loads((root / "contract.json").read_text(encoding="utf-8"))


# ===========================================================================
# 1. ppa_contract_check
# ===========================================================================
def test_contract_corpus_positive_finds_a_record_under_any_name(tmp_path,
                                                                contract_doc):
    """The whole point: the record is judged because of what it IS."""
    c = corpus(tmp_path, "good")
    put(c / "nested" / "deep" / "whatever-name.json", contract_doc)
    r = gate(CONTRACT_GATE, "--corpus", str(c))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 published contract record(s) selected" in r.stdout


def test_contract_corpus_negative_refuses_a_record(tmp_path, contract_doc):
    c = corpus(tmp_path, "bad")
    broken = copy.deepcopy(contract_doc)
    broken["contract_digest"] = "sha256:" + "0" * 64
    put(c / "x.json", broken)
    r = gate(CONTRACT_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PPA-C-001" in (r.stdout + r.stderr)


def test_contract_corpus_vacuous_is_rc2_and_names_the_root(tmp_path):
    """AN EMPTY CORPUS IS NOT A PASS, and the refusal states WHERE it looked.
    A refusal that does not name its root leaves a reader unable to tell a
    scan of the wrong tree from a scan of an empty one."""
    c = corpus(tmp_path, "empty")
    r = gate(CONTRACT_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr
    assert str(c) in r.stderr


def test_contract_corpus_conflict_is_refused_not_picked(tmp_path, contract_doc,
                                                        second_contract_doc):
    """Two contracts, one identity, different content. Both are individually
    CLEAN, so an rc 1 here can only have come from the conflict."""
    a = corpus(tmp_path, "solo_a")
    put(a / "a.json", contract_doc)
    b = corpus(tmp_path, "solo_b")
    put(b / "b.json", second_contract_doc)
    assert gate(CONTRACT_GATE, "--corpus", str(a)).returncode == 0
    assert gate(CONTRACT_GATE, "--corpus", str(b)).returncode == 0

    both = corpus(tmp_path, "conflict")
    put(both / "a.json", contract_doc)
    put(both / "b.json", second_contract_doc)
    r = gate(CONTRACT_GATE, "--corpus", str(both))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "claimed by 2 documents that DISAGREE" in r.stderr
    assert "a.json" in r.stderr and "b.json" in r.stderr


def test_contract_corpus_identical_copies_are_disclosed_not_deduplicated(
        tmp_path, contract_doc):
    """Two byte-identical files are a copy, not a disagreement: NOTE, rc 0 --
    but never silently folded away."""
    c = corpus(tmp_path, "copies")
    put(c / "a.json", contract_doc)
    put(c / "b.json", contract_doc)
    r = gate(CONTRACT_GATE, "--corpus", str(c))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "byte-identical" in r.stderr


def test_contract_exact_path_and_corpus_together_is_bad_invocation(
        tmp_path, contract_doc):
    c = corpus(tmp_path, "both")
    one = put(tmp_path / "one.json", contract_doc)
    put(c / "a.json", contract_doc)
    r = gate(CONTRACT_GATE, "--contract", str(one), "--corpus", str(c))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "bad invocation" in r.stderr


def test_contract_neither_path_nor_corpus_is_not_a_pass(tmp_path):
    r = gate(CONTRACT_GATE)
    assert r.returncode != 0, r.stdout + r.stderr


# ===========================================================================
# 2. ppa_measurement_check
# ===========================================================================
def test_measurement_corpus_positive(tmp_path):
    c = corpus(tmp_path, "good")
    put(c / "deep" / "unexpected-name.json", complete_bundle())
    r = gate(MEASUREMENT_GATE, "--corpus", str(c))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 published metric bundle(s) selected" in r.stdout


def test_measurement_corpus_negative_an_omitted_row_is_still_rc1(tmp_path):
    c = corpus(tmp_path, "bad")
    put(c / "x.json", bundle_missing_a_row())
    r = gate(MEASUREMENT_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NO RECORD AT ALL" in r.stderr


def test_measurement_corpus_vacuous_is_rc2_and_names_the_root(tmp_path):
    """The vacuous 100% this gate refuses to compute, one level up."""
    c = corpus(tmp_path, "empty")
    r = gate(MEASUREMENT_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr


def test_measurement_corpus_conflict_across_two_bundles(tmp_path):
    """`MetricIndex.add` already refuses two records for one (metric, scope)
    INSIDE a bundle. Across bundles nothing did, and taking the first would
    pick a winner on directory order."""
    good = complete_bundle()
    other = copy.deepcopy(good)
    other["records"][0]["value"] = 999999.0     # same metric, same scope
    c = corpus(tmp_path, "conflict")
    put(c / "a.json", good)
    put(c / "b.json", other)
    r = gate(MEASUREMENT_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "DISAGREE" in r.stderr
    assert "area.die_um2" in r.stderr


def test_measurement_exact_and_corpus_together_is_bad_invocation(tmp_path):
    c = corpus(tmp_path, "both")
    one = put(tmp_path / "b.json", complete_bundle())
    put(c / "a.json", complete_bundle())
    r = gate(MEASUREMENT_GATE, "--coverage", str(one), "--corpus", str(c))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "bad invocation" in r.stderr


# ===========================================================================
# 3. ppa_feasibility_check
# ===========================================================================
def test_feasibility_corpus_positive(tmp_path):
    c = corpus(tmp_path, "good")
    put(c / "runs" / "not-named-candidates.json",
        candidate_set(candidate("ok")))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 published candidate set(s) selected" in r.stdout


def test_feasibility_corpus_negative(tmp_path):
    c = corpus(tmp_path, "bad")
    put(c / "x.json", candidate_set(infeasible_candidate()))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr


def test_feasibility_corpus_vacuous_is_rc2_and_names_the_root(tmp_path):
    """"Every candidate is feasible" over an empty corpus is the empty-tree
    lie this gate already refuses for an empty candidate list."""
    c = corpus(tmp_path, "empty")
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr


def test_feasibility_corpus_conflicting_candidate_id_is_refused(tmp_path):
    c = corpus(tmp_path, "conflict")
    put(c / "a.json", candidate_set(candidate("shared")))
    put(c / "b.json", candidate_set(infeasible_candidate("shared")))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "candidate_id" in r.stderr and "DISAGREE" in r.stderr


def test_feasibility_does_not_read_its_own_verdict_document_as_an_input(
        tmp_path):
    """`vibeic.ppa.feasibility.v1` carries a `candidates` key too. Selecting on
    shape alone would adjudicate the gate's own output as if it were a run."""
    c = corpus(tmp_path, "report_only")
    report = gate(FEASIBILITY_GATE, "--candidates",
                  str(put(tmp_path / "in.json",
                          candidate_set(candidate("ok")))),
                  "--json", str(tmp_path / "out.json"))
    assert report.returncode == 0, report.stderr
    put(c / "verdict.json",
        json.loads((tmp_path / "out.json").read_text(encoding="utf-8")))
    r = gate(FEASIBILITY_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr


def test_feasibility_exact_and_corpus_together_is_bad_invocation(tmp_path):
    c = corpus(tmp_path, "both")
    one = put(tmp_path / "one.json", candidate_set(candidate("ok")))
    put(c / "a.json", candidate_set(candidate("ok")))
    r = gate(FEASIBILITY_GATE, "--candidates", str(one), "--corpus", str(c))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "bad invocation" in r.stderr


# ===========================================================================
# 4. ppa_pareto_check
# ===========================================================================
def pareto_set(*cands):
    doc = candidate_set(*cands)
    doc["objectives"] = copy.deepcopy(PARETO_CONTRACT["objectives"])
    return doc


def test_pareto_corpus_positive(tmp_path):
    c = corpus(tmp_path, "good")
    put(c / "sweep" / "run-17.json",
        pareto_set(cand("A", 100.0, 0.010, 0.05),
                   cand("B", 140.0, 0.014, 0.30)))
    r = gate(PARETO_GATE, "--corpus", str(c))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 published candidate set(s) selected" in r.stdout


def test_pareto_corpus_negative(tmp_path):
    """An INFEASIBLE candidate is the only admitted one: nothing may be
    promoted, and the recomputed frontier is empty."""
    c = corpus(tmp_path, "bad")
    put(c / "x.json", pareto_set(cand("A", 100.0, 0.010, 0.05, lvs="MISMATCH")))
    r = gate(PARETO_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PARETO_EMPTY_FRONTIER" in (r.stdout + r.stderr)


def test_pareto_corpus_vacuous_is_rc2_and_names_the_root(tmp_path):
    """A frontier nobody recomputed is this gate's whole subject; reporting
    VALID over zero candidate sets would publish exactly that."""
    c = corpus(tmp_path, "empty")
    r = gate(PARETO_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr


def test_pareto_corpus_conflicting_candidate_id_is_refused(tmp_path):
    c = corpus(tmp_path, "conflict")
    put(c / "a.json", pareto_set(cand("A", 100.0, 0.010, 0.05)))
    put(c / "b.json", pareto_set(cand("A", 55.0, 0.001, 0.90)))
    r = gate(PARETO_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "candidate_id" in r.stderr and "DISAGREE" in r.stderr


def test_pareto_frontier_and_corpus_together_is_bad_invocation(tmp_path):
    c = corpus(tmp_path, "both")
    put(c / "a.json", pareto_set(cand("A", 100.0, 0.010, 0.05)))
    f = put(tmp_path / "frontier.json", {"frontier": ["A"]})
    r = gate(PARETO_GATE, "--frontier", str(f), "--corpus", str(c))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "bad invocation" in r.stderr


# ===========================================================================
# 5. ppa_problem_integrity_check
# ===========================================================================
def test_integrity_corpus_positive_compares_the_pair_it_grouped(
        tmp_path, contract_doc, second_contract_doc):
    """Two arms of one problem. They share every identity here, so the pair is
    COMPARABLE-but-not-a-result: PPA-C-013, UNDETERMINED. What is asserted is
    that the pair was FORMED and compared, which the exact mode could only do
    if somebody named both paths."""
    c = corpus(tmp_path, "pair")
    put(c / "arm-a.json", contract_doc)
    put(c / "arm-b.json", second_contract_doc)
    r = gate(INTEGRITY_GATE, "--corpus", str(c))
    assert "1 pair(s) compared" in r.stdout
    assert "PPA-C-013" in (r.stdout + r.stderr)


def test_integrity_corpus_negative_a_moved_problem_is_refused(
        tmp_path, tmp_path_factory, contract_doc):
    """The second arm was built from a DIFFERENT clock: `problem` moved."""
    root = tmp_path_factory.mktemp("moved")
    decl = base_declaration()
    decl["problem"]["facts"][0]["value"] = 8.0
    decl["problem"]["facts"][1]["value"] = 8.0
    built = build_contract(root, decl)
    assert built.returncode == 0, built.stderr
    moved = json.loads((root / "contract.json").read_text(encoding="utf-8"))

    c = corpus(tmp_path, "moved")
    put(c / "arm-a.json", contract_doc)
    put(c / "arm-b.json", moved)
    r = gate(INTEGRITY_GATE, "--corpus", str(c))
    # Two DIFFERENT problems -> two groups of one. Neither is a comparison that
    # passed, and saying so is the finding.
    assert r.returncode == 2, r.stdout + r.stderr
    assert "has ONE arm" in r.stderr


def test_integrity_corpus_vacuous_is_rc2_and_names_the_root(tmp_path):
    c = corpus(tmp_path, "empty")
    r = gate(INTEGRITY_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr


def test_integrity_a_lone_arm_is_undetermined_not_a_pass(tmp_path,
                                                         contract_doc):
    """One arm cannot be shown to be solving the same problem as anything."""
    c = corpus(tmp_path, "solo")
    put(c / "only.json", contract_doc)
    r = gate(INTEGRITY_GATE, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "has ONE arm" in r.stderr
    assert "only.json" in r.stderr


def test_integrity_conflicting_identity_is_refused(tmp_path, contract_doc,
                                                   second_contract_doc):
    c = corpus(tmp_path, "conflict")
    put(c / "a.json", contract_doc)
    put(c / "b.json", second_contract_doc)
    r = gate(INTEGRITY_GATE, "--corpus", str(c))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "claimed by 2 documents that DISAGREE" in r.stderr


def _flags_named(stderr: str) -> list:
    """The flags the refusal says were GIVEN — from the claim, not from beside it.

    MEASURED 2026-08-22, and the reason this helper exists rather than a bare
    `assert "--baseline" in stderr`: the refusal also prints GUIDANCE listing
    every legal mode, and that guidance contains the literal `--baseline`. A
    substring check over the whole message therefore passes even when the
    "were given together" clause has stopped naming the flag — the mutation
    that drops `--baseline` from the clause was run and the substring form did
    NOT catch it. This reads only the text BEFORE `were given together`, which
    is the clause that makes the claim.
    """
    head = stderr.split("were given together", 1)[0]
    return [f for f in ("--baseline", "--candidate", "--corpus") if f in head]


def test_integrity_two_population_sources_together_is_bad_invocation(
        tmp_path, contract_doc):
    """WHAT SURVIVED THE 2026-08-22 RULING, and what did not.

    This test used to pin `--baseline X --corpus Y` as a bad invocation. That
    rule is GONE and it was replaced rather than dropped: `--corpus Y` alone
    and `--baseline X --corpus Y` are two DIFFERENT questions -- every pair
    within a problem identity, versus every contract against one named
    baseline -- and the flag combination is how a caller says which one is
    being asked. `test_integrity_baseline_against_corpus_*` below drive that.

    What is still a refusal is naming TWO POPULATION SOURCES, and the reason is
    unchanged: `--candidate` names ONE document and `--corpus` names a
    population, so accepting both means the caller asked about one subject and
    was answered about another. That holds whether or not a baseline came with
    them, so BOTH shapes are driven here, and the message must NAME every flag
    it was given -- a refusal that lists two of the three flags the caller
    typed is a refusal the caller cannot act on.
    """
    c = corpus(tmp_path, "both")
    one = put(tmp_path / "one.json", contract_doc)
    put(c / "a.json", contract_doc)

    # --candidate with --corpus: two population sources, no baseline.
    r = gate(INTEGRITY_GATE, "--candidate", str(one), "--corpus", str(c))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "bad invocation" in r.stderr
    assert _flags_named(r.stderr) == ["--candidate", "--corpus"], r.stderr

    # All three: the pair question and the corpus question at once.
    r = gate(INTEGRITY_GATE, "--baseline", str(one), "--candidate", str(one),
             "--corpus", str(c))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "bad invocation" in r.stderr
    assert _flags_named(r.stderr) == ["--baseline", "--candidate",
                                      "--corpus"], r.stderr


def test_integrity_baseline_against_corpus_is_a_question_not_a_mistake(
        tmp_path, contract_doc, second_contract_doc):
    """`--baseline X --corpus Y`: the baseline against every OTHER contract.

    The baseline is NEVER paired with itself -- a contract compared against
    itself matches on every identity by construction, so counting it would let
    a corpus of one document look checked."""
    c = corpus(tmp_path, "against")
    base = put(c / "base.json", contract_doc)
    put(c / "arm-b.json", second_contract_doc)
    r = gate(INTEGRITY_GATE, "--baseline", str(base), "--corpus", str(c))
    assert r.returncode != 3, r.stdout + r.stderr
    assert "1 to pair against the baseline" in (r.stdout + r.stderr), r.stdout
    assert "1 pair(s)" in (r.stdout + r.stderr), r.stdout


def test_integrity_baseline_against_a_corpus_holding_only_itself_is_rc2(
        tmp_path, contract_doc):
    """VACUOUS SURVIVES THE SECOND MODE. A baseline WAS read, so the temptation
    is to call this a clean run; it is not one. No comparison was made."""
    c = corpus(tmp_path, "solo-against")
    base = put(c / "base.json", contract_doc)
    r = gate(INTEGRITY_GATE, "--baseline", str(base), "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr


def test_integrity_baseline_against_an_empty_corpus_is_rc2_not_rc0(
        tmp_path, contract_doc):
    c = corpus(tmp_path, "empty-against")
    base = put(tmp_path / "outside.json", contract_doc)
    r = gate(INTEGRITY_GATE, "--baseline", str(base), "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr and str(c) in r.stderr


def test_integrity_baseline_mode_one_bad_pair_does_not_decide_the_row(tmp_path,
                                                                     contract_doc):
    """A malformed pair is rc 2 and NAMED — it does not take the whole row.

    THE SIBLING LOOP ALREADY HAD THIS and this one did not. `check_corpus`'s
    all-pairs loop guards `compare_contracts` per pair; the baseline mode was
    added later with the identical call and no guard, so an exception reached
    `__main__` and the row became rc 3 "Nothing was compared" — which is false
    when 20 or 60 other pairs were about to be, and which lets ONE badly shaped
    document decide a verdict about an entire campaign.

    rc 2 AND NOT 3, for the reason the all-pairs arm gives: the INVOCATION was
    correct. A corpus where one document is the wrong shape is not a bad
    command line.
    """
    c = corpus(tmp_path, "badpair")
    base = put(c / "contract.json", contract_doc)
    # A well-formed `problem` so the pair FORMS, and an `analysis` written as a
    # bare digest string instead of a record so `identity.compare` raises.
    broken = json.loads(json.dumps(contract_doc))
    broken["run_label"] = "t1"
    ids = broken.setdefault("identities", {})
    ids["analysis"] = "a" * 8
    put(c / "t1" / "contract.json", broken)

    r = gate(INTEGRITY_GATE, "--baseline", str(base), "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "CANNOT CHECK" in r.stderr
    # the pair is NAMED on both sides, and so is what is missing
    assert "t1" in r.stderr and "contract.json" in r.stderr
    assert "NOT a finding about either run" in r.stderr
    assert "WHAT IS MISSING" in r.stderr
    # and it is reported as a pair, not as a dead run
    assert "1 undetermined" in (r.stdout + r.stderr), r.stdout + r.stderr


def test_integrity_baseline_against_corpus_keeps_the_unreadable_verdict(
        tmp_path, contract_doc, second_contract_doc):
    """UNREADABLE IS NOT ABSENT, in the baseline mode too. A file nobody could
    parse was not established to hold no record, and the roll-up must say so
    rather than silently shrink the denominator."""
    c = corpus(tmp_path, "unread-against")
    base = put(c / "base.json", contract_doc)
    put(c / "arm-b.json", second_contract_doc)
    # NAMED a contract on purpose: `population` keeps an unreadable file only
    # when its NAME claims it is one of these records. A file called
    # `broken.json` was never named a contract and was never a subject.
    (c / "broken_contract.json").write_text('{"schema": "vibeic',
                                            encoding="utf-8")
    r = gate(INTEGRITY_GATE, "--baseline", str(base), "--corpus", str(c))
    assert "1 unreadable" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "broken_contract.json" in r.stderr


# ===========================================================================
# 6. The shared seam itself
# ===========================================================================
@pytest.mark.parametrize("program", [
    CONTRACT_GATE, MEASUREMENT_GATE, FEASIBILITY_GATE, PARETO_GATE,
    INTEGRITY_GATE,
])
def test_an_absent_corpus_is_not_an_empty_one(tmp_path, program):
    """`Path.glob` yields nothing for a missing directory, so without the
    resolution branch a corpus that is NOT THERE and a corpus that is EMPTY
    print the same zero. Both are rc 2; only one of them may say it looked."""
    missing = tmp_path / "no_such_corpus"
    present = corpus(tmp_path, "empty")
    a = gate(program, "--corpus", str(missing))
    b = gate(program, "--corpus", str(present))
    assert a.returncode == 2 and b.returncode == 2
    assert "no corpus at" in a.stderr
    assert "no corpus at" not in b.stderr


@pytest.mark.parametrize("program", [
    CONTRACT_GATE, MEASUREMENT_GATE, FEASIBILITY_GATE, PARETO_GATE,
    INTEGRITY_GATE,
])
def test_the_absent_corpus_opt_in_states_the_zero_it_did_not_take(tmp_path,
                                                                  program):
    """rc 0, and it must never read as a scan that happened."""
    import os
    env = dict(os.environ)
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    r = gate(program, "--corpus", str(tmp_path / "gone"),
             "--corpus-may-be-absent", env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NO_CORPUS" in r.stderr
    assert "NOTHING WAS SCANNED" in r.stderr


@pytest.mark.parametrize("program", [
    CONTRACT_GATE, MEASUREMENT_GATE, FEASIBILITY_GATE, PARETO_GATE,
    INTEGRITY_GATE,
])
def test_a_pointer_that_is_set_and_wrong_is_never_excused(tmp_path, program):
    """The one row `--corpus-may-be-absent` may not launder: somebody said
    where the corpus is and was wrong."""
    import os
    env = dict(os.environ)
    env["VIBE_IC_BENCHMARK_DATA"] = str(tmp_path / "typo")
    r = gate(program, "--corpus", str(tmp_path / "gone"),
             "--corpus-may-be-absent", env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "UNDETERMINED" in r.stderr


@pytest.mark.parametrize("program", [
    CONTRACT_GATE, MEASUREMENT_GATE, FEASIBILITY_GATE, PARETO_GATE,
    INTEGRITY_GATE,
])
def test_a_file_nobody_could_parse_is_not_a_file_that_held_no_record(
        tmp_path, program):
    """A `*.json` that does not parse has NOT been established to hold no
    record -- nobody looked. It is named and it forces UNDETERMINED."""
    c = corpus(tmp_path, "broken")
    (c / "truncated.json").write_text("{not json", encoding="utf-8")
    r = gate(program, "--corpus", str(c))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "truncated.json" in r.stderr
    assert "was NOT established to hold no record" in r.stderr


@pytest.mark.parametrize("program", [
    CONTRACT_GATE, MEASUREMENT_GATE, FEASIBILITY_GATE, PARETO_GATE,
    INTEGRITY_GATE,
])
def test_every_corpus_run_discloses_its_denominator(tmp_path, program):
    """A zero over a population nobody can size is not a stated zero."""
    c = corpus(tmp_path, "empty")
    r = gate(program, "--corpus", str(c))
    assert "JSON file(s) opened under" in (r.stdout + r.stderr)
