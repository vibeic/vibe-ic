#!/usr/bin/env python3
"""CLI: run Program-First diagnosis over a situation; hand off only on a waive.

The library is `_ppa/agent_router.py` and the reasoning lives there. This file
is the CLI contract from `docs/PPA_INTERFACES.md` 1 and nothing else, because a
verdict that is computed in an argument parser is a verdict nobody can unit-test.

THE EXIT CODES, AND WHY THE INTERESTING ONE IS 2
================================================
    0  the router routed: the program decided, or a LEGAL handoff was emitted
    1  REFUSED -- the situation asked for something policy forbids
    2  UNDETERMINED -- the evidence to diagnose was not there
    3  BAD INVOCATION

rc=1 is a claim about the design, so it is spent only on a real refusal: an
autonomy level that is not activated, a never-delegated question, a domain
outside the closed set, a handoff reason outside the closed set. A run that
could not READ its situation file exits 2 and prints `[CANNOT CHECK]`, because
this repository has shipped gates that refused with a bare `SystemExit(...)` --
which exits 1 -- and so reported a hard finding from a run that never opened its
input.

AND WHY A HANDOFF IS rc=0
=========================
A handoff is the router working, not the design failing. Making it non-zero
would put a flow gate in the position of treating "we asked for an explanation"
as a silicon finding, and would create pressure to avoid legitimate handoffs to
keep a gate green. The verdict about the DESIGN is `outcome`, printed and in
the JSON; the exit code is about whether the ROUTING was valid.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _ppa import agent_policy, agent_router  # noqa: E402

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

MARKER_REFUSE = "[REFUSE]"
MARKER_CANNOT_CHECK = "[CANNOT CHECK]"


def _load(path: Path, what: str) -> Dict[str, Any]:
    """Read a JSON document, or raise the UNDETERMINED-shaped error.

    Every failure to obtain the input is `SituationIncomplete`, which the
    caller maps to rc=2. None of them is rc=1: not being able to look is never
    a finding.
    """
    if not path.exists():
        raise agent_router.SituationIncomplete(
            f"{what} {path} does not exist")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise agent_router.SituationIncomplete(
            f"{what} {path} could not be read: {exc}") from None
    if not raw.strip():
        # An empty file is a different fact from a missing one and both are
        # rc=2, but the message must say which, or a reader debugging this
        # cannot tell whether the producer ran.
        raise agent_router.SituationIncomplete(
            f"{what} {path} is empty (0 non-whitespace bytes); the producer "
            f"may have died mid-write")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise agent_router.SituationIncomplete(
            f"{what} {path} is not valid JSON: {exc}") from None
    if not isinstance(doc, dict):
        raise agent_router.SituationIncomplete(
            f"{what} {path} is not a JSON object")
    return doc


def format_report(report: Dict[str, Any]) -> str:
    out: List[str] = []
    outcome = report["outcome"]
    out.append(f"PPA diagnostic router: {outcome} (rule {report['rule']})")
    out.append(f"  question    : {report['question']}")
    doms = report["domains"]
    out.append(f"  violated    : {doms['violated'] or '-'}")
    out.append(f"  clean       : {doms['clean'] or '-'}")
    out.append(f"  undetermined: {doms['undetermined'] or '-'}")
    out.append(f"  root cause  : {report['root_cause']}")
    if report.get("remedy"):
        out.append(f"  remedy      : {report['remedy']}")
    if report["reached_agent"]:
        h = report["handoff"]
        out.append(f"  HANDOFF     : reason={h['reason']} "
                   f"explain_only={h['explain_only']} "
                   f"level={h['autonomy_level']}")
        out.append(f"  handoff sha : {h['handoff_sha256']}")
    else:
        out.append("  HANDOFF     : none -- the program decided "
                   "(invariant 12: the program has the first right to decide)")
    for note in report.get("notes", []):
        out.append(f"  note        : {note}")
    return "\n".join(out)


def run(situation_path: Path,
        policy_path: Optional[Path],
        handoff_out: Optional[Path]) -> tuple:
    """Returns (rc, report_dict). Raises nothing the caller must translate."""
    policy = None
    if policy_path is not None:
        policy = _load(policy_path, "policy")

    situation = _load(situation_path, "situation")
    diag = agent_router.diagnose(situation, policy)
    report = diag.as_report()

    if handoff_out is not None and diag.handoff is not None:
        atomic_write_text(
            handoff_out,
            json.dumps(diag.handoff, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        report["handoff_written_to"] = str(handoff_out)

    return diag.rc, report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Program-First PPA diagnosis. Emits an AI handoff only "
                    "when the deterministic rules explicitly waive.")
    ap.add_argument("situation", nargs="?",
                    help="path to a vibeic.ppa.situation.v1 JSON document")
    ap.add_argument("--policy", default=None, metavar="PATH",
                    help="agent policy document; the default policy is the "
                         "most restrictive one this system can express")
    ap.add_argument("--handoff-out", default=None, metavar="PATH",
                    help="write the handoff document here when one is emitted")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="write the machine-readable report here")
    args = ap.parse_args(argv)

    if not args.situation:
        # Bad invocation is 3, never 2: the caller made a mistake, the evidence
        # is not the problem, and a flow that retries on 2 would loop forever.
        print("give a situation document path", file=sys.stderr)
        return RC_BAD_INVOCATION

    try:
        rc, report = run(Path(args.situation),
                         Path(args.policy) if args.policy else None,
                         Path(args.handoff_out) if args.handoff_out else None)
    except agent_router.SituationIncomplete as exc:
        print(f"{MARKER_CANNOT_CHECK} {exc}", file=sys.stderr)
        report = {"schema": "vibeic.ppa.diagnosis.v1",
                  "outcome": "UNDETERMINED", "rc": RC_UNDETERMINED,
                  "marker": MARKER_CANNOT_CHECK, "detail": str(exc),
                  "reached_agent": False}
        if args.json:
            atomic_write_text(Path(args.json),
                              json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
        return RC_UNDETERMINED
    except (agent_router.RouterRefused, agent_policy.PolicyError) as exc:
        print(f"{MARKER_REFUSE} {exc}", file=sys.stderr)
        report = {"schema": "vibeic.ppa.diagnosis.v1",
                  "outcome": "REFUSED", "rc": RC_REFUSED,
                  "marker": MARKER_REFUSE, "detail": str(exc),
                  "reached_agent": False}
        if args.json:
            atomic_write_text(Path(args.json),
                              json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
        return RC_REFUSED

    print(format_report(report))
    if args.json:
        atomic_write_text(Path(args.json),
                          json.dumps(report, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
