#!/usr/bin/env python3
"""step_required_inputs_check.py — refuse to run a step that has nothing to read.

WHY THIS EXISTS
===============
The flow declared HALF a contract. 61 steps declare `required_outputs` (133
paths); ZERO declared `required_inputs`, so nothing could ask whether a step
HAD WHAT IT NEEDED. The only thing resembling a dependency was `blocks_on`, and
the flow's own gate message says what that is:

    "12 ordered behind waived step 13, which declares no artefact they read"

`blocks_on` is an ORDERING edge. It says step 12 runs after step 11. It does
not say step 12 READS `phase2/stage2/dft/scan_netlist.v`, so nothing could tell
the difference between

    (a) the step ran, had its input, and produced nothing  -> a real defect
        in the step, and
    (b) the step ran with NOTHING TO READ                  -> a defect one or
        more steps UPSTREAM, mis-attributed to this step every time.

Both landed in the report as the same sentence — `flow_compliance_check`'s
"no required_outputs found (expected: [...])" — charged to the step that was
starved. This module makes (b) sayable, and says it BEFORE the step runs
instead of judging the step on the absence afterwards.

WHAT IT DOES NOT DO
===================
It does not replace `flow_compliance_check`. That module judges a step AFTER
the fact on the outputs it produced. This one is a PRE-FLIGHT: call it with
`--step <id>` immediately before dispatching that step, and it answers one
question — are the artefacts this step reads on disk right now?

It also does NOT invent a data edge. Every `required_inputs` entry with a
`from:` naming a real step carries a `path:` COPIED VERBATIM from that step's
own `required_outputs`, and this module ENFORCES that (exit 2, `SELF-
INCONSISTENT`). A declaration that points at a path its named producer does not
declare cannot be checked and is not allowed to sit in the flow pretending to
be one. That check is the guard against the exact defect this repo keeps
finding: a wrong dependency is worse than a missing one.

PRESENCE IS RESOLVED BY THE SAME FUNCTION AS OUTPUTS
====================================================
`flow_compliance_check._glob_first` — not a second, private notion of "exists".
Two consequences, both wanted: an input satisfied by a DANGLING SYMLINK does
not count (that function already refuses those, and the reason is in its own
docstring), and the " OR " inside one declared entry means the same
any-of-these-spellings here as it does there.

ATTRIBUTION, WHEN A LEDGER EXISTS
=================================
Presence alone answers "a file matching this glob exists SOMEWHERE in the
project" — never "the step that owes it produced it". When the run carries
`reports/write_ledger.json` (written by `step_write_ledger`, which records what
a run ACTUALLY wrote), this module reads it and reports, per satisfied input,
whether the DECLARED PRODUCER's own ledger row lists that file as produced:

    ledger_confirmed    the named producing step's row lists this artefact
    ledger_absent       the ledger has that step, and it is NOT in its row
    no_ledger           no reports/write_ledger.json in this run

`ledger_absent` is ADVISORY by default and blocking only under
`--strict-attribution`. It is a real signal (the file is there, the step that
owes it is not recorded as having written it) but on a pre-ledger run it is
unanswerable, and turning an unanswerable question into a FAIL is how a cell
that was fine goes red for no finding.

BACKWARD COMPATIBILITY — EXPLICIT, NEVER SILENT
===============================================
This module reads the CANONICAL `phaseN/` tree. It does NOT require a `steps/`
tree, and does not read one: a published cell (benchmark-data/ic/spm/
v1.5.58_ihp-sg13g2 has no `steps/`) and any older run are judged exactly as a
new run is. The only thing a missing ledger costs is ATTRIBUTION, and the
record says so in as many words — every JSON report carries
`degraded.attribution` naming what was unavailable and what the verdict fell
back to. A run that cannot be asked a question gets "unanswered", not "pass".

A step with NO `required_inputs` is `UNDECLARED`, which is NOT `READY`. It is
counted separately, listed by id, and never contributes to exit 0 as though it
had been checked. 7 of the flow's 68 steps are undeclared today and saying so
is the point; a check that reported them green would be the falsely-clean
result this whole exercise exists to remove.

EXIT
    0  every judged step's declared inputs are present (or the step will not
       run: condition unmet / waived), and nothing is self-inconsistent
    1  at least one judged step is BLOCKED — a declared input is absent
    2  the check could not run: flow unreadable, no steps, unknown --step id,
       or a SELF-INCONSISTENT declaration. A check that scanned nothing has
       not passed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import yaml
except ImportError:                                     # pragma: no cover
    print("step_required_inputs_check: PyYAML required", file=sys.stderr)
    sys.exit(2)

# Resolver parity with the OUTPUT side. Imported, never reimplemented: two
# notions of "this artefact exists" is how the two halves of one contract end
# up disagreeing about the same file.
try:
    from flow_compliance_check import (      # type: ignore
        _glob_first, _check_condition, _load_waivers, DEFAULT_FLOW_DEF)
except Exception as exc:                                # pragma: no cover
    print(f"step_required_inputs_check: cannot import flow_compliance_check: "
          f"{exc}", file=sys.stderr)
    sys.exit(2)


LEDGER_REL = "reports/write_ledger.json"


# --------------------------------------------------------------------------- #
# Declaration loading + SELF-CONSISTENCY
# --------------------------------------------------------------------------- #
def load_flow(flow_def: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        doc = yaml.safe_load(flow_def.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [], f"flow unreadable: {exc}"
    steps = (doc or {}).get("steps") or []
    if not isinstance(steps, list) or not steps:
        return [], "flow declares no steps"
    return steps, None


def declaration_defects(steps: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Every way a `required_inputs` entry can fail to MEAN anything.

    Returned non-empty => exit 2. This is deliberately fatal rather than a
    per-step FAIL: an input naming a path its declared producer does not
    declare is not a finding ABOUT A RUN, it is a broken contract, and every
    verdict computed from it would be arbitrary.
    """
    by_id = {str(s.get("id")): s for s in steps}
    out: List[Dict[str, str]] = []
    for s in steps:
        sid = str(s.get("id"))
        for i, e in enumerate(s.get("required_inputs") or []):
            where = f"step {sid} required_inputs[{i}]"
            if not isinstance(e, dict) or "from" not in e:
                out.append({"where": where, "defect": "entry is not a mapping "
                            "with a `from:` key"})
                continue
            src = str(e["from"])
            if src == "external":
                if e.get("check") == "none":
                    if not e.get("what"):
                        out.append({"where": where, "defect": "external input "
                                    "with check:none must carry `what:` — an "
                                    "unnamed unchecked input is not a "
                                    "declaration"})
                elif not e.get("path"):
                    out.append({"where": where, "defect": "external input "
                                "needs either `path:` or `check: none`"})
                continue
            if src not in by_id:
                out.append({"where": where,
                            "defect": f"`from: {src}` names no step in the flow"})
                continue
            outs = by_id[src].get("required_outputs") or []
            if e.get("outputs") == "all":
                if not outs:
                    out.append({"where": where, "defect": f"`outputs: all` but "
                                f"step {src} declares no required_outputs"})
                continue
            path = e.get("path")
            if not path:
                out.append({"where": where,
                            "defect": "needs `path:` or `outputs: all`"})
            elif path not in outs:
                out.append({"where": where, "defect":
                            f"path {path!r} is NOT one of step {src}'s declared "
                            f"required_outputs — a data edge that names an "
                            f"artefact its own producer does not declare"})
    return out


def expand(entry: Dict[str, Any],
           by_id: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str]]:
    """(producer, declared-output-spec) pairs this entry requires."""
    src = str(entry["from"])
    if src == "external":
        p = entry.get("path")
        return [("external", p)] if p else []
    if entry.get("outputs") == "all":
        return [(src, spec) for spec in (by_id[src].get("required_outputs") or [])]
    return [(src, entry["path"])]


# --------------------------------------------------------------------------- #
# Ledger attribution
# --------------------------------------------------------------------------- #
def load_ledger(project: Path) -> Optional[Dict[str, set]]:
    """step-id -> set of project-relative paths that step's row records as
    PRODUCED. None when the run carries no ledger (pre-ledger / published)."""
    f = project / LEDGER_REL
    if not f.is_file():
        return None
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = doc.get("steps")
    if not isinstance(rows, list):
        return None
    out: Dict[str, set] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        out[str(r.get("id"))] = {
            str(p.get("rel")) for p in (r.get("produced") or [])
            if isinstance(p, dict) and p.get("rel")}
    return out


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #
def check_one(project: Path, step: Dict[str, Any],
              by_id: Dict[str, Dict[str, Any]],
              waivers: Dict[Any, Dict[str, str]],
              ledger: Optional[Dict[str, set]]) -> Dict[str, Any]:
    sid = str(step.get("id"))
    rec: Dict[str, Any] = {
        "id": sid, "name": step.get("name", ""),
        "stage": step.get("stage", ""),
        "verdict": "READY", "inputs": [], "reasons": [],
    }

    # A step that will not run cannot be starved. Report why, do not judge it.
    cond = step.get("condition")
    if cond and not _check_condition(project, cond):
        rec["verdict"] = "SKIPPED-CONDITION"
        rec["reasons"].append(f"condition not met: {cond}")
        return rec
    try:
        wkey: Any = int(sid)
    except ValueError:
        wkey = sid
    if wkey in waivers:
        rec["verdict"] = "WAIVED"
        rec["reasons"].append(
            f"waived: {waivers[wkey].get('reason', '(no reason)')}")
        return rec

    entries = step.get("required_inputs") or []
    if not entries:
        rec["verdict"] = "UNDECLARED"
        rec["reasons"].append(
            "this step declares no required_inputs — its data dependency is "
            "UNKNOWN, not empty. Nothing was checked, so nothing passed.")
        return rec

    blocked, advisory = [], []
    for e in entries:
        if str(e.get("from")) == "external" and e.get("check") == "none":
            rec["inputs"].append({
                "from": "external", "path": None, "present": None,
                "attribution": "not_applicable",
                "what": e.get("what"),
                "note": "declared external input with no project-relative path "
                        "to probe; recorded so it is visible, NOT counted as "
                        "satisfied"})
            continue
        for producer, spec in expand(e, by_id):
            hits: List[str] = []
            for alt in (p.strip() for p in spec.split(" OR ")):
                hits = _glob_first(project, alt)
                if hits:
                    break
            item: Dict[str, Any] = {
                "from": producer, "path": spec,
                "present": bool(hits),
                "evidence": hits[0] if hits else None,
            }
            if e.get("what"):
                item["what"] = e["what"]
            if not hits:
                # "absent", not "not_applicable": nothing to attribute because
                # the artefact is not there, which is a DIFFERENT fact from an
                # external input that has no producer to attribute it to.
                item["attribution"] = "absent"
                blocked.append(item)
            elif producer == "external" or ledger is None:
                item["attribution"] = ("no_ledger" if producer != "external"
                                       else "not_applicable")
            elif producer in ledger:
                ok = item["evidence"] in ledger[producer]
                item["attribution"] = "ledger_confirmed" if ok else "ledger_absent"
                if not ok:
                    advisory.append(item)
            else:
                item["attribution"] = "no_ledger"
            rec["inputs"].append(item)

    if blocked:
        rec["verdict"] = "BLOCKED"
        for b in blocked:
            owed = ("an EXTERNAL input" if b["from"] == "external"
                    else f"step {b['from']}")
            rec["reasons"].append(
                f"required input ABSENT: {b['path']} (owed by {owed}). This "
                f"step has nothing to read; running it now would produce "
                f"nothing and the absence would be charged to this step.")
    for a in advisory:
        rec["reasons"].append(
            f"ADVISORY attribution: {a['evidence']} is present but step "
            f"{a['from']}'s write-ledger row does not record producing it — "
            f"presence here is 'a matching file exists somewhere', not "
            f"'the step that owes it produced it'.")
    rec["attribution_advisories"] = len(advisory)
    return rec


def build(project: Path, flow_def: Path, only: Optional[str],
          strict_attribution: bool) -> Tuple[Dict[str, Any], int]:
    steps, err = load_flow(flow_def)
    if err:
        return {"ok": False, "error": err}, 2

    defects = declaration_defects(steps)
    if defects:
        return {"ok": False, "error": "SELF-INCONSISTENT required_inputs "
                "declaration — refusing to compute a verdict from it",
                "declaration_defects": defects}, 2

    by_id = {str(s.get("id")): s for s in steps}
    if only is not None and only not in by_id:
        return {"ok": False,
                "error": f"--step {only!r} names no step in the flow"}, 2

    waivers = _load_waivers(project)
    ledger = load_ledger(project)
    judged = [by_id[only]] if only else steps

    rows = [check_one(project, s, by_id, waivers, ledger) for s in judged]
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    advisories = sum(r.get("attribution_advisories", 0) for r in rows)

    report = {
        "ok": True,
        "project": str(project),
        "flow_def": str(flow_def),
        "mode": "preflight-one-step" if only else "whole-project",
        "step": only,
        "counts": counts,
        "undeclared": [r["id"] for r in rows if r["verdict"] == "UNDECLARED"],
        "blocked": [r["id"] for r in rows if r["verdict"] == "BLOCKED"],
        "attribution_advisories": advisories,
        "degraded": {
            # Named, never silent. A reader must be able to tell an answered
            # question from one this run could not be asked.
            "attribution": (
                "unavailable — no reports/write_ledger.json in this run "
                "(pre-ledger or published cell). Input presence is "
                "PRESENCE-ONLY, i.e. today's behaviour: a matching file "
                "exists somewhere in the project. Producer attribution was "
                "NOT checked and is not claimed."
                if ledger is None else
                f"available — reports/write_ledger.json carries "
                f"{len(ledger)} step rows; each satisfied input is compared "
                f"against its declared producer's row."),
            "steps_tree": (
                "not required and not read — this check judges the canonical "
                "phaseN/ tree, so a run with no steps/ tree is judged "
                "identically to one with it."),
        },
        "steps": rows,
    }
    if counts.get("BLOCKED"):
        return report, 1
    if strict_attribution and advisories:
        report["strict_attribution"] = (
            f"{advisories} attribution advisory(ies) escalated to a failure by "
            f"--strict-attribution")
        return report, 1
    return report, 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Pre-flight: does this step have what it needs to read?")
    ap.add_argument("project", nargs="?", default=".", type=Path)
    ap.add_argument("--step", default=None,
                    help="judge exactly this step id (the pre-flight call "
                         "made immediately before dispatching it)")
    ap.add_argument("--flow-def", type=Path, default=DEFAULT_FLOW_DEF)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--strict-attribution", action="store_true",
                    help="escalate ledger attribution advisories to a failure")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    report, rc = build(a.project.resolve(), a.flow_def, a.step,
                       a.strict_attribution)
    if a.json:
        try:
            a.json.parent.mkdir(parents=True, exist_ok=True)
            a.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"could not write {a.json}: {exc}", file=sys.stderr)
    if not a.quiet:
        if not report.get("ok"):
            print(f"required-inputs: {report.get('error')}")
            for d in report.get("declaration_defects", [])[:20]:
                print(f"  - {d['where']}: {d['defect']}")
        else:
            print(f"required-inputs pre-flight: {report['counts']}")
            print(f"  attribution: {report['degraded']['attribution']}")
            for r in report["steps"]:
                if r["verdict"] in ("BLOCKED", "UNDECLARED"):
                    print(f"  [{r['verdict']}] {r['id']}: {r['reasons'][0]}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
