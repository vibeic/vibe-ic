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
    whose value is a list naming one or more DECLARED STEP IDS is a second
    membership declaration, whatever it is called. Renaming `steps:` to
    `members:` does not evade this.

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
from typing import Any, Dict, List

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
    out: List[str] = []
    if isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_flatten(v))
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_flatten(v))
    elif value is not None and not isinstance(value, bool):
        out.append(str(value))
    return out


def analyze(doc: Dict[str, Any]) -> Dict[str, Any]:
    """The whole predicate, over an already-parsed flow document."""
    stages = [s for s in (doc.get("stages") or []) if isinstance(s, dict)]
    steps = [s for s in (doc.get("steps") or []) if isinstance(s, dict)]
    declared_ids = [str(s.get("id")) for s in stages if s.get("id") is not None]
    step_ids = set(_step_ids(doc))

    # P1 — a roster is any stage key whose value names declared step ids.
    rosters: List[Dict[str, Any]] = []
    for st in stages:
        for key, value in st.items():
            if key in _NON_MEMBERSHIP_KEYS:
                continue
            named = [v for v in _flatten(value) if v in step_ids]
            if named:
                rosters.append({"stage": str(st.get("id")), "key": str(key),
                                "names_steps": named})

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

    sizes = ", ".join(f"{k}={len(v)}"
                      for k, v in sorted(rec["membership"].items()))
    print(f"{_NAME}: PASS — {rec['steps_examined']} step(s) across "
          f"{rec['stages_examined']} declared stage(s); membership declared once, "
          f"on the step. Sizes: {sizes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
