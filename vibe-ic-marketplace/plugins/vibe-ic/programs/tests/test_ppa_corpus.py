#!/usr/bin/env python3
"""`_ppa_corpus` — the seam the five PPA record gates share, on its own.

`test_ppa_corpus_mode.py` drives the five CLIs end to end, which is where the
EXIT CODE is measured. This file tests the seam's own three decisions directly,
because each of them is a place where a corpus walk stops being a check:

    the aggregation order      REFUSED outranks UNDETERMINED outranks OK. rc 2
                               is the LARGER integer and the WEAKER verdict, so
                               `max()` here promotes a refusal to a pass and
                               ADDING a record subtracts a finding.
    conflict vs copy           one identity claimed by two documents that
                               DISAGREE is a refusal; claimed by two that are
                               byte-identical is a copy. Collapsing either into
                               the other loses a real fact.
    read vs classified         a file nobody could parse has not been shown to
                               hold no record.

chip-AGNOSTIC: paths, JSON and digests.
"""
from __future__ import annotations

import json
import pathlib
import sys

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _ppa_corpus as corpus_seam  # noqa: E402


# --------------------------------------------------------------- aggregation
def test_worst_rc_is_severity_order_and_not_integer_order():
    """The measured defect this order exists to prevent: a corpus holding one
    REFUSED record returned 1, and dropping one further UNDETERMINED record
    beside it returned 2 — so the refusal reached the flow as a vacuous pass."""
    assert corpus_seam.worst_rc([]) == corpus_seam.RC_OK
    assert corpus_seam.worst_rc([0, 0]) == corpus_seam.RC_OK
    assert corpus_seam.worst_rc([0, 2]) == corpus_seam.RC_UNDETERMINED
    assert corpus_seam.worst_rc([1, 2]) == corpus_seam.RC_REFUSED
    assert corpus_seam.worst_rc([2, 1, 0]) == corpus_seam.RC_REFUSED
    assert max([1, 2]) == 2      # what the wrong aggregator would have said


def test_an_unknown_rc_is_treated_as_the_most_severe():
    """A code this module does not know is not thereby harmless."""
    assert corpus_seam.worst_rc([0, 99]) == corpus_seam.RC_REFUSED


# ----------------------------------------------------------------- selection
def _write(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_collect_selects_on_content_and_never_on_the_filename(tmp_path):
    """The complaint that produced this seam is that a record filed under an
    unexpected name went unjudged. A filename glob answers it with a smaller
    version of itself."""
    _write(tmp_path, "nothing/like/a/record/name.json", {"kind": "wanted"})
    _write(tmp_path, "obviously_a_record.json", {"kind": "other"})
    scan = corpus_seam.collect(tmp_path, lambda d: d.get("kind") == "wanted")
    assert [p.name for p, _ in scan.records] == ["name.json"]
    assert scan.files == 2


def test_collect_counts_the_files_it_opened_so_a_zero_has_a_denominator(
        tmp_path):
    _write(tmp_path, "a.json", {"kind": "other"})
    _write(tmp_path, "b.json", {"kind": "other"})
    scan = corpus_seam.collect(tmp_path, lambda d: False)
    assert scan.files == 2 and scan.records == []
    line = scan.denominator("thing(s)")
    assert "2 JSON file(s) opened" in line and "0 thing(s) selected" in line


def test_an_unparseable_file_is_recorded_not_silently_skipped(tmp_path):
    (tmp_path / "truncated.json").write_text("{not json", encoding="utf-8")
    scan = corpus_seam.collect(tmp_path, lambda d: True)
    assert scan.records == []
    assert len(scan.unreadable) == 1
    assert "is not JSON" in scan.unreadable[0][1]
    assert corpus_seam.report_unreadable("g", scan) == \
        corpus_seam.RC_UNDETERMINED


def test_a_selector_that_raises_has_not_answered_no(tmp_path):
    """"I could not classify it" and "it is not a record" must not reach the
    verdict as the same word."""
    _write(tmp_path, "a.json", {"kind": "wanted"})

    def explodes(_doc):
        raise ValueError("selector is broken")

    scan = corpus_seam.collect(tmp_path, explodes)
    assert scan.records == [] and len(scan.unreadable) == 1
    assert "could not be classified" in scan.unreadable[0][1]


# ------------------------------------------------------------------ conflict
def test_two_documents_one_identity_different_content_is_a_conflict():
    rows = [(pathlib.Path("a.json"), "id-1", {"v": 1}),
            (pathlib.Path("b.json"), "id-1", {"v": 2})]
    conflicts, copies = corpus_seam.identity_conflicts(rows, "g", "identity")
    assert copies == []
    assert len(conflicts) == 1
    assert [c["path"] for c in conflicts[0]["claimed_by"]] == ["a.json",
                                                               "b.json"]
    assert corpus_seam.print_conflicts("g", conflicts, copies) == \
        corpus_seam.RC_REFUSED


def test_two_documents_one_identity_identical_content_is_a_copy():
    rows = [(pathlib.Path("a.json"), "id-1", {"v": 1}),
            (pathlib.Path("b.json"), "id-1", {"v": 1})]
    conflicts, copies = corpus_seam.identity_conflicts(rows, "g", "identity")
    assert conflicts == [] and len(copies) == 1
    assert corpus_seam.print_conflicts("g", conflicts, copies) == \
        corpus_seam.RC_OK


def test_one_identity_per_document_is_neither():
    rows = [(pathlib.Path("a.json"), "id-1", {"v": 1}),
            (pathlib.Path("b.json"), "id-2", {"v": 1})]
    assert corpus_seam.identity_conflicts(rows, "g", "identity") == ([], [])


def test_a_conflict_names_every_claimant_not_just_the_first_two():
    rows = [(pathlib.Path(f"{n}.json"), "id-1", {"v": i})
            for i, n in enumerate("abc")]
    conflicts, _ = corpus_seam.identity_conflicts(rows, "g", "identity")
    assert len(conflicts[0]["claimed_by"]) == 3


# ------------------------------------------------------------------- refusal
def test_the_vacuous_arm_is_rc2_and_names_the_root(tmp_path, capsys):
    rc = corpus_seam.vacuous("g", tmp_path, "record(s)")
    assert rc == corpus_seam.RC_UNDETERMINED
    err = capsys.readouterr().err
    assert "VACUOUS" in err and str(tmp_path) in err and "NOT a pass" in err


def test_both_given_is_rc3_and_never_a_design_finding(capsys):
    rc = corpus_seam.both_given("g", "--exact", "--corpus")
    assert rc == corpus_seam.RC_BAD_INVOCATION
    assert "bad invocation" in capsys.readouterr().err


def test_an_absent_corpus_is_refused_through_the_shared_location_seam(
        tmp_path, monkeypatch, capsys):
    """`_corpus_location` is the one seam; this asserts the module DELEGATES
    rather than re-deriving a fourth hand-rolled answer to the same question."""
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    corpus, rc = corpus_seam.open_corpus(tmp_path / "gone", "g", "record(s)")
    assert corpus is None and rc == corpus_seam.RC_UNDETERMINED
    assert "no corpus at" in capsys.readouterr().err

    corpus, rc = corpus_seam.open_corpus(tmp_path / "gone", "g", "record(s)",
                                         may_be_absent=True)
    assert corpus is None and rc == corpus_seam.RC_OK
    assert "NO_CORPUS" in capsys.readouterr().err


def test_a_pointer_set_and_wrong_is_undetermined_even_with_the_opt_in(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(tmp_path / "typo"))
    monkeypatch.delenv("GATEKEEPER_BENCHMARK_DATA_SHA", raising=False)
    corpus, rc = corpus_seam.open_corpus(tmp_path / "gone", "g", "record(s)",
                                         may_be_absent=True)
    assert corpus is None and rc == corpus_seam.RC_UNDETERMINED
    assert "UNDETERMINED" in capsys.readouterr().err
