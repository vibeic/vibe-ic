#!/usr/bin/env python3
"""pad_assignment_gen — the AUTHOR of `phase3/stage3/pnr/pad_assignment.json`.

WHY THIS PROGRAM EXISTS
=======================
`pad_ring_gen` reads that file and NOTHING WROTE IT. Measured on this tree
before this program landed:

    grep -rn "pad_assignment" <repo root>          ->  2 files
        programs/pad_ring_gen.py                        reader
        programs/_pad_ring.py                           reader

Two hits, both readers, zero writers. `_pad_ring.py`'s own docstring recorded
the same fact and drew the correct conclusion for the tree it was written in:
"NOTHING IN THIS FILE DERIVES AN ASSIGNMENT ... So `pad_ring_gen` SKIPs".
So step 15.5ic could take exactly one branch — the SKIP — on the shuttle path
and on the self-tape-out path alike. A step that can only skip is not a step.

WHAT CHANGED UNDER IT
=====================
The input it went without now exists. Step 0.5ic writes
`input/submission_template/tapeout_declaration.json` on EVERY route, and its
section 2B is `_pad_ring.REQUIRED_VARS` grouped into the 8 things a human
decides — `_tapeout_declaration.py` says so where it derives the 18 questions,
naming `pad_ring_gen` as the `consumer` of every one of the 8. The consumer
was never wired to the answers. This program is that wiring and nothing more.

TWO SOURCES, AND WHICH ONE WINS
===============================
    operator slot file    `input/submission_template/slots/*.yaml`
    the design's own      `input/submission_template/tapeout_declaration.json`

The SLOT WINS where it speaks, and it speaks about ONE thing. Measured in
`_submission_template.py`: a slot record carries `DIE_AREA`, `CORE_AREA`,
`FP_SIZING`, a ring width, and the pad lists matched by
`PAD_LIST_KEY_RE` — and of the 13 variables `_pad_ring.REQUIRED_VARS` names,
the only ones a slot file can supply are the four per-side lists. It carries no
site name, no corner site, no edge spacing, no rotation, no corner master, no
filler and no signal map. So the merge is:

    PAD_SOUTH/EAST/NORTH/WEST   slot, when the slot names that side;
                                otherwise the declaration's `pad_order_by_side`
    the other nine variables     the declaration, always

and a shuttle design that answers nothing gets what it gets today: nothing
written, and `pad_ring_gen`'s own SKIP untouched.

THE THREE OUTCOMES, AND WHY THE MIDDLE ONE IS NOT A FAIL
========================================================
    0  WROTE       every required variable resolved; the config was written
                   with a per-variable `provenance` block naming its source.
    2  NOT_ASKED   no source answered ANY of section 2B. This is not a defect
                   and not a refusal: it is "nobody was asked", which is the
                   state every tree in this repository is in today. NOTHING IS
                   WRITTEN — in particular no half-filled config, because
                   `pad_ring_gen` reads a config that declares SOME of the
                   contract as a MALFORMED DECLARATION and FAILs on it, and
                   turning "nobody was asked" into "somebody wrote it wrong"
                   is precisely the substitution both programs exist to refuse.
    1  REFUSE      a source could not be read, two sources disagree, or the
                   declaration was STARTED and still owes a field. The message
                   NAMES THE FIELD. It never guesses a pad site, a spacing, a
                   rotation or a filler.

THE PARTIAL RULE, STATED ONCE
=============================
Section 2B is answered ALL-OR-NOTHING by construction: there is no answer in it
that makes another unnecessary. `pad_ring_gen` needs all 13 variables or it can
place nothing. So:

    0 of 8 answered   -> NOT_ASKED (rc 2). Today's state; behaviour unchanged.
    1..7 of 8         -> REFUSE (rc 1), naming every one of the 8 still owed.
    8 of 8            -> WROTE (rc 0).

The distinction is the same one `pad_ring_gen` already draws between an ABSENT
config and a HALF-WRITTEN one, and it is drawn here for the same reason: an
unanswered question and a wrong answer must never buy the same exit code.

WHAT THIS PROGRAM WILL NOT DO
=============================
It derives NOTHING. Every value it writes was read out of a slot file or out of
the declaration, verbatim, and is stamped with which. There is no default, no
fallback value and no "sensible" pad site anywhere in this file — the six
refusals `_pad_ring` renders as rule ids (`PAD_SITE_NOT_FOUND`,
`PAD_SITE_CLASS_NOT_PAD`, `PAD_INSTANCE_NOT_IN_BLOCK`, `PAD_RING_DOES_NOT_FIT`,
`PAD_CORNER_SPACING_NOT_SITE_MULTIPLE`, `PAD_CONFIG_VARIABLE_ABSENT`) all
remain reachable and all still fire, because this program hands `pad_ring_gen`
declared values and never manufactured ones.

    pad_assignment_gen <project_dir> [--json REPORT] [--out CONFIG]
    main(argv) -> 0 wrote / 1 refuse / 2 nobody was asked

chip-AGNOSTIC: no chip, vendor, SKU, foundry, library or process-node literal.
The only fixed strings are upstream's own variable names, the declaration's own
question keys, and this flow's relative paths.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _atomic_artefact import write_json as atomic_write_json

import _pad_ring as PR
import _submission_template as ST
import _tapeout_declaration as TD

PROGRAM = "pad_assignment_gen"
SCHEMA = "vibe-ic/pad_assignment/1"
REPORT_REL = "reports/phase3/pad_assignment.json"

#: The declaration's section-2B key -> the upstream variable(s) it answers.
#: One entry per question, so a question added to 2B without a variable behind
#: it is a loud failure at import rather than a silent omission at run time.
#: A tuple of more than one variable is a question a HUMAN answers once and
#: upstream spells several times; the split rule is stated beside it below.
QUESTION_TO_VARS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("pad_order_by_side",
     ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST")),
    ("pad_site_name", ("PAD_SITE_NAME",)),
    ("pad_corner_site_name", ("PAD_CORNER_SITE_NAME",)),
    ("pad_edge_spacing_um", ("PAD_EDGE_SPACING",)),
    ("pad_rotations",
     ("PAD_ROTATION_HORIZONTAL", "PAD_ROTATION_VERTICAL",
      "PAD_ROTATION_CORNER")),
    ("pad_corner_master", ("PAD_CORNER",)),
    ("pad_fillers", ("PAD_FILLERS",)),
    ("pad_signal_map", ("SIGNAL_MAP",)),
)

#: `pad_order_by_side` is one mapping; upstream spells it four variables. The
#: side words are the declaration's own prompt, verbatim.
SIDE_KEY_TO_VAR: Tuple[Tuple[str, str], ...] = (
    ("south", "PAD_SOUTH"), ("east", "PAD_EAST"),
    ("north", "PAD_NORTH"), ("west", "PAD_WEST"),
)
#: `pad_rotations` is one mapping; upstream spells it three variables.
ROTATION_KEY_TO_VAR: Tuple[Tuple[str, str], ...] = (
    ("horizontal", "PAD_ROTATION_HORIZONTAL"),
    ("vertical", "PAD_ROTATION_VERTICAL"),
    ("corner", "PAD_ROTATION_CORNER"),
)

#: A slot file's own spelling of each side, matched case-insensitively against
#: the keys `_submission_template.PAD_LIST_KEY_RE` claimed. `PADS`, `PAD_LIST`
#: and `PAD_ORDER` also match that pattern and name NO side — see
#: `_unsided_slot_lists`, which refuses rather than splitting them.
SLOT_SIDE_KEYS: Tuple[Tuple[str, str], ...] = (
    ("PAD_SOUTH", "PAD_SOUTH"), ("PAD_EAST", "PAD_EAST"),
    ("PAD_NORTH", "PAD_NORTH"), ("PAD_WEST", "PAD_WEST"),
)

# Every question in section 2B must appear above exactly once, and every
# variable in `_pad_ring.REQUIRED_VARS` must be produced by exactly one of
# them. Asserted at import: a question or a variable added on one side and not
# the other is the drift this map exists to prevent, and a silent 12-of-13
# config is a config `pad_ring_gen` calls MALFORMED.
_2B_KEYS = tuple(q.key for q in TD.QUESTIONS
                 if q.section == TD.SECTION_PAD_RING)
_MAPPED_QUESTIONS = tuple(k for k, _ in QUESTION_TO_VARS)
_MAPPED_VARS = tuple(v for _, vs in QUESTION_TO_VARS for v in vs)
if sorted(_2B_KEYS) != sorted(_MAPPED_QUESTIONS):        # pragma: no cover
    raise AssertionError(
        f"section {TD.SECTION_PAD_RING} declares {sorted(_2B_KEYS)} but this "
        f"map covers {sorted(_MAPPED_QUESTIONS)}")
if sorted(_MAPPED_VARS) != sorted(PR.REQUIRED_VARS):     # pragma: no cover
    raise AssertionError(
        f"this map produces {sorted(_MAPPED_VARS)} but _pad_ring requires "
        f"{sorted(PR.REQUIRED_VARS)}")


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def _finding(severity: str, rule: str, message: str, **extra: Any) -> Dict[str, Any]:
    d = {"severity": severity, "rule": rule, "message": message}
    d.update(extra)
    return d


def _report(verdict: str, reason: str, **kw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "schema": SCHEMA,
        "program": PROGRAM,
        "verdict": verdict,
        "reason": reason,
        "sources": {
            "slot_files": [],
            "slot_files_unreadable": [],
            "declaration": None,
            "declaration_unreadable": None,
        },
        "questions_total": len(_2B_KEYS),
        "questions_answered": 0,
        "questions_unanswered": sorted(_2B_KEYS),
        "config_variables_required": list(PR.REQUIRED_VARS),
        "provenance": {},
        "config_written": None,
        "findings": [],
    }
    out.update(kw)
    return out


def _write_report(project: Path, json_arg: Optional[str],
                  report: Dict[str, Any]) -> None:
    dest = Path(json_arg) if json_arg else (project / REPORT_REL)
    if not dest.is_absolute():
        dest = (Path.cwd() / dest).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(dest, report)


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
def read_slot_pad_lists(project: Path) -> Tuple[Dict[str, Dict[str, Any]],
                                                List[Dict[str, str]],
                                                List[Dict[str, Any]],
                                                List[str]]:
    """The operator's per-side pad lists, and everything that got in the way.

    Returns (by_var, unreadable, unsided, files_seen).

    `unreadable` is NEVER folded into "the slot declared nothing". A slot file
    that could not be parsed may carry the very pad list that should have
    overridden the declaration, so it is returned for the caller to REFUSE on —
    rule 9 of this repository's own operating rules: "I could not read it" and
    "I read it and it was empty" must never produce the same verdict.
    """
    slots_dir = project / ST.SLOTS_DIR_REL
    by_var: Dict[str, Dict[str, Any]] = {}
    unreadable: List[Dict[str, str]] = []
    unsided: List[Dict[str, Any]] = []
    files_seen: List[str] = []
    if not slots_dir.is_dir():
        return by_var, unreadable, unsided, files_seen

    records, scan = ST.discover_slots(slots_dir)
    for bad in scan.get("unparsable") or []:
        unreadable.append({"file": str(bad.get("file")),
                           "reason": str(bad.get("reason"))})
    for rec in records:
        rel = rec.get("source_relpath") or rec.get("source_file")
        files_seen.append(str(rel))
        pads = rec.get("pads") or {}
        for entry in pads.get("lists") or []:
            key = str(entry.get("key", "")).strip().upper()
            var = dict(SLOT_SIDE_KEYS).get(key)
            if var is None:
                # `PADS` / `PAD_LIST` / `PAD_ORDER`: a real pad list that names
                # no side. Splitting it across four sides would be choosing
                # which package pin each signal leaves on, which is the one
                # decision this whole step refuses to make for anybody.
                unsided.append({"slot": rec.get("slot"), "file": str(rel),
                                "key": entry.get("key"),
                                "count": entry.get("count")})
                continue
            prior = by_var.get(var)
            if prior is not None and prior["value"] != list(entry.get("raw") or []):
                # Two slot files pinning the same side differently: this tree
                # holds more than one slot and nothing here can say which one
                # this design was accepted into.
                prior.setdefault("conflicts", []).append(
                    {"file": str(rel), "value": list(entry.get("raw") or [])})
                continue
            by_var[var] = {"value": list(entry.get("raw") or []),
                           "source": f"slot {rec.get('slot')} ({rel}) key "
                                     f"{entry.get('key')}",
                           "conflicts": prior.get("conflicts", []) if prior else []}
    return by_var, unreadable, unsided, files_seen


def read_declaration(project: Path) -> Tuple[Optional[Dict[str, Any]],
                                             Optional[str]]:
    """The design's own declaration, or (None, why-not)."""
    path = project / TD.DECLARATION_REL
    if not path.is_file():
        return None, None                     # absent is not unreadable
    doc, why = TD.load(path)
    if doc is None:
        return None, why
    if not isinstance(doc, dict):
        return None, f"{TD.DECLARATION_REL}: the top level is not a mapping"
    return doc, None


# --------------------------------------------------------------------------- #
# the merge
# --------------------------------------------------------------------------- #
def _mapping_answer(value: Any, pairs: Tuple[Tuple[str, str], ...],
                    question: str) -> Tuple[Dict[str, Any], List[str]]:
    """Split one declaration mapping into its upstream variables.

    Returns (by_var, missing_keys). A key the mapping does not carry is
    MISSING, never an empty default: "no pads on the north side" is written
    `[]` on purpose and "I did not say what is on the north side" is the key
    not being there, and `_tapeout_declaration.is_answered` already draws that
    distinction the same way.
    """
    if not isinstance(value, dict):
        return {}, [f"{question} (not a mapping: "
                    f"{type(value).__name__})"]
    lowered = {str(k).strip().lower(): v for k, v in value.items()}
    by_var: Dict[str, Any] = {}
    missing: List[str] = []
    for key, var in pairs:
        if key in lowered and TD.is_answered(lowered[key]):
            by_var[var] = lowered[key]
        else:
            missing.append(f"{question}.{key}")
    return by_var, missing


def compose(slot_vars: Dict[str, Dict[str, Any]],
            declaration: Optional[Dict[str, Any]]
            ) -> Tuple[Dict[str, Any], Dict[str, str], List[str], List[str]]:
    """(config, provenance, answered_questions, owed).

    Nothing is derived. Every value in `config` came verbatim from a slot file
    or from the declaration, and `provenance` says which for every variable.
    """
    config: Dict[str, Any] = {}
    provenance: Dict[str, str] = {}
    answered: List[str] = []
    owed: List[str] = []

    decl_answers: Dict[str, Any] = {}
    if isinstance(declaration, dict):
        decl_answers = declaration.get("answers") or {}
        if not isinstance(decl_answers, dict):
            decl_answers = {}

    for question, variables in QUESTION_TO_VARS:
        raw = decl_answers.get(question)
        declared_here: Dict[str, Any] = {}
        missing_here: List[str] = []
        if question == "pad_order_by_side":
            if TD.is_answered(raw):
                declared_here, missing_here = _mapping_answer(
                    raw, SIDE_KEY_TO_VAR, question)
        elif question == "pad_rotations":
            if TD.is_answered(raw):
                declared_here, missing_here = _mapping_answer(
                    raw, ROTATION_KEY_TO_VAR, question)
        elif TD.is_answered(raw):
            declared_here = {variables[0]: raw}

        if declared_here or missing_here:
            answered.append(question)

        for var in variables:
            # THE SLOT WINS. It is the operator's own geometry and the design
            # does not get to restate it; where the slot is silent the
            # declaration is the only source there is.
            if var in slot_vars:
                config[var] = slot_vars[var]["value"]
                provenance[var] = slot_vars[var]["source"]
            elif var in declared_here:
                config[var] = declared_here[var]
                provenance[var] = f"declaration answer {question}"
            else:
                owed.append(f"{var} (declaration question {question})")
    return config, provenance, answered, owed


# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None,
                    help=f"report destination (default {REPORT_REL})")
    ap.add_argument("--out", default=None,
                    help=f"config destination (default {PR.ASSIGNMENT_REL})")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{PROGRAM}] project dir not found: {project}", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else (project / PR.ASSIGNMENT_REL)
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()

    slot_vars, slot_unreadable, unsided, slot_files = read_slot_pad_lists(project)
    declaration, decl_why = read_declaration(project)
    config, provenance, answered, owed = compose(slot_vars, declaration)

    sources = {
        "slot_files": slot_files,
        "slot_files_unreadable": slot_unreadable,
        "slot_lists_without_a_side": unsided,
        "declaration": (TD.DECLARATION_REL
                        if declaration is not None else None),
        "declaration_unreadable": decl_why,
    }
    common = dict(sources=sources,
                  questions_answered=len(answered),
                  questions_unanswered=sorted(set(_2B_KEYS) - set(answered)),
                  provenance=provenance)

    def _emit(verdict: str, reason: str, findings, rc: int, **kw: Any) -> int:
        rep = _report(verdict, reason, findings=list(findings), **common, **kw)
        _write_report(project, args.json, rep)
        print(f"=== {PROGRAM} ({project.name}) ===")
        print(f"  verdict: {verdict}")
        print(f"  {reason}")
        for f in rep["findings"]:
            print(f"  {f['rule']}: {f['message']}")
        return rc

    # ── refusals that come BEFORE any verdict about completeness ───────────
    # A source that could not be READ is not a source that said nothing. Both
    # of these can hide the very answer the merge below would have used, so
    # neither may fall through into NOT_ASKED.
    if slot_unreadable:
        named = "; ".join(f"{u['file']} ({u['reason']})"
                          for u in slot_unreadable)
        return _emit(
            "REFUSE",
            f"{len(slot_unreadable)} operator slot file(s) under "
            f"{ST.SLOTS_DIR_REL} could not be parsed, so this program cannot "
            f"say whether they pin a pad list that would have overridden the "
            f"declaration: {named}",
            [_finding("ERROR", "SLOT_FILE_UNREADABLE", named)], 1)

    if decl_why:
        return _emit(
            "REFUSE",
            f"the tape-out declaration exists and could not be read, so the "
            f"answers to section {TD.SECTION_PAD_RING} are unknown rather "
            f"than absent: {decl_why}",
            [_finding("ERROR", "DECLARATION_UNREADABLE", decl_why)], 1)

    if unsided:
        named = "; ".join(f"{u['file']} key {u['key']} ({u['count']} pad(s))"
                          for u in unsided)
        return _emit(
            "REFUSE",
            f"an operator slot file declares a pad list that names NO die "
            f"side. Assigning those pads to sides would be choosing which "
            f"package pin each signal leaves on, which this step refuses to "
            f"do for anybody. Re-express it as PAD_SOUTH / PAD_EAST / "
            f"PAD_NORTH / PAD_WEST: {named}",
            [_finding("ERROR", "SLOT_PAD_LIST_WITHOUT_A_SIDE", named)], 1)

    conflicted = {v: rec["conflicts"] for v, rec in slot_vars.items()
                  if rec.get("conflicts")}
    if conflicted:
        named = "; ".join(
            f"{v}: {slot_vars[v]['source']} vs "
            + " vs ".join(str(c["file"]) for c in cs)
            for v, cs in sorted(conflicted.items()))
        return _emit(
            "REFUSE",
            f"two or more operator slot files pin the same die side "
            f"differently and nothing here can say which slot this design was "
            f"accepted into: {named}",
            [_finding("ERROR", "SLOT_PAD_LIST_CONFLICT", named)], 1)

    # ── nobody was asked ───────────────────────────────────────────────────
    if not answered and not slot_vars:
        reason = (
            f"NOT_ASKED: no source answers any of the "
            f"{len(_2B_KEYS)} questions of declaration section "
            f"{TD.SECTION_PAD_RING} and no operator slot file pins a per-side "
            f"pad list, so there is nothing to write down. "
            f"`{PR.ASSIGNMENT_REL}` was NOT created: a config declaring SOME "
            f"of the contract is what `pad_ring_gen` calls a MALFORMED "
            f"declaration and FAILs on, and an unanswered question must not "
            f"buy the exit code of a wrong answer. Answer section "
            f"{TD.SECTION_PAD_RING} in `{TD.DECLARATION_REL}`, or ingest an "
            f"operator template that pins the per-side pad lists.")
        return _emit("NOT_ASKED", reason,
                     [_finding("INFO", "PAD_RING_NOT_DECLARED", reason)], 2)

    # ── started and still owing ────────────────────────────────────────────
    if owed:
        named = "; ".join(owed)
        return _emit(
            "REFUSE",
            f"declaration section {TD.SECTION_PAD_RING} was STARTED "
            f"({len(answered)} of {len(_2B_KEYS)} question(s) answered) and "
            f"still owes {len(owed)} of the {len(PR.REQUIRED_VARS)} variables "
            f"`pad_ring_gen` requires. No value is guessed for any of them — "
            f"a pad site, an edge spacing or a filler invented here would be "
            f"indistinguishable in the artefact from a real pin-out. Still "
            f"owed: {named}",
            [_finding("ERROR", "PAD_CONFIG_VARIABLE_ABSENT", named,
                      variables_owed=list(owed))], 1)

    # ── every variable resolved ────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(config)
    payload["_provenance"] = dict(provenance)
    payload["_written_by"] = PROGRAM
    atomic_write_json(out_path, payload)
    try:
        written = str(out_path.relative_to(project))
    except ValueError:
        written = str(out_path)
    reason = (
        f"every one of the {len(PR.REQUIRED_VARS)} variables `pad_ring_gen` "
        f"requires resolved from a declared source; none was derived. "
        f"{sum(1 for v in provenance.values() if v.startswith('slot '))} came "
        f"from the operator's slot geometry and "
        f"{sum(1 for v in provenance.values() if v.startswith('declaration'))} "
        f"from the design's own tape-out declaration.")
    return _emit("WROTE", reason, [], 0, config_written=written)


if __name__ == "__main__":                                 # pragma: no cover
    raise SystemExit(main())
