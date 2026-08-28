#!/usr/bin/env python3
"""`ppa_ablation_check` — the gate that makes `vibeic.ppa.ablation.v1` mean something.

WHAT THIS FILE IS DEFENDING
===========================
The ablation document kind was created to stop a within-project comparison
being filed as a head-to-head. It shipped with a schema, one re-filed record
and one pytest driving one hardcoded path — and with NOTHING in the gate
dispatcher. A kind with no gate behind it is worse than no kind at all: it is a
place a real head-to-head can be filed to escape the fairness conditions
`ppa_head_to_head_check` applies, and no automatic verdict would ever open it.

So the properties below are, in order of what they stop:

    a mis-filed head-to-head is REFUSED     an arm this project did not tune
                                            makes the document a head-to-head;
                                            it must not pass as an ablation
    an EMPTY corpus is rc 2, never rc 0     a gate that has never met an
                                            artefact cannot have cleared one
    an ABSENT corpus is rc 2 and NAMES the  "I could not look" must never
      pointer                               arrive as "there are none"
    an UNREADABLE file is rc 2 and NAMED    a file nobody parsed is not a file
                                            that held no record
    two population sources is rc 3          the caller who names a document
                                            must not get a verdict about a
                                            different population
    the gate is WIRED                       a program nothing invokes is a
                                            program that does not run, which
                                            is the exact defect this whole
                                            lane is about

WHY THE RECORDS ARE FOUND BY CONTENT AND NOT BY NAME: several fixtures below
are filed under names no glob would guess. A filename glob answers "a record
under an unexpected name went unjudged" with a smaller version of itself.

chip-AGNOSTIC: synthetic bytes and declared policy only.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

TESTS = pathlib.Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
REPO = PROGRAMS.parents[3]
GATE = PROGRAMS / "ppa_ablation_check.py"
SCHEMA_DIR = PROGRAMS.parent / "schemas" / "ppa"
DISPATCHER = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

KIND = "vibeic.ppa.ablation.v1"


def run(*args):
    """Drive the REAL entry point. Deliberately not `main(argv)` in-process:
    the dispatcher acts on the EXIT CODE, and a test that calls a function
    leaves the verdict-to-exit-code mapping unmeasured."""
    return _pr.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True)


def arm(role, tuned=True):
    return {
        "flow": f"synthetic-{role}",
        "role": role,
        "config_source": f"synthetic/{role}.yaml",
        "tuned_by_this_project": tuned,
        "ppa": {"area_um2": 100.0, "power_mw": 1.0, "timing_wns_ns": 0.5},
    }


def ablation(**over):
    doc = {
        "schema": KIND,
        "claim_scope": "within_project",
        "isolates": "what the second configuration adds over the first",
        "arms": [arm("a"), arm("b")],
    }
    doc.update(over)
    return doc


def put(path: pathlib.Path, obj) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# THE POSITIVE, AND IT RUNS ON THE SHIPPED CORPUS TOO
# ---------------------------------------------------------------------------

def test_a_well_formed_ablation_under_an_unguessable_name_is_accepted(tmp_path):
    put(tmp_path / "deep" / "nested" / "whatever-name.json", ablation())
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "1 record(s), 0 refused, 0 undetermined, 1 accepted" in r.stdout


def test_the_shipped_corpus_validates_and_the_gate_says_what_it_opened():
    """The REAL published corpus, not a fixture.

    A gate proven only against synthetic bytes has not been shown to run on the
    thing it is wired to. The denominator is asserted with the verdict because
    `0 records` and `0 files` must never read as the same sentence.
    """
    corpus = REPO / "ppa-crosslayer"
    if not corpus.is_dir():                       # pragma: no cover - layout
        pytest.skip(f"{corpus} is not in this checkout")
    r = run("--corpus", str(corpus))
    assert r.returncode == 0, r.stderr + r.stdout
    assert "JSON file(s) opened" in r.stdout
    assert "ablation record(s) selected" in r.stdout


# ---------------------------------------------------------------------------
# THE CLAUSE THAT STOPS A HEAD-TO-HEAD HIDING IN THIS KIND
# ---------------------------------------------------------------------------

def test_an_arm_this_project_did_not_tune_is_refused_and_the_clause_is_named(tmp_path):
    """This is the whole reason the kind exists, and the whole reason it needs
    a gate. A document with an untuned arm is a HEAD-TO-HEAD; passing it here
    is how a comparison escapes `ppa_head_to_head_check`'s fairness
    conditions."""
    doc = ablation()
    doc["arms"][0]["tuned_by_this_project"] = False
    put(tmp_path / "h2h_hiding_as_an_ablation.json", doc)
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "tuned_by_this_project" in r.stderr
    # The reader must be told WHICH failure this is, not merely that some shape
    # rule failed.
    assert "comparison.v2" in r.stderr
    assert "1 refused" in r.stdout


def test_a_claim_scope_that_is_not_within_project_is_refused(tmp_path):
    put(tmp_path / "x.json", ablation(claim_scope="cross_project"))
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "claim_scope" in r.stderr


def test_a_single_arm_ablates_nothing_and_is_refused(tmp_path):
    doc = ablation()
    doc["arms"] = [arm("only")]
    put(tmp_path / "x.json", doc)
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "arms" in r.stderr


def test_a_missing_isolates_is_a_NOTE_and_never_a_finding(tmp_path):
    """The schema does not put `isolates` in `required`. A gate that enforces
    more than the document it cites turns a rule nobody agreed to into a
    load-bearing one, so this stays rc 0 with the gap disclosed."""
    doc = ablation()
    doc.pop("isolates")
    put(tmp_path / "x.json", doc)
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOTE" in r.stdout and "isolates" in r.stdout


# ---------------------------------------------------------------------------
# THE FOUR CORPUS OUTCOMES — ABSENT, VACUOUS, UNREADABLE, PRESENT
# ---------------------------------------------------------------------------

def test_an_empty_corpus_is_rc_2_and_says_it_is_not_a_pass(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run("--corpus", str(empty))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr
    assert "NOT a pass" in r.stderr
    assert str(empty) in r.stderr           # the root is NAMED


def test_an_absent_corpus_is_rc_2_and_names_the_pointer(tmp_path):
    r = run("--corpus", str(tmp_path / "not-there"))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not-there" in r.stderr
    # ABSENT and VACUOUS are two states and must not share one sentence.
    assert "VACUOUS" not in r.stderr


def test_a_corpus_holding_only_unreadable_json_is_rc_2_and_names_the_file(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{ not json", encoding="utf-8")
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "broken.json" in r.stderr
    assert "NOT established to hold no record" in r.stderr


def test_an_unreadable_file_beside_a_good_record_still_raises_the_verdict(tmp_path):
    put(tmp_path / "good.json", ablation())
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "broken.json" in r.stderr


def test_a_refusal_outranks_an_undetermined_in_the_corpus_verdict(tmp_path):
    doc = ablation()
    doc["arms"][0]["tuned_by_this_project"] = False
    put(tmp_path / "bad.json", doc)
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    r = run("--corpus", str(tmp_path))
    # rc 2 is the LARGER integer and the WEAKER verdict; aggregating with max()
    # would promote this refusal to "could not check".
    assert r.returncode == 1, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# INVOCATION — §1 reserves 3 for a bad invocation, never 2
# ---------------------------------------------------------------------------

def test_naming_no_mode_is_rc_3_and_names_every_mode():
    r = run()
    assert r.returncode == 3, r.stdout + r.stderr
    for mode in ("--record", "--corpus", "--corpus-may-be-absent"):
        assert mode in r.stderr


def test_two_population_sources_together_is_rc_3_naming_both(tmp_path):
    put(tmp_path / "x.json", ablation())
    r = run("--record", str(tmp_path / "x.json"), "--corpus", str(tmp_path))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "--record" in r.stderr and "--corpus" in r.stderr


def test_an_unknown_flag_is_rc_3_not_rc_2():
    """argparse exits 2, which §1 reserves for 'I could not look'. A misspelled
    flag reported as 2 reads to a caller as a step with nothing to check."""
    r = run("--this-flag-does-not-exist")
    assert r.returncode == 3, r.stdout + r.stderr


def test_help_is_rc_0():
    r = run("--help")
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# THE WRONG DOCUMENT IS UNDETERMINED, NOT A PILE OF FAILURES
# ---------------------------------------------------------------------------

def test_a_document_of_another_kind_is_undetermined_not_refused(tmp_path):
    """Applying this schema to an unrelated document yields a long list of
    violations that read as 'this ablation is broken' when the truth is 'this
    is not an ablation'. rc 1 is a claim about a published record."""
    other = put(tmp_path / "not-an-ablation.json",
                {"schema": "vibeic.ppa.comparison.v2", "arms": []})
    r = run("--record", str(other))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not validated" in r.stderr.lower()


def test_a_corpus_of_other_kinds_only_is_vacuous_not_a_pass(tmp_path):
    put(tmp_path / "a.json", {"schema": "vibeic.ppa.comparison.v2"})
    put(tmp_path / "b.json", {"schema": "vibeic.ppa.contract.v1"})
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr
    # The denominator must show that files WERE opened, so "0 records" cannot
    # be read as "0 files".
    assert "2 JSON file(s) opened" in r.stdout


def test_selection_is_by_the_DECLARED_schema_and_not_by_a_hint(tmp_path):
    """A document that LOOKS like an ablation and does not DECLARE the kind is
    not one, and this is the property `is_ablation` exists to hold.

    MEASURED, AND IT IS WHY THIS TEST EXISTS: a mutation replacing the declared
    -schema test with a substring test over the document's first bytes passed
    the whole of the rest of this file. Every fixture here happens to put
    `"schema": "vibeic.ppa.ablation.v1"` first, so a selector reading the WORD
    and a selector reading the DECLARATION agree on all of them — a checker
    validating the thing NEXT TO its claim. This corpus separates them: the
    file is NAMED for the kind and name-drops it in its first key, and declares
    a different one. It must NOT be selected, and the verdict must therefore be
    VACUOUS rather than a per-record CANNOT CHECK.
    """
    put(tmp_path / "ablation_looking_but_not.json",
        {"ablation": "this document is about an ablation",
         "schema": "vibeic.ppa.comparison.v2",
         "claim_scope": "within_project",
         "arms": [arm("a"), arm("b")]})
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "VACUOUS" in r.stderr, (
        "a document that only name-drops the kind was SELECTED as one")
    assert "1 JSON file(s) opened" in r.stdout
    assert "0 ablation record(s) selected" in r.stdout


def test_the_declared_kind_is_selected_even_when_nothing_else_hints_at_it(tmp_path):
    """The other half of the same rule: no hint in the path, no hint in any
    key but the declaration itself, and it is still judged."""
    doc = ablation()
    doc.pop("isolates")                       # remove the one prose field
    put(tmp_path / "q" / "zz.json", doc)
    r = run("--corpus", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 ablation record(s) selected" in r.stdout


# ---------------------------------------------------------------------------
# THE WIRING — a program nothing invokes does not run
# ---------------------------------------------------------------------------

def test_the_gate_is_invoked_by_the_hygiene_dispatcher():
    """The defect this lane exists to close is a schema with no gate behind it.
    Shipping a program and not wiring it reproduces that defect one level up.
    """
    if not DISPATCHER.is_file():                  # pragma: no cover - layout
        pytest.skip(f"{DISPATCHER} is not in this checkout")
    text = DISPATCHER.read_text(encoding="utf-8")
    invocations = [ln for ln in text.splitlines()
                   if "ppa_ablation_check.py" in ln and not ln.lstrip().startswith("#")]
    assert invocations, (
        "ppa_ablation_check.py is not invoked by tools/ci/repo_hygiene_gates.sh. "
        "A gate that nothing runs is the defect this program was written to close.")
    assert len(invocations) == 1, (
        f"invoked {len(invocations)} times; a gate run twice reports one "
        f"verdict under two labels: {invocations}")


def test_the_row_tolerates_rc_2_and_BUYS_that_tolerance_with_a_declaration():
    """The wrapper choice AND its exemption, pinned — both were got wrong once.

    FIRST WRONG: plain `run`. MEASURED, a landing that binds a corpus
    (`GATEKEEPER_BENCHMARK_DATA_SHA`) redirects `--corpus` away from the named
    root to the bound clone, and a clone carrying no ablation record answers
    rc 2. Under `run` that fails a landing for a fact about the ENVIRONMENT.

    SECOND WRONG: `run_tolerating_uncheckable` with NO `uncheckable_until`, on
    the reasoning that an undeclared row stays louder in the roll-up. The
    dispatcher refuses that outright — "tolerance has to be bought, not
    defaulted into" — and fails the WHOLE run as a wiring error, so the
    reasoning was not merely stylistically wrong, it certified nothing.

    So both halves are pinned here: the row tolerates rc 2, and it declares
    WHY it can be unable to look.
    """
    if not DISPATCHER.is_file():                  # pragma: no cover - layout
        pytest.skip(f"{DISPATCHER} is not in this checkout")
    lines = DISPATCHER.read_text(encoding="utf-8").splitlines()
    idx = [i for i, ln in enumerate(lines)
           if "ppa_ablation_check.py" in ln and not ln.lstrip().startswith("#")]
    assert len(idx) == 1
    window = "\n".join(lines[max(0, idx[0] - 3):idx[0] + 1])
    assert "run_tolerating_uncheckable" in window, (
        "the row must tolerate rc 2: a bound landing redirects this corpus and "
        f"an absent one is not a finding about a record. Saw:\n{window}")
    # `uncheckable_until` binds to the NEXT gate, so it sits between the
    # previous invocation and this one.
    preceding = lines[max(0, idx[0] - 12):idx[0]]
    declared = [ln for ln in preceding
                if ln.lstrip().startswith("uncheckable_until")]
    assert len(declared) == 1, (
        "the tolerance must be BOUGHT: the dispatcher rejects a "
        f"run_tolerating_uncheckable row with no exemption. Saw: {declared}")
    # And the reason must name the state it is excusing, not merely exist —
    # an exemption that says nothing is a skip button with a date on it.
    assert "GATEKEEPER_BENCHMARK_DATA_SHA" in declared[0], (
        "the exemption does not name the measured way rc 2 is reached")
    assert "rc 1" in declared[0], (
        "the exemption does not say that a record which IS read and fails "
        "still fails this row")


def test_a_bound_landing_redirects_the_corpus_and_says_so(tmp_path):
    """The measured behaviour the wrapper choice rests on, driven end to end."""
    clone = tmp_path / "bound-clone"
    clone.mkdir()
    env = dict(os.environ)
    env["GATEKEEPER_BENCHMARK_DATA_SHA"] = "0" * 40
    env["VIBE_IC_BENCHMARK_DATA"] = str(clone)
    r = _pr.run([sys.executable, str(GATE), "--corpus",
                        str(REPO / "ppa-crosslayer")],
                       capture_output=True, text=True,
                       env=env)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "binds the landing corpus" in r.stderr
    assert "VACUOUS" in r.stderr
    # The redirect is ANNOUNCED, never silent: a reader must be able to tell
    # which tree produced the verdict.
    assert str(clone) in r.stderr
