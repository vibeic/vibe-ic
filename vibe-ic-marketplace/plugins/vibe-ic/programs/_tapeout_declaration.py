#!/usr/bin/env python3
"""_tapeout_declaration — the 18 questions a die has to answer about itself.

WHY A DECLARATION AT ALL
========================
Three of the general precheck's checks cannot be answered from the layout
alone. "Is the die the right size" is not a property of a GDS; it is an
AGREEMENT between a GDS and a number somebody wrote down. Same for "is there a
seal ring" (required by whom?) and "are any forbidden layers used" (forbidden
by whom?). Without a written-down side, those three checks have nothing to
compare against and can only ever report NOT_DETERMINED.

A design submitted to a shuttle gets that written-down side for free: the
operator's template PINS it, and step 0.5ic ingests it. A design doing its OWN
tape-out gets nothing, and until this module the flow had no place for it to
say what it had decided. That is the whole gap: the numbers were never
computed, they were never GOT — and for a self-tape-out there is nobody to get
them from, so they have to be DECLARED.

NOT_DETERMINED, NEVER A DEFAULT
===============================
Every unanswered field is the literal string `NOT_DETERMINED`. Not `null`, not
`0`, not an empty list, and above all not a plausible number.

A default is a fake number wearing a real number's clothes. It reads as an
answer at every downstream consumer, it survives into a report, and the one
thing it cannot do is be wrong in a way anybody notices. This tree has found
that shape repeatedly — an empty result indistinguishable from a clean one —
and the declaration is the place it would be cheapest to reintroduce, because
every one of these 18 fields has an obvious-looking value.

So: `blank_declaration()` fills all 18 with `NOT_DETERMINED`, `merge_answers()`
only ever replaces a field with something a human supplied, and there is no
code path anywhere in this module that invents a value. A consumer handed
`NOT_DETERMINED` must report NOT_DETERMINED — which is a non-pass — and that is
the intended and only behaviour.

WHERE THE 18 COME FROM — DERIVED, NOT INVENTED
==============================================
Each question exists because a REAL CONSUMER in this tree reads it. The
`consumer` field on every question names that consumer, so a question nobody
reads is visible as such rather than being carried forever because it once
seemed sensible.

  SECTION 2A — DIE SIZE (7).
      `die_area` / `core_area` / `fp_sizing` are the three keys
      `_submission_template.py` discovers a shuttle slot file BY
      (`DIE_AREA_KEY`, `CORE_AREA_KEY`, `FP_SIZING_KEY`) — i.e. the three an
      operator pins when there IS an operator. The other four are what the
      pure-geometry checks compare against: which cell must be the top, where
      the die's lower-left must be, what the database unit must be, and
      whether this deliverable is a die at all.
  SECTION 2B — PAD RING (8).
      `_pad_ring.REQUIRED_VARS` — 13 variables, which are upstream's own pad
      placer's names, verbatim. Grouped into the 8 things a HUMAN decides: the
      four per-side lists are one decision (which pads, in which order, on
      which side) and the three rotations are one decision (the orientations).
      The grouping is stated here so the 13:8 gap is a recorded reading and not
      a miscount.
  SECTION 2C — SEAL RING (3).
      The three inputs `sealring/sealring_verify.py` and `die_finishing_gen.py`
      already take: whether a ring is required, which PDK script builds it, and
      which marker layer must end up carrying geometry (`SEAL_MARKER`).

A NINETEENTH FIELD, AND WHY IT IS NOT IN THE 18
===============================================
`forbidden_layers` is required by the general precheck's forbidden-layer check
and belongs to none of the three sections. It is carried at the top level and
labelled as outside the 18, rather than being pushed into a section to make a
tidier count. A field filed under a heading it does not belong to is a small
lie that later gets quoted as a finding.

THE PAD REFUSALS ARE HONOURED, NOT RESTATED
===========================================
`_pad_ring.py` already refuses rather than improvising, in the places upstream
does — a side whose pad widths exceed its edge, leftover space that is not an
integer multiple of the minimum site width, a site name that is missing or is
not `CLASS PAD` — and it already emits each refusal as a RULE ID in
`reports/phase3/padring.json` where upstream's TCL emits a line of prose and
exits 1. Nothing here re-implements or relaxes any of that. Section 2B exists
to give those refusals their INPUTS: `PAD_CONFIG_VARIABLE_ABSENT` is the
refusal a `NOT_DETERMINED` in this section produces, which is the correct
outcome and not a gap.

chip-AGNOSTIC: no vendor, foundry, process node, SKU or design name. The only
fixed strings are upstream's own variable names and this flow's relative paths.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "vibe-ic/tapeout_declaration/1"

#: The one sentinel. Nothing in this module ever writes any other placeholder.
NOT_DETERMINED = "NOT_DETERMINED"

#: Where the declaration lives. Step 0.5ic owns it; the general precheck and
#: the pad-ring step read it. Named in ONE place so the producer and the two
#: consumers cannot drift onto different paths.
DECLARATION_REL = "input/submission_template/tapeout_declaration.json"
REPORT_REL = "reports/phase1/tapeout_declaration.json"

#: The three routes out of step 0.5ic, and the router file each one writes.
#: They are MUTUALLY EXCLUSIVE by construction: exactly one is written.
#:
#: THE THIRD FILE IS NEW, AND THE REASON IS MEASURED. Before it, 0.5ic had two
#: router files for what are actually three routes:
#:     slots/*.yaml     -> step 37.5ic, the operator's own container
#:     NO_TEMPLATE.txt  -> step 37.5ip, the IP/hardmacro terminal
#: and a CHIP doing its own tape-out fell into neither. It has no operator
#: template, so 37.5ic's condition excludes it; and it is a die, not an IP, so
#: 37.5ip is the wrong terminal for it. Such a design reached tape-out having
#: passed NO submission check of any kind. Routing it onto `NO_TEMPLATE.txt`
#: would have collided with the IP path, so the discriminator is its own file
#: and neither existing condition changes.
ROUTE_SHUTTLE = "SHUTTLE"          # an operator template was ingested
ROUTE_SELF_TAPEOUT = "SELF_TAPEOUT"
ROUTE_IP = "IP"

SELF_TAPEOUT_REL = "input/submission_template/SELF_TAPEOUT.txt"

#: First line of every SELF_TAPEOUT.txt this flow writes, so a re-ingest can
#: retire its OWN stale marker and will not touch a file some other hand put
#: there. Same rule `_submission_template.NO_TEMPLATE_MARKER` already applies.
SELF_TAPEOUT_MARKER = "# tapeout_declaration: self tape-out, no operator"

#: What a `deliverable` answer may be. A die and a hardmacro are checked
#: differently — a die's geometry MUST start at the origin, a hardmacro's need
#: not, because its LEF declares the offset — so this is the one field the
#: general precheck reads before it reads any other.
DELIVERABLE_DIE = "DIE"
DELIVERABLE_HARDMACRO = "HARDMACRO"
DELIVERABLES = (DELIVERABLE_DIE, DELIVERABLE_HARDMACRO)

SECTION_DIE_SIZE = "2A_die_size"
SECTION_PAD_RING = "2B_pad_ring"
SECTION_SEAL_RING = "2C_seal_ring"


@dataclass(frozen=True)
class Question:
    """One field of the declaration.

    `required_for` is the set of deliverables that MUST answer it; a question
    outside that set is `NOT_APPLICABLE` for this deliverable rather than
    unanswered, and the two are reported apart. `consumer` names the program
    that reads the answer, so an unread question is visible.
    """
    key: str
    section: str
    prompt: str
    kind: str                        # rect_um | point_um | number | text | list | enum | bool
    consumer: str
    required_for: Tuple[str, ...] = DELIVERABLES
    choices: Tuple[str, ...] = ()
    note: str = ""


# --------------------------------------------------------------------------- #
# SECTION 2A — DIE SIZE (7)
# --------------------------------------------------------------------------- #
_2A: Tuple[Question, ...] = (
    Question(
        "deliverable", SECTION_DIE_SIZE,
        "Is what leaves this flow a DIE that will be fabricated, or a "
        "HARDMACRO that somebody else will place?",
        "enum", "general_precheck", DELIVERABLES, choices=DELIVERABLES,
        note="Asked first because it decides whether the other six are "
             "required at all, and because it decides the origin rule: a die "
             "must start at (0,0); a hardmacro's LEF ORIGIN may declare an "
             "offset instead."),
    Question(
        "top_cell", SECTION_DIE_SIZE,
        "Which cell name must be the top cell of the streamed layout?",
        "text", "general_precheck",
        note="Compared against the layout's own defined-and-never-referenced "
             "structure. A layout whose top cell is not this name is not this "
             "design, whatever else is right about it."),
    Question(
        "die_area_um", SECTION_DIE_SIZE,
        "The die rectangle [llx, lly, urx, ury] in microns, absolutely.",
        "rect_um", "general_precheck", (DELIVERABLE_DIE,),
        note="`DIE_AREA` — the key `_submission_template` discovers an "
             "operator slot file BY. A self-tape-out has no operator to pin "
             "it, so it pins it here."),
    Question(
        "core_area_um", SECTION_DIE_SIZE,
        "The core rectangle [llx, lly, urx, ury] in microns.",
        "rect_um", "general_precheck", (DELIVERABLE_DIE,),
        note="`CORE_AREA`. Refused rather than skipped when absent: a file "
             "that pins a die and omits the core must be FOUND and refused."),
    Question(
        "fp_sizing", SECTION_DIE_SIZE,
        "Was the floorplan sized ABSOLUTE (the rectangles above are the "
        "truth) or RELATIVE (they were derived from a utilisation)?",
        "enum", "general_precheck", (DELIVERABLE_DIE,),
        choices=("absolute", "relative"),
        note="`FP_SIZING`. A die that was CHOSEN and a die that was DEFAULTED "
             "are the same number with different provenance, and only one of "
             "them can be checked."),
    Question(
        "die_origin_um", SECTION_DIE_SIZE,
        "Where must the streamed layout's lower-left corner be, in microns? "
        "For a die this is [0, 0].",
        "point_um", "general_precheck", (DELIVERABLE_DIE,),
        note="THE ORIGIN CHECK's declared side. Stated as a field rather than "
             "hard-coded to [0,0] so the check compares a measurement against "
             "a DECLARATION, like every other check here, instead of against "
             "a constant of ours."),
    Question(
        "database_unit_um", SECTION_DIE_SIZE,
        "What database unit, in microns, does the technology file declare?",
        "number", "general_precheck",
        note="Compared against the layout's own UNITS record. A stream written "
             "at a different grid than the tech file declares is off-grid "
             "everywhere at once, and nothing downstream says so."),
)

# --------------------------------------------------------------------------- #
# SECTION 2B — PAD RING (8)
#
# `_pad_ring.REQUIRED_VARS`, grouped. Every `consumer` here is the pad-ring
# step, which ALREADY refuses on each of these being absent
# (`PAD_CONFIG_VARIABLE_ABSENT`) and already emits that refusal as a rule id in
# `reports/phase3/padring.json`. Nothing below relaxes that.
# --------------------------------------------------------------------------- #
_2B: Tuple[Question, ...] = (
    Question(
        "pad_order_by_side", SECTION_PAD_RING,
        "Which pad INSTANCES sit on each die side, in order? "
        "{south: [...], east: [...], north: [...], west: [...]}",
        "list", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`PAD_SOUTH` / `PAD_EAST` / `PAD_NORTH` / `PAD_WEST`. Instances, "
             "not signals and not cell types: upstream resolves each against "
             "the block, so the pads must ALREADY EXIST in the netlist."),
    Question(
        "pad_site_name", SECTION_PAD_RING,
        "What is the SITE name of the IO row in the pad library?",
        "text", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`PAD_SITE_NAME`. Must exist and must be CLASS PAD — the pad "
             "placer refuses (`PAD_SITE_NOT_FOUND` / "
             "`PAD_SITE_CLASS_NOT_PAD`) rather than improvising, and that "
             "refusal is kept."),
    Question(
        "pad_corner_site_name", SECTION_PAD_RING,
        "What is the SITE name of the corner cells in the pad library?",
        "text", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`PAD_CORNER_SITE_NAME`. Same two refusals as above."),
    Question(
        "pad_edge_spacing_um", SECTION_PAD_RING,
        "How many microns from the die edge to the IO row?",
        "number", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`PAD_EDGE_SPACING`."),
    Question(
        "pad_rotations", SECTION_PAD_RING,
        "What orientation do the pads take? "
        "{horizontal: ..., vertical: ..., corner: ...}",
        "list", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`PAD_ROTATION_HORIZONTAL` / `_VERTICAL` / `_CORNER`. One "
             "question because a human decides an orientation convention "
             "once: NORTH is SOUTH's half turn and each corner is a further "
             "quarter turn, both DERIVED from the declared value by a stated "
             "rule rather than guessed."),
    Question(
        "pad_corner_master", SECTION_PAD_RING,
        "Which cell MASTER is the corner cell?",
        "text", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`PAD_CORNER`."),
    Question(
        "pad_fillers", SECTION_PAD_RING,
        "Which cell masters may fill the gaps between pads?",
        "list", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`PAD_FILLERS`. Load-bearing, not cosmetic: the ring's power and "
             "ground are formed by cells TOUCHING, so a gap no declared filler "
             "can close is a ring that is electrically nothing. That is what "
             "`PAD_CORNER_SPACING_NOT_SITE_MULTIPLE` refuses on, and the "
             "refusal is kept."),
    Question(
        "pad_signal_map", SECTION_PAD_RING,
        "Which top-level port does each pad instance bring out? "
        "{instance: port}",
        "list", "pad_ring_gen", (DELIVERABLE_DIE,),
        note="`SIGNAL_MAP` — OURS, and required. Upstream needs no such map "
             "because it never checks that every top-level port reached a "
             "pad. `BTERM_WITHOUT_PAD` does, so it needs the map."),
)

# --------------------------------------------------------------------------- #
# SECTION 2C — SEAL RING (3)
# --------------------------------------------------------------------------- #
_2C: Tuple[Question, ...] = (
    Question(
        "seal_ring_required", SECTION_SEAL_RING,
        "Does the party that takes this layout require a seal ring?",
        "bool", "general_precheck", (DELIVERABLE_DIE,),
        note="MEASURED on the live open-MPW precheck (2026-08-18): it refused "
             "a published layout at ladder step 3 of 16 with \"requires a seal "
             "ring (guard ring) around the die\". A self-tape-out has to "
             "answer this for itself because no operator is asking."),
    Question(
        "seal_ring_script", SECTION_SEAL_RING,
        "Which PDK script builds the seal ring? (path, or the PDK-relative "
        "`libs.tech/klayout/tech/scripts/sealring.py`)",
        "text", "general_precheck", (DELIVERABLE_DIE,),
        note="Read by `die_finishing_gen`. When the PDK ships no such script "
             "the honest answer is NOT_DETERMINED and the seal-ring check "
             "reports NOT_DETERMINED — never a pass, and never a FAIL either, "
             "because the PDK not shipping a generator is not this design "
             "getting it wrong."),
    Question(
        "seal_ring_marker_layer", SECTION_SEAL_RING,
        "Which marker layer must carry geometry once the ring exists? "
        "(\"layer/datatype\")",
        "text", "general_precheck", (DELIVERABLE_DIE,),
        note="`SEAL_MARKER` in `sealring/sealring_verify.py`. Its own "
             "docstring records why an exit code is not the verdict: a PDK "
             "seal-ring script was measured calling `sys.exit()` with NO "
             "argument after failing to load its cell library — exiting 0 and "
             "writing nothing."),
)

QUESTIONS: Tuple[Question, ...] = _2A + _2B + _2C

#: 7 + 8 + 3. Asserted at import so a question added to a section without the
#: section's count being revisited is a loud failure, not a silent drift.
SECTION_COUNTS = {SECTION_DIE_SIZE: 7, SECTION_PAD_RING: 8, SECTION_SEAL_RING: 3}
for _sec, _n in SECTION_COUNTS.items():
    _have = sum(1 for q in QUESTIONS if q.section == _sec)
    if _have != _n:                                            # pragma: no cover
        raise AssertionError(
            f"section {_sec} declares {_n} question(s) but carries {_have}")

#: The nineteenth field. See "A NINETEENTH FIELD" above — carried at the top
#: level and labelled, never filed under a section it does not belong to.
FORBIDDEN_LAYERS_KEY = "forbidden_layers"
EXTRA_KEYS: Tuple[str, ...] = (FORBIDDEN_LAYERS_KEY,)


def question(key: str) -> Optional[Question]:
    for q in QUESTIONS:
        if q.key == key:
            return q
    return None


def blank_declaration() -> Dict[str, Any]:
    """All 18 questions plus the extra field, every one `NOT_DETERMINED`.

    This is the ONLY constructor. There is no variant that pre-fills anything,
    because the moment one exists somebody calls it.
    """
    doc: Dict[str, Any] = {
        "schema": SCHEMA,
        "answers": {q.key: NOT_DETERMINED for q in QUESTIONS},
        FORBIDDEN_LAYERS_KEY: NOT_DETERMINED,
    }
    return doc


def is_answered(value: Any) -> bool:
    """True iff `value` is a real answer.

    `NOT_DETERMINED`, `None`, and an empty string are all unanswered. An empty
    LIST is deliberately NOT unanswered: "no pads on the north side" and "I did
    not say what is on the north side" are different facts, and a caller that
    means the first has to write `[]` on purpose.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != "" and value.strip() != NOT_DETERMINED
    return True


def merge_answers(doc: Dict[str, Any], answers: Dict[str, Any]
                  ) -> Tuple[Dict[str, Any], List[str]]:
    """Replace fields in `doc` with `answers`, and name what was ignored.

    Only keys this module KNOWS are accepted. An unknown key is returned in the
    ignored list rather than being written through, so an answers file that
    misspells `die_area_um` cannot leave a declaration that looks answered
    carrying a field nothing reads.

    An answer whose value is `NOT_DETERMINED` is a no-op: a caller cannot
    un-answer a field by supplying the sentinel, and cannot answer one by
    supplying it either.
    """
    known = {q.key for q in QUESTIONS} | set(EXTRA_KEYS)
    ignored: List[str] = []
    for key, value in sorted(answers.items()):
        if key not in known:
            ignored.append(key)
            continue
        if not is_answered(value):
            continue
        if key in EXTRA_KEYS:
            doc[key] = value
        else:
            doc["answers"][key] = value
    return doc, ignored


def route_of(doc: Dict[str, Any], has_slots: bool) -> str:
    """Which of the three routes this declaration selects.

    `has_slots` is the OPERATOR's answer and it wins: a design that ingested a
    template goes to the operator's own container whatever it declared about
    itself. That ordering is deliberate — it is what keeps step 37.5ic's
    verdict "not the one we wrote" on the shuttle route, which is the whole
    point of that step.
    """
    if has_slots:
        return ROUTE_SHUTTLE
    deliverable = (doc.get("answers") or {}).get("deliverable")
    if deliverable == DELIVERABLE_DIE:
        return ROUTE_SELF_TAPEOUT
    if deliverable == DELIVERABLE_HARDMACRO:
        return ROUTE_IP
    # UNDECLARED. Not routed to either terminal, because a design that did not
    # say what it is has not chosen a route and must not be given one. The
    # caller writes no router file at all, which selects nothing — the
    # mechanism `_submission_template.NO_DECLARATION.txt` already established.
    return NOT_DETERMINED


def applicable(q: Question, deliverable: Any) -> bool:
    """Is `q` required for this deliverable?

    An UNDECLARED deliverable makes every question applicable. That is the safe
    direction: a design that has not said what it is owes every answer, and the
    alternative — treating unknown as "probably not required" — is how an
    unanswered set becomes a clean one.
    """
    if not is_answered(deliverable):
        return True
    return deliverable in q.required_for


def audit(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Per-section answered/unanswered counts. States its own denominator.

    No verdict is taken. This function reports how much of the declaration
    exists; whether an unanswered field matters is the CONSUMER's call, and it
    is always the same call — a consumer handed NOT_DETERMINED reports
    NOT_DETERMINED.
    """
    ans = doc.get("answers") or {}
    deliverable = ans.get("deliverable")
    sections: Dict[str, Dict[str, Any]] = {}
    for sec in (SECTION_DIE_SIZE, SECTION_PAD_RING, SECTION_SEAL_RING):
        qs = [q for q in QUESTIONS if q.section == sec]
        answered, unanswered, not_applicable = [], [], []
        for q in qs:
            if not applicable(q, deliverable):
                not_applicable.append(q.key)
            elif is_answered(ans.get(q.key)):
                answered.append(q.key)
            else:
                unanswered.append(q.key)
        sections[sec] = {
            "questions": len(qs),
            "answered": len(answered),
            "unanswered": len(unanswered),
            "not_applicable": len(not_applicable),
            "answered_keys": answered,
            "unanswered_keys": unanswered,
            "not_applicable_keys": not_applicable,
        }
    total_q = len(QUESTIONS)
    total_a = sum(s["answered"] for s in sections.values())
    total_u = sum(s["unanswered"] for s in sections.values())
    total_na = sum(s["not_applicable"] for s in sections.values())
    return {
        "questions_total": total_q,
        "answered": total_a,
        "unanswered": total_u,
        "not_applicable": total_na,
        "sections": sections,
        FORBIDDEN_LAYERS_KEY + "_answered": is_answered(
            doc.get(FORBIDDEN_LAYERS_KEY)),
        "deliverable": deliverable if is_answered(deliverable)
        else NOT_DETERMINED,
    }


# --------------------------------------------------------------------------- #
# Schema refusals — a MALFORMED declaration, never an incomplete one
# --------------------------------------------------------------------------- #
RULE_NOT_A_MAPPING = "DECLARATION_NOT_A_MAPPING"
RULE_SCHEMA_UNKNOWN = "DECLARATION_SCHEMA_UNKNOWN"
RULE_FIELD_MISSING = "DECLARATION_FIELD_MISSING"
RULE_FIELD_UNKNOWN = "DECLARATION_FIELD_UNKNOWN"
RULE_ENUM_INVALID = "DECLARATION_ENUM_INVALID"
RULE_RECT_INVALID = "DECLARATION_RECT_INVALID"
RULE_POINT_INVALID = "DECLARATION_POINT_INVALID"
RULE_NUMBER_INVALID = "DECLARATION_NUMBER_INVALID"


def _refusal(rule: str, message: str, **extra: Any) -> Dict[str, Any]:
    d = {"rule": rule, "message": message}
    d.update(extra)
    return d


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(doc: Any) -> List[Dict[str, Any]]:
    """Refuse a MALFORMED declaration. An INCOMPLETE one is not malformed.

    THE DISTINCTION IS THE WHOLE DESIGN. A field left `NOT_DETERMINED` is the
    declaration working exactly as intended and produces NO refusal here — it
    produces a NOT_DETERMINED at the consuming check, which is a non-pass in
    the place where the reader can see WHICH check went without. A field that
    is ABSENT, or present with a value of the wrong shape, is refused here,
    because that is a declaration nobody can read — and it is the only way a
    default could sneak back in.
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(doc, dict):
        return [_refusal(RULE_NOT_A_MAPPING,
                         f"the declaration's top level is {type(doc).__name__}, "
                         "not a mapping")]
    if doc.get("schema") != SCHEMA:
        out.append(_refusal(
            RULE_SCHEMA_UNKNOWN,
            f"schema is {doc.get('schema')!r}, expected {SCHEMA!r}"))
    answers = doc.get("answers")
    if not isinstance(answers, dict):
        out.append(_refusal(
            RULE_NOT_A_MAPPING,
            f"`answers` is {type(answers).__name__}, not a mapping"))
        return out

    for q in QUESTIONS:
        if q.key not in answers:
            out.append(_refusal(
                RULE_FIELD_MISSING,
                f"question {q.key!r} ({q.section}) is absent. Every question "
                f"must be present; an unanswered one carries {NOT_DETERMINED}, "
                "which is not the same as not being there at all",
                key=q.key, section=q.section))
    for key in sorted(answers):
        if question(key) is None:
            out.append(_refusal(
                RULE_FIELD_UNKNOWN,
                f"{key!r} is not one of the {len(QUESTIONS)} questions",
                key=key))
    for key in EXTRA_KEYS:
        if key not in doc:
            out.append(_refusal(
                RULE_FIELD_MISSING,
                f"{key!r} is absent from the declaration", key=key))

    for q in QUESTIONS:
        v = answers.get(q.key)
        if not is_answered(v):
            continue                       # unanswered is not malformed
        if q.kind == "enum" and v not in q.choices:
            out.append(_refusal(
                RULE_ENUM_INVALID,
                f"{q.key!r} is {v!r}; allowed: {', '.join(q.choices)}",
                key=q.key))
        elif q.kind == "rect_um":
            if not (isinstance(v, (list, tuple)) and len(v) == 4
                    and all(_is_number(c) for c in v)):
                out.append(_refusal(
                    RULE_RECT_INVALID,
                    f"{q.key!r} must be [llx, lly, urx, ury] in microns",
                    key=q.key))
            elif not (v[2] > v[0] and v[3] > v[1]):
                out.append(_refusal(
                    RULE_RECT_INVALID,
                    f"{q.key!r} = {list(v)} is degenerate or inverted; a "
                    "rectangle needs urx > llx and ury > lly",
                    key=q.key))
        elif q.kind == "point_um":
            if not (isinstance(v, (list, tuple)) and len(v) == 2
                    and all(_is_number(c) for c in v)):
                out.append(_refusal(
                    RULE_POINT_INVALID,
                    f"{q.key!r} must be [x, y] in microns", key=q.key))
        elif q.kind == "number":
            if not _is_number(v) or v <= 0:
                out.append(_refusal(
                    RULE_NUMBER_INVALID,
                    f"{q.key!r} must be a positive number, got {v!r}",
                    key=q.key))
    return out


def load(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(declaration, None) or (None, why-not). Never raises on bad input."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"cannot read {path}: {exc}"
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, f"{path} is not JSON: {exc}"


def answer(doc: Dict[str, Any], key: str) -> Any:
    """The answer to `key`, or `NOT_DETERMINED`. Never invents one."""
    if key in EXTRA_KEYS:
        v = doc.get(key)
    else:
        v = (doc.get("answers") or {}).get(key)
    return v if is_answered(v) else NOT_DETERMINED
