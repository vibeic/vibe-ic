#!/usr/bin/env python3
"""tapeout_declaration_gen.py — write the physical and implementation contract.

STEP 0.5ic's OTHER HALF
=======================
`submission_template_ingest` records what the OPERATOR published. This records
what the DESIGN declares about itself. Both belong to step 0.5ic — the step
that decides the route — because a design doing its own tape-out has no
operator to publish anything and still has to write these numbers down.

The step has no `condition`, and that is the point: EVERY design passes through
it, including the ones with no shuttle. A self-tape-out that skipped it would
be a die whose size, pad ring and seal ring nobody ever stated, and every check
that compares against a declaration would report NOT_DETERMINED forever with no
way to fix it.

THE THIRD ROUTER FILE
=====================
MEASURED on `flow/phase1_phase2_phase3.yaml` at v1.10.98: step 0.5ic wrote two
router files for what are three routes.

    input/submission_template/slots/*.yaml     -> 37.5ic  operator's container
    input/submission_template/NO_TEMPLATE.txt  -> 37.5ip  IP/hardmacro terminal
    (nothing)                                  -> a CHIP doing its own tape-out

The third design has no operator template, so 37.5ic's `files_exist` condition
excludes it; and it is a die rather than an IP, so 37.5ip is the wrong terminal
for it. It reached tape-out having passed no submission check of any kind.

This program writes the missing third file, `SELF_TAPEOUT.txt`. Routing the
self-tape-out chip onto `NO_TEMPLATE.txt` instead would have collided with the
IP path — the two designs want different terminals and `files_exist` cannot
express "and not" — so the discriminator is its own file. Three router files,
mutually exclusive by construction.

2026-08-20 — THE FILE SURVIVES; THE STEP IT USED TO SELECT DOES NOT. The three
router files were, for a while, three ROUTES, the third being step `37.5self`.
The owner retired that step: the general precheck was never an alternative to
the operator's container, it is a second ARM of `37.5ic` that runs on every
design reaching that step. So `SELF_TAPEOUT.txt` is now one of the TWO files
that mark the CHIP path — 37.5ic's condition is `slots/*.yaml` OR
`SELF_TAPEOUT.txt`, `any_of` — and `NO_TEMPLATE.txt` still marks the IP path
alone. This program is unchanged in what it writes and why; only what the file
selects downstream moved, and it moved towards MORE checking: a self tape-out
now gets the same ladder a shuttle design gets.

Step 37.5ic is untouched, and its verdict stays the shuttle operator's own.
That property is the whole point of that step and nothing here weakens it:
`_tapeout_declaration.route_of` gives the OPERATOR's answer priority over the
design's, so a project carrying slot files goes to the operator's container
whatever it declared about itself.

RETIRING THE OTHER MARKER
=========================
When this program selects SELF_TAPEOUT it retires a `NO_TEMPLATE.txt` that
carries `submission_template_ingest`'s OWN marker line, because a die that is
also flagged as an IP would select both terminals at once. A file WITHOUT that
marker is somebody else's and is left exactly where it is — the checker refuses
the contradiction rather than this program resolving it by deleting evidence.
That is the same rule `submission_template_ingest.write_artefacts` already
applies to its own stale markers, applied symmetrically.

NEVER A DEFAULT
===============
The declaration this program writes starts as `_tapeout_declaration.
blank_declaration()` — all 18 physical questions and both contract fields
`NOT_DETERMINED` — and the ONLY thing that can change a field is a value in the
caller's `--answers` file. There is no inference here: not from the floorplan,
not from the PDK, not from the netlist. A number derived from an artefact and
written into a DECLARATION stops being a measurement and becomes a claim, and
the next check compares the artefact against a number taken from that same
artefact, which is not a check.

Running it with no `--answers` is therefore both legal and useful: it produces
a well-formed, entirely unanswered declaration. The owning declaration gate
then reports the synthesis-area dependency INCOMPLETE unless Phase 1 extracts
a design-owned ceiling into L19; every physical consumer reports
NOT_DETERMINED naming the exact question it went without.

chip-AGNOSTIC: no vendor, foundry, process node, SKU or design literal.

USAGE
-----
    python3 tapeout_declaration_gen.py <project> [--answers ANSWERS.json]
        [--json REPORT.json] [--print-json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _submission_template as ST                              # noqa: E402
import _tapeout_declaration as TD                              # noqa: E402
import plugin_manifest_discovery as _pmd                       # noqa: E402
from _atomic_artefact import write_text as atomic_write_text   # noqa: E402

PROGRAM = "tapeout_declaration_gen"


def _self_tapeout_text(doc: Dict[str, Any]) -> str:
    audit = TD.audit(doc)
    return "\n".join([
        TD.SELF_TAPEOUT_MARKER,
        "",
        "This design declares that it is a DIE and that it targets NO shuttle",
        "operator. It is on the CHIP path, so it runs step 37.5ic and gets that",
        "step's general tape-out precheck; the operator's own container is the",
        "arm it does not get, because there is no operator. It is not an IP",
        "hardmacro (37.5ip).",
        "",
        f"declaration: {TD.DECLARATION_REL}",
        f"answered:    {audit['answered']} of {audit['questions_total']} "
        f"question(s); {audit['unanswered']} still NOT_DETERMINED",
        "",
        "Every unanswered question is reported by the general precheck as",
        "NOT_DETERMINED, which is a non-pass. Nothing is defaulted.",
        "",
    ])


def _retire_own_marker(path: Path, marker: str) -> Optional[str]:
    """Delete `path` iff its first line is `marker`. Returns it if deleted."""
    if not path.exists():
        return None
    try:
        head = path.read_text(errors="replace").splitlines()[:1]
    except OSError:
        return None
    if head and head[0].strip() == marker:
        try:
            path.unlink()
        except OSError:
            return None
        return str(path)
    return None


def build(project: Path, answers_path: Optional[Path]) -> Dict[str, Any]:
    """The declaration, the route, and everything that went into both."""
    doc = TD.blank_declaration()
    source: Dict[str, Any] = {"answers_file": None, "ignored_keys": [],
                              "error": None}
    if answers_path is not None:
        source["answers_file"] = str(answers_path)
        if not answers_path.is_file():
            source["error"] = f"no such answers file: {answers_path}"
        else:
            raw, err = TD.load(answers_path)
            if err is not None:
                source["error"] = err
            elif not isinstance(raw, dict):
                source["error"] = ("the answers file's top level is "
                                   f"{type(raw).__name__}, not a mapping")
            else:
                # Accept either the flat `{key: value}` shape a human writes or
                # a full declaration document. Both, because a caller who
                # copies a previous declaration and edits it should not have to
                # unwrap it first.
                flat = raw.get("answers") if isinstance(
                    raw.get("answers"), dict) else raw
                merged = dict(flat)
                for key in TD.EXTRA_KEYS:
                    if key in raw:
                        merged[key] = raw[key]
                doc, ignored = TD.merge_answers(doc, merged)
                source["ignored_keys"] = ignored
                # #2070 — a transcribed TECHNOLOGY fact answers its question.
                # `merge_answers` carried the provenance record through as an
                # extra key; this is what makes the VALUE land in `answers`
                # where every consumer reads it, from the one record, so a
                # declaration can never carry the provenance of a number it
                # does not publish. Idempotent when the producer already wrote
                # the value (it does), and the single source of the rule when
                # some other producer does not.
                doc = TD.merge_technology(doc, doc.get(TD.TECHNOLOGY_KEY)
                                          if isinstance(
                                              doc.get(TD.TECHNOLOGY_KEY), dict)
                                          else {})

    slots = sorted((project / ST.SLOTS_DIR_REL).glob("*.yaml")) + \
        sorted((project / ST.SLOTS_DIR_REL).glob("*.yml"))
    has_slots = bool(slots)
    route = TD.route_of(doc, has_slots)
    return {
        "schema": TD.SCHEMA,
        "program": PROGRAM,
        "project": str(project),
        "declaration": doc,
        "declaration_refusals": TD.validate(doc),
        "audit": TD.audit(doc),
        "answers_source": source,
        "operator_slot_files": [str(p) for p in slots],
        "route": route,
        "route_reason": _route_reason(route, has_slots, doc),
    }


def _route_reason(route: str, has_slots: bool, doc: Dict[str, Any]) -> str:
    if route == TD.ROUTE_SHUTTLE:
        return ("an operator template was ingested, so the chip path (step "
                "37.5ic) runs BOTH arms: the general precheck and the "
                "operator's own container. The operator's answer wins over "
                "anything this design declares about itself, and where the two "
                "arms disagree the step refuses rather than preferring one")
    if route == TD.ROUTE_SELF_TAPEOUT:
        return ("no operator template, and the design declares deliverable="
                f"{TD.DELIVERABLE_DIE}: it is a die doing its own tape-out, so "
                "it takes the chip path (step 37.5ic) and is judged by the "
                "general precheck alone — the operator's arm has no operator")
    if route == TD.ROUTE_IP:
        return ("no operator template, and the design declares deliverable="
                f"{TD.DELIVERABLE_HARDMACRO}: it is delivered, not fabricated, "
                "so it terminates at the hardmacro kit (step 37.5ip) and needs "
                "no pad ring, seal ring or submission check")
    return ("`deliverable` is NOT_DETERMINED, so no route was selected and no "
            "router file was written. A design that has not said what it is "
            "has not chosen a route and must not be given one")


def write_artefacts(project: Path, rec: Dict[str, Any]) -> Dict[str, Any]:
    written: Dict[str, Any] = {"declaration": None, "self_tapeout": None,
                               "retired_stale": []}
    decl_path = project / TD.DECLARATION_REL
    decl_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        decl_path,
        json.dumps(rec["declaration"], indent=2, ensure_ascii=False) + "\n")
    written["declaration"] = str(decl_path)

    self_path = project / TD.SELF_TAPEOUT_REL
    if rec["route"] == TD.ROUTE_SELF_TAPEOUT:
        atomic_write_text(self_path, _self_tapeout_text(rec["declaration"]))
        written["self_tapeout"] = str(self_path)
        # A die must not also select the IP terminal. Only OUR OWN sibling's
        # marker is retired; anything else is left as evidence.
        gone = _retire_own_marker(project / ST.NO_TEMPLATE_REL,
                                  ST.NO_TEMPLATE_MARKER)
        if gone:
            written["retired_stale"].append(gone)
    else:
        gone = _retire_own_marker(self_path, TD.SELF_TAPEOUT_MARKER)
        if gone:
            written["retired_stale"].append(gone)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Write the tape-out declaration (step 0.5ic) and select "
                    "the delivery route. Every unanswered question is "
                    "NOT_DETERMINED; nothing is ever defaulted or inferred.")
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--answers", type=Path, default=None,
                   help="JSON file of answers. Omitting it produces a "
                        "complete, well-formed, entirely unanswered "
                        "declaration — which is a legal and useful result.")
    p.add_argument("--json", type=Path, dest="out_json", default=None,
                   help=f"Report path (default: <project>/{TD.REPORT_REL}).")
    p.add_argument("--print-json", action="store_true")
    args = p.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: project directory not found: {project}", file=sys.stderr)
        return 2

    rec = build(project, args.answers)
    try:
        rec["written"] = write_artefacts(project, rec)
    except OSError as exc:
        print(f"[ERROR] {PROGRAM}: could not write the declaration: {exc}",
              file=sys.stderr)
        return 2
    rec["emitted_by"] = _pmd.emitted_by(PROGRAM)

    out = args.out_json or (project / TD.REPORT_REL)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(rec, indent=2,
                                          ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[ERROR] {PROGRAM}: could not write the report: {exc}",
              file=sys.stderr)
        return 2

    if args.print_json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))

    a = rec["audit"]
    print(f"{PROGRAM}: route={rec['route']} "
          f"answered={a['answered']}/{a['questions_total']} "
          f"unanswered={a['unanswered']} not_applicable={a['not_applicable']}")
    for sec, s in a["sections"].items():
        print(f"  {sec}: {s['answered']}/{s['questions']} answered"
              + (f", unanswered: {', '.join(s['unanswered_keys'])}"
                 if s["unanswered_keys"] else ""))
    print(f"  {rec['route_reason']}")
    if rec["answers_source"]["error"]:
        print(f"  answers not read: {rec['answers_source']['error']}",
              file=sys.stderr)
    if rec["answers_source"]["ignored_keys"]:
        print("  IGNORED (not a recognized declaration field): "
              + ", ".join(rec["answers_source"]["ignored_keys"]),
              file=sys.stderr)
    # A malformed declaration is the one thing this program can produce that
    # nobody can read. An UNANSWERED one is the intended output and is rc 0.
    if rec["declaration_refusals"]:
        for r in rec["declaration_refusals"]:
            print(f"  REFUSED {r['rule']}: {r['message']}", file=sys.stderr)
        return 1
    if rec["answers_source"]["error"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
