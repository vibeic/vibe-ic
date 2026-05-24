#!/usr/bin/env python3
"""Stage 2 (Synthesis + DFT) interim gate.

Thin wrapper around `flow_compliance_check.py --stage 2`. Run this after
completing Steps 07-13 and before starting Stage 3 floorplan/placement.
Exits 0 only if every Stage 2 step is PASS (or WAIVED).

Usage:
    python3 stage2_compliance.py <project_dir> [--json out.json]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flow_compliance_check import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:] + ["--stage", "2", "--strict"]
    sys.exit(main(argv))
