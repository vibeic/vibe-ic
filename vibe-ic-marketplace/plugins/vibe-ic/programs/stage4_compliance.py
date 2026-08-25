#!/usr/bin/env python3
"""Stage 4 (Output + Validation) interim gate.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
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
