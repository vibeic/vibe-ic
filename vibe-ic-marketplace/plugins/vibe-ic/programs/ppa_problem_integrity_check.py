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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--require-implementation-differs", action="store_true",
                    help="promote an identical implementation from "
                         "UNDETERMINED to a refusal")
    args = ap.parse_args(argv)

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
