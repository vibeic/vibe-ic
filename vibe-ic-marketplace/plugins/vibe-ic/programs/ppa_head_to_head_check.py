#!/usr/bin/env python3
"""A PPA head-to-head is a claim about SILICON, so it has to survive every way
such a claim goes wrong. vibe-ic#1121, comparison schema v2.

    SAME RTL, SAME PDK, LOWER POWER, HIGHER PERFORMANCE, SMALLER AREA -- THAT IS
    BETTER.

That sentence is the product claim, and this program exists to make it
UNARGUABLE rather than merely asserted. v1 encoded the four refusals #1121 asked
for and all four are still here, unchanged, below. v2 adds the five conditions
without which the sentence stays arguable by anyone who wants to argue with it,
and the useful property of all five is that they are CHECKABLE:

    the same STAGE          synthesis area is not post-route area
    the same corner/mode    an arm at one PVT is not an arm at another
    the same activity basis vectorless power is not VCD power
    both arms FEASIBLE      smaller area with DRC violations is not smaller
    a tuned arm may tune    a win over a weakened opponent measures the setup

The conditions themselves live in `_ppa/benchmark.py`, each with the argument
for why it is not already covered; this file is their CLI, their corpus driver,
and the place where the two halves of a verdict -- what the numbers derive and
what the record asserts -- are put side by side.

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

THE FOUR v1 REFUSALS, EACH ONE OF #1121'S OWN STATED CONSTRAINTS
===============================================================
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

THE FIVE v2 CONDITIONS, AND WHY EACH IS NOT ALREADY COVERED
==========================================================
F1  ONE CONTRACT, PROVEN BY HASH.  C1 compares four declared fields. A contract
    that differs in a FIFTH thing -- a floorplan constraint, an IO budget, a
    permitted cell set -- passes C1 and is still a different problem. Every arm
    declares `contract.sha256` and they must be identical, or the comparison is
    UNDETERMINED. UNDETERMINED and not REFUSED because a hash mismatch says the
    contracts differ without saying how, and this program is not entitled to
    pick one. A declared hash that disagrees with the contract body carried in
    the SAME record is a different matter and is rc 1: that one IS demonstrable
    here, by recomputing it with the canonical serializer.

F2  ONE SCOPE PER AXIS.  A v1 axis is a BARE FLOAT, and a bare float cannot say
    which stage, corner, mode or activity basis produced it. So v1 could not
    answer three of the four arguabilities above -- not answered them badly, but
    carried nothing capable of answering them. A v2 axis is the canonical metric
    record and the arms' `scope` objects must be EQUAL.

    Equality rather than three hand-written comparisons, deliberately: a checker
    that compares stage, then corner, then activity basis acquires a fourth
    blind spot the day a fifth scope key is added, whereas requiring the scopes
    to match has none by construction. `REQUIRED_SCOPE` closes the degenerate
    way to satisfy equality, which is for both arms to declare nothing.

F3  STAGE AND BASIS MUST AGREE.  An arm declaring `signed_off_gds` while citing
    a synthesis-stage number is claiming a measurement it did not take. This is
    the refusal that stops a proxy standing in for the property INSIDE one arm,
    which no comparison between arms can catch.

F4  BOTH ARMS FEASIBLE, OVER THE SAME QUESTION.  An implementation that does not
    close is not an implementation, so a number taken off it is the cost of a
    design that does not exist. The asymmetry half matters as much: DRC + LVS +
    antenna on the subject and DRC alone on the baseline gives two arms both
    reporting clean over different questions, and the one asked less looks
    exactly as good as the one asked more.

F5  A TUNED ARM MUST BE ALLOWED TO TUNE.  Publishing a win over a deliberately
    weakened opponent is the same defect as a gate that cannot fail, and worse
    in one respect -- a gate that cannot fail merely misses defects, while a
    rigged benchmark publishes a false one. If the opponent's flow ships a tuner
    it gets that tuner, its OFFICIAL search space, and a budget no smaller than
    ours. C3's `tuned_by_this_project: false` does not cover this: a campaign can
    answer it truthfully while having authored the opponent's search space and
    given it five trials against our five hundred.

AND THE PARETO RELATION, WHICH IS NOT A REFUSAL
===============================================
The derived verdict carries a `pareto` relation per baseline: SUBJECT_DOMINATES,
BASELINE_DOMINATES, EQUAL or INCOMPARABLE. INCOMPARABLE is a RESULT and it is
the common one, because the three axes trade against each other by construction.
A record asserting a Pareto relation the numbers do not support is refused
exactly as an asserted per-axis verdict is -- otherwise the collapsed scalar the
record may not CARRY simply arrives through the verdict instead.

MISSING IS NOT WINNING
======================
An arm with an unmeasured axis yields rc=2 UNDETERMINED, never a win on the axes
that were measured. A comparison that could not look must not reach a reader as
a comparison that looked and was favourable.

ENFORCEMENT: advisory — no runner spawns this gate inline, so it cannot stop
step 36 while step 36 is running. That is the narrow question
`flow_gate_enforcement_audit` scores, and `advisory` is that audit's token for
the answer; it is NOT a licence to ignore the verdict. This gate is a leg of
step 36 in the flow's BLOCKING slot -- wired as `optional_program_exit_zero`
with an `absent_condition_reason`, never as `advisory_program_exit_zero`. An
`optional_` clause whose condition IS met is evaluated exactly like the
unconditional blocking form, and since vibe-ic W4 an UNMET condition FAILs
outright unless the wiring site declares why an absent input is genuinely
not-applicable. So when `flow_compliance_check` evaluates that clause an rc 1
FAILs the step — and step 37 `blocks_on: [34, 36]`, so a record
that cannot support its claim stops the run before stream-out. The two words are
one axis apart and reading them as one axis is how a gate gets quietly defanged
into the advisory slot.

WHY IT IS NOT PROMOTED TO INLINE-BLOCKING: this program validates a RECORD, not
a design. The phase-3 runner's inline pattern spawns gates over artefacts the
step it guards has just produced, and no step produces a head-to-head record —
it is written by a comparison campaign, not by a flow run. There is nothing for
an inline spawn to observe as it happens.

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
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)
import _corpus_location as _corpus  # sibling program, one seam for all corpora
from _ppa import benchmark as _bench  # the fairness conditions, and their argument

RC_OK = _bench.RC_OK
RC_REFUSED = _bench.RC_REFUSED
RC_UNDETERMINED = _bench.RC_UNDETERMINED

SCHEMA_V1 = _bench.SCHEMA_V1
SCHEMA_V2 = _bench.SCHEMA_V2

#: The three axes, and which direction is better. This is the whole of the
#: program's PPA knowledge and it is a physical fact, not a tuning choice:
#: smaller area is better, more positive slack is better, less power is better.
#: Defined once in `_ppa/benchmark.py` and bound here, so that the CLI and the
#: library can never disagree about which direction is better -- two answers to
#: that question is how a LOSS gets reported as a WIN with nobody lying.
AXES: Dict[str, str] = _bench.AXES

#: Fields whose presence IS the defect: a collapsed score is the number that
#: gets quoted, and quoting it is lie-shape #12 by construction.
COLLAPSED_SCALAR_FIELDS = ("score", "ppa_score", "overall", "figure_of_merit",
                           "fom", "composite")

#: The identity of the PROBLEM. Two arms disagreeing on any of these are not
#: running the same problem. Compared as opaque values; never interpreted.
PROBLEM_FIELDS = ("spec_sha256", "pdk", "clock_target_ns", "corners")

MEASUREMENT_BASES = ("signed_off_gds", "post_route_sta", "silicon")


#: ONE Refusal type, defined in the library and bound here. If this file
#: defined its own, a refusal raised by a fairness condition would not be caught
#: by `evaluate`'s `except Refusal`, and it would escape as a traceback -- which
#: exits 1 on the way out. rc 1 in this program means "the record cannot support
#: its claim", a finding about silicon, so a crash would report a hard finding
#: over a bug. That is the exact shape `docs/PPA_INTERFACES.md` section 1
#: records two shipped gates paying for on 2026-08-21.
Refusal = _bench.Refusal


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
        # v1 wrote a bare float, v2 the canonical metric record. `axis_value`
        # reads both, so the two shapes differ in what they can be CHECKED for
        # and never in what the arithmetic does -- a migration that changed the
        # arithmetic would itself become a source of disagreement.
        missing = [ax for ax in AXES if _bench.axis_value(a, ax) is None]
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
    """C5 — per AXIS plus the Pareto relation, never collapsed.

    Delegated to `_ppa.benchmark.score`, which is handed `arms` AND NOTHING
    ELSE. There is no parameter through which the record's asserted verdict
    could reach the scorer, so it cannot agree with an assertion -- it can only
    compute one. Whether the assertion matches is asked afterwards, by
    `check_asserted_verdict`, over the scorer's output. A future author who
    wants the scorer to see the assertion has to widen the signature, and that
    is visible in a diff in a way that reading one more key off a dict is not.

    LOSS is derived by the same code path as WIN; there is no branch only a win
    takes.
    """
    return _bench.score(arms)


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
            # `pareto` sits beside the three axes and is a RELATION, not an
            # axis verdict, so it is compared against the derived relation
            # directly. It is checked at all because it is the remaining route
            # for a collapsed claim: the record may not CARRY a figure of merit
            # (C2 refuses one for existing), so an author wanting to say "we
            # won" in one word has only the verdict left, and an unchecked
            # `pareto: SUBJECT_DOMINATES` over a mixed triple is that word.
            if ax == "pareto":
                got = d.get("pareto")
            else:
                got = d.get(ax, {}).get("verdict") if isinstance(
                    d.get(ax), dict) else None
            if said != got:
                raise Refusal(
                    "VERDICT_CONTRADICTED",
                    f"record asserts {ax}={said!r} against {flow!r}; the "
                    f"numbers in the same record derive {got!r}")


#: Schemas whose rules this program knows. A record declaring anything else is
#: UNDETERMINED and not refused: rules we do not have are not rules a record
#: broke, and guessing that a v3 record obeys v2's conditions would be a verdict
#: this program is not entitled to.
KNOWN_SCHEMAS = (SCHEMA_V1, SCHEMA_V2)


def check_declared_schema(doc: Dict[str, Any]) -> str:
    """Which rules this record says it was written to.

    A record that declares NOTHING is v1, because every record written before
    the fairness conditions existed declares nothing. Reading them as v2 and
    refusing them would be charging a document with breaking a rule that did not
    exist when it was written; reading them as v1 gives them the v1 checks and
    then the v2 conditions find them UNDETERMINED for carrying no scope, which
    is the true state of affairs.

    And declaring v1 buys nothing. The conditions below run over EVERY record
    whatever it declares, so the only thing the declaration changes is what the
    report calls the document. A gate that could be switched off by a field in
    its own input is not a gate.
    """
    declared = _bench.record_schema(doc)
    if declared not in KNOWN_SCHEMAS:
        raise Refusal(
            "UNKNOWN_SCHEMA",
            f"record declares schema {declared!r}; this program knows "
            f"{list(KNOWN_SCHEMAS)}. Rules this program does not have are not "
            "rules the record broke, so this is UNDETERMINED and not a "
            "refusal.",
            RC_UNDETERMINED)
    return declared


def evaluate(path: Path) -> Tuple[int, Dict[str, Any]]:
    report: Dict[str, Any] = {"record": str(path)}
    try:
        doc = _load(path)
        report["declared_schema"] = check_declared_schema(doc)
        arms = _arms(doc)
        # ORDER IS THE v1 REFUSALS FIRST, and it is not arbitrary. A record
        # that is defective in a v1 way is defective in the way #1121 named,
        # and it should be told so in #1121's words rather than being refused
        # for a scope key it was never asked to carry.
        report["problem"] = check_same_problem(arms)
        check_triple(arms)
        report["roles"] = check_baseline_is_theirs(arms)
        report["measurement_bases"] = check_measurement_basis(arms)
        # v2. Each one is argued in `_ppa/benchmark.py`; none of them can be
        # switched off by anything the record says about itself.
        report["contract"] = _bench.check_contract_identity(arms)
        report["scope"] = _bench.check_scope_parity(arms)
        _bench.check_stage_basis_agreement(arms)
        report["feasibility"] = _bench.check_feasibility(arms)
        subject = next(a for a in arms if a.get("role") == "subject")
        report["tuning"] = _bench.check_tuning_parity(
            subject, [a for a in arms if a.get("role") == "baseline"])
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
            for ax in sorted(a for a in axes if a != "pareto"):
                d = axes[ax]
                pct = "n/a" if d["delta_pct"] is None else f"{d['delta_pct']:+.2f}%"
                lines.append(
                    f"    {ax:<14} subject={d['subject']:<12} "
                    f"baseline={d['baseline']:<12} ({d['better_is']} better) "
                    f"{pct}  -> {d['verdict']}")
            rel = axes.get("pareto")
            lines.append(f"    {'pareto':<14} {rel}")
            if rel == "INCOMPARABLE":
                lines.append(
                    "      INCOMPARABLE is a RESULT, not a missing one: this "
                    "arm is better on some axes and worse on others, which is "
                    "what a trade-off looks like. Reporting it as a win would "
                    "be the collapsed figure this record is not allowed to "
                    "carry, arriving through the verdict instead.")
        if report.get("scope"):
            lines.append("  scope, identical in every arm and that is what "
                         "makes the numbers comparable:")
            for ax in sorted(report["scope"]):
                lines.append(f"    {ax:<14} "
                             f"{json.dumps(report['scope'][ax], sort_keys=True)}")
        if report.get("contract"):
            lines.append(f"  one contract, all arms: {report['contract']}")
        if report.get("tuning"):
            t = report["tuning"]
            subj = t.get("_subject", {})
            lines.append(
                f"  tuning: subject supported={subj.get('supported')} "
                f"performed={subj.get('performed')} budget={subj.get('budget')}")
            for flow in sorted(k for k in t if k != "_subject"):
                b = t[flow]
                lines.append(
                    f"          {flow}: supported={b['supported']} "
                    f"performed={b['performed']} budget={b['budget']} "
                    f"search_space={b['search_space_source']!r}")
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
            # `[CANNOT CHECK]` is the marker `docs/PPA_INTERFACES.md` section 1
            # names for an rc 2, and it is printed as well as `[UNDETERMINED]`
            # rather than instead of it: the second is this repository's own
            # established token and other programs print it, while the first is
            # the PPA contract's. A reader or a grep looking for either finds
            # it, and neither can be mistaken for a silent skip.
            lines.append(
                "  [CANNOT CHECK] Could not decide. That is not a pass and it "
                "is not a win: a comparison that could not look must never "
                "reach a reader as one that looked and was favourable.")
        else:
            lines.append(
                "  [REFUSE] The record cannot support the claim printed on "
                "it. rc=1 here is a finding about the comparison and through "
                "it about silicon, not a report that something could not be "
                "read.")
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


#: Aggregation order for a corpus, and it is NOT the integer order.
#:
#: `flow_compliance_check.__check_program_exit_zero` maps rc 2 -> VACUOUS_PASS
#: (the step PASSES and is disclosed) and rc 1 -> FAIL. So rc 2 is the larger
#: integer and the WEAKER verdict, and aggregating a corpus with `max()` — which
#: is what this did — promoted a refusal to a pass. MEASURED: a corpus holding
#: one C3-refused record returned rc 1; dropping ONE further record with an
#: unmeasured axis beside it returned rc 2, so the refusal reached the flow as a
#: vacuous pass. Adding a record must never be able to SUBTRACT a refusal, and
#: an aggregator in which it can is a defeat-the-gate primitive inside the one
#: gate whose whole subject is claims that cannot be checked afterwards.
#:
#: The order below is the docstring's own: "MISSING IS NOT WINNING" — a refusal
#: outranks an undetermined, which outranks an accepted record.
_SEVERITY = {RC_REFUSED: 2, RC_UNDETERMINED: 1, RC_OK: 0}


def worst_rc(rcs: List[int]) -> int:
    """The corpus verdict: the single most severe record decides it."""
    worst = RC_OK
    for rc in rcs:
        if _SEVERITY.get(rc, _SEVERITY[RC_REFUSED]) > _SEVERITY[worst]:
            worst = rc if rc in _SEVERITY else RC_REFUSED
    return worst


#: What this gate would have examined, for the NO_CORPUS / UNDETERMINED line. A
#: zero is stated over a NAMED population or it is not stated at all.
_SCANNED = "published head-to-head record(s)"
_GATE = "PPA head-to-head records"


def check_corpus(named: Path, may_be_absent: bool = False) -> int:
    # A CORPUS THAT IS NOT THERE IS NOT AN EMPTY CORPUS, and until this branch
    # existed those two were byte-identical here: `Path.glob` yields nothing for
    # a missing directory, so both printed `0 head-to-head record(s) found` and
    # both exited 2. That is a denominator asserted over a population nobody
    # searched. It was not hypothetical — the only caller in the tree points at
    # `<repo>/benchmark-data`, and that tree moved to its own repository in
    # v1.10.56, so this gate has been certifying a clean empty population over a
    # path that is absent.
    #
    # Resolved through `_corpus_location` rather than a fourth hand-rolled
    # answer: that module exists because three gates re-derived this same
    # question on the same day and got it wrong the same way, and it keeps the
    # four outcomes apart — a pointer that is SET AND WRONG stays UNDETERMINED
    # and is never excused by the opt-in, while "the corpus lives in another
    # repository" is a separate, stated NO_CORPUS. The flow's call site names
    # the project directory, which always exists, so it never reaches here.
    corpus, origin = _corpus.resolve(named, gate=_GATE, announce=True)
    if not corpus.is_dir():
        return _corpus.refuse(_GATE, named, corpus, origin, may_be_absent,
                              _SCANNED)
    recs = corpus_records(corpus)
    print(f"ppa_head_to_head_check --corpus {corpus}: "
          f"{len(recs)} head-to-head record(s) found")
    if not recs:
        print("VACUOUS: the corpus carries no head-to-head record, so nothing "
              "was validated. This is NOT a pass — the first head-to-head run "
              "has not been published yet (vibe-ic#1121). rc=2.",
              file=sys.stderr)
        return RC_UNDETERMINED
    rcs = [main([str(r)]) for r in recs]
    worst = worst_rc(rcs)
    refused = sum(1 for rc in rcs if rc == RC_REFUSED)
    undet = sum(1 for rc in rcs if rc == RC_UNDETERMINED)
    print(f"ppa_head_to_head_check --corpus {corpus}: {len(recs)} record(s), "
          f"{refused} refused, {undet} undetermined, "
          f"{len(recs) - refused - undet} accepted -> rc={worst}")
    if refused:
        print(f"REFUSED: {refused} of {len(recs)} record(s) cannot support the "
              f"claim printed on them. An undetermined record beside a refused "
              f"one does not soften it.", file=sys.stderr)
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
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="this repository need not carry the published corpus "
                         "(vibe-ic#1710). Turns 'nothing anywhere' into a "
                         "stated NO_CORPUS that names its zero, and NEVER "
                         "excuses a $VIBE_IC_BENCHMARK_DATA that is set and "
                         "unreadable.")
    ap.add_argument("--json", default=None, help="optional JSON report path")
    args = ap.parse_args(argv)
    if args.corpus is not None:
        return check_corpus(Path(args.corpus).resolve(),
                            args.corpus_may_be_absent)
    if not args.record:
        ap.error("give a record path or --corpus DIR")

    rc, report = evaluate(Path(args.record))
    print(format_report(rc, report))
    if args.json:
        atomic_write_text(Path(args.json), 
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
