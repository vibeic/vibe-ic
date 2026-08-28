#!/usr/bin/env python3
"""One quantity, two numbers, one page — and nothing reads both.

THIS GATE BLOCKS (rc=1) when a page states the same named quantity twice with
different values.

WHY THIS EXISTS
===============
MEASURED on the published PPA review, 2026-08-28, while re-deriving its figures
against the tree. The page's headline metric cards and its VERIFICATION RECEIPT
state the SAME closed-loop census, and they disagreed:

    headline cards   DECLARED_ONLY 18 | EXECUTABLE 0 | REMEASURED 1 | ROLLBACK_PROVEN 2
    receipt          DECLARED_ONLY 18 | EXECUTABLE 0 | REMEASURED 3 | ROLLBACK_PROVEN 0

The cards had been updated when the tiers moved; the receipt had not. The
receipt is the half a reader trusts MOST — it is headed "what this review
actually ran" and it names a pinned commit — so the stale half was the
authoritative-looking half. The same page carried `1,290` in one sentence and
`1300` in a metric card for the same population.

Neither half was checkable against the other, because nothing read both. Every
existing guard on that page reads a sentence against an EXTERNAL artefact:
`ppa_page_claim_check` compares claim language to a claims document,
`derived_corpus_figure_check` compares a docstring's funnel to what a program
derives. A page can satisfy both while contradicting itself, because the
contradiction lives entirely inside the page.

THE RULE
========
Extract every (quantity, value) the page states, in the two shapes a page
states them: the number/label pair of a metric card, and `NAME=VALUE` /
`NAME: VALUE` in prose and receipts. Group by the normalised quantity name.
A quantity stated with two different values is reported with both sites.

A QUANTITY IS COMPARED ONLY IF THE PAGE PUTS IT ON A CARD. That restriction is
not a convenience; without it the prose channel says yes to everything.
MEASURED over the 19 published pages: with prose compared to prose, one page
returned three findings and ALL THREE were the rule's own blind spot —

    MAXEDGES=2 ... MAXEDGES=15   two settings of one knob in a NEG/POS
                                 experiment, deliberately contrasted
    met1.PIN=1/2 -> met1.PIN=68/16   GDS layer/datatype pairs, stock vs fixed
    README:30-43 ... README:48-51    line ranges in two file citations

None of the three is a page contradicting itself. A card is the page's own
declaration that a name is a published FIGURE, and comparing prose to a
declared figure is the shape the measured defect actually had: a headline card
against a receipt sentence.

It does NOT decide which value is right — that requires the producer, and this
program deliberately does not have one. It reports that the page cannot be read
without deciding, which is the state a reader should never be left in.

WHERE IT IS NOT WIRED, AND WHY THAT IS THE HONEST ANSWER
========================================================
This rule has NO subject in this repository, and that is stated rather than
worked around. MEASURED: the generated `ppa-e2e/report/winner/report.md` and
`docs/PPA_CURRENT_STATE.md` both declare zero figures on a metric card, so both
return rc 2. The pages the defect was measured on live in the site repository.

Declaring it in the hygiene lane anyway would make it exit 2 on every run —
a red that only means "nothing was there", which is precisely the state
`gate_red_is_more_than_absence_census` was written to separate out. Wiring it
here to look wired would be committing the defect this campaign just shipped a
census against. It is therefore routed via `benchmark/CAPTURE_ROUTING.json` and
run against a page by whoever publishes one, until a page lands in-tree.

WHAT IT DOES NOT CATCH
======================
A figure stated once and wrong. That is `derived_corpus_figure_check`'s
question for a docstring and the `<!--figure:...-->` anchors' question for
in-repo markdown — and neither reaches a page after it is published, which is
where a reader acts on it.
"""
from __future__ import annotations

import argparse
import collections
import html
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: `NAME=VALUE` and `NAME: VALUE`, where NAME is a CONSTANT-shaped identifier.
#: Constant-shaped on purpose: `REMEASURED=3` names a quantity, `width=8` in a
#: code sample names a parameter of that sample. Requiring the upper-case
#: convention keeps the population to figures a page is asserting.
#: The trailing guard rejects `1/2` (a layer/datatype pair), `30-43` (a line
#: range) and `2.5` — none of them a count, all of them measured on a real page.
#: A DIGIT after the separator is required. Without it the guard also rejected
#: `ROLLBACK_PROVEN=0.` at the end of a sentence, reading the full stop as a
#: decimal point and silently dropping the very statement this rule exists to
#: catch — a guard that removed a true positive while passing its own
#: false-positive tests.
_KV_RE = re.compile(
    r"\b([A-Z][A-Z0-9_]{2,})\s*[=:]\s*([0-9][0-9,]*)(?![0-9,]*[/\-.][0-9])\b")

#: A metric card: a number in one element, its label in the very next one.
#:
#: TABLE CELLS ARE EXCLUDED, and that exclusion is the whole precision of this
#: rule. MEASURED on the same page: a layers table pairs an EDGE LIST cell,
#: `8->7 . 9->1 . 10->7 . 13->9 . 14->9`, with a STATUS cell, `DECLARED_ONLY`.
#: Read as a card that is "DECLARED_ONLY = 9", and the rule then reports the
#: real card (18) as disagreeing with a row that states no count at all. A
#: `<td>` next to a `<td>` is a row, and a status in a row is a status.
_CARD_RE = re.compile(
    r"([0-9][0-9,]*)\s*</(?!td\b|th\b)[a-z]+>\s*<(?!td\b|th\b)[a-z][^>]*>\s*"
    r"([A-Z][A-Z0-9_ ]{2,}?)\s*<")

_TAG_RE = re.compile(r"<[^>]+>")
_BILINGUAL_RE = re.compile(r'\sdata-(?:en|zh|title-en|title-zh)="(?:[^"\\]|\\.)*"')


def _visible(raw: str) -> str:
    """The page as a reader sees it: markup dropped, entities resolved.

    The bilingual `data-en`/`data-zh` attributes are stripped FIRST. They carry
    a full copy of every sentence, so leaving them in would make the page state
    each of its own figures three times and turn every agreement into a triple.
    """
    text = _BILINGUAL_RE.sub("", raw)
    text = _TAG_RE.sub(" ", text)
    return html.unescape(text)


def _norm(name: str) -> str:
    return re.sub(r"[\s_]+", "_", name.strip()).upper()


def _value(raw: str) -> str:
    return raw.replace(",", "")


def statements(raw: str) -> List[Tuple[str, str, str]]:
    """Every `(quantity, value, how)` this page states about a declared figure."""
    out: List[Tuple[str, str, str]] = []
    declared = set()
    for m in _CARD_RE.finditer(raw):
        name = _norm(m.group(2))
        declared.add(name)
        out.append((name, _value(m.group(1)), "metric card"))
    for m in _KV_RE.finditer(_visible(raw)):
        name = _norm(m.group(1))
        if name in declared:
            out.append((name, _value(m.group(2)), "stated in prose"))
    return out


def audit(raw: str) -> dict:
    by_name: Dict[str, List[Tuple[str, str]]] = collections.defaultdict(list)
    for name, value, how in statements(raw):
        by_name[name].append((value, how))

    conflicts = []
    for name, seen in sorted(by_name.items()):
        values = {v for v, _ in seen}
        if len(values) > 1:
            conflicts.append({
                "quantity": name,
                "values": sorted(values),
                "sites": [{"value": v, "how": h} for v, h in seen],
            })
    return {
        "quantities_stated": len(by_name),
        "statements": sum(len(v) for v in by_name.values()),
        "conflicts": conflicts,
    }


#: THE PROOF BEHIND THIS PROGRAM'S `unwired_by_decision` ENTRY.
#:
#: The docstring above states that this rule has no subject in this repository
#: and is therefore deliberately not machine-wired. That sentence is a
#: MEASUREMENT, and a measurement nothing re-derives decays into a waiver — so
#: `checker_execution_wiring_audit` re-derives it every run by calling this
#: function and requiring 0. The day a page carrying a metric card lands in
#: this tree, the count stops being 0, the disclosure stops being true, and
#: that audit goes RED naming this entry. That is the whole difference between
#: a disclosure and permission.
#:
#: A CARD, not a page: `_CARD_RE` is the same predicate `statements()` uses to
#: decide a quantity is a declared figure, so the probe and the rule cannot
#: disagree about what a subject is. Reusing it is the point — a probe with its
#: own copy of the pattern would go on returning 0 after the rule's pattern
#: changed.
def subject_count(root, globs=("**/*.md", "**/*.html", "**/*.htm")) -> int:
    """How many pages under `root` declare at least one metric card.

    0 means this rule HAS NO SUBJECT here — not that it passed. `.git/` is
    skipped because a packfile is not a published page, and an unreadable file
    is counted as no subject rather than raising: a probe that can crash is a
    probe that can take the audit down with it.
    """
    root = Path(root)
    seen, n = set(), 0
    for g in globs:
        for f in root.glob(g):
            if ".git/" in str(f) or not f.is_file() or f in seen:
                continue
            seen.add(f)
            try:
                if _CARD_RE.search(f.read_text(errors="replace")):
                    n += 1
            except OSError:
                continue
    return n


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("page", help="the published page (HTML or Markdown)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.page)
    if not path.is_file():
        print(f"CANNOT CHECK: no page at {path}", file=sys.stderr)
        return 2

    report = audit(path.read_text(encoding="utf-8", errors="ignore"))
    if report["quantities_stated"] == 0:
        print(f"CANNOT CHECK: {path} declares no figure on a metric card, so "
              f"this rule has nothing to compare prose against. A verdict over "
              f"an empty set is NOT a pass.", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['statements']} statement(s) of "
              f"{report['quantities_stated']} named quantity(ies) in {path.name}")
        for c in report["conflicts"]:
            sites = "; ".join(f"{s['value']} ({s['how']})" for s in c["sites"])
            print(f"  [DISAGREES] {c['quantity']}: {sites} — the page cannot be "
                  f"read without deciding which is current")
        print("PASS" if not report["conflicts"]
              else f"FAIL: {len(report['conflicts'])} quantity(ies) stated twice, differently")

    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
