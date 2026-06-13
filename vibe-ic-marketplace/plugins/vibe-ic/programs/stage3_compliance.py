#!/usr/bin/env python3
"""Stage 3 (Physical Design + Sign-off) interim gate.

Thin wrapper around `flow_compliance_check.py --stage 3`. Run this after
completing Steps 14-24. GDS (Step 27) is in Stage 4 and is gated on Stage 3
being fully clean — do NOT produce GDS if this gate fails.

Usage:
    python3 stage3_compliance.py <project_dir> [--json out.json]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flow_compliance_check import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:] + ["--stage", "3", "--strict"]
    sys.exit(main(argv))
