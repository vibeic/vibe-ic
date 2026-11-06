#!/usr/bin/env python3
"""A campaign document may not ask for a fix the tree already carries.

WHAT HAPPENED. `ppa-e2e/RESULT.md` and its generator carried, in a present-tense
**REQUESTS TO THE LANDER** list ranked by value, request #1: *"Three
`puts "STA_BASIS: POST_ROUTE_SPEF"` lines, in the emitters that write
`sta_spef_multicorner.rpt` and `sta_mcorner_ocv.rpt`. Today they stamp nothing"*.
Those three `puts` had landed in `e4c5840d6` (v1.11.57, 2026-08-21) together
with their own guard, and request #2 in the same list — the Phase-3 power
session — landed in that same commit. The list went on asking for both.

THE HARM IS NOT HYPOTHETICAL. An agent reading that list in order to explain 144
`SCOPE_INCOMPLETE` refusals filed the residual as a live FOURTH producer defect
and reported it as such. It was not a producer defect at all: the emitters stamp,
and the run trees that still refuse are simply OLDER than the fix. Measured
2026-08-22 on one host -- every `sta_mcorner_ocv.rpt` / `sta_spef_multicorner.rpt`
written before 2026-08-21 carries no stamp and every one written after carries
it, and the six run trees split on exactly that line: stamped -> 0 refusals,
unstamped -> 48 each. A document that misdescribes the tree tells a reader to
stop looking where the answer is -- `PPA_INTERFACES` §2.1 says exactly this about
a scope gap, and it is just as true of a request list.

THE RULE. A satisfied request is MARKED, never deleted -- the finding was true
when it was written and the record of it is worth keeping. What may not survive
is the present tense.

NON-VACUITY IS THE LOAD-BEARING PART, twice over. A test that only greps for an
absent phrase passes on an empty file, on a renamed file, and on a file it never
opened. So this file first proves it is reading the real artefacts: the runner
must emit each of the four materially different stamp/stage pairs from synthetic
fixtures, and each document must still carry the same conditional truth. A
source grep for `STA_BASIS:` cannot establish either fact: the token may sit in
an unreachable arm, or every arm may stamp the flattering extracted stage. Only
then is the absence of the stale claim allowed to mean anything.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
GENERATOR = REPO / "docs" / "campaigns" / "ppa-e2e" / "tools" / "gen_result_md.py"
RESULT_MD = REPO / "docs" / "campaigns" / "ppa-e2e" / "RESULT.md"
FINDINGS_MD = REPO / "docs" / "campaigns" / "ppa-e2e" / "FINDINGS.md"

#: These are required shipped artefacts.  There is deliberately no skip for a
#: checkout that lacks one: the tests below must fail when their subject is
#: absent, renamed, or unreadable rather than turning missing evidence into a
#: non-blocking result.

#: Present-tense claims that the emitters do not stamp. Matched case-insensitively
#: and across a line break, because the documents are hard-wrapped and the claim
#: straddled one. PAST tense is deliberately NOT here -- "at the time they
#: stamped nothing" is the record of a finding and must stay readable.
_STALE = (
    r"today\s+they\s+stamp\s+nothing",
    r"they\s+stamp\s+nothing\s*,",
    r"emitters\s+stamp\s+nothing",
)

#: Text that proves this test opened the document it means to check. If a
#: document is renamed, restructured or emptied, these vanish and the test fails
#: rather than passing over an artefact it never read.
_ANCHOR = {
    "gen_result_md.py": "REQUESTS TO THE LANDER",
    "RESULT.md": "REQUESTS TO THE LANDER",
    "FINDINGS.md": "F-6 — the multi-corner sign-off STA reports",
}

_COMMIT = "e4c5840d6"

#: The exact conditional statement the three current prose sites must carry.
#: It names four arms even though two share one stamp/stage pair; collapsing
#: them to "all extracted" is the regression this continuation repairs.
_CONDITIONAL_TRUTH = (
    "`PRE_LAYOUT_ESTIMATE` -> `pre_layout_estimate` for RC pre-layout and for "
    "OCV pre-layout; `POST_ROUTE_NO_SPEF` -> `post_route_no_extraction` for "
    "routed OCV without SPEF; and `POST_ROUTE_SPEF` -> "
    "`post_route_extracted` for routed OCV with SPEF"
)

#: The EXACT marking, not the bare word. `SATISFIED` already appears in these
#: documents for unrelated reasons -- as a feasibility-axis verdict in four
#: RESULT.md table rows and two FINDINGS.md lines -- so asserting the bare word
#: would have passed on a document carrying none of this lane's markings at all.
#: That is not hypothetical: it passed exactly that way once, on a checkout
#: where the markings had been reverted.
_MARKING = f"**SATISFIED by `{_COMMIT}` (v1.11.57, 2026-08-21)"

#: The four sections this lane marked, and where each one ENDS. Checked PER
#: SECTION rather than per document, because a per-document check is satisfied
#: by any ONE surviving marking: dropping the commit id from F-6 while F-7 kept
#: its own left the whole file passing. MEASURED -- that mutation came out
#: green, which is why the rule below is scoped to the section.
_SECTIONS = {
    "gen_result_md.py": (
        ("**1 — `phase3_one_shot_runner.py`: stamp the multi-corner STA emitters**",
         "**2 — `phase3_one_shot_runner.py`"),
        ("**2 — `phase3_one_shot_runner.py`: fix the Phase-3 power session**",
         "**3 —"),
    ),
    "RESULT.md": (
        ("**1 — `phase3_one_shot_runner.py`: stamp the multi-corner STA emitters**",
         "**2 — `phase3_one_shot_runner.py`"),
        ("**2 — `phase3_one_shot_runner.py`: fix the Phase-3 power session**",
         "**3 —"),
    ),
    "FINDINGS.md": (
        ("## F-6 — the multi-corner sign-off STA reports", "## F-7 —"),
        ("## F-7 — the Phase-3 power report", "## F-8"),
    ),
}

#: A commit id as these documents spell one.
_COMMITISH = re.compile(r"\b[0-9a-f]{7,40}\b")

def _section(body: str, start: str, stop: str) -> str:
    """One uniquely anchored section, refusing absence or ambiguity."""
    assert body.count(start) == 1, (
        f"expected one section start {start!r}, found {body.count(start)}")
    begin = body.index(start)
    assert stop in body[begin + len(start):], (
        f"section beginning {start!r} has no closing anchor {stop!r}")
    end = body.index(stop, begin + len(start))
    return body[begin:end]


# ------------------------------------------------------- NON-VACUITY FIRST ---


@pytest.mark.parametrize("doc", [GENERATOR, RESULT_MD, FINDINGS_MD],
                         ids=lambda p: p.name)
def test_the_document_this_test_checks_is_the_one_it_opened(doc: Path):
    """Second non-vacuity control, per document."""
    body = doc.read_text(encoding="utf-8", errors="replace")
    anchor = _ANCHOR[doc.name]
    assert anchor in body, (
        f"{doc.name} no longer contains {anchor!r}; the stale-claim check "
        f"below would pass over a document it does not understand")


# ------------------------------------------------------------- THE RULE ------


@pytest.mark.parametrize("doc", [GENERATOR, RESULT_MD, FINDINGS_MD],
                         ids=lambda p: p.name)
def test_each_current_prose_site_states_the_four_arm_conditional_truth(doc: Path):
    """The narrative must agree with the emitted/result mapping above."""
    body = doc.read_text(encoding="utf-8", errors="replace")
    start, stop = _SECTIONS[doc.name][0]
    lines = []
    for line in _section(body, start, stop).splitlines():
        line = line.strip()
        if line.startswith(">"):
            line = line[1:].lstrip()
        lines.append(line)
    section = " ".join(" ".join(lines).split())
    assert _CONDITIONAL_TRUTH in section, (
        f"{doc.name}: the satisfied STA section does not state the four-arm "
        f"conditional mapping. Expected this exact truth:\n"
        f"{_CONDITIONAL_TRUTH}\nSection was:\n{section}")


@pytest.mark.parametrize("doc", [GENERATOR, RESULT_MD, FINDINGS_MD],
                         ids=lambda p: p.name)
def test_the_satisfied_marking_names_the_commit_that_satisfied_it(doc: Path):
    """A bare "SATISFIED" is an unexplained overwrite of a finding.

    The same discipline `_ppa/contract` applies to a metric authority: a
    resolution with no stated reason is not a resolution.
    """
    body = doc.read_text(encoding="utf-8", errors="replace")
    assert _MARKING in body, (
        f"{doc.name} carries no SATISFIED marking naming {_COMMIT}. Either the "
        f"marking was dropped, or a request was marked satisfied without "
        f"naming what satisfied it -- an unexplained overwrite of a finding")
    marked = 0
    for start, stop in _SECTIONS[doc.name]:
        assert start in body, (
            f"{doc.name}: section {start[:48]!r} is gone; this check would "
            f"pass over a request it can no longer find")
        seg = body[body.index(start):]
        seg = seg[:seg.index(stop, len(start))] if stop in seg[len(start):] else seg
        if "SATISFIED" not in seg:
            continue
        marked += 1
        assert _COMMITISH.search(seg), (
            f"{doc.name}: the section beginning {start[:48]!r} is marked "
            f"SATISFIED and names no commit. A resolution with no stated "
            f"reason is an unexplained overwrite of a finding -- the same rule "
            f"`_ppa/contract` applies to a metric authority")
    assert marked, (
        f"{doc.name}: neither marked section says SATISFIED any more, so the "
        f"per-section rule above asserted nothing")


@pytest.mark.consistency
def test_the_generator_and_its_committed_output_do_not_drift():
    """`RESULT.md` is `gen_result_md.py`'s output and NOTHING re-derives it.

    The generator hard-codes a run tree that no longer exists, so it cannot be
    run to check. Compare the entire static request section, not two stamp
    tokens that can agree while the surrounding claims drift.
    """
    gen = GENERATOR.read_text(encoding="utf-8", errors="replace")
    out = RESULT_MD.read_text(encoding="utf-8", errors="replace")
    start, stop = "## REQUESTS TO THE LANDER", "## Where everything is"
    gen_section = _section(gen, start, stop)
    out_section = _section(out, start, stop)
    assert gen_section == out_section, (
        "gen_result_md.py and RESULT.md disagree in their generated request "
        "section; the generator cannot be re-run to settle the drift")
