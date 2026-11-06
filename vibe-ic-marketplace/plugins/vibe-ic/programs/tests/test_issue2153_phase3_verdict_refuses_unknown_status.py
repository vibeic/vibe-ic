#!/usr/bin/env python3
"""vibe-ic#2153 — the phase-3 catch-all, and why R-0915-85 deletes the machinery.

WHAT #2153 WAS. `phase3_one_shot_runner._aggregate_verdict` ended
`return "PASS"`. Any status it did not enumerate fell through and turned the
whole run green: the system did not recognise something and reported success,
which is the worst available default because it is invisible exactly when a new
tier, a rename or a typo is introduced.

It had been patched BY HAND three times before #2153 — `BLOCKED` (#544),
`VACUOUS_PASS` (#654), `PASS_WITH_ATTRIBUTION` (#2148) — each by an author who
happened to notice. #2153 then found two MORE arriving green, by walking every
`StepResult` construction rather than by reading the code: `WARN` from
`step_prelayout_signoff`, and `PASS_W_WARN`, which is in the published corpus
(`ic/caravel_user_project/v1.9.43_sky130A`, `step11_dft_insertion`, ATPG rc=1 at
60.5 % stuck-at coverage) contributing nothing to that run's verdict.

#2153's answer was a REFUSAL: an aggregator holding a word it cannot classify
says `UNKNOWN_STATUS:<word>@<step>` and exits non-zero, rather than grading a
plan it does not understand.

WHY THIS FILE IS REWRITTEN AND NOT DELETED. R-0915-85 removes the thing #2153
guarded: there is no tier table and no catch-all, because
`verdict.run_verdict` is total over the declared words and `verdict.parse`
refuses an unregistered word AT THE ROW THAT CARRIES IT. That is #2153's refusal moved EARLIER — from
the roll-up at the end of a run to the construction of the row — and it is
strictly stronger, because a run can no longer reach its aggregator carrying an
unclassifiable word at all.

The two words #2153 found are gone with it: `WARN` is `PASS_WITH_WAIVERS` (a
pass the step itself declined to make clean) and `PASS_W_WARN` likewise. Both
are asserted below, so the corpus case #2153 measured cannot come back.
"""
from __future__ import annotations

import sys

import pytest

from _plugin_tree import plugin_path

sys.path.insert(0, str(plugin_path() / "programs"))

import die_level_deck_rule_attribution as D  # noqa: E402
import verdict as V  # noqa: E402

RUNNER = plugin_path() / "programs" / "phase3_one_shot_runner.py"


@pytest.fixture(scope="module")
def agg():
    import phase3_one_shot_runner as P  # noqa: PLC0415 — heavy, module-scoped
    return P.StepResult


# ── the refusal, moved to the row ────────────────────────────────────────

def test_an_unclassifiable_word_is_refused_at_the_row_not_at_the_rollup(agg):
    """#2153's property, earlier. The plan can no longer BE built."""
    SR = agg
    with pytest.raises(V.UnknownVerdictWord):
        SR("step31_drc", "A_TIER_INVENTED_TOMORROW")


@pytest.mark.parametrize("word", ["WARN", "PASS_W_WARN", "BLOCKED",
                                  "VACUOUS_PASS", "ENV_UNAVAILABLE",
                                  "SKIP", "NOT_EXECUTED"])
def test_genuinely_retired_words_are_refused(word):
    """A typo or retired producer word still fails at the row."""
    with pytest.raises(V.UnknownVerdictWord):
        V.parse(word)
