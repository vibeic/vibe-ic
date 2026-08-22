#!/usr/bin/env python3
"""die_finishing_check.py — the Step 26.5ic gate.

ENFORCEMENT: advisory here — this gate is not in
``phase3_one_shot_runner._DECLARED_SIGNOFF_GATES``; no one-shot runner invokes
it inline at all. It runs when ``flow_compliance_check`` evaluates step 26.5ic's
``program_exit_zero`` clause, so its rc IS that step's verdict — "advisory"
names the RUNNER channel it is absent from, not a verdict this gate cannot
reach. Declared because vibe-ic#886 counts an undeclared AUDIT_ONLY gate as an
enforcement decision nobody made; wiring it into the runner would change what a
real run blocks on, which is the flow owner's call and is recorded, not taken
here. Kept in the first 4 kB: `declared_intent` reads only `text[:4000]`.

It RE-REPORTS what `die_finishing_gen` measured. It never runs a seal-ring
generator, never opens a layout and never writes a GDS, so auditing a finished
project can never mutate the die it is auditing — the same producer/auditor
split Step 34 uses for `metal_fill_emit --verify-only`.

THE TWO HALVES ARE REPORTED SEPARATELY, ALWAYS
-----------------------------------------------
Step 26.5ic is die FINISHING: a seal ring AND die identification. They have
different owners and different states, and collapsing them into one word is the
failure this gate is written to prevent.

    seal ring   PASS / FAIL / DISCLOSED_SKIP — measured from the layout by
                the producer (a diff of the pre- and post-generator GDS).
    die id      PRESENT / ABSENT / NOT_APPLICABLE / NOT_DETERMINED — the
                shuttle's own cells, and CONDITIONAL on the packaging choice.
                Measured on the operator's own `generate_id.py`: the entire
                four-cell requirement sits behind `if cob:` and `--cob`
                defaults OFF, so a non-CoB submission legitimately carries
                none of them. NOT_APPLICABLE is a DECIDED answer (the
                condition was read and did not hold); NOT_DETERMINED is an
                undecided one (the condition was never declared).

HOW THAT REACHES THE FLOW, in the flow's own vocabulary
-------------------------------------------------------
    seal FAIL                       -> rc 1, hard FAIL.
    seal DISCLOSED_SKIP             -> rc 2 + `VACUOUS_PASS:` — the flow's
                                       "the checker did not run, and says so"
                                       tier. Never a bare PASS.
    seal PASS, die id NOT_DETERMINED-> rc 0 + `INCOMPLETE:` — the flow's
                                       "not audited, and someone must come
                                       back" tier (flow_compliance_check
                                       promotes a step that prints it). It is
                                       neither clean nor red.
    seal PASS, die id ABSENT        -> rc 1. A chip-on-board submission that
                                       is missing the cells its operator
                                       hard-blocks on is a real failure, not
                                       an open question.
    seal PASS, die id NOT_APPLICABLE-> rc 0 + `SUBSTANTIVE_PASS`. The
                                       condition was READ and it did not hold;
                                       that is an answer, not a silence.
    seal PASS, die id PRESENT       -> rc 0 + `SUBSTANTIVE_PASS`.

A missing producer report is NOT a pass: rc 2 with the reason named.

WHY IT READS A `run` BLOCK. This gate's `--json` target is the same path the
producer writes (`reports/phase3/die_finishing.json`) — the flow declares it
that way. Overwriting the measurement with the verdict would destroy the
evidence, and a second run would then audit its own output, which is the
`_discover`-re-ingests-its-own-verdict defect Step 26 hit for real. So the
verdict document EMBEDS the producer's report under `run`, and this program
always unwraps a `run` block before reading. Running it twice is therefore
idempotent and loses nothing.

chip/PDK-AGNOSTIC: it reads a report. No foundry, PDK, vendor or design literal
appears here.

    die_finishing_check <project_dir> [--report R] [--json J] [--strict]
    main(argv) -> int : 0 PASS / 1 FAIL / 2 DISCLOSED SKIP
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from _atomic_artefact import write_json as atomic_write_json  # vibe-ic#1082

PASS, FAIL, SKIP = 0, 1, 2

_CHECK = "die_finishing"
_PRODUCER = "die_finishing_gen"
_REPORT_REL = "reports/phase3/die_finishing.json"
#: The producer's own marker artefacts, read only to CROSS-CHECK the report
#: against what is on disk. A report that says PASS beside no finished-die DEF
#: is describing a run that did not leave what it claims to have left.
_DEF_REL = "phase3/stage3/pnr/die_finished.def"
_SKIPPED_REL = "phase3/stage3/pnr/die_finishing.SKIPPED.txt"

_UNDETERMINED = "NOT_DETERMINED"


def _unwrap(doc: Any) -> Optional[Dict[str, Any]]:
    """The producer's measurement, whether `doc` is that report or a verdict
    document this program wrote around it."""
    if not isinstance(doc, dict):
        return None
    inner = doc.get("run")
    if isinstance(inner, dict) and inner.get("producer") == _PRODUCER:
        return inner
    if doc.get("producer") == _PRODUCER:
        return doc
    return None


def evaluate(project: Path, report: Optional[str] = None) -> Dict[str, Any]:
    rep = Path(report) if report else (project / _REPORT_REL)
    if not rep.is_absolute():
        rep = project / rep

    def undecided(reason: str) -> Dict[str, Any]:
        return {"check": _CHECK, "verdict": "DISCLOSED_SKIP", "reason": reason,
                "seal_ring": {"state": _UNDETERMINED, "reason": reason},
                "die_id": {"state": _UNDETERMINED, "reason": reason}}

    if not rep.is_file():
        return undecided(
            f"{_PRODUCER} has not run on this project — no die-finishing "
            f"report at {rep}. Nothing is claimed about the seal ring or the "
            "die identification.")
    try:
        doc = json.loads(rep.read_text())
    except (ValueError, OSError) as exc:
        return {"check": _CHECK, "verdict": "FAIL",
                "reason": f"die-finishing report unreadable: {exc}"}
    run = _unwrap(doc)
    if run is None:
        return {"check": _CHECK, "verdict": "FAIL",
                "reason": (f"{rep} is not a {_PRODUCER} report (no "
                           f"producer={_PRODUCER!r} field) — refusing to read "
                           "an unattributed document as evidence")}

    seal = run.get("seal_ring") if isinstance(run.get("seal_ring"), dict) else {}
    die = run.get("die_id") if isinstance(run.get("die_id"), dict) else {}
    seal_state = seal.get("state") or _UNDETERMINED
    die_state = die.get("state") or _UNDETERMINED

    res: Dict[str, Any] = {"check": _CHECK, "report": str(rep),
                           "seal_ring": dict(seal), "die_id": dict(die),
                           "run": run}

    # CROSS-CHECK the report against the artefacts on disk. A claim and the
    # thing it claims about are two different facts, and the whole point of
    # this repository is not to let one stand in for the other.
    fin, skipped = project / _DEF_REL, project / _SKIPPED_REL
    res["artefacts_on_disk"] = {"die_finished.def": fin.is_file(),
                                "die_finishing.SKIPPED.txt": skipped.is_file()}
    if seal_state == "PASS" and not fin.is_file():
        return {**res, "verdict": "FAIL",
                "reason": (f"the report says the seal ring was inserted, but "
                           f"{_DEF_REL} is not on disk — the finished die the "
                           "report describes was not left behind")}
    # Only a skip that CLAIMS the marker is cross-checked against it. A skip
    # for an absent input ("no streamed GDS", "no KLayout") deliberately writes
    # no marker — the step could not run, which is not the same fact as die
    # finishing legitimately not applying to this PDK, and must not be recorded
    # as though it were.
    if (seal_state == "DISCLOSED_SKIP" and seal.get("marker")
            and not skipped.is_file()):
        return {**res, "verdict": "FAIL",
                "reason": (f"the report says die finishing was skipped, but "
                           f"{_SKIPPED_REL} is not on disk — the skip was not "
                           "recorded where the flow declares it")}

    if seal_state == "FAIL":
        return {**res, "verdict": "FAIL",
                "reason": "seal ring: " + str(seal.get("reason")
                                              or "not inserted")}
    if seal_state == "DISCLOSED_SKIP":
        return {**res, "verdict": "DISCLOSED_SKIP",
                "reason": "seal ring: " + str(seal.get("reason"))}
    if seal_state != "PASS":
        return {**res, "verdict": "DISCLOSED_SKIP",
                "reason": (f"the report records no seal-ring state "
                           f"({seal_state!r}); nothing is claimed")}

    # The ring is verified. The die-id half decides only the TIER from here —
    # it can raise a FAIL of its own, but it can never turn a verified ring
    # into an unverified one.
    if die_state == "ABSENT":
        return {**res, "verdict": "FAIL",
                "reason": "die identification: " + str(die.get("reason"))}
    if die_state == "PRESENT":
        return {**res, "verdict": "PASS", "tier": "SUBSTANTIVE_PASS",
                "reason": "seal ring verified; die identification present"}
    if die_state == "NOT_APPLICABLE":
        # DECIDED, not silent. The packaging condition was read and it did not
        # hold, so there is nothing left for anyone to come back to — which is
        # exactly what separates this from NOT_DETERMINED below.
        return {**res, "verdict": "PASS", "tier": "SUBSTANTIVE_PASS",
                "reason": ("seal ring verified; die identification not "
                           f"applicable: {die.get('reason')}")}
    return {**res, "verdict": "PASS", "tier": "INCOMPLETE",
            "reason": ("seal ring verified; die identification "
                       f"{die_state}: {die.get('reason')}")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Step 26.5ic gate — re-report the die-finishing "
                    "measurement; never re-run it.")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--report", default=None,
                    help=f"the producer's report (default {_REPORT_REL})")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="treat a disclosed skip or an undetermined die-id "
                         "half as a FAIL (tapeout sign-off)")
    ns = ap.parse_args(argv)

    project = Path(ns.project_dir).resolve()
    try:
        res = evaluate(project, ns.report)
    except Exception as exc:                                 # noqa: BLE001
        res = {"check": _CHECK, "verdict": "FAIL",
               "reason": f"gate error: {exc}"}

    verdict, tier = res.get("verdict"), res.get("tier")
    if ns.strict and (verdict == "DISCLOSED_SKIP" or tier == "INCOMPLETE"):
        res = {**res, "verdict": "FAIL",
               "reason": f"--strict: {res.get('reason')}"}
        verdict, tier = "FAIL", None

    if ns.json_out:
        o = Path(ns.json_out)
        if not o.is_absolute():
            o = project / o
        o.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(o, res)

    print(json.dumps({k: v for k, v in res.items() if k != "run"}, indent=2))
    if verdict == "DISCLOSED_SKIP":
        print(f"VACUOUS_PASS: die_finishing_check judged nothing — "
              f"{res.get('reason')}")
        return SKIP
    if verdict == "PASS":
        # The flow's own two disclosure tiers, printed so the roll-up can tell
        # "audited by another route" from "not audited, and someone must come
        # back" — the distinction the die-id half exists inside today.
        if tier == "INCOMPLETE":
            print(f"INCOMPLETE: {res.get('reason')}")
        else:
            print(f"SUBSTANTIVE_PASS: {res.get('reason')}")
        return PASS
    print(f"die_finishing_check: FAIL — {res.get('reason')}")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
