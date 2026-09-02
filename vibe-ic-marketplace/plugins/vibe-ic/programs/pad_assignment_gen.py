#!/usr/bin/env python3
"""pad_assignment_gen — the AUTHOR of `phase3/stage3/pnr/pad_assignment.json`.

ENFORCEMENT: blocking — ``phase3_one_shot_runner.step_pad_ring_gen`` invokes
this program inline before routing. Any nonzero rc makes that step non-PASS;
``_prepare_padring_for_route`` then returns no routing consumer and the PnR
step fails with ``PADRING_PREROUTE_BLOCKED``. Canonical step 15.5ic also
consumes the same rc through a blocking ``program_exit_zero`` clause. This
token names the measured runner/flow control path, not finding severity. Kept
in the first 4 kB because ``declared_intent`` reads only ``text[:4000]``.

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

THE THIRD SOURCE — WHAT THE DESIGN ALREADY WROTE DOWN
=====================================================
MEASURED on the self-tape-out re-run: this program reported NOT_ASKED with
0 of 8 answered, step 15.5ic refused, PnR would not route, and 17 steps
stayed blocked with no layout, no DRC, no LVS and no post-layout equivalence
check. THE DESIGN WAS NOT SILENT. Its external-interface document carries a
`Physical Pad Placement` section partitioning EVERY top-level port across the
four die edges, one pad per bus bit, and its product-metadata document states
that the pad count is deliberately unpinned BECAUSE it follows from that port
list. Nothing read either. So a third source is added below the other two:

    the design's own       `input/docs` / `phase1/input_doc` / generated docs
    L-DOCUMENTS            (`_l_doc_pad_placement`)
    the IO library those   the PDK TECH-view config the documents DELEGATE the
    documents delegate to  IO cell library to (`_pad_ring.parse_pad_env_
                           declarations`), read only when a document says so

and it is the LOWEST of the three, so a slot file and a hand-written
declaration both keep the behaviour they had.

WHAT THE DESIGN'S DOCUMENTS DO NOT ANSWER, AND WHY IT IS NOT FILLED IN
=====================================================================
`PAD_SOUTH`/`PAD_EAST`/`PAD_NORTH`/`PAD_WEST` and `SIGNAL_MAP` are lists of
NETLIST INSTANCES — upstream resolves each against the block. A document
partitions PORTS, and the derived partition is carried in the report under
`design_pad_partition` so a reader sees exactly what the design DID answer.
It is NOT written into the config: naming instances that the netlist does not
contain would be inventing the one thing this step exists to refuse to invent.
Those two questions therefore stay OWED, and the step keeps refusing.

AND THE NEAR MISS, REFUSED ON PURPOSE
=====================================
The pad-placement section states a minimum distance BETWEEN PADS on one side.
`PAD_EDGE_SPACING` is the distance FROM THE DIE EDGE TO THE IO ROW. Different
lengths, same unit. `_l_doc_pad_placement` parses the first, carries it as
`min_pad_distance_um`, and nothing maps it to the second.

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

import _l_doc_pad_placement as LDOC
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
            "design_documents": [],
            "design_documents_unreadable": [],
        },
        "design": None,
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


#: The variables a PDK IO-library config may DECLARE, and which question each
#: answers. Every one is a property of the IO CELL LIBRARY, which is what a
#: design document delegates when it says the IO cells are the PDK's. The four
#: per-side lists and `SIGNAL_MAP` are deliberately NOT here: they are netlist
#: instances, and no PDK declares this design's instances.
PDK_DELEGATED_VARS: Tuple[str, ...] = (
    "PAD_SITE_NAME", "PAD_CORNER_SITE_NAME", "PAD_EDGE_SPACING",
    "PAD_ROTATION_HORIZONTAL", "PAD_ROTATION_VERTICAL", "PAD_ROTATION_CORNER",
    "PAD_CORNER", "PAD_FILLERS",
)

#: The three of `PDK_DELEGATED_VARS` that NOTHING else in the flow can answer:
#: the two site names and the die-edge-to-IO-row distance. `PAD_CORNER` and
#: `PAD_FILLERS` reach `read_derived_chip_top` by their own route (the producer
#: confirms each against a macro the LEF carries); these three are values, not
#: masters, so there is nothing to confirm them against and they are
#: transcribed with their file:line or not at all.
PDK_LIBRARY_OWNED_VARS: Tuple[str, ...] = (
    "PAD_SITE_NAME", "PAD_CORNER_SITE_NAME", "PAD_EDGE_SPACING",
)

#: Variables upstream spells as one whitespace-separated string and this
#: flow's config contract spells as a list. Splitting on whitespace is a
#: TRANSCRIPTION of one file format into another; no element is added, dropped
#: or reordered, and an empty declaration stays empty rather than becoming a
#: default.
PDK_LIST_VARS: Tuple[str, ...] = ("PAD_FILLERS",)


def read_design_documents(project: Path, pdk_root: Optional[str],
                          pdk: Optional[str]
                          ) -> Tuple[Dict[str, Dict[str, Any]],
                                     Dict[str, Any]]:
    """(by_var, record) — what the DESIGN'S OWN DOCUMENTS answer.

    `by_var` carries only variables a document, or the IO library a document
    DELEGATES to, actually states. `record` is everything a reader needs to
    check that against the documents by hand: which files were scanned, which
    section was read, the per-side PORT partition derived from it, and every
    file and line a delegated value came from.

    THE GATE, STATED ONCE: when no document states a pad placement, this
    function contributes NOTHING — not the partition and not the delegated
    library either, because a design that says nothing about its pad ring has
    delegated nothing about it. A reader that always finds an answer is a
    defaulter, and a defaulted pad ring is invented geometry.
    """
    record: Dict[str, Any] = {
        "documents_scanned": [],
        "documents_unreadable": [],
        "placement": None,
        "parameter_defaults": {},
        "pad_partition_by_side": None,
        "pad_partition_total": None,
        "pad_partition_unresolved": [],
        "pdk_io_library_configs": [],
        "pdk_declarations": {},
        "pdk_declarations_unresolved": [],
        "pdk_declaration_conflicts": [],
    }
    by_var: Dict[str, Dict[str, Any]] = {}

    placement, params, unreadable, scanned = LDOC.read_project_placement(project)
    record["documents_scanned"] = scanned
    record["documents_unreadable"] = unreadable
    record["parameter_defaults"] = dict(params)
    if placement is None:
        return by_var, record
    record["placement"] = placement.as_dict()

    ports, unresolved = LDOC.expand_side_ports(placement, params)
    record["pad_partition_unresolved"] = unresolved
    if not unresolved:
        record["pad_partition_by_side"] = {s: list(v) for s, v in ports.items()}
        record["pad_partition_total"] = sum(len(v) for v in ports.values())

    if not placement.delegates_io_library_to_pdk:
        return by_var, record

    declared: Dict[str, Dict[str, Any]] = {}
    for cfg in PR.discover_io_library_configs(pdk_root, pdk):
        try:
            text = cfg.read_text(errors="replace")
        except OSError as exc:
            record["documents_unreadable"].append(
                {"file": str(cfg), "reason": str(exc)})
            continue
        record["pdk_io_library_configs"].append(str(cfg))
        for var, (value, line) in PR.parse_pad_env_unresolved(text).items():
            if var in PDK_DELEGATED_VARS:
                # The library DOES declare it, in terms only Tcl can expand.
                # Recorded so the variable is reported as unread rather than
                # as absent, and left unanswered either way.
                record["pdk_declarations_unresolved"].append(
                    {"variable": var, "source": f"{cfg}:{line}", "raw": value})
        for var, (value, line) in PR.parse_pad_env_declarations(text).items():
            if var not in PDK_DELEGATED_VARS:
                continue
            prior = declared.get(var)
            if prior is not None and prior["raw"] != value:
                # Two IO libraries in one tree declaring one variable two
                # ways: which one this run uses is not something this program
                # can decide, and picking by directory order would decide it
                # silently.
                record["pdk_declaration_conflicts"].append(
                    {"variable": var, "first": prior["source"],
                     "first_value": prior["raw"],
                     "second": f"{cfg}:{line}", "second_value": value})
                continue
            declared[var] = {"raw": value, "source": f"{cfg}:{line}"}

    for var, rec in declared.items():
        value: Any = rec["raw"]
        if var in PDK_LIST_VARS:
            value = [tok for tok in rec["raw"].split() if tok]
        by_var[var] = {"value": value,
                       "source": f"pdk io library {rec['source']}"}
        record["pdk_declarations"][var] = {"value": value,
                                           "source": rec["source"]}
    return by_var, record


# --------------------------------------------------------------------------- #
# the merge
# --------------------------------------------------------------------------- #
#: What `io_pad_chip_top_gen` writes. Read here rather than re-derived: that
#: producer CREATED the pad instances, so it is the only thing in the flow that
#: can name them truthfully.
DERIVED_CHIP_TOP_REL = "reports/phase3/io_pad_chip_top.json"


def read_derived_chip_top(project: Path) -> Tuple[Dict[str, Dict[str, Any]],
                                                  Dict[str, Any]]:
    """The FOURTH SOURCE: variables derived by the IO-pad chip-top producer.

    THE THREE INSTANCE-KEYED QUESTIONS WERE UNANSWERABLE BY CONSTRUCTION.
    This file's own header records why: `PAD_SOUTH`/`PAD_EAST`/`PAD_NORTH`/
    `PAD_WEST` and `SIGNAL_MAP` "are lists of NETLIST INSTANCES", a document
    "partitions PORTS", and writing instance names for a netlist that does not
    contain them "would be inventing the one thing this step exists to refuse
    to invent". Both halves stayed true and the step kept refusing, for every
    design, on every chip route -- MEASURED on one benchmark IC and one open 5 V PDK at plugin
    1.15.67 as `PAD_INSTANCE_NOT_IN_BLOCK` even with all eight answered by
    hand.

    What changed is not the rule. `io_pad_chip_top_gen` now INSTANTIATES the
    pads, from the same partition this program already reads, so the instances
    exist and naming them is a statement of fact rather than an invention.
    Its record is read here, and only for the variables it actually created:
    the four side lists, the signal map and the three rotations.

    RANKED WITH THE DOCUMENTS, not above them. The slot and the declaration
    both still win, so a tree carrying either behaves exactly as it did.
    """
    rec_path = project / DERIVED_CHIP_TOP_REL
    info: Dict[str, Any] = {"file": DERIVED_CHIP_TOP_REL, "verdict": None}
    if not rec_path.is_file():
        info["verdict"] = "ABSENT"
        return {}, info
    try:
        doc = json.loads(rec_path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        info["verdict"] = "UNREADABLE"
        info["reason"] = str(exc)
        return {}, info
    info["verdict"] = doc.get("verdict")
    if doc.get("verdict") != "WROTE":
        return {}, info
    answers = doc.get("derived_answers") or {}
    basis = doc.get("derivation_basis") or {}
    out: Dict[str, Dict[str, Any]] = {}

    order = answers.get("pad_order_by_side")
    if isinstance(order, dict):
        for key, var in SIDE_KEY_TO_VAR:
            if isinstance(order.get(key), list):
                out[var] = {"value": order[key],
                            "source": f"{DERIVED_CHIP_TOP_REL} "
                                      f"(pad_order_by_side): "
                                      f"{basis.get('pad_order_by_side', '')}"}
    smap = answers.get("pad_signal_map")
    if isinstance(smap, dict) and smap:
        out["SIGNAL_MAP"] = {"value": smap,
                             "source": f"{DERIVED_CHIP_TOP_REL} "
                                       f"(pad_signal_map): "
                                       f"{basis.get('pad_signal_map', '')}"}
    rots = answers.get("pad_rotations")
    if isinstance(rots, dict):
        rot_basis = basis.get("pad_rotations") or {}
        for key, var in ROTATION_KEY_TO_VAR:
            if rots.get(key):
                out[var] = {"value": rots[key],
                            "source": f"{DERIVED_CHIP_TOP_REL} "
                                      f"(pad_rotations): "
                                      f"{rot_basis.get(key, '')}"}
    # PAD_CORNER / PAD_FILLERS. `read_design_documents` above cannot supply
    # these on a PDK that spells them with a Tcl substitution, and correctly
    # declines to guess; the producer resolved the substitution against the
    # library it read the LEFs from and confirmed the result is a macro that
    # library carries. Absent from the record means it did NOT confirm one, and
    # the variable stays owed.
    if answers.get("pad_corner_master"):
        out["PAD_CORNER"] = {
            "value": answers["pad_corner_master"],
            "source": f"{DERIVED_CHIP_TOP_REL} (pad_corner_master): "
                      f"{basis.get('pad_corner_master', '')}"}
    if answers.get("pad_fillers"):
        out["PAD_FILLERS"] = {
            "value": list(answers["pad_fillers"]),
            "source": f"{DERIVED_CHIP_TOP_REL} (pad_fillers): "
                      f"{basis.get('pad_fillers', '')}"}
    # THE THREE THE PDK OWNS, and why they are read HERE rather than re-read
    # from the PDK. `PAD_SITE_NAME`, `PAD_CORNER_SITE_NAME` and
    # `PAD_EDGE_SPACING` are properties of the IO CELL LIBRARY, so this program
    # answers them only when a caller supplies `--pdk-root/--pdk`. The FLOW
    # DECLARATION of step 15.5ic invokes it with neither -- MEASURED: on a tree
    # carrying this record, that invocation refuses with exactly these three
    # `PAD_CONFIG_VARIABLE_ABSENT` and nothing else -- while the runner passes
    # both, so the same tree answers 13 of 13 to one caller and 10 of 13 to the
    # other. The producer already RESOLVED all three, out of the one IO library
    # whose LEFs it read, and published each with its file:line. Reading its
    # record is therefore a transcription of what this run measured, not a
    # second guess at which library the run used -- the same standing this
    # function already gives `PAD_CORNER` and `PAD_FILLERS` from the same file.
    #
    # A value the producer did NOT publish stays owed. No default, here or
    # anywhere: an edge spacing invented on a tree whose PDK never resolved
    # would be indistinguishable in the artefact from a measured one.
    pdk_declared = doc.get("pdk_declared")
    pdk_sources = doc.get("pdk_declared_sources") or {}
    if isinstance(pdk_declared, dict):
        for var in PDK_LIBRARY_OWNED_VARS:
            value = pdk_declared.get(var)
            if value is None or value == "" or var in out:
                continue
            where = pdk_sources.get(var)
            out[var] = {
                "value": value,
                "source": f"{DERIVED_CHIP_TOP_REL} (pdk_declared): the IO "
                          f"cell library the design's documents delegate to, "
                          f"read by the producer at "
                          f"{where if where else 'a source it did not record'}"}
    info["variables"] = sorted(out)
    return out, info


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
            declaration: Optional[Dict[str, Any]],
            design_vars: Optional[Dict[str, Dict[str, Any]]] = None
            ) -> Tuple[Dict[str, Any], Dict[str, str], List[str], List[str]]:
    """(config, provenance, answered_questions, owed).

    Nothing is invented. Every value in `config` came verbatim from a slot
    file, from the declaration, or from a document the design itself wrote
    (or the IO library that document delegates to), and `provenance` says
    which for every variable.

    PRECEDENCE, highest first: the operator's slot, the design's own tape-out
    declaration, the design's documents. The documents are LAST on purpose —
    a tree that already carries either of the other two behaves exactly as it
    did before this source existed.
    """
    design_vars = design_vars or {}
    from_design: set = set()
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
            elif var in design_vars:
                config[var] = design_vars[var]["value"]
                provenance[var] = design_vars[var]["source"]
                from_design.add(var)
            else:
                owed.append(f"{var} (declaration question {question})")

        # A question the DESIGN'S DOCUMENTS answered counts as answered only
        # when EVERY variable behind it resolved. A source that states four of
        # a question's five variables has not answered it, and counting it
        # would make the report claim more was known than is. The declaration
        # keeps its own rule above — a declaration somebody STARTED and left
        # must stay distinguishable from one nobody was asked.
        if (question not in answered
                and any(v in from_design for v in variables)
                and all(v in config for v in variables)):
            answered.append(question)
    return config, provenance, answered, owed


# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None,
                    help=f"report destination (default {REPORT_REL})")
    ap.add_argument("--out", default=None,
                    help=f"config destination (default {PR.ASSIGNMENT_REL})")
    ap.add_argument("--pdk-root", default=None,
                    help="PDK root; only read when a design document DELEGATES "
                         "the IO cell library to the PDK. Absent means the "
                         "delegated variables stay unanswered, never defaulted.")
    ap.add_argument("--pdk", default=None, help="PDK tree name under --pdk-root")
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
    design_vars, design = read_design_documents(project, args.pdk_root, args.pdk)
    derived_vars, derived = read_derived_chip_top(project)
    # THE PRODUCER'S RECORD WINS WITHIN THIS TIER. Both are derived from the
    # design's own documents plus the library; only one of them created the
    # instances it names.
    merged_design_vars = dict(design_vars)
    merged_design_vars.update(derived_vars)
    config, provenance, answered, owed = compose(slot_vars, declaration,
                                                 merged_design_vars)

    sources = {
        "slot_files": slot_files,
        "slot_files_unreadable": slot_unreadable,
        "slot_lists_without_a_side": unsided,
        "declaration": (TD.DECLARATION_REL
                        if declaration is not None else None),
        "declaration_unreadable": decl_why,
        "design_documents": design["documents_scanned"],
        "design_documents_unreadable": design["documents_unreadable"],
        "derived_chip_top": derived,
    }
    common = dict(sources=sources,
                  design=design,
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

    if design["documents_unreadable"]:
        named = "; ".join(f"{u['file']} ({u['reason']})"
                          for u in design["documents_unreadable"])
        return _emit(
            "REFUSE",
            f"{len(design['documents_unreadable'])} design input document(s) "
            f"could not be read or state something this program will not "
            f"interpret, so what the design says about its pad ring is "
            f"UNKNOWN rather than absent: {named}",
            [_finding("ERROR", "DESIGN_DOCUMENT_UNREADABLE", named)], 1)

    if design["pdk_declaration_conflicts"]:
        named = "; ".join(
            f"{c['variable']}: {c['first']}={c['first_value']!r} vs "
            f"{c['second']}={c['second_value']!r}"
            for c in design["pdk_declaration_conflicts"])
        return _emit(
            "REFUSE",
            f"the design's documents delegate the IO cell library to the PDK "
            f"and the PDK tree declares the same pad variable two different "
            f"ways in two IO libraries. Nothing here can say which library "
            f"this run uses, and choosing by directory order would choose it "
            f"silently: {named}",
            [_finding("ERROR", "PDK_IO_LIBRARY_DECLARATION_CONFLICT", named)],
            1)

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
    if not answered and not slot_vars and not design_vars:
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

    # ── a source spoke, and the contract is still incomplete ───────────────
    # TWO WAYS TO GET HERE, and the message says which, because the reader's
    # next move differs:
    #   the DESIGN answered some of section 2B and not the rest — a
    #   declaration somebody started and left;
    #   the OPERATOR's slot pinned the per-side pad lists and the design has
    #   answered nothing. That is NOT "nobody was asked": a source was asked
    #   and answered, and reporting NOT_ASKED would be false about the tree.
    #   It is also the ONLY thing an operator template can supply — a slot
    #   file carries no site name, no spacing, no rotation, no corner master,
    #   no filler and no signal map — so the remaining nine are owed by the
    #   design whatever the operator published.
    if owed:
        named = "; ".join(owed)
        if answered and design_vars:
            started = (f"section {TD.SECTION_PAD_RING} is now "
                       f"{len(answered)} of {len(_2B_KEYS)} answered, "
                       f"{len(design_vars)} variable(s) of it read out of the "
                       f"design's own documents and the IO cell library those "
                       f"documents delegate to")
            note = ""
            if design.get("pad_partition_by_side"):
                sides = design["pad_partition_by_side"]
                note = (
                    f" THE DESIGN DID ANSWER THE PARTITION: "
                    f"{design['pad_partition_total']} pads, "
                    + ", ".join(f"{k} {len(v)}" for k, v in sorted(sides.items()))
                    + f", from {design['placement']['source']} section "
                    f"{design['placement']['heading']!r}. What is still owed "
                    f"is not a design statement: the four side lists and "
                    f"SIGNAL_MAP name NETLIST INSTANCES, upstream resolves "
                    f"each against the block, and no document can name an "
                    f"instance the netlist does not contain. The partition is "
                    f"in this report under `design.pad_partition_by_side`; it "
                    f"is NOT written into the config, because writing "
                    f"instance names for pads that do not exist would put "
                    f"invented geometry into an artefact.")
        elif answered:
            started = (f"declaration section {TD.SECTION_PAD_RING} was STARTED "
                       f"({len(answered)} of {len(_2B_KEYS)} question(s) "
                       f"answered)")
            note = ""
        else:
            started = (f"the operator's slot geometry pinned "
                       f"{len(slot_vars)} of the {len(PR.REQUIRED_VARS)} "
                       f"variables while declaration section "
                       f"{TD.SECTION_PAD_RING} answers none of its "
                       f"{len(_2B_KEYS)} questions")
            note = (" A slot file cannot supply the rest — it carries no site "
                    "name, no edge spacing, no rotation, no corner master, no "
                    "filler and no signal map — so these are owed by the "
                    "design whatever the operator published.")
        return _emit(
            "REFUSE",
            f"{started} and still owes {len(owed)} of the "
            f"{len(PR.REQUIRED_VARS)} variables `pad_ring_gen` requires."
            f"{note} No value is guessed for any of them — a pad site, an "
            f"edge spacing or a filler invented here would be "
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
    # EVERY TIER IS COUNTED, INCLUDING THE NEW ONE. The sentence used to end
    # "none was derived" and count two tiers, which was true while there were
    # only two; with a producer-derived tier in the mix, a summary that named
    # 5 of 13 sources would have read as a partial resolution of a complete
    # config. A reader must be able to see, from this line alone, that eight
    # of these values came from a program rather than from a person.
    n_slot = sum(1 for v in provenance.values() if v.startswith('slot '))
    n_decl = sum(1 for v in provenance.values()
                 if v.startswith('declaration'))
    n_derived = sum(1 for v in provenance.values()
                    if v.startswith(DERIVED_CHIP_TOP_REL))
    n_docs = len(provenance) - n_slot - n_decl - n_derived
    reason = (
        f"every one of the {len(PR.REQUIRED_VARS)} variables `pad_ring_gen` "
        f"requires resolved from a stated source; nothing was guessed. "
        f"{n_slot} came from the operator's slot geometry, "
        f"{n_decl} from the design's own tape-out declaration, "
        f"{n_docs} from the design's documents and the IO library they "
        f"delegate to, and {n_derived} were DERIVED by "
        f"`io_pad_chip_top_gen` from that same partition plus the library — "
        f"the instances it names exist because it created them.")
    return _emit("WROTE", reason, [], 0, config_written=written)


if __name__ == "__main__":                                 # pragma: no cover
    raise SystemExit(main())
