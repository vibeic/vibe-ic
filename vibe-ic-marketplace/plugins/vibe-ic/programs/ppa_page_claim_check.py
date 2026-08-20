#!/usr/bin/env python3
"""Refuse a public sentence that claims more than the artefact behind it supports.

Spec §3.3 (P0, forbidden unqualified forms), §18.1 (claim language rules).
Interface contract: `docs/PPA_INTERFACES.md` §1 (exit codes), §5 (schemas).

WHY A PROGRAM AND NOT A STYLE GUIDE
===================================
This gate exists because of a measurement, not a preference. On 2026-08-21 the
published PPA page carried these three sentences, each stated in the present
tense:

    "it does not measure area at all"
    "no step even declares an area metric"
    "Step 33 measures total power and feeds it to nothing"

They were true when they were written. One landing later they were false: step 9
gained an area `closed_loop` and an `area_total_vs_budget_check` gate, and step
33 gained a power `closed_loop` and a `power_total_vs_budget_check` gate. The
page was not edited, and nothing was wrong with the author. What was wrong is
that the sentences were unfalsifiable-by-construction: they named no revision, so
no later measurement could ever be compared against them, so nothing could go red
when the tree moved underneath them.

The other shape on the same page is worse because no landing can ever disprove
it: "This axis genuinely converges." `genuinely` states no criterion. There is no
experiment whose outcome would contradict that sentence, which means it is not a
claim about silicon at all — it is a claim about the author's confidence.

So the fix is mechanical and it is a program: a banned form is refused UNLESS the
sentence carrying it also carries a citation `[claim:<id>]` that resolves to a
claim which supplies the specific missing qualification — a pinned base, a stated
review scope, a stated criterion, or a definition of the term the sentence leans
on. Prose cannot be re-read every landing. A citation can be re-run every landing.

THE TWO DIRECTIONS THIS GATE CHECKS
===================================
  page -> claims   a banned form must be qualified by a resolvable claim, and a
                   citation must resolve at all
  claims -> evidence
                   a claim's status may never be STRONGER than the weakest
                   evidence record it cites, and a claim that cites nothing is
                   an assertion (with one exception, below)

The exception is exact and it is the point of the whole lane: a `NOT_MEASURED`
claim legitimately cites no evidence, because the absence of the artefact IS the
fact being reported. That row must be PRINTED, never dropped — a report that
omits what it could not measure reads as complete, and it reads that way to its
author first.

"I COULD NOT READ IT" IS NOT "I READ IT AND IT WAS CLEAN"
=========================================================
Every way this gate fails to see its input is rc=2 with a printed marker and its
own code, never rc=0 and never rc=1:

    [CANNOT CHECK] PAGE_MISSING / PAGE_UNREADABLE / EMPTY_PAGE
    [CANNOT CHECK] CLAIMS_MISSING / CLAIMS_UNREADABLE / CLAIMS_NOT_A_CLAIMS_DOC

rc=1 is reserved for a finding — a sentence that outruns its evidence — because
rc=1 in this family of programs is a claim about silicon (PPA_INTERFACES.md §1).

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: the banned forms are statements
about a FLOW and about the language of a claim. No design, PDK, process, vendor
or part literal appears in the logic or can affect it.
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

CLAIMS_SCHEMA = "vibeic.ppa.claims.v1"

#: How strong a status is. A claim may never be STRONGER than its weakest cited
#: evidence record. NOT_MEASURED is not "weak MEASURED" — it is a different kind
#: of statement — so it sits at the bottom and nothing can be promoted past a
#: record that carries it.
STATUS_STRENGTH: Dict[str, int] = {
    "MEASURED": 4,
    "DERIVED": 3,
    "ESTIMATED": 2,
    "NOT_APPLICABLE": 1,
    "INVALID": 0,
    "NOT_MEASURED": 0,
}

#: A claim carrying one of these fields is refused for carrying it: a single
#: combined figure is a proxy for the PPA property and not the property, and it
#: is the figure a reader quotes. Same list the head-to-head gate refuses.
COLLAPSED_SCALAR_FIELDS = ("score", "ppa_score", "overall", "figure_of_merit",
                           "fom", "composite", "weighted_score", "qor_score")

#: What lifts a banned form. Each value is the SPECIFIC missing qualification,
#: not "write more carefully" — a rule a future author has to remember is a rule
#: that stops running the week they leave.
#:
#:   NEVER              nothing lifts it; the sentence states no criterion and no
#:                      measurement could ever contradict it. Rewrite it.
#:   base_pin           claim.scope.base — the revision the statement was
#:                      measured AT. Without it a statement about the tree reads
#:                      present-tense and goes false with no edit.
#:   review_scope       claim.scope.reviewed — what was actually searched, and
#:                      when. This is what turns an unbounded universal negative
#:                      into a bounded, checkable search.
#:   criterion          claim.criterion — the falsifiable test the sentence would
#:                      fail. "converges", "honest" and "nothing violates" are
#:                      not criteria until one is written down.
#:   definition:<term>  claim.definitions[<term>] — the word the sentence leans
#:                      on, defined, so a reader is not supplying it themselves.
REQUIREMENT_NEVER = "NEVER"

#: The list is spec §3.3's, verbatim. Every entry was measured live on the
#: published page on 2026-08-21 — all eight forms were present — so this is a
#: real corpus and not a hypothetical one.
BANNED_FORMS: Tuple[Dict[str, str], ...] = (
    {
        "code": "GENUINELY_CONVERGES",
        "pattern": r"this axis genuinely converges",
        "requires": REQUIREMENT_NEVER,
        "why": ("`genuinely` states no criterion, so no measurement can ever "
                "contradict this sentence. It is a claim about confidence, not "
                "about silicon. State what converged, to what, measured how."),
    },
    {
        "code": "UNTIL_NOTHING_VIOLATES",
        "pattern": r"until nothing violates",
        "requires": "criterion",
        "why": ("`nothing violates` is unbounded: it does not say which rule "
                "set, over which cells, at which corner. Name the checks and "
                "the population, or the sentence cannot be falsified."),
    },
    {
        "code": "FEEDS_IT_TO_NOTHING",
        "pattern": r"feeds it to nothing",
        "requires": "base_pin",
        "why": ("a statement about what the flow does today is false tomorrow "
                "without anyone editing it. MEASURED: this exact sentence was "
                "disproved one day after publication when step 33 gained a "
                "power closed_loop and a budget gate."),
    },
    {
        "code": "DOES_NOT_MEASURE_AREA",
        "pattern": r"does not measure area at all",
        "requires": "base_pin",
        "why": ("same shape, same landing: step 9 declares an area output, "
                "gates on an area budget and carries an area closed_loop. "
                "Pin the revision the claim was measured at."),
    },
    {
        "code": "REAL_FALLBACK_EDGE",
        "pattern": r"real fallback edge",
        "requires": "definition:executable",
        "why": ("`real` is doing the work of a definition. A fallback edge is "
                "real when something EXECUTES it; define `executable` and the "
                "sentence becomes checkable."),
    },
    {
        "code": "ANTI_CHEATING_VERBATIM",
        "pattern": r"keep the two anti-cheating terms verbatim",
        "requires": "criterion",
        "why": ("this asserts the score cannot be gamed. That is a testable "
                "claim and it needs the test: state what gaming was attempted "
                "and what the terms did to it."),
    },
    {
        "code": "UNBOUNDED_NOBODY",
        "pattern": r"\bnobody\b",
        "requires": "review_scope",
        "why": ("an unbounded universal negative about everyone else's work. "
                "State what was reviewed and when; the bounded version is both "
                "honest and stronger."),
    },
    {
        "code": "UNBOUNDED_NO_OPEN_FLOW",
        "pattern": r"no open flow\b",
        "requires": "review_scope",
        "why": ("same shape as `nobody`: it claims a search of every open flow "
                "in existence. Name the flows and versions actually examined."),
    },
    {
        "code": "SEARCH_STAYS_HONEST",
        # Spec §3.3 writes this as one entry with an ellipsis
        # ("every rewrite is checked ... so the search stays honest") because
        # the two fragments make ONE claim. Either fragment alone carries the
        # same implication, so either fragment alone trips the gate.
        "pattern": r"every rewrite is checked|so the search stays honest",
        "requires": "criterion",
        "why": ("`every` is a coverage claim and `honest` is a property claim, "
                "and neither says how it was checked. State the gate set and "
                "the evidence that it ran on every rewrite, not on the ones "
                "that reached it."),
    },
)

CITATION_RE = re.compile(r"\[claim:([A-Za-z0-9][A-Za-z0-9._-]*)\]")
_TAG_RE = re.compile(r"<[^>]+>")
_DROP_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


# --------------------------------------------------------------------------
# reading the page
# --------------------------------------------------------------------------

def page_text(raw: str) -> str:
    """Rendered text — what a reader actually meets.

    A banned sentence broken across `<span>`s is the same sentence to a reader
    and must be the same sentence to this gate, so markup is removed rather than
    matched around. `<script>` and `<style>` bodies are dropped entirely: they
    are not prose, and a phrase inside a CSS selector is not a claim.
    """
    text = _DROP_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    text = _WS_RE.sub(" ", text)
    return text


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_BLANK_LINE_RE = re.compile(r"\n\s*\n")


def _unwrap(text: str) -> str:
    """Join soft line breaks inside a block; keep blank lines and fences.

    MEASURED, and it is why this function exists rather than splitting on every
    newline: a hard-wrapped sentence carries its `[claim:<id>]` on whichever
    line it happened to fall on. Splitting per line put the number in one unit
    and its citation in the next, and `--cite-numbers` reported seven findings
    against a page whose every number WAS cited. A checker that punishes the
    line-wrap width is a checker nobody can satisfy, and one nobody can satisfy
    is one that gets turned off.

    Lines inside a fenced block are never joined: their line structure is the
    content, and joining them would also lose the fence markers the number
    check uses to skip them.
    """
    out: List[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("\n" + line.strip() + "\n")
            continue
        if in_fence:
            out.append("\n" + line + "\n")
            continue
        if not line.strip():
            out.append("\n\n")
            continue
        out.append(line.strip() + " ")
    return "".join(out)


def sentences(text: str) -> List[str]:
    """Sentence-ish units: a block, split at sentence terminators.

    A unit is bounded by a blank line or a terminator, never by the width the
    author happened to wrap at. Deliberately crude in the direction that keeps
    a citation WITH the sentence it qualifies: a unit that is too small produces
    findings against correctly-cited prose, which is the failure that gets a
    gate switched off. A unit that is too large could let a neighbouring
    citation qualify a banned form — bounded here by the blank line, which in
    both Markdown and rendered HTML is where a new thought starts.
    """
    units: List[str] = []
    for block in _BLANK_LINE_RE.split(_unwrap(text)):
        for unit in _SENTENCE_SPLIT_RE.split(block):
            if unit.strip():
                units.append(unit.strip())
    return units


# --------------------------------------------------------------------------
# reading the claims
# --------------------------------------------------------------------------

def load_claims(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, str]]]:
    """Returns (doc, undetermined). Exactly one is None."""
    if not path.exists():
        return None, {"code": "CLAIMS_MISSING",
                      "detail": (f"{path} does not exist. Without it no "
                                 f"citation on the page can be resolved, so "
                                 f"this run checked nothing.")}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, {"code": "CLAIMS_UNREADABLE",
                      "detail": f"{path}: {type(exc).__name__}: {exc}"}
    if not isinstance(doc, dict) or doc.get("schema") != CLAIMS_SCHEMA:
        got = doc.get("schema") if isinstance(doc, dict) else type(doc).__name__
        return None, {"code": "CLAIMS_NOT_A_CLAIMS_DOC",
                      "detail": (f"{path}: schema is {got!r}, expected "
                                 f"{CLAIMS_SCHEMA!r}. A document this gate "
                                 f"cannot identify is not a document it may "
                                 f"report clean over.")}
    if not isinstance(doc.get("claims"), list):
        return None, {"code": "CLAIMS_NOT_A_CLAIMS_DOC",
                      "detail": f"{path}: `claims` is not a list"}
    return doc, None


def index_claims(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {c["id"]: c for c in doc["claims"]
            if isinstance(c, dict) and isinstance(c.get("id"), str)}


# --------------------------------------------------------------------------
# the two checks
# --------------------------------------------------------------------------

def _qualification_present(claim: Dict[str, Any], requires: str) -> bool:
    """Does this claim supply the SPECIFIC qualification the form is missing?

    Non-empty after stripping, in every case: an empty string is a field that
    was added to satisfy the gate rather than to inform a reader, and a gate
    that accepts it is a gate that taught someone to defeat it.
    """
    if requires == REQUIREMENT_NEVER:
        return False
    if requires.startswith("definition:"):
        term = requires.split(":", 1)[1]
        defs = claim.get("definitions")
        return isinstance(defs, dict) and bool(str(defs.get(term, "")).strip())
    if requires in ("base_pin", "review_scope"):
        key = "base" if requires == "base_pin" else "reviewed"
        scope = claim.get("scope")
        return isinstance(scope, dict) and bool(str(scope.get(key, "")).strip())
    if requires == "criterion":
        return bool(str(claim.get("criterion", "")).strip())
    # An unknown requirement is a bug in THIS file, and it must not silently
    # become "qualified" — that would make a new banned form unenforceable the
    # moment it was added with a typo.
    return False


def check_page(text: str, by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Banned forms, and citations that resolve to nothing."""
    findings: List[Dict[str, Any]] = []
    for sentence in sentences(text):
        cited = [by_id.get(cid) for cid in CITATION_RE.findall(sentence)]
        for cid in CITATION_RE.findall(sentence):
            if cid not in by_id:
                findings.append({
                    "code": "DANGLING_CITATION",
                    "sentence": sentence,
                    "detail": (f"`[claim:{cid}]` resolves to nothing in the "
                               f"claims document. A citation that resolves to "
                               f"nothing reads to a reader exactly like one "
                               f"that resolves to evidence."),
                })
        for form in BANNED_FORMS:
            if not re.search(form["pattern"], sentence, re.I):
                continue
            qualified = any(c is not None
                            and _qualification_present(c, form["requires"])
                            for c in cited)
            if qualified:
                continue
            findings.append({
                "code": form["code"],
                "sentence": sentence,
                "requires": form["requires"],
                "detail": (
                    f"forbidden unqualified form (spec §3.3): {form['why']} "
                    + ("This form cannot be qualified; it has to be rewritten."
                       if form["requires"] == REQUIREMENT_NEVER else
                       f"Lift it with `[claim:<id>]` citing a claim that "
                       f"supplies `{form['requires']}`.")),
            })
    return findings


_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w.])")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _prose_only(sentence: str) -> str:
    """The sentence with inline code spans removed.

    A number inside `backticks` is a literal a reader copies, not a figure a
    reader quotes: a path like `/var/run-1000`, a schema like `metric.v1`, a
    flag like `--top-2`. Counting those as claims produces findings nobody can
    act on, and a gate that produces findings nobody can act on is a gate that
    gets switched off — which is a worse outcome than the false positives.

    Citations are matched on the ORIGINAL sentence, never on this, because
    `[claim:x]` is itself usually written inside backticks.
    """
    return _INLINE_CODE_RE.sub(" ", sentence)


def check_numbers_are_cited(text: str) -> List[Dict[str, Any]]:
    """Opt-in (`--cite-numbers`): a sentence stating a number carries a citation.

    Off by default and that is deliberate. On an arbitrary marketing page every
    version string and every date is a number, and a gate that fires on all of
    them is a gate somebody switches off. On a GENERATED report — where
    `ppa_report_gen.py` cites every row AND every count it prints — it is
    exact, and that is where the flag is meant to be used.

    Fenced code blocks are skipped for the same reason as inline code: the
    contents are an instruction to run, not an assertion to believe. The fence
    state is tracked across units because a fence opens on one line and closes
    on another, and a checker that forgot that would treat a whole shell
    transcript as prose.
    """
    findings: List[Dict[str, Any]] = []
    in_fence = False
    for sentence in sentences(text):
        if _FENCE_RE.match(sentence):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not _NUMBER_RE.search(_prose_only(sentence)):
            continue
        if CITATION_RE.search(sentence):
            continue
        findings.append({
            "code": "UNCITED_NUMBER",
            "sentence": sentence,
            "detail": ("states a number and cites no claim. A number a reader "
                       "can quote must be traceable to the artefact it was "
                       "parsed from."),
        })
    return findings


def check_claims(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A claim may not be stronger than its weakest evidence."""
    findings: List[Dict[str, Any]] = []
    for index, claim in enumerate(doc["claims"]):
        where = claim.get("id") if isinstance(claim, dict) else f"#{index}"
        if not isinstance(claim, dict):
            findings.append({"code": "CLAIM_MALFORMED", "claim": str(where),
                             "detail": "claim entry is not an object"})
            continue

        for field in COLLAPSED_SCALAR_FIELDS:
            if field in claim:
                findings.append({
                    "code": "COLLAPSED_SCALAR", "claim": str(where),
                    "detail": (f"carries `{field}`. Area, timing and power "
                               f"trade against each other, so one combined "
                               f"figure is a proxy for the property and not "
                               f"the property — and it is the figure that "
                               f"gets quoted."),
                })

        status = claim.get("status")
        if status not in STATUS_STRENGTH:
            findings.append({
                "code": "CLAIM_STATUS_UNKNOWN", "claim": str(where),
                "detail": (f"status {status!r} is not one of "
                           f"{sorted(STATUS_STRENGTH)}. An unknown status is "
                           f"not a weaker claim, it is an unreadable one."),
            })
            continue

        evidence = claim.get("evidence") or []
        if not evidence:
            # THE EXCEPTION, and the whole reason the NOT_MEASURED row exists:
            # the absence of the artefact IS the reported fact. Everything else
            # citing nothing is an assertion.
            if status != "NOT_MEASURED":
                findings.append({
                    "code": "UNCITED_CLAIM", "claim": str(where),
                    "detail": (f"status {status} and no evidence. Only a "
                               f"NOT_MEASURED claim may cite nothing, because "
                               f"there the absence is the fact."),
                })
            elif not str(claim.get("reason", "")).strip():
                findings.append({
                    "code": "NOT_MEASURED_WITHOUT_REASON", "claim": str(where),
                    "detail": ("NOT_MEASURED with no reason. The row must be "
                               "printed AND say why, or it is a hole with a "
                               "label on it."),
                })
            continue

        weakest = min(STATUS_STRENGTH.get(e.get("status"), -1)
                      for e in evidence if isinstance(e, dict)) \
            if all(isinstance(e, dict) for e in evidence) else -1
        if weakest < 0:
            findings.append({
                "code": "EVIDENCE_MALFORMED", "claim": str(where),
                "detail": "an evidence entry has no readable `status`",
            })
            continue
        if STATUS_STRENGTH[status] > weakest:
            worst = [e.get("status") for e in evidence
                     if STATUS_STRENGTH.get(e.get("status"), -1) == weakest]
            findings.append({
                "code": "CLAIM_OUTRUNS_EVIDENCE", "claim": str(where),
                "detail": (f"claims {status} while its evidence is "
                           f"{sorted(set(map(str, worst)))}. The sentence a "
                           f"reader takes away would be stronger than anything "
                           f"that was measured."),
            })
    return findings


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def evaluate(page_path: Path, claims_path: Path,
             cite_numbers: bool = False) -> Tuple[int, Dict[str, Any]]:
    if not page_path.exists():
        return RC_UNDETERMINED, {
            "code": "PAGE_MISSING", "marker": "[CANNOT CHECK]",
            "detail": (f"{page_path} does not exist. Nothing was read, so "
                       f"nothing is clean."),
        }
    try:
        raw = page_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return RC_UNDETERMINED, {
            "code": "PAGE_UNREADABLE", "marker": "[CANNOT CHECK]",
            "detail": f"{page_path}: {type(exc).__name__}: {exc}",
        }

    doc, undetermined = load_claims(claims_path)
    if doc is None:
        undetermined["marker"] = "[CANNOT CHECK]"
        return RC_UNDETERMINED, undetermined

    text = page_text(raw)
    units = sentences(text)
    if not units:
        return RC_UNDETERMINED, {
            "code": "EMPTY_PAGE", "marker": "[CANNOT CHECK]",
            "detail": (f"{page_path} rendered to 0 sentences ({len(raw)} raw "
                       f"bytes). A page this gate cannot read is not a page it "
                       f"may report clean over."),
        }

    by_id = index_claims(doc)
    findings = check_page(text, by_id) + check_claims(doc)
    if cite_numbers:
        findings += check_numbers_are_cited(text)

    report = {
        "page": str(page_path),
        "claims_file": str(claims_path),
        "sentences_read": len(units),
        "claims_read": len(doc["claims"]),
        "banned_forms_enforced": [f["code"] for f in BANNED_FORMS],
        "cite_numbers": bool(cite_numbers),
        "findings": findings,
    }
    if findings:
        report["code"] = "REFUSED"
        report["marker"] = "[REFUSE]"
        return RC_REFUSED, report
    report["code"] = "OK"
    return RC_OK, report


def format_report(rc: int, report: Dict[str, Any]) -> str:
    if rc != RC_REFUSED:
        return (f"page-claim check: {report['sentences_read']} sentence(s), "
                f"{report['claims_read']} claim(s), "
                f"{len(report['banned_forms_enforced'])} banned form(s) "
                f"enforced -> rc={rc} {report['code']}")
    lines = [f"[REFUSE] {len(report['findings'])} finding(s) over "
             f"{report['sentences_read']} sentence(s) and "
             f"{report['claims_read']} claim(s):"]
    for finding in report["findings"]:
        subject = finding.get("sentence") or f"claim {finding.get('claim')}"
        lines.append(f"  {finding['code']}: {finding['detail']}")
        lines.append(f"    -> {subject[:200]}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse a public page sentence that outruns its evidence "
                    "(spec §3.3, §18.1).")
    ap.add_argument("page", nargs="?",
                    help="the public page (HTML or Markdown)")
    ap.add_argument("--claims", default=None, metavar="PATH",
                    help=f"the {CLAIMS_SCHEMA} document the page cites")
    ap.add_argument("--cite-numbers", action="store_true",
                    help="also require that every sentence stating a number "
                         "carries a [claim:<id>]. Intended for generated "
                         "reports, where every row is cited by construction.")
    ap.add_argument("--list-banned-forms", action="store_true",
                    help="print the enforced forms and exit 0")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="write the machine-readable report here")
    args = ap.parse_args(argv)

    if args.list_banned_forms:
        for form in BANNED_FORMS:
            print(f"{form['code']}\t{form['requires']}\t{form['pattern']}")
        return RC_OK

    if not args.page or not args.claims:
        ap.error("give a page path and --claims PATH")

    rc, report = evaluate(Path(args.page), Path(args.claims),
                          cite_numbers=args.cite_numbers)
    if rc == RC_UNDETERMINED:
        print(f"{report['marker']} {report['code']}: {report['detail']}",
              file=sys.stderr)
        print(f"{report['marker']} {report['code']} -> rc={rc}")
    else:
        print(format_report(rc, report))
        if rc == RC_REFUSED:
            print(f"REFUSED: {len(report['findings'])} sentence(s) or claim(s) "
                  f"cannot support what they say.", file=sys.stderr)
    if args.json:
        payload = dict(report)
        payload["rc"] = rc
        atomic_write_text(Path(args.json),
                          json.dumps(payload, indent=2, sort_keys=True,
                                     ensure_ascii=False) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
