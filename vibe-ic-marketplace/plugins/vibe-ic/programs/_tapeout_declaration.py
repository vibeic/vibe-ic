#!/usr/bin/env python3
"""_tapeout_declaration — the 18 physical questions a die answers about itself.

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

TWO CONTRACT FIELDS, AND WHY THEY ARE NOT IN THE 18
===================================================
`forbidden_layers` is required by the general precheck's forbidden-layer check.
`synthesis_area_budget` is required by the synthesis-area comparison. Neither
belongs to the three physical-deliverable sections, so both are carried at the
top level rather than being pushed into a section to make a tidier count. A
field filed under a heading it does not belong to is a small lie that later
gets quoted as a finding.

The area field is a typed union, never a sentinel overloaded as a waiver:

* `{status: LIMIT, max_die_dimensions_um: [W, H]}` is an explicit ceiling;
* `{status: NOT_APPLICABLE, rationale: ...}` is an explicit disposition;
* `NOT_DETERMINED` is unanswered and is never read as either of the above.

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


# --------------------------------------------------------------------------- #
# WHO IS ENTITLED TO ANSWER A QUESTION (#2070)
#
# Seventeen of the eighteen questions ask the DESIGN about itself. One does
# not. `database_unit_um` asks what the TECHNOLOGY FILE declares, and a design
# has no standing to answer that: the number is a property of the PDK the run
# targets, published by that PDK's own tech LEF.
#
# MEASURED, and this is why it is a defect and not a nicety. Two designs in the
# corpus each name TWO open PDK families in L1, and the pinned image's tech
# LEFs declare DIFFERENT database units for them — `DATABASE MICRONS 2000`
# (0.0005 um) for one family, `DATABASE MICRONS 1000` (0.001 um) for the other.
# One answers file drives run trees on BOTH, so any single scalar written there
# is wrong for one of the two runs. The designs correctly answered
# NOT_DETERMINED and cited both measurements — which is the right answer to a
# question that should never have been put to them.
#
# So the value is TRANSCRIBED, per run, from the tech LEF of the run's own
# `--pdk`, and carried here with the path:line it was read at. A design answer
# that DISAGREES with the run's technology is refused BY NAME, with both values
# in the message; one that AGREES is accepted with a note, because a design
# that happens to be right is still not the authority.
ANSWERED_BY_DESIGN = "the design"
ANSWERED_BY_TECHNOLOGY = "the technology"

#: The refusal a design's claim about the technology earns. Named here, beside
#: the vocabulary it belongs to, so the producer and the validator cannot spell
#: it two ways.
RULE_TECHNOLOGY_FACT_FROM_DESIGN = "DATABASE_UNIT_IS_A_TECHNOLOGY_FACT"

#: Where the transcription lands in the declaration. NOT inside `answers`:
#: `answers` is what somebody ANSWERED, and this was not answered by anybody —
#: it was read off a technology file. The answered VALUE still lands in
#: `answers.database_unit_um`, because every consumer reads it there; this key
#: is its provenance, and a reader that wants to know who said it can see.
TECHNOLOGY_KEY = "from_the_technology"


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
    #: WHO is entitled to answer. `ANSWERED_BY_DESIGN` for the seventeen
    #: questions about the design itself; `ANSWERED_BY_TECHNOLOGY` for the one
    #: that asks what a technology file declares. Declared as a field rather
    #: than kept as a list of keys somewhere else, so the entitlement travels
    #: with the question and a new question has to state it.
    answered_by: str = ANSWERED_BY_DESIGN


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
        "number", "general_precheck", answered_by=ANSWERED_BY_TECHNOLOGY,
        note="Compared against the layout's own UNITS record. A stream written "
             "at a different grid than the tech file declares is off-grid "
             "everywhere at once, and nothing downstream says so. "
             "NOT ASKED OF THE DESIGN (#2070): it is a fact of the "
             "TECHNOLOGY the run targets, not a claim the design is entitled "
             "to make. Step 0.5ic transcribes `DATABASE MICRONS` from the "
             "tech LEF of the run's own `--pdk` inside the pinned image and "
             "records the path:line it read. Measured: the two families one "
             "design named declare DIFFERENT units (2000 vs 1000 dbu/um), so "
             "a single scalar in a design's answers file is wrong for one of "
             "the two runs that file drives. A design scalar that DISAGREES "
             "with the run's technology is refused by name "
             f"({RULE_TECHNOLOGY_FACT_FROM_DESIGN}); one that agrees is "
             "accepted with a note."),
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

#: Contract fields outside the 18 physical-deliverable questions. See the
#: module-level explanation above.
FORBIDDEN_LAYERS_KEY = "forbidden_layers"
SYNTHESIS_AREA_BUDGET_KEY = "synthesis_area_budget"
AREA_BUDGET_LIMIT = "LIMIT"
AREA_BUDGET_NOT_APPLICABLE = "NOT_APPLICABLE"
EXTRA_KEYS: Tuple[str, ...] = (
    FORBIDDEN_LAYERS_KEY,
    SYNTHESIS_AREA_BUDGET_KEY,
    TECHNOLOGY_KEY,
)

#: Every question whose answer is transcribed from the technology rather than
#: asked of the design. Derived from the questions themselves — a second list
#: of key names is a second place to forget one.
TECHNOLOGY_ANSWERED: Tuple[str, ...] = tuple(
    q.key for q in QUESTIONS if q.answered_by == ANSWERED_BY_TECHNOLOGY)


def question(key: str) -> Optional[Question]:
    for q in QUESTIONS:
        if q.key == key:
            return q
    return None


def blank_declaration() -> Dict[str, Any]:
    """All 18 questions plus contract fields, all `NOT_DETERMINED`.

    This is the ONLY constructor. There is no variant that pre-fills anything,
    because the moment one exists somebody calls it.
    """
    doc: Dict[str, Any] = {
        "schema": SCHEMA,
        "answers": {q.key: NOT_DETERMINED for q in QUESTIONS},
        FORBIDDEN_LAYERS_KEY: NOT_DETERMINED,
        SYNTHESIS_AREA_BUDGET_KEY: NOT_DETERMINED,
    }
    return doc


def area_budget_resolution(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return the typed Phase-1 disposition of the synthesis area question.

    Status is one of ``UNSET``, ``INVALID``, ``LIMIT`` or
    ``NOT_APPLICABLE``. This helper invents no value and deliberately keeps an
    unanswered field distinct from an explicit N/A declaration.
    """
    raw = doc.get(SYNTHESIS_AREA_BUDGET_KEY)
    if not is_answered(raw):
        return {"status": "UNSET", "raw": raw}
    if not isinstance(raw, dict):
        return {"status": "INVALID", "raw": raw,
                "reason": "the declaration is not a mapping"}
    status = raw.get("status")
    if status == AREA_BUDGET_LIMIT:
        dims = raw.get("max_die_dimensions_um")
        if not (isinstance(dims, (list, tuple)) and len(dims) == 2
                and all(_is_number(v) and v > 0 for v in dims)):
            return {"status": "INVALID", "raw": raw,
                    "reason": "LIMIT needs two positive dimensions in um"}
        w, h = float(dims[0]), float(dims[1])
        wxh = f"{w:g}x{h:g}"
        return {
            "status": AREA_BUDGET_LIMIT,
            "raw": raw,
            "max_die_dimensions_um": [w, h],
            "ceiling_wxh_um": wxh,
            "ceiling_um2": w * h,
        }
    if status == AREA_BUDGET_NOT_APPLICABLE:
        rationale = raw.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            return {"status": "INVALID", "raw": raw,
                    "reason": "NOT_APPLICABLE needs a non-empty rationale"}
        return {"status": AREA_BUDGET_NOT_APPLICABLE, "raw": raw,
                "rationale": rationale.strip()}
    return {"status": "INVALID", "raw": raw,
            "reason": f"unknown status {status!r}"}


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


def technology_refusals(claimed: Dict[str, Any],
                        facts: Dict[str, Any],
                        claimed_by: str = "the design") -> List[Dict[str, Any]]:
    """Refuse `claimed` where it contradicts the run's own technology.

    `claimed` is whatever answers file was about to be published (the design's,
    or the design's under an operator's); `facts` is the transcription record
    written by the fetch — `{key: {"value": ..., "source": "<path>:<line>",
    "statement": ..., "pdk": ...}}`.

    A refusal is returned only for a DISAGREEMENT, and it names BOTH values and
    the run's PDK, because the reader's next question is always "which of the
    two is this run?". Agreement is NOT a refusal: it earns a note from the
    caller and the technology's value is published either way. Silence — the
    design left the field NOT_DETERMINED, which is what both corpus designs
    correctly did — is not a refusal either.

    Returns [] when there is nothing to refuse. Never raises.
    """
    out: List[Dict[str, Any]] = []
    for key in TECHNOLOGY_ANSWERED:
        rec = (facts or {}).get(key)
        if not isinstance(rec, dict):
            continue
        measured = rec.get("value")
        if not _is_number(measured):
            continue
        said = (claimed or {}).get(key)
        if not is_answered(said) or said == measured:
            continue
        out.append(_refusal(
            RULE_TECHNOLOGY_FACT_FROM_DESIGN,
            f"{claimed_by} answers {key}={said!r}, and the technology this "
            f"run targets declares {measured!r}: "
            f"{rec.get('statement') or '(no statement recorded)'} at "
            f"{rec.get('source') or '(no source recorded)'} for PDK "
            f"{rec.get('pdk')!r}. {key} is a fact of the TECHNOLOGY, not a "
            f"claim the design is entitled to make, and the two do not agree. "
            f"The transcribed value is what this declaration carries; the "
            f"answered one is refused. Remove it from the answers file — a "
            f"design that states it can only ever be right for one of the "
            f"processes it names.",
            key=key, answered=said, technology=measured,
            source=rec.get("source"), pdk=rec.get("pdk"),
            claimed_by=claimed_by))
    return out


def merge_technology(doc: Dict[str, Any],
                     facts: Dict[str, Any]) -> Dict[str, Any]:
    """Publish the transcribed technology facts into `doc`, provenance and all.

    The VALUE lands in `answers`, where every consumer already reads it. The
    RECORD lands under `TECHNOLOGY_KEY`, so the declaration says out loud that
    this field came from a technology file and names the file and line. A fact
    with no usable value is carried for its provenance and answers nothing —
    "we looked and could not read it" must never arrive as a number.
    """
    if not isinstance(facts, dict) or not facts:
        return doc
    doc[TECHNOLOGY_KEY] = facts
    for key in TECHNOLOGY_ANSWERED:
        rec = facts.get(key)
        if isinstance(rec, dict) and _is_number(rec.get("value")):
            doc.setdefault("answers", {})[key] = rec["value"]
    return doc


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


def declared_route_on_disk(project: Path, has_slots: bool
                           ) -> Tuple[str, Optional[str]]:
    """The route THE DECLARATION FILE ON DISK selects, and why not if none.

    THE ROUTE WORD IS NOT A REASON, AND THIS FUNCTION EXISTS SO A REFUSAL CAN
    SAY SO PRECISELY. `submission_template_check` reports it inside
    NO_TEMPLATE_WITHOUT_REASON to name what it already read: the route is
    computed by `route_of` from `deliverable` AND the absence of ingested slot
    files, so on the self-tape-out arm it is derived from the very absence
    whose reason is being asked for. Naming it is disclosure; it never buys a
    verdict, here or in any caller.

    Read through `route_of` — the same predicate `tapeout_declaration_gen` used
    when it chose which router file to write — so what this reports can never
    be a route the producer would have refused.

    `NOT_DETERMINED` is returned, never raised and never defaulted, whenever
    the declaration is absent, unreadable, not a mapping, not stamped with this
    module's schema, or answers no `deliverable`. The second element names
    which of those it was, because "I could not read it" and "I read it and it
    declared nothing" are two different facts and a caller quoting one must not
    be handed the other.
    """
    path = project / DECLARATION_REL
    if not path.is_file():
        return NOT_DETERMINED, f"{DECLARATION_REL} is not on disk"
    doc, err = load(path)
    if err is not None:
        return NOT_DETERMINED, err
    if not isinstance(doc, dict):
        return NOT_DETERMINED, (f"{DECLARATION_REL}'s top level is "
                                f"{type(doc).__name__}, not a mapping")
    if doc.get("schema") != SCHEMA:
        return NOT_DETERMINED, (f"{DECLARATION_REL} does not declare schema "
                                f"{SCHEMA!r} (found {doc.get('schema')!r})")
    route = route_of(doc, has_slots)
    if route == NOT_DETERMINED:
        return route, (f"{DECLARATION_REL} is a declaration and answers no "
                       f"`deliverable`, so it selects no route")
    return route, None


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
        "synthesis_area_budget": area_budget_resolution(doc),
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
RULE_AREA_BUDGET_INVALID = "SYNTHESIS_AREA_BUDGET_INVALID"


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
    because that is a declaration nobody can read — except the additive
    `synthesis_area_budget` field, whose absence in a legacy declaration is
    deliberately the UNSET state. A present malformed value is always refused.
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
    # `synthesis_area_budget` was added to the existing schema by #1982. Its
    # absence in a pre-existing declaration is the UNSET state, not malformed
    # evidence; only a typed LIMIT or NOT_APPLICABLE changes that state. Keep
    # the older forbidden-layers field structurally required as before.
    for key in (FORBIDDEN_LAYERS_KEY,):
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

    # THE TECHNOLOGY'S OWN SIDE (#2070). Two things are refused here, and
    # nothing else about this key is:
    #
    #   1. A refusal the PRODUCER recorded is re-emitted, so it reaches the
    #      reader through the same channel every other declaration refusal
    #      does. `tapeout_declaration_gen` exits 1 on a non-empty refusal list,
    #      which is what gives a design's contradicted claim about the
    #      technology actual teeth instead of a note nobody reads.
    #   2. A declaration whose published unit DISAGREES with the very
    #      technology record it cites is malformed — not incomplete. It is the
    #      one shape that cannot be true, and it is exactly what a partial
    #      hand-edit of either half produces.
    #
    # An ABSENT `from_the_technology` is NOT refused. A declaration written
    # before this key existed, or a run that could not read the tech LEF and
    # said so, is incomplete — and incomplete is the consuming check's
    # NOT_DETERMINED to report, never a malformed-evidence refusal here.
    tech = doc.get(TECHNOLOGY_KEY)
    if isinstance(tech, dict):
        for rec in (tech.get("refusals") or []):
            if isinstance(rec, dict) and rec.get("rule") and rec.get("message"):
                out.append(dict(rec))
        for key in TECHNOLOGY_ANSWERED:
            fact = tech.get(key)
            if not isinstance(fact, dict) or not _is_number(fact.get("value")):
                continue
            published = answers.get(key)
            if is_answered(published) and published != fact["value"]:
                out.append(_refusal(
                    RULE_TECHNOLOGY_FACT_FROM_DESIGN,
                    f"the declaration publishes {key}={published!r} while the "
                    f"technology record it carries says {fact['value']!r} "
                    f"(read at {fact.get('source')!r} for PDK "
                    f"{fact.get('pdk')!r}). A declaration that contradicts its "
                    f"own cited source cannot be read by anybody",
                    key=key, published=published, technology=fact["value"]))

    budget = area_budget_resolution(doc)
    if budget["status"] == "INVALID":
        out.append(_refusal(
            RULE_AREA_BUDGET_INVALID,
            f"{SYNTHESIS_AREA_BUDGET_KEY!r} is malformed: "
            f"{budget.get('reason')}. Use "
            "{status: 'LIMIT', max_die_dimensions_um: [W, H]} or "
            "{status: 'NOT_APPLICABLE', rationale: '...'}; leaving the "
            f"field {NOT_DETERMINED!r} is incomplete but not malformed",
            key=SYNTHESIS_AREA_BUDGET_KEY))
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
