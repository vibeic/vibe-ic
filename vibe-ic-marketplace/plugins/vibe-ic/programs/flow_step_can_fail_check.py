#!/usr/bin/env python3
"""flow_step_can_fail_check — a step whose gate cannot fail must say so.

WHY
===
The flow-gate dashboard publishes eight per-step dimensions, one of which asks
"can this step actually fail". It reads 62 of 63 clean. Nothing recomputes it —
the page's own generator says so in its docstring and carries the distribution
forward untouched, so the figure is a judgement someone made once.

Recomputed from the flow yaml, SEVEN of the 68 steps have no criterion capable
of failing on content (it was EIGHT until step 12 was given
`program_exit_zero: dft_post_optimization_scan_survival_check` in 23d96bf55,
which is why the entry below is gone rather than merely quiet):

    no blocking criterion at all
      P0   Structural-RTL pre-flight            (no `gate:` key)
      14   Synthesis handoff gate               (only optional_program_exit_zero)

    judged only by "the declared file exists and is non-empty"
      1    Spec-to-RTL
      18   Spare-cell + ECO-prep insertion
      27   Signal Integrity (crosstalk / noise / glitch)
      32   Post-route timing repair pass
      35   DFM screen

Step 32 is not hypothetical. A run recorded `eco_needed=true, changes_count=0,
re_verified=false` — an ECO that changed nothing and was never re-verified — and
the step passed, because a file existed and its program criterion is optional.
An ECO raised and not applied is indistinguishable from no ECO at all, and the
step said PASS.

WHAT THIS CHECKS
================
For every step in the canonical flow, whether its `gate:` declares at least one
criterion that can FAIL the step:

    blocking       program_exit_zero · files_exist · json_field_true
    non-blocking   advisory_program_exit_zero · optional_program_exit_zero

`all_of` / `any_of` are walked. A step with no blocking criterion cannot fail on
anything its gate examines; a step whose only blocking criterion is
`files_exist` can fail only on absence, never on content — a file written by a
tool that got the wrong answer passes it.

Both are reported, and both are held to a baseline that MAY ONLY SHRINK. The
baseline is not an excuse: it exists because failing eight pre-existing entries
on day one produces a gate people route around, and a gate that is blocking for
anything NEW from its first run is the property worth having.

Removing an entry means giving that step a criterion that can fail. Deleting the
entry without doing so is the one repair this file exists to prevent.

EXIT
    0  no step outside the baseline lacks a failing criterion
    1  a step does — or a baseline entry now has one and the baseline should shrink
    2  the flow yaml could not be read or contains no steps. A gate that scanned
       nothing has not passed; see the rc=2 convention used across this repo.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:                                   # pragma: no cover
    yaml = None

BLOCKING = {"program_exit_zero", "files_exist", "json_field_true"}
NON_BLOCKING = {"advisory_program_exit_zero", "optional_program_exit_zero"}
COMBINATORS = {"all_of", "any_of"}

# Steps that already lack a failing criterion. MAY ONLY SHRINK.
# `reason` records WHICH of the two shapes it is, so a reader can tell
# "nothing can fail here" from "only absence can fail here" without re-deriving.
BASELINE: Dict[str, str] = {
    "P0": "no gate key at all",
    "14": "only optional_program_exit_zero",
    "1": "files_exist only — fails on absence, never on content",
    "18": "files_exist only — fails on absence, never on content",
    "27": "files_exist only — fails on absence, never on content",
    "32": "files_exist only — fails on absence, never on content",
    "35": "files_exist only — fails on absence, never on content",
}


def criteria(gate) -> Set[str]:
    """Every criterion kind this gate declares, with combinators walked."""
    out: Set[str] = set()
    if isinstance(gate, dict):
        for k, v in gate.items():
            if k in COMBINATORS and isinstance(v, (list, tuple)):
                for x in v:
                    out |= criteria(x)
            else:
                out.add(k)
    elif isinstance(gate, (list, tuple)):
        for x in gate:
            out |= criteria(x)
    return out


def load_steps(path: Path) -> Optional[List[dict]]:
    if yaml is None:
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    steps: List[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                steps.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    # stage containers are not steps; they carry no gate of their own
    return [s for s in steps if not str(s.get("id", "")).startswith("stage")]


def classify(step: dict) -> Tuple[bool, str]:
    """(can this step fail on content, why not)."""
    kinds = criteria(step.get("gate"))
    if not kinds:
        return False, "no gate key at all"
    blocking = kinds & BLOCKING
    if not blocking:
        only = "/".join(sorted(kinds & NON_BLOCKING)) or "/".join(sorted(kinds))
        return False, f"only {only}"
    if blocking == {"files_exist"}:
        return False, "files_exist only — fails on absence, never on content"
    return True, ""


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flow", type=Path,
                    default=here.parent / "flow" / "phase1_phase2_phase3.yaml")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    if yaml is None:
        print("flow_step_can_fail_check: rc=2 NOT CHECKED — pyyaml unavailable")
        return 2
    steps = load_steps(a.flow)
    if not steps:
        print(f"flow_step_can_fail_check: rc=2 NOT CHECKED — no steps in {a.flow}")
        return 2

    weak: Dict[str, str] = {}
    for s in steps:
        ok, why = classify(s)
        if not ok:
            weak[str(s["id"])] = why

    names = {str(s["id"]): str(s.get("name", ""))[:64] for s in steps}
    present = set(names)
    new = {k: v for k, v in weak.items() if k not in BASELINE}
    # A baseline entry is FIXED only when its step is still here and now has a
    # criterion that can fail. An entry whose step is ABSENT is a different
    # thing — the step was renamed or removed — and conflating the two makes
    # this gate fire on any flow that does not happen to contain all eight,
    # which is every synthetic fixture and every partial flow.
    fixed = [k for k in BASELINE if k in present and k not in weak]
    gone = [k for k in BASELINE if k not in present]

    rec = {"steps": len(steps), "cannot_fail_on_content": weak,
           "baseline": BASELINE, "new": new, "now_fixed": fixed,
           "baseline_steps_absent": gone}
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")

    if new:
        print(f"flow_step_can_fail_check: FAIL — {len(new)} step(s) gained a gate "
              f"that cannot fail on content:")
        for k, v in sorted(new.items()):
            print(f"    step {k:<4} {names.get(k, '')}")
            print(f"             {v}")
        print("    A step whose gate cannot fail certifies nothing. Give it a "
              "criterion that can, or record it in BASELINE with the reason.")
        return 1

    if fixed:
        print(f"flow_step_can_fail_check: FAIL — {len(fixed)} baseline entr(ies) "
              f"now have a failing criterion: {', '.join(sorted(fixed))}")
        print("    Good news, and the baseline must shrink to match — it exists to "
              "record what is still weak, not to keep saying so after it is fixed.")
        return 1

    if gone:
        print(f"flow_step_can_fail_check: note — {len(gone)} baseline step(s) not "
              f"present in this flow: {', '.join(sorted(gone))}")
    print(f"flow_step_can_fail_check: PASS — {len(steps)} step(s); "
          f"{len(steps) - len(weak)} can fail on content, {len(weak)} cannot and "
          f"are the recorded baseline (may only shrink)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
