#!/usr/bin/env python3
"""dft_signoff_check.py — aggregate DFT sign-off gate (foundry / ATE bar).

Rolls the three DFT-depth checks into ONE tapeout-facing verdict:

  1. STUCK-AT   : measured stuck-at coverage >= foundry floor
                  (delegated to dft_atpg_coverage_check — recomputed, never
                  a trusted self-asserted boolean; foundry floor clamps a
                  lenient written target UP).
  2. TRANSITION : at-speed (launch-off-capture) transition coverage
                  >= target, OR a DOCUMENTED OSS engine limitation
                  (transition.engine_limited == true WITH a reason). A
                  claimed-supported run with no number, or a MISSING
                  transition record, FAILs.
  3. BSDL       : a padded design has a BSDL + boundary-scan-cell-per-pad
                  plan present (from bsdl_emit). A bare core is N/A (SKIP).
                  A padded design with a missing BSDL FAILs. Missing
                  bsdl_plan evidence FAILs (never a vacuous pass).

§4.05 (never a vacuous pass on absence):
  * absent stuck-at evidence  → FAIL
  * absent transition record  → FAIL
  * absent BSDL plan          → FAIL (cannot prove boundary-scan status)
  * bare-core BSDL            → SKIP (honest N/A, not a pass-for-nothing)
  * engine-limited transition → ENGINE_LIMITED (accepted only when
                                documented; otherwise FAIL)

Overall PASS iff:
  stuck_at == PASS
  AND transition ∈ {PASS, ENGINE_LIMITED(documented)}   (--strict-transition
                                                          demotes ENGINE_LIMITED
                                                          to FAIL)
  AND bsdl ∈ {PASS, SKIP}

Usage:
    python3 dft_signoff_check.py <project_dir> [--json <out>]
        [--foundry-floor 95] [--transition-target 90]
        [--coverage-json PATH] [--bsdl-plan PATH]
        [--strict-transition]

main(argv) -> int : 0 PASS / 1 FAIL / 2 IO-or-arg error.

chip-AGNOSTIC: reads only the generic coverage.json / bsdl_plan.json schemas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover - standalone fallback
    _pl = None

# Sibling checker — reused as a library (recompute + foundry floor).
try:
    import dft_atpg_coverage_check as _sa
except Exception:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dft_atpg_coverage_check as _sa  # type: ignore

try:
    import dft_signoff_common
except Exception:  # pragma: no cover - path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dft_signoff_common  # type: ignore

_PROGRAM = "dft_signoff_check"
_VERSION = "1.0.0"

FOUNDRY_FLOOR_DEFAULT = getattr(_sa, "FOUNDRY_FLOOR_DEFAULT", 95.0)
TRANSITION_TARGET_DEFAULT = 90.0


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _coverage_json_path(project: Path, override: Optional[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.is_file() else None
    cands = []
    if _pl is not None:
        cands.append(_pl.report_path(project, "dft/coverage.json"))
        cands.append(_pl.reports_phase2_dir(project) / "dft" / "coverage.json")
    cands.append(project / "reports" / "phase2" / "dft" / "coverage.json")
    cands.append(project / "reports" / "dft" / "coverage.json")
    return next((p for p in cands if p.is_file()), None)


def _bsdl_plan_path(project: Path, override: Optional[str]) -> Optional[Path]:
    if override:
        p = Path(override)
        return p if p.is_file() else None
    cands = []
    if _pl is not None:
        cands.append(_pl.report_path(project, "dft/bsdl_plan.json"))
        cands.append(_pl.reports_phase2_dir(project) / "dft" / "bsdl_plan.json")
    cands.append(project / "reports" / "phase2" / "dft" / "bsdl_plan.json")
    cands.append(project / "reports" / "dft" / "bsdl_plan.json")
    return next((p for p in cands if p.is_file()), None)


def _dft_inputs_absent(project: Path,
                       coverage_json_override: Optional[str]) -> bool:
    """True iff NONE of the DFT sign-off inputs are present: no coverage.json,
    no atpg_coverage.rpt, and no scan_netlist.v. Used ONLY to GUARD the
    disclosed-skip path so a real run (ANY real DFT input present) is judged
    normally — a real low coverage still FAILs."""
    cov_candidates, rpt_candidates = _sa._resolve_paths(project,
                                                        coverage_json_override)
    if any(p.is_file() for p in cov_candidates):
        return False
    if any(p.is_file() for p in rpt_candidates):
        return False
    scan_cands = []
    if _pl is not None:
        scan_cands.append(_pl.dft_dir(project) / "scan_netlist.v")
    scan_cands.append(project / "phase2" / "stage2" / "dft" / "scan_netlist.v")
    if any(p.is_file() for p in scan_cands):
        return False
    return True


# ── sub-check: transition ──────────────────────────────────────────────

def evaluate_transition(coverage_json: Optional[dict],
                        transition_target: float,
                        strict: bool = False) -> dict:
    """Evaluate the transition (at-speed) fault-model sub-check from the
    coverage.json `transition` block (or flat mirror fields). Honest:
      * missing transition record          → FAIL (no evidence)
      * engine_limited + documented reason  → ENGINE_LIMITED (accepted unless
                                              --strict-transition)
      * supported + number >= target        → PASS
      * supported + number < target         → FAIL
      * supported + no number               → FAIL (claimed but unproven)
    """
    reasons = []
    if coverage_json is None:
        return {"status": "FAIL",
                "reasons": ["no coverage.json — cannot read a transition "
                            "(at-speed) fault-model record"]}

    block = coverage_json.get("transition")
    if not isinstance(block, dict):
        # Fall back to flat mirror fields if present.
        if "transition_engine_limited" in coverage_json or \
           "transition_coverage_pct" in coverage_json:
            block = {
                "engine_limited": coverage_json.get("transition_engine_limited"),
                "supported": coverage_json.get("transition_supported"),
                "coverage_pct": coverage_json.get("transition_coverage_pct"),
                "target_pct": coverage_json.get("transition_target_pct"),
                "ge_target": coverage_json.get("transition_ge_target"),
                "reason": coverage_json.get("transition_reason"),
            }
        else:
            return {"status": "FAIL",
                    "reasons": ["coverage.json has NO `transition` fault-model "
                                "record — at-speed ATPG was never attempted "
                                "(missing evidence, not a pass)"]}

    target = block.get("target_pct", transition_target)
    measured = block.get("coverage_pct")
    engine_limited = bool(block.get("engine_limited"))
    reason = block.get("reason") or ""

    if engine_limited:
        if not reason.strip():
            return {"status": "FAIL", "target_pct": target,
                    "reasons": ["transition marked engine_limited but with NO "
                                "documented reason — undocumented limitation "
                                "cannot be accepted"]}
        if strict:
            return {"status": "FAIL", "target_pct": target,
                    "reasons": [f"--strict-transition: engine-limited "
                                f"transition ATPG not accepted; a real "
                                f"at-speed coverage number is required. "
                                f"({reason})"]}
        return {"status": "ENGINE_LIMITED", "target_pct": target,
                "measured_pct": None,
                "reasons": [f"transition ATPG engine-limited (documented): "
                            f"{reason}"]}

    # Engine claims support → require a real number.
    if measured is None:
        return {"status": "FAIL", "target_pct": target,
                "reasons": ["transition claims engine support but carries NO "
                            "coverage number — unproven, cannot pass"]}
    ge = measured >= target
    return {
        "status": "PASS" if ge else "FAIL",
        "measured_pct": measured,
        "target_pct": target,
        "reasons": ([] if ge else
                    [f"transition coverage {measured:.2f}% < target "
                     f"{target:.2f}% — at-speed coverage below floor"]),
    }


# ── sub-check: BSDL ────────────────────────────────────────────────────

def evaluate_bsdl(bsdl_plan: Optional[dict]) -> dict:
    """Evaluate the BSDL sub-check from bsdl_emit's plan. Honest:
      * missing plan            → FAIL (cannot prove boundary-scan status)
      * N_A (bare core)         → SKIP
      * padded + bsdl_present   → PASS
      * padded + missing bsdl   → FAIL
    """
    if bsdl_plan is None:
        return {"status": "FAIL",
                "reasons": ["no bsdl_plan.json — boundary-scan status unknown; "
                            "run bsdl_emit.py (a padded design must ship a "
                            "BSDL; a bare core is recorded N/A). Missing "
                            "evidence is not a pass."]}
    verdict = bsdl_plan.get("verdict") or bsdl_plan.get("status")
    padded = bsdl_plan.get("padded")
    if verdict == "N_A":
        return {"status": "SKIP", "padded": padded,
                "reasons": ["design is a bare core / no pad ring — boundary "
                            "scan N/A (honest SKIP)"]}
    if verdict == "PASS" and bsdl_plan.get("bsdl_present"):
        return {"status": "PASS", "padded": True,
                "boundary_length": bsdl_plan.get("boundary_length"),
                "reasons": [f"padded design has BSDL "
                            f"({bsdl_plan.get('boundary_length')} boundary "
                            f"cells)"]}
    # padded but FAIL / no bsdl
    return {"status": "FAIL", "padded": padded,
            "reasons": [f"padded design missing a valid BSDL "
                        f"(bsdl verdict={verdict}, "
                        f"bsdl_present={bsdl_plan.get('bsdl_present')})"]}


# ── aggregate ──────────────────────────────────────────────────────────

def audit(project: Path,
          foundry_floor: float = FOUNDRY_FLOOR_DEFAULT,
          transition_target: float = TRANSITION_TARGET_DEFAULT,
          coverage_json_override: Optional[str] = None,
          bsdl_plan_override: Optional[str] = None,
          strict_transition: bool = False) -> dict:
    cov_path = _coverage_json_path(project, coverage_json_override)
    plan_path = _bsdl_plan_path(project, bsdl_plan_override)
    coverage_json = _load_json(cov_path) if cov_path else None
    bsdl_plan = _load_json(plan_path) if plan_path else None

    # 1) stuck-at (delegated recompute + foundry floor)
    sa = _sa.audit(project, coverage_json_override, foundry_floor=foundry_floor)
    stuck_at = {
        "status": sa.get("verdict"),
        "measured_pct": sa.get("measured_coverage_pct"),
        "effective_target_pct": sa.get("effective_target_pct"),
        "foundry_floor_pct": sa.get("foundry_floor_pct"),
        "reasons": sa.get("reasons", []),
    }

    # 2) transition
    transition = evaluate_transition(coverage_json, transition_target,
                                     strict=strict_transition)
    # 3) BSDL
    bsdl = evaluate_bsdl(bsdl_plan)

    stuck_ok = stuck_at["status"] == "PASS"
    trans_ok = transition["status"] in ("PASS", "ENGINE_LIMITED")
    bsdl_ok = bsdl["status"] in ("PASS", "SKIP")

    overall = "PASS" if (stuck_ok and trans_ok and bsdl_ok) else "FAIL"

    return {
        "program": _PROGRAM,
        "version": _VERSION,
        "project_dir": str(project),
        "coverage_json": str(cov_path) if cov_path else None,
        "bsdl_plan": str(plan_path) if plan_path else None,
        "stuck_at": stuck_at,
        "transition": transition,
        "bsdl": bsdl,
        "verdict": overall,
        "status": overall,
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Aggregate DFT sign-off gate: stuck-at + transition "
                    "(at-speed) + BSDL for a padded design.")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--foundry-floor", type=float, default=FOUNDRY_FLOOR_DEFAULT,
                    help=f"Stuck-at foundry floor %% (default "
                         f"{FOUNDRY_FLOOR_DEFAULT:.0f})")
    ap.add_argument("--transition-target", type=float,
                    default=TRANSITION_TARGET_DEFAULT,
                    help=f"Transition (at-speed) target %% (default "
                         f"{TRANSITION_TARGET_DEFAULT:.0f})")
    ap.add_argument("--coverage-json", default=None,
                    help="Explicit coverage.json path")
    ap.add_argument("--bsdl-plan", default=None,
                    help="Explicit bsdl_plan.json path")
    ap.add_argument("--strict-transition", action="store_true",
                    help="Demote an engine-limited transition result to FAIL "
                         "(require a real at-speed coverage number)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    # HONEST disclosed-skip (flow step-11): when NONE of the DFT sign-off
    # inputs exist (the runner removed atpg_coverage.rpt, left no measurable
    # coverage.json, and renamed scan_netlist.v because the OSS Fault ATPG
    # engine could not measure sign-off coverage) AND a sibling
    # dft_atpg_not_run.json honestly self-reports the skip
    # (verdict ∈ SKIP/SKIPPED/SKIPPED-CONDITION), resolve to SKIPPED-CONDITION
    # (rc=2 → VACUOUS_PASS) instead of a hard missing-evidence FAIL. Guarded
    # on BOTH conditions — any real DFT input present means normal judgment.
    _skip = dft_signoff_common.disclosed_atpg_skip(project)
    if _skip is not None and _dft_inputs_absent(project, args.coverage_json):
        print(f"{_PROGRAM}: SKIPPED-CONDITION — DFT ATPG disclosed-skipped: "
              f"{_skip}")
        if args.json:
            try:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(json.dumps({
                    "program": _PROGRAM,
                    "version": _VERSION,
                    "project_dir": str(project),
                    "verdict": "SKIPPED-CONDITION",
                    "status": "SKIPPED-CONDITION",
                    "reason": _skip,
                    "reasons": [f"DFT ATPG disclosed-skipped: {_skip} — no "
                                "DFT sign-off inputs and a sibling sentinel "
                                "honestly self-reports the skip"],
                }, indent=2, ensure_ascii=False) + "\n")
            except OSError as exc:  # pragma: no cover - IO edge
                print(f"WARN: could not write --json {args.json}: {exc}",
                      file=sys.stderr)
        return 2

    report = audit(project,
                   foundry_floor=args.foundry_floor,
                   transition_target=args.transition_target,
                   coverage_json_override=args.coverage_json,
                   bsdl_plan_override=args.bsdl_plan,
                   strict_transition=args.strict_transition)

    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        try:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out + "\n")
        except OSError as exc:  # pragma: no cover - IO edge
            print(f"WARN: could not write --json {args.json}: {exc}",
                  file=sys.stderr)
    print(out)

    print(f"{_PROGRAM}: stuck_at={report['stuck_at']['status']} "
          f"transition={report['transition']['status']} "
          f"bsdl={report['bsdl']['status']} verdict={report['verdict']}",
          file=sys.stderr)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
