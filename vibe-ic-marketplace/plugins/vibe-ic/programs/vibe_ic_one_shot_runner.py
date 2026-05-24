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
from typing import Any, Dict, List, Tuple
import _path_layout as _pl


PROGRAMS_DIR = Path(__file__).resolve().parent


def _phase_runner(name: str) -> Path:
    return PROGRAMS_DIR / f"{name}_one_shot_runner.py"


def _need_phase1(project: Path, force_skip: bool) -> bool:
    if force_skip:
        return False
    p1_struct = project / "input" / "phase1_structured.yaml"
    p1_prompt = project / "input" / "phase1_prompt.md"
    docs = project / "input" / "docs"
    gd = _pl.generated_docs_dir(project)
    L_count = len(list(gd.glob("L*.json"))) if gd.is_dir() else 0
    # Already has L docs → no need
    if L_count >= 13:
        return False
    # Has Path A inputs → run phase1
    if p1_struct.is_file() or p1_prompt.is_file():
        return True
    # Has vendor docs only → Path B (phase1 will handle)
    if docs.is_dir() and any(docs.iterdir()):
        return False
    # No inputs at all — phase1 will SKIP gracefully
    return False


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


def _run_phase(label: str, runner: Path, args: List[str]) -> int:
    print(f"\n{'='*72}\n=== {label} → {runner.name}\n{'='*72}")
    cp = subprocess.run([sys.executable, str(runner), *args])
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
    if any(v in ("PASS_WITH_WAIVERS", "WAIVED") for v in verdicts):
        return "PASS_WITH_WAIVERS"
    return "PASS"


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

    t0 = time.time()
    plan: List[Tuple[str, str, int]] = []   # (phase, verdict, rc)
    halted_at: str = ""
    reports: Dict[str, Any] = {}

    # ---------------- Phase 1 ----------------
    if _need_phase1(project, args.skip_phase1):
        runner = _phase_runner("phase1")
        rc = _run_phase("PHASE 1 (NL → L1-L13)", runner,
                         [str(project), "--ic-name", args.ic_name])
        rep = _read_report(_pl.report_path(project, "phase1_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("phase1", verdict, rc))
        reports["phase1"] = rep
        if verdict == "FAIL":
            halted_at = "phase1"
    else:
        plan.append(("phase1", "SKIPPED", 0))

    # ---------------- Phase 2 ----------------
    if not halted_at:
        runner = _phase_runner("phase2")
        p2_args = [str(project),
                   "--top-name", args.top_name,
                   "--container", args.container,
                   "--max-eco", str(args.max_eco)]
        if args.skip_hardware:
            p2_args.append("--skip-hardware")
        rc = _run_phase("PHASE 2 (= 2a + 2b)", runner, p2_args)
        rep = _read_report(_pl.report_path(project, "phase2_one_shot.json"))
        verdict = rep.get("verdict") or ("PASS" if rc == 0 else "FAIL")
        plan.append(("phase2", verdict, rc))
        reports["phase2"] = rep
        if verdict == "FAIL":
            halted_at = "phase2"
    else:
        plan.append(("phase2", "SKIPPED", 0))

    # ---------------- Analog A1..A8 ----------------
    # Run after Phase 2 so L5_ADI_SPEC is populated. Non-blocking on FAIL.
    if not halted_at and _need_analog(project, args.skip_analog):
        runner = _phase_runner("analog")
        rc = _run_phase("ANALOG A1..A8", runner,
                         [str(project), "--container", args.container])
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
                         runner, p3_args)
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
    print(f"  duration          : {summary['duration_s']:.1f}s")
    print(f"  final summary     : {'reports/final_summary.md' if fs_ok else 'NOT generated'}")
    print(f"{'='*72}")
    return 0 if overall in ("PASS", "PASS_WITH_WAIVERS") else 1


if __name__ == "__main__":
    sys.exit(main())
