#!/usr/bin/env python3
"""submission_template_answers.py — the operator's constants, as an answers file.

ENFORCEMENT: BLOCKING as step 0.5ic's third program. rc 0 when it wrote an
answers file or when there is legitimately nothing to answer FROM; rc 1 when a
template was ingested and could not be turned into answers.

THE LINK THAT WAS MISSING
=========================
`tapeout_declaration_gen` refuses to infer, and that refusal is CORRECT:

    the ONLY thing that can change a field is a value in the caller's
    `--answers` file. There is no inference here: not from the floorplan, not
    from the PDK, not from the netlist.

Deriving a die size from the floorplan and then checking the floorplan against
it is self-certification, so the generator is right to refuse. But nobody ever
WROTE an answers file, so every field stayed `NOT_DETERMINED` for every design
in the corpus, and both arms of step 37.5ic were starved by it.

THIS IS NOT INFERENCE. It is transcription of what the OPERATOR handed over.
`docs/research/shuttle_slot_geometry.md`, after measuring:

    The die size is not something a submitter computes. It is a constant the
    operator's template hands them, per slot.

The values here come from `input/submission_template/slots/<slot>.yaml`, which
`submission_template_ingest` wrote from the operator's own published template,
which `submission_template_fetch` read out of the operator's own digest-pinned
image. Nothing on that path is computed from this design's own artefacts, which
is exactly what makes the check downstream mean something.

THE SPLIT, AND WHY IT IS NOT NEGOTIABLE
=======================================
Of the declaration's 18 questions, the operator answers SOME and the DESIGN
answers the rest. Answering a design question from the operator's template
would be inventing an answer the design never gave — the same defect one layer
up — so the design's questions are left `NOT_DETERMINED` and stay a non-pass
until the design states them.

    THE OPERATOR'S      top_cell, die_area_um, die_origin_um,
                        database_unit_um, fp_sizing, seal_ring_required,
                        seal_ring_marker_layer, forbidden_layers
                        — terms of submission, identical for every design in
                          that slot, and none of them derived from this design.

    THE DESIGN'S        deliverable, core_area_um, every pad_*, and
                        seal_ring_script
                        — choices inside the die, or a PDK path. The operator
                          says a ring is REQUIRED; which script builds it is
                          not its business, so that one is left open even
                          though it sits in the same section.

A FIELD WITH NO SOURCE IS OMITTED, NEVER DEFAULTED. If a template does not
carry a value, the key is absent from the answers file and the generator's
`NOT_DETERMINED` stands. An emitted default would read downstream exactly like
a term the operator stated.

USAGE
-----
    python3 submission_template_answers.py <project> [--slot NAME] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _submission_template as _st                            # noqa: E402
import _tapeout_declaration as _decl                          # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402

ATTRIBUTION = "submission_template_answers"
ANSWERS_REL = "input/submission_template/operator_answers.json"
REPORT_REL = "reports/phase1/submission_template_answers.json"

PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "NOT_APPLICABLE"
#: An operator exists and the design has not settled WHICH of its slots it
#: bought. That is not a malfunction of this program: the question is open, and
#: `tapeout_declaration_gen` is built to CARRY an unanswered question rather
#: than to be spared one. rc 0, and the refusal that matters lands later at
#: step 37.5ic where the layout is actually judged. rc 1 stays reserved for
#: something BROKEN — a template or source that cannot be read, or one that
#: changed after it was ingested.
NOT_DETERMINED = "NOT_DETERMINED"

#: Declaration keys this file is ALLOWED to answer. Anything outside it is the
#: design's to state, and is left NOT_DETERMINED however tempting the template
#: makes it. Written as an allow-list so that a new key added to the
#: declaration is NOT silently answered from an operator's template.
OPERATOR_ANSWERABLE = (
    "top_cell", "die_area_um", "die_origin_um", "database_unit_um",
    "fp_sizing", "seal_ring_required", "seal_ring_marker_layer",
)


def _absolute_sizing() -> str:
    """The declaration's own word for an absolutely-sized floorplan."""
    for q in _decl.QUESTIONS:
        if q.key == "fp_sizing":
            for c in (q.choices or ()):
                if str(c).strip().lower() == "absolute":
                    return c
    return "absolute"


def _rect_from_die_area(raw: Any) -> Optional[List[float]]:
    """`"0 0 W H"` -> `[0, 0, W, H]`, or None when it is not four numbers."""
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            return [float(v) for v in raw]
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, str):
        return None
    parts = raw.replace(",", " ").split()
    if len(parts) != 4:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def _source_record(project: Path, slot: Dict[str, Any]
                   ) -> Tuple[Dict[str, Any], List[str]]:
    """The FETCHED record the ingest read, re-verified against its own hash.

    WHY REACH PAST THE INGEST AT ALL. `slot_record` keeps the keys its schema
    models — slot, die_area, ring, pads — and lists the rest under
    `pads.unmatched_list_keys`. The operator also states a top cell, a database
    unit and which layers it refuses in which direction, and those are terms of
    submission too. Teaching the general ingest one operator's extra keys would
    push operator-specific shape into the shared core, which is the thing the
    adapter exists to prevent.

    SO THIS FOLLOWS THE POINTER THE INGEST ITSELF RECORDED, and re-checks the
    hash the ingest itself computed before reading a byte. A source file that
    changed after ingestion is refused rather than read: the whole value of the
    chain is that the number in the declaration is the number the operator
    published, and a silently-edited source would break exactly that.
    """
    notes: List[str] = []
    src = slot.get("source_file")
    want = slot.get("source_sha256")
    if not isinstance(src, str) or not src:
        return {}, ["the ingested slot names no source_file, so the operator's "
                    "remaining terms could not be read"]
    p = Path(src)
    if not p.is_absolute():
        p = project / src
    if not p.is_file():
        return {}, [f"the ingested slot points at {src}, which is not there "
                    f"now; nothing was read from it"]
    data = p.read_bytes()
    if isinstance(want, str) and want:
        import hashlib
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            return {}, [
                f"{p.name} changed since it was ingested (recorded "
                f"{want[:16]}…, now {got[:16]}…). A source edited after "
                f"ingestion is refused, not read: the declaration would then "
                f"carry a number the operator never published."]
    try:
        return json.loads(data.decode("utf-8", "replace")), notes
    except ValueError as exc:
        return {}, [f"{p.name} is not readable as the fetched record: {exc}"]


def answers_from_slot(slot: Dict[str, Any],
                      source: Optional[Dict[str, Any]] = None
                      ) -> Tuple[Dict[str, Any], List[str]]:
    """(answers, notes). Only what the operator actually stated.

    `slot` is the INGEST's normalised record (the authority for the slot name,
    the die rectangle and the ring); `source` is the fetched record it points
    at, for the terms the ingest's schema does not model.
    """
    out: Dict[str, Any] = {}
    notes: List[str] = []
    src = source or {}

    top = src.get("TOP_CELL")
    if isinstance(top, str) and top.strip():
        out["top_cell"] = top.strip()

    die = slot.get("die_area") or {}
    rect = _rect_from_die_area(die.get("rect") or die.get("raw"))
    if rect:
        out["die_area_um"] = rect
        out["die_origin_um"] = [rect[0], rect[1]]
        # ABSOLUTE, because the operator handed a rectangle and refuses on an
        # exact match to it. A relative sizing would make the die a consequence
        # of the design's own utilisation, which is the number it is checked
        # against — the self-certification this whole path exists to avoid.
        # READ FROM THE DECLARATION, not typed. Measured: the literal
        # "ABSOLUTE" was refused as DECLARATION_ENUM_INVALID — the enum is
        # lower-case. A value spelled in two places is one place to get wrong,
        # and the generator is the authority on its own vocabulary.
        out["fp_sizing"] = _absolute_sizing()
    elif die:
        notes.append(
            f"the template's DIE_AREA ({die.get('raw')!r}) is not four "
            f"numbers, so no die rectangle was transcribed; the declaration's "
            f"die_area_um stays NOT_DETERMINED rather than take a guess")

    dbu = src.get("DATABASE_UNIT_UM")
    if isinstance(dbu, (int, float)) and dbu > 0:
        out["database_unit_um"] = dbu

    markers = src.get("REQUIRED_MARKER_LAYERS") or []
    if markers:
        out["seal_ring_required"] = True
        if len(markers) == 1:
            m = markers[0]
            out["seal_ring_marker_layer"] = (
                f"{m.get('name')} {m.get('layer')}/{m.get('datatype')}")
        else:
            notes.append(
                f"the operator requires {len(markers)} marker layers "
                f"({[m.get('name') for m in markers]}); which one is the SEAL "
                f"RING's is not stated, so seal_ring_marker_layer is left "
                f"NOT_DETERMINED instead of picking one")
    return out, notes


def build(project: Path, slot_name: str = "") -> Dict[str, Any]:
    rep: Dict[str, Any] = {
        "program": ATTRIBUTION, "project": str(project), "verdict": FAIL,
        "reason": "", "slot": None, "slot_file": None,
        "answers": {}, "notes": [], "left_to_the_design": [],
    }
    slots_dir = project / _st.SLOTS_DIR_REL
    files = sorted(p for p in slots_dir.glob("*.yaml") if p.is_file()) \
        if slots_dir.is_dir() else []
    if not files:
        rep["verdict"] = NOT_APPLICABLE
        rep["reason"] = (
            f"no {_st.SLOTS_DIR_REL}/*.yaml, so no operator stated any terms "
            f"for this design. That is the legitimate case for a PDK with no "
            f"shuttle, and it is NOT a licence to answer these questions from "
            f"anywhere else — the declaration's fields stay NOT_DETERMINED "
            f"until the design states them.")
        return rep

    chosen: Optional[Path] = None
    if slot_name.strip():
        want = slot_name.strip()
        for p in files:
            try:
                doc = json.loads(p.read_text(errors="replace"))
            except (OSError, ValueError):
                continue
            if str(doc.get("SLOT", p.stem)).strip() == want:
                chosen = p
                break
        if chosen is None:
            rep["verdict"] = NOT_DETERMINED
            rep["reason"] = (
                f"the design declares slot {want!r} and the operator's template "
                f"ships {[p.stem for p in files]}. A slot nobody sells cannot "
                f"be transcribed, and substituting one that is on offer would "
                f"answer with terms the design never agreed to.")
            return rep
    else:
        rep["verdict"] = NOT_DETERMINED
        rep["reason"] = (
            f"the operator ships {len(files)} slot(s) "
            f"({[p.stem for p in files]}) and the design has not said which it "
            f"purchased. Picking one would put a die size the design never "
            f"chose into its own declaration — state it with --slot. This "
            f"holds even when the operator ships exactly ONE: what it sells "
            f"today is not what this design bought, and an operator that adds "
            f"a second slot tomorrow would silently move a design that never "
            f"chose.")
        return rep

    try:
        slot = json.loads(chosen.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        rep["reason"] = f"{chosen} could not be read as a slot record: {exc}"
        return rep

    source, src_notes = _source_record(project, slot)
    answers, notes = answers_from_slot(slot, source)
    notes = src_notes + notes
    rep["slot"] = str(slot.get("SLOT", chosen.stem))
    rep["slot_file"] = str(chosen.relative_to(project))
    rep["answers"] = answers
    rep["notes"] = notes
    rep["left_to_the_design"] = sorted(
        q.key for q in _decl.QUESTIONS if q.key not in answers)

    stray = sorted(set(answers) - set(OPERATOR_ANSWERABLE))
    if stray:
        rep["reason"] = (
            f"this program tried to answer {stray}, which is the DESIGN's to "
            f"state. An operator's template cannot answer a question about "
            f"what is inside the die.")
        rep["answers"] = {}
        return rep

    if not answers:
        rep["reason"] = (
            f"the slot record {chosen.name} states none of the operator's "
            f"terms this flow transcribes, so nothing was written. "
            f"{'; '.join(notes)}")
        return rep

    rep["verdict"] = PASS
    rep["reason"] = (
        f"{len(answers)} operator term(s) transcribed from {rep['slot_file']} "
        f"for slot {rep['slot']}: {', '.join(sorted(answers))}. "
        f"{len(rep['left_to_the_design'])} question(s) remain the design's and "
        f"stay NOT_DETERMINED.")
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Transcribe the operator's stated terms into the answers "
                    "file `tapeout_declaration_gen --answers` reads.")
    p.add_argument("project", type=Path)
    p.add_argument("--slot", default="",
                   help="Which slot the design purchased. Required when the "
                        "template ships more than one; never guessed.")
    p.add_argument("--design-answers", type=Path, default=None,
                   help="The DESIGN's own answers file, merged underneath the "
                        "operator's. The operator wins on any key both state: "
                        "its terms are conditions of submission, not opinions, "
                        "and a design that disagrees with them is refused by "
                        "the operator's own tool anyway. Every override is "
                        "recorded by key so the substitution is auditable.")
    p.add_argument("--technology-json", type=Path, default=None,
                   help="The `submission_template_fetch` report this run "
                        "wrote. Its `technology` record carries what the tech "
                        "LEF of the run's own PDK declares, with the "
                        "path:line it was read at. Those facts are published "
                        "OVER anything the design or the operator answered, "
                        "and a design answer that disagrees with them is "
                        "refused by name — see "
                        "`_tapeout_declaration.ANSWERED_BY_TECHNOLOGY`.")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--json", type=Path, dest="out_json", default=None)
    args = p.parse_args(argv)

    if not args.project.is_dir():
        print(f"ERROR: project directory not found: {args.project}",
              file=sys.stderr)
        return 2

    rep = build(args.project, args.slot)

    # THE DESIGN'S OWN ANSWERS, UNDERNEATH. `tapeout_declaration_gen` takes ONE
    # answers file, so the precedence has to be decided HERE rather than left
    # to whichever file happened to be passed. The operator wins: its values are
    # terms of submission, and a design that states a different die size does
    # not get a different die — it gets refused by the operator's own tool. The
    # merge is recorded key by key so a reader can see what was overridden and
    # by whom, instead of finding a value it cannot account for.
    merged = dict(rep.get("answers") or {})
    if args.design_answers and args.design_answers.is_file():
        try:
            doc = json.loads(args.design_answers.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            rep["notes"].append(f"{args.design_answers} unreadable: {exc}")
            doc = {}
        # THE WHOLE DOCUMENT IS CARRIED, not just its `answers` mapping.
        # MEASURED: the design's file also carries siblings this program does
        # not model — `operator_template.absent_reason`, the synthesis area
        # budget — and `tapeout_declaration_gen` READS THEM. A merge that
        # rebuilt the document from the `answers` key alone silently dropped
        # them, and the declaration check went from rc 0 to rc 2 for a design
        # that had answered correctly. Whatever this program does not model, it
        # must carry through untouched rather than discard.
        carried = dict(doc) if isinstance(doc, dict) else {}
        design = doc.get("answers") if isinstance(doc.get("answers"), dict) \
            else (doc if isinstance(doc, dict) else {})
        overridden, taken = [], []
        for k, v in design.items():
            if k in merged:
                if merged[k] != v:
                    overridden.append(k)
                continue
            merged[k] = v
            taken.append(k)
        rep["design_answers_file"] = str(args.design_answers)
        rep["from_the_design"] = sorted(taken)
        rep["operator_overrode"] = sorted(overridden)
        if rep["verdict"] == NOT_APPLICABLE and taken:
            # No operator, but the design answered: that file must still reach
            # the generator, or the design's own words are dropped on the floor.
            rep["verdict"] = PASS
            rep["reason"] = (
                f"no operator states terms for this design, so the answers file "
                f"carries only its own: {', '.join(taken)}.")
        rep["answers"] = merged
        rep["_carried"] = carried

    # THE TECHNOLOGY'S OWN ANSWER, PUBLISHED LAST (#2070).
    #
    # LAST because it is not an opinion in a precedence order. `database_unit_um`
    # asks what a technology file declares; the design is not a party to that
    # question and neither is the operator, so what either of them wrote about
    # it cannot win. Measured: two designs each name TWO PDK families whose tech
    # LEFs declare DIFFERENT units, and one answers file drives runs on both —
    # so a single scalar there is wrong for one of the two runs, whichever it is.
    #
    # A DISAGREEMENT IS REFUSED BY NAME, with both values in the message, and it
    # travels into the declaration so `tapeout_declaration_gen` exits 1 on it.
    # AGREEMENT is accepted with a note, never with silence: a design that
    # happens to be right about the technology is still not the authority on it,
    # and the note is how the next reader knows which of the two we published.
    #
    # AND WHEN THE TECHNOLOGY DID NOT ANSWER, NEITHER DOES THE DESIGN. Measured
    # while building this: a run whose PDK the design does not name is refused
    # by the fetch, which then transcribes nothing — and the design's own
    # scalar sailed through into the declaration as `database_unit_um`, read
    # downstream as a measured technology fact. A claim that was never checked
    # against a technology must not be published as one, so the key is STRIPPED
    # whenever this producer was pointed at a technology record, and only a
    # transcription puts it back. NOT_DETERMINED is the honest answer there; the
    # design's number is kept in the report as an unpublished claim.
    facts = {}
    tech_why = None
    if args.technology_json is not None:
        if not args.technology_json.is_file():
            rep["notes"].append(
                f"--technology-json {args.technology_json} is not on disk, so "
                f"no technology fact was transcribed. That is NOT the same as "
                f"a technology that declares none")
        else:
            try:
                fetched = json.loads(
                    args.technology_json.read_text(errors="replace"))
            except (OSError, ValueError) as exc:
                rep["notes"].append(f"{args.technology_json} unreadable: {exc}")
                fetched = {}
            facts = (fetched or {}).get("technology") or {}
            if not facts:
                tech_why = (
                    f"{args.technology_json} records no `technology` for this "
                    f"run — the fetch transcribed none (see its own verdict "
                    f"and reason). Nothing was measured, so nothing is "
                    f"published")
    if args.technology_json is not None:
        merged = dict(rep.get("answers") or {})
        # WHOSE claim is being refused, named exactly. The merge above records
        # which keys came from the design, so a refusal says "the design"
        # when it was the design and does not blame it when it was not.
        _from_design = set(rep.get("from_the_design") or [])
        claimed_by = ("the design's answers file"
                      if _from_design & set(_decl.TECHNOLOGY_ANSWERED)
                      else "the answers file this run assembled")
        refusals = _decl.technology_refusals(merged, facts, claimed_by)
        agreed, unread = [], []
        for key in _decl.TECHNOLOGY_ANSWERED:
            fact = facts.get(key) or {}
            if fact.get("value") is None:
                _why = (fact.get("unavailable") or tech_why
                        or "the fetch recorded no fact for this key")
                unread.append(f"{key}: NOT_DETERMINED — {_why}")
                continue
            said = merged.get(key)
            if _decl.is_answered(said) and said == fact["value"]:
                agreed.append(
                    f"{key}: the answers file states {said!r} and the "
                    f"technology this run targets declares the same "
                    f"({fact.get('statement')} at {fact.get('source')} for PDK "
                    f"{fact.get('pdk')!r}). Accepted — and published from the "
                    f"technology, which is where it comes from either way")
        # THE STRIP. Unconditional on this branch and BEFORE any value is
        # written back, so a key can only ever be published by a transcription.
        withheld = {}
        for key in _decl.TECHNOLOGY_ANSWERED:
            fact = facts.get(key) or {}
            if fact.get("value") is not None:
                continue
            if _decl.is_answered(merged.get(key)):
                withheld[key] = merged[key]
            merged.pop(key, None)
        if withheld:
            unread.append(
                f"withheld from the declaration: {withheld} — "
                f"{tech_why or 'the technology this run targets was not read'}. "
                f"{', '.join(sorted(withheld))} is answered by the TECHNOLOGY "
                f"or by nobody; an unverified claim about it is not published")
        rep["technology_withheld"] = withheld
        record = dict(facts)
        if refusals:
            record["refusals"] = refusals
        rep["technology"] = record
        rep["technology_refusals"] = [r["rule"] for r in refusals]
        rep["technology_agreed"] = agreed
        rep["technology_unreadable"] = unread
        rep["notes"] += agreed + unread + [r["message"] for r in refusals]
        doc_tech = dict(rep.get("_carried") or {})
        for key in _decl.TECHNOLOGY_ANSWERED:
            fact = facts.get(key) or {}
            if fact.get("value") is not None:
                merged[key] = fact["value"]
        rep["answers"] = merged
        # Only a real record is published. An empty one would be a
        # provenance block asserting that a technology was consulted.
        if record:
            doc_tech[_decl.TECHNOLOGY_KEY] = record
        rep["_carried"] = doc_tech
        if rep["verdict"] in (NOT_APPLICABLE, NOT_DETERMINED) and any(
                (facts.get(k) or {}).get("value") is not None
                for k in _decl.TECHNOLOGY_ANSWERED):
            # The technology answered even though no operator did. That file
            # must still reach the generator, or the transcription is dropped
            # on the floor exactly like the design's own answers used to be.
            rep["verdict"] = PASS
            rep["reason"] = (
                (rep["reason"] + " ") if rep["reason"] else "") + (
                "The technology this run targets answered "
                f"{', '.join(k for k in _decl.TECHNOLOGY_ANSWERED)}, so the "
                "answers file carries that transcription.")

    if rep["verdict"] == PASS:
        out = args.out or (args.project / ANSWERS_REL)
        out.parent.mkdir(parents=True, exist_ok=True)
        doc_out = dict(rep.get("_carried") or {})
        doc_out.setdefault("schema", _decl.SCHEMA)
        doc_out["answers"] = rep["answers"]
        doc_out["source"] = {"program": ATTRIBUTION, "slot": rep["slot"],
                             "slot_file": rep["slot_file"],
                             "from_the_design": rep.get("from_the_design", []),
                             "operator_overrode":
                                 rep.get("operator_overrode", [])}
        atomic_write_text(out, json.dumps(doc_out, indent=2) + "\n",
                          encoding="utf-8")
        rep["answers_file"] = str(out.relative_to(args.project))

    j = args.out_json or (args.project / REPORT_REL)
    j.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(j, json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    rep.pop("_carried", None)
    print(json.dumps(rep, indent=2))
    print(f"[{rep['verdict']}] {ATTRIBUTION}: {rep['reason']}")
    return 0 if rep["verdict"] in (PASS, NOT_APPLICABLE,
                                   NOT_DETERMINED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
