#!/usr/bin/env python3
"""Stage 4 (Output + Validation) interim gate.

Thin wrapper around `flow_compliance_check.py --stage 4`. Final stage —
covers power analysis, tapeout checklist, GDS output, and FPGA sign-off.
Exits 0 only if every step in Stage 4 is PASS (or WAIVED).

Usage:
    python3 stage4_compliance.py <project_dir> [--json out.json]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from flow_compliance_check import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:] + ["--stage", "4", "--strict"]
    sys.exit(main(argv))
