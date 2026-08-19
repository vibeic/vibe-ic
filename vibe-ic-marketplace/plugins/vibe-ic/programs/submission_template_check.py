#!/usr/bin/env python3
"""Gate the shuttle-template ingest — step 0.5ic's verdict.

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
    NO_TEMPLATE_FILE_MISSING      the record says no template and the step's
                                  declared prose output is not there.
    REPORT_ABSENT / REPORT_UNREADABLE / REPORT_SCHEMA
                                  there is no record to judge, which is a
                                  refusal and never a quiet pass.

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
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402  vibe-ic#1082


PROGRAM = "submission_template_check"


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
        "no_template_marker_on_disk": False,
    }
    na_reason: Optional[str] = None

    slots_dir = project / ST.SLOTS_DIR_REL
    on_disk = sorted(slots_dir.glob("*.yaml")) if slots_dir.is_dir() else []
    no_tmpl = project / ST.NO_TEMPLATE_REL
    examined["slot_files_on_disk"] = len(on_disk)
    examined["no_template_marker_on_disk"] = no_tmpl.is_file()

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
        if not no_tmpl.is_file():
            refusals.append(_refusal(
                "NO_TEMPLATE_FILE_MISSING",
                f"the record says no template and {ST.NO_TEMPLATE_REL} is not "
                f"there, so the step produced nothing and said nothing."))
        detail = ""
        if why:
            detail = (f" A reason IS stated ({len(why)} chars) and buys "
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
        if not no_tmpl.is_file():
            refusals.append(_refusal(
                "NO_TEMPLATE_FILE_MISSING",
                f"the record says the template is absent and "
                f"{ST.NO_TEMPLATE_REL} is not there. A design that targets no "
                f"shuttle must still SAY so."))
        if lookup.get("path_exists"):
            examined["template_path_exists_but_is_not_a_directory"] = True
        if len(why) < ST.MIN_REASON_CHARS:
            refusals.append(_refusal(
                "NO_TEMPLATE_WITHOUT_REASON",
                f"the template was searched for at "
                f"{', '.join(lookup.get('searched') or ['(nowhere named)'])} "
                f"and is not there, and the record states no usable reason why "
                f"that is a genuine not-applicable for this design "
                f"({'absent' if not why else f'only {len(why)} char(s)'}; "
                f"{ST.MIN_REASON_CHARS} required). Nothing to check is a FAIL, "
                f"not a pass.",
                stated_chars=len(why), floor=ST.MIN_REASON_CHARS))
        else:
            na_reason = why
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
