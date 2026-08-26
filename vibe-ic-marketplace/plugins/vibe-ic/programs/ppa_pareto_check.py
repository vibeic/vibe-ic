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

CORPUS MODE
===========
    python3 ppa_pareto_check.py --corpus DIR [--contract contract.json]
                                [--corpus-may-be-absent]

`--candidates` names ONE document, so a candidate set filed anywhere the caller
did not name never had its frontier recomputed. `--corpus DIR` recomputes the
frontier for every candidate set under DIR, resolved through
`_corpus_location` -- the same seam `ppa_head_to_head_check` uses, so both
follow `$VIBE_IC_BENCHMARK_DATA` to a cloned corpus.

Candidate sets are selected by SHAPE, not by filename: a mapping carrying a
`candidates` list, excluding this lane's own output schemas (`vibeic.ppa.
feasibility.v1`, `vibeic.ppa.pareto_frontier.v1`), which carry that key too.

AN EMPTY CORPUS IS rc=2 WITH THE ROOT NAMED. The whole subject of this gate is
a frontier nobody recomputed; a corpus mode that reported VALID over zero
candidate sets would be publishing exactly that.

TWO CANDIDATE ENTRIES CLAIMING ONE `candidate_id` ARE A CONFLICT -- both paths
and both digests are named and the run REFUSES. Taking the first match would
decide which implementation reaches a public frontier on directory order.

`--candidates` or `--frontier` together with `--corpus` is rc=3, a bad
invocation: each names one document, and `--frontier` in particular is the
record under test, which cannot be under test against N candidate sets at once.
`--contract` is the declared objective set the whole corpus is measured
against, so it composes with `--corpus`.

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
import _ppa_corpus as corpus_seam  # noqa: E402  one seam for all corpora
from _ppa import cli_exit  # noqa: E402  PPA_INTERFACES §1: one argv->rc seam
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


#: What this gate would have examined, for the NO_CORPUS / VACUOUS line.
_GATE = "PPA candidate sets (frontier)"
_SCANNED = "published candidate set(s)"

#: Documents this lane PRODUCES; they carry a `candidates` key too.
_OUTPUT_SCHEMAS = (feas.FEASIBILITY_SCHEMA, par.PARETO_SCHEMA)


def is_candidate_set(doc: Any) -> bool:
    """A corpus record for THIS gate, decided on the document, not its name."""
    return (isinstance(doc, Mapping)
            and isinstance(doc.get("candidates"), list)
            and doc.get("schema") not in _OUTPUT_SCHEMAS)


def check_corpus(named: pathlib.Path, contract: Optional[str],
                 may_be_absent: bool = False,
                 json_out: Optional[str] = None) -> int:
    """Recompute the frontier for every candidate set under `named`."""
    corpus, rc = corpus_seam.open_corpus(named, _GATE, _SCANNED, may_be_absent)
    if corpus is None:
        return rc
    scan = corpus_seam.collect(corpus, is_candidate_set)
    print(f"ppa_pareto_check --corpus {corpus}: {scan.denominator(_SCANNED)}")
    unread_rc = corpus_seam.report_unreadable(_GATE, scan)
    if not scan.records:
        return corpus_seam.worst_rc(
            [corpus_seam.vacuous(_GATE, corpus, _SCANNED, scan), unread_rc])

    rows: List[Any] = []
    for path, doc in scan.records:
        for cand in doc.get("candidates") or []:
            if isinstance(cand, Mapping) and cand.get("candidate_id"):
                rows.append((path, str(cand["candidate_id"]), cand))
    conflicts, copies = corpus_seam.identity_conflicts(
        rows, _GATE, "candidate_id")
    conflict_rc = corpus_seam.print_conflicts(_GATE, conflicts, copies)

    rcs = []
    for path, _ in scan.records:
        argv = ["--candidates", str(path)]
        if contract:
            argv += ["--contract", contract]
        rcs.append(main(argv))
    worst = corpus_seam.worst_rc(rcs + [conflict_rc, unread_rc])
    refused = sum(1 for r in rcs if r == feas.RC_FAIL)
    undet = sum(1 for r in rcs if r == feas.RC_UNDETERMINED)
    print(f"ppa_pareto_check --corpus {corpus}: {len(rcs)} set(s), "
          f"{refused} refused, {undet} undetermined, "
          f"{len(rcs) - refused - undet} valid, {len(conflicts)} "
          f"candidate_id conflict(s) -> rc={worst}")
    if json_out:
        _atomic_artefact.write_json(json_out, {
            "schema": par.PARETO_SCHEMA, "mode": "corpus",
            "corpus": str(corpus), "files_opened": scan.files,
            "sets": [str(path) for path, _ in scan.records],
            "unreadable": [{"path": str(p), "why": w}
                           for p, w in scan.unreadable],
            "candidate_id_conflicts": conflicts,
            "candidate_id_copies": copies,
            "exit_code": worst,
            "verdict": {feas.RC_PASS: "VALID", feas.RC_FAIL: "REFUSED"}.get(
                worst, "UNDETERMINED"),
            "frontier": [],
        }, indent=2, sort_keys=True)
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Recompute a Pareto frontier and refuse a published lie.")
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--corpus", default=None, metavar="DIR",
                    help="recompute the frontier for every candidate set "
                         "under DIR; exits 2 when the corpus carries none")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="this repository need not carry the published "
                         "corpus. Turns 'nothing anywhere' into a stated "
                         "NO_CORPUS that names its zero, and NEVER excuses a "
                         "$VIBE_IC_BENCHMARK_DATA that is set and unreadable.")
    ap.add_argument("--contract", default=None,
                    help="declares `objectives` (and required_views / limits)")
    ap.add_argument("--frontier", default=None,
                    help="the published frontier document under test")
    ap.add_argument("--json", default=None, help="report artefact path")
    args, rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        # argparse exited on its own. `parse_or_refuse` reads exc.code rather
        # than catching the type: `--help` is SystemExit(0) and stays rc=0
        # (argparse already printed the usage text), while a usage error is
        # SystemExit(2) and becomes rc=3. Catching SystemExit bare -- which is
        # what stood here -- turned asking this program for its flags into a
        # BAD INVOCATION. PPA_INTERFACES §1.
        return rc

    if args.corpus is not None:
        if args.candidates is not None or args.frontier is not None:
            return corpus_seam.both_given("ppa_pareto_check",
                                          "--candidates/--frontier",
                                          "--corpus")
        return check_corpus(pathlib.Path(args.corpus).resolve(),
                            args.contract, args.corpus_may_be_absent,
                            args.json)
    if args.candidates is None:
        print(f"{MARK_REFUSE} give --candidates CANDIDATES.json or --corpus "
              f"DIR (rc=3, bad invocation)", file=sys.stderr)
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
        # NAME WHAT WAS READ AND WHAT IS ABSENT.
        # This refusal is CORRECT and stays rc 2: with no declared objective
        # there is no trade-off, and deriving one here so the gate could then
        # check a frontier against its own recomputation is a manufactured
        # pass. But it used to be one sentence -- "the contract declares no
        # objective" -- naming no document, no key and no flag, over a
        # candidates set it had already opened and counted. An rc 2 with no
        # named missing input is indistinguishable from an rc 2 over a file
        # that was never there, and only one of those is fixed by looking
        # somewhere else.
        n_metrics = sum(len(c.get("metrics") or [])
                        for c in candidates if isinstance(c, Mapping))
        declared_in = args.contract or args.candidates
        return _undetermined(
            args.json, par.P_NO_OBJECTIVES,
            f"no objective is declared, so there is no trade-off to compute a "
            f"frontier over. READ: {args.candidates} -- {len(candidates)} "
            f"candidate(s), {n_metrics} metric record(s); the candidate half of "
            f"this measurement is present. MISSING ARTEFACT (1): an "
            f"`objectives` list of [{{key, metric, sense, scope}}] rows, read "
            f"from {declared_in} and absent there. MISSING ARTEFACT (2): a "
            f"PUBLISHED frontier for this gate to be under test against -- none "
            f"was supplied with --frontier. Both are needed: with only (1) this "
            f"gate would recompute a frontier and then check it against itself.")

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
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - the guard, not the path
        # PPA_INTERFACES §1: 3 is INTERNAL ERROR. Letting a traceback propagate
        # exits 1, which is reserved for a FINDING about the design -- so a
        # crash would reach the roll-up as a verdict nothing reached.
        #
        # NEWLY LOAD-BEARING. While this gate took an exact path a crash was a
        # local accident; with `--corpus` it sweeps a whole campaign, so one
        # badly shaped document decides the entire row. The same guard
        # ppa_contract_check has carried from the start.
        print(f"{MARK_REFUSE} ppa_pareto_check: internal error "
              f"{type(exc).__name__}: {exc}. Nothing was decided. rc=3 "
              f"(NOT a finding about any design).", file=sys.stderr)
        sys.exit(3)
