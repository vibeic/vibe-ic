#!/usr/bin/env python3
"""tapeout_declaration_check.py — judge the declaration step 0.5ic wrote.

ENFORCEMENT: advisory here — this gate runs as a second `program_exit_zero`
clause at step 0.5ic, beside `submission_template_check` and under the same
`all_of`, so when `flow_compliance_check` evaluates that step its rc IS half of
the step's verdict. "advisory" names the RUNNER channel it is absent from: no
one-shot runner invokes it inline, and `submission_template_check` — the clause
it stands next to — carries these same words for that same reason. Declaring
`blocking` here was MEASURED to be worse rather than braver: the audit reads the
word against the wiring and reports `contradiction::tapeout_declaration_check`,
since a gate no runner invokes cannot block in the venue the word names.
Declared at all because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
enforcement decision nobody made. Kept in the first 4 kB: `declared_intent`
reads only `text[:4000]`.

WHAT THIS REFUSES, AND WHAT IT DELIBERATELY DOES NOT
====================================================
It refuses a declaration nobody can READ. It does NOT refuse one that is merely
incomplete, and the distinction is the entire design of the declaration.

    MALFORMED   -> FAIL here.   A question absent altogether; a rectangle that
                                is not four numbers; an enum outside its
                                choices; a database unit that is zero or
                                negative; the schema unrecognised. None of
                                these can be read by any consumer, and each is
                                a way a DEFAULT could get back in wearing a
                                real answer's clothes.
    UNANSWERED  -> PASS here.   `NOT_DETERMINED` in a field is the declaration
                                working exactly as intended. It is reported by
                                the CONSUMING check — as NOT_DETERMINED, which
                                is a non-pass — in the place where the reader
                                can see WHICH check went without WHICH answer.

Refusing incompleteness here instead would move every one of those findings
into a single early gate that says "the declaration is not finished" and names
none of them, and it would make step 0.5ic — the step that decides the route —
unpassable for every design that has not yet answered all 18. A router that
cannot route is worse than an honest NOT_DETERMINED downstream.

WHY THE ROUTE IS CHECKED FOR CONTRADICTION
==========================================
The three router files select three mutually exclusive terminals by
`files_exist` alone. Two of them present at once selects two terminals, and
`files_exist` cannot express "and not". So this checks that AT MOST ONE is
present and refuses the contradiction — it never resolves it by deleting one,
because deleting a router file is deleting the evidence of how the tree got
into that state.

DENOMINATOR
===========
The verdict line always states answered / 18, the per-section split, and which
router file (if any) is present.

EXIT CODES
----------
    0  PASS            the declaration is well-formed and at most one router
                       file is present. It may be entirely unanswered.
    1  FAIL            malformed, unreadable, or a router contradiction.
    2  usage

chip-AGNOSTIC.
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

PROGRAM = "tapeout_declaration_check"

RULE_DECLARATION_ABSENT = "DECLARATION_ABSENT"
RULE_ROUTER_CONTRADICTION = "ROUTER_CONTRADICTION"
RULE_ROUTE_WITHOUT_DECLARATION = "ROUTE_WITHOUT_DECLARATION"


def _routers_present(project: Path) -> Dict[str, bool]:
    """Which of the three router files exist. All three, always reported."""
    slots = sorted((project / ST.SLOTS_DIR_REL).glob("*.yaml")) + \
        sorted((project / ST.SLOTS_DIR_REL).glob("*.yml"))
    return {
        ST.SLOTS_DIR_REL + "/*.yaml": bool(slots),
        ST.NO_TEMPLATE_REL: (project / ST.NO_TEMPLATE_REL).is_file(),
        TD.SELF_TAPEOUT_REL: (project / TD.SELF_TAPEOUT_REL).is_file(),
    }


def evaluate(project: Path,
             declaration_path: Optional[Path] = None) -> Dict[str, Any]:
    decl_path = declaration_path or (project / TD.DECLARATION_REL)
    refusals: List[Dict[str, Any]] = []
    doc: Optional[Dict[str, Any]] = None

    if not decl_path.is_file():
        refusals.append({
            "rule": RULE_DECLARATION_ABSENT,
            "message": (
                f"no declaration at {decl_path}. Step 0.5ic has no `condition`, "
                "so EVERY design passes through it — including one with no "
                "shuttle, which is exactly the design that has nobody else to "
                "write these numbers down for it. Run "
                "`tapeout_declaration_gen <project>`; with no answers at all it "
                "still produces a complete, well-formed, entirely "
                "NOT_DETERMINED declaration."),
            "path": str(decl_path)})
    else:
        loaded, err = TD.load(decl_path)
        if err is not None:
            refusals.append({"rule": "DECLARATION_UNREADABLE",
                             "message": err, "path": str(decl_path)})
        else:
            doc = loaded
            refusals.extend(TD.validate(doc))

    routers = _routers_present(project)
    present = [name for name, ok in routers.items() if ok]
    if len(present) > 1:
        refusals.append({
            "rule": RULE_ROUTER_CONTRADICTION,
            "message": (
                "the tree carries " + str(len(present)) + " router files at "
                "once (" + ", ".join(present) + "). Each selects a different "
                "terminal by `files_exist`, which cannot express \"and not\", "
                "so this design currently selects more than one delivery path. "
                "Refused rather than resolved: deleting one of them would "
                "delete the evidence of how the tree got here."),
            "routers": present})

    if present and doc is None:
        refusals.append({
            "rule": RULE_ROUTE_WITHOUT_DECLARATION,
            "message": (
                "a router file (" + ", ".join(present) + ") selects a delivery "
                "terminal, and there is no readable declaration beside it. The "
                "route was chosen and the reasons for it were not written "
                "down."),
            "routers": present})

    audit = TD.audit(doc) if isinstance(doc, dict) else TD.audit(
        TD.blank_declaration())
    verdict = "FAIL" if refusals else "PASS"
    return {
        "schema": TD.SCHEMA,
        "program": PROGRAM,
        "project": str(project),
        "declaration": str(decl_path),
        "declaration_present": decl_path.is_file(),
        "verdict": verdict,
        "refusals": refusals,
        "routers_present": routers,
        "router_selected": present[0] if len(present) == 1 else None,
        "audit": audit,
        "emitted_by": _pmd.emitted_by(PROGRAM),
    }


def summary_line(res: Dict[str, Any]) -> str:
    a = res["audit"]
    secs = " ".join(f"{k}={v['answered']}/{v['questions']}"
                    for k, v in a["sections"].items())
    return (f"{res['verdict']}: {PROGRAM} — "
            f"answered={a['answered']}/{a['questions_total']} ({secs}), "
            f"not_applicable={a['not_applicable']}, "
            f"router={res['router_selected'] or '(none)'}, "
            f"refusals={len(res['refusals'])}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Judge the tape-out declaration written by step 0.5ic. "
                    "Refuses a MALFORMED declaration and a contradictory "
                    "router; an entirely UNANSWERED declaration passes, and "
                    "every unanswered question is reported as NOT_DETERMINED "
                    "by the check that needed it.")
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--declaration", type=Path, default=None,
                   help=f"default: <project>/{TD.DECLARATION_REL}")
    p.add_argument("--json", type=Path, dest="out_json", default=None,
                   help=f"default: <project>/{TD.REPORT_REL}")
    args = p.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: project directory not found: {project}", file=sys.stderr)
        return 2

    res = evaluate(project, args.declaration)
    out = args.out_json or (project / TD.REPORT_REL)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(res, indent=2,
                                          ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[ERROR] {PROGRAM}: could not write the report: {exc}",
              file=sys.stderr)
        return 2

    for r in res["refusals"]:
        print(f"  REFUSED {r['rule']}: {r['message']}", file=sys.stderr)
    print(summary_line(res))
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
