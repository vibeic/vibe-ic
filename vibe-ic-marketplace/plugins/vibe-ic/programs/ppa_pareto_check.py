#!/usr/bin/env python3
"""ppa_pareto_check.py — recompute the frontier and refuse a published lie.

WHAT IT ANSWERS
===============
Given the candidates, their feasibility verdicts and the declared objectives:
is the published `frontier.json` the frontier those inputs actually imply? It
recomputes the domination relation from the RAW triple and compares. It never
trusts the published `frontier` list while computing.

The four refusals it exists for:

    an INFEASIBLE candidate appears in the frontier
    a candidate nobody could compare is listed as a winner
    the published frontier disagrees with the recomputation
    the public document carries a collapsed scalar

The last is not pedantry. A single weighted score is a proxy for the property
and not the property, and it is the number that gets quoted -- so once it is in
a public artefact the trade-off it flattened stops being visible to anyone
downstream.

EXIT CODES (docs/PPA_INTERFACES.md 1)
=====================================
    0  the frontier is valid and recomputable
    1  REFUSED -- a finding: an ineligible or incomparable candidate was
       published as a winner, the frontier disagrees, or a scalar was collapsed
    2  UNDETERMINED -- a comparison could not be established (no declared
       objective scope, scope mismatch, missing or unprovenanced metric), or an
       input could not be read. Marked [CANNOT CHECK].
    3  bad invocation

2 outranks 1 for the same reason as in `ppa_feasibility_check.py`, and every
finding is printed whichever code is returned.

USAGE
=====
    python3 ppa_pareto_check.py --candidates candidates.json
                                --contract contract.json
                                [--frontier frontier.json]
                                [--json out.json]

Without `--frontier` the recomputed document is checked against its own
invariants and written to `--json`; that is the emit-and-verify mode. With
`--frontier` the published document is the thing under test.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _atomic_artefact  # noqa: E402
from _ppa import feasibility as feas  # noqa: E402
from _ppa import pareto as par  # noqa: E402

MARK_CANNOT = "[CANNOT CHECK]"
MARK_REFUSE = "[REFUSE]"


def _load(path: Optional[str], what: str) -> Any:
    if not path:
        return {"__error__": f"no {what} path given"}
    p = pathlib.Path(path)
    if not p.exists():
        return {"__error__": f"{what} not found: {p}"}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"__error__": f"{what} unreadable: {p}: {exc}"}
    if not text.strip():
        return {"__error__": f"{what} is empty: {p}"}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        return {"__error__": f"{what} is not JSON: {p}: {exc}"}


def _undetermined(out: Optional[str], code: str, detail: str) -> int:
    print(f"{MARK_CANNOT} {detail}", file=sys.stderr)
    if out:
        _atomic_artefact.write_json(out, {
            "schema": par.PARETO_SCHEMA, "verdict": "UNDETERMINED",
            "exit_code": feas.RC_UNDETERMINED,
            "findings": [{"code": code, "detail": detail}],
            "frontier": []}, indent=2, sort_keys=True)
    return feas.RC_UNDETERMINED


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Recompute a Pareto frontier and refuse a published lie.")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--contract", default=None,
                    help="declares `objectives` (and required_views / limits)")
    ap.add_argument("--frontier", default=None,
                    help="the published frontier document under test")
    ap.add_argument("--json", default=None, help="report artefact path")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return feas.RC_BAD_INVOCATION

    cand_doc = _load(args.candidates, "candidates")
    if isinstance(cand_doc, Mapping) and "__error__" in cand_doc:
        return _undetermined(args.json, "PARETO_INPUT_UNREADABLE",
                             cand_doc["__error__"])

    contract_doc: Any = cand_doc
    if args.contract:
        contract_doc = _load(args.contract, "contract")
        if isinstance(contract_doc, Mapping) and "__error__" in contract_doc:
            return _undetermined(args.json, "PARETO_CONTRACT_UNREADABLE",
                                 contract_doc["__error__"])

    if not isinstance(cand_doc, Mapping):
        return _undetermined(args.json, "PARETO_INPUT_UNREADABLE",
                             "candidates document is not an object")
    candidates = cand_doc.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return _undetermined(args.json, "PARETO_NO_CANDIDATES",
                             f"no candidates in {args.candidates}")

    objectives = par.objectives_from_document(
        contract_doc if isinstance(contract_doc, Mapping) else {})
    if not objectives:
        return _undetermined(args.json, par.P_NO_OBJECTIVES,
                             "the contract declares no objective, so there is "
                             "no trade-off to compute a frontier over")

    policy = feas.policy_from_document(
        contract_doc if isinstance(contract_doc, Mapping) else {})
    results = feas.adjudicate_set(candidates, policy)

    published: Mapping[str, Any]
    if args.frontier:
        pub = _load(args.frontier, "frontier")
        if isinstance(pub, Mapping) and "__error__" in pub:
            return _undetermined(args.json, "PARETO_FRONTIER_UNREADABLE",
                                 pub["__error__"])
        if not isinstance(pub, Mapping):
            return _undetermined(args.json, "PARETO_FRONTIER_UNREADABLE",
                                 "frontier document is not an object")
        published = pub
    else:
        published = par.build_frontier(candidates, results, objectives)

    verified = par.verify_frontier(published, candidates, results, objectives)
    findings: List[Dict[str, Any]] = list(verified["findings"])
    recomputed = verified["recomputed"] or {}
    empty = par.empty_frontier_finding(recomputed)
    if empty is not None:
        findings.append(empty)
    rc = par.frontier_exit_code(recomputed, findings)

    doc: Dict[str, Any] = dict(recomputed)
    doc["schema"] = par.PARETO_SCHEMA
    doc["exit_code"] = rc
    doc["verdict"] = {feas.RC_PASS: "VALID", feas.RC_FAIL: "REFUSED",
                      feas.RC_UNDETERMINED: "UNDETERMINED"}.get(rc,
                                                                "UNDETERMINED")
    doc["findings"] = findings
    doc["published_frontier"] = sorted(published.get("frontier") or [])
    if args.json:
        _atomic_artefact.write_json(args.json, doc, indent=2, sort_keys=True)

    print("objectives: " + ", ".join(f"{o.key}({o.sense})" for o in objectives))
    print("frontier: " + (", ".join(doc.get("frontier") or []) or "<empty>"))
    for row in doc.get("excluded_infeasible") or []:
        print(f"excluded {row['candidate_id']}: {row['feasibility']}")
    for row in doc.get("undetermined") or []:
        print(f"undetermined {row['candidate_id']}: {','.join(row['codes'])}")
    for f in findings:
        print(f"finding {f.get('code')}: "
              f"{ {k: v for k, v in f.items() if k != 'code'} }")

    if rc == feas.RC_UNDETERMINED:
        print(f"{MARK_CANNOT} at least one comparison could not be "
              f"established; this run names no winner", file=sys.stderr)
    elif rc == feas.RC_FAIL:
        print(f"{MARK_REFUSE} the published frontier does not follow from the "
              f"measured triple", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
