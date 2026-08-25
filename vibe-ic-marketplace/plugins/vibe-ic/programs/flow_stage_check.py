#!/usr/bin/env python3
"""Flow stage check — wrapper for signoff_audit --mode flow.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This wrapper is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from signoff_audit import main
if __name__ == "__main__":
    sys.exit(main([sys.argv[1] if len(sys.argv) > 1 else ".", "--mode", "flow"]))
