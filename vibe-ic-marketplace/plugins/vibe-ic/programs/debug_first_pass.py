#!/usr/bin/env python3
"""debug_first_pass.py — single dispatcher for debug-skill deterministic first-pass.

Replaces 7 same-template stubs created in v1.3.0 Round 5:
  drc_fix, hold_fix, ir_drop_triage, lvs_triage, ppa_predict, sta_review,
  synth_doctor.

Each call emits a `<project>/reports/<step>_first_pass.json` with verdict
PASS_DEFERRED_TO_AI — programs handle known patterns; AI's debug-tier
skills (rtl-repair / drc-fix / synth-doctor / ...) take over for novel
patterns per the 4-tier model.

chip-AGNOSTIC. Future iterations replace the placeholder with real
known-pattern fix tables per step.

Usage:
    python3 debug_first_pass.py <project> <step_name>
    where <step_name> ∈ {drc_fix, hold_fix, ir_drop_triage, lvs_triage,
                          ppa_predict, sta_review, synth_doctor}
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import _path_layout as _pl


_VALID_STEPS = {
    "drc_fix":          "DRC violation auto-fix (known patterns)",
    "hold_fix":         "STA hold-time violation repair",
    "ir_drop_triage":   "IR-drop hot-spot triage",
    "lvs_triage":       "LVS mismatch triage",
    "ppa_predict":      "PPA prediction from synth/PnR reports",
    "sta_review":       "STA timing review",
    "synth_doctor":     "Synthesis log analysis",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("step", choices=sorted(_VALID_STEPS.keys()))
    args = p.parse_args()
    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    desc = _VALID_STEPS[args.step]
    out = _pl.report_path(project, f"{args.step}_first_pass.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "step": args.step,
        "description": desc,
        "verdict": "PASS_DEFERRED_TO_AI",
        "note": (f"deterministic first-pass placeholder — novel patterns "
                  f"should fall back to skill `{args.step.replace('_','-')}` "
                  f"for AI close-loop."),
    }
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[PASS_DEFERRED] debug_first_pass={args.step} ({desc}) → "
          f"{out.name} — invoke skill `{args.step.replace('_','-')}` for "
          f"full close-loop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
