#!/usr/bin/env python3
"""bringup_plan_gen.py — emit bring-up plan from L13_LAB_CALIBRATION.

Replaces skill `bringup-plan` (archived).
"""
import argparse, json, sys
from pathlib import Path
import _path_layout as _pl

def main():
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    args = p.parse_args()
    l13 = _pl.generated_docs_dir(args.project) / "L13_LAB_CALIBRATION.json"
    out = _pl.report_path(args.project, "bringup_plan.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not l13.is_file():
        out.write_text("# Bringup plan\n\n(Empty — L13_LAB_CALIBRATION not generated yet.)\n")
        print(f"[SKIP] bringup_plan_gen: no L13")
        return 0
    try:
        d = json.loads(l13.read_text())
    except Exception:
        d = {}
    steps = d.get("calibration_steps") or d.get("trim_loop") or []
    md = ["# Bring-up plan", ""]
    for s in steps:
        if isinstance(s, dict):
            md.append(f"- [{s.get('step','?')}] {s.get('action','?')} → {s.get('expected','?')}")
    out.write_text("\n".join(md) + "\n")
    print(f"[PASS] bringup_plan_gen: {len(steps)} steps → {out.name}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
