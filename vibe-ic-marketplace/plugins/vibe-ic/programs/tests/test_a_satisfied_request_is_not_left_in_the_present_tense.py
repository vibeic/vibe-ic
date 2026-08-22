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
must actually STAMP (that is a positive control on the fix itself, and it goes
red if anyone removes a stamp), and each document must still carry the marker
text this test is scoped to. Only then is the absence of the stale claim
allowed to mean anything.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
RUNNER = (Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py")
GENERATOR = REPO / "ppa-e2e" / "tools" / "gen_result_md.py"
RESULT_MD = REPO / "ppa-e2e" / "RESULT.md"
FINDINGS_MD = REPO / "ppa-e2e" / "FINDINGS.md"

#: These are required shipped artefacts.  There is deliberately no skip for a
#: checkout that lacks one: the tests below must fail when their subject is
#: absent, renamed, or unreadable rather than turning missing evidence into a
#: non-blocking result.

#: The sign-off STA emitters the satisfied request named. Every one of them must
#: write a basis stamp; this list is the reason the request is satisfied.
_EMITTERS = ("_emit_spef_sta", "_emit_corner_spef_sta", "_emit_mcorner_ocv_sta")

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


def _emitter_sources() -> dict:
    """Each named emitter's own source segment, by AST rather than by line math.

    A regex over the whole 41k-line runner would find a stamp written by some
    OTHER function and call this one stamped, which is the vacuous pass this
    test exists to refuse.
    """
    text = RUNNER.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _EMITTERS:
            out[node.name] = ast.get_source_segment(text, node) or ""
    return out


# ------------------------------------------------------- NON-VACUITY FIRST ---
def test_the_three_named_emitters_still_exist_in_the_runner():
    """If they were renamed, every assertion below would be about nothing."""
    found = _emitter_sources()
    missing = [n for n in _EMITTERS if n not in found]
    assert not missing, (
        f"emitter(s) {missing} are no longer module-level functions of "
        f"{RUNNER.name}; this guard's subject moved and the guard must move "
        f"with it rather than quietly passing")


def test_every_signoff_sta_emitter_writes_a_basis_stamp():
    """The POSITIVE CONTROL, and the fact that makes the request satisfied.

    Goes RED if anyone removes a stamp -- at which point the request in
    `RESULT.md` becomes live again and this file's other assertions are the
    wrong ones to be making.
    """
    for name, src in sorted(_emitter_sources().items()):
        assert "STA_BASIS: " in src, (
            f"{name} no longer writes a `STA_BASIS:` line. The satisfied "
            f"request in ppa-e2e/RESULT.md (#1, F-6) is live again: sign-off "
            f"timing rows will come back as `stage=null` and the canonical "
            f"index will refuse them SCOPE_INCOMPLETE")


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
def test_no_campaign_document_claims_the_emitters_stamp_nothing(doc: Path):
    """The rule, and it only means anything because of the two tests above."""
    body = doc.read_text(encoding="utf-8", errors="replace")
    for pattern in _STALE:
        hit = re.search(pattern, body, re.IGNORECASE)
        assert hit is None, (
            f"{doc.name} states, in the present tense, that the sign-off STA "
            f"emitters do not stamp: {hit.group(0)!r}. They do -- "
            f"{', '.join(_EMITTERS)} each write a `STA_BASIS:` line, since "
            f"{_COMMIT}. Mark the request SATISFIED and keep it; do not delete "
            f"it, and do not leave it in the present tense")


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


def test_the_generator_and_its_committed_output_do_not_drift():
    """`RESULT.md` is `gen_result_md.py`'s output and NOTHING re-derives it.

    The generator hard-codes a run tree that no longer exists, so it cannot be
    run to check. Two copies of one fact that can disagree is the defect this
    whole lane is about, so the marking is asserted to be identical in both.
    """
    gen = GENERATOR.read_text(encoding="utf-8", errors="replace")
    out = RESULT_MD.read_text(encoding="utf-8", errors="replace")
    for probe in (f"**SATISFIED by `{_COMMIT}` (v1.11.57, 2026-08-21)**",
                  "The first LIVE request in this list is #3."):
        assert gen.count(probe) == out.count(probe) >= 1, (
            f"gen_result_md.py and RESULT.md disagree about {probe!r} "
            f"(generator {gen.count(probe)}, output {out.count(probe)}); the "
            f"generator cannot be re-run to settle it, so they are kept in "
            f"step by hand and this is what notices when they are not")
