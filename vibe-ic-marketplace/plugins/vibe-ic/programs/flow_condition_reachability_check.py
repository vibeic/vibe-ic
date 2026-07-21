#!/usr/bin/env python3
"""flow_condition_reachability_check.py — the self-disabling-condition gate.

The defect (measured twice in one day, independently, in two subsystems)
-----------------------------------------------------------------------
A flow step is conditioned on a file. That same file's absence is the defect the
step exists to catch. When the defect occurs the condition is false, the step
does not run, and the run reports nothing wrong.

**The check is disabled by exactly the situation it was written for.**

Instance 1 — Step 23 `post_route_signoff_corner_check` (#210) was wired as

    optional_program_exit_zero:
      condition_files_exist: ["phase3/stage3/sta/sta_spef_multicorner.rpt"]

so a vanished hold corner produced "PASS — all analyzed sign-off corners MET".
The word *analyzed* silently excludes whatever disappeared, which makes the
sentence unfalsifiable.

Instance 2 — DT1 at-speed ATPG (#219) was gated on `cut_netlist.v`, whose
absence IS the symptom. The gate never ran, so `transition_coverage_check` —
which ALREADY fails on an absent artefact — was never reached.

Two authors, two subsystems, one shape, one day. This gate exists so the class
becomes extinct instead of being fixed a third time.

What this gate is (and what it deliberately is NOT)
---------------------------------------------------
This is a STATIC gate over `flow/phase1_phase2_phase3.yaml`. It runs no design
and reads no project. It asks one question of every condition in the flow:

    If the thing this step checks for went wrong, would this condition
    still be true?

It is emphatically NOT a sweep that strips conditions. A condition that scopes a
step to a design SHAPE is correct and must survive: "skip the analog gate on a
purely digital design" is right. The defect is narrower — a condition whose
FALSE branch coincides with the step's own FAILURE MODE. Mechanically removing
conditions would break every legitimately-scoped step and be worse than the bug.
So the rules below key on artefact IDENTITY (does the step gate on its own
deliverable?) and on gate STRUCTURE (can this gate pass with nothing executed?),
never on "this step has a condition".

Rules
-----
R1 SELF-OUTPUT GATING — a step must not be conditioned on an artefact that the
   same step declares in its own `required_outputs`. Such a step can only run
   once it has already succeeded, so the one run that needed judging — the one
   where the deliverable never appeared — is the exact run that is not judged.
   This is the purest form of the defect and it is decidable from the YAML
   alone.

   EXEMPT — the `any_of` escape established by #219: a condition may name its
   own output PROVIDED it also accepts an alternative trigger that exists when
   the step did not produce its output (a not-run record, an explicit
   deferral). A not-run record reaching the gate is the whole point: the step
   runs and reports BLOCKED with the reason named, instead of vanishing.

   EXEMPT — a sibling sub-gate in the same `gate` block that unconditionally
   requires that exact path. Then the hard sibling already fails loudly when
   the artefact is missing and the conditional sub-gate is merely redundant.
   An `any_of` sibling does NOT exempt: it can be satisfied by the OTHER path
   while the conditioned check still silently skips.

   EXEMPT — an explicit `condition_rationale` naming why this particular
   self-gate is correct scoping rather than the defect. This is a reviewable
   escape, not a suppression: it must be prose of substance, and the reviewer
   reads the sentence rather than a bare allowlist entry. The canonical valid
   case is a gate that VALIDATES A CLAIM — skipping a waiver-validator when no
   waiver is claimed is right, because there is nothing to judge.

R2 UNDECLARED CONDITION INTENT — every step-level `condition` must state its
   `condition_kind` explicitly. The engine supports two kinds:

     design_dependent → silent skip; the step is genuinely N/A for this design
                        shape (analog steps on a digital-only IC).
     setup_required   → the trigger SHOULD have been authored; skipping is a
                        setup mistake and surfaces as SKIPPED-SETUP-REQUIRED.

   Both are legitimate. What is not legitimate is deciding by OMISSION: the
   default is the silent one, and a SKIPPED-CONDITION step is not merely passed
   over — `flow_compliance_check` subtracts it from `total_required`, so it
   leaves the denominator too. It does not even dilute the score. Requiring the
   author to type which kind they mean is what stops the next self-disabling
   condition from being added by accident.

R3 VACUOUS GATE — a step's `gate` must contain at least one sub-gate that
   always executes. A gate composed ENTIRELY of `optional_program_exit_zero`
   sub-gates passes with zero programs run and zero files checked whenever none
   of the trigger paths exist, and — because the no-inputs skip records no
   reason — the resulting PASS is byte-identical to a step that ran every check
   and met every one.

Direction: louder, never greener. Every finding here converts an invisible skip
into a visible BLOCKED. An invisible skip was never a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - yaml ships with the plugin env
    print("flow_condition_reachability_check: PyYAML is required",
          file=sys.stderr)
    raise SystemExit(2)

_PROGRAM = "flow_condition_reachability_check"

# The flow definition, relative to this program's package root.
_DEFAULT_FLOW = Path(__file__).resolve().parent.parent / (
    "flow/phase1_phase2_phase3.yaml")

_VALID_KINDS = ("design_dependent", "setup_required")

# A `condition_rationale` shorter than this is a rubber stamp, not a reason.
# The point of the escape is that a reviewer reads a sentence explaining why
# self-gating is correct HERE; "n/a" or "ok" defeats it.
_MIN_RATIONALE_CHARS = 40


def _rationale(obj: Dict[str, Any]) -> str:
    """A substantive `condition_rationale`, or "" if absent/too thin."""
    text = str(obj.get("condition_rationale") or "").strip()
    return text if len(text) >= _MIN_RATIONALE_CHARS else ""


def _tracked(obj: Dict[str, Any]) -> str:
    """A `condition_defect_tracked` reference (e.g. "#219"), or "".

    A CONFIRMED self-disabling condition whose repair is in flight in another
    change. It is deliberately NOT an exemption: the finding is still reported,
    still printed, and the banner still refuses to say PASS. It only stops this
    gate from blocking on work that is already owned elsewhere — the same
    shape the STA record gate uses for SINGLE_CORNER_ONLY, where the verdict
    exits 0 but is never rendered as a pass.
    """
    return str(obj.get("condition_defect_tracked") or "").strip()


def _norm(path: str) -> str:
    """Normalise an artefact path for identity comparison.

    `required_outputs` entries may carry an ` OR ` alternation and a trailing
    slash on directory triggers; conditions never do. Compare the bare paths.
    """
    return str(path).strip().rstrip("/")


def _required_outputs(step: Dict[str, Any]) -> set:
    """Every path the step declares as its own deliverable, alternations split."""
    out = set()
    for pat in (step.get("required_outputs") or []):
        for alt in str(pat).split(" OR "):
            alt = _norm(alt)
            if alt:
                out.add(alt)
    return out


def _iter_optional_gates(gate: Any):
    """Yield every `optional_program_exit_zero` spec nested anywhere in a gate."""
    if isinstance(gate, dict):
        spec = gate.get("optional_program_exit_zero")
        if isinstance(spec, dict):
            yield spec
        for value in gate.values():
            yield from _iter_optional_gates(value)
    elif isinstance(gate, list):
        for value in gate:
            yield from _iter_optional_gates(value)


def _hard_required_paths(gate: Any) -> set:
    """Paths a gate requires UNCONDITIONALLY.

    A `files_exist` sub-gate with `any_of: true` requires none of its paths
    unconditionally — any single one satisfies it — so it contributes nothing
    here. That distinction is the whole point of R1's sibling exemption: an
    `any_of` hard gate can be met by the OTHER path while the conditioned check
    still silently skips.
    """
    hard = set()
    if isinstance(gate, dict):
        files = gate.get("files_exist")
        if isinstance(files, list) and not gate.get("any_of", False):
            for pat in files:
                hard.add(_norm(pat))
        for key, value in gate.items():
            # An `optional_program_exit_zero` block never contributes hard
            # requirements; its `condition_files_exist` is the opposite of one.
            if key == "optional_program_exit_zero":
                continue
            hard |= _hard_required_paths(value)
    elif isinstance(gate, list):
        for value in gate:
            hard |= _hard_required_paths(value)
    return hard


def _gate_has_unconditional_subgate(gate: Any) -> bool:
    """True if any leaf of the gate always executes."""
    if isinstance(gate, dict):
        if "optional_program_exit_zero" in gate:
            # This node IS the conditional form; it never executes
            # unconditionally. Do not descend into its own spec.
            return False
        if "program_exit_zero" in gate or "files_exist" in gate:
            return True
        return any(_gate_has_unconditional_subgate(v) for v in gate.values())
    if isinstance(gate, list):
        return any(_gate_has_unconditional_subgate(v) for v in gate)
    return False


def _check_r1_step(step: Dict[str, Any]) -> List[Dict[str, Any]]:
    """R1 over a step-level `condition`."""
    findings: List[Dict[str, Any]] = []
    cond = step.get("condition")
    if not isinstance(cond, dict):
        return findings
    files = cond.get("files_exist") or []
    if not isinstance(files, list):
        return findings
    own = _required_outputs(step)
    self_gated = [p for p in files if _norm(p) in own]
    if not self_gated:
        return findings
    # #219 escape: an `any_of` condition that also accepts a trigger which is
    # NOT the step's own output can still be reached when the step failed.
    if cond.get("any_of", False):
        alternatives = [p for p in files if _norm(p) not in own]
        if alternatives:
            return findings
    if _rationale(step):
        return findings
    findings.append({
        "rule": "R1",
        "step": step.get("id"),
        "name": step.get("name", ""),
        "scope": "step-condition",
        "paths": self_gated,
        "detail": (
            f"step {step.get('id')} is conditioned on {self_gated}, which it "
            f"also declares in its own required_outputs. The step can only run "
            f"once it has already succeeded; the run where the deliverable "
            f"never appeared is the exact run that goes unjudged."),
    })
    return findings


def _check_r1_gate(step: Dict[str, Any]) -> List[Dict[str, Any]]:
    """R1 over every `optional_program_exit_zero` in the step's gate."""
    findings: List[Dict[str, Any]] = []
    gate = step.get("gate")
    own = _required_outputs(step)
    if not own:
        return findings
    hard = _hard_required_paths(gate)
    for spec in _iter_optional_gates(gate):
        files = spec.get("condition_files_exist") or []
        if not isinstance(files, list):
            continue
        self_gated = [p for p in files if _norm(p) in own]
        if not self_gated:
            continue
        # Sibling exemption: a hard, non-any_of sub-gate already requires the
        # same path, so absence fails loudly there first.
        if all(_norm(p) in hard for p in self_gated):
            continue
        # Reviewable escape: the gate's own stated reason why self-gating is
        # correct scoping here (canonically, a validator with no claim to judge).
        if _rationale(spec):
            continue
        findings.append({
            "rule": "R1",
            "step": step.get("id"),
            "name": step.get("name", ""),
            "scope": "gate-condition",
            "paths": self_gated,
            "command": str(spec.get("command", ""))[:120],
            "detail": (
                f"step {step.get('id')} runs `{str(spec.get('command',''))[:60]}` "
                f"only when {self_gated} exists, and declares that same path as "
                f"its own required_output. No unconditional sibling sub-gate "
                f"requires it, so when the artefact is absent the check is "
                f"skipped and the step still reports PASS with no reason."),
        })
    return findings


def _check_r2(step: Dict[str, Any]) -> List[Dict[str, Any]]:
    """R2 — a step-level condition must declare its kind explicitly."""
    if not isinstance(step.get("condition"), dict):
        return []
    kind = step.get("condition_kind")
    if kind is None:
        return [{
            "rule": "R2",
            "step": step.get("id"),
            "name": step.get("name", ""),
            "scope": "step-condition",
            "paths": (step.get("condition") or {}).get("files_exist", []),
            "detail": (
                f"step {step.get('id')} has a `condition` but no explicit "
                f"`condition_kind`. It therefore defaults to design_dependent "
                f"— a silent skip that is also subtracted from total_required, "
                f"so it leaves the denominator too. State "
                f"`condition_kind: design_dependent` (genuinely N/A for this "
                f"design shape) or `setup_required` (the trigger should have "
                f"been authored)."),
        }]
    if kind not in _VALID_KINDS:
        return [{
            "rule": "R2",
            "step": step.get("id"),
            "name": step.get("name", ""),
            "scope": "step-condition",
            "paths": [],
            "detail": (f"step {step.get('id')} declares unknown "
                       f"condition_kind {kind!r}; expected one of "
                       f"{list(_VALID_KINDS)}."),
        }]
    return []


def _check_r3(step: Dict[str, Any]) -> List[Dict[str, Any]]:
    """R3 — a gate must have at least one sub-gate that always executes."""
    gate = step.get("gate")
    if not gate:
        return []
    if _gate_has_unconditional_subgate(gate):
        return []
    return [{
        "rule": "R3",
        "step": step.get("id"),
        "name": step.get("name", ""),
        "scope": "gate-structure",
        "paths": [],
        "detail": (
            f"step {step.get('id')}'s gate is composed entirely of conditional "
            f"sub-gates. When none of the trigger paths exist it passes with "
            f"zero programs run and zero files checked, and the resulting PASS "
            f"is indistinguishable from a step that ran every check and met "
            f"every one. Add one unconditional sub-gate that reports BLOCKED "
            f"naming the missing input."),
    }]


def _check_r4(step: Dict[str, Any]) -> List[Dict[str, Any]]:
    """R4 — a declared tracked defect is REPORTED until the marker is gone.

    R1 keys on artefact identity: condition path == the step's own
    required_output. That is precise, but it is blind to a step that declares
    NO required_outputs at all — which is exactly the DT1/DT2/DT3 shape, where
    the condition names an input the step's own producer was supposed to make.
    Without this rule the guard would go green while three confirmed
    self-disabling steps sat in the file: the guard would itself have been
    disabled by the situation it exists to catch.

    So `condition_defect_tracked` is not a suppression, it is a DECLARATION,
    and declaring it emits a finding. The marker only moves the finding out of
    the blocking set (the repair is owned by another change); it never removes
    it from the report and never lets the banner read PASS.
    """
    ref = _tracked(step)
    if not ref:
        return []
    return [{
        "rule": "R4",
        "step": step.get("id"),
        "name": step.get("name", ""),
        "scope": "declared-tracked-defect",
        "paths": (step.get("condition") or {}).get("files_exist", []),
        "detail": (
            f"step {step.get('id')} carries a CONFIRMED self-disabling "
            f"condition, declared as tracked by {ref}. It is reported on every "
            f"run until the condition is actually repaired and the "
            f"`condition_defect_tracked` key is deleted."),
    }]


def check_flow(flow_path: Path) -> Dict[str, Any]:
    """Evaluate R1-R3 over a flow definition. Pure; reads only the YAML."""
    try:
        doc = yaml.safe_load(flow_path.read_text())
    except Exception as exc:
        return {
            "verdict": "ERROR",
            "flow": str(flow_path),
            "reasons": [f"cannot parse {flow_path}: {exc}"],
            "findings": [],
        }
    steps = (doc or {}).get("steps") or []
    findings: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        findings.extend(_check_r1_step(step))
        findings.extend(_check_r1_gate(step))
        findings.extend(_check_r2(step))
        findings.extend(_check_r3(step))
        findings.extend(_check_r4(step))

    # Split confirmed-but-owned-elsewhere findings out of the blocking set.
    # They stay in `findings` (reported, printed, counted); they just do not
    # make this gate block on another change's work.
    for f in findings:
        step = next((s for s in steps if isinstance(s, dict)
                     and s.get("id") == f["step"]), {})
        ref = _tracked(step)
        if ref:
            f["tracked_by"] = ref

    blocking = [f for f in findings if not f.get("tracked_by")]
    deferred = [f for f in findings if f.get("tracked_by")]

    by_rule: Dict[str, int] = {}
    for f in findings:
        by_rule[f["rule"]] = by_rule.get(f["rule"], 0) + 1

    if blocking:
        verdict = "FAIL"
    elif deferred:
        verdict = "TRACKED_DEFECTS_ONLY"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "blocking_count": len(blocking),
        "deferred_count": len(deferred),
        "flow": str(flow_path),
        "steps_examined": len(steps),
        "conditions_examined": sum(
            1 for s in steps if isinstance(s, dict) and s.get("condition")
        ) + sum(
            len(list(_iter_optional_gates(s.get("gate"))))
            for s in steps if isinstance(s, dict)
        ),
        "findings_by_rule": by_rule,
        "findings": findings,
        "reasons": [f["detail"] for f in findings],
    }


def render_table(res: Dict[str, Any]) -> str:
    findings = res.get("findings") or []
    if not findings:
        return (f"  {res.get('conditions_examined', 0)} conditions across "
                f"{res.get('steps_examined', 0)} steps — every gate is "
                f"reachable when its own subject is missing.")
    width = max(len(str(f.get("step"))) for f in findings)
    lines = [f"  {'RULE':<5} {'STEP':<{max(width, 4)}}  SCOPE            SUBJECT"]
    for f in findings:
        paths = ", ".join(str(p) for p in (f.get("paths") or [])) or "-"
        lines.append(
            f"  {f['rule']:<5} {str(f.get('step')):<{max(width, 4)}}  "
            f"{f.get('scope', ''):<16} {paths[:70]}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Static gate: no flow step may be disabled by the very "
                     "situation it exists to catch."))
    ap.add_argument("project", nargs="?", default=".",
                    help="project dir (accepted for flow-gate uniformity; "
                         "this check reads only the flow definition)")
    ap.add_argument("--flow", default=None,
                    help=f"flow YAML to check (default: {_DEFAULT_FLOW})")
    ap.add_argument("--json", default=None, help="write JSON result here")
    args = ap.parse_args(argv)

    flow_path = Path(args.flow) if args.flow else _DEFAULT_FLOW
    if not flow_path.is_file():
        print(f"[FAIL] {_PROGRAM}: flow definition not found: {flow_path}",
              file=sys.stderr)
        return 2

    res = check_flow(flow_path)

    if args.json:
        out_path = Path(args.json)
        if not out_path.is_absolute():
            out_path = Path(args.project) / args.json
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(res, indent=2) + "\n")
        except OSError as e:
            print(f"{_PROGRAM}: cannot write {out_path}: {e}", file=sys.stderr)
            return 2

    tag = str(res["verdict"])
    # TRACKED_DEFECTS_ONLY exits 0 — the repair is owned by another change —
    # but is NEVER printed as PASS. A confirmed self-disabling condition that
    # renders as "PASS" because someone else is fixing it would be this very
    # bug wearing a different hat.
    ok = tag in ("PASS", "TRACKED_DEFECTS_ONLY")
    print(f"[{tag}] {_PROGRAM}: {tag}")
    print(render_table(res))
    for f in res.get("findings", []):
        ref = f.get("tracked_by")
        prefix = f"[{f['rule']}]" + (f"[tracked {ref}]" if ref else "")
        print(f"  - {prefix} {f['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
