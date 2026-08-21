"""The CURRENT round has to be machine-readable — position is not authority.

MEASURED, 2026-08-05. Two escapes in one hour, both from the same defect in the
ARTEFACT rather than in the reader:

  (i)  A RESULT.md accumulates rounds and the NEWEST round was written at the
       TOP with older tallies left below. A reader doing
       ``grep -oE 'PASS=… FAIL=… MISSING=…' | tail -1`` got the OLDEST triple
       and reported it as this round's result.
  (ii) A tally was grepped out of a report whose very next paragraph RETRACTED
       it. A withdrawn hypothesis was reported as the fleet's best number.

The document in each case was a machine-readable deliverable carrying several
numbers with NO machine-readable statement of which one was current and which
had been withdrawn. Whichever consumer reads it — a human with grep, a monitor,
the next agent, or ``result_md_audit_provenance_check`` — eventually takes the
wrong one, and nothing tells it that it did.

WHAT THESE TESTS ASSERT
=======================
Every gating assertion below is driven through the PUBLIC surface
(``run_output_completeness_check.check`` / ``.main``) and never references a
symbol this change introduces. That is deliberate: it makes each failure a
BEHAVIOURAL one rather than a missing-symbol one, and it means a different
correct implementation of the same rule passes this file unchanged.

The two directions carried here:

  DETECTION  — a deliverable presenting two or more DIFFERENT tallies without
               declaring which is live must not be signed off.
  RESTRAINT  — the OVER-CORRECTION is a rule that demands ceremony from an
               honest report. A report with one tally, or with one tally
               repeated, or with no tally at all, must stay clean; the whole
               published corpus must stay clean; and no existing classification
               may change. Those are the tests that matter most here, because
               the cheap way to "fix" this defect is a rule that fires on every
               report that ever mentions a number twice.
"""
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import run_output_completeness_check as R  # noqa: E402
import result_md_audit_provenance_check as P  # noqa: E402
from _published_corpus import corpus_root, needs_corpus  # noqa: E402

AMBIG = "DELIVERABLE_CURRENT_ROUND_AMBIGUOUS"

# Enough prose to clear the deliverable's real-content floors in every fixture,
# so that no assertion below is accidentally about byte count.
_FILLER = (
    "Shape B — runner with --skip-phase3, entry point vibe_ic_one_shot_runner.\n"
    "Tool substitution: commercial simulator -> iverilog; commercial synthesis\n"
    "-> yosys + OpenROAD. Residual triage: every remaining fail is category C.\n"
    "Reproduce: re-run the scorer against the same design directory with every\n"
    "installed check enabled, then re-read this deliverable.\n"
)


def _run(tmp_path: Path, body: str, *, name: str = "run", live: bool = False,
         extra_files: bool = True) -> Path:
    """A run dir that is COMPLETE on every axis except the one under test."""
    d = tmp_path / name
    (d / "reports" / "orchestrator").mkdir(parents=True, exist_ok=True)
    (d / "out").mkdir(parents=True, exist_ok=True)
    (d / "RESULT.md").write_text(body + "\n" + _FILLER)
    (d / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        json.dumps({"verdict": "FAIL"}))
    if extra_files:
        (d / "out" / "design.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    if live:
        # This process is alive by construction, so the lock is genuinely live.
        (d / ".runner.lock").write_text(json.dumps({"pid": __import__("os").getpid()}))
    return d


# ---------------------------------------------------------------------------
# DETECTION — the two measured shapes, and the ways of half-declaring.
# ---------------------------------------------------------------------------
_THREE_ROUNDS_NEWEST_TOP = """# RESULT — nangate45 demo cell

## Round C (newest)

Verdict: FAIL

Tally: PASS=21 FAIL=7 MISSING=1

## Round B

Tally: PASS=24 FAIL=4 MISSING=1

## Round A

Tally: PASS=26 FAIL=2 MISSING=1
"""

_THREE_ROUNDS_NEWEST_BOTTOM = """# RESULT — nangate45 demo cell

## Round A

Tally: PASS=26 FAIL=2 MISSING=1

## Round B

Tally: PASS=24 FAIL=4 MISSING=1

## Round C (newest)

Verdict: FAIL

Tally: PASS=21 FAIL=7 MISSING=1
"""

_RETRACTED_IN_PROSE_ONLY = """# RESULT — sky130A demo cell

Verdict: FAIL

## Hypothesis run

Tally: PASS=26 FAIL=2 MISSING=1

I retract that number: PASS=26 was reachable only by disabling a check the repo
installed deliberately, so it is not a legitimate reading of this design.

## Final measurement

Tally: PASS=19 FAIL=9 MISSING=1
"""


def test_measured_case_i_newest_round_at_top_is_refused(tmp_path):
    """The exact shape that produced a stale triple: rounds accumulate, the
    newest is at the TOP, and a positional reader takes the oldest."""
    rep = R.check(_run(tmp_path, _THREE_ROUNDS_NEWEST_TOP))
    assert rep.state == AMBIG and rep.verdict == "FAIL" and rep.rc == 1
    # The census must name all three so an operator can see the choice they
    # were unknowingly making.
    assert len(rep.evidence["round_tally_distinct"]) == 3


def test_the_defect_is_the_document_not_the_ordering(tmp_path):
    """Same three rounds, newest at the BOTTOM instead. The verdict must be
    identical: a rule that only caught one ordering would be a rule about
    ordering, and ordering is exactly what a reader cannot rely on."""
    top = R.check(_run(tmp_path, _THREE_ROUNDS_NEWEST_TOP, name="a"))
    bot = R.check(_run(tmp_path, _THREE_ROUNDS_NEWEST_BOTTOM, name="b"))
    assert top.state == bot.state == AMBIG


def test_measured_case_ii_prose_retraction_does_not_reach_a_machine(tmp_path):
    """A number retracted in the next paragraph is still a live claim to every
    mechanical reader. Correct, and insufficient."""
    rep = R.check(_run(tmp_path, _RETRACTED_IN_PROSE_ONLY))
    assert rep.state == AMBIG and rep.rc == 1


def test_declaring_the_current_one_is_not_enough_on_its_own(tmp_path):
    """Half the fix. The live round is declared, but the withdrawn number sits
    in the file unmarked, so a reader landing on that line still reads a dead
    number as a live claim."""
    body = """# RESULT

Tally: PASS=26 FAIL=2 MISSING=1

Tally: PASS=19 FAIL=9 MISSING=1  [CURRENT]
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG and rep.rc == 1
    stat = {d["status"] for d in rep.evidence["round_tally_distinct"]}
    assert stat == {"CURRENT", "UNMARKED"}


_BASELINE_VS_THIS_RUN = """# RESULT

Verdict: FAIL

canonical v1.0.0 : PASS=30  FAIL=1  MISSING=3  WAIVED-DEFERRED=3  SKIPPED=22
this run         : PASS=32  FAIL=0  MISSING=2  WAIVED-DEFERRED=3  SKIPPED=22
"""


def test_the_baseline_vs_this_run_shape_is_refused(tmp_path):
    """The dominant shape in the wild: a two-line comparison of the reference
    figure against this round's, with nothing marking which is which.

    A FIRST-MATCH consumer takes the BASELINE and reports it as the round's
    result; a `tail -1` consumer takes the round. Two readers, two different
    answers off one file, and neither can tell it guessed.
    """
    rep = R.check(_run(tmp_path, _BASELINE_VS_THIS_RUN))
    assert rep.state == AMBIG and rep.rc == 1


def test_a_baseline_may_be_labelled_a_baseline_not_a_withdrawal(tmp_path):
    """A baseline is not a retracted claim — it is a live figure about a
    different thing. A rule that could only be satisfied by stamping WITHDRAWN
    on it would be asking the author to write something false, and a rule
    satisfiable only by lying gets worked around rather than followed.

    This is the fixed form of the shape above, and it must sign off clean.
    """
    body = """# RESULT

Verdict: FAIL

canonical v1.0.0 : PASS=30  FAIL=1  MISSING=3   [BASELINE]
this run         : PASS=32  FAIL=0  MISSING=2   [CURRENT]
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "COMPLETE" and rep.rc == 0


def test_withdrawing_everything_declares_nothing(tmp_path):
    """The cheapest way to silence a guard like this is to stamp WITHDRAWN on
    every line. That leaves the document with no live number at all, which is
    the undeclared state under another spelling, and it must not pass."""
    body = """# RESULT

Tally: PASS=26 FAIL=2 MISSING=1  [SUPERSEDED]

Tally: PASS=19 FAIL=9 MISSING=1  [SUPERSEDED]
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG and rep.rc == 1


def test_two_rounds_both_claiming_to_be_current_is_refused(tmp_path):
    body = """# RESULT

Tally: PASS=26 FAIL=2 MISSING=1  [CURRENT]

Tally: PASS=19 FAIL=9 MISSING=1  [CURRENT]
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG and rep.rc == 1


def test_one_tally_marked_both_ways_is_refused(tmp_path):
    """A line that says it is both live and withdrawn resolves to nothing."""
    body = """# RESULT

Tally: PASS=26 FAIL=2 MISSING=1  [CURRENT] [WITHDRAWN]

Tally: PASS=19 FAIL=9 MISSING=1  [SUPERSEDED]
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG and rep.rc == 1


def test_a_status_word_not_attached_to_a_number_declares_nothing(tmp_path):
    """A marker floating in prose says nothing about any particular number.
    The declaration has to RESOLVE to one tally or it is not a declaration."""
    body = """# RESULT

CURRENT ROUND: see below.

Tally: PASS=26 FAIL=2 MISSING=1

Tally: PASS=19 FAIL=9 MISSING=1
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG and rep.rc == 1


def test_a_tally_split_across_lines_is_still_counted(tmp_path):
    """``\\s+`` in the tally grammar spans newlines, so the in-repo consumer's
    ``search(text)`` matches a tally broken across lines. A guard that scanned
    strictly line by line would see fewer tallies than the consumer does, which
    would reopen the same hole one level up."""
    body = """# RESULT

Tally:
PASS=26
FAIL=2
MISSING=1

Tally: PASS=19 FAIL=9 MISSING=1
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG
    assert rep.evidence["round_tally_occurrences"] == 2


def test_cli_exits_nonzero_and_prints_the_census(tmp_path, capsys):
    d = _run(tmp_path, _RETRACTED_IN_PROSE_ONLY)
    rc = R.main([str(d)])
    out = capsys.readouterr().out
    assert rc == 1
    assert AMBIG in out
    assert "position is not authority" in out
    # Both numbers named, so the operator can see which one they were about to
    # quote and which one the document actually stands behind.
    assert "PASS=26 FAIL=2 MISSING=1" in out
    assert "PASS=19 FAIL=9 MISSING=1" in out


def test_json_report_carries_the_census_and_the_capture_candidate(tmp_path):
    d = _run(tmp_path, _THREE_ROUNDS_NEWEST_TOP)
    out = tmp_path / "v.json"
    assert R.main([str(d), "--json", str(out)]) == 1
    doc = json.loads(out.read_text())
    assert doc["state"] == AMBIG and doc["rc"] == 1
    assert len(doc["evidence"]["round_tally_distinct"]) == 3
    assert doc["capture_candidate"]["failure_mode"] == AMBIG


# ---------------------------------------------------------------------------
# THE COUPLING — the guard must cover the consumer that actually misreads.
# ---------------------------------------------------------------------------
def test_every_document_the_repo_consumer_can_misread_is_refused(tmp_path):
    """``result_md_audit_provenance_check`` extracts a tally out of RESULT.md
    with a FIRST-MATCH positional search and quotes it verbatim as
    ``quoted_tally``. Driven on the retraction case, it quotes the WITHDRAWN
    number. So the property is not "this gate recognises some tallies" — it is
    "for every document that consumer can take a number out of, if the document
    holds two different numbers, this gate refuses it".

    Expressed against both programs' behaviour rather than against either
    program's regex, so re-spelling the pattern on either side cannot make this
    pass while the hole reopens.
    """
    shapes = [
        _THREE_ROUNDS_NEWEST_TOP,
        _THREE_ROUNDS_NEWEST_BOTTOM,
        _RETRACTED_IN_PROSE_ONLY,
        "# R\n\nPASS=26 FAIL=2 MISSING=1\n\nPASS=19 FAIL=9 MISSING=1\n",
        "# R\n\n    PASS = 26  FAIL = 2  MISSING = 1\n\n    PASS=19 FAIL=9 MISSING=1\n",
        "# R\n\npass=26 fail=2 missing=1\n\nPASS=19 FAIL=9 MISSING=1\n",
        "# R\n\n```\nPASS=26 FAIL=2 MISSING=1\n```\n\n```\nPASS=19 FAIL=9 MISSING=1\n```\n",
        "# R\n\n| round | tally |\n|---|---|\n| A | PASS=26 FAIL=2 MISSING=1 |\n"
        "| B | PASS=19 FAIL=9 MISSING=1 |\n",
    ]
    for i, body in enumerate(shapes):
        d = _run(tmp_path, body, name=f"c{i}")
        # The consumer does take a number out of this document...
        assert P._TALLY_RE.search((d / "RESULT.md").read_text()), (
            f"shape {i}: consumer extracts nothing — fixture no longer exercises "
            f"the coupling")
        # ...so the gate must refuse it.
        assert R.check(d).state == AMBIG, f"shape {i} not refused"


# ---------------------------------------------------------------------------
# RESTRAINT — the over-correction direction. These are the ones that matter.
# ---------------------------------------------------------------------------
def test_one_tally_needs_no_ceremony(tmp_path):
    """The simple case. A report that states one number, unmarked, is
    unambiguous and must be signed off exactly as before. A rule that demanded
    a CURRENT marker here would flag the state this repo has already shipped."""
    body = "# RESULT\n\nVerdict: FAIL\n\nTally: PASS=21 FAIL=7 MISSING=1\n"
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "COMPLETE" and rep.rc == 0


def test_the_same_tally_stated_three_times_is_one_claim(tmp_path):
    """Repetition is not ambiguity. A report that puts its number in the
    headline, again in a table and again in the reproduce section is honest;
    counting OCCURRENCES instead of DISTINCT values would fail all of them."""
    body = """# RESULT

Headline: PASS=21 FAIL=7 MISSING=1

| gate set | tally |
|---|---|
| all | PASS=21 FAIL=7 MISSING=1 |

Reproduce and you get PASS=21 FAIL=7 MISSING=1 again.
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "COMPLETE" and rep.rc == 0


def test_a_report_with_no_tally_is_untouched(tmp_path):
    """54 of the 56 published RESULT.md carry no tally at all."""
    body = "# RESULT\n\nVerdict: FAIL\n\nThe run did not reach sign-off.\n"
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "COMPLETE" and rep.rc == 0


def test_the_declared_form_passes_so_the_rule_is_satisfiable(tmp_path):
    """A guard nobody can satisfy is not a gate, it is a wall. The corrected
    form of the measured document — one CURRENT, the rest WITHDRAWN — signs
    off clean."""
    body = """# RESULT

Verdict: FAIL

Round C: PASS=21 FAIL=7 MISSING=1  [CURRENT]
Round B: PASS=24 FAIL=4 MISSING=1  [SUPERSEDED]
Round A: PASS=26 FAIL=2 MISSING=1  (WITHDRAWN — reachable only with a check disabled)
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "COMPLETE" and rep.rc == 0


@pytest.mark.parametrize("marker_line", [
    "Tally: PASS=21 FAIL=7 MISSING=1  [CURRENT]",
    "Tally: PASS=21 FAIL=7 MISSING=1 — CURRENT",
    "Tally: PASS=21 FAIL=7 MISSING=1 CURRENT",
    "**CURRENT** — PASS=21 FAIL=7 MISSING=1",
    "| CURRENT | PASS=21 FAIL=7 MISSING=1 |",
    "<!-- CURRENT --> PASS=21 FAIL=7 MISSING=1",
    "CURRENT_ROUND: PASS=21 FAIL=7 MISSING=1",
    "Tally: PASS=21 FAIL=7 MISSING=1  [LATEST]",
    "Tally: PASS=21 FAIL=7 MISSING=1  (AUTHORITATIVE)",
])

def test_the_ways_an_author_will_actually_write_the_marker_all_work(
        tmp_path, marker_line):
    """A rule that only accepts one spelling gets worked around rather than
    followed. Each of these is a shape a real report already uses somewhere."""
    body = f"# RESULT\n\n{marker_line}\n\nOld: PASS=26 FAIL=2 MISSING=1 [STALE]\n"
    rep = R.check(_run(tmp_path, body, name=str(abs(hash(marker_line)))))
    assert rep.state == "COMPLETE" and rep.rc == 0


@pytest.mark.parametrize("not_current", [
    "WITHDRAWN", "RETRACTED", "SUPERSEDED", "OBSOLETE", "STALE", "HISTORICAL",
    "BASELINE", "REFERENCE", "PRIOR", "PREVIOUS",
])
def test_both_honest_reasons_a_number_is_not_this_round_are_sayable(
        tmp_path, not_current):
    """A claim taken back and a reference that was never the claim are
    different facts. Both keep a number out of the current slot, and the
    vocabulary has to let an author write whichever one is true."""
    body = (f"# RESULT\n\nRound C: PASS=21 FAIL=7 MISSING=1  [CURRENT]\n"
            f"Round A: PASS=26 FAIL=2 MISSING=1  [{not_current}]\n")
    rep = R.check(_run(tmp_path, body, name="v" + not_current))
    assert rep.state == "COMPLETE" and rep.rc == 0


def test_an_adjective_in_prose_is_not_a_marker(tmp_path):
    """``rerun_v1293_hard94/RESULT.md:7`` in this repo reads "…of the CURRENT
    plugin…". That is an adjective about a plugin, not a claim about a number,
    and if it could set a tally's status then a sentence would be able to
    decide which round is live. Here the word sits ON the older tally's line and
    must still leave the document undeclared."""
    body = """# RESULT

Round A was measured against the CURRENT plugin: PASS=26 FAIL=2 MISSING=1

Round B: PASS=19 FAIL=9 MISSING=1
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG
    assert all(d["status"] == "UNMARKED"
               for d in rep.evidence["round_tally_distinct"])


def test_supersede_written_about_the_live_round_does_not_kill_it(tmp_path):
    """"these numbers supersede everything below" is written ON the current
    round's line. Reading the verb as a withdrawal would mark the live number
    dead and then fail an honest, fully-declared report."""
    body = """# RESULT

Round C: PASS=21 FAIL=7 MISSING=1 [CURRENT] — these numbers supersede everything below
Round A: PASS=26 FAIL=2 MISSING=1 [SUPERSEDED]
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "COMPLETE" and rep.rc == 0


def test_a_live_runner_is_not_a_failure(tmp_path):
    """A round still being written may legitimately hold a moment where the new
    tally is down and the marker has not moved yet. That is IN_PROGRESS, not a
    failure — and rc 3 is still not rc 0, so nothing signs it off."""
    d = _run(tmp_path, _THREE_ROUNDS_NEWEST_TOP, live=True)
    rep = R.check(d)
    assert rep.state == "RUN_STILL_IN_PROGRESS"
    assert rep.verdict == "IN_PROGRESS" and rep.rc == 3


# ---------------------------------------------------------------------------
# BLAST RADIUS — no existing classification may change.
# ---------------------------------------------------------------------------
def test_a_stub_with_two_tallies_is_still_a_stub(tmp_path):
    """The new branch is judged only where everything else already read green.
    A hollow deliverable keeps its own, more fundamental diagnosis."""
    d = tmp_path / "stub"
    (d / "reports" / "orchestrator").mkdir(parents=True)
    (d / "RESULT.md").write_text("PASS=26 FAIL=2 MISSING=1\nPASS=19 FAIL=9 MISSING=1\n")
    (d / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        json.dumps({"verdict": "FAIL"}))
    rep = R.check(d)
    assert rep.state == "DELIVERABLE_STUB"


def test_a_missing_deliverable_is_still_the_abandon_bug(tmp_path):
    d = tmp_path / "gone"
    (d / "reports").mkdir(parents=True)
    (d / "reports" / "final_summary.md").write_text("# final\nverdict: PASS\ndone\n")
    rep = R.check(d)
    assert rep.state == "COMPUTE_DONE_DELIVERABLE_MISSING"


def test_a_self_declared_interim_report_keeps_its_own_diagnosis(tmp_path):
    """Precedence: the stronger, older state wins. A document that says of
    itself that it is unfinished is diagnosed as unfinished, not as ambiguous,
    even when it also carries two tallies."""
    body = """# RESULT

> ⚠️ INTERIM — numbers will be filled from the run's own artefacts.

Tally: PASS=26 FAIL=2 MISSING=1

Tally: PASS=19 FAIL=9 MISSING=1
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "DELIVERABLE_SELF_DECLARED_INTERIM"


def test_a_contradicting_headline_keeps_its_own_diagnosis(tmp_path):
    body = """# RESULT

Verdict: PASS

Tally: PASS=26 FAIL=2 MISSING=1

Tally: PASS=19 FAIL=9 MISSING=1
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "DELIVERABLE_CONTRADICTS_ORCHESTRATOR"


def test_a_run_that_produced_only_inputs_keeps_its_own_diagnosis(tmp_path):
    d = tmp_path / "inputs_only"
    (d / "input").mkdir(parents=True)
    (d / "input" / "spec.md").write_text("the design spec\n")
    (d / "RESULT.md").write_text(
        "# RESULT\n\nPASS=26 FAIL=2 MISSING=1\n\nPASS=19 FAIL=9 MISSING=1\n"
        + _FILLER)
    rep = R.check(d)
    assert rep.state == "NO_OUTPUTS_ONLY_INPUTS"


# ---------------------------------------------------------------------------
# CORPUS SWEEP — the guard must not flag the state the repo already shipped.
# ---------------------------------------------------------------------------
@needs_corpus
def test_no_published_result_md_is_flagged(tmp_path):
    """Swept through ``check()`` — the shipped verdict, not a helper — with each
    published deliverable presented as a complete run's RESULT.md.

    Two of the 56 carry a tally, one each; the other 54 carry none. If a future
    deliverable trips this, that is either a real ambiguous report (fix the
    report) or the rule is too wide (narrow the rule) — never a reason to
    weaken the assertion.

    SWEPT OVER THE CORPUS, NOT OVER THIS CHECKOUT. Every one of the 56 is a
    PUBLISHED deliverable and they now live in `vibeic/benchmark-data`; walking
    the repository root found ONE unrelated `RESULT.md` and tripped the
    too-thin floor. That floor is the assertion doing its job — a sweep of 1 is
    not the sweep this test claims to be — so the fix is to walk the tree that
    holds the deliverables, and to SKIP naming the corpus when no such tree is
    readable. The floor itself is untouched.
    """
    root = corpus_root()
    files = sorted(root.rglob("RESULT.md"))
    files = [f for f in files if ".git" not in f.parts]
    run = tmp_path / "sweep"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "final_summary.md").write_text("verdict: FAIL\n")
    flagged = []
    for f in files:
        rep = R.check(run, result=f)
        if rep.state == AMBIG:
            flagged.append((str(f.relative_to(root)),
                            rep.evidence["round_tally_distinct"]))
    assert not flagged, ("published RESULT.md flagged as ambiguous-current-"
                        "round: " + repr(flagged))
    assert len(files) >= 20, f"sweep saw only {len(files)} files — too thin"
