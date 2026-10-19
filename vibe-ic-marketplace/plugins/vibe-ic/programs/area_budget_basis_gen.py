#!/usr/bin/env python3
"""area_budget_basis_gen.py — derive step 0.5ic's `synthesis_area_budget`
answer from the design's own documents and the OWNER-ATTESTED deliverable.

WHY A PRODUCER (R-0929-DELIVERABLE-CONSISTENCY, owner go 2026-09-29)
===================================================================
MEASURED: two designs' `input/step_0_5ic_answers.json` carry the owner-attested
`deliverable = DIE` (R-0915-95, 2026-09-17) beside a `synthesis_area_budget`
rationale written on 2026-09-06, while the deliverable was still an agent's
HARDMACRO, that says "declares deliverable=HARDMACRO". The owner changed the
answer; the text that DEPENDED on it had no producer, so nothing re-derived it
and it went on asserting the route the owner had overruled.

The owner's answer is authoritative and is never rewritten here. The derived
answer is REGENERATED — never hand-edited — from two inputs:

  * the design's documents: where they decline a die size, where they say the
    die area is decided by the run, the std-cell area gate row, and any
    die-area figure (with or without a comparator);
  * the owner-attested deliverable, read through
    `_tapeout_declaration.answer`, so an unattested value is NOT_DETERMINED and
    this program refuses instead of writing a premise nobody declared.

THE PREMISE IS READ, NEVER TYPED
================================
The deliverable sentence is rendered from the attested value and from the
input's die disposition. For a DIE whose input DECLINES a die size it states
the ruling's basis: the die area is an OUTCOME of the run (a pad-limited die:
die = core + pad ring + power ring, sized by the pad-ring perimeter when the
pad count dominates), and the input's std-cell area gate still applies. For an
input that FIXES the die the status is LIMIT with that rectangle, and nothing
about the die is called an outcome (R-0929-DELIVERABLE-CONSISTENCY-2). For a HARDMACRO it keeps the earlier meaning
(a macro takes no operator slot whose geometry could supply a ceiling).
`NOT_APPLICABLE` disposes of the die LIMIT only; the std-cell gate is carried
in `stdcell_area_gate`, with its file, line and row.

WHAT IS WRITTEN
===============
  answers.synthesis_area_budget        status, rationale, stdcell_area_gate,
                                       basis (every citation, structured)
  answer_provenance.synthesis_area_budget
                                       answered_by=program, producer,
                                       derived_from_attested {deliverable:
                                       <the attested value>}, inputs (every
                                       document read) and inputs_sha256 — the
                                       STRUCTURE the step-0.5ic gate compares
                                       with the owner's current answer
                                       (R-0929-DELIVERABLE-CONSISTENCY-2)
  answer_revisions[]                   one record per change: reason, the
                                       rulings followed (this ruling and the
                                       one cited by the owner's attestation),
                                       the previous text's sha256 and the
                                       previous provenance record

Nothing else in the file changes, except one line appended to a `_comment`
that says nothing in the file is derived by a program. A second run with the
same inputs writes nothing.

REFUSALS (nothing is written)
=============================
  rc 1  the deliverable is not owner-attested; the input both fixes and
        declines a die; the input gates a die AREA with no dimensions (a LIMIT
        carries two, and none is invented); the answers file is unreadable.
  rc 2  the input neither fixes nor declines a die size: the answer stays
        unanswered, never a default. Also a usage error.

chip-AGNOSTIC: no design, process, library or vendor name. Every value comes
from the design's input at run time.

USAGE
-----
    python3 area_budget_basis_gen.py <project> [--answers IN.json]
        [--out OUT.json] [--reason TEXT] [--json REPORT.json]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _atomic_artefact as _aa                                 # noqa: E402
import _submission_template as ST                              # noqa: E402
import _tapeout_declaration as TD                              # noqa: E402
import area_signoff_baseline as ASB                            # noqa: E402
import floorplan_contract as FPC                               # noqa: E402
import plugin_manifest_discovery as _pmd                       # noqa: E402
# The repo's one vocabulary of "the implementation may choose this".
from crosslayer_search_space import _FREEDOM_MARKERS           # noqa: E402

PROGRAM = "area_budget_basis_gen"
KEY = TD.SYNTHESIS_AREA_BUDGET_KEY

_PROSE_SUFFIXES = (".md", ".txt", ".rst")
#: A die-size SUBJECT. `(?<![A-Za-z])` rather than `\b`, because a CJK
#: character before "die" is a word character and `\b` would miss it.
_DIE_SUBJECT_RE = re.compile(
    r"(?<![A-Za-z])die\s*(?:(?:size|area|dimensions?)\b|尺寸|面積|大小)"
    r"|晶粒\s*(?:尺寸|面積)", re.IGNORECASE)
_FREEDOM_RE = re.compile("|".join(_FREEDOM_MARKERS), re.IGNORECASE)
#: "the die area is decided by the run": an outcome, not a ceiling.
_OUTCOME_RE = re.compile(
    r"跑出後決定|(?:由|依)[^。.;；\n]{0,40}?(?:決定|推算)"
    r"|(?:determined|sized)\s+by\s+the\s+"
    r"(?:(?:canonical|IC)\s+)*(?:run|flow|implementation)"
    r"|an?\s+outcome\s+of", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_BULLET_RE = re.compile(r"^[\s>*+\-]+")
_RULING_RE = re.compile(r"\bR-\d{4}-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")

#: The die area, read by the same table reader as the std-cell gate. A bare
#: figure is a measurement; a comparator in front of it is a gate.
_DIE_AREA_METRIC = ASB.Metric(
    key="die_area", label="die area",
    metric_re=re.compile(r"(?<![A-Za-z])die\s*area|die\s*面積|晶粒\s*面積",
                         re.IGNORECASE),
    unit_pattern=ASB._UM2, units=ASB._AREA_UNITS, canonical_unit="um^2",
    hdr_re=re.compile(r"area|面積", re.IGNORECASE),
    prose_re=re.compile(r"(?<![A-Za-z])die\s*area|die\s*面積", re.IGNORECASE),
    disclosure="", no_signoff_reason="no_die_area_stated")


def _fmt(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _quote(line: str, limit: int = 160) -> str:
    q = _BULLET_RE.sub("", line).strip()
    q = q.lstrip("❌✅ ").strip()
    return q if len(q) <= limit else q[:limit - 3].rstrip() + "..."


#: Where flow step D1 writes its plain-text copy of `input/docs/`
#: (`phase1_doc_one_shot_runner.extract_text_pipeline`).
_D1_COPY_ROOTS = ("phase1/input_doc/", "input_doc/")


def _d1_copy_stems(project: Path) -> set:
    """The names D1 gives its copies of `input/docs/*`: `<sub>__<stem>`,
    lower-cased (`spec/foo.pdf` -> `spec__foo.txt`)."""
    src = Path(project) / "input" / "docs"
    if not src.is_dir():
        return set()
    return {"__".join(f.relative_to(src).with_suffix("").parts).lower()
            for f in src.rglob("*") if f.is_file()}


def _one_copy(project: Path, items, rel_of) -> list:
    """Read each design document ONCE. D1 copies `input/docs/X.md` to
    `phase1/input_doc/X.txt`; when the original exists its copy is skipped,
    exactly as `l8_doc_clock_freq_synth._iter_docs` does. Otherwise the same
    table is read twice (two std-cell rows, the copies among the inputs) and a
    re-derivation after D1 disagrees with the answer derived before it
    (DELIVC3 final check)."""
    originals = _d1_copy_stems(project)
    out = []
    for item in items:
        rel = rel_of(item)
        if (rel.startswith(_D1_COPY_ROOTS)
                and Path(rel).stem.lower() in originals):
            continue
        out.append(item)
    return out


def l7_docs(project: Path) -> List[Tuple[str, str]]:
    """The L7 documents, each read once (see `_one_copy`)."""
    return _one_copy(project, ASB.l7_docs_of(project), lambda it: it[0])


def design_docs(project: Path) -> List[Tuple[str, Path, str]]:
    """The design's own prose documents, through the shared input walker
    (which already skips every oracle/reference tree). Operator material under
    the submission-template directories is not the design speaking."""
    out = []
    for rel, path, text in _one_copy(project, FPC._iter_input_files(project),
                                     lambda it: it[0]):
        if path.suffix.lower() not in _PROSE_SUFFIXES:
            continue
        if rel.startswith("input/submission_template"):
            continue
        out.append((rel, path, text))
    return out


def die_size_statements(docs: Sequence[Tuple[str, Path, str]]
                        ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(declines, outcomes): lines where the input declines a die size, and
    lines where it says the die area is decided by the run.

    A heading that names the die (e.g. a "Die size" subsection) is read with
    the first line of its body, since that is where the decline is written.
    """
    declines: List[Dict[str, Any]] = []
    outcomes: List[Dict[str, Any]] = []
    for rel, _path, text in docs:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not _DIE_SUBJECT_RE.search(line):
                continue
            span, body, cite = line, line, f"{rel}:{i + 1}"
            if _HEADING_RE.match(line):
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines) or _HEADING_RE.match(lines[j]):
                    continue
                body = lines[j]
                span = line + "\n" + body
                cite = f"{rel}:{i + 1}-{j + 1}"
            rec = {"source": rel, "cite": cite, "quote": _quote(body)}
            if _FREEDOM_RE.search(span):
                declines.append(rec)
            elif _OUTCOME_RE.search(span):
                outcomes.append(rec)
    return declines, outcomes


def _table_rows(project: Path, metric) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {"ceilings": [], "baselines": []}
    seen = set()
    for rel, text in l7_docs(project):
        got = ASB.parse_signoff_statements(text, metric, source=rel)
        for kind in ("ceilings", "baselines"):
            for row in got[kind]:
                ident = (kind, rel, row["line"])
                if ident in seen:
                    continue
                seen.add(ident)
                out[kind].append({"source": rel, "line": row["line"],
                                  "cite": f"{rel}:{row['line']}",
                                  "row": row["row"],
                                  "value_um2": row["value"]})
    return out


def _ruling_ref(citation: Optional[str]) -> str:
    m = _RULING_RE.search(citation or "")
    if m:
        return m.group(0)
    c = (citation or "").strip()
    return f"'{c[:80]}'" if c else "no citation"


def premise(deliverable: str, ref: str, fixed: Optional[str] = None) -> str:
    """The deliverable sentence, rendered FROM the attested value AND the
    input's die disposition. When the input FIXES the die (`fixed` = "WxH"),
    that rectangle is the LIMIT and nothing about the die is an outcome of
    the run; the pad-limited outcome basis is for an input that declines a
    die size (R-0929-DELIVERABLE-CONSISTENCY-2)."""
    attested = (f"The deliverable is {deliverable}, attested by the owner "
                f"(`{TD.PROVENANCE_KEY}.deliverable`, {ref})")
    if fixed:
        if deliverable == TD.DELIVERABLE_DIE:
            return (attested + f", so the die is the input's fixed {fixed} "
                    "um: core = die minus the pad ring and the power ring.")
        return (attested + f", so the macro outline is the input's fixed "
                f"{fixed} um, and the macro takes no operator slot.")
    if deliverable == TD.DELIVERABLE_DIE:
        return (attested + ", so the die area is an OUTCOME of this run, not "
                "a ceiling the input set: a pad-limited die, die = core + pad "
                "ring + power ring, sized by the pad-ring perimeter when the "
                "pad count dominates.")
    return (attested + ", so the delivery is a macro that takes no operator "
            "slot whose geometry could supply a ceiling; its outline is an "
            "outcome of this run.")


def _cites(recs: Sequence[Dict[str, Any]]) -> str:
    return "; ".join(f"{r['cite']} ('{r['quote']}')" for r in recs)


def _operator_slot_attestation(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the chooser distinct from an owner's scoped implementation grant.

    Delegation applies only to this slot choice. It cannot attest the
    deliverable or turn an uncited agent inference into an owner decision.
    """
    key = "operator_template.slot"
    att = TD.attestation_of(doc, key)
    provenance = doc.get(TD.PROVENANCE_KEY)
    record = provenance.get(key) if isinstance(provenance, dict) else None
    grant = record.get("delegation") if isinstance(record, dict) else None
    if (att["answered_by"] == TD.ANSWERED_BY_AGENT_VALUE and att["citation"]
            and isinstance(grant, dict) and grant.get("scope") == key):
        owner = TD.attestation_of({TD.PROVENANCE_KEY: {key: grant}}, key)
        if owner["declares"]:
            return {**att, "declares": True, "why_not": None,
                    "delegation": {**owner, "scope": key}}
    return att


def _operator_die_basis(project: Path, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Read an owner-selected slot through the existing template producer.

    The ingested rectangle alone is not authority: re-read its source and
    compare the geometry, and refuse stale/unattested selections. No slot
    is selected here and no published dimension is rounded.
    """
    operator = doc.get("operator_template") or {}
    slot = operator.get("slot") if isinstance(operator, dict) else None
    current_path = project / ST.DESIGN_ANSWERS_REL
    if current_path.is_file():
        current, error = TD.load(current_path)
        if error or not isinstance(current, dict):
            return {"error": error or "the current owner answers are not a mapping"}
        current_operator = current.get("operator_template") or {}
        current_slot = (current_operator.get("slot")
                        if isinstance(current_operator, dict) else None)
        if current_slot != slot:
            return {"error": "the recorded operator slot differs from the current owner answers"}
        if TD.is_answered(slot) and _operator_slot_attestation(current) != _operator_slot_attestation(doc):
            return {"error": "the recorded slot attestation differs from the current owner answers"}
    if not TD.is_answered(slot):
        return {}
    attestation = _operator_slot_attestation(doc)
    if not isinstance(slot, str) or not attestation["declares"]:
        return {"error": "the selected operator slot is not owner-attested or explicitly owner-delegated"}
    import submission_template_answers as producer
    report = producer.build(project, slot_name=slot)
    if report["verdict"] != producer.PASS:
        return {"error": report["reason"]}
    record, error = ST._load_mapping(project / report["slot_file"])
    if error or not isinstance(record, dict):
        return {"error": error or "the selected slot record is not a mapping"}
    if not isinstance(record.get("source_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["source_sha256"]):
        return {"error": "the selected slot has no source digest to verify"}
    source, notes = producer._source_record(project, record)
    if notes or not source:
        return {"error": "; ".join(notes) or "the selected slot source is unavailable"}
    source_path = Path(record["source_file"])
    if not source_path.is_absolute():
        source_path = project / source_path
    try:
        source_rel = str(source_path.resolve().relative_to(project.resolve()))
    except ValueError:
        return {"error": "the selected operator source is outside the project and cannot be input-bound"}
    fresh = ST.slot_record(source_path, source, source_path.parent)
    rect = ST.parse_rect((fresh.get("die_area") or {}).get("rect"))
    transcribed = ST.parse_rect(report["answers"].get("die_area_um"))
    if rect is None or rect != transcribed:
        return {"error": "the selected slot geometry disagrees with its source"}
    width, height = ST.rect_wh(rect)
    return {"fixed": (f"{ST.dec_str(width)}x{ST.dec_str(height)}", report["slot_file"]),
            "slot": slot, "attestation": attestation,
            "inputs": [report["slot_file"], source_rel]}


def derive(project: Path, doc: Dict[str, Any]) -> Dict[str, Any]:
    """{status: WRITE|REFUSED|NOT_DETERMINED, budget?, reason?, basis}."""
    # THE OWNER'S FIELD IS NEVER OVERWRITTEN (DELIVC final check, finding 2).
    # Any owner record, cited or not: an uncited one is a defect the owner
    # fixes, never a licence for a program to replace the owner's answer.
    # Decided by the repo's one reader, the same one the gate uses, so a
    # record the gate reads as the owner's (e.g. " owner ") is never
    # overwritten here (DELIVC3 final check).
    if TD.attestation_of(doc, KEY)["answered_by"] == \
            TD.ANSWERED_BY_OWNER_VALUE:
        return {"status": "REFUSED", "rc": 1,
                "reason": (f"`{TD.PROVENANCE_KEY}.{KEY}` says the owner "
                           f"answered `{KEY}`; this program never overwrites "
                           f"an owner field")}
    deliverable = TD.answer(doc, "deliverable")
    att = TD.attestation_of(doc, "deliverable")
    if deliverable not in TD.DELIVERABLES:
        return {"status": "REFUSED", "rc": 1,
                "reason": ("the area basis depends on the deliverable, and it "
                           "is not owner-attested: "
                           + TD.not_declared_message(doc, "deliverable"))}
    ref = _ruling_ref(att["citation"])
    docs = design_docs(project)
    declines, outcomes = die_size_statements(docs)
    fixed = FPC._prose_die_area(project, list(docs))
    operator = (_operator_die_basis(project, doc)
                if deliverable == TD.DELIVERABLE_DIE else {})
    if operator.get("error"):
        return {"status": "REFUSED", "rc": 1, "reason": operator["error"]}
    if operator.get("fixed"):
        if fixed and fixed[0] != operator["fixed"][0]:
            return {"status": "REFUSED", "rc": 1,
                    "reason": "the design's fixed die disagrees with the owner-selected operator slot"}
        fixed = operator["fixed"]
    cell = _table_rows(project, ASB.METRIC_CELL_AREA)
    die = _table_rows(project, _DIE_AREA_METRIC)
    basis: Dict[str, Any] = {
        "deliverable": deliverable,
        "deliverable_attested_by": ref,
        "die_size_declined": declines,
        "die_area_decided_by_the_run": outcomes,
        "die_fixed_by_the_input": (
            {"wxh_um": fixed[0], "source": fixed[1]} if fixed else None),
        "die_area_figures": die["baselines"],
        "die_area_gates": die["ceilings"],
        "stdcell_area_baseline": cell["baselines"],
    }
    if operator:
        basis["operator_slot"] = {"slot": operator["slot"],
                                  "attestation": operator["attestation"]}
    gates = cell["ceilings"]
    if die["ceilings"]:
        return {"status": "REFUSED", "rc": 1, "basis": basis,
                "reason": ("the input gates a die AREA at "
                           + ", ".join(r["cite"] for r in die["ceilings"])
                           + "; a LIMIT carries two die dimensions and this "
                           "program invents neither")}
    if fixed and declines and not operator:
        return {"status": "REFUSED", "rc": 1, "basis": basis,
                "reason": (f"the input fixes the die at {fixed[0]} um "
                           f"({fixed[1]}) and declines a die size at "
                           + ", ".join(r["cite"] for r in declines)
                           + "; two design statements disagree and neither "
                           "may silently win")}
    if not fixed and not declines and not outcomes:
        return {"status": "NOT_DETERMINED", "rc": 2, "basis": basis,
                "reason": ("the input neither fixes nor declines a die size; "
                           f"`{KEY}` stays unanswered, never a default")}

    parts: List[str] = []
    if fixed:
        w, h = (float(x) for x in fixed[0].lower().split("x"))
        if operator:
            chooser = ("owner-selected" if operator['attestation']['answered_by'] == TD.ANSWERED_BY_OWNER_VALUE
                       else "owner-authorized agent-selected")
            parts.append(f"The {chooser} operator slot {operator['slot']!r} "
                         "fulfills the original documents' delegated sizing choice.")
        parts.append(f"The input fixes the die at {fixed[0]} um "
                     f"({fixed[1]}); that rectangle is the LIMIT carried "
                     "here.")
        parts.append(premise(deliverable, ref, fixed[0]))
    else:
        if declines:
            parts.append("The input declines a die size: "
                         + _cites(declines) + ".")
        if outcomes:
            parts.append("It says the die area is decided by the run: "
                         + _cites(outcomes) + ".")
        parts.append("So there is no die or core rectangle to fit inside and "
                     "no max_die_dimensions_um for a LIMIT to carry: "
                     "NOT_APPLICABLE disposes of the die LIMIT only.")
        parts.append(premise(deliverable, ref))
    if gates:
        g = "; ".join(f"{r['cite']} '{r['row']}' (ceiling "
                      f"{_fmt(r['value_um2'])} µm²)" for r in gates)
        b = cell["baselines"]
        base = ("" if not b else ", against the baseline std-cell area of "
                + "; ".join(f"{_fmt(r['value_um2'])} µm² at {r['cite']}"
                            for r in b))
        parts.append("The input's std-cell area gate still applies and is "
                     f"carried in `stdcell_area_gate`: {g}{base}. A "
                     "cell-area ceiling in µm² is not two die dimensions and "
                     "is not re-typed as one.")
    else:
        parts.append("The input states no std-cell area gate, so none is "
                     "carried.")
    if die["baselines"]:
        parts.append("The die-area figure(s) at "
                     + "; ".join(f"{r['cite']} ({_fmt(r['value_um2'])} µm²)"
                                 for r in die["baselines"])
                     + " carry no comparator: a measurement reported for "
                     "comparison, not a gate.")
    budget: Dict[str, Any] = {"status": (TD.AREA_BUDGET_LIMIT if fixed
                                         else TD.AREA_BUDGET_NOT_APPLICABLE),
                              "rationale": " ".join(parts)}
    if fixed:
        budget["max_die_dimensions_um"] = [w, h]
    budget["stdcell_area_gate"] = [
        {k: r[k] for k in ("source", "line", "row", "value_um2")}
        for r in gates]
    budget["basis"] = basis
    # EVERY document the derivation read, not only the ones it cited: a
    # decline or a gate added to any of them changes the answer, so each is
    # part of what the answer was derived from.
    inputs = sorted({rel for rel, _p, _t in docs}
                    | {rel for rel, _t in l7_docs(project)}
                    | set(operator.get("inputs", [])))
    digest = TD.derived_inputs_sha256(project, inputs)
    if digest is None:                               # pragma: no cover
        return {"status": "REFUSED", "rc": 1, "basis": basis,
                "reason": f"an input it read cannot be re-read: {inputs}"}
    return {"status": "WRITE", "rc": 0, "budget": budget,
            "inputs": inputs, "inputs_sha256": digest,
            "ref": ref, "attestation": att, "deliverable": deliverable}


def provenance_record(got: Dict[str, Any]) -> Dict[str, Any]:
    """The `answer_provenance.<KEY>` record for a WRITE result of `derive`."""
    return {"answered_by": TD.ANSWERED_BY_PROGRAM_VALUE,
            "producer": PROGRAM,
            TD.DERIVED_FROM_ATTESTED: {"deliverable": got["deliverable"]},
            TD.DERIVED_INPUTS: got["inputs"],
            TD.DERIVED_INPUTS_SHA256: got["inputs_sha256"]}


def rederive(project: Path, doc: Dict[str, Any]) -> Dict[str, Any]:
    """What this producer would write NOW for `doc` in `project`, without
    writing anything: {answer, provenance} on a WRITE, else {refused: reason}.
    The step-0.5ic gate compares the recorded answer with this instead of
    believing a self-declared provenance record (DELIVC final, finding 1)."""
    got = derive(project, doc)
    if got["status"] != "WRITE":
        return {"refused": f"{got['status']}: {got.get('reason')}"}
    return {"answer": got["budget"], "provenance": provenance_record(got)}


def _sha(text: Any) -> Optional[str]:
    if not isinstance(text, str):
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply(doc: Dict[str, Any], got: Dict[str, Any],
          extra_reason: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(new document, revision record or {}). The owner's answers are copied
    through untouched; only this program's own field, its provenance record,
    the revision log and (once) the `_comment` disclosure change."""
    old = (doc.get("answers") or {}).get(KEY)
    new = copy.deepcopy(doc)
    deliverable, ref = got["deliverable"], got["ref"]
    old_prov_map = doc.get(TD.PROVENANCE_KEY)
    old_prov = (old_prov_map.get(KEY) if isinstance(old_prov_map, dict)
                else None)
    prov_rec = provenance_record(got)
    if old == got["budget"] and old_prov == prov_rec:
        return new, {}
    # WHY it changed, from the recorded structure only (never its prose).
    recorded = (old_prov.get(TD.DERIVED_FROM_ATTESTED)
                if isinstance(old_prov, dict) else None)
    if not isinstance(recorded, dict):
        reason = (f"the previous answer carried no producer provenance, so "
                  f"nothing showed which deliverable it was rendered from; "
                  f"regenerated from the design's documents and the "
                  f"owner-attested deliverable={deliverable} ({ref})")
    elif recorded.get("deliverable") != deliverable:
        reason = (f"the previous answer was rendered from "
                  f"deliverable={recorded.get('deliverable')!r}; the owner "
                  f"attests deliverable={deliverable} ({ref}); regenerated")
    else:
        reason = (f"the design's documents changed; regenerated from them and "
                  f"the owner-attested deliverable={deliverable} ({ref})")
    if extra_reason.strip():
        reason += f". {extra_reason.strip()}"
    rulings = [TD.RULING_DERIVED_FOLLOWS_OWNER, TD.RULING_DERIVED_STRUCTURAL]
    if _RULING_RE.fullmatch(ref) and ref not in rulings:
        rulings.append(ref)
    new["answers"][KEY] = got["budget"]
    prov = new.get(TD.PROVENANCE_KEY)
    if not isinstance(prov, dict):
        prov = {}
        new[TD.PROVENANCE_KEY] = prov
    prov[KEY] = prov_rec
    revision = {
        "field": f"answers.{KEY}",
        "producer": PROGRAM,
        "emitted_by": _pmd.emitted_by(PROGRAM),
        "date": date.today().isoformat(),
        "reason": reason,
        "rulings": rulings,
        "follows_owner_answer": {"deliverable": deliverable,
                                 "citation": got["attestation"]["citation"]},
        "previous": {
            "status": old.get("status") if isinstance(old, dict) else old,
            "rationale_sha256": _sha(old.get("rationale"))
            if isinstance(old, dict) else None,
            "provenance": old_prov if isinstance(old_prov, dict) else None},
    }
    log = new.get(TD.REVISIONS_KEY)
    if not isinstance(log, list):
        log = []
        new[TD.REVISIONS_KEY] = log
    log.append(revision)
    note = (f"answers.{KEY} is DERIVED by {PROGRAM} from input/docs and the "
            f"owner-attested deliverable; see {TD.PROVENANCE_KEY}.{KEY} and "
            f"{TD.REVISIONS_KEY}.")
    comment = new.get("_comment")
    if isinstance(comment, list) and note not in comment:
        comment.append(note)
    elif isinstance(comment, str) and note not in comment:
        new["_comment"] = comment.rstrip() + " " + note
    return new, revision


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Derive step 0.5ic's synthesis_area_budget from the "
                    "design's documents and the owner-attested deliverable "
                    "(R-0929-DELIVERABLE-CONSISTENCY). Writes only that "
                    "field, its provenance and a revision record.")
    p.add_argument("project_dir")
    p.add_argument("--answers", type=Path, default=None,
                   help=f"default: <project>/{ST.DESIGN_ANSWERS_REL}")
    p.add_argument("--out", type=Path, default=None,
                   help="default: rewrite --answers in place")
    p.add_argument("--reason", default="",
                   help="appended to the revision record's reason")
    p.add_argument("--json", type=Path, dest="out_json", default=None)
    args = p.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: project directory not found: {project}",
              file=sys.stderr)
        return 2
    src = args.answers or (project / ST.DESIGN_ANSWERS_REL)
    doc, err = TD.load(src)
    if err or not isinstance(doc, dict) or \
            not isinstance(doc.get("answers"), dict):
        print(f"REFUSED: {PROGRAM} — {err or f'{src}: no answers mapping'}",
              file=sys.stderr)
        return 1
    got = derive(project, doc)
    report: Dict[str, Any] = {"program": PROGRAM,
                              "emitted_by": _pmd.emitted_by(PROGRAM),
                              "project": str(project), "answers": str(src),
                              "status": got["status"],
                              "reason": got.get("reason"),
                              "basis": got.get("basis")}
    rc = got["rc"]
    if got["status"] == "WRITE":
        new, revision = apply(doc, got, args.reason)
        own = [r for r in TD.derived_answer_refusals(new, project)
               if r["field"] == f"answers.{KEY}"]
        if own:                                      # pragma: no cover
            print(f"REFUSED: {PROGRAM} wrote an answer its own gate refuses: "
                  f"{own[0]['message']}", file=sys.stderr)
            return 1
        out = args.out or src
        if revision or out != src:
            try:
                _aa.write_json(out, new)
            except OSError as exc:
                print(f"ERROR: {PROGRAM}: cannot write {out}: {exc}",
                      file=sys.stderr)
                return 1
        report.update({"status": "WRITTEN" if revision else "UNCHANGED",
                       "out": str(out), "budget": got["budget"],
                       "revision": revision or None})
        others = TD.derived_answer_refusals(new, project)
        for r in others:
            print(f"  NOTE (not this program's field): {r['message']}",
                  file=sys.stderr)
        report["other_contradictions"] = len(others)
    if args.out_json:
        try:
            _aa.write_json(args.out_json, report)
        except OSError as exc:
            print(f"ERROR: {PROGRAM}: cannot write the report: {exc}",
                  file=sys.stderr)
            return 1
    line = f"{report['status']}: {PROGRAM} — {KEY}"
    if got["status"] == "WRITE":
        line += (f" status={got['budget']['status']} "
                 f"deliverable={got['deliverable']} "
                 f"stdcell_area_gate={len(got['budget']['stdcell_area_gate'])}"
                 f" -> {report['out']}")
    else:
        line += f" — {got.get('reason')}"
    print(line, file=sys.stdout if rc == 0 else sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
