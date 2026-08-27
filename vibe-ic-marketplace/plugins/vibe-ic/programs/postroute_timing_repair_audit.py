#!/usr/bin/env python3
"""Audit the post-route timing repair pass's log for completeness.

The step this audits is NOT an Engineering Change Order: it re-runs
``detailed_route`` on the whole design, and there is no released revision for
a change order to act on. Its module, API, schema, directory and artefact names
therefore use ``postroute_timing_repair`` / ``repair`` consistently.

Step 32 declares TWO artefacts:

    phase3/stage3/postroute_timing_repair/repair_log.json OR phase3/stage3/postroute_timing_repair/no_repair_needed.flag
    phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json

The second one is the record of WHY a post-route repair was or was not run —
it is what `phase3_one_shot_runner.step_canonicalize_artefacts` writes from
`postroute_timing_repair_decision.decide(...)`, and it is the only artefact
that states whether a post-route repair was REQUIRED. This audit used to open
the repair log only, so the decision the step exists to justify was never
cross-checked against the outcome the step recorded.

Measured on a project holding a decision record that says a post-route repair was required
(`repair_needed: true`, a hard `ir_drop` sign-off failure) next to a
`no_repair_needed.flag`::

    $ postroute_timing_repair_audit <proj>
    "repair_needed": false, "pass": true      rc=0

The `no_repair_needed.flag` branch returned with NO findings before reading
anything else, so the flag alone certified the step — the exact false-clean
`postroute_timing_repair_decision`'s own v1.7.64 fail-close was written to prevent, one
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
TRIGGER_DECISION_DECLARED = "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json"

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

    ``_path_layout.postroute_timing_repair_dir`` stays the catalogue of record and the two are
    cross-checked in :func:`load_trigger_decision`; composing here from
    :data:`TRIGGER_DECISION_DECLARED` is what makes the literal load-bearing
    instead of decorative.
    """
    return Path(project_dir) / TRIGGER_DECISION_DECLARED


def load_trigger_decision(
        project_dir: Path) -> Tuple[Optional[Dict[str, Any]], Optional[Finding]]:
    """``(decision dict, finding)`` for ``postroute_timing_repair_decision.json``.

    Absent  -> ``(None, None)``  — nothing to cross-check (Step 32's
               ``required_outputs`` is what reports a missing artefact).
    Unparseable / not an object -> ``(None, Finding)`` — an unreadable
               decision is UNMEASURED, and unmeasured is not "no post-route repair needed".

    Takes the PROJECT root, not the repair directory: the path is built from
    the flow's
    own spelling of the artefact (see :data:`TRIGGER_DECISION_DECLARED`).
    """
    src = decision_path(project_dir)
    # The declared spelling and the directory catalogue must agree. If they
    # ever diverge, this gate would be auditing a different file from the one
    # the rest of the flow writes — report it rather than silently pick one.
    catalogued = _pl.postroute_timing_repair_dir(Path(project_dir)) / TRIGGER_DECISION_FILENAME
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
            f"WHY a post-route repair was or was not run is unreadable, so the post-route repair outcome "
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

    ``repair_needed: true`` beside ``no_repair_needed.flag`` is a SIGN-OFF LIE: the
    step's own record says a repair was required and the run certified that
    none was. Nothing downstream re-checks that, so it is an ERROR and it
    blocks.

    ``repair_needed: false`` beside an ``repair_log.json`` is an inconsistency, not a
    lie about closure: a post-route repair ran that the auto-trigger did not
    demand. A manual repair can also write the log, so raising this to ERROR
    would fail a run whose only fault is that a human decided to repair
    something the automation did not insist on. It is a WARNING, reported and
    not blocking — deliberately, not by omission.
    """
    out: List[Finding] = []
    repair_needed = decision.get("repair_needed")
    action = decision.get("action")
    reason = str(decision.get("reason") or "")[:200]
    nontiming = decision.get("nontiming_failures") or []

    if repair_needed is True and flag_present:
        detail = f"decision reason: {reason}" if reason else ""
        if isinstance(nontiming, list) and nontiming:
            domains = ", ".join(
                str(r.get("domain")) for r in nontiming if isinstance(r, dict))
            detail = (detail + f"; hard sign-off failure(s): {domains}").strip("; ")
        out.append(Finding(
            "ERROR", "TRIGGER_DECISION_CONTRADICTED",
            f"{TRIGGER_DECISION_DECLARED} records repair_needed=true "
            f"(action={action!r}) but the run certified no_repair_needed.flag — "
            f"the step's own record of WHY says a post-route repair was required",
            detail))
    if repair_needed is False and log_present and not flag_present:
        out.append(Finding(
            "WARNING", "TRIGGER_DECISION_UNEXPLAINED_REPAIR",
            f"a repair_log.json exists but {TRIGGER_DECISION_DECLARED} records "
            f"repair_needed=false (action={action!r}) — the post-route repair that ran is not "
            f"the one the decision record justifies",
            f"decision reason: {reason}" if reason else ""))
    if not isinstance(repair_needed, bool):
        # A RECORD THAT STATES NOTHING IS NOT A RECORD THAT STATES "NO", so it
        # is reported. It is NOT an ERROR, and the reason is measured rather
        # than assumed: `postroute_timing_repair_decision.decide` initialises `repair_needed`
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
            f"`repair_needed` (found {repair_needed!r}) — the record of WHY a post-route repair "
            f"was or was not run says nothing, so the outcome beside it is "
            f"uncorroborated",
            f"decision keys: {sorted(decision)[:12]}"))
    return out


def _nontiming_block_domains(log: dict, decision: Optional[dict]) -> List[str]:
    """Names of the NON-TIMING sign-off domains that required this post-route repair, when
    the run is in the v1.7.64 fail-close state and no timing post-route repair was applied.

    Empty list => not that state => every pre-existing finding applies
    unchanged. Both inputs are consulted because the two records carry the same
    two fields and either may be the one present: `postroute_timing_repair_decision.json`
    is canonical, `repair_log.json` is what `postroute_timing_repair_status_gen` copies into the log.

    The state is recognised ONLY from an EXPLICIT declaration — the
    `repair_required_non_timing` action, or `timing_repair_needed` declared literally
    False beside a non-empty `nontiming_failures`. A missing, null or
    non-boolean `timing_repair_needed` does NOT qualify: a record that says
    nothing must not be read as saying "no timing post-route repair was needed", which is
    what would let this branch swallow a genuine unapplied timing repair.

    chip-AGNOSTIC: canonical record keys only; no design, PDK or vendor token.
    """
    for rec in (decision, log):
        if not isinstance(rec, dict):
            continue
        action = rec.get("action")
        timing_needed = rec.get("timing_repair_needed")
        nontiming = rec.get("nontiming_failures")
        domains = [str(r.get("domain")) for r in nontiming
                   if isinstance(r, dict) and r.get("domain")] \
            if isinstance(nontiming, list) else []
        qualifies = (action == "repair_required_non_timing") or (
            timing_needed is False and bool(domains))
        if qualifies and domains:
            # De-duplicated, order preserved: the same domain can be named by
            # both records, and a repeated name reads as two separate failures.
            seen, out = set(), []
            for d in domains:
                if d not in seen:
                    seen.add(d)
                    out.append(d)
            return out
    return []


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    postroute_timing_repair_dir = _pl.postroute_timing_repair_dir(project_dir)
    repair_log = postroute_timing_repair_dir / "repair_log.json"
    no_repair = postroute_timing_repair_dir / "no_repair_needed.flag"
    stats = {"repair_needed": None, "changes_count": 0, "re_verified": False}

    # The step's DECLARED decision record, read before either branch: it is
    # the only artefact that states whether a post-route repair was REQUIRED, and the
    # `no_repair_needed.flag` branch used to return before anything read it.
    decision, decision_problem = load_trigger_decision(project_dir)
    if decision_problem is not None:
        findings.append(decision_problem)
    stats["trigger_decision_read"] = decision is not None
    if decision is not None:
        stats["trigger_decision_repair_needed"] = decision.get("repair_needed")
        stats["trigger_decision_action"] = decision.get("action")
        findings.extend(_decision_findings(
            decision,
            flag_present=no_repair.exists(),
            log_present=repair_log.exists()))

    if no_repair.exists():
        stats["repair_needed"] = False
        return findings, stats

    if not repair_log.exists():
        findings.append(Finding(
            "ERROR", "NO_REPAIR_ARTIFACT",
            "Neither postroute_timing_repair/repair_log.json nor "
            "postroute_timing_repair/no_repair_needed.flag found"))
        return findings, stats

    stats["repair_needed"] = True
    try:
        data = json.loads(repair_log.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        findings.append(Finding("ERROR", "BAD_JSON",
                                f"Cannot parse repair_log.json: {exc}"))
        return findings, stats

    changes = data.get("changes", [])
    stats["changes_count"] = len(changes) if isinstance(changes, list) else 0
    re_verified = data.get("re_verified", False)
    stats["re_verified"] = bool(re_verified)

    # WHICH post-route repair DID NOT HAPPEN, AND WAS IT SUPPOSED TO?
    #
    # v1.7.64 made Step 32 fail-close: a HARD non-timing sign-off failure (IR
    # drop, PERC, PV, EM, SI) forces `repair_needed=True` so the step can no longer
    # certify "no post-route repair needed" over a failed power-integrity domain. That fix
    # deliberately leaves `timing_repair_needed=False`, and it says so in its own
    # docstring: the timing-repair TCL never fires and therefore "never
    # fabricates a repaired `repair_log.json`". So in exactly that state `changes`
    # is empty and `re_verified` is false BY DESIGN.
    #
    # The two halves then disagreed about the same run, and this half was the
    # wrong one. EMPTY_CHANGES and NOT_REVERIFIED are structural probes — "is
    # the array populated?", "is the flag set?" — and both are ADJACENT to the
    # question the audit exists to answer: did the post-route repair loop do the right thing?
    # Reported unconditionally they assert "post-route repair applied but re_verified is
    # false — must re-run sign-off" about a post-route repair that was never applied, and
    # they point the reader at sign-off STA: the one action that cannot help,
    # because timing is not what failed. (Measured cost: a whole convergence
    # round took "re-run sign-off STA after the post-route repair" as its next action on a
    # design carrying +6.28 ns of setup margin.)
    #
    # The verdict does NOT change. The post-route repair is still required, the design is
    # still failing, this is still an ERROR and Step 32 still FAILs. Only the
    # diagnosis becomes true, and it names the domains and the action that can
    # actually clear it.
    #
    # FAIL-OPEN BY CONSTRUCTION: a record that does not declare this state is
    # byte-identical to before. It takes an explicit `repair_required_non_timing`
    # action, or an explicit `timing_repair_needed=False` beside a non-empty
    # `nontiming_failures` list, to reach the new branch — so this can never
    # silence a real EMPTY_CHANGES/NOT_REVERIFIED by omission or by a missing
    # field.
    _blocking = _nontiming_block_domains(data, decision)
    stats["nontiming_block_domains"] = _blocking

    if _blocking:
        findings.append(Finding(
            "ERROR", "REPAIR_BLOCKED_ON_NONTIMING_SIGNOFF",
            "no timing post-route repair was applied, and none should have been: the post-route repair was "
            "required by a NON-TIMING sign-off failure ("
            + ", ".join(_blocking) + "), which a timing-repair post-route repair cannot fix. "
            "Re-running sign-off STA will not clear this step — triage and "
            "re-run the named sign-off domain(s), then re-run the flow",
            f"decision action: {(decision or {}).get('action')!r}; "
            f"timing_repair_needed: "
            f"{(decision or {}).get('timing_repair_needed', data.get('timing_repair_needed'))!r}"))
    else:
        if not isinstance(changes, list) or len(changes) == 0:
            findings.append(Finding(
                "ERROR", "EMPTY_CHANGES",
                "repair_log.json 'changes' array is missing or empty"))
        if not re_verified:
            findings.append(Finding(
                "ERROR", "NOT_REVERIFIED",
                "post-route repair applied but re_verified is false — must re-run sign-off"))

    if "affected_steps" not in data:
        findings.append(Finding("WARNING", "NO_AFFECTED_STEPS",
                                "repair_log.json missing 'affected_steps' array"))

    # #766 — DID THE REPAIR SEE THE VIOLATION IT WAS SENT TO FIX?
    #
    # A post-route repair fires because a sign-off measurement found NEGATIVE setup slack.
    # A repair that answers `RSZ-0098 No setup violations found` to that has
    # not repaired anything — it is analysing a different design, or different
    # parasitics, or a different timing view. Every structural question above
    # (`changes`, `re_verified`, `affected_steps`) is satisfied by exactly that
    # run, and so was the delta guard below, because a repair that changed
    # NOTHING cannot regress anything either. It passed.
    #
    # MEASURED (subservient x gf180mcuD, r8): trigger `setup_worst_slack_ns
    # -0.09`, `postroute_timing_repair.log` `No setup violations found` on both passes, ZERO
    # setup changes — while the same design repaired from the shipped
    # post-route DEF with its own extracted SPEF closed with ONE buffer and one
    # pin swap (-0.09 -> +0.14 ns).
    #
    # Keyed on the runner's own recorded contradiction (`repair_blind_to_violation`
    # / the `postroute_timing_repair_log` sub-record beside a negative `repair_before`), so it
    # fires only where BOTH sides were measured. A record that never measured
    # one of them is untouched — absence is not the finding.
    _before = (data.get("repair_before") or {}) if isinstance(
        data.get("repair_before"), dict) else {}
    _before_setup = _before.get("setup_worst_slack_ns")
    _log_rec = data.get("postroute_timing_repair_log")
    _saw_none = bool(isinstance(_log_rec, dict)
                     and _log_rec.get("saw_no_setup_violations")
                     and not _log_rec.get("saw_setup_violations"))
    _blind = bool(data.get("repair_blind_to_violation")) or bool(
        _saw_none and isinstance(_before_setup, (int, float))
        and not isinstance(_before_setup, bool) and _before_setup < 0)
    stats["repair_blind_to_violation"] = _blind
    if _blind:
        _b = (f"{_before_setup:+.3f} ns"
              if isinstance(_before_setup, (int, float))
              and not isinstance(_before_setup, bool) else "negative")
        findings.append(Finding(
            "ERROR", "REPAIR_BLIND_TO_VIOLATION",
            "the post-route repair reported NO setup violations while the design it was "
            f"asked to fix measured setup {_b} — the repair and the "
            "measurement that fired it are not describing the same design, "
            "parasitics or timing view, so nothing was repaired",
            f"start point: {data.get('repair_start_point_basis')!r}; "
            f"before parasitics: {data.get('repair_before_parasitics')!r}; "
            f"after parasitics: {data.get('repair_after_parasitics')!r}"))

    # #766 — the post-route repair's own reroute is what realizes the repair it just made.
    # When it aborts, the post-route repair's DEF carries an unrouted net and its
    # re-extraction does not describe a complete route, so every number
    # measured on it is provisional. The runner already declines to use those
    # parasitics; this makes the abort VISIBLE in the audit rather than only in
    # a note. It does not block: the post-route repair artefacts are not the shipped ones, so
    # a failed post-route repair reroute damages nothing — it just did not deliver.
    if isinstance(_log_rec, dict) and _log_rec.get("reroute_failed"):
        findings.append(Finding(
            "WARNING", "REPAIR_REROUTE_INCOMPLETE",
            "the post-route repair's own reroute aborted — the repair it made was never "
            "realized as routing, so the post-route repair netlist/DEF beside this record "
            "is not a complete implementation",
            f"after parasitics: {data.get('repair_after_parasitics')!r}"))

    # The question this audit never asked: DID THE post-route repair HELP?
    # `changes`, `re_verified` and `affected_steps` are all structural — a post-route repair
    # that measurably made timing WORSE satisfies every one of them and passed.
    # A post-route repair is a REPAIR step, so "it ran and was re-verified" and "it improved
    # the design" are different questions, and only the first was being asked.
    #
    # Keyed on the record's own measured delta, so this fires ONLY when the
    # runner itself measured a regression; a post-route repair that gained slack, or one
    # whose before/after was never measured, is untouched.
    #
    # #766 — AND ONLY WHEN THE DELTA IS A DELTA. `repair_before` is measured on
    # the shipped post-route design; if the post-route repair started from a DIFFERENT design
    # (the pre-route post_hold.def) or the "after" was measured on the BASE
    # route's parasitics, the subtraction compares two implementations and its
    # sign says nothing about the repair. The runner records that judgement as
    # `repair_delta_comparable`; a record that does not carry the field is treated
    # exactly as before (this cannot silence an existing finding by omission).
    _delta = data.get("repair_setup_delta_ns")
    _comparable = data.get("repair_delta_comparable")
    _negative = isinstance(_delta, (int, float)) and _delta < -1e-9
    _d = (f" (setup {_delta:+.3f} ns)"
          if isinstance(_delta, (int, float)) else "")
    if _comparable is False and (_negative or data.get("repair_regressed")):
        findings.append(Finding(
            "WARNING", "REPAIR_DELTA_NOT_COMPARABLE",
            "the recorded setup delta" + _d + " is NOT a before/after of one "
            "design — " + str(data.get("repair_delta_comparable_reason")
                              or "the runner recorded the two ends as "
                                 "incomparable") +
            "; it is reported, and it is NOT charged to the post-route repair as a regression"))
    elif data.get("repair_regressed") or _negative:
        findings.append(Finding(
            "ERROR", "REPAIR_REGRESSED",
            "the post-route repair made timing measurably WORSE" + _d
            + " — a repair that regresses the design must not be recorded as "
              "applied; the pre-post-route repair artefacts are the better ones"))
    stats["repair_setup_delta_ns"] = _delta
    stats["repair_delta_comparable"] = _comparable

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "postroute_timing_repair_audit",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "repair_needed": stats["repair_needed"],
            "changes_count": stats["changes_count"],
            "re_verified": stats["re_verified"],
            "trigger_decision_read": stats.get("trigger_decision_read", False),
            "trigger_decision_repair_needed":
                stats.get("trigger_decision_repair_needed"),
            "trigger_decision_action": stats.get("trigger_decision_action"),
            # #766 — the two questions a repair step must answer beside "did it
            # run": could it SEE the violation, and is its delta a delta.
            "repair_blind_to_violation": stats.get("repair_blind_to_violation"),
            "repair_delta_comparable": stats.get("repair_delta_comparable"),
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Audit post-route repair log completeness")
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
