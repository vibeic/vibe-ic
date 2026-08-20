#!/usr/bin/env python3
"""pad_assignment_gen — step 15.5ic's FIRST producer: write the pad-ring config
from a DECLARED source, or refuse and name the field nobody answered.

THE HOLE THIS CLOSES, MEASURED BEFORE IT WAS CODED
==================================================
`pad_ring_gen` reads its whole geometry out of ONE file,
`phase3/stage3/pnr/pad_assignment.json`. Measured on v1.11.7:

    grep -rn pad_assignment --include=*.py --include=*.yaml --include=*.json .
      -> 5 hits, every one of them a READER inside `_pad_ring.py` /
         `pad_ring_gen.py`. NOTHING IN THE TREE WRITES IT.

    python3 programs/pad_ring_gen.py <a project carrying an operator slot
                                      template with four pad lists in it>
      -> verdict: SKIP, rc 2, "absent variable" x 13

So step 15.5ic could only ever SKIP — and not only on the self-tape-out path
the step's condition excluded, but on the SHUTTLE path too, the one path the
condition admitted. A step wired to a file with no producer is the same defect
as an unwired step, and it had been shipping.

Meanwhile the two artefacts that DO carry the answers were already being
written, by step 0.5ic, on every run:

    reports/phase1/submission_template.json   the operator's slot, PARSED —
        `submission_template_ingest` already reads PAD_SOUTH / PAD_EAST /
        PAD_NORTH / PAD_WEST out of the slot yaml into `ingest.slots[].pads`,
        and then stops. That parse is this program's input; the slot file is
        NOT re-parsed here, because two parsers of one file drift and the
        second one is always the one nobody re-measures.
    input/submission_template/tapeout_declaration.json   the design's own
        answers — `_tapeout_declaration`'s section `2B_pad_ring`, whose eight
        questions carry `consumer="pad_ring_gen"` in their own definition.

This program is the wire between them. It computes NOTHING.

WHAT IT WILL NOT DO
===================
It never invents a pad order, a site name, a spacing, a rotation, a corner
master, a filler or a signal map. Every one of the 13 variables comes from a
source that DECLARED it, and each is stamped with which source that was. A
variable no source declared is a refusal that names the variable and, when it
is a declaration question, names the question — never a default. A default is
a fake number wearing a real number's clothes: it reads as an answer at
`pad_ring_gen`, survives into `padring.def`, and the one thing it cannot do is
be wrong in a way anybody notices.

TWO SOURCES THAT DISAGREE ARE A REFUSAL, NOT A PREFERENCE
=========================================================
An operator template pins the pads for its slot; the design declares its own.
When both are present and they differ, picking one silently records a pin-out
nobody chose — and the losing value is exactly the one a reader would have to
see to notice. So a disagreement is `PAD_CONFIG_SOURCES_DISAGREE`, naming the
variable, BOTH values and BOTH source paths, and nothing is written.

Precedence therefore only ever applies where the sources AGREE, which is where
precedence cannot change an answer. It is recorded anyway (`provenance`) so a
reader can see which document each variable came out of.

THIS PROGRAM'S OWN OUTPUT IS NOT ONE OF ITS SOURCES
===================================================
An existing `pad_assignment.json` is read as a source — a human or an upstream
tool may legitimately have written one, and that is a declaration like any
other. But a file THIS program wrote carries `_provenance.written_by`, and one
of those is skipped and replaced. A checker that re-ingests its own last
verdict agrees with itself forever; that failure has already happened once in
this tree (step 26's `_discover`) and it is not being reintroduced here.

For the same reason a refusal DELETES a stamped stale config: leaving one
behind would let `pad_ring_gen` place a ring from geometry this run refused.
An UNSTAMPED file is never deleted — it is somebody else's input and this
program does not own it.

EXIT
    0  PASS — every one of the 13 variables is declared; the config is written.
    2  SKIP — no source declared ANY of them, i.e. nobody was ever asked. No
       config is written and `pad_ring_gen` skips downstream exactly as it does
       today. Non-zero on purpose: the flow reads exit 2 as its "could not
       measure" tier, never as a pass.
    1  FAIL — a source declared SOME of the contract and not the rest, or two
       sources disagree, or a declared answer is the wrong shape. Somebody
       wrote it and it is wrong, which is a different fact from nobody having
       written it, and the two must not buy the same exit code.

chip-AGNOSTIC: no chip, vendor, SKU, foundry, PDK or process-node literal. The
only fixed strings are upstream's own variable names, this module's question
keys and this flow's relative paths.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:                                  # pragma: no cover
    sys.path.insert(0, str(_HERE))

from _atomic_artefact import write_json as atomic_write_json    # noqa: E402

import _pad_ring as PR                                          # noqa: E402
import _submission_template as ST                               # noqa: E402
import _tapeout_declaration as TD                               # noqa: E402

PROGRAM = "pad_assignment_gen"
SCHEMA = "vibe-ic/pad_assignment/1"
REPORT_REL = "reports/phase3/pad_assignment.json"

#: The key this program stamps its own output with, so a later run reads its
#: own file as OUTPUT and not as a source. See "THIS PROGRAM'S OWN OUTPUT".
PROVENANCE_KEY = "_provenance"

PASS, FAIL, SKIP = 0, 1, 2

# --------------------------------------------------------------------------- #
# The 8 declaration questions -> the 13 placer variables.
#
# This is the 13:8 grouping `_tapeout_declaration` records in its own
# "SECTION 2B" comment, written out as data. The sub-keys are the ones each
# question's PROMPT shows the answerer ("{south: [...], east: ...}",
# "{horizontal: ..., vertical: ..., corner: ...}"), so an answer written
# against the prompt is readable here unchanged.
# --------------------------------------------------------------------------- #
#: question key -> {sub-key -> placer variable}. A question with no sub-keys
#: maps its whole answer to one variable.
SIDE_SUBKEY: Dict[str, str] = {"south": "PAD_SOUTH", "east": "PAD_EAST",
                               "north": "PAD_NORTH", "west": "PAD_WEST"}
ROTATION_SUBKEY: Dict[str, str] = {
    "horizontal": "PAD_ROTATION_HORIZONTAL",
    "vertical": "PAD_ROTATION_VERTICAL",
    "corner": "PAD_ROTATION_CORNER",
}
#: question key -> placer variable, for the six that map one-to-one.
SCALAR_QUESTION: Dict[str, str] = {
    "pad_site_name": "PAD_SITE_NAME",
    "pad_corner_site_name": "PAD_CORNER_SITE_NAME",
    "pad_edge_spacing_um": "PAD_EDGE_SPACING",
    "pad_corner_master": "PAD_CORNER",
    "pad_fillers": "PAD_FILLERS",
    "pad_signal_map": "SIGNAL_MAP",
}
QUESTION_OF_VAR: Dict[str, str] = {}
for _sub, _var in SIDE_SUBKEY.items():
    QUESTION_OF_VAR[_var] = f"pad_order_by_side.{_sub}"
for _sub, _var in ROTATION_SUBKEY.items():
    QUESTION_OF_VAR[_var] = f"pad_rotations.{_sub}"
for _q, _var in SCALAR_QUESTION.items():
    QUESTION_OF_VAR[_var] = _q

# LOUD ON DRIFT, at import. A variable added to the placer's contract, or a
# question renamed in the declaration, must be a failure here and not a
# silently unmapped field that reaches a reader as "nobody declared it".
_mapped = set(QUESTION_OF_VAR)
if _mapped != set(PR.REQUIRED_VARS):                            # pragma: no cover
    raise AssertionError(
        f"{PROGRAM}: the question->variable map covers {sorted(_mapped)} but "
        f"the placer requires {sorted(PR.REQUIRED_VARS)}")
_2b = {q.key for q in TD.QUESTIONS if q.section == TD.SECTION_PAD_RING}
_used = set(SCALAR_QUESTION) | {"pad_order_by_side", "pad_rotations"}
if _used != _2b:                                                # pragma: no cover
    raise AssertionError(
        f"{PROGRAM}: this map reads {sorted(_used)} but section "
        f"{TD.SECTION_PAD_RING} declares {sorted(_2b)}")

#: The operator's slot file can only ever declare these four — measured on the
#: ingest's own parse, which matches `PAD_SOUTH|EAST|NORTH|WEST` and nothing
#: else in the placer's contract. 4 of 13; the other 9 are the design's.
OPERATOR_VARS: Tuple[str, ...] = tuple(SIDE_SUBKEY.values())


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
def _source(path: str, kind: str, **kw: Any) -> Dict[str, Any]:
    rec: Dict[str, Any] = {"path": path, "kind": kind, "present": False,
                           "readable": None, "declared": {}, "notes": []}
    rec.update(kw)
    return rec


def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """(document, None) or (None, why-not). NEVER collapses the two.

    "I could not read it" and "I read it and it declared nothing" must not
    produce the same record: the first is an unusable source and the second is
    a source that answered.
    """
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(errors="replace")), None
    except (ValueError, OSError) as exc:
        return None, f"{exc}"


def existing_config(project: Path) -> Dict[str, Any]:
    """A `pad_assignment.json` somebody ELSE wrote, as a source.

    Our own stamped output is not a source (see the module docstring); it is
    recorded as skipped, with the stamp that identified it.
    """
    path = project / PR.ASSIGNMENT_REL
    rec = _source(PR.ASSIGNMENT_REL, "explicit pad-ring config",
                  ours=False)
    doc, err = _read_json(path)
    rec["present"] = path.is_file()
    if not rec["present"]:
        rec["notes"].append("no explicit config was written by hand or by an "
                            "upstream tool")
        return rec
    if err is not None:
        rec["readable"] = False
        rec["notes"].append(f"present but unreadable: {err}")
        return rec
    rec["readable"] = True
    if not isinstance(doc, dict):
        rec["notes"].append(
            f"present but its top level is {type(doc).__name__}, not a "
            f"mapping, so it declares nothing this program can read")
        return rec
    stamp = doc.get(PROVENANCE_KEY)
    if isinstance(stamp, dict) and stamp.get("written_by") == PROGRAM:
        rec["ours"] = True
        rec["notes"].append(
            f"skipped as a source: this file carries "
            f"{PROVENANCE_KEY}.written_by={PROGRAM!r}, i.e. a previous run of "
            f"this program wrote it. A producer that reads its own last output "
            f"back agrees with itself forever")
        return rec
    for var in PR.REQUIRED_VARS:
        val = doc.get(var)
        if val is None or val == "":
            continue
        rec["declared"][var] = val
    if not rec["declared"]:
        rec["notes"].append("present and declares none of the 13 variables")
    return rec


def operator_pads(project: Path) -> Dict[str, Any]:
    """The operator slot's four pad lists, taken from the INGEST'S PARSE.

    The slot yaml is deliberately not opened here. `submission_template_ingest`
    already parses it (`ingest.slots[].pads.lists`) and that record is a
    declared step output; a second parser of the same file is a second thing to
    keep in step with the operator's spelling, and it is always the one nobody
    re-measures.
    """
    path = project / ST.REPORT_REL
    rec = _source(ST.REPORT_REL, "operator slot template (ingested)",
                  declared_slot=None, slots_shipped=[])
    doc, err = _read_json(path)
    rec["present"] = path.is_file()
    if not rec["present"]:
        rec["notes"].append(
            "step 0.5ic wrote no ingest report, so no operator template was "
            "read on this run")
        return rec
    if err is not None:
        rec["readable"] = False
        rec["notes"].append(f"present but unreadable: {err}")
        return rec
    rec["readable"] = True
    ingest = (doc or {}).get("ingest") if isinstance(doc, dict) else None
    if not isinstance(ingest, dict):
        rec["notes"].append("the report carries no `ingest` block")
        return rec
    slots = [s for s in (ingest.get("slots") or []) if isinstance(s, dict)]
    rec["slots_shipped"] = [str(s.get("slot")) for s in slots]
    declared = ingest.get("declared_slot")
    rec["declared_slot"] = declared
    if not slots:
        rec["notes"].append(
            "no operator template was ingested — this design targets no "
            "shuttle slot, so the operator declares no pads for it")
        return rec
    if declared is None:
        rec["notes"].append(
            f"a template was ingested and no slot was declared, so which of "
            f"the {len(slots)} shipped slot(s) pins this design's pads is not "
            f"knowable here. Refused rather than guessed; step 0.5ic's own "
            f"gate refuses this as SLOT_NOT_DECLARED")
        return rec
    chosen = [s for s in slots if str(s.get("slot")) == str(declared)]
    if not chosen:
        rec["notes"].append(
            f"the declared slot {declared!r} is not among the ingested slots "
            f"{rec['slots_shipped']}, so no pad list can be attributed to it")
        return rec
    pads = (chosen[0].get("pads") or {}) if isinstance(chosen[0], dict) else {}
    lists = [l for l in (pads.get("lists") or []) if isinstance(l, dict)]
    by_key = {str(l.get("key") or "").strip().upper(): l for l in lists}
    for var in OPERATOR_VARS:
        entry = by_key.get(var)
        if entry is None:
            continue
        raw = entry.get("raw")
        if isinstance(raw, list):
            rec["declared"][var] = list(raw)
    matched = [k for k in by_key if k not in OPERATOR_VARS]
    if matched:
        rec["notes"].append(
            f"the slot also declares {sorted(matched)}, which name no "
            f"per-side list in the placer's contract and are not read here")
    if not rec["declared"]:
        rec["notes"].append(
            f"slot {declared!r} declares no per-side pad list "
            f"({list(OPERATOR_VARS)}); the design's own declaration is then "
            f"the only source for the pad order")
    return rec


def declaration_pads(project: Path) -> Dict[str, Any]:
    """Section `2B_pad_ring` of the design's own tape-out declaration.

    An answer of the wrong SHAPE is a refusal recorded here, not a value
    passed on: `_tapeout_declaration.validate` deliberately does not inspect
    the inside of a `list`-kind answer, so this is where a
    `pad_order_by_side` that is not a mapping, or a `pad_rotations` missing a
    sub-key, is caught — named, with the sub-key it went without.
    """
    path = project / TD.DECLARATION_REL
    rec = _source(TD.DECLARATION_REL, "the design's tape-out declaration "
                                      "(section 2B_pad_ring)",
                  unanswered=[], shape_refusals=[])
    doc, err = _read_json(path)
    rec["present"] = path.is_file()
    if not rec["present"]:
        rec["notes"].append(
            "step 0.5ic wrote no declaration, so this design has never been "
            "asked the eight pad-ring questions")
        return rec
    if err is not None:
        rec["readable"] = False
        rec["notes"].append(f"present but unreadable: {err}")
        return rec
    rec["readable"] = True
    if not isinstance(doc, dict):
        rec["notes"].append(
            f"present but its top level is {type(doc).__name__}, not a mapping")
        return rec

    def _refuse(rule: str, message: str) -> None:
        rec["shape_refusals"].append({"rule": rule, "message": message})

    for qkey, sub_map in (("pad_order_by_side", SIDE_SUBKEY),
                          ("pad_rotations", ROTATION_SUBKEY)):
        val = TD.answer(doc, qkey)
        if val == TD.NOT_DETERMINED:
            rec["unanswered"].extend(sorted(sub_map.values()))
            continue
        if not isinstance(val, dict):
            _refuse("PAD_DECLARATION_SHAPE_INVALID",
                    f"declaration question {qkey!r} is "
                    f"{type(val).__name__}, not the mapping its own prompt "
                    f"asks for ({{{', '.join(sub_map)}}})")
            rec["unanswered"].extend(sorted(sub_map.values()))
            continue
        lowered = {str(k).strip().lower(): v for k, v in val.items()}
        extra = sorted(set(lowered) - set(sub_map))
        if extra:
            _refuse("PAD_DECLARATION_SHAPE_INVALID",
                    f"declaration question {qkey!r} carries sub-key(s) "
                    f"{extra} that name no side/orientation this placer has "
                    f"({sorted(sub_map)})")
        for sub, var in sub_map.items():
            if sub not in lowered or not TD.is_answered(lowered[sub]):
                rec["unanswered"].append(var)
                continue
            rec["declared"][var] = lowered[sub]

    for qkey, var in SCALAR_QUESTION.items():
        val = TD.answer(doc, qkey)
        if val == TD.NOT_DETERMINED:
            rec["unanswered"].append(var)
            continue
        rec["declared"][var] = val

    rec["unanswered"] = sorted(set(rec["unanswered"]))
    if not rec["declared"]:
        rec["notes"].append(
            f"the declaration exists and all eight of section "
            f"{TD.SECTION_PAD_RING} are {TD.NOT_DETERMINED} — a legal state, "
            f"and one that declares no pad ring")
    return rec


# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #
def _same(a: Any, b: Any) -> bool:
    """Do two sources declare the SAME value?

    Compared on the JSON they would each write, so `["a"]` from a yaml parse
    and `["a"]` from a declaration compare equal, and `1` and `1.0` do not
    silently disagree.
    """
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    try:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except (TypeError, ValueError):                             # pragma: no cover
        return a == b


def merge(sources: List[Dict[str, Any]]
          ) -> Tuple[Dict[str, Any], Dict[str, str], List[str],
                     List[Dict[str, Any]]]:
    """(config, provenance, absent, disagreements).

    `sources` is in precedence order, and precedence is only ever consulted
    where the sources AGREE — a disagreement is a refusal, so precedence can
    never pick a winner over a loser.
    """
    config: Dict[str, Any] = {}
    provenance: Dict[str, str] = {}
    disagreements: List[Dict[str, Any]] = []
    for var in PR.REQUIRED_VARS:
        claims = [(s, s["declared"][var]) for s in sources
                  if var in s["declared"]]
        if not claims:
            continue
        first_src, first_val = claims[0]
        for other_src, other_val in claims[1:]:
            if not _same(first_val, other_val):
                disagreements.append({
                    "variable": var,
                    "question": QUESTION_OF_VAR[var],
                    "sources": [
                        {"path": first_src["path"], "value": first_val},
                        {"path": other_src["path"], "value": other_val},
                    ],
                })
        config[var] = first_val
        provenance[var] = first_src["path"]
    absent = [v for v in PR.REQUIRED_VARS if v not in config]
    return config, provenance, absent, disagreements


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def _finding(severity: str, rule: str, message: str) -> Dict[str, str]:
    return {"severity": severity, "rule": rule, "message": message}


def _report(verdict: str, reason: str, **kw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "schema": SCHEMA,
        "program": PROGRAM,
        "verdict": verdict,
        "reason": reason,
        "config_variables_required": list(PR.REQUIRED_VARS),
        "sources": [],
        "provenance": {},
        "absent_variables": [],
        "disagreements": [],
        "assignment": None,
        "stale_removed": None,
        "findings": [],
    }
    out.update(kw)
    return out


def _write_report(project: Path, json_arg: Optional[str],
                  report: Dict[str, Any]) -> None:
    dest = Path(json_arg) if json_arg else (project / REPORT_REL)
    if not dest.is_absolute():
        dest = project / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(dest, report)


def _retire_our_stale(project: Path) -> Optional[str]:
    """Delete a `pad_assignment.json` THIS program wrote, and nothing else.

    A refusal that left a previously-written config on disk would let
    `pad_ring_gen` place a ring from geometry this run refused — the artefact
    outliving the evidence, which is this tree's own worst failure shape. An
    UNSTAMPED file is somebody else's input and is never touched.
    """
    path = project / PR.ASSIGNMENT_REL
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (ValueError, OSError):
        return None
    stamp = doc.get(PROVENANCE_KEY) if isinstance(doc, dict) else None
    if not (isinstance(stamp, dict) and stamp.get("written_by") == PROGRAM):
        return None
    try:
        path.unlink()
    except OSError:                                             # pragma: no cover
        return None
    return PR.ASSIGNMENT_REL


def build(project: Path) -> Dict[str, Any]:
    """Read every source, merge, and decide. Writes nothing."""
    sources = [existing_config(project),
               operator_pads(project),
               declaration_pads(project)]
    config, provenance, absent, disagreements = merge(sources)
    return {"sources": sources, "config": config, "provenance": provenance,
            "absent": absent, "disagreements": disagreements}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 15.5ic producer — write the pad-ring config from a "
                    "DECLARED source, or refuse and name the field nobody "
                    "answered. Nothing is ever defaulted or inferred.")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--json", default=None,
                    help=f"report destination (default {REPORT_REL})")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{PROGRAM}] project dir not found: {project}", file=sys.stderr)
        return FAIL

    got = build(project)
    sources, config = got["sources"], got["config"]
    provenance, absent = got["provenance"], got["absent"]
    disagreements = got["disagreements"]
    shape_refusals = [r for s in sources for r in s.get("shape_refusals") or []]

    def emit(verdict: str, reason: str, rc: int, **kw: Any) -> int:
        rep = _report(verdict, reason, sources=sources, provenance=provenance,
                      absent_variables=absent, disagreements=disagreements,
                      **kw)
        _write_report(project, args.json, rep)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print(f"  verdict: {verdict}  (rc={rc})")
        for s in sources:
            state = ("declares " + ", ".join(sorted(s["declared"]))
                     if s["declared"] else "declares nothing")
            print(f"  source {s['path']}: {state}")
            for n in s["notes"]:
                print(f"      {n}")
        for f in rep["findings"][:16]:
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
        return rc

    # ── the SKIP tier: nobody was ever asked ───────────────────────────────
    if not config and not disagreements and not shape_refusals:
        parts = [f"`{s['path']}` ({s['kind']}): "
                 + ("; ".join(s["notes"]) or "declares none of the 13")
                 for s in sources]
        reason = (
            f"SKIPPED: no source declares any of the {len(PR.REQUIRED_VARS)} "
            f"pad-ring config variables {list(PR.REQUIRED_VARS)}, so there is "
            f"no pad ring to configure and nobody has been asked for one. "
            f"Sources consulted: {' | '.join(parts)}. This program does not "
            f"derive a pad ring config: the side variables name INSTANCES "
            f"that must already exist in the netlist, and choosing them would "
            f"mean choosing which package pin each signal leaves on.")
        stale = _retire_our_stale(project)
        return emit("SKIP", reason, SKIP, stale_removed=stale,
                    findings=[_finding("INFO", "PAD_CONFIG_NEVER_DECLARED",
                                       reason)])

    findings: List[Dict[str, str]] = []
    for r in shape_refusals:
        findings.append(_finding("ERROR", r["rule"], r["message"]))
    for d in disagreements:
        a, b = d["sources"]
        findings.append(_finding(
            "ERROR", "PAD_CONFIG_SOURCES_DISAGREE",
            f"{d['variable']} (declaration question {d['question']}) is "
            f"declared as {json.dumps(a['value'])} by `{a['path']}` and as "
            f"{json.dumps(b['value'])} by `{b['path']}`. Two sources that "
            f"disagree about a pin-out are a refusal, not a preference: "
            f"choosing one silently records a pin-out nobody chose, and the "
            f"losing value is exactly what a reader would need to see"))
    if absent:
        findings.append(_finding(
            "ERROR", "PAD_CONFIG_VARIABLE_ABSENT",
            f"{len(absent)} of {len(PR.REQUIRED_VARS)} required config "
            f"variable(s) are declared by no source: "
            + "; ".join(f"{v} (declaration question "
                        f"{QUESTION_OF_VAR[v]} is {TD.NOT_DETERMINED})"
                        for v in absent)
            + ". Upstream's placer aborts on the first unset one, and a value "
              "this program invented would be a pin-out nobody chose"))

    if not findings:
        # The merged config must satisfy the SAME contract `pad_ring_gen`
        # applies, and be refused HERE if it does not — a config written to
        # disk and refused one step later is a refusal a reader has to go
        # looking for.
        try:
            PR.validate_assignment(config)
        except PR.AssignmentError as exc:
            findings.append(_finding("ERROR", exc.rule, exc.message))

    if findings:
        stale = _retire_our_stale(project)
        reason = f"{findings[0]['rule']}: {findings[0]['message']}"
        return emit("FAIL", reason, FAIL, findings=findings,
                    stale_removed=stale)

    doc = dict(config)
    doc[PROVENANCE_KEY] = {
        "written_by": PROGRAM,
        "schema": SCHEMA,
        "variable_source": provenance,
        "note": ("every value above came from the source named beside it; "
                 "this program computed none of them"),
    }
    dest = project / PR.ASSIGNMENT_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(dest, doc)
    reason = (
        f"every one of the {len(PR.REQUIRED_VARS)} pad-ring config variables "
        f"is declared; `{PR.ASSIGNMENT_REL}` was written from "
        f"{len(set(provenance.values()))} declared source(s) and nothing was "
        f"derived")
    return emit("PASS", reason, PASS, assignment=PR.ASSIGNMENT_REL,
                findings=[])


if __name__ == "__main__":                                      # pragma: no cover
    sys.exit(main())
