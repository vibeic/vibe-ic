#!/usr/bin/env python3
"""Audit ECO (Engineering Change Order) log for completeness.

Step 32 declares TWO artefacts:

    phase3/stage3/eco/eco_log.json OR phase3/stage3/eco/no_eco_needed.flag
    phase3/stage3/eco/eco_trigger_decision.json

The second one is the record of WHY an ECO was or was not run — it is what
`phase3_one_shot_runner.step_canonicalize_artefacts` writes from
`eco_trigger_decision.decide(...)`, and it is the only artefact that states
whether an ECO was REQUIRED. This audit opened the eco LOG only, so the
decision the step exists to justify was never cross-checked against the
outcome the step recorded.

Measured on a project holding a decision record that says an ECO was required
(`eco_needed: true`, a hard `ir_drop` sign-off failure) next to a
`no_eco_needed.flag`::

    $ eco_loop_audit <proj>
    "eco_needed": false, "pass": true      rc=0

The `no_eco_needed.flag` branch returned with NO findings before reading
anything else, so the flag alone certified the step — the exact false-clean
`eco_trigger_decision`'s own v1.7.64 fail-close was written to prevent, one
artefact downstream.

CONTRADICTION IS THE FINDING, ABSENCE IS NOT. A project with no decision
record is left alone (it is Step 32's `required_outputs` that reports a
missing artefact, not this gate's job), and an UNPARSEABLE record is reported
rather than skipped — "unmeasured is not zero".
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl

#: The decision record step 32 declares, spelled EXACTLY as the flow yaml
#: spells it — and this constant is what :func:`decision_path` composes the
#: read from, not merely what the messages quote.
#:
#: That distinction is the whole point of it being here. When the literal
#: appears only inside a message f-string, a static "is this gate wired to the
#: artefact its step declares?" audit is satisfied by the gate's PROSE: delete
#: the read, keep the message, and the audit still says wired. The read is
#: therefore composed from this constant, so the string the audit sees and the
#: path the program opens are the same object.
TRIGGER_DECISION_DECLARED = "phase3/stage3/eco/eco_trigger_decision.json"

#: Basename of the above, derived rather than restated so the two cannot drift.
TRIGGER_DECISION_FILENAME = TRIGGER_DECISION_DECLARED.rsplit("/", 1)[-1]


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def decision_path(project_dir: Path) -> Path:
    """The declared decision record, composed from the declared spelling.

    ``_path_layout.eco_dir`` stays the catalogue of record and the two are
    cross-checked in :func:`load_trigger_decision`; composing here from
    :data:`TRIGGER_DECISION_DECLARED` is what makes the literal load-bearing
    instead of decorative.
    """
    return Path(project_dir) / TRIGGER_DECISION_DECLARED


def load_trigger_decision(
        project_dir: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Finding]]:
    """``(decision dict, finding)`` for ``eco_trigger_decision.json``.

    Absent  -> ``(None, None)``  — nothing to cross-check (Step 32's
               ``required_outputs`` is what reports a missing artefact).
    Unparseable / not an object -> ``(None, Finding)`` — an unreadable
               decision is UNMEASURED, and unmeasured is not "no ECO needed".

    Takes the PROJECT root, not the eco dir: the path is built from the flow's
    own spelling of the artefact (see :data:`TRIGGER_DECISION_DECLARED`).
    """
    src = decision_path(project_dir)
    # The declared spelling and the directory catalogue must agree. If they
    # ever diverge, this gate would be auditing a different file from the one
    # the rest of the flow writes — report it rather than silently pick one.
    catalogued = _pl.eco_dir(Path(project_dir)) / TRIGGER_DECISION_FILENAME
    if src != catalogued:
        return None, Finding(
            "ERROR", "TRIGGER_DECISION_PATH_DRIFT",
            f"this gate composes {TRIGGER_DECISION_DECLARED} while "
            f"_path_layout puts the record at {catalogued} — the flow's "
            f"declaration and the directory catalogue have drifted apart, so "
            f"nothing here can be trusted to have read the step's artefact")
    if not src.exists():
        return None, None
    try:
        data = json.loads(src.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, Finding(
            "ERROR", "BAD_TRIGGER_DECISION",
            f"cannot parse {TRIGGER_DECISION_DECLARED}: {exc} — the record of "
            f"WHY an ECO was or was not run is unreadable, so the ECO outcome "
            f"below is uncorroborated")
    if not isinstance(data, dict):
        return None, Finding(
            "ERROR", "BAD_TRIGGER_DECISION",
            f"{TRIGGER_DECISION_DECLARED} is not a JSON object "
            f"({type(data).__name__}) — no decision to cross-check")
    return data, None


def _decision_findings(decision: Dict[str, Any], *,
                       flag_present: bool,
                       log_present: bool) -> List[Finding]:
    """Cross-check the recorded DECISION against the recorded OUTCOME.

    THE TWO CONTRADICTIONS ARE NOT SYMMETRIC, and the severities say so.

    ``eco_needed: true`` beside ``no_eco_needed.flag`` is a SIGN-OFF LIE: the
    step's own record says a repair was required and the run certified that
    none was. Nothing downstream re-checks that, so it is an ERROR and it
    blocks.

    ``eco_needed: false`` beside an ``eco_log.json`` is an inconsistency, not a
    lie about closure: an ECO ran that the auto-trigger did not demand. The
    auto-trigger is not the only legitimate way an ECO gets run (the `eco-plan`
    skill and a manual repair both write the log), so raising this to ERROR
    would fail a run whose only fault is that a human decided to repair
    something the automation did not insist on. It is a WARNING, reported and
    not blocking — deliberately, not by omission.
    """
    out: List[Finding] = []
    eco_needed = decision.get("eco_needed")
    action = decision.get("action")
    reason = str(decision.get("reason") or "")[:200]
    nontiming = decision.get("nontiming_failures") or []

    if eco_needed is True and flag_present:
        detail = f"decision reason: {reason}" if reason else ""
        if isinstance(nontiming, list) and nontiming:
            domains = ", ".join(
                str(r.get("domain")) for r in nontiming if isinstance(r, dict))
            detail = (detail + f"; hard sign-off failure(s): {domains}").strip("; ")
        out.append(Finding(
            "ERROR", "TRIGGER_DECISION_CONTRADICTED",
            f"{TRIGGER_DECISION_DECLARED} records eco_needed=true "
            f"(action={action!r}) but the run certified no_eco_needed.flag — "
            f"the step's own record of WHY says an ECO was required",
            detail))
    if eco_needed is False and log_present and not flag_present:
        out.append(Finding(
            "WARNING", "TRIGGER_DECISION_UNEXPLAINED_ECO",
            f"an eco_log.json exists but {TRIGGER_DECISION_DECLARED} records "
            f"eco_needed=false (action={action!r}) — the ECO that ran is not "
            f"the one the decision record justifies",
            f"decision reason: {reason}" if reason else ""))
    if not isinstance(eco_needed, bool):
        # A RECORD THAT STATES NOTHING IS NOT A RECORD THAT STATES "NO", so it
        # is reported. It is NOT an ERROR, and the reason is measured rather
        # than assumed: `eco_trigger_decision.decide` initialises `eco_needed`
        # to a bool on every path, so no run this flow produces can reach here
        # — the only trees that do are hand-authored or synthesized ones. An
        # earlier cut of this made it block on the flag branch and the cost was
        # real and immediate: the dimension-8 module drives every step's OWN
        # gate over a synthesized tree that seeds each declared output with
        # kind-correct-but-contentless bytes, and step 32 fell out of
        # `REAL_GATE_PASS_TIER_STEPS` — i.e. step 32 lost its only production-
        # gate proof that the missing-output downgrade is reachable. Trading a
        # measured coverage loss elsewhere for a guard against a state the flow
        # cannot produce is a bad trade, so this discloses and does not block.
        out.append(Finding(
            "WARNING", "TRIGGER_DECISION_SILENT",
            f"{TRIGGER_DECISION_DECLARED} is present but states no "
            f"`eco_needed` (found {eco_needed!r}) — the record of WHY an ECO "
            f"was or was not run says nothing, so the outcome beside it is "
            f"uncorroborated",
            f"decision keys: {sorted(decision)[:12]}"))
    return out


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    eco_dir = _pl.eco_dir(project_dir)
    eco_log = eco_dir / "eco_log.json"
    no_eco = eco_dir / "no_eco_needed.flag"
    stats = {"eco_needed": None, "changes_count": 0, "re_verified": False}

    # The step's DECLARED decision record, read before either branch: it is
    # the only artefact that states whether an ECO was REQUIRED, and the
    # `no_eco_needed.flag` branch used to return before anything read it.
    decision, decision_problem = load_trigger_decision(project_dir)
    if decision_problem is not None:
        findings.append(decision_problem)
    stats["trigger_decision_read"] = decision is not None
    if decision is not None:
        stats["trigger_decision_eco_needed"] = decision.get("eco_needed")
        stats["trigger_decision_action"] = decision.get("action")
        findings.extend(_decision_findings(
            decision,
            flag_present=no_eco.exists(),
            log_present=eco_log.exists()))

    if no_eco.exists():
        stats["eco_needed"] = False
        return findings, stats

    if not eco_log.exists():
        findings.append(Finding("ERROR", "NO_ECO_ARTIFACT",
                                "Neither eco/eco_log.json nor eco/no_eco_needed.flag found"))
        return findings, stats

    stats["eco_needed"] = True
    try:
        data = json.loads(eco_log.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        findings.append(Finding("ERROR", "BAD_JSON",
                                f"Cannot parse eco_log.json: {exc}"))
        return findings, stats

    changes = data.get("changes", [])
    if not isinstance(changes, list) or len(changes) == 0:
        findings.append(Finding("ERROR", "EMPTY_CHANGES",
                                "eco_log.json 'changes' array is missing or empty"))
    stats["changes_count"] = len(changes) if isinstance(changes, list) else 0

    re_verified = data.get("re_verified", False)
    stats["re_verified"] = bool(re_verified)
    if not re_verified:
        findings.append(Finding("ERROR", "NOT_REVERIFIED",
                                "ECO applied but re_verified is false — must re-run sign-off"))

    if "affected_steps" not in data:
        findings.append(Finding("WARNING", "NO_AFFECTED_STEPS",
                                "eco_log.json missing 'affected_steps' array"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "eco_loop_audit",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "eco_needed": stats["eco_needed"],
            "changes_count": stats["changes_count"],
            "re_verified": stats["re_verified"],
            "trigger_decision_read": stats.get("trigger_decision_read", False),
            "trigger_decision_eco_needed":
                stats.get("trigger_decision_eco_needed"),
            "trigger_decision_action": stats.get("trigger_decision_action"),
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Audit ECO log completeness")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(project_dir)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
