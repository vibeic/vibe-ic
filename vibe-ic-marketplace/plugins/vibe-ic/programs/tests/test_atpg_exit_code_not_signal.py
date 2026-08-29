#!/usr/bin/env python3
"""BIDIRECTIONAL control for plugin_fixes/atpg-exit-code-not-signal.patch.

Usage:
    python3 test_atpg_exit_code_not_signal.py <path-to-fault_atpg_run.py>

Contract:
  * against the byte-identical PRE-FIX file  -> must FAIL (non-zero exit)
  * against the POST-FIX file                -> must PASS (exit 0)

Three cases, and the third is the one that matters most:

  1. FORWARD  — the defect. An engine that exits with its ELABORATION ERROR
     COUNT (>= the 128 floor) must NOT be classified as killed by a signal,
     and must NOT be retried.
  2. REVERSE  — the guard against "tighten the filter until the count is zero".
     A genuine signal death (exit 139 = 128+SIGSEGV, no diagnostic grammar in
     the log) must STILL be classified as a signal death and STILL be retried.
     A fix that simply stopped calling anything a crash would pass case 1 and
     fail here.
  3. FLOOR    — a clean non-zero exit below the floor is still not a signal
     death, with or without diagnostics. Unchanged behaviour must stay
     unchanged.

Pure: no docker, no PDK, no design, no I/O beyond importing the module.

HOW THIS FILE IS EXECUTED. It is named `test_*.py` and pytest collects ZERO
tests from it, because it is a CLI parameterised by the program path and not a
pytest module — that is deliberate, and it is the only shape in which the
negative half of the contract above can be driven. It is not dead:
`test_bidirectional_controls_are_executed.py` runs it BOTH ways on every suite
run (against the shipped program, and against a copy with the fixed construct
removed), and lists it in that file's `DRIVEN` set, which
`test_no_test_file_collects_zero_tests` re-checks. Delete the entry there and
this file becomes an undeclared zero-collect module, which that test fails on.
"""
import importlib.util
import sys
from pathlib import Path

# The real log the flow captured when the ATPG input referenced a cell it had
# no model for. Cell name redacted -- the grammar is what is load-bearing, and
# the grammar is Icarus Verilog's, not any PDK's.
ELAB_ERROR_LOG = """ SOME_CELL
153 error(s) during elaboration.
*** These modules were missing:
        SOME_CELL referenced 2 times.
***
/work/phase2/stage2/dft/cut_netlist.v:15485: error: Unknown module type: SOME_CELL
153 error(s) during elaboration.
"""

# What a real SIGSEGV leaves behind: the engine's normal progress chatter, cut
# off mid-stride. No error report, because it never got to write one.
SIGSEGV_LOG = """[INFO] reading netlist
[INFO] building fault list
[INFO] 1080 faults collected
"""


def load(path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("fault_atpg_run_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(path: Path) -> int:
    try:
        mod = load(path)
    except Exception as exc:                       # pragma: no cover
        print(f"FAIL: could not import {path}: {exc!r}")
        return 2

    fn = getattr(mod, "atpg_exit_is_signal_death", None)
    if fn is None:
        print("FAIL: no atpg_exit_is_signal_death() — this file classifies a "
              "high exit code as death by signal on the number ALONE, so an "
              "engine that exits with its error count is misread as a crash.")
        return 1

    failures = []

    # 1. FORWARD — the defect this fix exists to remove.
    if fn(153, ELAB_ERROR_LOG):
        failures.append(
            "exit 153 with '153 error(s) during elaboration' in the log was "
            "classified as death by signal 25 — it is the engine's error count")
    if fn(154, ELAB_ERROR_LOG):
        failures.append("exit 154 with an elaboration-error log misclassified")

    # 2. REVERSE — must STILL be a signal death, must STILL be retried.
    if not fn(139, SIGSEGV_LOG):
        failures.append(
            "exit 139 (128+SIGSEGV) with NO engine diagnostic was NOT "
            "classified as a signal death — the fix over-reached and a real "
            "crash lost its retry")
    if not fn(137, SIGSEGV_LOG):
        failures.append("exit 137 (128+SIGKILL) with no diagnostic misclassified")
    if not fn(128, ""):
        failures.append("exit 128 with an EMPTY log must stay a signal death "
                        "(ambiguous input must not be reclassified)")

    # 3. FLOOR — unchanged behaviour stays unchanged.
    for ec in (0, 1, 2, 127):
        if fn(ec, SIGSEGV_LOG) or fn(ec, ELAB_ERROR_LOG):
            failures.append(f"exit {ec} is below the floor and is never a "
                            f"signal death, but was classified as one")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: forward (error-count exit is not a crash), reverse (real "
          "signal death keeps its retry), floor (unchanged) — 11 assertions")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
