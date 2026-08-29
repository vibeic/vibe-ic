#!/usr/bin/env python3
"""skill_stage_membership_check — every shipped skill says WHERE IN THE FLOW it applies.

WHY THIS EXISTS
===============
MEASURED on main at v1.12.93: the tree ships 70 skills and a stage names only
29. FORTY-ONE belonged to no stage at all, including SEVEN OF THE EIGHT members
of the `verification` tier -- the tier whose own description in
`skills/_classification.json` is "Run AFTER program PASS to spot-check the
deterministic output. AI MUST invoke before claiming PASS to user." v1.12.87
wired the first of the eight (stage1's `on_pass_review`). The other seven had
no attachment, and TWO STAGES NAMED ZERO SKILLS while carrying real steps:
`stage_phase1` (2 steps) and `stage5_manufacturing` (5).

"41 skills belong to no stage" is an AMBIGUOUS SENTENCE, and that ambiguity is
the thing this check removes. It conflates a skill that is correctly outside
the flow with a stage that is missing its AI half -- opposite facts that one
number cannot tell apart. With the axis declared, the residue is unambiguous:
a skill in no stage, not `stage_all` and not `off_flow` is a GAP, and it is the
only thing left in that bucket.

THE AXIS
========
The flow's OWN `stage:` field -- the eight values declared in
`flow/phase1_phase2_phase3.yaml` -- plus two values that are NOT flow stages:

    a named stage (or several)   it applies there, and the entry says why
    stage_all                    a POSITIVE CLAIM: worth invoking at EVERY
                                 stage. Multi-stage is NOT all-stage.
    off_flow                     a POSITIVE CLAIM: its subject is the plugin,
                                 the repo, the CI or the benchmark programme --
                                 not a design passing through the flow.
    NEITHER                      a gap, reported by this program.

`off_flow` exists because the 41 did NOT split cleanly into stage/stage_all.
Forcing a repo-maintenance cron into `stage_all` would have made that value
mean "anything I could not place", which is the failure the name was chosen to
prevent. Same shape as `unbuilt_skills`: when three options were all dishonest,
declare an honest fourth rather than distort one of the three.

NO FOURTH MAPPING
=================
There are already three tables (the flow yaml, `benchmark/CAPTURE_ROUTING.json`,
`skills/_classification.json`) and this adds none. A skill NAMED BY A STEP --
in that step's `skills:` list or in its stage's `on_pass_review:` -- inherits
that step's stage BY DERIVATION and must NOT also be declared: P4 below fails
on that second declaration, for the same reason
`flow_stage_membership_single_declaration_check` deleted the step roster.

WHAT THIS CHECKS
================
P1  COVERAGE.   Every shipped skill is placed: derived from the flow, or
                declared with a NON-EMPTY stage list (a named stage,
                `stage_all`, or `off_flow`). A NAME IS NOT A PLACEMENT: an
                entry whose `stages` is absent or `[]` is the UNDECIDED state
                and is reported, not counted as placed.
P2  REFERENTIAL INTEGRITY.  Every stage named in a declaration is a stage the
                flow actually declares (or `stage_all` / `off_flow`). A typo
                must not silently create a stage nobody runs.
P3  THE AXIS-ONLY VALUES ARE NOT FLOW STAGES.  `stage_all` / `off_flow` must
                never appear in the flow's own `stages[]`.
P4  SINGLE DECLARATION.  A skill the flow already names must not ALSO be
                declared here.
P5  EXCLUSIVITY.  `stage_all` and `off_flow` are whole-skill verdicts: neither
                may be combined with a named stage or with each other.
P6  STAGE_ALL STAYS A CLAIM.  `stage_all` must stay small enough to be a claim
                rather than a bucket. (Non-vacuity of the shipped declaration
                is a property of this repo, not of the checker, and is
                asserted in this program's test instead.)

EXIT CODES
==========
0  every shipped skill is placed and every rule above holds
1  at least one finding (this is the RED the axis must be able to go)
2  an input could not be read -- never confused with "no findings"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
AXIS_ONLY = ("stage_all", "off_flow")
# A stage_all population above this stops being a claim and starts being a
# bucket. Raise it only with a defence for each member, never to go green.
STAGE_ALL_CEILING = 6


def _load(plugin: Path):
    import yaml

    flow = plugin / "flow" / "phase1_phase2_phase3.yaml"
    cls = plugin / "skills" / "_classification.json"
    doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    cj = json.loads(cls.read_text(encoding="utf-8"))
    return doc, cj


def _iter_steps(node):
    if isinstance(node, dict):
        if "id" in node and ("name" in node or "stage" in node):
            yield node
        for v in node.values():
            yield from _iter_steps(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_steps(v)


def shipped_skills(plugin: Path) -> set[str]:
    d = plugin / "skills"
    return {p.name for p in d.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}


def derived_attachment(doc) -> dict[str, set[str]]:
    """skill -> {stage, ...}, from the flow ALONE. Never re-declared.

    A STAGE WRAPPER IS ITS OWN STAGE, and missing that reported a wired skill
    as an unplaced gap. `on_pass_review` is declared on the STAGE entry (that
    is the whole point of v1.12.87 -- 76 steps is the wrong granularity for
    eight reviewers), and the eight stage wrappers carry NO `stage:` field of
    their own: their `id` IS the stage. Reading only `stage:` therefore skipped
    every stage-level reviewer -- measured, it reported `phase2-rtl-verify`
    (wired by v1.12.87) as belonging to no stage.
    """
    wrappers = flow_stage_names(doc)
    out: dict[str, set[str]] = {}
    for s in _iter_steps(doc):
        sid = str(s.get("id") or "")
        stage = sid if sid in wrappers else str(s.get("stage") or "")
        if not stage:
            continue
        for sk in (s.get("skills") or []):
            if isinstance(sk, str) and sk:
                out.setdefault(sk, set()).add(stage)
        opr = s.get("on_pass_review")
        if isinstance(opr, dict) and isinstance(opr.get("skill"), str):
            out.setdefault(opr["skill"], set()).add(stage)
    return out


def declared_axis(cj) -> dict[str, list[str]]:
    """skill -> [stage, ...] from the _classification.json declaration.

    An entry whose `stages` is absent or empty is KEPT, with an empty list, so
    that P1 can tell "declared, and says nothing" apart from "not declared at
    all". Both are unplaced; only the first can be fixed by editing an entry
    that already exists, so the finding names them differently.
    """
    axis = cj.get("stage_axis", {})
    out: dict[str, list[str]] = {}
    for bucket in ("stages", "stage_all", "off_flow"):
        for name, entry in (axis.get(bucket) or {}).items():
            out[name] = list(entry.get("stages") or [])
    return out


def flow_stage_names(doc) -> set[str]:
    return {str(s.get("id")) for s in (doc.get("stages") or []) if s.get("id")}


def analyse(plugin: Path):
    doc, cj = _load(plugin)
    shipped = shipped_skills(plugin)
    derived = derived_attachment(doc)
    declared = declared_axis(cj)
    stages = flow_stage_names(doc)
    findings: list[str] = []

    # A NAME IS NOT A PLACEMENT, and testing membership by KEY was a guard that
    # could not say no about its own subject. `placed` used to read
    # `s in derived or s in declared`, so an entry whose `stages` was absent or
    # `[]` still counted as placed -- the skill was "placed" because somebody
    # had written its name down. MEASURED on the shipped file: deleting
    # `spec-review`'s entire `stages` list (a shipped skill the flow names
    # nowhere, so it cannot fall back to derivation) still returned rc 0 and
    # "70 skills placed ... no unplaced skill". Once every name was listed, no
    # edit to the stages themselves could produce the one state P1 could see.
    # Placement now requires a NON-EMPTY stage list -- the truthiness of the
    # list, not the presence of the key.
    placed = {s for s in shipped if s in derived or declared.get(s)}
    # P1 -- the gap this program exists to report.
    gaps = sorted(shipped - placed)
    if gaps:
        empty = sorted(g for g in gaps if g in declared)
        missing = sorted(g for g in gaps if g not in declared)
        detail = []
        if missing:
            detail.append(f"not declared at all: {missing}")
        if empty:
            detail.append(
                f"declared but naming NO stage: {empty} -- an entry with an "
                f"absent or empty `stages` list is the UNDECIDED state, not a "
                f"placement")
        findings.append(
            f"P1 UNPLACED ({len(gaps)}): " + "; ".join(detail) + ". Each names "
            f"no stage, and is neither stage_all nor off_flow. Declare where it "
            f"applies under stage_axis in skills/_classification.json, or say "
            f"why it is off_flow. If you cannot decide, that is UNDECIDED -- "
            f"report the question, do not park it in stage_all.")
    # P2
    bad = sorted({v for sk in declared for v in declared[sk]
                  if v not in stages and v not in AXIS_ONLY})
    if bad:
        findings.append(
            f"P2 UNKNOWN STAGE {bad}: not declared in the flow's stages[] and "
            f"not one of {list(AXIS_ONLY)}. A typo must not invent a stage.")
    # P3
    leaked = sorted(set(AXIS_ONLY) & stages)
    if leaked:
        findings.append(
            f"P3 {leaked} appear in the flow's own stages[]. These are "
            f"SKILL-AXIS values, not flow stages; the flow must not declare "
            f"them or flow_stage_membership_single_declaration_check P3 would "
            f"demand steps for them.")
    # P4
    both = sorted(set(derived) & set(declared))
    if both:
        findings.append(
            f"P4 DOUBLE DECLARATION {both}: the flow already names these, so "
            f"their stage is DERIVED. Remove the stage_axis entry -- one "
            f"premise, one place.")
    # P5
    for sk, vals in sorted(declared.items()):
        axis_vals = [v for v in vals if v in AXIS_ONLY]
        if axis_vals and len(vals) > 1:
            findings.append(
                f"P5 {sk} combines {axis_vals} with {sorted(set(vals) - set(axis_vals))}. "
                f"stage_all and off_flow are whole-skill verdicts and are "
                f"exclusive of a named stage and of each other.")
    # P6. NOT a "the declaration must be big" rule: that is a property of THIS
    # repo, not of the checker, and asserting it here made the program refuse
    # any small tree `--plugin` was pointed at -- including the fixtures that
    # prove it discriminates. Non-vacuity of the SHIPPED declaration is
    # asserted where it belongs, in test_control_the_axis_actually_places_a_lot.
    n_all = sum(1 for v in declared.values() if "stage_all" in v)
    if n_all > STAGE_ALL_CEILING:
        findings.append(
            f"P6 stage_all holds {n_all} skills (ceiling {STAGE_ALL_CEILING}). "
            f"stage_all is a claim that a skill is useful at EVERY stage; at "
            f"this population it has become a bucket. Place them, or report "
            f"them as UNDECIDED.")

    per_stage: dict[str, set[str]] = {}
    for sk, vals in list(derived.items()) + [(k, v) for k, v in declared.items()]:
        if sk not in shipped:
            continue
        for v in vals:
            per_stage.setdefault(v, set()).add(sk)
    return findings, {
        "shipped": len(shipped),
        "derived_from_flow": len([s for s in derived if s in shipped]),
        "declared": len(declared),
        "unplaced": gaps,
        "per_stage": {k: sorted(v) for k, v in sorted(per_stage.items())},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plugin", default=str(PLUGIN),
                    help="plugin tree to check (default: this file's own)")
    ap.add_argument("--json", help="write the report here")
    a = ap.parse_args(argv)
    plugin = Path(a.plugin).resolve()
    try:
        findings, report = analyse(plugin)
    except Exception as exc:  # unreadable input is rc 2, never a silent PASS
        print(f"[SKIP] skill_stage_membership_check: cannot read input: {exc}")
        return 2
    report["findings"] = findings
    report["verdict"] = "FAIL" if findings else "PASS"
    if a.json:
        out = Path(a.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for f in findings:
        print(f"[FAIL] {f}")
    if not findings:
        print(f"[PASS] skill_stage_membership_check: {report['shipped']} skills "
              f"placed ({report['derived_from_flow']} derived from the flow, "
              f"{report['declared']} declared); no unplaced skill.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
