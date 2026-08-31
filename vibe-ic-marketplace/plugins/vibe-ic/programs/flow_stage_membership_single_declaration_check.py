#!/usr/bin/env python3
"""flow_stage_membership_single_declaration_check — stage membership is declared once.

WHY THIS EXISTS (vibe-ic#923)
=============================
`flow/phase1_phase2_phase3.yaml` used to say which stage a step belongs to in
TWO independent places:

    1. a per-stage roster   stages[].steps: [14, 15, 16, ...]
    2. a per-step field     steps[].stage: stage3

Neither was derived from the other and nothing compared them, so they drifted.
Measured on the flow as committed at f6a7f9d1, the two declarations disagreed
for 12 of the 63 steps:

    contradictions (4)   14  roster=stage3                field=stage2
                         32  roster=stage4                field=stage3
                         38  roster=stage5_manufacturing  field=stage4
                         39  roster=stage5_manufacturing  field=stage4

    roster omissions (8) 42, 43, 44, DT1, DT2, DT3, FS1, P0 carried a field
                         and appeared in no roster at all

The roster was deleted rather than the field, because the roster was never the
live declaration: every shipped consumer that places a step in a stage reads
`steps[].stage`, and the single program that loads `stages[]` at all
(`phase1_planned_consumer_starved_check`) reads only `id` and `condition` from
it. Deleting it moved no step for any program.

WHAT THIS CHECKS
================
P1  SECOND DECLARATION.  No `stages[]` entry may carry a membership roster.
    A roster is DISCOVERED, not matched by key name: any key on a stage entry
    that names DECLARED STEP IDS **in a collection** — a list or tuple at any
    depth — or that names TWO OR MORE distinct step ids by any shape, is a
    second membership declaration, whatever it is called. Renaming `steps:` to
    `members:` does not evade this, and neither does a one-element roster: a
    list of one is still a list.

    A KEY THAT NAMES EXACTLY ONE STEP ID, REACHED ONLY THROUGH SCALARS, IS A
    REFERENCE AND NOT A DECLARATION. The two are not the same object and the
    difference is testable rather than stylistic:

        a ROSTER assigns steps TO a stage. Delete `steps[].stage` and the
        roster still tells you the membership — which is exactly what makes it
        a second declaration, and what let it drift for 12 of 63 steps.

        a BACK-POINTER names the ONE step that dispatches a stage-scoped
        clause. Delete `steps[].stage` and it recovers nothing. It names one
        step out of a stage of up to twenty, and MEASURED on the shipped flow,
        five of the six `dispatched_by` pointers name a step that is NOT in the
        stage carrying the clause (a stage's on-pass review is dispatched from
        the stage that follows it) — a roster naming a step in another stage
        would be the #923 contradiction, so these cannot be rosters.

    Before this reading, `_flatten` walked the whole `on_pass_review` sub-tree
    and collected the single scalar `dispatched_by: '7'`, so the flow went red
    on P1 at the moment it obeyed its own "a clause dispatched by nothing is not
    a gate" doctrine (`on_pass_review_declared_command_runs_check` P3, and
    `test_on_pass_review_clauses_are_dispatched_by_nothing.py` before it, which
    measured five stage-level clauses dispatched 0 times in a 125-gate ledger on
    a real published cell). There was NO state of the flow in which both gates
    were green: as shipped this check FAILED with 6 findings and P3 passed; with
    the six `dispatched_by` lines cut this check passed and P3 FAILED with 6.

    THE BOUND, stated rather than discovered later: a one-step roster written as
    a bare SCALAR (`steps: 14`) reads as a reference here. It is not silent —
    every such reference is listed in the record and printed as REFERENCE — but
    it is not a finding. Closing it structurally is not possible without
    key-name matching, which is the thing this predicate was written to avoid.

P2  REFERENTIAL INTEGRITY.  Every step must carry a non-empty `stage:` naming
    a stage declared in `stages[]`. This is what stops the P1 finding from
    being satisfied by deleting the surviving declaration instead of the
    duplicate one.

P3  NO DEAD STAGE.  Every declared stage must be named by at least one step.
    A stage nothing belongs to is a third way to lose membership silently.

Exit 0 = one declaration, intact. Exit 2 = a second declaration, a dangling
reference, or a dead stage. Exit 2 also for "could not check" (no flow file,
no parser) — a checker that cannot read its input must not report clean.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - environment without pyyaml
    yaml = None  # type: ignore

_NAME = "flow_stage_membership_single_declaration_check"

#: Keys on a `stages[]` entry that declare the stage's IDENTITY or its
#: CONDITION rather than its membership. Everything else is examined for
#: step ids; this is a list of what is EXEMPT, not a list of what is checked,
#: so a newly invented membership key is caught by default.
_NON_MEMBERSHIP_KEYS = ("id", "name", "condition", "description")


def _step_ids(doc: Dict[str, Any]) -> List[str]:
    return [str(s.get("id")) for s in (doc.get("steps") or [])
            if isinstance(s, dict) and s.get("id") is not None]


def _flatten(value: Any) -> List[str]:
    """Every scalar reachable from ``value``, as a string."""
    collected, scalar = _reachable(value, False)
    return collected + scalar


def _reachable(value: Any, in_collection: bool) -> Tuple[List[str], List[str]]:
    """``(reached through a list/tuple, reached only through scalars/maps)``.

    The split is the whole of P1's roster-vs-reference distinction, and it is a
    property of the CONTAINER, not of the count: a one-element list is still a
    collection, so `members: [14]` cannot evade the roster rule by being short.
    """
    collected: List[str] = []
    plain: List[str] = []
    if isinstance(value, (list, tuple)):
        for v in value:
            got_c, got_p = _reachable(v, True)
            collected.extend(got_c + got_p)
    elif isinstance(value, dict):
        for v in value.values():
            got_c, got_p = _reachable(v, in_collection)
            collected.extend(got_c)
            (collected if in_collection else plain).extend(got_p)
    elif value is not None and not isinstance(value, bool):
        (collected if in_collection else plain).append(str(value))
    return collected, plain


def analyze(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The whole predicate, over an already-parsed flow document."""
    stages = [s for s in (doc.get("stages") or []) if isinstance(s, dict)]
    steps = [s for s in (doc.get("steps") or []) if isinstance(s, dict)]
    declared_ids = [str(s.get("id")) for s in stages if s.get("id") is not None]
    step_ids = set(_step_ids(doc))

    # P1 — a roster is any stage key that names declared step ids IN A
    # COLLECTION, or that names two or more distinct ids by any shape. A key
    # naming exactly one id through scalars alone is a REFERENCE: recorded and
    # printed, never a finding. See the P1 paragraph in the module docstring.
    rosters: List[Dict[str, Any]] = []
    references: List[Dict[str, Any]] = []
    for st in stages:
        for key, value in st.items():
            if key in _NON_MEMBERSHIP_KEYS:
                continue
            in_coll, plain = _reachable(value, False)
            named_coll = [v for v in in_coll if v in step_ids]
            named_plain = [v for v in plain if v in step_ids]
            named = named_coll + named_plain
            if not named:
                continue
            if named_coll or len(set(named)) >= 2:
                rosters.append({"stage": str(st.get("id")), "key": str(key),
                                "names_steps": named,
                                "why": ("in a collection" if named_coll
                                        else "names 2+ distinct steps")})
            else:
                references.append({"stage": str(st.get("id")),
                                   "key": str(key), "names_step": named[0]})

    # P2 — every step's stage must resolve.
    dangling: List[Dict[str, str]] = []
    for s in steps:
        stage = s.get("stage")
        sid = str(s.get("id"))
        if stage is None or str(stage).strip() == "":
            dangling.append({"step": sid, "stage": "", "why": "no stage field"})
        elif str(stage) not in declared_ids:
            dangling.append({"step": sid, "stage": str(stage),
                             "why": "not declared in stages[]"})

    # P3 — every declared stage must have a member.
    claimed = {str(s.get("stage")) for s in steps if s.get("stage") is not None}
    dead = [sid for sid in declared_ids if sid not in claimed]

    members: Dict[str, List[str]] = {}
    for s in steps:
        if s.get("stage") is not None:
            members.setdefault(str(s["stage"]), []).append(str(s.get("id")))

    return {
        "stages_examined": len(stages),
        "steps_examined": len(steps),
        "declared_stage_ids": declared_ids,
        "second_declarations": rosters,
        "step_references": references,
        "dangling_stage_refs": dangling,
        "stages_with_no_members": dead,
        "membership": members,
        "findings": len(rosters) + len(dangling) + len(dead),
    }


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flow", type=Path,
                    default=here.parent / "flow" / "phase1_phase2_phase3.yaml",
                    help="flow yaml to check (default: the shipped flow)")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the full record to this path")
    a = ap.parse_args(argv)

    if yaml is None:
        print(f"{_NAME}: rc=2 NOT CHECKED — pyyaml unavailable")
        return 2
    if not a.flow.is_file():
        print(f"{_NAME}: rc=2 NOT CHECKED — no flow file at {a.flow}")
        return 2
    try:
        doc = yaml.safe_load(a.flow.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"{_NAME}: rc=2 NOT CHECKED — {a.flow} did not parse: {exc}")
        return 2
    if not isinstance(doc, dict):
        print(f"{_NAME}: rc=2 NOT CHECKED — {a.flow} is not a mapping")
        return 2

    rec = analyze(doc)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")

    if rec["stages_examined"] == 0 or rec["steps_examined"] == 0:
        print(f"{_NAME}: rc=2 NOT CHECKED — {a.flow} declares "
              f"{rec['stages_examined']} stage(s) and {rec['steps_examined']} "
              f"step(s); a zero denominator cannot certify a single declaration")
        return 2

    bad = False
    if rec["second_declarations"]:
        bad = True
        print(f"{_NAME}: FAIL — {len(rec['second_declarations'])} second "
              f"membership declaration(s) in stages[]:")
        for r in rec["second_declarations"]:
            shown = ", ".join(r["names_steps"][:8])
            more = "" if len(r["names_steps"]) <= 8 else f", +{len(r['names_steps']) - 8} more"
            print(f"    stage {r['stage']}: key `{r['key']}` names step(s) {shown}{more}")
        print("    Stage membership is declared by the per-step `stage:` field. A "
              "roster here is a second copy nothing derives or reconciles, and it "
              "drifted for 12 of 63 steps before it was removed (vibe-ic#923).")

    if rec["dangling_stage_refs"]:
        bad = True
        print(f"{_NAME}: FAIL — {len(rec['dangling_stage_refs'])} step(s) whose "
              f"`stage:` does not resolve:")
        for d in rec["dangling_stage_refs"]:
            print(f"    step {d['step']:<5} stage={d['stage']!r} — {d['why']}")
        print("    The per-step field is the ONLY membership declaration; a step "
              "without a resolvable one belongs to no stage at all.")

    if rec["stages_with_no_members"]:
        bad = True
        print(f"{_NAME}: FAIL — {len(rec['stages_with_no_members'])} declared "
              f"stage(s) that no step names: "
              f"{', '.join(rec['stages_with_no_members'])}")
        print("    A stage with no member is either a dead declaration or a sign "
              "that steps were moved out of it without removing it.")

    if bad:
        return 2

    for r in rec["step_references"]:
        print(f"{_NAME}: REFERENCE — stage {r['stage']}: key `{r['key']}` "
              f"names one step ({r['names_step']}) through a scalar. A "
              f"reference, not a membership declaration; listed so it is not "
              f"silent.")

    sizes = ", ".join(f"{k}={len(v)}"
                      for k, v in sorted(rec["membership"].items()))
    print(f"{_NAME}: PASS — {rec['steps_examined']} step(s) across "
          f"{rec['stages_examined']} declared stage(s); membership declared once, "
          f"on the step. Sizes: {sizes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
