"""test_an_audit_that_did_not_certify_is_not_a_pass.py

TWO VERDICT DEFECTS IN THE PHASE-2/3 CHAIN, both about reading a word and ignoring
everything else the producer said.

(a) `design_one_shot_runner.step_final_audit` read its verdict as
    `"Overall: PASS" in out` -- a SUBSTRING of the whole captured stream -- and consulted
    the audit's exit code only for 124 (timeout). `flow_compliance_check` has a DESIGNED
    state where those two disagree: its vibe-ic#2092 reconciliation canary prints the run
    word, then prints "THIS REPORT DOES NOT RECONCILE ... do not quote its counts", says
    "(the run's own status is unchanged and still PASS.)" and returns 1. Its own contract
    spells it out -- "the report is still WRITTEN ... and the run exits non-zero.
    `run_status` is untouched -- what changes is that the artefact stops CERTIFYING its own
    arithmetic." So the audit withdraws its certification and the orchestrator wrote PASS.

(b) `phase23_one_shot_runner._aggregate_verdict._TIERS` knew three of the four words
    `verdict.run_verdict` can hand up. The missing one is NOT_MEASURED, which phase 2 can
    publish (`step_final_audit`'s own R-0915-159 branch produces a NOT_MEASURED step), and
    a phase that measured nothing came back as `UNKNOWN_PHASE_VERDICT` -- loud and
    non-zero, so nothing was laundered, but it is the wrong answer: that word is not
    unrecognised, it is a state this repo has a tier for.

THE RULE, with no tool or step name in it:

    A producer has as many channels as it chooses to use, and a consumer that reads one
    of them has not read the producer. An exit code is an account of the run; a word
    printed beside a refusal to certify is not a certificate. And a vocabulary with one
    owner must be ASKED, never retyped -- a fourth copy of a list drifts the way the
    first three did.

Fixtures quote the producers' OWN print statements and the OWN vocabulary module; nothing
here restates a path or a word that the code does not itself produce.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _audit_verdict as _AV                      # noqa: E402 — the rule's owner


# ═══ (a) the audit's two channels ═════════════════════════════════════════

















def test_the_parser_takes_the_verdict_line_and_nothing_else():
    """The parser, directly: anchored, last-match-wins, and `None` for no verdict line.

    THE HELPER MOVED, and this arm followed it rather than being deleted. #2572 put the rule
    in `design_one_shot_runner`; two SIBLING readers turned out to have the same defect, so
    the rule moved to `_audit_verdict` — one owner, asked by all three — and it was MOVED, not
    copied. The property is unchanged; only its address is.
    """
    assert _AV.verdict_word("\nOverall: PASS  (strict=True)\n") == "PASS"
    # the decoy LAST, which is where the blocker list puts it — see the arm above
    assert _AV.verdict_word(
        "\nOverall: NOT_MEASURED  (strict=True)\n"
        "       observed : ... | output: Overall: PASS  (strict=True)\n") == "NOT_MEASURED"
    # and the last VERDICT LINE wins when there really are two of them
    assert _AV.verdict_word(
        "Overall: PASS  (strict=True)\nOverall: FAIL  (strict=True)\n") == "FAIL"
    assert _AV.verdict_word("no verdict here at all\n") is None
    assert _AV.verdict_word("") is None




# ═══ (b) one vocabulary, asked rather than retyped ═════════════════════════
