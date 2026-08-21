#!/usr/bin/env python3
"""Does the INPUT state facts for a layer that the layer did not extract?

WHY (the measured defect, chip-AGNOSTIC)
----------------------------------------
Phase 1's coverage percentage is a LITERAL metric: each auto-discovered literal
is credited when it appears anywhere in ``l_text``, the concatenation of every
``generated_docs/*.json``. So the question it asks is

    "does this token appear ANYWHERE in the union of 28 layers?"

and never

    "did it land in the layer that CONSUMES it?"

Measured on a real mixed-signal cell, every one of these was true at once::

    overall.pct = 100.0%   status = PASS   input_documents_unread = 0
    per_l_doc: {"name": "L21_POWER_INTENT", "evidence_count": 0}
    literals 'IOVDD' / 'CORE' / '1.8 V' / '1.2 V' -- all IN the denominator,
      all credited HIT, all credited from L1_DATASHEET / L2_FRS / L5_ADI_SPEC
    L21_POWER_INTENT.json: {"power_domains": [], ...}

The design STATES its rails in a two-row table under a heading called
``## Supplies / levels``. They landed in three PROSE layers. The layer the back
end builds the PDN from got zero. Downstream that is not cosmetic: an empty L21
makes every hard-macro PG pin `undeclared`, which FAILs the l21 pre-route gate,
which means no DEF, no GDS, and a mixed-signal top with no digital half. The
coverage number could not tell those two outcomes apart, so it printed 100 %
over the exact miss that later blocked the back end.

WHAT THIS DOES ABOUT IT
-----------------------
It follows the remedy this file's own neighbour already established for the
same defect shape (v1.7.72 / #499, the unread-document census): **do not reshape
the percentage** -- a literal-coverage figure is a literal-coverage figure and
rebasing it only moves the dishonesty -- but carry the census beside it and
degrade ``overall.status`` rather than averaging the miss away.

A layer is DEMANDED when a deterministic probe can show, from the design's own
input documents, that the input states facts belonging to that layer. It is
SILENT-EMPTY when it is demanded and its structured fields hold nothing.

WHY A PROBE AND NOT "FLAG EVERY EMPTY LAYER"
--------------------------------------------
Most empty layers are correctly empty. On the same run, 14 of 28 layers had
``evidence_count == 0`` -- L3 has no opcodes because the IP has no command
protocol, and the run says so itself ("structurally correct for non-protocol
IPs"). Flagging those would be a false-positive machine and would train readers
to ignore the field. A probe fires only on POSITIVE evidence that the input
stated something, so silence stays silent and only a real miss speaks.

Registry, not a special case: each probe declares its layer, how to count what
the INPUT states, and how to count what the LAYER holds. Adding a probe for
another layer is a new entry, not a new mechanism.

A ZERO FROM THE PROBE WAS ITSELF AN UNCHECKED NUMBER
----------------------------------------------------
The first version of this file had the same defect one level down that it was
written to catch. Measured on a fleet Phase-1 run::

    Layer demand:        0 layer(s) demanded by the input, 0 silently empty
    overall.pct = 100.0%   status = PASS

while `L21_POWER_INTENT.json` was a byte-empty skeleton
(`extraction_status: NOT_YET_EXTRACTED`, every field an empty container) and
FOUR of the design's own input documents stated its power domains outright.

Nothing in that line is false and nothing in it is a measurement. `NOT_DEMANDED`
was reached by ``stated["count"] == 0`` alone, and the extractor behind that
count already returns ``docs_read`` / ``tables_seen`` / ``tables_qualified`` --
which this file received and threw away. So one printed 0 was covering three
different worlds:

* the probe read documents and they state no rails      (a measured zero)
* the probe read NO documents at all                    (an unexamined zero)
* the probe read the documents and its TABLE parser did not admit the shape
  the design used, while the documents state the subject in plain sight
                                                        (a contradicted zero)

Only the first is an answer. The rule this file now enforces::

    a demand probe returning zero must carry the evidence that zero is the
    MEASURED answer and not the UNEXAMINED one; and a layer that is an empty
    skeleton while an input document STATES its subject is a FAIL, not a
    silent pass.

Three mechanisms, in the order they run:

1. **The examination record is carried, not discarded.** Every probe returns
   ``examined`` beside its count, and every zero is stamped
   ``zero_is_measured``. A zero over ``documents_read == 0`` becomes
   ``ZERO_UNEXAMINED`` -- disclosed, never counted as a measured zero, and NOT
   a FAIL, because a corpus that does not exist cannot state anything.
2. **A zero over a real corpus is contradicted, or it stands.** When the
   extractor returns zero and the layer is an EMPTY SKELETON, a second reading
   of the SAME documents (`l21_doc_supply_rail_synth.doc_sources`) asks the
   parser-independent question: does any line in the design's own input STATE
   this subject? If it does, that is `SILENT_EMPTY` with
   ``demand_source = "input_corpus_scan"`` and the run FAILs, with the file and
   line quoted. If it does not, `NOT_DEMANDED` stands -- and now stands on a
   stated denominator.
3. **The summary line can no longer print a bare 0/0.** Every zero it renders
   carries either the number of documents the zeros were measured over or the
   word UNEXAMINED.
4. **Both readings' unavailability reaches the verdict, not just the first's.**
   `stated["unavailable"]` (the extractor died) was wired from the start.
   `corroboration["unavailable"]` (the SECOND reading died, or the
   empty-skeleton test that decides whether to ask it could not answer) was
   computed and published into the artifact and then never consulted, so a zero
   with no second opinion was stamped ``zero_is_measured=True``. The asymmetry
   is what marked it an omission rather than a design choice. Both now land in
   ``ZERO_UNEXAMINED``.

WHY ``ZERO_UNEXAMINED`` DEGRADES ``overall.status``
---------------------------------------------------
Because a list carried BESIDE a verdict cannot correct the verdict. This status
is 33 of the 106 projects that carry this layer -- roughly a third -- and while it
had its own word, its own list and its own summary line, the field a consumer
actually reads still said ``PASS``. That is the same substitution as the defect
above, one level up: real disclosure sitting next to a word that contradicts it,
where only the word is machine-read.

``phase1_doc_one_shot_runner.emit_coverage_report`` therefore degrades
``overall.status`` to ``INCOMPLETE_ZERO_UNEXAMINED``. Three properties are
deliberate:

* **INCOMPLETE, not FAIL.** A reading that did not happen accuses nobody. Same
  tier the P0 structural umbrella mints for the same sentence ("the input WAS
  applicable and was NOT examined"); the suffix is this artifact's dialect --
  its existing words are ``PASS`` / ``FAIL`` / ``FAIL_INPUT_NOT_FULLY_READ`` /
  ``FAIL_LAYER_DEMANDED_BUT_EMPTY``, so a bare ``INCOMPLETE`` would be the one
  unqualified word in the set.
* **Gated on ``_status == "PASS"``,** exactly like ``FAIL_LAYER_DEMANDED_BUT_
  EMPTY`` beside it, so a real FAIL always outranks a disclosure and the two
  pre-existing FAIL words are unreachable-by-this-branch.
* **The percentage is NOT touched.** Same remedy as #499 and as mechanism 2
  above: reshaping the ratio only moves the dishonesty.

The consumer blast radius of the new word was MEASURED, not assumed: no
allow-list, enum or JSON schema constrains this field anywhere in the repo, and
the only consumer that reads it as a verdict
(``benchmark_evidence_publish._citations_under_a_pass``) fails OPEN on an
unknown word -- it asserts less, never more. Full accounting at the assignment
site in ``phase1_doc_one_shot_runner``.

WHY THE CORROBORATION IS NOT A SECOND EXTRACTOR
-----------------------------------------------
It answers yes/no with evidence; it never emits a rail into the layer. It also
does not accept a MENTION. A line qualifies only when its LEADING token is the
supply subject itself -- a supply noun (`Supplies`, `Power domains`, `Rail`) or
a conventional supply-net identifier -- AND the same line states a voltage. That
is deliberately the same admission rule the sibling producer applies to a table
ROW ("the first cell yields a leading bare identifier, and some other cell in
the SAME row states a voltage"), lifted from table scope to line scope, which is
exactly the gap the table parser leaves.

Measured over the 107 Phase-1 projects tracked in this repo, that leading-token
requirement is what separates a statement from prose. Without it the scan also
fired on lines like "…the supply voltage is reduced from 2.5 to 1.8 V" and
"…confused with the EPS12V connector" -- narrative about a standard, in
documents whose designs declare no rails. With it, those three stop firing and
the real one still does.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROGRAM = "phase1_layer_demand_probe"
VERSION = "1.0.0"


# ── what "the probe examined nothing" looks like ─────────────────────────────
#: The examination record a probe carries when it could not even reach its
#: extractor. `None` for every counter means UNKNOWN, which is distinct from 0.
_EXAMINED_UNKNOWN: Dict[str, Any] = {
    "documents_read": None, "tables_seen": None, "tables_qualified": None}


# ── probes ───────────────────────────────────────────────────────────────────
def _l21_input_states(project: Path) -> Dict[str, Any]:
    """Supply rails the design's own documents STATE, via the shipped
    doc-table producer. Never invents: see `l21_doc_supply_rail_synth`.

    Carries the producer's own examination counters. They were already being
    returned and already being dropped here, which is what made a zero rail
    count indistinguishable from a zero DOCUMENT count.
    """
    try:
        from l21_doc_supply_rail_synth import derive as _derive
    except Exception:                                       # noqa: BLE001
        return {"count": 0, "unavailable": True, "items": [],
                "examined": dict(_EXAMINED_UNKNOWN)}
    try:
        res = _derive(project)
    except Exception:                                       # noqa: BLE001
        return {"count": 0, "unavailable": True, "items": [],
                "examined": dict(_EXAMINED_UNKNOWN)}
    rails = res.get("rails") or []
    return {
        "count": len(rails),
        "unavailable": False,
        "items": [{"name": r["rail"], "use": r["use"],
                   "voltage_v": r["voltage_v"],
                   "evidence": r["evidence"]} for r in rails],
        "examined": {
            "documents_read": res.get("docs_read"),
            "tables_seen": res.get("tables_seen"),
            "tables_qualified": res.get("tables_qualified"),
        },
    }


# ── the corroborating reading (mechanism 2) ──────────────────────────────────
#
# Line decoration a markdown/PDF-converted document puts in front of its own
# subject. Stripped so the LEADING token is the document's subject and not its
# bullet.
_LINE_DECOR_RE = re.compile(r"^[\s>*+\-|`#]*")

#: The subject named as a noun. `Supplies / levels`, `Power domains:`, `Rail`.
_SUPPLY_SUBJECT_NOUN_RE = re.compile(
    r"^(?:power\s+(?:supply|supplies|rail|rails|domain|domains|net|nets)|"
    r"suppl(?:y|ies)|rails?|voltage\s+domains?|core\s+supply|io\s+supply)\b",
    re.I)

#: The subject named as a net. Conventional supply-net spellings only -- these
#: are industry naming conventions, not any one design's or PDK's literals.
#:
#: The bare English word `ground` is deliberately NOT here. It leads lines like
#: "Ground bounce is limited to 100 mV", which is a noise spec and not a rail
#: declaration; the net spellings below already cover a document that names its
#: return path as a net, and a document that states supplies at all states a
#: POWER rail somewhere, so nothing is lost by refusing the ambiguous word.
_SUPPLY_SUBJECT_IDENT_RE = re.compile(
    r"^(v(?:dd|cc|ss|ee|bat|sub|pp|aa)[a-z0-9_]*|[adiv]?gnd[a-z0-9_]*|"
    r"[adi]v(?:dd|ss)[a-z0-9_]*|io_?v(?:dd|ss)[a-z0-9_]*)\b", re.I)

#: Volts or millivolts, never W / mW / A / mA / Hz -- identical intent to the
#: sibling producer's literal: a power table is not a supply-level table.
_SUPPLY_VOLT_RE = re.compile(
    r"(?<![A-Za-z0-9_.])([0-9]+(?:\.[0-9]+)?)\s*(mV|V)\b")

#: Evidence items kept in the JSON. The COUNT is never capped; this bounds only
#: the quoted list, and says so in `items_truncated` rather than silently.
_MAX_EVIDENCE_ITEMS = 25


def _lead_token_text(line: str) -> str:
    """The line with its list/table/quote decoration and markdown emphasis
    removed, so the first token is the line's own subject."""
    s = _LINE_DECOR_RE.sub("", line)
    s = s.replace("**", "").replace("`", "").replace("*", "")
    return s.strip()


def _supply_statement(line: str) -> Optional[Tuple[str, float]]:
    """``(subject, volts)`` when this LINE states a supply, else None.

    A mention is not a statement. The subject has to be what the line is ABOUT
    -- its leading token -- and the level has to be on the same line.
    """
    m_v = _SUPPLY_VOLT_RE.search(line)
    if not m_v:
        return None
    head = _lead_token_text(line)
    m_id = _SUPPLY_SUBJECT_IDENT_RE.match(head)
    if m_id:
        subject = m_id.group(1)
    else:
        m_n = _SUPPLY_SUBJECT_NOUN_RE.match(head)
        if not m_n:
            return None
        subject = m_n.group(0)
    volts = float(m_v.group(1))
    if m_v.group(2) == "mV":
        volts = volts / 1000.0
    return subject, volts


def _l21_subject_stated(project: Path) -> Dict[str, Any]:
    """Does any input document STATE a supply, read line-wise?

    Reads exactly the documents the extractor read, so the two readings share a
    denominator. Emits evidence only; it never writes a rail anywhere.
    """
    try:
        from l21_doc_supply_rail_synth import doc_sources as _sources
    except Exception:                                       # noqa: BLE001
        return {"statements": 0, "documents": 0, "unavailable": True,
                "items": [], "items_truncated": False}
    try:
        sources = _sources(project)
    except Exception:                                       # noqa: BLE001
        return {"statements": 0, "documents": 0, "unavailable": True,
                "items": [], "items_truncated": False}

    items: List[Dict[str, Any]] = []
    total = 0
    docs: set = set()
    for _p, rel, text in sources:
        for lineno, line in enumerate(text.splitlines(), 1):
            hit = _supply_statement(line)
            if hit is None:
                continue
            total += 1
            docs.add(rel)
            if len(items) < _MAX_EVIDENCE_ITEMS:
                items.append({
                    "name": hit[0],
                    "use": "STATED_IN_INPUT_DOCUMENT",
                    "voltage_v": hit[1],
                    "evidence": {"file": rel, "line": lineno,
                                 "text": line.strip()[:200]},
                })
    return {"statements": total, "documents": len(docs), "unavailable": False,
            "items": items, "items_truncated": total > len(items)}


def _empty_skeleton_verdict(doc: Dict[str, Any]) -> Optional[bool]:
    """Is the layer an empty skeleton? ``True`` / ``False`` / ``None``.

    ``None`` is the third answer, and it is the reason this function exists
    beside `_is_empty_skeleton`: the extraction-claim contract could not be
    imported, so this reading DID NOT HAPPEN. Collapsing that into ``False``
    is the same substitution this whole program is against -- "I looked and
    the answer is no" standing in for "I could not look". The distinction is
    load-bearing downstream: a `False` means the corroborating reading is not
    NEEDED (the layer holds content, or claims its extractor ran), while a
    `None` means it was never ASKED, and only one of those two may be reported
    as a measured zero.
    """
    try:
        from l_doc_consumer_contract import is_extraction_claimed
    except Exception:                                       # noqa: BLE001
        return None
    if is_extraction_claimed(doc):
        return False
    fields = doc.get("fields")
    if not isinstance(fields, dict):
        return False
    return _is_empty_value(fields)


def _is_empty_skeleton(doc: Dict[str, Any]) -> bool:
    """The layer asserts nothing AND holds nothing.

    Both halves are load-bearing. Dropping the second one turns a layer that
    carries its content under a DIFFERENT key vocabulary into a finding -- a
    real and separate defect, but not this one. Measured on the tracked corpus:
    29 of the 76 candidate projects hold content under keys this probe's
    `layer_holds` does not count, and calling those "empty" would have made the
    rule fire on a filled layer.

    The two-valued view, kept for readers that only need the predicate. A
    reading that could not run collapses to ``False`` here, which is why
    `evaluate` uses `_empty_skeleton_verdict` instead: it is the caller that
    has to tell "not a skeleton" from "could not tell".
    """
    return _empty_skeleton_verdict(doc) is True


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set)):
        return all(_is_empty_value(v) for v in value)
    if isinstance(value, dict):
        return all(_is_empty_value(v) for v in value.values())
    return False


def _l21_layer_holds(doc: Dict[str, Any]) -> int:
    f = (doc or {}).get("fields") or {}
    n = 0
    for key in ("power_rails", "power_domains"):
        v = f.get(key)
        if isinstance(v, list):
            n += len(v)
    return n


PROBES: List[Dict[str, Any]] = [
    {
        "layer": "L21_POWER_INTENT",
        "fact": "supply rail",
        "consumer": ("hardmacro_supply_intent.declared_rails -> the l21 "
                     "pre-route gate -> PDN / detailed routing"),
        "input_states": _l21_input_states,
        "layer_holds": _l21_layer_holds,
        # What a zero from `input_states` has to survive before it may be
        # reported as NOT_DEMANDED.
        "subject_stated": _l21_subject_stated,
        "corroborating_fact": "supply statement",
    },
]


# ── evaluation ───────────────────────────────────────────────────────────────
def _read_layer(project: Path, layer: str) -> Optional[Dict[str, Any]]:
    p = project / "phase1" / "generated_docs" / f"{layer}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:                                       # noqa: BLE001
        return None


def evaluate(project: Path) -> Dict[str, Any]:
    """``{"silent_empty": [...], "zero_unexamined": [...], "layers": [...],
    "probes_run": N}``.

    ``silent_empty`` is the load-bearing list: a layer the INPUT demands and
    the OUTPUT left empty. Empty list = nothing to say, which is the ordinary
    case and must stay quiet.

    ``zero_unexamined`` is the list that stops an empty ``silent_empty`` from
    reading as a clean measurement. A layer lands there when a reading that the
    zero depends on DID NOT HAPPEN. Three ways in, one per reading:

      * the FIRST reading (the extractor) could not run   -> PROBE_UNAVAILABLE
      * the first reading ran over ZERO documents         -> ZERO_UNEXAMINED
      * the first reading ran over real documents and returned zero, but the
        SECOND, corroborating reading could not run -- either the reading
        itself was unavailable, or the empty-skeleton test that decides whether
        to ask it could not answer -> ZERO_UNEXAMINED

    The third one is the one that closes the loop. A zero standing on a second
    reading that never happened is the unexamined answer wearing the measured
    answer's word, which is the entire subject of this program; the
    ``unavailable`` flag was already computed and already published in the
    artifact while the verdict declined to consult it.

    That is disclosure, not a verdict: it does NOT put the run into FAIL,
    because a corpus that does not exist cannot state a demand.

    Each layer record now also carries ``zero_is_measured`` (True / False /
    None-when-nonzero), ``examined``, and ``demand_source`` -- so a reader can
    tell WHICH of the two readings produced the finding.
    """
    layers: List[Dict[str, Any]] = []
    silent: List[str] = []
    unexamined: List[str] = []
    for probe in PROBES:
        layer = probe["layer"]
        stated = probe["input_states"](project)
        examined = stated.get("examined") or dict(_EXAMINED_UNKNOWN)
        doc = _read_layer(project, layer)
        if doc is None:
            layers.append({"layer": layer, "status": "LAYER_ABSENT",
                           "input_states": stated["count"], "layer_holds": 0,
                           "examined": examined,
                           "zero_is_measured": None,
                           "demand_source": "extractor"})
            continue
        holds = probe["layer_holds"](doc)

        record: Dict[str, Any] = {
            "layer": layer,
            "fact": probe["fact"],
            "consumer": probe["consumer"],
            "input_states": stated["count"],
            "layer_holds": holds,
            "stated_items": stated["items"],
            "examined": examined,
            "demand_source": "extractor",
            "zero_is_measured": None,
        }

        if stated.get("unavailable"):
            # The extractor never ran. Its 0 is the absence of an answer.
            record.update(status="PROBE_UNAVAILABLE", zero_is_measured=False)
            unexamined.append(layer)
        elif stated["count"] > 0:
            if holds == 0:
                record["status"] = "SILENT_EMPTY"
                silent.append(layer)
            else:
                record["status"] = "SATISFIED"
        elif not examined.get("documents_read"):
            # Zero rails over zero documents. Not a measurement of the design.
            record.update(status="ZERO_UNEXAMINED", zero_is_measured=False)
            unexamined.append(layer)
        else:
            # A zero over a real corpus. It stands only if a second, parser-
            # independent reading of the SAME documents also finds nothing --
            # and only the empty-skeleton case is worth asking about, because
            # a layer that holds content is not the defect this probe is for.
            corr: Dict[str, Any] = {"statements": 0, "documents": 0,
                                    "items": [], "items_truncated": False,
                                    "unavailable": False}
            skeleton = _empty_skeleton_verdict(doc)
            if skeleton is None:
                # The skeleton test could not answer, so the probe never
                # learned whether the second reading was even called for. That
                # is the same standing as a second reading that ran and could
                # not report: the corroborating evidence is UNAVAILABLE, not
                # absent. Recorded in the artifact's own vocabulary so the one
                # verdict branch below covers both ways of not having looked.
                corr["unavailable"] = True
            elif skeleton and holds == 0:
                corr = probe["subject_stated"](project)
            record["layer_is_empty_skeleton"] = skeleton
            record["corroboration"] = {
                "statements": corr.get("statements", 0),
                "documents": corr.get("documents", 0),
                "unavailable": bool(corr.get("unavailable")),
                "items_truncated": bool(corr.get("items_truncated")),
                "asked": bool(skeleton and holds == 0),
            }
            if corr.get("statements"):
                # The probe's zero is contradicted by the design's own input.
                record.update(
                    status="SILENT_EMPTY",
                    demand_source="input_corpus_scan",
                    zero_is_measured=False,
                    fact=probe.get("corroborating_fact", probe["fact"]),
                    input_states=corr["statements"],
                    stated_items=corr["items"],
                )
                silent.append(layer)
            elif corr.get("unavailable"):
                # The corroborating reading could not run. Its zero is the
                # ABSENCE of a second opinion, not a second opinion of zero --
                # exactly the reading `unavailable` was computed and published
                # for, and the branch that was missing while the flag sat in
                # the artifact unread. Symmetric with the FIRST reading's
                # `stated["unavailable"]` handling above; that asymmetry is
                # what made this an omission rather than a choice.
                record.update(status="ZERO_UNEXAMINED", zero_is_measured=False)
                unexamined.append(layer)
            else:
                record.update(status="NOT_DEMANDED", zero_is_measured=True)
        layers.append(record)
    return {"probes_run": len(PROBES), "layers": layers,
            "silent_empty": silent, "zero_unexamined": unexamined}


def _documents_examined(result: Dict[str, Any]) -> int:
    """Documents the probes actually read, summed over the probes.

    This is the denominator every reported zero is measured against. Printing a
    zero without it is what let "0 layers demanded" read as a finished
    measurement over a corpus nothing had opened.
    """
    total = 0
    for layer in result.get("layers") or []:
        n = (layer.get("examined") or {}).get("documents_read")
        if isinstance(n, int):
            total += n
    return total


def summary_line(result: Dict[str, Any]) -> str:
    """One line for the runner SUMMARY, so a reader cannot see the percentage
    without also seeing this.

    Invariant this line must keep: it never renders a zero without rendering
    what that zero was measured over, or the word UNEXAMINED.
    """
    silent = result.get("silent_empty") or []
    unexamined = result.get("zero_unexamined") or []
    if silent:
        line = ("Layer demand:        **{n} LAYER(S) DEMANDED BY THE INPUT AND "
                "EMPTY**: {names}".format(n=len(silent),
                                          names=", ".join(silent)))
        if unexamined:
            line += (f" (+{len(unexamined)} probe zero(s) UNEXAMINED: "
                     f"{', '.join(unexamined)})")
        return line

    demanded = [l for l in result["layers"]
                if l.get("status") in ("SATISFIED", "SILENT_EMPTY")]
    head = (f"Layer demand:        {len(demanded)} layer(s) demanded by "
            f"the input, 0 silently empty")
    if unexamined:
        return (f"{head} — but {len(unexamined)} probe zero(s) are "
                f"**UNEXAMINED**, not measured: {', '.join(unexamined)}")
    return f"{head} (zeros measured over {_documents_examined(result)} " \
           f"input document(s))"


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(
        description="Report layers the input states facts for and the layer "
                    "left empty.")
    ap.add_argument("project")
    ap.add_argument("--json", help="write the result JSON here")
    args = ap.parse_args(argv)

    proj = Path(args.project).resolve()
    res = evaluate(proj)

    print(f"=== {PROGRAM} ===")
    for l in res["layers"]:
        print(f"  {l['layer']:22s} {l['status']:18s} "
              f"input_states={l['input_states']} layer_holds={l['layer_holds']}")
        # Every zero prints what it was measured over. A count with no
        # denominator is the defect this program was corrected for.
        ex = l.get("examined") or {}
        print(f"    examined: documents_read={ex.get('documents_read')} "
              f"tables_seen={ex.get('tables_seen')} "
              f"tables_qualified={ex.get('tables_qualified')} "
              f"zero_is_measured={l.get('zero_is_measured')}")
        if l["status"] == "ZERO_UNEXAMINED":
            # Two different ways of not having looked reach this status, and
            # the line must not assert the wrong one: printing "read no input
            # document" over a run that read plenty and lost its SECOND
            # reading would be a fresh false statement in a program whose
            # subject is false statements about zeros.
            if (l.get("corroboration") or {}).get("unavailable"):
                print("    this zero is NOT a measurement: the corroborating "
                      "reading of the same documents could not run, so the "
                      "extractor's zero has no second opinion. It is "
                      "disclosed, not counted as demand.")
            else:
                print("    this zero is NOT a measurement: the probe read no "
                      "input document. It is disclosed, not counted as "
                      "demand.")
        if l["status"] == "PROBE_UNAVAILABLE":
            print("    this zero is NOT a measurement: the probe could not "
                  "run at all.")
        if l["status"] == "SILENT_EMPTY":
            print(f"    the input states {l['input_states']} {l['fact']}(s) "
                  f"and this layer holds none.")
            print(f"    demand_source: {l.get('demand_source')}")
            if l.get("demand_source") == "input_corpus_scan":
                corr = l.get("corroboration") or {}
                print(f"    the layer is an EMPTY SKELETON while "
                      f"{corr.get('documents')} input document(s) state its "
                      f"subject — the extractor's zero was the unexamined "
                      f"answer, not the measured one.")
            print(f"    consumer: {l['consumer']}")
            for it in l.get("stated_items") or []:
                ev = it["evidence"]
                print(f"      - {it['name']} ({it['use']}, {it['voltage_v']} V) "
                      f"[{ev['file']}:{ev['line']}]")
            if (l.get("corroboration") or {}).get("items_truncated"):
                print(f"      ... quoted list capped at {_MAX_EVIDENCE_ITEMS}; "
                      f"the count above is the full one.")
    print(f"  silent_empty: {res['silent_empty'] or 'none'}")
    print(f"  zero_unexamined: {res.get('zero_unexamined') or 'none'}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(res, indent=2, ensure_ascii=False) + "\n")

    return 1 if res["silent_empty"] else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
