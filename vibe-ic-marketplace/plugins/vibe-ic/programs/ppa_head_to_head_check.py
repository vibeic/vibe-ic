#!/usr/bin/env python3
"""A PPA head-to-head is a claim about SILICON, so it has to survive the four
ways such a claim goes wrong. vibe-ic#1121.

WHAT #1121 SAYS, AND WHY A GATE IS THE FIRST STEP
=================================================
Our published numbers — VerilogEval-v2 153/156, RTLLM 49/50, CVDP 243/302 —
prove an AI can produce relatively correct RTL. They do not prove it can produce
BETTER SILICON, and a reviewer is entitled to answer them with "so what?".

The question that measures the property is:

    Given an IDENTICAL specification and an IDENTICAL PDK, can this project
    produce better PPA than a human, a LibreLane, or an OpenECOS baseline?

The first head-to-head run is worth nothing if nobody can check it afterwards.
So the first landable step is not a number — it is the RECORD SCHEMA and the
refusals that make such a number checkable. This program is that.

It COMPUTES NOTHING about a design. It reads a record somebody else produced and
refuses it when the record cannot support the claim printed on it. It has no
opinion about which flow should win, and the LOSS verdict is derived by exactly
the same code path as the WIN.

THE FOUR REFUSALS, EACH ONE OF #1121'S OWN STATED CONSTRAINTS
============================================================
C1  SAME PROBLEM (#1121 constraint 4).  Every arm must declare the same spec
    digest, PDK, clock target and corner SET. Two flows run on two different
    problems are not a comparison, however carefully each was measured.

C2  THE TRIPLE, NEVER A PROXY (#1121 constraint 3, lie-shape #12).  Area,
    timing and power trade against each other, so any SINGLE figure is a proxy
    for the property and not the property. Every arm must carry all three, and
    a record that also carries a collapsed scalar is refused for carrying it —
    the scalar is the thing that gets quoted.

C3  THE BASELINE IS THEIRS (#1121 constraint 2).  "A baseline we tune ourselves
    is an oracle we wrote — the exact shape this project exists to remove." The
    baseline arm must declare `tuned_by_this_project: false` and name where its
    configuration came from. A baseline this project tuned is refused even if
    its numbers are worse than ours, because a favourable number from a rigged
    opponent is the failure this refusal exists for.

C4  SIMULATED IS NOT SILICON (#1121 constraint 1).  PPA off a signed-off GDS is
    a far better number than a pass rate and it is still not a wafer. Each arm
    declares its measurement basis; anything claiming `silicon` must name the
    evidence, and the report says in words that a simulated triple is not a
    silicon result. #1120's Silicon Proof dimension reads zero and this program
    is not allowed to make it look otherwise.

AND ONE THAT IS NOT A REFUSAL BUT A DERIVATION
==============================================
C5  THE VERDICT IS DERIVED, NOT ASSERTED.  If the record states a verdict, it
    must equal what this program computes from the numbers. A record asserting
    that we won, over numbers that say we lost, is refused — that is the only
    direction of dishonesty a head-to-head has room for, and it is cheap to
    close.

The derived verdict is a TRIPLE of per-axis verdicts, never one word. #1121:
"Report the triple with the constraints that produced it, or do not report it."
There is deliberately no `overall` field to quote.

MISSING IS NOT WINNING
======================
An arm with an unmeasured axis yields rc=2 UNDETERMINED, never a win on the axes
that were measured. A comparison that could not look must not reach a reader as
a comparison that looked and was favourable.

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: no design, PDK, process, vendor or
part literal appears in the logic or can affect it. The PDK string is compared
to the OTHER arm's PDK string and is never interpreted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2

#: The three axes, and which direction is better. This is the whole of the
#: program's PPA knowledge and it is a physical fact, not a tuning choice:
#: smaller area is better, more positive slack is better, less power is better.
AXES: Dict[str, str] = {
    "area_um2": "lower",
    "timing_wns_ns": "higher",
    "power_mw": "lower",
}

#: Fields whose presence IS the defect: a collapsed score is the number that
#: gets quoted, and quoting it is lie-shape #12 by construction.
COLLAPSED_SCALAR_FIELDS = ("score", "ppa_score", "overall", "figure_of_merit",
                           "fom", "composite")

#: The identity of the PROBLEM. Two arms disagreeing on any of these are not
#: running the same problem. Compared as opaque values; never interpreted.
PROBLEM_FIELDS = ("spec_sha256", "pdk", "clock_target_ns", "corners")

MEASUREMENT_BASES = ("signed_off_gds", "post_route_sta", "silicon")


class Refusal(Exception):
    """A record that cannot support the claim printed on it."""

    def __init__(self, code: str, message: str, rc: int = RC_REFUSED):
        super().__init__(message)
        self.code = code
        self.message = message
        self.rc = rc


def _load(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refusal("NO_RECORD", f"no such record: {path}", RC_UNDETERMINED)
    except json.JSONDecodeError as exc:
        raise Refusal("BAD_JSON", f"{path}: {exc}", RC_UNDETERMINED)
    if not isinstance(doc, dict):
        raise Refusal("BAD_JSON", f"{path}: top level is not an object",
                      RC_UNDETERMINED)
    return doc


def _arms(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    arms = doc.get("arms")
    if not isinstance(arms, list) or len(arms) < 2:
        raise Refusal(
            "TOO_FEW_ARMS",
            "a head-to-head needs at least two arms; "
            f"got {0 if not isinstance(arms, list) else len(arms)}")
    for a in arms:
        if not isinstance(a, dict) or not a.get("flow"):
            raise Refusal("ARM_UNNAMED", "every arm must name its `flow`")
    return arms


def check_same_problem(arms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """C1 — #1121 constraint 4. Identical spec, PDK, clock target, corner set."""
    ref = arms[0]
    ref_id = ref.get("design") or {}
    diverged = []
    for field in PROBLEM_FIELDS:
        want = ref_id.get(field)
        if want is None:
            raise Refusal(
                "PROBLEM_UNDECLARED",
                f"arm {ref['flow']!r} does not declare `design.{field}`, so "
                "there is nothing to compare the other arms' problem against")
        for other in arms[1:]:
            got = (other.get("design") or {}).get(field)
            # A corner SET, not a corner list: order is not part of identity.
            same = (sorted(want) == sorted(got)
                    if field == "corners"
                    and isinstance(want, list) and isinstance(got, list)
                    else want == got)
            if not same:
                diverged.append({
                    "field": field, "a": ref["flow"], "a_value": want,
                    "b": other["flow"], "b_value": got,
                })
    if diverged:
        raise Refusal(
            "DIFFERENT_PROBLEM",
            "the arms are not running the same problem, so the comparison "
            "measures two designs and not two flows: "
            + "; ".join(f"{d['field']}: {d['a']}={d['a_value']!r} vs "
                        f"{d['b']}={d['b_value']!r}" for d in diverged))
    return {f: ref_id.get(f) for f in PROBLEM_FIELDS}


def check_triple(arms: List[Dict[str, Any]]) -> None:
    """C2 — #1121 constraint 3. All three axes, and no collapsed scalar."""
    for a in arms:
        ppa = a.get("ppa")
        if not isinstance(ppa, dict):
            raise Refusal("NO_PPA",
                          f"arm {a['flow']!r} carries no `ppa` object")
        for bad in COLLAPSED_SCALAR_FIELDS:
            if bad in ppa or bad in a:
                raise Refusal(
                    "COLLAPSED_SCALAR",
                    f"arm {a['flow']!r} carries a collapsed figure "
                    f"`{bad}`. Area, timing and power trade against each "
                    "other, so a single number is a proxy for the property "
                    "and not the property (lie-shape #12). It is refused for "
                    "EXISTING: whatever else the record says, the scalar is "
                    "the number that gets quoted.")
        missing = [ax for ax in AXES
                   if not isinstance(ppa.get(ax), (int, float))
                   or isinstance(ppa.get(ax), bool)]
        if missing:
            raise Refusal(
                "AXIS_UNMEASURED",
                f"arm {a['flow']!r} has no numeric value for {missing}. An "
                "unmeasured axis is UNDETERMINED, never a win on the axes "
                "that were measured.",
                RC_UNDETERMINED)


def check_baseline_is_theirs(arms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """C3 — #1121 constraint 2. The opponent's flow, the opponent's defaults."""
    baselines = [a for a in arms if a.get("role") == "baseline"]
    subjects = [a for a in arms if a.get("role") == "subject"]
    if len(subjects) != 1 or len(baselines) < 1:
        raise Refusal(
            "ROLES_UNCLEAR",
            "exactly one arm must declare role='subject' and at least one "
            f"role='baseline'; got {len(subjects)} subject(s), "
            f"{len(baselines)} baseline(s)")
    for b in baselines:
        if b.get("tuned_by_this_project") is not False:
            raise Refusal(
                "BASELINE_TUNED_BY_US",
                f"baseline {b['flow']!r} does not declare "
                "`tuned_by_this_project: false`. A baseline we tune is an "
                "oracle we wrote, and a favourable number measured against it "
                "says nothing about silicon.")
        if not b.get("config_source"):
            raise Refusal(
                "BASELINE_CONFIG_UNSOURCED",
                f"baseline {b['flow']!r} does not name a `config_source`. "
                "Without it, 'their defaults' is an assertion.")
    return {"subject": subjects[0]["flow"],
            "baselines": [b["flow"] for b in baselines]}


def check_measurement_basis(arms: List[Dict[str, Any]]) -> List[str]:
    """C4 — #1121 constraint 1. Simulated is not silicon, and says so."""
    bases = []
    for a in arms:
        basis = a.get("measurement_basis")
        if basis not in MEASUREMENT_BASES:
            raise Refusal(
                "BASIS_UNDECLARED",
                f"arm {a['flow']!r} declares measurement_basis={basis!r}; "
                f"must be one of {MEASUREMENT_BASES}")
        if basis == "silicon" and not a.get("silicon_evidence"):
            raise Refusal(
                "SILICON_UNEVIDENCED",
                f"arm {a['flow']!r} claims a SILICON measurement without "
                "`silicon_evidence`. A simulated triple that calls itself "
                "silicon is the one thing this comparison must never publish.")
        bases.append(basis)
    return bases


def derive_verdict(arms: List[Dict[str, Any]]) -> Dict[str, Any]:
    """C5 — per AXIS, never collapsed. LOSS is derived like WIN."""
    subject = next(a for a in arms if a.get("role") == "subject")
    out: Dict[str, Any] = {"subject": subject["flow"], "per_baseline": {}}
    for b in [a for a in arms if a.get("role") == "baseline"]:
        axes: Dict[str, Any] = {}
        for ax, better in AXES.items():
            s = float(subject["ppa"][ax])
            o = float(b["ppa"][ax])
            if s == o:
                verdict = "TIE"
            elif (s < o) == (better == "lower"):
                verdict = "SUBJECT_BETTER"
            else:
                verdict = "BASELINE_BETTER"
            axes[ax] = {
                "subject": s, "baseline": o, "better_is": better,
                "verdict": verdict,
                "delta": round(s - o, 6),
                "delta_pct": (round((s - o) / o * 100.0, 4)
                              if o not in (0, 0.0) else None),
            }
        out["per_baseline"][b["flow"]] = axes
    return out


def check_asserted_verdict(doc: Dict[str, Any], derived: Dict[str, Any]) -> None:
    """A record may state its verdict, but it may not state a DIFFERENT one."""
    asserted = doc.get("verdict")
    if asserted is None:
        return
    if not isinstance(asserted, dict):
        raise Refusal("VERDICT_SHAPE",
                      "`verdict`, when present, must be an object keyed by "
                      "baseline flow, mapping each axis to its verdict")
    for flow, axes in asserted.items():
        d = derived["per_baseline"].get(flow)
        if d is None:
            raise Refusal(
                "VERDICT_UNKNOWN_BASELINE",
                f"record asserts a verdict against {flow!r}, which is not a "
                "baseline arm in this record")
        for ax, said in (axes or {}).items():
            got = d.get(ax, {}).get("verdict")
            if said != got:
                raise Refusal(
                    "VERDICT_CONTRADICTED",
                    f"record asserts {ax}={said!r} against {flow!r}; the "
                    f"numbers in the same record derive {got!r}")


def evaluate(path: Path) -> Tuple[int, Dict[str, Any]]:
    report: Dict[str, Any] = {"record": str(path)}
    try:
        doc = _load(path)
        arms = _arms(doc)
        report["problem"] = check_same_problem(arms)
        check_triple(arms)
        report["roles"] = check_baseline_is_theirs(arms)
        report["measurement_bases"] = check_measurement_basis(arms)
        derived = derive_verdict(arms)
        check_asserted_verdict(doc, derived)
        report["derived_verdict"] = derived
        report["ok"] = True
        return RC_OK, report
    except Refusal as r:
        report["ok"] = False
        report["refusal"] = {"code": r.code, "message": r.message}
        return r.rc, report


def format_report(rc: int, report: Dict[str, Any]) -> str:
    lines: List[str] = []
    if rc == RC_OK:
        v = report["derived_verdict"]
        lines.append(f"[PASS] ppa_head_to_head_check: {report['record']}")
        lines.append(f"  problem: {json.dumps(report['problem'], sort_keys=True)}")
        for flow, axes in v["per_baseline"].items():
            lines.append(f"  {v['subject']} vs {flow}:")
            for ax, d in axes.items():
                pct = "n/a" if d["delta_pct"] is None else f"{d['delta_pct']:+.2f}%"
                lines.append(
                    f"    {ax:<14} subject={d['subject']:<12} "
                    f"baseline={d['baseline']:<12} ({d['better_is']} better) "
                    f"{pct}  -> {d['verdict']}")
        if "silicon" not in report.get("measurement_bases", []):
            lines.append(
                "  NOT SILICON: every arm here is a simulated triple "
                f"({sorted(set(report['measurement_bases']))}). This is a "
                "better number than a pass rate and it is not a wafer "
                "measurement; #1120's Silicon Proof dimension still reads zero.")
        lines.append(
            "  No overall figure is emitted. Area, timing and power trade "
            "against each other; the triple IS the result.")
    else:
        tag = "[FAIL]" if rc == RC_REFUSED else "[UNDETERMINED]"
        r = report["refusal"]
        lines.append(f"{tag} ppa_head_to_head_check: {r['code']}")
        lines.append(f"  {r['message']}")
        if rc == RC_UNDETERMINED:
            lines.append(
                "  Could not decide. That is not a pass and it is not a win: "
                "a comparison that could not look must never reach a reader "
                "as one that looked and was favourable.")
    return "\n".join(lines)


#: vibe-ic#1241 — CORPUS MODE, and why it refuses instead of passing.
#:
#: This checker validates a record someone else produced; it computes nothing.
#: At the time it was wired, the corpus carried ZERO head-to-head records — the
#: first head-to-head run has not happened, which is the whole point of #1121
#: ("the first landable step is not a number, it is the record schema").
#:
#: So wiring it as an ordinary gate would have printed PASS over an empty
#: population — a gate that has never met an artefact reporting success, which
#: is the exact shape `gate_zero_denominator_refuses_check` exists to refuse and
#: the shape #1241 is cleaning up. Instead it exits 2 (NOT CHECKED) and says how
#: many records it found, and the hygiene script calls it through
#: `run_tolerating_uncheckable`. The day a record lands the gate starts deciding
#: with no further change.
_RECORD_GLOB = "**/*head_to_head*.json"


def corpus_records(corpus: Path):
    """Head-to-head records under `corpus`, by name. The denominator is
    disclosed on every run so "none found" can never read as "all clean"."""
    return sorted(p for p in corpus.glob(_RECORD_GLOB) if p.is_file())


def check_corpus(corpus: Path) -> int:
    recs = corpus_records(corpus)
    print(f"ppa_head_to_head_check --corpus {corpus}: "
          f"{len(recs)} head-to-head record(s) found")
    if not recs:
        print("VACUOUS: the corpus carries no head-to-head record, so nothing "
              "was validated. This is NOT a pass — the first head-to-head run "
              "has not been published yet (vibe-ic#1121). rc=2.",
              file=sys.stderr)
        return 2
    worst = 0
    for r in recs:
        rc = main([str(r)])
        worst = max(worst, rc)
    return worst


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Refuse a PPA head-to-head record that cannot support the "
                    "claim printed on it (vibe-ic#1121).")
    ap.add_argument("record", nargs="?",
                    help="path to the head-to-head JSON record")
    ap.add_argument("--corpus", default=None, metavar="DIR",
                    help="validate every head-to-head record under DIR; "
                         "exits 2 when the corpus carries none (#1241)")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)
    if args.corpus is not None:
        return check_corpus(Path(args.corpus).resolve())
    if not args.record:
        ap.error("give a record path or --corpus DIR")

    rc, report = evaluate(Path(args.record))
    print(format_report(rc, report))
    if args.json:
        atomic_write_text(
            Path(args.json),
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
