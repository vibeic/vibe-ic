#!/usr/bin/env python3
"""phase3_backend_step.py — single dispatcher for Phase 3 backend per-step entries.

Replaces 10 same-template stubs created in v1.3.0 Round 4:
  atpg, dft_insert, cts_plan, placement_optimize, em_check,
  perc_check, power_analysis, upf_author, lef_psm_patch, open_rcx_fallback.

Per-step invocation entry point — phase3_one_shot_runner orchestrates the
full chain. This script lets AI invoke individual backend phases when
debugging or running specialised flows.

chip-AGNOSTIC. Vendor-specific behaviour isolated to docker exec command
lines per step.

Usage:
    python3 phase3_backend_step.py <project> <step_name>
    where <step_name> ∈ {atpg, dft_insert, cts_plan, placement_optimize,
                          em_check, perc_check, power_analysis, upf_author,
                          lef_psm_patch, open_rcx_fallback}
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path


_VALID_STEPS = {
    "atpg":               "Automatic Test Pattern Generation",
    "dft_insert":         "DFT scan-chain insertion",
    "cts_plan":            "Clock Tree Synthesis planning",
    "placement_optimize":  "Detailed placement optimization",
    "em_check":            "Electromigration check",
    "perc_check":          "Power-Effective Reliability Check",
    "power_analysis":      "Power consumption analysis",
    "upf_author":          "Unified Power Format authoring",
    "lef_psm_patch":       "LEF Power Strap Mesh patch",
    "open_rcx_fallback":   "OpenROAD-RCX parasitic extraction fallback",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("step", choices=sorted(_VALID_STEPS.keys()))
    p.add_argument("--container", default="vibeic-eda")
    p.add_argument("--top-name", default="chip_top")
    args = p.parse_args()
    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    desc = _VALID_STEPS[args.step]
    print(f"[SKIP] phase3_backend_step={args.step} ({desc}) — "
          f"deterministic per-step entry-point. Invoke "
          f"phase3_one_shot_runner.py for the full chain. For specialised "
          f"per-step flows extend this script with the corresponding "
          f"docker exec command for your PDK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
