#!/usr/bin/env python3
"""ppa_feasibility_check.py — the hard promotion gate, as a flow-callable gate.

WHAT IT ANSWERS
===============
"May these candidates be promoted?" -- and nothing else. It does not rank them,
does not score them, and has no tunable margin. The adjudication lives in
`_ppa/feasibility.py`; this file is the CLI shell, the artefact writer and the
exit code, so that the rule and the plumbing can be reviewed apart.

EXIT CODES (docs/PPA_INTERFACES.md 1)
=====================================
    0  every candidate FEASIBLE
    1  at least one candidate INFEASIBLE and none UNDETERMINED
       -- a finding about the DESIGN: a real, measured violation
    2  at least one candidate could not be adjudicated, or the input could not
       be read. Printed with a [CANNOT CHECK] marker on stderr.
    3  bad invocation

2 OUTRANKS 1 DELIBERATELY. rc=1 asserts a complete finding about silicon, and a
run that could not see all of its evidence has no standing to make one. Nothing
is hidden by that choice: every per-candidate verdict is in the JSON and every
INFEASIBLE finding is printed regardless of which code is returned.

THE VACUOUS CASE IS THE ONE THAT MATTERS
=========================================
No input file, an unreadable file, an empty candidate list, or a candidate set
whose contract declares no required views all exit 2 with a marker. They do NOT
exit 0. A gate that reports clean when it never opened its input is a gate that
cannot fail, and this repository has shipped that twice.

USAGE
=====
    python3 ppa_feasibility_check.py --candidates candidates.json
                                     [--contract contract.json]
                                     [--json out.json] [--no-waivers]
    python3 ppa_feasibility_check.py --corpus DIR [--contract contract.json]
                                     [--corpus-may-be-absent]

CORPUS MODE
===========
`--candidates` names ONE document, so a candidate set filed anywhere the caller
did not name was never adjudicated. `--corpus DIR` adjudicates every candidate
set under DIR, resolved through `_corpus_location` -- the same seam
`ppa_head_to_head_check` uses, so both follow `$VIBE_IC_BENCHMARK_DATA` to a
cloned corpus.

Candidate sets are selected by SHAPE, not by filename: a mapping carrying a
`candidates` list. The two documents this lane PRODUCES -- `vibeic.ppa.
feasibility.v1` and `vibeic.ppa.pareto_frontier.v1` -- also carry a `candidates`
key and are excluded by their declared schema, because adjudicating a verdict
document as if it were an input would report on the gate's own output.

AN EMPTY CORPUS IS rc=2 WITH THE ROOT NAMED. It is the same refusal an empty
candidate list already gets, one level up: "every candidate is feasible" over
nothing is the empty-tree lie, and this gate exists to refuse it.

TWO CANDIDATE ENTRIES CLAIMING ONE `candidate_id` ARE A CONFLICT. Both paths and
both digests are named and the run REFUSES; it does not take the first match,
which would decide a promotion on directory order.

`--candidates` together with `--corpus` is rc=3, a bad invocation. `--contract`
is NOT an exact record under test -- it is the policy the whole corpus is
adjudicated against -- so it composes with `--corpus`.

`--candidates` is a document with a `candidates` list; each entry has a
`candidate_id`, a `metrics` list of `vibeic.ppa.metric.v1` records, and an
optional `waivers` list. `--contract` supplies `required_views`, `limits` and
`allow_waivers`; when it is omitted those are read from the candidates document
itself, which is convenient for a single-run check and is why the contract lane
owns the authoritative form.

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
from _ppa import canonical_json as cj  # noqa: E402
from _ppa import feasibility as feas  # noqa: E402
from _ppa import pareto as par  # noqa: E402

MARK_CANNOT = "[CANNOT CHECK]"
MARK_REFUSE = "[REFUSE]"


def _load(path: Optional[str], what: str) -> Any:
    """Read a JSON document, or say precisely which of the two failures it was.

    "the file is not there", "the file is not JSON" and "the file held an empty
    object" are three different facts and this returns three different reasons.
    A single False for all of them is how a missing input becomes a clean bill
    of health.
    """
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


def _report(results: List[feas.FeasibilityResult], rc: int,
            policy: feas.FeasibilityPolicy,
            sources: Mapping[str, Any]) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "schema": feas.FEASIBILITY_SCHEMA,
        "verdict": {feas.RC_PASS: "FEASIBLE",
                    feas.RC_FAIL: "INFEASIBLE",
                    feas.RC_UNDETERMINED: "UNDETERMINED"}.get(rc, "UNDETERMINED"),
        "exit_code": rc,
        "policy": {
            "axes": [a.name for a in policy.axes],
            "required_views": [dict(v) for v in policy.required_views],
            "limits": {k: dict(v) for k, v in policy.limits.items()},
            "allow_waivers": policy.allow_waivers,
        },
        "sources": dict(sources),
        "candidates": [r.as_dict() for r in results],
    }
    doc["policy_digest"] = cj.digest_of(doc["policy"])
    return doc


def _emit(out: Optional[str], doc: Dict[str, Any]) -> None:
    if out:
        _atomic_artefact.write_json(out, doc, indent=2, sort_keys=True)


#: What this gate would have examined, for the NO_CORPUS / VACUOUS line.
_GATE = "PPA candidate sets"
_SCANNED = "published candidate set(s)"

#: Documents this lane PRODUCES. They carry a `candidates` key too, and reading
#: one as an input would adjudicate a verdict document rather than a run.
_OUTPUT_SCHEMAS = (feas.FEASIBILITY_SCHEMA, par.PARETO_SCHEMA)


def is_candidate_set(doc: Any) -> bool:
    """A corpus record for THIS gate, decided on the document, not its name."""
    return (isinstance(doc, Mapping)
            and isinstance(doc.get("candidates"), list)
            and doc.get("schema") not in _OUTPUT_SCHEMAS)


def check_corpus(named: pathlib.Path, contract: Optional[str],
                 no_waivers: bool, may_be_absent: bool = False,
                 json_out: Optional[str] = None) -> int:
    """Adjudicate every candidate set under `named`, aggregated by severity."""
    corpus, rc = corpus_seam.open_corpus(named, _GATE, _SCANNED, may_be_absent)
    if corpus is None:
        return rc
    scan = corpus_seam.collect(corpus, is_candidate_set)
    print(f"ppa_feasibility_check --corpus {corpus}: "
          f"{scan.denominator(_SCANNED)}")
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
        if no_waivers:
            argv.append("--no-waivers")
        rcs.append(main(argv))
    worst = corpus_seam.worst_rc(rcs + [conflict_rc, unread_rc])
    infeasible = sum(1 for r in rcs if r == feas.RC_FAIL)
    undet = sum(1 for r in rcs if r == feas.RC_UNDETERMINED)
    print(f"ppa_feasibility_check --corpus {corpus}: {len(rcs)} set(s), "
          f"{infeasible} infeasible, {undet} undetermined, "
          f"{len(rcs) - infeasible - undet} feasible, {len(conflicts)} "
          f"candidate_id conflict(s) -> rc={worst}")
    _emit(json_out, {"schema": feas.FEASIBILITY_SCHEMA, "mode": "corpus",
                     "corpus": str(corpus), "files_opened": scan.files,
                     "sets": [str(path) for path, _ in scan.records],
                     "unreadable": [{"path": str(p), "why": w}
                                    for p, w in scan.unreadable],
                     "candidate_id_conflicts": conflicts,
                     "candidate_id_copies": copies,
                     "exit_code": worst,
                     "verdict": {feas.RC_PASS: "FEASIBLE",
                                 feas.RC_FAIL: "INFEASIBLE"}.get(
                                     worst, "UNDETERMINED"),
                     "candidates": []})
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Hard promotion gate over the feasibility axes.")
    ap.add_argument("--candidates", default=None,
                    help="JSON document with a `candidates` list")
    ap.add_argument("--corpus", default=None, metavar="DIR",
                    help="adjudicate every candidate set under DIR; exits 2 "
                         "when the corpus carries none")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="this repository need not carry the published "
                         "corpus. Turns 'nothing anywhere' into a stated "
                         "NO_CORPUS that names its zero, and NEVER excuses a "
                         "$VIBE_IC_BENCHMARK_DATA that is set and unreadable.")
    ap.add_argument("--contract", default=None,
                    help="JSON contract supplying required_views / limits")
    ap.add_argument("--json", default=None, help="report artefact path")
    ap.add_argument("--no-waivers", action="store_true",
                    help="adjudicate as if no waiver had been granted")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        # argparse exits 2 on a usage error; the contract says a bad invocation
        # is 3, and 2 there would be indistinguishable from "not checked".
        return feas.RC_BAD_INVOCATION

    if args.corpus is not None:
        if args.candidates is not None:
            return corpus_seam.both_given("ppa_feasibility_check",
                                          "--candidates", "--corpus")
        return check_corpus(pathlib.Path(args.corpus).resolve(),
                            args.contract, args.no_waivers,
                            args.corpus_may_be_absent, args.json)
    if args.candidates is None:
        print(f"{MARK_REFUSE} give --candidates CANDIDATES.json or --corpus "
              f"DIR (rc=3, bad invocation)", file=sys.stderr)
        return feas.RC_BAD_INVOCATION

    cand_doc = _load(args.candidates, "candidates")
    if isinstance(cand_doc, Mapping) and "__error__" in cand_doc:
        print(f"{MARK_CANNOT} {cand_doc['__error__']}", file=sys.stderr)
        _emit(args.json, {"schema": feas.FEASIBILITY_SCHEMA,
                          "verdict": "UNDETERMINED",
                          "exit_code": feas.RC_UNDETERMINED,
                          "codes": ["FEAS_INPUT_UNREADABLE"],
                          "detail": cand_doc["__error__"],
                          "candidates": []})
        return feas.RC_UNDETERMINED

    contract_doc: Any = cand_doc
    if args.contract:
        contract_doc = _load(args.contract, "contract")
        if isinstance(contract_doc, Mapping) and "__error__" in contract_doc:
            print(f"{MARK_CANNOT} {contract_doc['__error__']}", file=sys.stderr)
            _emit(args.json, {"schema": feas.FEASIBILITY_SCHEMA,
                              "verdict": "UNDETERMINED",
                              "exit_code": feas.RC_UNDETERMINED,
                              "codes": ["FEAS_CONTRACT_UNREADABLE"],
                              "detail": contract_doc["__error__"],
                              "candidates": []})
            return feas.RC_UNDETERMINED

    if not isinstance(cand_doc, Mapping):
        print(f"{MARK_CANNOT} candidates document is not an object",
              file=sys.stderr)
        return feas.RC_UNDETERMINED

    candidates = cand_doc.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        # An EMPTY set is not a clean set. Nothing was adjudicated, so nothing
        # may be promoted, and saying PASS here is the empty-tree lie.
        print(f"{MARK_CANNOT} no candidates in {args.candidates}",
              file=sys.stderr)
        _emit(args.json, {"schema": feas.FEASIBILITY_SCHEMA,
                          "verdict": "UNDETERMINED",
                          "exit_code": feas.RC_UNDETERMINED,
                          "codes": ["FEAS_NO_CANDIDATES"],
                          "candidates": []})
        return feas.RC_UNDETERMINED

    policy = feas.policy_from_document(
        contract_doc if isinstance(contract_doc, Mapping) else {})
    if args.no_waivers:
        policy = feas.FeasibilityPolicy(policy.axes, policy.required_views,
                                        policy.limits, allow_waivers=False)

    results = feas.adjudicate_set(candidates, policy)
    rc = feas.set_exit_code(results)
    doc = _report(results, rc, policy,
                  {"candidates": args.candidates, "contract": args.contract})
    _emit(args.json, doc)

    # Print EVERY finding, whatever the exit code ends up being.
    for r in results:
        line = f"{r.candidate_id}: {r.verdict}"
        if r.verdict != feas.FEASIBLE:
            line += "  " + ",".join(r.codes)
        print(line)
    if rc == feas.RC_UNDETERMINED:
        print(f"{MARK_CANNOT} at least one candidate was not adjudicated; "
              f"this run makes no claim about it", file=sys.stderr)
    elif rc == feas.RC_FAIL:
        print(f"{MARK_REFUSE} at least one candidate carries a measured "
              f"violation and is not eligible for promotion", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
