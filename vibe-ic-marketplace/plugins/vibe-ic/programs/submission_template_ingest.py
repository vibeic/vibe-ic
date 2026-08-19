#!/usr/bin/env python3
"""Ingest the shuttle operator's published project template — step 0.5ic.

Reads a template that is ALREADY ON DISK and records, per purchasable slot, the
slot name, the die rectangle, the core rectangle, the sizing mode and the pad
list, verbatim and with the file each came from. Records the layout fixtures the
template ships by path, digest and cell name. Writes the step's report on EVERY
path, including the one where no template was ever looked for.

WHY THIS IS A STEP AND NOT A CALCULATION
========================================
A shuttle operator's template pins the die rectangle for each slot absolutely,
to exactly the values the operator's own size check computes, and it ships the
die-identification cells the operator's submission gate requires as pre-built
layout -- the operator's generator PLACES those cells, it does not create them.
So the geometry was never ours to compute. It is data the flow never went and
got, and only a step can be said to have not run.

THIS PROGRAM NEVER FETCHES
==========================
It takes a PATH. It does not clone, download or reach a network, because a step
that silently downloads its own input produces a result nobody can reproduce.
If the path is not there, that is a fact this program records -- not one it
repairs.

WHAT IT WRITES (`flow/phase1_phase2_phase3.yaml`, step 0.5ic)
=============================================================
    input/submission_template/slots/<slot>.yaml   one per slot the template ships
      OR
    input/submission_template/NO_TEMPLATE.txt     what happened instead, in prose
    reports/phase1/submission_template.json       the machine record, always

The `OR` is the honest half. A design that targets no shuttle must still SAY so;
a step that silently produces nothing is indistinguishable from one that never
ran. So one of the two always exists, and the report always exists beside it.

THE DECLARED SLOT IS NEVER GUESSED
==================================
`--slot` is the design's declaration and the only way this program learns one.
It is not inferred from the template, and it is NOT defaulted to the only slot
when a template ships exactly one -- a die that was chosen and a die that was
defaulted are the same number with different provenance, and only one of them
can be checked.

NOTHING IS VENDORED
===================
The operator's slot files and fixtures stay where they are. What is written here
is a record OF them: paths, digests, and the values read out of them.

Usage:
    submission_template_ingest <project_dir> --template <path> --slot <name>
    submission_template_ingest <project_dir> --template <path>   # no slot chosen
    submission_template_ingest <project_dir>                     # nobody looked

Exit codes:
    0 = the record was written (whatever it says)
    2 = the record could NOT be written

The VERDICT on that record belongs to `submission_template_check`, which is what
step 0.5ic's gate runs. This program reports; it does not judge.

Generality: works for ANY shuttle operator's template. No vendor, SKU or
process-node literal appears here -- slot names, geometry, pads and fixture cell
names are read out of whatever template the caller points at.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling imports below resolve however this is invoked

import _submission_template as ST  # noqa: E402
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402  vibe-ic#1082


PROGRAM = "submission_template_ingest"


# --------------------------------------------------------------------------- #
# the record
# --------------------------------------------------------------------------- #
def build_record(project: Path, template: Optional[str], slot: Optional[str],
                 no_template_reason: Optional[str]) -> Dict[str, Any]:
    """The ingest record for one run, on all three paths.

    `template is None` is NOT_ATTEMPTED and is a different fact from a path
    that was given and is not there. Keeping them apart is the reason this step
    exists, so they are separate statuses carrying separate evidence: a search
    that never happened has an EMPTY `searched` list, and one that happened and
    found nothing names the path it looked at.
    """
    lookup: Dict[str, Any] = {
        "attempted": template is not None,
        "searched": [],
        "template_root": None,
        "template_present": False,
    }
    rec: Dict[str, Any] = {
        "status": ST.STATUS_NOT_ATTEMPTED,
        "lookup": lookup,
        "no_template_reason": (no_template_reason.strip()
                               if isinstance(no_template_reason, str)
                               and no_template_reason.strip() else None),
        "declared_slot": slot.strip() if isinstance(slot, str) and slot.strip() else None,
        "declared_slot_source": None,
        "slots": [],
        "slots_shipped": [],
        "fixtures": [],
        "scan": None,
        "provenance": {
            "fetched_by_this_program": False,
            "network": "never — the template is a path, not a download",
            "vendored_into_this_repo": False,
        },
    }
    if rec["declared_slot"] is not None:
        rec["declared_slot_source"] = "--slot"

    if template is None:
        return rec

    root = Path(template).expanduser()
    try:
        root = root.resolve()
    except OSError:
        root = root.absolute()
    lookup["searched"] = [str(root)]
    lookup["template_root"] = str(root)

    if not root.is_dir():
        rec["status"] = ST.STATUS_ABSENT
        return rec

    lookup["template_present"] = True
    rec["status"] = ST.STATUS_INGESTED
    slots, scan = ST.discover_slots(root)
    rec["slots"] = slots
    rec["slots_shipped"] = sorted({s["slot"] for s in slots})
    rec["scan"] = scan
    rec["fixtures"] = ST.discover_fixtures(root)
    return rec


# --------------------------------------------------------------------------- #
# the artefacts
# --------------------------------------------------------------------------- #
def _slot_yaml(rec_slot: Dict[str, Any]) -> str:
    """One slot's record, as the YAML this step declares under `slots/`.

    Emitted through the JSON writer on purpose: JSON is a YAML subset, so the
    file parses as YAML while the values stay byte-exact instead of passing
    through a serializer that may re-render a number.
    """
    return json.dumps(rec_slot, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _safe_slot_filename(slot: str, used: set) -> str:
    """A filesystem-safe stem for a slot name, unique within one run.

    A slot name is the OPERATOR's string and may carry separators. It is
    sanitised for the filename only -- the record inside always carries the
    name verbatim.
    """
    stem = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in slot).strip("._") or "slot"
    cand, n = stem, 1
    while cand in used:
        n += 1
        cand = f"{stem}__{n}"
    used.add(cand)
    return cand


def _no_template_text(rec: Dict[str, Any]) -> str:
    """The prose half of the record: what happened, in the two absent cases."""
    lines = [ST.NO_TEMPLATE_MARKER, ""]
    if rec["status"] == ST.STATUS_ABSENT:
        lines += [
            "STATUS: ABSENT — a template path was given and nothing is there.",
            "",
            "Searched:",
        ]
        lines += [f"  {p}" for p in rec["lookup"]["searched"]]
    else:
        lines += [
            "STATUS: NOT_ATTEMPTED — no template path was given. NOBODY LOOKED.",
            "",
            "This is NOT the same fact as a template that is absent, and it",
            "cannot be bought with a stated reason: a reason offered for a",
            "template nobody searched for describes nothing. Re-run this step",
            "with --template <path> pointing at the operator's published",
            "template, or state a reason together with the path that was",
            "searched.",
        ]
    lines += ["", "Stated reason:"]
    why = rec.get("no_template_reason")
    if why:
        lines += [f"  {why}"]
    else:
        lines += [f"  (none stated — at least {ST.MIN_REASON_CHARS} characters "
                  f"are required for this to read as a declared not-applicable)"]
    lines += [
        "",
        "NOT_APPLICABLE IS NOT A PASS. This file records that the step could",
        "not pin a die from an operator's slot contract. `submission_template_check`",
        "decides what that is worth; it never reads as a clean run.",
        "",
    ]
    return "\n".join(lines)


def write_artefacts(project: Path, rec: Dict[str, Any]) -> Dict[str, Any]:
    """Write the step's declared outputs and report what was written."""
    written: Dict[str, Any] = {"slot_files": [], "no_template": None,
                               "retired_stale": []}
    slots_dir = project / ST.SLOTS_DIR_REL
    no_tmpl = project / ST.NO_TEMPLATE_REL

    if rec["status"] == ST.STATUS_INGESTED:
        slots_dir.mkdir(parents=True, exist_ok=True)
        used: set = set()
        for s in rec["slots"]:
            stem = _safe_slot_filename(s["slot"], used)
            path = slots_dir / f"{stem}.yaml"
            atomic_write_text(path, _slot_yaml(s))
            written["slot_files"].append(str(path))
            s["ingested_to"] = str(path)
        # Retire a NO_TEMPLATE marker THIS STEP wrote, so the tree does not say
        # two things at once. A file without the marker is somebody else's and
        # is left exactly where it is -- the checker refuses the contradiction
        # rather than this program resolving it by deleting evidence.
        if no_tmpl.exists():
            try:
                head = no_tmpl.read_text(errors="replace").splitlines()[:1]
            except OSError:
                head = []
            if head and head[0].strip() == ST.NO_TEMPLATE_MARKER:
                no_tmpl.unlink()
                written["retired_stale"].append(str(no_tmpl))
    else:
        no_tmpl.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(no_tmpl, _no_template_text(rec))
        written["no_template"] = str(no_tmpl)
    return written


def report_document(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {"schema": ST.SCHEMA, "program": PROGRAM, "ingest": rec}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Ingest a shuttle operator's published project template "
                    "(step 0.5ic). Reads a path; never fetches.")
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--template", default=None,
                   help="path to the operator's template, ALREADY ON DISK. "
                        "Omitting it is recorded as NOT_ATTEMPTED — nobody looked.")
    p.add_argument("--slot", default=None,
                   help="the slot this design DECLARES it targets. Never guessed "
                        "and never defaulted.")
    p.add_argument("--no-template-reason", default=None,
                   help="why an absent template is a genuine not-applicable for "
                        f"this design (at least {ST.MIN_REASON_CHARS} characters).")
    p.add_argument("--print-json", action="store_true",
                   help="also print the report to stdout")
    args = p.parse_args(argv)

    project = Path(args.project_dir)
    rec = build_record(project, args.template, args.slot, args.no_template_reason)

    try:
        rec["written"] = write_artefacts(project, rec)
        doc = report_document(rec)
        report = project / ST.REPORT_REL
        report.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(report, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[ERROR] {PROGRAM}: could not write the step record: {exc}",
              file=sys.stderr)
        return 2

    if args.print_json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))

    print(f"{PROGRAM}: status={rec['status']} "
          f"slots_shipped={len(rec['slots_shipped'])} "
          f"declared_slot={rec['declared_slot'] or '(none declared)'} "
          f"fixtures={len(rec['fixtures'])}")
    print(f"  report: {project / ST.REPORT_REL}")
    if rec["status"] == ST.STATUS_NOT_ATTEMPTED:
        print("  NOBODY LOOKED — no template path was given. This is not the "
              "same fact as a template that is absent.")
    elif rec["status"] == ST.STATUS_ABSENT:
        print(f"  ABSENT — searched {rec['lookup']['searched'][0]} and found "
              f"no template there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
