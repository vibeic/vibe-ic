#!/usr/bin/env python3
"""Stage 1 (RTL + Verification) interim gate.

Thin wrapper around `flow_compliance_check.py --stage 1`. Run this after
completing Steps 01-06 and before starting Stage 2 synthesis. Exits 0 only
if every step in Stage 1 is PASS (or WAIVED with an entry in waivers.json).

Usage:
    python3 stage1_compliance.py <project_dir> [--json out.json]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flow_compliance_check import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:] + ["--stage", "1", "--strict"]
    sys.exit(main(argv))
