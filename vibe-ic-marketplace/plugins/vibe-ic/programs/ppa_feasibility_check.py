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
import dataclasses
import json
import pathlib
import sys
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _atomic_artefact  # noqa: E402
import _corpus_location as _corpus  # noqa: E402  one seam for every corpus
from _ppa import canonical_json as cj  # noqa: E402
from _ppa import feasibility as feas  # noqa: E402

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
            "required_views_by_axis": {
                k: [dict(v) for v in vs]
                for k, vs in sorted((policy.required_views_by_axis or {}).items())},
            # The views each axis was ACTUALLY asked for, resolved. The two
            # fields above are what the contract wrote; this is what the gate
            # used, and printing only the first would leave a reader deriving
            # the fallback by hand.
            "views_used_by_axis": {
                a.name: [dict(v) for v in feas.views_for(a.name, policy)]
                for a in policy.axes},
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


#: --corpus, and the reason it exists (vibe-ic#1241, 2026-08-22).
#:
#: This gate was wired at an EXACT path, `$ROOT/benchmark-data/ppa/candidates.json`,
#: in a directory that left this repository in v1.10.56. It exited 2 "candidates
#: not found" under an exemption declaring that "no run in this repository has
#: filed one yet". TWENTY-ONE are filed here, under
#: `ppa-crosslayer/records/trials/*/candidates.json`.
#:
#: The corpus is identified by DECLARATION and never by filename, for the same
#: reason as the contract and head-to-head corpora: a name-glob missed fifteen
#: real head-to-head records in this tree and refused two of the checker's own
#: reports as if they were records.
_CANDIDATES_SCHEMA = "vibeic.ppa.candidates.v1"
_SCANNED = "PPA candidate set(s)"
_GATE = "PPA promotion feasibility"


#: The filename is NOT how a candidate set is identified — it is only how an
#: UNREADABLE one is kept from disappearing. See `corpus_candidate_sets`.
_NAME_GLOB = "**/*candidates*.json"


def corpus_candidate_sets(corpus: pathlib.Path) -> List[pathlib.Path]:
    named = {x for x in corpus.glob(_NAME_GLOB) if x.is_file()}
    out: List[pathlib.Path] = []
    for path in sorted(x for x in corpus.glob("**/*.json") if x.is_file()):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # UNREADABLE IS NOT ABSENT — a file that claims by its NAME to be a
            # candidate set and cannot be parsed stays in the population and is
            # adjudicated UNDETERMINED out loud, rather than being dropped as
            # though it had never been filed.
            if path in named:
                out.append(path)
            continue
        if isinstance(doc, Mapping) and doc.get("schema") == _CANDIDATES_SCHEMA:
            out.append(path)
    return out


def check_corpus(named: pathlib.Path, contract: Optional[str],
                 no_waivers: bool) -> int:
    corpus, origin = _corpus.resolve(named, gate=_GATE, announce=True)
    if not corpus.is_dir():
        return _corpus.refuse(_GATE, named, corpus, origin, False, _SCANNED)
    paths = corpus_candidate_sets(corpus)
    scanned = sum(1 for x in corpus.glob("**/*.json") if x.is_file())
    print(f"ppa_feasibility_check --corpus {corpus}: {len(paths)} candidate "
          f"set(s) found in {scanned} JSON document(s) scanned")
    if not paths:
        print(f"{MARK_CANNOT} VACUOUS: {corpus} carries no document declaring "
              f"{_CANDIDATES_SCHEMA!r}, so no candidate was adjudicated. This "
              f"is NOT a pass. rc=2.", file=sys.stderr)
        return feas.RC_UNDETERMINED
    argv_common: List[str] = []
    if contract:
        argv_common += ["--contract", contract]
    if no_waivers:
        argv_common += ["--no-waivers"]
    rcs = [main(["--candidates", str(q)] + argv_common) for q in paths]
    # A REFUSAL OUTRANKS AN UNDETERMINED OUTRANKS A PASS. `max()` would let an
    # unadjudicated candidate set promote a refusal to "could not check", and
    # adding a candidate set must never SUBTRACT a refusal.
    refused = sum(1 for rc in rcs if rc == feas.RC_FAIL)
    undet = sum(1 for rc in rcs if rc == feas.RC_UNDETERMINED)
    worst = (feas.RC_FAIL if refused
             else feas.RC_UNDETERMINED if undet else feas.RC_PASS)
    print(f"ppa_feasibility_check --corpus {corpus}: {len(paths)} set(s), "
          f"{refused} infeasible, {undet} undetermined, "
          f"{len(paths) - refused - undet} feasible -> rc={worst}")
    if refused:
        print(f"REFUSED: {refused} of {len(paths)} candidate set(s) hold a "
              f"candidate that may not be promoted.", file=sys.stderr)
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Hard promotion gate over the feasibility axes.")
    ap.add_argument("--candidates",
                    help="JSON document with a `candidates` list")
    ap.add_argument("--corpus", metavar="DIR",
                    help="adjudicate every document declaring "
                         f"{_CANDIDATES_SCHEMA} under DIR; exits 2 when the "
                         "corpus is absent or carries none (vibe-ic#1241)")
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

    if bool(args.corpus) == bool(args.candidates):
        print(f"{MARK_CANNOT} give exactly one of --candidates or --corpus",
              file=sys.stderr)
        return feas.RC_BAD_INVOCATION
    if args.corpus:
        return check_corpus(pathlib.Path(args.corpus), args.contract,
                            args.no_waivers)

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
        # `replace` and not a positional rebuild: a positional constructor
        # silently reassigns every field when one is inserted, and this one
        # already dropped `limits` into `required_views_by_axis` the moment that
        # field was added. dataclasses.replace cannot make that mistake.
        policy = dataclasses.replace(policy, allow_waivers=False)

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
