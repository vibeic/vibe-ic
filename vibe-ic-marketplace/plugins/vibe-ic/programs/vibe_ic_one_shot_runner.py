#!/usr/bin/env python3
"""vibe_ic_one_shot_runner.py — full Vibe-IC flow orchestrator.

Top-level chain that runs the entire spec → silicon pipeline:

    Phase 1 (optional)  → input/phase1_* → generated_docs/L*.json
        ↓
    Phase 2 (= 2a + 2b) → input/docs → 13 L docs → RTL → SOF → <half-duplex-tester>
        ↓
    Analog A1..A8        → analog/<block> hardmacros (skipped if no analog)
        ↓
    Phase 3              → synth → PnR → GDS → DRC → LVS

chip-AGNOSTIC. Auto-detects entry point:
  - Path A (NL prompt):  <project>/input/phase1_structured.yaml present
  - Path B (vendor docs): <project>/input/docs/ already populated;
                          phase1 SKIPped automatically.

Halt rules:
  - Phase 1 FAIL → halt before Phase 2
  - Phase 2 FAIL → halt before Phase 3 (and analog skipped if not run yet)
  - Analog WAIVED is non-blocking
  - Phase 3 FAIL → final verdict FAIL but report still emitted

Aggregate report: <project>/reports/vibe_ic_one_shot.json
Per-phase reports: phase1/phase2/phase1/phase2/phase3/analog _one_shot.json

Usage:
    python3 vibe_ic_one_shot_runner.py <project>
            [--top-name chip_top]
            [--container iic-eda]
            [--max-eco 3]
            [--skip-hardware]
            [--skip-phase1]
            [--skip-analog]
            [--skip-phase3]
            [--die-um 1500x1500]
            [--util 0.4]
            [--pdk auto|sky130A|<custom>]
            [--ic-name <name>]      # forwarded to phase1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl
import _runner_lock


PROGRAMS_DIR = Path(__file__).resolve().parent


def _phase_runner(name: str) -> Path:
    return PROGRAMS_DIR / f"{name}_one_shot_runner.py"


def _phase1_decision(project: Path, force_skip: bool) -> Tuple[bool, str]:
    """Decide whether to run Phase 1 and in which mode.

    Returns (run, mode) where:
      run  -> True if phase1 must run before phase2
      mode -> "prompt" (Path A NL inputs), "docs" (Path B vendor docs),
              or "" when run is False.

    Path-B fix (v-orch): when a project carries POPULATED vendor docs
    (input/docs/ or phase1/input_doc/) but no generated L*.json yet,
    phase2 hard-requires the L docs, so the orchestrator MUST auto-run
    phase1 in docs mode rather than skip it. Previously docs-only
    projects skipped phase1 and dead-ended at the phase2 precondition.

    chip-AGNOSTIC — path existence + L-doc count only.
    """
    if force_skip:
        return (False, "")
    p1_struct = project / "input" / "phase1_structured.yaml"
    p1_prompt = project / "input" / "phase1_prompt.md"
    docs = project / "input" / "docs"
    # phase1/input_doc/ is the canonical Path-B raw-corpus location.
    input_doc = (_pl.input_doc_dir(project)
                 if hasattr(_pl, "input_doc_dir") else None)
    gd = _pl.generated_docs_dir(project)
    L_count = len(list(gd.glob("L*.json"))) if gd.is_dir() else 0
    # Already has the full L-doc set → nothing to do.
    if L_count >= 13:
        return (False, "")
    def _has_extractable(d: Path) -> bool:
        # #583 — "populated" means at least one real, non-empty,
        # non-hidden document (a .gitkeep placeholder must not flip a
        # prompt-only project into docs mode).
        if not d.is_dir():
            return False
        for f in d.rglob("*"):
            if f.is_file() and not f.name.startswith(".") \
                    and f.stat().st_size > 0:
                return True
        return False

    docs_populated = _has_extractable(docs)
    input_doc_populated = bool(input_doc) and _has_extractable(input_doc)
    # UNIFIED DOC->JSON backend (owner directive 2026-06-20): EVERY front-end —
    # vendor docs, a free-text prompt, OR a dialogue convergence fact-graph —
    # flows through the one doc-extraction track so the L1-L24 JSON is
    # homogeneous. So the orchestrator now resolves ALL of them to "docs";
    # phase1_one_shot_runner --mode docs render-bridges a phase1_structured.yaml
    # (dialogue) / phase1_prompt.md (prose) into input/docs/ and re-detects the
    # precise mode. The legacy engine reverse-extractor stays reachable only via
    # an explicit `phase1_one_shot_runner --mode prompt` invocation.
    if (p1_struct.is_file() or docs_populated or input_doc_populated
            or p1_prompt.is_file()):
        return (True, "docs")
    # No inputs at all — phase1 will SKIP gracefully (don't run).
    return (False, "")


def _need_phase1(project: Path, force_skip: bool) -> bool:
    """Back-compat boolean wrapper around `_phase1_decision`."""
    run, _mode = _phase1_decision(project, force_skip)
    return run


def _need_analog(project: Path, force_skip: bool) -> bool:
    if force_skip:
        return False
    for cand in (_pl.analog_dir(project) / "analog_block_list.json",
                  project / "input" / "analog_block_list.json"):
        if cand.is_file():
            return True
    l5 = _pl.generated_docs_dir(project) / "L5_ADI_SPEC.json"
    if l5.is_file():
        try:
            d = json.loads(l5.read_text())
            if d.get("no_analog") is True:
                return False
            blocks = d.get("analog_blocks") or d.get("blocks")
            if isinstance(blocks, list) and any(blocks):
                return True
        except Exception:
            pass
    return False


def _run_phase(label: str, runner: Path, args: List[str],
               env: Optional[Dict[str, str]] = None) -> int:
    print(f"\n{'='*72}\n=== {label} → {runner.name}\n{'='*72}")
    # ORGANIC #588 — pass the re-entrancy env so the spawned standalone
    # phase runner re-enters THIS orchestrator's project lock instead of
    # being refused by it.
    cp = subprocess.run([sys.executable, str(runner), *args], env=env)
    return cp.returncode


def _read_report(p: Path) -> Dict[str, Any]:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"verdict": "FAIL", "error": f"parse failed: {p}"}


def _aggregate(verdicts: List[str]) -> str:
    if any(v == "FAIL" for v in verdicts):
        return "FAIL"
    # v0.3.7 — ORGANIC #505: COVERAGE-INCOMPLETE is a non-gating advisory
    # tier (a demoted coverage-only phase1 failure in the standalone-design
    # shape). It does NOT fail the run but DOES surface as PASS_WITH_WAIVERS
    # so the overall verdict never hides the documented doc-extraction gap.
    if any(v in ("PASS_WITH_WAIVERS", "WAIVED", "COVERAGE-INCOMPLETE")
           for v in verdicts):
        return "PASS_WITH_WAIVERS"
    return "PASS"


def _phase1_failure_is_coverage_only(project: Path) -> Tuple[bool, dict]:
    """v0.3.7 — ORGANIC #505. Read the phase1 exit-reason sidecar
    (``reports/phase1/phase1_exit_reason.json``, written by
    phase1_doc_one_shot_runner) and report whether phase1's FAIL is
    attributable SOLELY to doc-extraction coverage (orthogonal to the RTL
    deliverable). Returns ``(coverage_only, reason_dict)``; ``(False, {})``
    when the sidecar is absent/unreadable (e.g. prompt-mode phase1 that
    never wrote one) so the default halting behaviour is preserved."""
    f = project / "reports" / "phase1" / "phase1_exit_reason.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, {}
    return bool(d.get("coverage_only_failure")), d


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--top-name", default="chip_top")
    p.add_argument("--container", default="iic-eda")
    p.add_argument("--max-eco", type=int, default=3)
    p.add_argument("--skip-hardware", action="store_true")
    p.add_argument("--skip-phase1", action="store_true")
    p.add_argument("--skip-analog", action="store_true")
    p.add_argument("--skip-phase3", action="store_true")
    p.add_argument("--die-um", default="1500x1500")
    p.add_argument("--util", type=float, default=0.4)
    p.add_argument("--pdk", default="auto")
    p.add_argument("--ic-name", default="UNNAMED_CHIP")
    args = p.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    # ---------------- Single-driver project lock (ORGANIC #498) ----------
    # Refuse a second concurrent invocation on a project already being
    # driven by a LIVE runner; clean a stale lock left by a dead one.
    # Acquired BEFORE any reports/manifests/provenance are written so two
    # racing orchestrators can never co-write the same reports/ tree.
    lock = _runner_lock.acquire_or_reenter(project, "vibe_ic_one_shot_runner")
    if lock is None:
        return 3
    # #588 — env passed to every delegated standalone phase runner so it
    # re-enters this orchestrator's lock instead of being refused by it.
    _phase_env = _runner_lock.child_env(project, held_lock=lock)

    t0 = time.time()
    plan: List[Tuple[str, str, int]] = []   # (phase, verdict, rc)
    halted_at: str = ""
    reports: Dict[str, Any] = {}
    advisories: List[str] = []   # v0.3.7 #505 — non-gating notes

    # ---------------- Phase 1 ----------------
    run_phase1, p1_mode = _phase1_decision(project, args.skip_phase1)
    if run_phase1:
        runner = _phase_runner("phase1")
        p1_args = [str(project), "--ic-name", args.ic_name]
        # Path B (vendor docs, no L docs yet): force docs mode so the
        # doc-extraction track runs and produces L*.json for phase2.
        if p1_mode == "docs":
            p1_args += ["--mode", "docs"]
        label = ("PHASE 1 (vendor docs → L1-L23)" if p1_mode == "docs"
                 else "PHASE 1 (NL → L1-L23)")
        rc = _run_phase(label, runner, p1_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "phase1_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("phase1", verdict, rc))
        reports["phase1"] = rep
        if verdict == "FAIL":
            # v0.3.7 — ORGANIC #505: in the standalone-design shape
            # (--skip-phase3 → the RTL is the deliverable, no silicon
            # backend), a phase1 failure that is PURELY doc-extraction
            # coverage is orthogonal to the RTL verdict. Demote it to a
            # non-gating COVERAGE-INCOMPLETE advisory and let phase2 run,
            # so the overall verdict reflects the actual RTL deliverable
            # (synth / lint / sdc). A TODO-stub or hard phase1 failure is
            # NOT coverage-only and still halts. Full-chip flows (phase3
            # in scope) keep halting — doc-extraction feeds the backend.
            cov_only, cov_reason = _phase1_failure_is_coverage_only(project)
            if args.skip_phase3 and cov_only:
                plan[-1] = ("phase1", "COVERAGE-INCOMPLETE", rc)
                advisories.append(
                    f"phase1 doc-extraction COVERAGE-INCOMPLETE "
                    f"(coverage {cov_reason.get('coverage_pct')}%, "
                    f"todo {cov_reason.get('total_todo')}): non-gating in "
                    f"the standalone-design shape — the RTL deliverable "
                    f"verdict follows phase2; close the doc-extraction gap "
                    f"before a full-chip (phase3) flow."
                )
            else:
                halted_at = "phase1"
    else:
        plan.append(("phase1", "SKIPPED", 0))

    # ---------------- Analog-applicability decision ----------------
    # Single source of truth (ORGANIC-20260606 #459): the analog-track
    # applicability is decided ONCE here, BEFORE phase2 runs, so the same
    # decision can (a) gate the analog A-track invocation below AND (b)
    # be forwarded into phase2's final_audit. Previously _need_analog()
    # was evaluated only AFTER phase2; phase2 therefore never learned that
    # the orchestrator was skipping the analog track, and final_audit
    # treated analog A9 as a HARD condition → every pure-digital run
    # halted at phase2. The two decision points now agree.
    run_analog = _need_analog(project, args.skip_analog)

    # ---------------- Phase 2 ----------------
    if not halted_at:
        runner = _phase_runner("phase2")
        p2_args = [str(project),
                   "--top-name", args.top_name,
                   "--container", args.container,
                   "--max-eco", str(args.max_eco)]
        if args.skip_hardware:
            p2_args.append("--skip-hardware")
        # v0.1.54 capture: forward --skip-analog so phase2 final_audit doesn't
        # FAIL a digital-only project on missing phase1/analog/analog_block_list.json.
        # (1) User explicitly asked to skip the analog track.
        if args.skip_analog:
            p2_args.append("--skip-analog")
        # (2) #459: the orchestrator's OWN analog decision is authoritative. If
        # we are NOT running the A-track because _need_analog()==False (even
        # without a user --skip-analog), phase2's final_audit must agree — so
        # inject --skip-analog here too. For analog / mixed-signal projects
        # (run_analog==True) the flag is NEVER injected, so the A-track and its
        # final_audit condition stay active (corpus-sweep guard). The membership
        # guard makes (1)+(2) idempotent (no duplicate append).
        elif not run_analog:
            p2_args.append("--skip-analog")
        rc = _run_phase("PHASE 2 (= 2a + 2b)", runner, p2_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "phase2_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("phase2", verdict, rc))
        reports["phase2"] = rep
        if verdict == "FAIL":
            halted_at = "phase2"
    else:
        plan.append(("phase2", "SKIPPED", 0))

    # ---------------- Analog A1..A8 ----------------
    # Non-blocking on FAIL. Dispatches off the single run_analog decision
    # computed above (#459) so the A-track invocation and phase2's
    # --skip-analog forwarding never disagree. The decision is sourced from
    # phase1 artefacts (L5_ADI_SPEC / analog_block_list), which are produced
    # before this point — phase2 does not emit them — so moving the decision
    # ahead of phase2 is behaviourally identical for analog/mixed-signal.
    if not halted_at and run_analog:
        runner = _phase_runner("analog")
        rc = _run_phase("ANALOG A1..A8", runner,
                         [str(project), "--container", args.container],
                         env=_phase_env)
        rep = _read_report(_pl.report_path(project, "analog_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("analog", verdict, rc))
        reports["analog"] = rep
        # Analog FAIL is logged but does NOT halt the digital flow —
        # downstream Phase 3 still proceeds (analog hardmacros land
        # via Step 14 floorplan in a future iteration).
    else:
        plan.append(("analog", "SKIPPED", 0))

    # ---------------- Phase 3 ----------------
    if not halted_at and not args.skip_phase3:
        runner = _phase_runner("phase3")
        p3_args = [str(project),
                   "--top-name", args.top_name,
                   "--container", args.container,
                   "--die-um", args.die_um,
                   "--util", str(args.util),
                   "--pdk", args.pdk]
        rc = _run_phase("PHASE 3 (synth → PnR → GDS → DRC → LVS)",
                         runner, p3_args, env=_phase_env)
        rep = _read_report(_pl.report_path(project, "phase3_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("phase3", verdict, rc))
        reports["phase3"] = rep
        if verdict == "FAIL":
            halted_at = "phase3"
    else:
        plan.append(("phase3", "SKIPPED", 0))

    # ---------------- Aggregate ----------------
    digital_verdicts = [v for n, v, _ in plan
                        if n != "analog" and v != "SKIPPED"]
    overall = _aggregate(digital_verdicts) if digital_verdicts else "FAIL"
    summary = {
        "phase": "vibe-ic",
        "project": str(project),
        "duration_s": time.time() - t0,
        "halted_at": halted_at or None,
        "phases": [{"name": n, "verdict": v, "rc": rc} for n, v, rc in plan],
        "advisories": advisories,   # v0.3.7 #505 — non-gating notes
        "verdict": overall,
    }
    out = _pl.report_path(project, "vibe_ic_one_shot.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    # v1.6.32: emit canonical final_summary.md (best-effort). Note that
    # phase23_one_shot_runner ALSO calls this; vibe_ic delegates to
    # phase23 today, so the final summary will be regenerated here on
    # the chained-end. Idempotent — generator overwrites.
    fs_ok = _pl.emit_final_summary(project, PROGRAMS_DIR)

    print(f"\n{'='*72}")
    print(f"=== vibe_ic_one_shot_runner DONE — {out}")
    print(f"  overall verdict   : {overall}")
    if halted_at:
        print(f"  halted at         : {halted_at}")
    for n, v, _ in plan:
        print(f"    {n:8} : {v}")
    for adv in advisories:   # v0.3.7 #505 — non-gating advisories
        print(f"  advisory          : {adv}")
    print(f"  duration          : {summary['duration_s']:.1f}s")
    print(f"  final summary     : {'reports/final_summary.md' if fs_ok else 'NOT generated'}")
    print(f"{'='*72}")
    lock.release()  # explicit; atexit/signal handlers are the backstop
    return 0 if overall in ("PASS", "PASS_WITH_WAIVERS") else 1


if __name__ == "__main__":
    sys.exit(main())
