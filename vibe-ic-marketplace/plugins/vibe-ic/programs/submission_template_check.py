#!/usr/bin/env python3
"""Gate the shuttle-template ingest — step 0.5ic's verdict.

ENFORCEMENT: advisory here — this gate is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; no one-shot runner invokes
it inline at all. It runs when ``flow_compliance_check`` evaluates step 0.5ic's
``program_exit_zero`` clause, so its rc IS that step's verdict — "advisory"
names the RUNNER channel it is absent from, not a verdict this gate cannot
reach. Declared because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
enforcement decision nobody made; wiring it into the runner would change what a
real run blocks on, which is the flow owner's call and is recorded, not taken
here. Kept in the first 4 kB: `declared_intent` reads only `text[:4000]`.

Judges the record `submission_template_ingest` wrote: that the template it
claims is really on disk and unchanged, that the slot geometry does not
disagree with itself, that the slot this design DECLARED is one the template
actually ships, and that an absent template reads as NOT_APPLICABLE with a
stated reason rather than as a clean run.

WHAT IT REFUSES
===============
    NEVER_LOOKED                  no template path was ever given. This is not
                                  the same fact as a template that is absent,
                                  and no stated reason can buy it: a reason
                                  offered for a template nobody searched for
                                  describes nothing.
    NO_TEMPLATE_WITHOUT_REASON    a template was searched for and is not there,
                                  and the record states no usable reason why
                                  that is a genuine not-applicable here.
    TEMPLATE_NOT_ON_DISK          the record claims a template, and the root or
                                  a slot's source file is not there.
    TEMPLATE_CHANGED_SINCE_INGEST a source file is there and no longer hashes to
                                  what the record says it did.
    TEMPLATE_SHIPS_NO_SLOTS       a template was read and pinned no slot at all.
    SLOT_GEOMETRY_INCOMPLETE      a slot pins a die and no core, so its geometry
                                  cannot be checked against itself.
    SLOT_GEOMETRY_DEGENERATE      a rect that is not four numbers, or has a
                                  non-positive width or height.
    PAD_LIST_UNREAD               a slot declares no pad list under any name the
                                  ingester knows, while the same file does carry
                                  list-valued keys it did not claim. That is not
                                  a slot with no pads; it is a slot whose pads
                                  were not understood, and the two must not
                                  share an answer.
    CORE_NOT_INSIDE_DIE           the core rect is not contained in the die rect.
    RING_DISAGREES                the slot DECLARES a ring width and the die is
                                  not the core grown by it on all four sides.
    SLOT_NAME_COLLISION           two slot files pin the same slot name to
                                  different geometry.
    SLOT_NOT_SHIPPED              the declared slot is not one the template ships.
    SLOT_NOT_DECLARED             a template was ingested and no slot was chosen.
                                  A die that was chosen and a die that was
                                  defaulted are the same number with different
                                  provenance, and only one of them can be checked.
    TREE_SAYS_BOTH                the tree carries slot files AND a no-template
                                  marker, so the step's own output says two
                                  things at once.
    TREE_DISAGREES_WITH_REPORT    the record and the files on disk do not agree
                                  about what was produced.
    SLOT_FILE_DISAGREES_WITH_RECORD
                                  the slot file a later step will open does not
                                  carry the geometry the record says it does. A
                                  report that agrees with the operator and
                                  disagrees with its own output has pinned
                                  nothing.
    NO_TEMPLATE_FILE_MISSING      the record DECLARES there is no template and
                                  the file that declaration lives in — the one
                                  the flow routes the IP path on — is not there.
    REPORT_ABSENT / REPORT_UNREADABLE / REPORT_SCHEMA
                                  there is no record to judge, which is a
                                  refusal and never a quiet pass.

THE TWO OUTPUTS ARE ROUTERS
==========================
Measured on the flow that consumes them: `slots/*.yaml` makes the chip-path
steps applicable and `NO_TEMPLATE.txt` makes the IP-path step applicable, by a
`files_exist` condition and nothing else. No step blocks on this one and no step
takes a required_input from it, so THIS GATE'S OWN FAIL DOES NOT STOP EITHER
PATH FROM BEING SELECTED — the file existing is the whole decision.

So an absence has to be BOUGHT before it is written, and this gate tests the
same predicate the producer used, out of the same module, so the two cannot
drift into a file one wrote and the other would have refused.

NOT_APPLICABLE IS NOT A PASS
============================
An absent template WITH a stated reason exits 0 and is recorded as
NOT_APPLICABLE -- never PASS, and never a bare boolean that conflates the two.
This is the idiom the flow already uses for an unmet `condition_files_exist`:
nothing to check is a FAIL unless the absence is BOUGHT with a declaration, and
the declaration is then made VISIBLE rather than folded into a clean verdict.
The floor on that reason is read from the same module the flow's own gate reads
it from, so the two cannot drift apart.

Usage:
    submission_template_check <project_dir> --json <report path>
    submission_template_check <project_dir>            # human-readable

Exit codes:
    0 = PASS, or NOT_APPLICABLE with a stated reason
    1 = FAIL — at least one refusal above fired

Generality: works for ANY shuttle operator's template. No vendor, SKU or
process-node literal appears here.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling imports below resolve however this is invoked

import _submission_template as ST  # noqa: E402
import _tapeout_declaration as TD  # noqa: E402  the OTHER half of step 0.5ic
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402  vibe-ic#1082


PROGRAM = "submission_template_check"


def _declared_absence_router(project: Path) -> Optional[str]:
    """Which router file a DECLARED absence of a template lives in, or None.

    STEP 0.5ic HAS TWO PROGRAMS AND THEY BOTH WRITE HERE. `submission_template_
    ingest` records the absence and writes `NO_TEMPLATE.txt`;
    `tapeout_declaration_gen` — the other half of the SAME step — then RETIRES
    that marker on purpose when the design declares `deliverable=DIE`, because
    `NO_TEMPLATE.txt` is the IP terminal's router (37.5ip) and a die must not
    select it. It writes `SELF_TAPEOUT.txt` in its place.

    So a declared absence legitimately lives in either file, and which one is
    decided by the design's own declaration rather than by this checker.
    (`slots/*.yaml` is the third router and is not an absence at all.)

    A FILE COUNTS ONLY WHEN IT CARRIES ITS PRODUCER'S MARKER on the first line.
    That is the same test both producers already apply before retiring a marker
    of their own: a file some other hand left behind is evidence of nothing,
    and accepting it would let an empty file of the right name buy a pass.
    """
    for rel, marker in ((ST.NO_TEMPLATE_REL, ST.NO_TEMPLATE_MARKER),
                        (TD.SELF_TAPEOUT_REL, TD.SELF_TAPEOUT_MARKER)):
        path = project / rel
        if not path.is_file():
            continue
        try:
            head = path.read_text(errors="replace").splitlines()[:1]
        except OSError:
            continue
        if head and head[0].strip() == marker:
            return rel
    return None


def _refusal(rule: str, message: str, **extra) -> Dict[str, Any]:
    r = {"rule": rule, "message": message}
    r.update(extra)
    return r


def _rect(field: Optional[dict]) -> Optional[List[Decimal]]:
    """The parsed rect a record field carries, as exact Decimals."""
    if not field or not field.get("rect"):
        return None
    try:
        return [Decimal(str(c)) for c in field["rect"]]
    except Exception:                                        # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# geometry — a slot file checked against itself
# --------------------------------------------------------------------------- #
def check_slot_geometry(slot: dict) -> List[Dict[str, Any]]:
    """Refusals raised by ONE slot record read against itself."""
    out: List[Dict[str, Any]] = []
    name = slot.get("slot")
    src = slot.get("source_file")

    die_f, core_f = slot.get("die_area"), slot.get("core_area")
    if die_f is None:
        out.append(_refusal(
            "SLOT_GEOMETRY_DEGENERATE",
            f"slot {name!r} ({src}) pins no {ST.DIE_AREA_KEY}",
            slot=name, source_file=src))
        return out
    if core_f is None:
        out.append(_refusal(
            "SLOT_GEOMETRY_INCOMPLETE",
            f"slot {name!r} ({src}) pins {ST.DIE_AREA_KEY} and no "
            f"{ST.CORE_AREA_KEY}, so its die cannot be checked against its own "
            f"core. An unverifiable slot is not a verified one.",
            slot=name, source_file=src))
        return out

    die, core = _rect(die_f), _rect(core_f)
    for label, field, rect in (("die", die_f, die), ("core", core_f, core)):
        if rect is None:
            out.append(_refusal(
                "SLOT_GEOMETRY_DEGENERATE",
                f"slot {name!r} ({src}): {label} value "
                f"{field.get('raw')!r} is not a rect of four numbers",
                slot=name, source_file=src))
    if die is None or core is None:
        return out

    for label, rect in (("die", die), ("core", core)):
        w, h = ST.rect_wh(rect)
        if w <= 0 or h <= 0:
            out.append(_refusal(
                "SLOT_GEOMETRY_DEGENERATE",
                f"slot {name!r} ({src}): {label} rect has non-positive extent "
                f"{ST.dec_str(w)} x {ST.dec_str(h)}",
                slot=name, source_file=src))
    if out:
        return out

    left, bottom = core[0] - die[0], core[1] - die[1]
    right, top = die[2] - core[2], die[3] - core[3]
    if min(left, bottom, right, top) < 0:
        out.append(_refusal(
            "CORE_NOT_INSIDE_DIE",
            f"slot {name!r} ({src}): the core rect is not contained in the die "
            f"rect — margins (l,b,r,t) = "
            f"({ST.dec_str(left)}, {ST.dec_str(bottom)}, "
            f"{ST.dec_str(right)}, {ST.dec_str(top)})",
            slot=name, source_file=src))
        return out

    ring = slot.get("ring")
    if ring and ring.get("value") is not None:
        want = Decimal(str(ring["value"]))
        if not (left == bottom == right == top == want):
            out.append(_refusal(
                "RING_DISAGREES",
                f"slot {name!r} ({src}) declares {ring['key']} = "
                f"{ring['raw']!r}, so {ST.DIE_AREA_KEY} must be "
                f"{ST.CORE_AREA_KEY} grown by {ST.dec_str(want)} on all four "
                f"sides. Measured margins (l,b,r,t) = "
                f"({ST.dec_str(left)}, {ST.dec_str(bottom)}, "
                f"{ST.dec_str(right)}, {ST.dec_str(top)}).",
                slot=name, source_file=src))
    return out


def check_slot_pads(slot: dict) -> List[Dict[str, Any]]:
    """Refusals raised by ONE slot's pad declaration.

    MEASURED against a real operator template: its slot files carry one pad list
    PER DIE SIDE, and an ingester looking for a single singular key found none
    and recorded a null. Nothing refused that, so "this slot has no pads" and
    "this program did not understand this slot" were the same sentence. They are
    not the same sentence any more.
    """
    pads = slot.get("pads") or {}
    if pads.get("lists"):
        return []
    unmatched = pads.get("unmatched_list_keys") or []
    if not unmatched:
        return []          # genuinely no list-valued key at all: nothing missed
    return [_refusal(
        "PAD_LIST_UNREAD",
        f"slot {slot.get('slot')!r} ({slot.get('source_file')}) declares no pad "
        f"list matching {pads.get('pattern')!r}, and the same file carries "
        f"{len(unmatched)} list-valued key(s) this program did not claim: "
        f"{', '.join(map(str, unmatched))}. A slot whose pads were not "
        f"understood must not read as a slot with no pads.",
        slot=slot.get("slot"), source_file=slot.get("source_file"),
        unmatched_list_keys=unmatched)]


def _geometry_key(slot: dict) -> tuple:
    die, core = slot.get("die_area") or {}, slot.get("core_area") or {}
    return (tuple(die.get("rect") or ()), tuple(core.get("rect") or ()))


# --------------------------------------------------------------------------- #
# the whole record
# --------------------------------------------------------------------------- #
def evaluate(project: Path, doc: Optional[dict],
             report_problem: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The verdict on one project's step-0.5ic record.

    Returns the `check` block. Every counted denominator it used is in
    `examined`, because a check that ran over nothing and a check that ran over
    everything must not produce the same sentence.
    """
    refusals: List[Dict[str, Any]] = []
    examined: Dict[str, Any] = {
        "slots_in_record": 0, "slot_files_on_disk": 0,
        "fixtures_in_record": 0, "template_files_rehashed": 0,
        "path_router_on_disk": False,
    }
    na_reason: Optional[str] = None

    slots_dir = project / ST.SLOTS_DIR_REL
    on_disk = sorted(slots_dir.glob("*.yaml")) if slots_dir.is_dir() else []
    no_tmpl = project / ST.NO_TEMPLATE_REL
    examined["slot_files_on_disk"] = len(on_disk)
    # A FILESYSTEM FACT, AND IT MUST STAY ONE. This says whether the IP
    # terminal's router is on disk, marker or no marker, because the refusal
    # that reads it — NEVER_LOOKED / NO_TEMPLATE_WITHOUT_REASON, "and the file
    # IS on disk, which is the file the flow selects its IP path on" — exists
    # precisely to name a stray one nobody declared. Requiring a marker here
    # would hide the case the sentence was written for. The marker-checked
    # question is a DIFFERENT question and is reported separately, below, as
    # `declared_absence_router`.
    examined["path_router_on_disk"] = no_tmpl.is_file()

    if report_problem is not None:
        refusals.append(report_problem)
        return _verdict(refusals, examined, na_reason)

    rec = (doc or {}).get("ingest")
    if not isinstance(rec, dict):
        refusals.append(_refusal(
            "REPORT_SCHEMA",
            f"the record at {ST.REPORT_REL} carries no `ingest` object, so "
            f"there is nothing to judge. An unreadable record is a refusal, "
            f"never a quiet pass."))
        return _verdict(refusals, examined, na_reason)

    status = rec.get("status")
    slots = rec.get("slots") or []
    examined["slots_in_record"] = len(slots)
    examined["fixtures_in_record"] = len(rec.get("fixtures") or [])
    lookup = rec.get("lookup") or {}
    why = rec.get("no_template_reason")
    why = why.strip() if isinstance(why, str) else ""

    if on_disk and no_tmpl.is_file():
        refusals.append(_refusal(
            "TREE_SAYS_BOTH",
            f"the step's output says two things at once: "
            f"{len(on_disk)} slot file(s) under {ST.SLOTS_DIR_REL} AND a "
            f"marker at {ST.NO_TEMPLATE_REL}."))

    # ---- nobody looked ---------------------------------------------------- #
    if status == ST.STATUS_NOT_ATTEMPTED:
        detail = ""
        if no_tmpl.is_file():
            detail += (f" And {ST.NO_TEMPLATE_REL} IS on disk, which is the "
                       f"file the flow selects its IP path on — a run nobody "
                       f"investigated is currently choosing a delivery path.")
        if why:
            detail += (f" A reason IS stated ({len(why)} chars) and buys "
                      f"nothing here: it describes a template nobody searched "
                      f"for. State it together with the path that was searched.")
        refusals.append(_refusal(
            "NEVER_LOOKED",
            f"no template path was ever given: `lookup.attempted` is "
            f"{lookup.get('attempted')!r} and `lookup.searched` names "
            f"{len(lookup.get('searched') or [])} path(s). A template that was "
            f"never looked for is not a template that is absent, and "
            f"\"I could not look\" must not reach a reader as \"I looked and "
            f"it was clean\".{detail}",
            searched=lookup.get("searched") or []))
        return _verdict(refusals, examined, na_reason)

    # ---- searched, and it is not there ------------------------------------ #
    if status == ST.STATUS_ABSENT:
        if lookup.get("path_exists"):
            examined["template_path_exists_but_is_not_a_directory"] = True
        # THE DECLARATION DECIDES WHETHER THE ROUTER IS EXPECTED. Tested with
        # the producer's own predicate so a file one wrote can never be one the
        # other would have refused.
        if ST.declares_no_template(status, why):
            # THE DECLARED ABSENCE HAS TWO LEGITIMATE HOMES, NOT ONE.
            #
            # This clause named `NO_TEMPLATE.txt` alone, and that made THE
            # SELF-TAPE-OUT ROUTE IMPASSABLE. Measured by driving step 0.5ic's
            # own two programs, in the order the flow declares them, on a die
            # with no operator:
            #
            #   submission_template_ingest  -> status=ABSENT, writes
            #                                  NO_TEMPLATE.txt
            #   tapeout_declaration_gen     -> RETIRES NO_TEMPLATE.txt on
            #                                  purpose and writes
            #                                  SELF_TAPEOUT.txt
            #   submission_template_check   -> rc 1, NO_TEMPLATE_FILE_MISSING
            #
            # The step's own gate refused the tree the step's own producers had
            # just built, and 0.5ic gates the whole chip path behind it. The
            # step's SECOND gate clause already reads it the other way:
            # `tapeout_declaration_check` PASSES that same tree and names
            # `SELF_TAPEOUT.txt` as its router.
            #
            # NOTHING IS WIDENED BY THIS. The absence must still be DECLARED,
            # it must still live in a file the flow reads, and that file must
            # still carry its producer's marker. The only change is that the
            # checker now accepts the file the design's own declaration
            # selected instead of insisting on the one the other half of its
            # step deliberately retired.
            router = _declared_absence_router(project)
            if router is None:
                refusals.append(_refusal(
                    "NO_TEMPLATE_FILE_MISSING",
                    f"the record DECLARES there is no template and neither "
                    f"{ST.NO_TEMPLATE_REL} nor {TD.SELF_TAPEOUT_REL} is there "
                    f"carrying its producer's marker. A design that targets no "
                    f"shuttle must still SAY so, in a file the flow reads: "
                    f"{ST.NO_TEMPLATE_REL} routes the IP terminal and "
                    f"{TD.SELF_TAPEOUT_REL} routes a die doing its own "
                    f"tape-out.",
                    declared_reason_chars=len(why)))
            else:
                examined["declared_absence_router"] = router
                na_reason = why
        else:
            extra = ("" if not no_tmpl.is_file() else
                     f" And {ST.NO_TEMPLATE_REL} IS on disk, which is the file "
                     f"the flow selects its IP path on — an undeclared absence "
                     f"is currently choosing a delivery path.")
            refusals.append(_refusal(
                "NO_TEMPLATE_WITHOUT_REASON",
                f"the template was searched for at "
                f"{', '.join(lookup.get('searched') or ['(nowhere named)'])} "
                f"and is not there, and the record states no usable reason why "
                f"that is a genuine not-applicable for this design "
                f"({'absent' if not why else f'only {len(why)} char(s)'}; "
                f"{ST.MIN_REASON_CHARS} required). Nothing to check is a FAIL, "
                f"not a pass.{extra}",
                stated_chars=len(why), floor=ST.MIN_REASON_CHARS))
        return _verdict(refusals, examined, na_reason)

    if status != ST.STATUS_INGESTED:
        refusals.append(_refusal(
            "REPORT_SCHEMA",
            f"the record carries status {status!r}, which is not one of "
            f"{ST.STATUS_INGESTED}, {ST.STATUS_ABSENT}, "
            f"{ST.STATUS_NOT_ATTEMPTED}."))
        return _verdict(refusals, examined, na_reason)

    # ---- a template was read ---------------------------------------------- #
    root = lookup.get("template_root")
    if not root or not Path(root).is_dir():
        refusals.append(_refusal(
            "TEMPLATE_NOT_ON_DISK",
            f"the record claims a template ingested from {root!r}, and no "
            f"directory is there now. A report is a claim about the tree; "
            f"this one cannot be checked against it.",
            template_root=root))

    # A record of 0 slots beside a tree of 0 slot files is not a disagreement
    # -- it is the SHIPS_NO_SLOTS case below, and saying both would report one
    # defect as two.
    if len(on_disk) != len(slots):
        refusals.append(_refusal(
            "TREE_DISAGREES_WITH_REPORT",
            f"the record claims {len(slots)} ingested slot(s) and "
            f"{ST.SLOTS_DIR_REL} holds {len(on_disk)} file(s)."))

    if not slots:
        # The ROOT cause, reported alone. Whether a slot was declared is moot
        # against a template that pins none: raising the declared-slot rules
        # here too would bury the one refusal that says what is actually wrong.
        refusals.append(_refusal(
            "TEMPLATE_SHIPS_NO_SLOTS",
            f"the template at {root} was read and pinned no slot at all "
            f"(no file under it carries a {ST.DIE_AREA_KEY} key). A template "
            f"with no slot contract is not the template this step needs, and "
            f"an empty scan must not read as a clean one.",
            scan=rec.get("scan")))
        return _verdict(refusals, examined, na_reason)

    # every slot: on disk, unchanged, and self-consistent
    for s in slots:
        src = s.get("source_file")
        p = Path(src) if src else None
        if p is None or not p.is_file():
            refusals.append(_refusal(
                "TEMPLATE_NOT_ON_DISK",
                f"slot {s.get('slot')!r} was recorded from {src!r} and no file "
                f"is there now.",
                slot=s.get("slot"), source_file=src))
        else:
            recorded = s.get("source_sha256")
            now = ST.sha256_file(p)
            examined["template_files_rehashed"] += 1
            if recorded and now and recorded != now:
                refusals.append(_refusal(
                    "TEMPLATE_CHANGED_SINCE_INGEST",
                    f"slot {s.get('slot')!r}: {src} no longer hashes to what "
                    f"the record says it did "
                    f"({recorded[:12]}… recorded, {now[:12]}… now). The "
                    f"geometry in this report is not the geometry on disk.",
                    slot=s.get("slot"), source_file=src,
                    recorded_sha256=recorded, actual_sha256=now))
        refusals.extend(check_slot_geometry(s))
        refusals.extend(check_slot_pads(s))

    # THE ARTEFACT A LATER STEP OPENS MUST SAY WHAT THE RECORD SAYS. The slot
    # files under the project are the step's declared output and the thing
    # downstream reads; checking the operator's template and not them would
    # leave the die number editable by anyone after the fact. Compared only
    # when the COUNTS already agree, so this rule and TREE_DISAGREES_WITH_REPORT
    # can never both name one defect.
    if slots and len(on_disk) == len(slots):
        emitted, unreadable = [], []
        for f in on_disk:
            try:
                emitted.append(json.loads(f.read_text(errors="replace")))
            except ValueError as exc:
                unreadable.append(f"{f.name} ({exc})")
        want = sorted((str(s.get("slot")), _geometry_key(s)) for s in slots)
        got = sorted((str(s.get("slot")), _geometry_key(s)) for s in emitted)
        if unreadable or want != got:
            detail = (f"unreadable: {', '.join(unreadable)}" if unreadable
                      else f"record pins {want}; the files carry {got}")
            refusals.append(_refusal(
                "SLOT_FILE_DISAGREES_WITH_RECORD",
                f"the slot file(s) under {ST.SLOTS_DIR_REL} do not carry the "
                f"geometry this record claims for them — {detail}",
                unreadable=unreadable))

    # two files pinning one name to different geometry
    by_name: Dict[str, List[dict]] = {}
    for s in slots:
        by_name.setdefault(str(s.get("slot")), []).append(s)
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        keys = {_geometry_key(s) for s in group}
        if len(keys) > 1:
            refusals.append(_refusal(
                "SLOT_NAME_COLLISION",
                f"slot {name!r} is pinned to {len(keys)} different geometries "
                f"by {len(group)} files: "
                f"{', '.join(str(s.get('source_file')) for s in group)}",
                slot=name,
                source_files=[s.get("source_file") for s in group]))

    # the declared slot
    shipped = rec.get("slots_shipped") or sorted({str(s.get("slot")) for s in slots})
    declared = rec.get("declared_slot")
    if declared is None:
        refusals.append(_refusal(
            "SLOT_NOT_DECLARED",
            f"a template was ingested and no slot was declared. The template "
            f"ships {len(shipped)} slot(s) ({', '.join(shipped) or 'none'}) and "
            f"this design chose none of them. A die that was chosen and a die "
            f"that was defaulted are the same number with different "
            f"provenance, and only one of them can be checked.",
            slots_shipped=shipped))
    elif declared not in shipped:
        refusals.append(_refusal(
            "SLOT_NOT_SHIPPED",
            f"the declared slot {declared!r} is not one the template ships. "
            f"Shipped: {', '.join(shipped) or 'none'}.",
            declared_slot=declared, slots_shipped=shipped))

    return _verdict(refusals, examined, na_reason)


def _verdict(refusals: List[Dict[str, Any]], examined: Dict[str, Any],
             na_reason: Optional[str]) -> Dict[str, Any]:
    """Assemble the `check` block.

    There is deliberately NO boolean `passed` field. A NOT_APPLICABLE folded
    into a `true` is the exact sentence this gate exists to refuse, and a
    reader grepping one key must not be able to read it as a clean run.
    """
    if refusals:
        verdict = ST.VERDICT_FAIL
    elif na_reason is not None:
        verdict = ST.VERDICT_NOT_APPLICABLE
    else:
        verdict = ST.VERDICT_PASS
    return {
        "program": PROGRAM,
        "verdict": verdict,
        "not_applicable_reason": na_reason,
        "refusals": refusals,
        "examined": examined,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _producer_record_of(doc):
    """The identity stamp of whoever wrote `doc` before this gate did.

    A record stamped by another program (the step's producer) yields that
    stamp; a document this gate already re-wrote yields the producer_record it
    carried forward. Nothing is invented: no stamp, no record."""
    if not isinstance(doc, dict):
        return None
    prior = doc.get("producer_record")
    if isinstance(prior, dict) and prior.get("program"):
        return dict(prior)
    prog = doc.get("program")
    if isinstance(prog, str) and prog.strip() and prog.strip() != PROGRAM:
        rec = {"program": prog.strip()}
        emitted = doc.get("emitted_by")
        if isinstance(emitted, str) and emitted.strip():
            rec["emitted_by"] = emitted.strip()
        return rec
    return None


def _load_report(project: Path):
    """(document, refusal) for the step's record. Exactly one is not None."""
    path = project / ST.REPORT_REL
    if not path.is_file():
        return None, _refusal(
            "REPORT_ABSENT",
            f"there is no record at {path}. The step declares this report on "
            f"EVERY path, including the one where no template was looked for, "
            f"so its absence means the step did not run — which is a refusal, "
            f"never a quiet pass.")
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (ValueError, OSError) as exc:
        return None, _refusal(
            "REPORT_UNREADABLE",
            f"the record at {path} could not be read as JSON: {exc}")
    if not isinstance(doc, dict) or doc.get("schema") != ST.SCHEMA:
        return doc if isinstance(doc, dict) else None, _refusal(
            "REPORT_SCHEMA",
            f"the record at {path} does not declare schema {ST.SCHEMA!r} "
            f"(found {(doc.get('schema') if isinstance(doc, dict) else type(doc).__name__)!r}).")
    return doc, None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Gate the shuttle-template ingest (step 0.5ic).")
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", nargs="?", const="-", default=None,
                   help="Emit JSON. With no value → stdout. With a path → write "
                        "file. Pointing it at the step's own report MERGES the "
                        "verdict in beside the ingest record; the record is "
                        "never overwritten away.")
    args = p.parse_args(argv)

    project = Path(args.project_dir)
    doc, problem = _load_report(project)
    check = evaluate(project, doc, problem)

    out_doc = {"schema": ST.SCHEMA,
               "ingest": (doc or {}).get("ingest"),
               "check": check}
    # v1.15.45 (sha256 capture) — the PRODUCER's identity travels with the
    # merged document. `submission_template_ingest` stamps its record
    # `program: submission_template_ingest`; merging the verdict in beside the
    # ingest used to drop that stamp, so after one audit the file carried only
    # this gate's identity and `flow_compliance_check` read the run's own
    # record as auditor-authored (audit_created) on every later pass. The stamp
    # is carried verbatim, never re-minted: when the record already holds a
    # producer_record (a prior audit merged it), that one is kept.
    _prod = _producer_record_of(doc)
    if _prod:
        out_doc["producer_record"] = _prod

    if args.json is not None:
        payload = json.dumps(out_doc, indent=2, ensure_ascii=False) + "\n"
        if args.json == "-":
            print(payload, end="")
        else:
            target = Path(args.json)
            if not target.is_absolute():
                target = project / target
            # LOOK AT THE TARGET BEFORE OVERWRITING IT. When the record itself
            # is on disk but unparsable, writing over it destroys the only
            # evidence of what the step produced. The refusal is already
            # reported; the file is left exactly where it is.
            if (problem is not None and problem["rule"] == "REPORT_UNREADABLE"
                    and target.resolve() == (project / ST.REPORT_REL).resolve()):
                print(f"[WARN] {PROGRAM}: left the unreadable record at "
                      f"{target} in place rather than overwriting it.",
                      file=sys.stderr)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(target, payload)

    for r in check["refusals"]:
        print(f"[REFUSED] {r['rule']}: {r['message']}")
    verdict = check["verdict"]
    if verdict == ST.VERDICT_NOT_APPLICABLE:
        print(f"\n{PROGRAM}: NOT_APPLICABLE — {check['not_applicable_reason']}")
        print("  NOT_APPLICABLE IS NOT A PASS: no slot contract was pinned, and "
              "this run checked no die geometry.")
    else:
        print(f"\n{PROGRAM}: {verdict} — {check['examined']}")

    return 0 if verdict in (ST.VERDICT_PASS, ST.VERDICT_NOT_APPLICABLE) else 1


if __name__ == "__main__":
    sys.exit(main())
