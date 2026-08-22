#!/usr/bin/env python3
"""l13_bringup_contract_check.py — SEMANTIC gate for L13_LAB_CALIBRATION.json.

VERDICT SEMANTICS — THIS GATE **BLOCKS**.
    Any FAIL-severity finding returns exit 1, and the caller must halt.
    Why blocking: L13 is the ONLY place a hardware PASS can be defined.
    `hardware_pass_attestation_check.py` dispatches on
    `L13.known_pass_transcript.criterion`; with no criterion it takes the
    not-found path and the project's "proven on silicon" claim is
    unattestable — silently. A layer gate that only advises reproduces the
    exact 2026-07 defect this campaign exists to kill: the completeness
    report said FAIL and the flow continued anyway. So FAIL here is fatal.
    A second, ADVISORY tier (WARN) carries systemic producer defects that
    are real but would halt most existing runs; `--strict` promotes the
    WARN tier to blocking so the flow can tighten once the producer is
    fixed.

WHAT IT ENFORCES (the CONSUMER contract, not token presence)
    Two programs consume L13:

      * programs/hardware_pass_attestation_check.py — reads the CONTRACT
        half: `criterion`, `criterion_params`, `tester`. It selects a
        validator out of its OWN registry `_CRITERIA`. This gate IMPORTS
        that registry and INTROSPECTS each validator's source for the
        `params.get("<key>", …)` reads it performs, so the set of valid
        criteria and the set of parameters a contract must pin are
        DERIVED FROM THE CONSUMER'S CODE — never a literal list here.
        Consequence: when the consumer grows a criterion or a knob, this
        gate follows automatically and cannot drift.

      * programs/bringup_plan_gen.py — renders
        `- [{step}] {action} → {expected}` per entry of
        `calibration_steps` / `trim_loop`. An entry with no `expected`
        renders literally `→ ?`: a plan line no technician can execute.
        An `action` that is a markdown heading lifted out of an input doc
        is document scaffolding, not a bring-up action.

    PHASE SEPARATION. L13 has two halves. Phase 1 owns the CONTRACT
    (criterion / criterion_params / tester — "what would count as a pass").
    Phase 2 owns the EVIDENCE (known_pass_bitstream / known_pass_transcript
    — "here are the tester bytes"). Evidence populated during Phase 1 is
    not evidence; it is a fabricated hardware claim, so it FAILS.

    SCOPE IS DERIVED FROM THE DOC'S OWN DECLARATIONS. The contract is
    demanded only when L13 itself declares that hardware/lab work is in
    scope — `lab_calibration_present == true`, or a non-empty
    `calibration_targets` / `lab_equipment` / `rig_pin_assignments`, or a
    CONTRACT/EVIDENCE key already partially present. Nothing keys off a
    design name, a PDK name, a vendor part number or a pin literal.
    Text-derived step lists alone do NOT establish scope: they are
    routinely harvested from a document that says calibration is *absent*.

RULES
    FAIL tier (blocking, always)
      l13_parseable                      L13 is valid JSON.
      l13_phase1_evidence_must_be_empty  EVIDENCE half empty during Phase 1.
      l13_criterion_known_to_consumer    declared criterion is dispatchable
                                         by the consumer's own registry.
      l13_contract_complete              when hardware is in scope: criterion
                                         + every param that criterion's own
                                         validator reads + a tester identity.
    WARN tier (advisory; `--strict` promotes to blocking)
      l13_bringup_step_not_actionable    a step with no `expected`, or whose
                                         `action` is document scaffolding,
                                         renders a vacuous plan line.
      l13_steps_contradict_declared_absence
                                         L13 declares no hardware content at
                                         all yet emits bring-up steps, so
                                         bringup_plan_gen writes a plan for a
                                         bring-up the same doc says does not
                                         exist.

USAGE
    python3 l13_bringup_contract_check.py <project_dir> [--l13 PATH]
        [--phase 1|2] [--strict] [--json OUT]

EXIT CODES
    0 = PASS (or WARN-only without --strict)
    1 = FAIL (blocking)
    2 = not applicable / input missing (skip)
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hardware_pass_attestation_check as _hpa  # noqa: E402  (the CONSUMER)

try:
    import _path_layout as _pl  # noqa: E402
except Exception:                # pragma: no cover - cache tree without helper
    _pl = None


# --------------------------------------------------------------------------
# Consumer introspection — the contract vocabulary is READ OUT OF THE
# CONSUMER, so this gate can never disagree with what actually runs.
# --------------------------------------------------------------------------
_PARAMS_GET_RE = re.compile(r"""params\.get\(\s*["']([A-Za-z_]\w*)["']""")


def consumer_criteria() -> List[str]:
    """Criterion names `hardware_pass_attestation_check` can dispatch."""
    return sorted(getattr(_hpa, "_CRITERIA", {}))


def consumer_required_params(criterion: str) -> List[str]:
    """Parameter keys the consumer's validator for `criterion` actually
    reads. Derived by introspecting that validator's source — a Phase-1
    contract that leaves one unpinned silently inherits a threshold
    authored for a different part."""
    fn = getattr(_hpa, "_CRITERIA", {}).get(criterion)
    if fn is None:
        return []
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):     # pragma: no cover - frozen import
        return []
    return sorted(set(_PARAMS_GET_RE.findall(src)))


# --------------------------------------------------------------------------
# L13 shape helpers
# --------------------------------------------------------------------------
_CONTRACT_KEYS = ("criterion", "criterion_params", "tester")
_EVIDENCE_KEYS = ("known_pass_bitstream", "known_pass_transcript")
# Declarations that establish "this part has real lab / hardware content".
_SCOPE_LIST_KEYS = ("calibration_targets", "lab_equipment")
_SCOPE_MAP_KEYS = ("rig_pin_assignments",)
_STEP_LIST_KEYS = ("calibration_steps", "trim_loop")
_EXPECTED_KEYS = ("expected", "expected_result", "pass_criterion",
                  "acceptance", "expected_value", "observable")
# A markdown heading / horizontal rule / arrow-note lifted verbatim out of an
# input document is document scaffolding, not an executable bring-up action.
_SCAFFOLD_RE = re.compile(r"^\s*(?:#{1,6}\s|-{3,}\s*$|={3,}\s*$|[→⇒]\s)")


def _contract_block(l13: Dict[str, Any]) -> Dict[str, Any]:
    """The CONTRACT may sit at the top level or inside the (Phase-2)
    known_pass_transcript envelope — the consumer reads it from the
    transcript, so accept either and prefer whichever is populated."""
    out: Dict[str, Any] = {}
    tx = l13.get("known_pass_transcript")
    for src in (tx if isinstance(tx, dict) else {}, l13):
        for k in _CONTRACT_KEYS:
            if k in src and k not in out:
                out[k] = src[k]
    return out


def _nonempty(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, tuple, set, dict, str)):
        return len(v) > 0
    return True


def hardware_in_scope(l13: Dict[str, Any]) -> tuple[bool, str]:
    """Derived purely from L13's own declarations."""
    if l13.get("lab_calibration_present") is True:
        return True, "lab_calibration_present == true"
    for k in _SCOPE_LIST_KEYS:
        if _nonempty(l13.get(k)):
            return True, f"{k} is non-empty"
    for k in _SCOPE_MAP_KEYS:
        if _nonempty(l13.get(k)):
            return True, f"{k} is non-empty"
    present = [k for k in _CONTRACT_KEYS + _EVIDENCE_KEYS
               if _nonempty(l13.get(k))]
    if present:
        return True, f"partial contract/evidence already present: {present}"
    return False, ("L13 declares no lab/hardware content "
                   "(lab_calibration_present not true; calibration_targets, "
                   "lab_equipment, rig_pin_assignments all empty)")


def _iter_steps(l13: Dict[str, Any]):
    for key in _STEP_LIST_KEYS:
        seq = l13.get(key)
        if isinstance(seq, list):
            for i, st in enumerate(seq):
                yield key, i, st


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
def check(l13: Optional[Dict[str, Any]], *, phase: int = 1) -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []

    def fail(rule, msg):
        findings.append({"severity": "FAIL", "rule": rule, "message": msg})

    def warn(rule, msg):
        findings.append({"severity": "WARN", "rule": rule, "message": msg})

    if not isinstance(l13, dict):
        fail("l13_parseable", "L13_LAB_CALIBRATION.json is not a JSON object")
        return {"findings": findings, "hardware_in_scope": None}

    in_scope, why = hardware_in_scope(l13)
    contract = _contract_block(l13)

    # ---- FAIL tier -------------------------------------------------------
    # 1. Phase-1 purity: the EVIDENCE half belongs to Phase 2.
    if phase < 2:
        for k in _EVIDENCE_KEYS:
            if _nonempty(l13.get(k)):
                fail("l13_phase1_evidence_must_be_empty",
                     f"`{k}` is populated during Phase 1. The EVIDENCE half "
                     f"is filled in Phase 2 from a real tester run; content "
                     f"here is a hardware claim with no hardware behind it. "
                     f"Phase 1 owns only {list(_CONTRACT_KEYS)}.")

    # 2. A declared criterion must be dispatchable by the consumer.
    valid = consumer_criteria()
    crit = contract.get("criterion")
    if _nonempty(crit):
        if not isinstance(crit, str) or crit not in valid:
            fail("l13_criterion_known_to_consumer",
                 f"criterion `{crit!r}` is not dispatchable by "
                 f"hardware_pass_attestation_check. Its registry accepts: "
                 f"{valid}. An unknown criterion makes the attestation "
                 f"return 'unknown criterion' — i.e. no attestation at all.")

    # 3. When hardware is in scope the CONTRACT must be complete AND the
    #    criterion's own knobs must be pinned.
    if in_scope:
        if not _nonempty(crit):
            fail("l13_contract_complete",
                 f"hardware/lab work is in scope ({why}) but L13 declares no "
                 f"`criterion`. hardware_pass_attestation_check cannot attest "
                 f"a hardware pass without one — it degrades to the "
                 f"not-found path and the pass is silently unattestable. "
                 f"Pick one of {valid}.")
        elif isinstance(crit, str) and crit in valid:
            need = consumer_required_params(crit)
            params = contract.get("criterion_params")
            if not isinstance(params, dict):
                if need:
                    fail("l13_contract_complete",
                         f"criterion `{crit}` needs `criterion_params` "
                         f"pinning {need}; none declared. Unpinned knobs fall "
                         f"back to the consumer's built-in defaults, which "
                         f"were authored for a different part.")
            else:
                missing = [k for k in need if k not in params]
                if missing:
                    fail("l13_contract_complete",
                         f"criterion `{crit}` reads {need} from "
                         f"criterion_params; {missing} unpinned. The default "
                         f"would silently come from another design's "
                         f"threshold, so the pass/fail line is not this "
                         f"part's.")
        tester = contract.get("tester")
        if not (isinstance(tester, str) and tester.strip()):
            fail("l13_contract_complete",
                 f"hardware/lab work is in scope ({why}) but L13 declares no "
                 f"`tester` identity. An attestation that cannot name the "
                 f"instrument that produced it is not an attestation.")
    else:
        # Not in scope: a half-written contract is still a defect, caught by
        # hardware_in_scope() returning True on any partial key.
        pass

    # ---- WARN tier -------------------------------------------------------
    steps = list(_iter_steps(l13))
    bad_steps: List[str] = []
    for key, i, st in steps:
        label = f"{key}[{i}]"
        if not isinstance(st, dict):
            bad_steps.append(f"{label}: not a step record")
            continue
        action = st.get("action") or st.get("step_action") or ""
        if not str(action).strip():
            bad_steps.append(f"{label}: empty `action`")
            continue
        if _SCAFFOLD_RE.match(str(action)):
            bad_steps.append(
                f"{label}: `action` is document scaffolding "
                f"({str(action).strip()[:48]!r}), not an executable action")
            continue
        if not any(_nonempty(st.get(k)) for k in _EXPECTED_KEYS):
            bad_steps.append(
                f"{label}: no `expected` — bringup_plan_gen renders this as "
                f"'→ ?', an unexecutable plan line")
    if bad_steps:
        warn("l13_bringup_step_not_actionable",
             f"{len(bad_steps)}/{len(steps)} bring-up steps are not "
             f"actionable for bringup_plan_gen. Examples: "
             + "; ".join(bad_steps[:4]))

    if steps and not in_scope:
        warn("l13_steps_contradict_declared_absence",
             f"L13 emits {len(steps)} bring-up step(s) while declaring no "
             f"hardware content at all ({why}). bringup_plan_gen will write a "
             f"{len(steps)}-step bring-up plan for a bring-up this same "
             f"document says does not exist.")

    return {
        "findings": findings,
        "hardware_in_scope": in_scope,
        "scope_reason": why,
        "consumer_criteria": valid,
        "declared_criterion": crit,
        "step_count": len(steps),
    }


def resolve_l13(project: Path, override: Optional[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.is_file() else None
    cands = [project / "phase1" / "generated_docs" / "L13_LAB_CALIBRATION.json"]
    if _pl is not None:
        try:
            cands.append(_pl.generated_docs_dir(project) /
                         "L13_LAB_CALIBRATION.json")
        except Exception:
            pass
    cands.append(project / "L13_LAB_CALIBRATION.json")
    for c in cands:
        if c.is_file():
            return c
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--l13", default=None)
    ap.add_argument("--phase", type=int, default=1, choices=(1, 2))
    ap.add_argument("--strict", action="store_true",
                    help="promote the advisory WARN tier to blocking")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    project = args.project_dir
    l13_path = resolve_l13(project, args.l13)
    if l13_path is None:
        print("[SKIP] l13_bringup_contract_check: "
              "L13_LAB_CALIBRATION.json not found")
        return 2

    try:
        l13 = json.loads(l13_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result = {"findings": [{"severity": "FAIL", "rule": "l13_parseable",
                                "message": f"cannot parse {l13_path}: {exc}"}]}
    else:
        result = check(l13, phase=args.phase)

    result["l13_path"] = str(l13_path)
    result["blocks"] = True
    result["strict"] = bool(args.strict)

    fails = [f for f in result["findings"] if f["severity"] == "FAIL"]
    warns = [f for f in result["findings"] if f["severity"] == "WARN"]
    result["pass"] = not fails and not (args.strict and warns)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2))

    for f in result["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    if result["pass"]:
        print(f"[PASS] l13_bringup_contract_check: "
              f"hardware_in_scope={result.get('hardware_in_scope')} "
              f"({len(warns)} advisory)")
        return 0
    print(f"[FAIL] l13_bringup_contract_check: "
          f"{len(fails)} blocking, {len(warns)} advisory "
          f"(strict={args.strict}) — BLOCKS the flow")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
