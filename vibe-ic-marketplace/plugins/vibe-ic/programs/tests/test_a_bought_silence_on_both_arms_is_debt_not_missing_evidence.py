#!/usr/bin/env python3
"""A hygiene gate silent on BOTH arms under a live exemption refused every landing.

MEASURED on 30772a457 (v1.20.93), running
`programs/tests/test_landing_merge_verdict.py` on a host where the hermetic arms
can actually start -- inside the pinned image they skip as NOT_MEASURED, so 24
ids never run and the file reads green from there:

    test_end_to_end_post_bootstrap_equal_corpus_uses_ordinary_delta   FAILED
      REFUSE INCOMPLETE EVIDENCE — HYGIENE_NO_VERDICT_EITHER_SIDE:DRC PASS is
                                   not vacuous (tiny/openpdkx)
      ... and the same for three sibling gates ...

THE DEFECT. `hygiene_finding_delta` reports every gate that reached no verdict
on both arms in one list, `no_verdict_either_side`, and `landing_merge_verdict`
(since v1.19.88, which made incomplete evidence blocking) turns each entry into
a refusal. That list holds two different things:

  * a gate NOT_CHECKED on both arms under a DATED, REASONED, UNEXPIRED
    `uncheckable_until` -- a disclosure this repository sells on purpose, and
  * a gate that is simply silent, with nothing bought.

Only the second is missing evidence. The first is an unchanged inherited state,
identical on both arms, that NO BRANCH CAN CLEAR -- so the landing was refused
for a reason no candidate could act on.

THE PROOF THAT THIS IS AN INCONSISTENCY AND NOT A POLICY. The same file already
answers this exact question on the EMPTY-base bootstrap path: `_bounded_not_
checked` -- "a dated, reasoned, unexpired disclosure" -- decides which unknowns
may stand in for a measured base, and `test_end_to_end_trusted_verifier_supplies
_the_one_bootstrap_evidence` asserts those FOUR `tiny/openpdkx` labels are
admitted as `bounded_not_checked` and LANDS. The bootstrap arm sees the gates
declared on ONE side; the ordinary arm sees them declared on BOTH, in the same
state, with the same live exemption -- and refused. Strictly more evidence
produced a strictly worse verdict.

NOTHING IS RELAXED, and that is what the controls below are for. The exemption
test is the one the bootstrap path already trusts. An unexempted silence, an
EXPIRED one, and a silence of a kind no exemption speaks to (`OUT_OF_SCOPE`,
`LISTED`, `OTHER_SHARD`) are each still outside the bought subset and still
refuse. A gate silent on only ONE arm still refuses, untouched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


#: The day both records are measured on. `delta` refuses arms measured on
#: different days, so one constant serves both.
TODAY = "2026-08-15"

#: A live bound and its reason, in the shape `repo_hygiene_gates.sh` writes for
#: `uncheckable_until <date> <why>`.
LIVE_UNTIL = "2027-02-28"
LIVE_WHY = "fixture has no macro LEF"

LABEL = "macro OBS not crossed (tiny/openpdkx)"










# ------------------------------------------------------------------------
# 1. WHAT THE DELTA MUST NOW SAY
# ------------------------------------------------------------------------









# ------------------------------------------------------------------------
# 2. WHAT THE VERDICT MUST NOW DO WITH IT
# ------------------------------------------------------------------------

def _decide(**over):
    """The sibling file's LAND-OK baseline, so this asserts against the REAL
    decision and not a re-typed copy of it that could drift into agreeing."""
    spec = importlib.util.spec_from_file_location(
        "sibling_landing_merge_verdict_tests",
        HERE / "test_landing_merge_verdict.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert hasattr(module, "_decide"), (
        "the sibling test file no longer exposes the LAND-OK baseline `_decide`")
    return module._decide(**over)


def _hygiene(**over):
    rec = {"status": "CLEAN", "introduced": [], "carried": [], "cleared": [],
           "candidate_findings": 0, "base_findings": 0, "declared": 2}
    rec.update(over)
    return rec


def _reasons_naming_no_verdict(verdict):
    return [r for r in verdict.reasons if "NO_VERDICT_EITHER_SIDE" in r]


def test_a_bought_silence_does_not_refuse_the_landing():
    """THE CASE THIS EXISTS FOR. Identical on both arms, bought, and therefore
    not something this branch did or could undo."""
    v = _decide(hygiene=_hygiene(
        no_verdict_either_side=[LABEL],
        no_verdict_either_side_bounded=[LABEL]))
    assert _reasons_naming_no_verdict(v) == [], v.reasons
    assert v.ok is True, v.reasons


def test_an_unbought_silence_still_refuses_the_landing():
    """THE PAIRED CONTROL, and the one that would catch this being turned into
    a blanket excuse: same record, empty subset, still refused."""
    v = _decide(hygiene=_hygiene(no_verdict_either_side=[LABEL],
                                 no_verdict_either_side_bounded=[]))
    assert _reasons_naming_no_verdict(v) == [
        "INCOMPLETE EVIDENCE — HYGIENE_NO_VERDICT_EITHER_SIDE:" + LABEL], v.reasons
    assert v.ok is False


def test_a_record_that_does_not_state_the_subset_keeps_todays_refusal():
    """A helper too old to state the subset must not be READ as having stated
    an empty-of-blocking one. Absence is the strict direction."""
    v = _decide(hygiene=_hygiene(no_verdict_either_side=[LABEL]))
    assert _reasons_naming_no_verdict(v) == [
        "INCOMPLETE EVIDENCE — HYGIENE_NO_VERDICT_EITHER_SIDE:" + LABEL], v.reasons
    assert v.ok is False


def test_the_subset_cannot_excuse_a_label_it_does_not_hold():
    """The bought subset is the one list here that BUYS something, so it is the
    one a wrong record could use. It must be a subset of the list it qualifies;
    otherwise a record naming any string at all could silence a reason."""
    v = _decide(hygiene=_hygiene(no_verdict_either_side=[],
                                 no_verdict_either_side_bounded=["a label "
                                                                "nothing is silent about"]))
    assert any("HYGIENE_RESULT_INVALID" in r for r in v.reasons), v.reasons
    assert v.ok is False


def test_an_excused_silence_is_still_reported_rather_than_disappearing():
    """Excused is not invisible. It must remain in the record a reader gets,
    or this trades a false refusal for a silent one."""
    v = _decide(hygiene=_hygiene(
        no_verdict_either_side=[LABEL],
        no_verdict_either_side_bounded=[LABEL]))
    assert v.debt.get("hygiene_no_verdict_bought") == [LABEL], v.debt
    assert any(LABEL in n and "uncheckable exemption" in n for n in v.notes), (
        "the note must say WHY it did not block", v.notes)
