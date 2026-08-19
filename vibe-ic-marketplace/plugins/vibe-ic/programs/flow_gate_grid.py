#!/usr/bin/env python3
"""flow_gate_grid — recompute the flow-gate grid, and say which cells cannot be.

WHY
===
The dashboard publishes 68 steps x 8 dimensions = 544 cells under the words
"every cell is a predicate recomputed against the current source, not a stored
verdict read back". Nothing recomputed them: the page's own generator says so in
its docstring and carries the eight distributions forward. (The grid was 63 x 8
= 504 when this was found; the shape of the defect is independent of its size,
and the figures here are the live ones.)

This program recomputes every dimension that IS decidable from the flow source,
and for the rest says plainly that it is not and why — because the alternative,
inventing a plausible predicate, produces a grid that measures something
ADJACENT to what it claims, which is the defect the whole review was about.

WHAT IS RECOMPUTED, AND WHAT IS NOT
===================================
  D1 wiring     every gate criterion that names a program must name one that
                EXISTS. A criterion pointing at a missing program never runs and
                cannot fail; the step then rests on whatever else the gate has.
  D2 runnable   delegated to `flow_step_can_fail_check` — one implementation.
  D5 deps       delegated to `flow_dependency_graph_check` — one implementation.
  D6 skip       a step with a `condition` must declare `condition_kind`. The
                consumer branches on it (`design_dependent` -> silent skip;
                `setup_required` -> SKIPPED-SETUP-REQUIRED unless waived) and NO
                step declares it, so every conditional skip falls to the benign
                default and the discriminator between "this design legitimately
                has none" and "someone forgot to author the trigger" is dead.
  D8 catcher    every `required_outputs` entry must have a gate criterion that
                would fail on its absence.

  D3 outputs    NOT DERIVABLE FROM SOURCE. "required_outputs really exist and are
                non-empty" is a fact about a RUN. The page's framing is wrong for
                this dimension, not merely stale.
  D4 criteria   NOT DERIVABLE. "does the thing measured match the thing claimed"
                is semantic. A mechanical stand-in here would be exactly the
                proxy-for-property substitution under review.
  D7 list       NOT DERIVABLE. Whether a declared output list is COMPLETE needs
                knowledge of what the step ought to produce.

Reporting a dimension as NOT DERIVABLE is the point, not a gap: it is what stops
the page claiming those cells are live.

EXIT
    0  every recomputable dimension is clean
    1  at least one is not — each finding names the steps
    2  the flow could not be read, or declares no steps
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:                                     # pragma: no cover
    yaml = None

PROGRAM_KEYS = {"program_exit_zero", "advisory_program_exit_zero",
                "optional_program_exit_zero"}
BLOCKING = {"program_exit_zero", "files_exist", "json_field_true"}
COMBINATORS = {"all_of", "any_of"}

# Steps that declare a `condition` and no `condition_kind`. MAY ONLY SHRINK.
#
# Not a list of permissions: most of these ARE design-dependent (analog on a
# digital design, manufacturing steps that need a fab). The defect is that none
# of them SAYS so, so the field the consumer branches on is never set and the
# `setup_required` path — the one that tells "this design legitimately has none"
# from "someone forgot to author the trigger" — is unreachable.
#
# Declaring the kind per step is a judgement about that step, made by whoever
# knows it. Guessing 22 classifications here would put the same silence back
# under a different name.
D6_BASELINE = {
    "40", "41", "42", "43", "44",              # manufacturing, need a fab
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",   # analog track
    "DT1", "DT2", "DT3",                       # transition-delay ATPG
    "FS1",                                     # ISO-26262 FMEDA
    "M1", "M2", "M3", "M4",                    # mixed-signal
}

# Steps declaring outputs with no criterion that would fail on their absence.
# MAY ONLY SHRINK. Step 14's gate is `optional_program_exit_zero` only, which is
# the same finding `flow_step_can_fail_check` records — kept here too because
# the two ask different questions and a reader of one should not have to know
# about the other.
D8_BASELINE = {"14"}

NOT_DERIVABLE = {
    "D3 outputs": ("'required_outputs really exist and are non-empty' is a fact "
                   "about a RUN, not about the source tree"),
    "D4 criteria": ("'does the thing measured match the thing claimed' is "
                    "semantic; a mechanical stand-in would be the very "
                    "proxy-for-property substitution under review"),
    "D7 list": ("whether a declared output list is COMPLETE needs knowledge of "
                "what the step ought to produce"),
}


def criteria(gate) -> List[Tuple[str, object]]:
    """Every (kind, value) the gate declares, with combinators walked."""
    out: List[Tuple[str, object]] = []
    if isinstance(gate, dict):
        for k, v in gate.items():
            if k in COMBINATORS and isinstance(v, (list, tuple)):
                for x in v:
                    out.extend(criteria(x))
            else:
                out.append((k, v))
    elif isinstance(gate, (list, tuple)):
        for x in gate:
            out.extend(criteria(x))
    return out


def program_targets(value) -> List[str]:
    """The program name(s) a criterion value names.

    A criterion value is a command string, a list of them, or a dict of the form
    {command: ..., condition_files_exist: [...]} — the conditional form. Reading
    the dict's KEYS as program names is the mistake this function exists to
    avoid; it yields plausible-looking names like `command.py` that resolve to
    nothing, and would report 14 clean steps as broken.
    """
    if isinstance(value, str):
        return [value.split()[0]] if value.split() else []
    if isinstance(value, dict):
        cmd = value.get("command")
        return program_targets(cmd) if cmd else []
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for v in value:
            out.extend(program_targets(v))
        return out
    return []


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
    return [s for s in steps if not str(s.get("id", "")).startswith("stage")]


def d1_wiring(steps: List[dict], programs_dir: Path) -> Dict[str, List[str]]:
    """Steps whose gate names a program that does not exist."""
    bad: Dict[str, List[str]] = {}
    for s in steps:
        for kind, value in criteria(s.get("gate")):
            if kind not in PROGRAM_KEYS:
                continue
            for name in program_targets(value):
                fn = name if name.endswith(".py") else f"{name}.py"
                if not (programs_dir / fn).is_file():
                    bad.setdefault(str(s["id"]), []).append(fn)
    return bad


def d6_skip(steps: List[dict]) -> List[str]:
    """Steps with a `condition` and no `condition_kind` to classify the skip."""
    return sorted(str(s["id"]) for s in steps
                  if s.get("condition") and not s.get("condition_kind"))


def d8_catcher(steps: List[dict]) -> List[str]:
    """Steps declaring outputs with no criterion that would fail on absence."""
    out: List[str] = []
    for s in steps:
        if not (s.get("required_outputs") or []):
            continue
        kinds = {k for k, _ in criteria(s.get("gate"))}
        if not (kinds & BLOCKING):
            out.append(str(s["id"]))
    return sorted(out)


def _delegate(program: Path, flow: Path) -> Tuple[int, str]:
    """Run a sibling check and return (rc, its last line).

    A MISSING delegate is rc=3, not rc=2. Both mean "no answer", but only one of
    them means this program is claiming a dimension it did not recompute — and
    the claimed cell count is printed a few lines below. Folding an absent
    delegate into the same bucket as an unreadable input would let the headline
    say 315 of 504 while two dimensions were never asked.

    THE DOOR THAT WAS OPEN. The paragraph above describes rc=3 and stops there,
    and so did the caller: rc=2 — the delegate RAN and answered "NOT CHECKED" —
    was counted as a fully recomputed dimension. The headline then printed the
    exact sentence this docstring says it exists to prevent, with exit 0 and no
    warning. Both delegates return 2 when pyyaml is unavailable or the flow
    yields no steps, so the condition is ordinary, not exotic. rc=2 and rc=3 are
    now both no-answer and both excluded from the count; they stay
    distinguishable in the message because the operator's next move differs.

    `--flow` IS FORWARDED. It was accepted here, used for the three dimensions
    computed in-process, and dropped for the two delegated ones — which both
    accept it. Pointing the grid at a flow file therefore recomputed 3 of 5
    dimensions against it while the headline claimed 5.
    """
    if not program.is_file():
        return 3, f"{program.name} is not present"
    try:
        p = subprocess.run([sys.executable, str(program), "--flow", str(flow)],
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        # Named separately from the OSError arm below. TimeoutExpired is a
        # SubprocessError subclass, so one `except` swallowed it into the same
        # rc=2 that used to be counted as an answer — turning a delegate still
        # working into a silent pass under the default invocation.
        return 2, f"{program.name} exceeded the 300s delegate budget"
    except (OSError, subprocess.SubprocessError) as e:
        return 2, f"{program.name} could not be run: {e}"
    return p.returncode, (p.stdout or p.stderr).strip().splitlines()[-1] \
        if (p.stdout or p.stderr).strip() else ""


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flow", type=Path,
                    default=here.parent / "flow" / "phase1_phase2_phase3.yaml")
    ap.add_argument("--programs", type=Path, default=here)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    if yaml is None:
        print("flow_gate_grid: rc=2 NOT CHECKED — pyyaml unavailable")
        return 2
    steps = load_steps(a.flow)
    if not steps:
        print(f"flow_gate_grid: rc=2 NOT CHECKED — no steps in {a.flow}")
        return 2

    n = len(steps)
    bad1 = d1_wiring(steps, a.programs)
    all6 = d6_skip(steps)
    all8 = d8_catcher(steps)
    bad6 = [x for x in all6 if x not in D6_BASELINE]
    bad8 = [x for x in all8 if x not in D8_BASELINE]
    # A BASELINED STEP THAT VANISHED IS NOT A BASELINED STEP THAT WAS FIXED.
    # `all6`/`all8` list steps that still carry the defect, so a step DELETED
    # from the flow drops out of them and landed in `fixed*` — announced as
    # "Good news" with an instruction to shrink the baseline, which would then
    # erase the record that the step ever owed anything. Deleting the evidence
    # and repairing the defect produced identical output.
    _present = {str(s["id"]) for s in steps}
    fixed6 = sorted((D6_BASELINE - set(all6)) & _present)
    fixed8 = sorted((D8_BASELINE - set(all8)) & _present)
    gone6 = sorted(D6_BASELINE - _present)
    gone8 = sorted(D8_BASELINE - _present)
    rc2, line2 = _delegate(a.programs / "flow_step_can_fail_check.py", a.flow)
    rc5, line5 = _delegate(a.programs / "flow_dependency_graph_check.py", a.flow)

    # rc=2 AND rc=3 are both "no answer". Only 0 and 1 are answers: the delegate
    # looked and said clean, or looked and said broken. Anything else must leave
    # the denominator alone — `declared` is the denominator, and a consumer
    # reports coverage against THAT, never against the number that happened to
    # run.
    _no_answer = [(nm, rc) for nm, rc in (("D2", rc2), ("D5", rc5))
                  if rc not in (0, 1)]
    _dims = 5 - len(_no_answer)
    rec = {
        "steps": n,
        "recomputed_dimensions": _dims,
        "recomputed_cells": _dims * n,
        "delegates_absent": [nm for nm, rc in _no_answer if rc == 3],
        "delegates_no_answer": [{"dim": nm, "rc": rc} for nm, rc in _no_answer],
        "total_cells": 8 * n,
        "D1_wiring_broken": bad1,
        "D2_delegated": {"rc": rc2, "line": line2},
        "D5_delegated": {"rc": rc5, "line": line5},
        "D6_condition_without_kind": all6,
        "D6_new": bad6, "D6_now_fixed": fixed6, "D6_step_gone": gone6,
        "D8_outputs_with_no_catcher": all8,
        "D8_new": bad8, "D8_now_fixed": fixed8, "D8_step_gone": gone8,
        "not_derivable_from_source": NOT_DERIVABLE,
    }
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")

    problems = 0
    if bad1:
        problems += 1
        print(f"flow_gate_grid: D1 wiring — {len(bad1)} step(s) name a program "
              f"that does not exist; the criterion never runs and cannot fail:")
        for sid, names in sorted(bad1.items()):
            print(f"    step {sid}: {', '.join(sorted(set(names)))}")
    for name, rc, line in (("D2 runnable", rc2, line2), ("D5 deps", rc5, line5)):
        if rc == 1:
            problems += 1
            print(f"flow_gate_grid: {name} — {line}")
        elif rc == 3:
            problems += 1
            print(f"flow_gate_grid: {name} — NOT RECOMPUTED, {line}. The cell "
                  f"count below excludes it; a headline that counted a "
                  f"dimension nobody asked about is the defect this grid exists "
                  f"to remove.")
        elif rc != 0:
            # The branch that did not exist. rc=2 fell through every arm above:
            # no problem counted, nothing printed, the dimension counted as
            # recomputed, exit 0. A delegate that answers "NOT CHECKED" is not a
            # delegate that answers "clean", and one killed by the 300s budget
            # while still working is neither.
            problems += 1
            print(f"flow_gate_grid: {name} — NO ANSWER (rc={rc}), {line}. The "
                  f"delegate ran and did not reach a verdict, so this dimension "
                  f"is excluded from the cell count below. Treating it as clean "
                  f"would report coverage this grid never obtained.")
    if bad6:
        problems += 1
        print(f"flow_gate_grid: D6 skip — {len(bad6)} step(s) declare a "
              f"`condition` and no `condition_kind`. The consumer branches on it "
              f"(`setup_required` reports SKIPPED-SETUP-REQUIRED unless waived) "
              f"and NO step sets it, so every conditional skip falls to the "
              f"benign default and 'this design legitimately has none' cannot be "
              f"told from 'someone forgot to author the trigger':")
        print(f"    {', '.join(bad6)}")
    if bad8:
        problems += 1
        print(f"flow_gate_grid: D8 catcher — {len(bad8)} step(s) declare outputs "
              f"nothing would miss: {', '.join(bad8)}")
    for name, gone in (("D6", gone6), ("D8", gone8)):
        if gone:
            problems += 1
            print(f"flow_gate_grid: {name} — {', '.join(gone)} is in the "
                  f"baseline and NO LONGER EXISTS in the flow. This is not a "
                  f"fix and must not be read as one: the step was removed, so "
                  f"nothing can be said about whether its defect was ever "
                  f"repaired. Drop it from the baseline only with the deletion "
                  f"as the stated reason.")
    for name, fixed in (("D6", fixed6), ("D8", fixed8)):
        if fixed:
            problems += 1
            print(f"flow_gate_grid: {name} — {', '.join(fixed)} left the "
                  f"baseline. Good news, and the baseline must shrink to match: "
                  f"one that never shrinks stops describing anything and becomes "
                  f"a list of permissions.")

    print(f"\n  recomputed {_dims * n} of {8 * n} cells "
          f"({n} steps x {_dims} of 8 dimensions)")
    for name, why in sorted(NOT_DERIVABLE.items()):
        print(f"  NOT DERIVABLE FROM SOURCE  {name}: {why}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
