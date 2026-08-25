#!/usr/bin/env python3
"""Stage 2 (Synthesis + DFT) interim gate.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
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
