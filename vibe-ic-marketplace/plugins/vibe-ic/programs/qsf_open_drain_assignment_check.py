#!/usr/bin/env python3
"""
qsf_open_drain_assignment_check.py — DEPRECATED in v0.119.29.

Why this gate is now a stub
===========================
v0.119.27 introduced this gate based on the v0.119.25 noris hypothesis
that a missing `set_instance_assignment -name OPEN_DRAIN ON -to <pad>`
in the project's QSF was the byte[6]=0x02 <half-duplex-tester> root cause.

The v0.119.27 noris benchmark proved that hypothesis wrong:

  • `OPEN_DRAIN ON` is NOT a valid Quartus pin-level instance
    assignment on MAX10 / Cyclone — adding it produces Quartus
    error 125048 ("the assignment name does not exist").

  • Quartus auto-infers OPEN_DRAIN_OUTPUT pad type from the
    RTL ternary pattern `(oe && !tx) ? 1'b0 : 1'bz` already
    enforced by LL-17 (`half_duplex_wrapper_open_drain_check`).
    No additional QSF entry is required.

So the gate as designed FAILed correct projects and instructed users
to add a non-existent QSF assignment. The agent on the v0.119.27 noris
run had to waiver the gate to proceed — a sign that the gate itself
was the false alert, not the project.

This file is kept (rather than deleted) so that any external caller
that imports it gets a graceful PASS + deprecation notice instead of
ImportError. The gate is NOT registered in
`flow_compliance_check._STRUCTURAL_RTL_GATES` from v0.119.29 onwards.

If you want to audit FPGA pad type on a half-duplex bus pin, rely on:
  - `half_duplex_wrapper_open_drain_check` (LL-17) — RTL pattern
  - `fpga_pad_fanout_check` — Quartus fitter result for fan-out
  - QSF `set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON` — set
    by the project's pin assignment, not audited by any gate

Usage
-----
python3 qsf_open_drain_assignment_check.py <project_dir>

Always returns 0 (PASS, deprecated). Prints a deprecation notice.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    # Accept project_dir for CLI-shape compatibility but don't act on it.
    if len(sys.argv) < 2:
        print("Usage: qsf_open_drain_assignment_check.py <project_dir>")
        return 2
    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.is_dir():
        print(f"FAIL — not a directory: {project_dir}")
        return 1
    print("PASS — gate deprecated in v0.119.29.")
    print("  Reason: the prescribed QSF form `OPEN_DRAIN ON` causes")
    print("  Quartus error 125048 (assignment name does not exist on")
    print("  MAX10 / Cyclone). Quartus auto-infers OPEN_DRAIN_OUTPUT")
    print("  from the RTL ternary pattern already enforced by LL-17,")
    print("  no extra QSF entry required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
