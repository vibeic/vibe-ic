#!/usr/bin/env python3
"""A marker is a substring; the doctrine it stands for is a SECTION.

WHAT HAPPENED. `e9ec0ce1c1` ("benchmark: remove dataset-specific solve
shortcuts", 2026-08-31) rewrote
`skills/open-benchmark-methodology/SKILL.md` from 101,530 bytes to 9,654 and
trimmed two blind-instruction documents alongside it. Its stated purpose was
legitimate and it carried other work, but four separately-landed doctrines went
with it as collateral: the #724 FLOOR-proof, the #558 turn-alive refutation,
the #482 module-name source priority, the #733 section 4-E no-leak guardrail --
and, found by measuring the spread rather than by the worklist, the Category-D
FORK-FIXABLE / T5 rules of #1343.

Each was pinned, and every pin is a SUBSTRING check through
`skill_doc_section_present_check` (case-, whitespace- and blockquote-
insensitive). MEASURED with that program's own `_flat()` predicate rather than
grep -- grep compares line by line and misses a marker broken across a line,
which is how a first pass mismeasured this: every marker PASSES at the parent
`612b5a94d3` and FAILS at `e9ec0ce1c1` and at the current tip.

WHY THIS FILE EXISTS. Those pins can all be satisfied by pasting the phrases as
one run of bullets, which is exactly the failure mode
`skill_doc_section_present_check` cannot tell from a restored section -- and
the repair for a documentation trim is the one place that shortcut is most
tempting. So this asserts the SHAPE the markers are supposed to evidence: each
doctrine's markers are CO-LOCATED under a single Markdown heading, with prose
between them. A scattered marker list fails here while passing every check
above it.

It does not assert a byte count. A size floor is a number a future edit will
meet by padding, and it would fight the trim's legitimate purpose.
"""
import pathlib
import re
import sys

import pytest

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import skill_doc_section_present_check as C  # noqa: E402

SKILL = PLUGIN / "skills" / "open-benchmark-methodology" / "SKILL.md"
SHAPE_B = PLUGIN / "benchmark" / "blind_instructions_shape_b.md"
SHAPE_C = PLUGIN / "benchmark" / "blind_instructions_shape_c.md"

#: doctrine -> (document, the markers its own landed pin requires)
#: Taken from the four pins verbatim, so this file cannot come to disagree with
#: what those tests actually demand.
DOCTRINES = {
    "#724 FLOOR-proof": (
        SKILL, ["FLOOR-proof", "mutually-exclusive", "original"]),
    "#558 turn-alive refutation": (
        SKILL, ["turn alive to completion", "re-invokes", "still alive",
                "notifies the DISPATCHER"]),
    "#482 module-name source priority": (
        SKILL, ["directory-leaf", "tb-facing", "prose typo",
                "why_not_bucket_a"]),
    "#1343 Category-D FORK-FIXABLE": (
        SKILL, ["FORK-FIXABLE", "tools/vibeic-eda/FIX_STATUS.md", "asyn_fifo",
                "over-fit"]),
    "#733 section 4-E no-leak (shape B)": (
        SHAPE_B, ["unless the spec states otherwise"]),
    "#733 section 4-E no-leak (shape C)": (
        SHAPE_C, ["unless the spec states otherwise"]),
}

_HEADING = re.compile(r"^#{1,6} .+$", re.MULTILINE)


def _sections(doc: pathlib.Path):
    """(heading, body) for every Markdown section, plus the preamble."""
    text = doc.read_text(encoding="utf-8", errors="replace")
    cuts = [m.start() for m in _HEADING.finditer(text)]
    if not cuts:
        return [("(no heading)", text)]
    out = []
    if cuts[0] > 0:
        out.append(("(preamble)", text[:cuts[0]]))
    for i, start in enumerate(cuts):
        end = cuts[i + 1] if i + 1 < len(cuts) else len(text)
        chunk = text[start:end]
        out.append((chunk.splitlines()[0].strip(), chunk))
    return out


@pytest.mark.parametrize("doctrine", sorted(DOCTRINES))
def test_every_marker_of_one_doctrine_sits_in_one_section(doctrine):
    """The markers are evidence OF a section, so they must live IN one.

    Uses `skill_doc_section_present_check._flat` -- the same predicate the pins
    use -- so a marker broken across a line still counts, and this file cannot
    be stricter than the checks it is protecting.
    """
    doc, markers = DOCTRINES[doctrine]
    assert doc.is_file(), doc
    whole = C.check(doc, markers)
    assert whole["missing"] == [], (
        f"{doctrine}: the doctrine is not in {doc.name} at all — that is the "
        f"landed pin's job to report; missing {whole['missing']}")

    flat_markers = [C._flat(m) for m in markers]
    holders = []
    for heading, body in _sections(doc):
        flat_body = C._flat(body)
        if all(m in flat_body for m in flat_markers):
            holders.append(heading)
    assert holders, (
        f"{doctrine}: every marker is somewhere in {doc.name} but no SINGLE "
        f"section holds them all — the doctrine has been reduced to a marker "
        f"list, which satisfies `skill_doc_section_present_check` and teaches "
        f"a fresh author nothing. Restore the section.")


@pytest.mark.parametrize("doctrine", sorted(DOCTRINES))
def test_the_section_holding_a_doctrine_has_prose_around_its_markers(doctrine):
    """A heading plus the four phrases is still a marker list.

    The bar is deliberately low and structural: the holding section must carry
    at least three lines that SAY SOMETHING BESIDES a marker — measured by
    deleting every marker from the line and requiring four words to survive.

    MEASURED WHILE WRITING THIS, and it is why the rule is worded that way. The
    first version compared a stripped line to a marker for EQUALITY, and the
    hazard arm — main's documents with every marker pasted as one run of
    bullets under a `## Doctrine markers` heading — went 12 PASSED: `- FLOOR-
    proof` is not equal to `floor-proof`, so each bullet counted as prose. A
    control that does not bite the arm it was written for proves nothing, so
    list bullets are stripped and the test is what remains.
    """
    doc, markers = DOCTRINES[doctrine]
    flat_markers = [C._flat(m) for m in markers]

    def _says_something_else(line):
        body = re.sub(r"^\s*(?:[-*+]|\d+[.)]|>)\s*", "", line)
        body = C._flat(body)
        for m in flat_markers:
            body = body.replace(m, " ")
        return len(re.findall(r"[a-z0-9][a-z0-9'/_.-]*", body)) >= 4

    best = None
    for heading, body in _sections(doc):
        if all(m in C._flat(body) for m in flat_markers):
            carrier = [ln for ln in body.splitlines()[1:]
                       if ln.strip() and _says_something_else(ln)]
            if best is None or len(carrier) > best[1]:
                best = (heading, len(carrier))
    assert best is not None, f"{doctrine}: no holding section (see the test above)"
    heading, n = best
    assert n >= 3, (
        f"{doctrine}: the section {heading!r} carries {n} line(s) that say "
        f"anything besides a marker — that is a checklist, not the doctrine.")
