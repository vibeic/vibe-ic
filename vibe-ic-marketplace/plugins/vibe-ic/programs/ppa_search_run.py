#!/usr/bin/env python3
"""ppa_search_run.py — build a PPA search manifest, and audit one.

Spec §11 (Search Layer), §11.1, §11.2, §11.6. Contract: `docs/PPA_INTERFACES.md`.
Library: `_ppa/search.py`. This file is the CLI and nothing else -- every rule
it applies lives in the library, so a second front end cannot disagree with it.

TWO MODES, AND THE SECOND ONE IS THE GATE
=========================================
    build    a search space (+ optionally the trials that were observed)
             becomes a manifest: every candidate, every budget dimension, and
             the comparable set with a named reason for each exclusion.

    --verify an existing manifest is audited for the ways a search report is
             dishonest: a truncated ledger, a frontier point that is not
             eligible, a frontier mixing fidelity stages, an ELIGIBLE verdict
             built from a partial feasibility vector, a tuner iteration counter
             recorded as flow progress, CPU-hours published without saying how
             many trials came from cache.

`--verify` is the half that discriminates. A generator can only be wrong about
its own run; the audit applies to a manifest anyone published, which is the
case worth checking.

EXIT CODES (PPA_INTERFACES §1)
==============================
    0  a manifest was produced / the audited manifest is self-consistent
    1  REFUSED -- a finding: the manifest does not describe the run it claims,
       or the budget was declared in a way that is not a budget
    2  UNDETERMINED -- the input could not be read, so nothing was checked.
       Prints `[CANNOT CHECK]`. This is NOT rc=1: "I could not look" and "I
       looked and it is wrong" must never share a verdict, and rc=1 in this
       family means a finding about a real design.
    3  BAD INVOCATION -- never a design FAIL.

BUDGET = 1 IS A FIRST-CLASS RUN
===============================
No flag is required to get a bundle. `--max-trials` defaults to 1 and a
one-trial manifest is complete: it publishes its single candidate, states that
the budget bought one point, and is auditable by the same clauses as a
fifty-trial one. Nothing here needs fifty runs before it can say anything.

chip-AGNOSTIC: no IC, vendor, SKU, process or PDK appears in this file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _ppa import canonical_json as cj  # noqa: E402
from _ppa import search as S  # noqa: E402

PROGRAM = "ppa_search_run"

RC_PASS = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

MARK_CANNOT_CHECK = "[CANNOT CHECK]"
MARK_REFUSE = "[REFUSE]"


# ---------------------------------------------------------------------------
# reading inputs -- "absent" and "unreadable" are the same verdict here (rc=2)
# and BOTH are different from "read it and it was empty"
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """(obj, reason-it-could-not-be-read). Exactly one of the two is None.

    An empty file is a READ that produced no document -- reported with its own
    reason rather than as an empty object, because an empty object would flow
    on into the manifest and be published as a space with no levers.
    """
    if not path.exists():
        return None, f"{path} does not exist"
    if path.is_dir():
        return None, f"{path} is a directory, not a JSON document"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path} could not be read: {exc}"
    if not raw.strip():
        return None, f"{path} is empty: it carries no document to check"
    try:
        return json.loads(raw), None
    except (ValueError, UnicodeDecodeError) as exc:
        return None, f"{path} is not valid JSON: {exc}"


def _parse_values(specs: List[str]) -> Tuple[Dict[str, List[str]], List[str]]:
    """`--values lever=a,b,c` -> {lever: [a,b,c]}, plus malformed entries."""
    out: Dict[str, List[str]] = {}
    bad: List[str] = []
    for spec in specs:
        if "=" not in spec:
            bad.append(spec)
            continue
        lever, _, rhs = spec.partition("=")
        lever = lever.strip()
        vals = [v.strip() for v in rhs.split(",") if v.strip()]
        if not lever or not vals:
            bad.append(spec)
            continue
        out[lever] = vals
    return out, bad


def _load_trials(obj: Any) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Observed trial outcomes, keyed by the knob set they belong to.

    The trials file is a list of `{"knobs": {...}, "state": ..., ...}`. Keyed
    by the canonical form of `knobs` rather than by index, so a trials file
    written in a different order than the proposal still lands on the right
    candidate -- an index join would silently attach one trial's numbers to
    another candidate's knobs.
    """
    if not isinstance(obj, list):
        return {}, ["the trials document is not a list"]
    by_knobs: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    for i, t in enumerate(obj):
        if not isinstance(t, dict) or not isinstance(t.get("knobs"), dict):
            problems.append(f"trials[{i}] has no `knobs` object")
            continue
        by_knobs[cj.dumps(t["knobs"])] = t
    return by_knobs, problems


def _apply_trial(cand: S.Candidate, trial: Dict[str, Any]) -> List[str]:
    """Fold one observed outcome into a candidate. Returns refusals.

    `set_completed_stage` is called rather than assigned, so a trials file that
    carries a Ray Tune `step` where a stage belongs is REFUSED here at the
    boundary instead of being written into a manifest.
    """
    problems: List[str] = []
    state = trial.get("state", S.ST_COMPLETED)
    if state not in S.ALL_STATES:
        problems.append(f"unknown state {state!r} for knobs {cand.knobs}")
        return problems
    cand.state = state
    try:
        cand.set_completed_stage(trial.get("completed_stage"))
    except (TypeError, ValueError) as exc:
        problems.append(str(exc))
    metrics = trial.get("metrics")
    cand.metrics = list(metrics) if isinstance(metrics, list) else []
    cost = trial.get("cost") if isinstance(trial.get("cost"), dict) else {}
    cand.cpu_seconds = cost.get("cpu_seconds")
    cand.wall_seconds = cost.get("wall_seconds")
    cand.peak_rss_mb = cost.get("peak_rss_mb")
    cand.cache_hit = bool(trial.get("cache_hit", False))
    if trial.get("note"):
        cand.note = (cand.note + " " if cand.note else "") + str(trial["note"])
    return problems


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build(space_path: Path, trials_path: Optional[Path], budget: S.Budget,
          explicit: Dict[str, List[str]], frontier_stage: Optional[str],
          ) -> Tuple[int, Dict[str, Any], List[str]]:
    """(rc, manifest_or_report, human lines)."""
    lines: List[str] = []

    problems = budget.problems()
    if problems:
        lines.append(f"{MARK_REFUSE} the declared budget is not a budget:")
        lines.extend(f"  - {p}" for p in problems)
        return RC_REFUSED, {"program": PROGRAM, "budget_problems": problems}, \
            lines

    space, why = _read_json(space_path)
    if why is not None:
        lines.append(f"{MARK_CANNOT_CHECK} no search space was read: {why}")
        lines.append("  Nothing was searched and nothing is claimed. This is "
                     "UNDETERMINED (rc=2), not a finding about any design.")
        return RC_UNDETERMINED, {"program": PROGRAM, "undetermined": why}, lines
    if not isinstance(space, dict):
        lines.append(f"{MARK_CANNOT_CHECK} {space_path} does not hold a search "
                     "space object")
        return RC_UNDETERMINED, {"program": PROGRAM,
                                 "undetermined": "space is not an object"}, \
            lines

    space_digest = cj.digest_of(space)
    values, lever_notes = S.values_from_space(space, explicit)

    trials: Dict[str, Dict[str, Any]] = {}
    if trials_path is not None:
        obj, why = _read_json(trials_path)
        if why is not None:
            lines.append(f"{MARK_CANNOT_CHECK} --trials was given but no trial "
                         f"record was read: {why}")
            lines.append("  A run whose observed trials could not be read must "
                         "not publish a manifest that looks like a plan; that "
                         "would report zero measured trials as a completed "
                         "search.")
            return RC_UNDETERMINED, {"program": PROGRAM,
                                     "undetermined": why}, lines
        trials, tprobs = _load_trials(obj)
        if tprobs:
            lines.append(f"{MARK_REFUSE} the trials document is malformed:")
            lines.extend(f"  - {p}" for p in tprobs)
            return RC_REFUSED, {"program": PROGRAM, "trial_problems": tprobs}, \
                lines

    proposed = S.propose(values, budget, space_digest)
    ledger = S.Ledger(budget, space_digest)
    ledger.admit(proposed)

    refusals: List[str] = []
    for cand in ledger.candidates:
        if cand.state in (S.ST_DEDUPLICATED, S.ST_BUDGET_EXHAUSTED):
            continue
        key = cj.dumps(cand.knobs)
        if key in trials:
            refusals.extend(_apply_trial(cand, trials[key]))
        elif trials_path is not None:
            cand.state = S.ST_BUDGET_EXHAUSTED
            cand.note = (cand.note + " " if cand.note else "") + \
                "no observed trial for this point"
        else:
            # No trials file: this is a PLAN. Every affordable point stays
            # PROPOSED, and the audit will say so -- a plan is not a result and
            # must not be able to masquerade as one.
            cand.state = S.ST_PROPOSED

    if refusals:
        lines.append(f"{MARK_REFUSE} the observed trials cannot be recorded "
                     "honestly:")
        lines.extend(f"  - {r}" for r in refusals)
        return RC_REFUSED, {"program": PROGRAM, "refusals": refusals}, lines

    ledger.evaluate_feasibility(None)  # the stub: UNDETERMINED, never ELIGIBLE
    man = S.build_manifest(ledger, space_digest, lever_notes, frontier_stage,
                           toolchain={"feasibility_source": "STUB",
                                      "feasibility_note":
                                          S.stub_feasibility(
                                              S.Candidate({})).reason},
                           is_plan=trials_path is None)

    n_full = ledger.full_pnr_trials()
    if n_full > budget.max_full_pnr_trials:
        lines.append(
            f"{MARK_REFUSE} {n_full} trials reached full place-and-route but "
            f"max_full_pnr_trials was declared as "
            f"{budget.max_full_pnr_trials}. The published budget does not "
            "describe the run that happened.")
        return RC_REFUSED, man, lines

    lines.append(man["what_the_budget_bought"]["sentence"])
    for note in lever_notes:
        lines.append(f"  lever {note['lever']}: {note['status']} — "
                     f"{note['reason']}")
    if trials_path is None:
        lines.append("  NOTE: no --trials given, so this is a PLAN. Its "
                     "candidates are PROPOSED, not results.")
    return RC_PASS, man, lines


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
def verify(manifest_path: Path) -> Tuple[int, Dict[str, Any], List[str]]:
    lines: List[str] = []
    man, why = _read_json(manifest_path)
    if why is not None:
        lines.append(f"{MARK_CANNOT_CHECK} the manifest was not read: {why}")
        lines.append("  No clause was evaluated. Reporting this as clean would "
                     "be a check that cannot fail.")
        return RC_UNDETERMINED, {"program": PROGRAM, "undetermined": why}, lines
    if not isinstance(man, dict):
        lines.append(f"{MARK_CANNOT_CHECK} {manifest_path} does not hold a "
                     "manifest object")
        return RC_UNDETERMINED, {"program": PROGRAM,
                                 "undetermined": "not an object"}, lines

    findings = S.audit_manifest(man)
    report = {"program": PROGRAM, "manifest": str(manifest_path),
              "findings": findings, "finding_count": len(findings),
              "clauses_evaluated": True}
    if findings:
        lines.append(f"{MARK_REFUSE} {len(findings)} finding(s): this manifest "
                     "does not describe the run it claims.")
        for f in findings:
            lines.append(f"  {f['code']}: {f['detail']}")
        return RC_REFUSED, report, lines
    bought = man.get("what_the_budget_bought") or {}
    lines.append("manifest is self-consistent: every trial published, every "
                 "budget dimension declared, every frontier point eligible and "
                 "at one scope.")
    if bought.get("sentence"):
        lines.append(f"  {bought['sentence']}")
    return RC_PASS, report, lines


# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ppa_search_run.py",
        description="Build a PPA search manifest, or audit one.")
    ap.add_argument("space", nargs="?",
                    help="path to a search-space JSON "
                         "(crosslayer_search_space.py output shape)")
    ap.add_argument("--trials", default=None, metavar="PATH",
                    help="observed trial outcomes; without it the manifest is "
                         "a PLAN and says so")
    ap.add_argument("--verify", default=None, metavar="MANIFEST",
                    help="audit an existing manifest instead of building one")
    ap.add_argument("--values", action="append", default=[],
                    metavar="LEVER=a,b,c",
                    help="explicit values for a lever whose declared domain is "
                         "prose; repeatable")
    ap.add_argument("--frontier-stage", default=None,
                    help=f"fix the frontier scope; one of "
                         f"{list(S.FIDELITY_LADDER)}")
    ap.add_argument("--max-trials", type=int, default=1,
                    help="default 1 — a one-point frontier is a valid frontier")
    ap.add_argument("--max-full-pnr-trials", type=int, default=1)
    ap.add_argument("--max-cpu-hours", type=float, default=None)
    ap.add_argument("--max-wall-seconds", type=float, default=None)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--memory-limit-mb", type=int, default=None)
    ap.add_argument("--per-trial-timeout-s", type=float, default=None)
    ap.add_argument("--failed-trial-policy", default=S.FAILED_COUNTS,
                    choices=list(S.FAILED_TRIAL_POLICIES))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cache-policy", default=S.CACHE_IGNORE,
                    choices=list(S.CACHE_POLICIES))
    ap.add_argument("--json", default=None, help="write the JSON report here")
    args = ap.parse_args(argv)

    if args.verify and args.space:
        print("give a space to build OR --verify a manifest, not both",
              file=sys.stderr)
        return RC_BAD_INVOCATION
    if not args.verify and not args.space:
        print("give a search-space path, or --verify MANIFEST", file=sys.stderr)
        return RC_BAD_INVOCATION
    if args.frontier_stage is not None and \
            args.frontier_stage not in S.FIDELITY_LADDER:
        print(f"--frontier-stage {args.frontier_stage!r} is not on the ladder "
              f"{list(S.FIDELITY_LADDER)}", file=sys.stderr)
        return RC_BAD_INVOCATION

    explicit, bad = _parse_values(args.values)
    if bad:
        print(f"--values entries must be LEVER=a,b,c; malformed: {bad}",
              file=sys.stderr)
        return RC_BAD_INVOCATION

    if args.verify:
        rc, report, lines = verify(Path(args.verify))
    else:
        budget = S.Budget(
            max_trials=args.max_trials,
            max_full_pnr_trials=args.max_full_pnr_trials,
            max_cpu_hours=args.max_cpu_hours,
            max_wall_seconds=args.max_wall_seconds,
            concurrency=args.concurrency,
            memory_limit_mb=args.memory_limit_mb,
            per_trial_timeout_s=args.per_trial_timeout_s,
            failed_trial_policy=args.failed_trial_policy,
            seed=args.seed,
            cache_policy=args.cache_policy,
        )
        rc, report, lines = build(
            Path(args.space), Path(args.trials) if args.trials else None,
            budget, explicit, args.frontier_stage)

    stream = sys.stderr if rc in (RC_REFUSED, RC_UNDETERMINED) else sys.stdout
    for line in lines:
        print(line, file=stream)
    if args.json:
        atomic_write_text(Path(args.json),
                          json.dumps(report, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
