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

EXIT CODES
----------
    0  [PASS]          the two runs are comparable
    1  [REFUSE]        they are not: the problem, analysis or toolchain moved,
                       a mutation is outside the allow-list, or a contract does
                       not hash to itself
    2  [CANNOT CHECK]  a contract is absent/unreadable, or an identity needed
                       for the comparison is NOT_MEASURED on either side
    3  bad invocation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
import _corpus_location as _corpus  # noqa: E402  one seam for every corpus
from _ppa import cli_exit  # PPA_INTERFACES §1: argparse exits 2; a bad invocation is 3
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

    # Computed BEFORE the must-match loop because the analysis verdict is only
    # interpretable next to it: `analysis` differing on its own is a genuinely
    # different measurement, while `analysis` differing WHEN THE IMPLEMENTATION
    # DOES is the signature of an artefact filed in the wrong identity.
    impl = ident.compare(b_ids.get("implementation", {}),
                         c_ids.get("implementation", {}))

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

        # THE DIAGNOSIS, not a second verdict. PPA-C-012 above says the
        # comparison is invalid and is deliberately unchanged; this says WHY it
        # is invalid in the one case where the cause is a declaration mistake
        # rather than a real difference in how the two runs were measured.
        if kind == "analysis" and impl["verdict"] == "DIFFERENT":
            moved = [row["role"] for row
                     in (verdict.get("differing_members", {}) or {}
                         ).get("artefacts", []) or []]
            if moved:
                out.append(C.finding(
                    "PPA-C-016", C.SEV_FAIL,
                    "the analysis identity moved WITH the implementation, "
                    f"which means {', '.join(sorted(moved))} "
                    f"{'is' if len(moved) == 1 else 'are'} declared under "
                    "`analysis` but produced BY the implementation. An "
                    "artefact that varies with the implementation may not sit "
                    "in `analysis` (PPA_INTERFACES §3.1): `analysis` is the "
                    "measurement CONFIGURATION -- the corners, the extraction, "
                    "the activity basis, the scripts that take the reading -- "
                    "and never the reading. Declaring an STA, DRC or LVS "
                    "REPORT there makes every legitimate comparison refuse, "
                    "because of course the reports differ: they are outputs. "
                    "Move them to `implementation` and this check passes on "
                    "two runs that really are comparable.",
                    identity=kind, misfiled_artefacts=sorted(moved)))

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


#: --corpus, and why one pair was not enough (vibe-ic#1241, 2026-08-22).
#:
#: This gate was wired at a single EXACT pair under `benchmark-data/ppa/`, a
#: directory that left this repository in v1.10.56, so it compared nothing. When
#: it was re-aimed at the two pairs each campaign PUBLISHES as its headline it
#: began deciding — and then decided about TWO pairs while EIGHTY sit committed
#: in this tree (20 cross-layer trials against `b000`, 60 end-to-end trials
#: against `baseline`). A gate that examines 2 of 80 available comparisons is
#: under-aimed by exactly the argument that re-aimed it: a contract that drifts
#: in trial 37 is a comparison nobody may quote, and nothing would say so.
#:
#: `--corpus DIR` compares `--baseline` against EVERY OTHER contract under DIR.
#: The corpus is identified by DECLARATION and never by filename, the same rule
#: the contract, candidates and head-to-head corpora use, and for the same
#: measured reason: a name glob in this family missed 15 real records in this
#: tree and refused two of a checker's own reports as if they were records.
_CONTRACT_SCHEMA = C.CONTRACT_SCHEMA
_NAME_GLOB = "**/*contract*.json"
_SCANNED = "PPA contract pair(s)"
_GATE = "PPA arms solved one problem"


def corpus_candidates(corpus: Path, baseline: Path) -> List[Path]:
    """Every contract under `corpus` that is not the baseline itself."""
    named = {x for x in corpus.glob(_NAME_GLOB) if x.is_file()}
    base = baseline.resolve()
    out: List[Path] = []
    for path in sorted(x for x in corpus.glob("**/*.json") if x.is_file()):
        if path.resolve() == base:
            continue
        doc, reason = C.load_json(path)
        if reason is not None:
            # UNREADABLE IS NOT ABSENT. A file that claims by its NAME to be a
            # contract and cannot be parsed stays in the population, so the
            # pair it would have formed is reported rc 2 rather than dropped.
            if path in named:
                out.append(path)
            continue
        if isinstance(doc, dict) and doc.get("schema") == _CONTRACT_SCHEMA:
            out.append(path)
    return out


def check_corpus(named: Path, baseline: str, require_differs: bool) -> int:
    corpus, origin = _corpus.resolve(named, gate=_GATE, announce=True)
    if not corpus.is_dir():
        return _corpus.refuse(_GATE, named, corpus, origin, False, _SCANNED,
                              opt_in_flag=None)  # this gate offers no opt-in
    base = Path(baseline)
    if not base.is_file():
        print(f"[CANNOT CHECK] ppa_problem_integrity_check: baseline "
              f"{baseline}: absent. No comparison was attempted.",
              file=sys.stderr)
        return 2
    cands = corpus_candidates(corpus, base)
    scanned = sum(1 for x in corpus.glob("**/*.json") if x.is_file())
    print(f"ppa_problem_integrity_check --corpus {corpus}: {len(cands)} "
          f"pair(s) against {base.name} in {scanned} JSON document(s) scanned")
    if not cands:
        print(f"[CANNOT CHECK] VACUOUS: {corpus} carries no contract to pair "
              f"the baseline with, so no comparison was made. This is NOT a "
              f"pass. rc=2.", file=sys.stderr)
        return 2
    rcs = [main(["--baseline", baseline, "--candidate", str(q)]
                + (["--require-implementation-differs"] if require_differs
                   else []))
           for q in cands]
    # A REFUSAL OUTRANKS AN UNDETERMINED OUTRANKS A PASS. `max()` would make 2
    # the winning verdict, so one unreadable contract could promote a real
    # refusal to "could not check" — adding a pair must never SUBTRACT one.
    refused = sum(1 for rc in rcs if rc == 1)
    undet = sum(1 for rc in rcs if rc == 2)
    worst = 1 if refused else (2 if undet else 0)
    print(f"ppa_problem_integrity_check --corpus {corpus}: {len(cands)} "
          f"pair(s), {refused} refused, {undet} undetermined, "
          f"{len(cands) - refused - undet} comparable -> rc={worst}")
    if refused:
        print(f"REFUSED: {refused} of {len(cands)} pair(s) were not solving "
              f"the same problem, so those comparisons may not be quoted.",
              file=sys.stderr)
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate")
    ap.add_argument("--corpus", metavar="DIR",
                    help="compare --baseline against EVERY other document "
                         f"declaring {_CONTRACT_SCHEMA} under DIR; exits 2 "
                         "when the corpus is absent or carries none (#1241)")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--require-implementation-differs", action="store_true",
                    help="promote an identical implementation from "
                         "UNDETERMINED to a refusal")
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc
    if bool(args.corpus) == bool(args.candidate):
        print("[CANNOT CHECK] ppa_problem_integrity_check: give exactly one "
              "of --candidate or --corpus", file=sys.stderr)
        return 2
    if args.corpus:
        return check_corpus(Path(args.corpus), args.baseline,
                            args.require_implementation_differs)

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
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - the guard, not the path
        # §1: 3 is INTERNAL ERROR. Letting this propagate exits 1, which is
        # reserved for a finding about the design — so a malformed contract
        # that crashes the comparator would reach the roll-up as "these two
        # runs were not solving the same problem", a verdict nothing reached.
        #
        # NEWLY REACHABLE (vibe-ic#1241). While this gate compared ONE pair of
        # hand-named files a crash was a local accident. `--corpus` sweeps every
        # contract in a campaign, so a single document whose `identities` are
        # shaped wrong now decides the whole corpus row. `ppa_contract_check`
        # has carried this guard from the start; this is the same one.
        print(f"{cli_exit.MARK_REFUSE} ppa_problem_integrity_check: internal "
              f"error {type(exc).__name__}: {exc}. Nothing was compared. rc=3 "
              f"(NOT a finding about any contract).", file=sys.stderr)
        raise SystemExit(cli_exit.RC_BAD_INVOCATION)
