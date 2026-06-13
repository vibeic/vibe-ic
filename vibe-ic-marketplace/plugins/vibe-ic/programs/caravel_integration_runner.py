"""v0.1.51 — Caravel chipignite integration runner (B2 from spm pilot).

Doctrine: spm pilot's Phase A/B/C took 2 days hand-driven. This runner
orchestrates the same flow as ONE command for any future hard-macro
Caravel user project, calling existing v0.1.51 programs:

  Phase A (clone + RTL install + wrapper emit + config gen)
    1. Clone caravel_user_project template (cached)
    2. Install user's core GDS + LEF + Verilog stub into the project
    3. Emit user_project_wrapper.v   ← caravel_wrapper_emit.py (B3)
    4. Emit user_defines.v (GPIO modes)
    5. Emit openlane wrapper config.json

  Phase B (OpenLane wrapper-level PnR)
    6. Docker run efabless/openlane flow.tcl
    7. Assert: WNS >= 0, TritonRoute violations == 0
    8. Install wrapper GDS + LEF into Caravel project

  Phase C (mpw_precheck + auto-cleanup + waiver)
    9. Docker run efabless/mpw_precheck
   10. Apply 5 mechanical fix-ups ← mpw_precheck_cleanup.py (B4)
   11. Re-run precheck
   12. IF remaining FAIL == {Consistency, XOR}: auto-emit waiver pair
       (signoff_waiver_emit + signoff_waiver_md_emit)
   13. IF remaining FAIL != {Consistency, XOR}: STOP for human triage

The runner is PURE plan-and-orchestrate; it does not implement Docker
calls directly. Each Phase step returns a `PhaseStepResult` so a thin
shell wrapper can dispatch them serially.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# Hard-macro Caravel signoff floor (what spm pilot proved):
KNOWN_2_OF_7_FLOOR: frozenset = frozenset({"Consistency", "XOR"})


@dataclass
class PhaseStepResult:
    step_id: str           # "A1" .. "C12"
    phase: str             # "A", "B", "C"
    name: str
    verdict: str           # PASS / FAIL / NOT_RUN / WAIVED
    details: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    command_hint: str = ""  # if external, the shell command a wrapper would run

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Phase A — clone + RTL install + wrapper emit
# ---------------------------------------------------------------------------
def step_a1_clone_template(work_dir: Path) -> PhaseStepResult:
    """Plan: git clone caravel_user_project template."""
    target = work_dir / "caravel_user_project"
    if target.exists():
        return PhaseStepResult(
            "A1", "A", "Clone Caravel template", "PASS",
            details={"target": str(target)},
            notes="template already present; skipped clone")
    return PhaseStepResult(
        "A1", "A", "Clone Caravel template", "NOT_RUN",
        details={"target": str(target)},
        command_hint=(
            "git clone --depth=1 "
            "https://github.com/efabless/caravel_user_project.git "
            f"{target}"))


def step_a2_install_core(work_dir: Path, core_gds: Path,
                           core_lef: Path, core_v: Path,
                           project_name: str) -> PhaseStepResult:
    """Plan: copy core GDS + LEF + Verilog stub into caravel project."""
    target_proj = work_dir / "caravel_user_project"
    moves = [
        (core_gds, target_proj / "gds_user" / f"{project_name}.gds"),
        (core_lef, target_proj / "lef_user" / f"{project_name}.lef"),
        (core_v,   target_proj / "verilog" / "rtl" / f"{project_name}.v"),
    ]
    plan = []
    for src, dst in moves:
        if not src.exists():
            return PhaseStepResult(
                "A2", "A", "Install core artifacts", "FAIL",
                notes=f"source file missing: {src}")
        plan.append({"src": str(src), "dst": str(dst)})
    return PhaseStepResult(
        "A2", "A", "Install core artifacts", "NOT_RUN",
        details={"copies": plan},
        command_hint=" && ".join(
            f"cp {p['src']} {p['dst']}" for p in plan))


def step_a3_emit_wrapper(work_dir: Path,
                           pin_map: Path) -> PhaseStepResult:
    """Step A3: emit user_project_wrapper.v via caravel_wrapper_emit."""
    target = (work_dir / "caravel_user_project" /
              "verilog" / "rtl" / "user_project_wrapper.v")
    try:
        import caravel_wrapper_emit as cw
    except ImportError:  # pragma: no cover
        from . import caravel_wrapper_emit as cw  # type: ignore
    if not pin_map.exists():
        return PhaseStepResult(
            "A3", "A", "Emit user_project_wrapper.v", "FAIL",
            notes=f"pin-map missing: {pin_map}")
    pm = cw.load_pin_map(pin_map)
    errors = cw.validate_pin_map(pm)
    if errors:
        return PhaseStepResult(
            "A3", "A", "Emit user_project_wrapper.v", "FAIL",
            details={"errors": errors})
    text = cw.emit_wrapper(pm)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return PhaseStepResult(
        "A3", "A", "Emit user_project_wrapper.v", "PASS",
        details={"target": str(target),
                 "lines": len(text.splitlines())})


def step_a4_emit_user_defines(work_dir: Path,
                                pin_map: Path) -> PhaseStepResult:
    """Step A4: emit user_defines.v (GPIO modes) via caravel_wrapper_emit."""
    target = (work_dir / "caravel_user_project" /
              "verilog" / "rtl" / "user_defines.v")
    try:
        import caravel_wrapper_emit as cw
    except ImportError:  # pragma: no cover
        from . import caravel_wrapper_emit as cw  # type: ignore
    if not pin_map.exists():
        return PhaseStepResult(
            "A4", "A", "Emit user_defines.v (GPIO modes)", "FAIL",
            notes=f"pin-map missing: {pin_map}")
    pm = cw.load_pin_map(pin_map)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cw.emit_user_defines(pm), encoding="utf-8")
    return PhaseStepResult(
        "A4", "A", "Emit user_defines.v (GPIO modes)", "PASS",
        details={"target": str(target)})


# ---------------------------------------------------------------------------
# Phase B — OpenLane wrapper PnR (plan only; needs Docker)
# ---------------------------------------------------------------------------
def step_b1_openlane_wrapper_pnr(work_dir: Path) -> PhaseStepResult:
    """Step B1: docker run efabless/openlane flow.tcl on wrapper."""
    target = work_dir / "caravel_user_project"
    return PhaseStepResult(
        "B1", "B", "OpenLane wrapper PnR", "NOT_RUN",
        notes="external Docker step — see command_hint",
        command_hint=(
            "cd " + str(target) + " && "
            "make user_project_wrapper "
            "# or: docker run --rm -u $(id -u):$(id -g) "
            "-v $(pwd):/work efabless/openlane:2023.07.19-1 "
            "flow.tcl -design user_project_wrapper -save"))


def step_b2_assert_wrapper_pnr_clean(
    work_dir: Path,
    wns_threshold_ns: float = 0.0,
    routing_violation_threshold: int = 0,
) -> PhaseStepResult:
    """Step B2: WNS >= 0 AND routing violations == 0."""
    rpt = (work_dir / "caravel_user_project" / "openlane" /
           "user_project_wrapper" / "runs")
    target_metrics = (
        work_dir / "reports" / "openlane_wrapper" / "metrics.json")
    if not target_metrics.exists():
        return PhaseStepResult(
            "B2", "B", "Wrapper PnR clean (WNS / routing)",
            "NOT_RUN",
            notes="no metrics.json — expects "
                  "reports/openlane_wrapper/metrics.json with "
                  "{wns_ns, routing_violations}")
    data = json.loads(target_metrics.read_text(encoding="utf-8"))
    wns = float(data.get("wns_ns", -1e9))
    rv = int(data.get("routing_violations", -1))
    ok = (wns >= wns_threshold_ns and rv <= routing_violation_threshold)
    return PhaseStepResult(
        "B2", "B", "Wrapper PnR clean (WNS / routing)",
        "PASS" if ok else "FAIL",
        details={"wns_ns": wns, "routing_violations": rv,
                 "wns_threshold": wns_threshold_ns,
                 "rv_threshold": routing_violation_threshold})


# ---------------------------------------------------------------------------
# Phase C — precheck + cleanup + waiver
# ---------------------------------------------------------------------------
def step_c1_run_precheck(work_dir: Path) -> PhaseStepResult:
    """Step C1: docker run efabless/mpw_precheck."""
    target = work_dir / "caravel_user_project"
    return PhaseStepResult(
        "C1", "C", "mpw_precheck (initial)", "NOT_RUN",
        notes="external Docker step",
        command_hint=(
            "docker run --rm -u $(id -u):$(id -g) "
            f"-v {target}:/work "
            "efabless/mpw_precheck:latest "
            "bash -c 'python3 mpw_precheck.py "
            "--input_directory /work --pdk_path $PDK_ROOT/sky130A "
            "license makefile default documentation consistency "
            "gpio_defines xor'"))


def step_c2_cleanup(work_dir: Path, project_name: str,
                     pin_map: Path) -> PhaseStepResult:
    """Step C2: run mpw_precheck_cleanup automation."""
    try:
        import mpw_precheck_cleanup as cu
    except ImportError:  # pragma: no cover
        from . import mpw_precheck_cleanup as cu  # type: ignore
    target_proj = work_dir / "caravel_user_project"
    rep = cu.cleanup_project(target_proj, project_name, pin_map_path=pin_map)
    return PhaseStepResult(
        "C2", "C", "Mechanical cleanup (5 fix-ups)",
        rep.verdict if rep.verdict != "IDEMPOTENT" else "PASS",
        details={"fixes_applied": [f.fix_name for f in rep.fixes_applied
                                     if f.files_changed],
                 "total_files_changed": sum(
                     len(f.files_changed) for f in rep.fixes_applied)})


def step_c3_rerun_precheck(work_dir: Path) -> PhaseStepResult:
    """Step C3: re-run precheck after cleanup."""
    return PhaseStepResult(
        "C3", "C", "mpw_precheck (after cleanup)", "NOT_RUN",
        command_hint=step_c1_run_precheck(work_dir).command_hint,
        notes="external Docker step (same as C1)")


def step_c4_emit_waivers_if_at_floor(
    work_dir: Path,
    precheck_fail_set: Optional[List[str]] = None,
    project_name: str = "",
    submitter_email: str = "",
) -> PhaseStepResult:
    """Step C4: IF remaining FAIL == {Consistency, XOR} (the known
    hard-macro 2/7 floor), auto-emit the chipignite waiver pair.
    Otherwise STOP for human triage."""
    if precheck_fail_set is None:
        return PhaseStepResult(
            "C4", "C", "Waiver emit (if at 2/7 floor)", "NOT_RUN",
            notes="no precheck fail-set supplied")
    actual = frozenset(precheck_fail_set)
    if actual == KNOWN_2_OF_7_FLOOR:
        return PhaseStepResult(
            "C4", "C", "Waiver emit (at 2/7 floor → auto-emit)",
            "PASS",
            details={"fail_set": sorted(actual),
                     "next_step": "Call signoff_waiver_emit.py twice + "
                                   "signoff_waiver_md_emit.py for "
                                   "consistency_layout + xor_blackbox"},
            command_hint=(
                "python3 plugins/vibe-ic/programs/signoff_waiver_emit.py "
                f"--project-name {project_name} --failed-check Consistency "
                "--reason-class blackbox-macro-signoff-limit "
                "--approver " + (submitter_email or "<reviewer@org>") +
                " --mitigation ... --out signoff/waivers/consistency_layout.json"))
    return PhaseStepResult(
        "C4", "C",
        "Waiver emit — NOT at 2/7 floor; human triage required",
        "FAIL",
        details={"fail_set": sorted(actual),
                 "expected_floor": sorted(KNOWN_2_OF_7_FLOOR)},
        notes="Remaining FAIL set != known 2/7 hard-macro floor. "
              "Investigate before submission.")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
@dataclass
class IntegrationReport:
    work_dir: str
    project_name: str
    pin_map: str
    steps: List[PhaseStepResult]
    overall_verdict: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "work_dir": self.work_dir,
            "project_name": self.project_name,
            "pin_map": self.pin_map,
            "steps": [s.as_dict() for s in self.steps],
            "overall_verdict": self.overall_verdict,
            "emitted_by": "caravel_integration_runner v0.1.51",
        }


def overall_verdict(steps: List[PhaseStepResult]) -> str:
    """Roll up step verdicts."""
    if any(s.verdict == "FAIL" for s in steps):
        return "FAIL"
    if any(s.verdict == "NOT_RUN" for s in steps):
        return "PARTIAL_PLAN_READY"
    return "PASS"


def plan_integration(
    work_dir: Path,
    project_name: str,
    core_gds: Path,
    core_lef: Path,
    core_v: Path,
    pin_map: Path,
    precheck_fail_set: Optional[List[str]] = None,
    submitter_email: str = "",
) -> IntegrationReport:
    """Produce the full integration plan. Some steps (Docker-bound)
    return verdict=NOT_RUN with command_hint set; the caller's shell
    wrapper dispatches them. Programs that ARE pure (A3, A4, C2, C4)
    run their actual logic."""
    steps: List[PhaseStepResult] = []
    # Phase A
    steps.append(step_a1_clone_template(work_dir))
    steps.append(step_a2_install_core(
        work_dir, core_gds, core_lef, core_v, project_name))
    steps.append(step_a3_emit_wrapper(work_dir, pin_map))
    steps.append(step_a4_emit_user_defines(work_dir, pin_map))
    # Phase B
    steps.append(step_b1_openlane_wrapper_pnr(work_dir))
    steps.append(step_b2_assert_wrapper_pnr_clean(work_dir))
    # Phase C
    steps.append(step_c1_run_precheck(work_dir))
    steps.append(step_c2_cleanup(work_dir, project_name, pin_map))
    steps.append(step_c3_rerun_precheck(work_dir))
    steps.append(step_c4_emit_waivers_if_at_floor(
        work_dir, precheck_fail_set, project_name, submitter_email))
    return IntegrationReport(
        work_dir=str(work_dir),
        project_name=project_name,
        pin_map=str(pin_map),
        steps=steps,
        overall_verdict=overall_verdict(steps),
    )


def _cli() -> int:
    p = argparse.ArgumentParser(
        description="Caravel chipignite integration runner — "
                    "Phase A/B/C orchestrator from spm pilot")
    p.add_argument("--work-dir", type=Path, required=True)
    p.add_argument("--project-name", required=True)
    p.add_argument("--core-gds", type=Path, required=True)
    p.add_argument("--core-lef", type=Path, required=True)
    p.add_argument("--core-v", type=Path, required=True)
    p.add_argument("--pin-map", type=Path, required=True)
    p.add_argument("--submitter-email", default="")
    p.add_argument("--precheck-fail-set", action="append", default=[],
                   help="Pass after C1 run; e.g. --precheck-fail-set Consistency XOR")
    p.add_argument("--out-json", type=Path)
    args = p.parse_args()
    rep = plan_integration(
        args.work_dir, args.project_name,
        args.core_gds, args.core_lef, args.core_v,
        args.pin_map,
        precheck_fail_set=args.precheck_fail_set or None,
        submitter_email=args.submitter_email,
    )
    payload = rep.as_dict()
    if args.out_json:
        args.out_json.write_text(json.dumps(payload, indent=2),
                                  encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
