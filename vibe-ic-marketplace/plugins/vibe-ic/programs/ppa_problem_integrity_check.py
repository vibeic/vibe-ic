#!/usr/bin/env python3
"""ppa_problem_integrity_check.py — were these two runs solving the same problem?

THE FAILURE THIS EXISTS TO CATCH
--------------------------------
A PPA head-to-head reports that the candidate is 12% smaller. It is. It is also
running at a different clock period, or against a different corner, or built
from a spec somebody edited between the two runs. The number is real; the
comparison is not, and nothing in the number itself says so.

A comparison is legitimate exactly when:

    problem         identical      the design, constraints, PDK, corners
    analysis        identical      how the measurement was taken
    toolchain       identical      the image and tool builds
    implementation  DIFFERENT      the one axis a PPA experiment may move

This program checks that sentence against two contracts and refuses anything
else. It is the reason the contract lane exists.

TWO INDEPENDENT DETECTORS, ON PURPOSE
-------------------------------------
A moved problem shows up twice: the `problem` identity digests differ, AND the
candidate's declared mutation list names something outside its allow-list. The
two were written not to share code, so one failing quietly cannot silence the
other. A candidate that moved the clock and declared nothing is caught by the
first; a candidate that declared a forbidden mutation whose artefacts happen to
hash the same is caught by the second.

AN IDENTICAL IMPLEMENTATION IS NOT A RESULT
-------------------------------------------
If the two arms' implementation identities MATCH, any difference between their
numbers is measurement noise, not an improvement. That is reported as
UNDETERMINED — which can never be mapped to PASS — and promoted to a refusal
with `--require-implementation-differs`.

chip-AGNOSTIC: it compares two JSON documents.

USAGE
-----
    ppa_problem_integrity_check.py --baseline A.json --candidate B.json
                                   [--json REPORT.json]
                                   [--require-implementation-differs]
    ppa_problem_integrity_check.py --corpus DIR [--corpus-may-be-absent]
                                   [--require-implementation-differs]

CORPUS MODE, AND WHY THE PAIRS ARE NOT GUESSED
----------------------------------------------
`--baseline`/`--candidate` name two EXACT documents, so a contract filed
anywhere the caller did not name was never checked against anything. `--corpus
DIR` reads every contract record under DIR through `_corpus_location` -- the
same seam `ppa_head_to_head_check` uses -- and GROUPS them by their `problem`
identity, because "were these two runs solving the same problem?" is answered by
that identity and by nothing else. Two contracts in one group are two arms of
one comparison, and every unordered pair in a group is compared.

Records are selected by their DECLARED SCHEMA, never by filename.

There is no baseline/candidate label in a corpus, so THERE IS NO ARM TO PICK.
The comparison itself is symmetric; the one asymmetric clause is the mutation
allow-list, which the exact mode applies to the `--candidate` side only. Corpus
mode applies it to BOTH arms of every pair rather than electing one, so no arm
escapes its own allow-list by being read first.

A GROUP OF ONE IS rc=2, NOT rc=0. One arm cannot be shown to be solving the
same problem as anything; the group and its single path are NAMED. An EMPTY
corpus is rc=2 with the corpus root named.

TWO CONTRACTS DECLARING THE SAME FULL `identities` ARE A CONFLICT when their
content differs -- two records for one identity, and taking the first match
would bury the disagreement. Both paths and both digests are named and the run
REFUSES. (The pair is still compared, so PPA-C-013 is reported too; nothing is
suppressed to make the conflict the only line.)

`--baseline` or `--candidate` together with `--corpus` is rc=3, a bad
invocation.

EXIT CODES
----------
    0  [PASS]          the two runs are comparable
    1  [REFUSE]        they are not: the problem, analysis or toolchain moved,
                       a mutation is outside the allow-list, or a contract does
                       not hash to itself
    2  [CANNOT CHECK]  a contract is absent/unreadable, or an identity needed
                       for the comparison is NOT_MEASURED on either side; in
                       corpus mode also an EMPTY corpus, a problem group with
                       only one arm, and a `*.json` nobody could parse
    3  bad invocation, including --baseline/--candidate with --corpus
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _ppa_corpus as corpus_seam  # noqa: E402  one seam for all corpora
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _ppa import canonical_json as cj  # noqa: E402
from _ppa import contract as C, identity as ident  # noqa: E402

#: The three that must MATCH for a comparison to mean anything.
_MUST_MATCH = ("problem", "analysis", "toolchain")

_WHY = {
    "problem": ("the two runs were built to different requirements, so "
                "whichever one won, won a different contest"),
    "analysis": ("the two numbers were taken under different measurement "
                 "conditions, so they are not the same metric"),
    "toolchain": ("the two runs used different tool builds, so the difference "
                  "may be the tools rather than the design"),
}


def compare_contracts(baseline: Mapping[str, Any],
                      candidate: Mapping[str, Any],
                      require_impl_differs: bool = False
                      ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    for label, doc in (("baseline", baseline), ("candidate", candidate)):
        if str(doc.get("schema", "")) != C.CONTRACT_SCHEMA:
            out.append(C.finding(
                "PPA-C-010", C.SEV_UNDETERMINED,
                f"the {label} document declares schema "
                f"{doc.get('schema')!r}, not {C.CONTRACT_SCHEMA!r}; nothing "
                f"has been established about it", arm=label))
            continue
        if doc.get("contract_digest") != C.contract_digest_of(doc):
            out.append(C.finding(
                "PPA-C-001", C.SEV_FAIL,
                f"the {label} contract does not hash to its own stated "
                f"digest — it was edited after it was built, so it describes "
                f"a document that no longer exists", arm=label))
    if any(f["code"] == "PPA-C-010" for f in out):
        return out

    b_ids = baseline.get("identities", {}) or {}
    c_ids = candidate.get("identities", {}) or {}

    for kind in _MUST_MATCH:
        left, right = b_ids.get(kind), c_ids.get(kind)
        if left is None or right is None:
            out.append(C.finding(
                "PPA-C-007", C.SEV_UNDETERMINED,
                f"identity {kind!r} is absent from the "
                f"{'baseline' if left is None else 'candidate'} contract, so "
                f"the two runs cannot be shown to agree about it",
                identity=kind))
            continue
        verdict = ident.compare(left, right)
        if verdict["verdict"] == "SAME":
            continue
        if verdict["verdict"] == "UNDETERMINED":
            out.append(C.finding(
                "PPA-C-007", C.SEV_UNDETERMINED,
                f"identity {kind!r} cannot be compared: {verdict['reason']}. "
                f"Two runs that each failed to measure something are not "
                f"thereby the same run",
                identity=kind))
            continue
        out.append(C.finding(
            "PPA-C-012", C.SEV_FAIL,
            f"the {kind} identity DIFFERS between the two arms, so "
            f"{_WHY[kind]}. Differing members: "
            f"{_render_diff(verdict.get('differing_members', {}))}",
            identity=kind,
            baseline_digest=verdict.get("left_digest"),
            candidate_digest=verdict.get("right_digest"),
            differing_members=verdict.get("differing_members")))

    impl = ident.compare(b_ids.get("implementation", {}),
                         c_ids.get("implementation", {}))
    if impl["verdict"] == "SAME":
        out.append(C.finding(
            "PPA-C-013",
            C.SEV_FAIL if require_impl_differs else C.SEV_UNDETERMINED,
            "the two arms have the SAME implementation identity, so any "
            "difference between their numbers is measurement noise rather "
            "than a result",
            digest=impl.get("digest")))
    elif impl["verdict"] == "UNDETERMINED":
        out.append(C.finding(
            "PPA-C-007", C.SEV_UNDETERMINED,
            f"the implementation identities cannot be compared: "
            f"{impl['reason']}", identity="implementation"))

    # The second, independent detector. Deliberately re-runs the candidate
    # contract's OWN mutation clause rather than trusting that
    # `ppa_contract_check` was run on it: an unrun check is not a passed one.
    out.extend(C._check_mutations(candidate))
    return sorted(out, key=lambda f: (f["code"], f["message"]))


def _render_diff(diff: Mapping[str, Any]) -> str:
    """Name what moved. A bare 'the digests differ' makes a reader diff two
    whole run trees by hand, which is where the answer stops being used."""
    parts: List[str] = []
    for row in diff.get("artefacts", []) or []:
        parts.append(f"artefact {row['role']} "
                     f"({_short(row.get('left'))} -> {_short(row.get('right'))})")
    for row in diff.get("facts", []) or []:
        parts.append(f"fact {row['key']} "
                     f"({json.dumps(row.get('left'))} -> "
                     f"{json.dumps(row.get('right'))})")
    return "; ".join(parts) if parts else "none reported"


def _short(digest: Any) -> str:
    if not isinstance(digest, str):
        return "absent"
    return digest[:14] + "…" if len(digest) > 14 else digest


#: What this gate would have examined, for the NO_CORPUS / VACUOUS line.
_GATE = "PPA problem integrity"
_SCANNED = "published contract record(s)"


def is_contract(doc: Any) -> bool:
    """A corpus record for THIS gate, decided on the document, not its name."""
    return isinstance(doc, dict) and doc.get("schema") == C.CONTRACT_SCHEMA


def problem_key(doc: Mapping[str, Any]) -> Optional[str]:
    """The `problem` identity digest, or None when there is nothing to key on.

    None is NOT "a problem nobody measured is its own group": grouping the
    unmeasured together would compare two runs on the strength of a shared
    absence, which is the exact inference PPA-C-007 exists to refuse.
    """
    rec = (doc.get("identities") or {}).get("problem")
    if not isinstance(rec, Mapping):
        return None
    digest = rec.get("digest")
    return str(digest) if isinstance(digest, str) and digest else None


def check_corpus(named: Path, require_impl_differs: bool = False,
                 may_be_absent: bool = False,
                 json_out: Optional[str] = None) -> int:
    """Every problem group under `named`, every pair inside it."""
    corpus, rc = corpus_seam.open_corpus(named, _GATE, _SCANNED, may_be_absent)
    if corpus is None:
        return rc
    scan = corpus_seam.collect(corpus, is_contract)
    print(f"ppa_problem_integrity_check --corpus {corpus}: "
          f"{scan.denominator(_SCANNED)}")
    unread_rc = corpus_seam.report_unreadable(_GATE, scan)
    if not scan.records:
        return corpus_seam.worst_rc(
            [corpus_seam.vacuous(_GATE, corpus, _SCANNED, scan), unread_rc])

    conflict_rows, groups, unkeyed = [], {}, []
    for path, doc in scan.records:
        ids = doc.get("identities")
        if isinstance(ids, dict) and ids:
            conflict_rows.append((path, cj.digest_of(ids), doc))
        key = problem_key(doc)
        if key is None:
            unkeyed.append(path)
            continue
        groups.setdefault(key, []).append((path, doc))
    conflicts, copies = corpus_seam.identity_conflicts(
        conflict_rows, _GATE, "contract identity")
    conflict_rc = corpus_seam.print_conflicts(_GATE, conflicts, copies)

    rcs: List[int] = [conflict_rc, unread_rc]
    for path in sorted(unkeyed, key=str):
        print(f"[{_GATE}] CANNOT CHECK: {path} carries no MEASURED `problem` "
              f"identity, so it cannot be grouped with anything and this run "
              f"establishes nothing about it. rc=2.", file=sys.stderr)
        rcs.append(corpus_seam.RC_UNDETERMINED)

    pairs = 0
    report_groups: List[Dict[str, Any]] = []
    for key in sorted(groups):
        arms = sorted(groups[key], key=lambda r: str(r[0]))
        if len(arms) < 2:
            print(f"[{_GATE}] CANNOT CHECK: problem identity {key} has ONE arm "
                  f"({arms[0][0]}). A comparison needs two; one arm is not a "
                  f"comparison that passed. rc=2.", file=sys.stderr)
            rcs.append(corpus_seam.RC_UNDETERMINED)
            report_groups.append({"problem": key, "arms": [str(arms[0][0])],
                                  "pairs": 0, "rc": corpus_seam.RC_UNDETERMINED})
            continue
        group_rcs: List[int] = []
        for i in range(len(arms)):
            for j in range(i + 1, len(arms)):
                (pa, da), (pb, db) = arms[i], arms[j]
                pairs += 1
                findings = compare_contracts(da, db, require_impl_differs)
                # BOTH arms get their own mutation clause; see the docstring.
                seen = {(f["code"], f["message"]) for f in findings}
                for extra in C._check_mutations(da):
                    if (extra["code"], extra["message"]) not in seen:
                        findings.append(extra)
                findings.sort(key=lambda f: (f["code"], f["message"]))
                pair_rc = C.rc_from(findings)
                group_rcs.append(pair_rc)
                stream = sys.stdout if pair_rc == 0 else sys.stderr
                print(f"{C.marker_for(pair_rc)} ppa_problem_integrity_check: "
                      f"{pa} vs {pb} — {len(findings)} finding(s)", file=stream)
                for line in C.format_findings(findings):
                    print(line, file=stream)
        rcs.extend(group_rcs)
        report_groups.append({"problem": key,
                              "arms": [str(p) for p, _ in arms],
                              "pairs": len(group_rcs),
                              "rc": corpus_seam.worst_rc(group_rcs)})

    worst = corpus_seam.worst_rc(rcs)
    print(f"ppa_problem_integrity_check --corpus {corpus}: "
          f"{len(scan.records)} contract(s) in {len(groups)} problem group(s), "
          f"{pairs} pair(s) compared, {len(conflicts)} identity conflict(s) "
          f"-> rc={worst}")
    if json_out:
        atomic_write_text(Path(json_out), json.dumps({
            "program": "ppa_problem_integrity_check", "mode": "corpus",
            "corpus": str(corpus), "files_opened": scan.files,
            "contracts": [str(path) for path, _ in scan.records],
            "unreadable": [{"path": str(p), "why": w}
                           for p, w in scan.unreadable],
            "identity_conflicts": conflicts, "identity_copies": copies,
            "groups": report_groups, "pairs": pairs, "rc": worst,
        }, indent=2) + "\n")
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--candidate", default=None)
    ap.add_argument("--corpus", default=None, metavar="DIR",
                    help="group every contract record under DIR by its "
                         "`problem` identity and compare every pair; exits 2 "
                         "when the corpus carries none")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="this repository need not carry the published "
                         "corpus. Turns 'nothing anywhere' into a stated "
                         "NO_CORPUS that names its zero, and NEVER excuses a "
                         "$VIBE_IC_BENCHMARK_DATA that is set and unreadable.")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--require-implementation-differs", action="store_true",
                    help="promote an identical implementation from "
                         "UNDETERMINED to a refusal")
    args = ap.parse_args(argv)

    if args.corpus is not None:
        if args.baseline is not None or args.candidate is not None:
            return corpus_seam.both_given("ppa_problem_integrity_check",
                                          "--baseline/--candidate", "--corpus")
        return check_corpus(Path(args.corpus).resolve(),
                            args.require_implementation_differs,
                            args.corpus_may_be_absent, args.json_out)
    if args.baseline is None or args.candidate is None:
        ap.error("give --baseline A.json --candidate B.json, or --corpus DIR")

    docs = {}
    for label, path in (("baseline", args.baseline), ("candidate", args.candidate)):
        doc, reason = C.load_json(Path(path))
        if reason is not None:
            print(f"[CANNOT CHECK] ppa_problem_integrity_check: {label} "
                  f"{reason}", file=sys.stderr)
            print("   No comparison was attempted. This is NOT a finding "
                  "about either design.", file=sys.stderr)
            return 2
        if not isinstance(doc, dict):
            print(f"[CANNOT CHECK] ppa_problem_integrity_check: {label} "
                  f"{path} holds a {type(doc).__name__}, not a contract",
                  file=sys.stderr)
            return 2
        docs[label] = doc

    findings = compare_contracts(docs["baseline"], docs["candidate"],
                                 args.require_implementation_differs)
    rc = C.rc_from(findings)

    if args.json_out:
        atomic_write_text(Path(args.json_out), json.dumps({
            "program": "ppa_problem_integrity_check",
            "baseline": str(args.baseline),
            "candidate": str(args.candidate),
            "rc": rc,
            "findings": findings,
        }, indent=2) + "\n")

    stream = sys.stdout if rc == 0 else sys.stderr
    print(f"{C.marker_for(rc)} ppa_problem_integrity_check: "
          f"{len(findings)} finding(s)", file=stream)
    for line in C.format_findings(findings):
        print(line, file=stream)
    if rc == 0:
        print("   problem, analysis and toolchain identities MATCH and the "
              "implementation identity differs — these two runs are "
              "comparable.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
