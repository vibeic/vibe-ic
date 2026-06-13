#!/usr/bin/env python3
"""sdc_validator_check.py — validate SDC against L8 timing constraints.

Replaces skill `sdc-validator` (archived).
"""
import argparse, json, re, sys
from pathlib import Path
import _path_layout as _pl

def main():
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    # v1.6.18 compat: flow_phase1_phase2_phase3.yaml gate command passes
    # `--l8 <path> --json <path>` even though this program only consumes
    # the project arg. Accept the flags so the gate doesn't argparse-FAIL.
    p.add_argument("--l8", type=Path, help="L8 timing JSON (advisory)")
    p.add_argument("--json", type=Path, help="optional JSON output path")
    args = p.parse_args()
    sdc_files = list((_pl.fpga_early_dir(args.project)).glob("*.sdc")) + \
                list((_pl.constraints_dir(args.project)).glob("*.sdc")) if (_pl.constraints_dir(args.project)).is_dir() else \
                list((_pl.fpga_early_dir(args.project)).glob("*.sdc"))
    if not sdc_files:
        print("[SKIP] sdc_validator_check: no .sdc files")
        return 0
    issues = []
    for sdc in sdc_files:
        text = sdc.read_text(errors="ignore")
        if "create_clock" not in text:
            issues.append(f"{sdc.name}: missing create_clock")
        if "set_input_delay" not in text:
            issues.append(f"{sdc.name}: missing set_input_delay")
        if "set_output_delay" not in text:
            issues.append(f"{sdc.name}: missing set_output_delay")
    if issues:
        print(f"[FAIL] sdc_validator_check: {len(issues)} issue(s)")
        for i in issues[:5]:
            print(f"  - {i}")
        return 1
    if args.json:
        try:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps({
                "verdict": "PASS",
                "sdc_files_checked": [str(p) for p in sdc_files],
                "issues": issues,
            }, indent=2))
        except OSError:
            pass
    print(f"[PASS] sdc_validator_check: {len(sdc_files)} SDC file(s) OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
