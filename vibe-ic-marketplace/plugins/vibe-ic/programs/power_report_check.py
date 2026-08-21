#!/usr/bin/env python3
"""Power report check — wrapper for eda_report_audit --mode power.

Forwards every extra CLI arg through to eda_report_audit (so ``--json <path>``
etc. work), while defaulting the project dir to ``.`` and pinning
``--mode power`` against BOTH caller spellings (``--mode lvs`` and
``--mode=lvs``).

Before this the wrapper rebuilt argv as
``[argv[1] or ".", "--mode", "power"]`` and dropped everything else, so the
``--json`` the flow yaml declared for Step 33 was silently discarded and the
checker's audit trail was never written to disk — only printed. Same shape, and
same fix, as lvs_report_check (#507).

The forwarding splitter is value-aware; see `split_argv` for the two ways the
first cut of it was wrong and what each measured.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main


# Options of the WRAPPED program (eda_report_audit) that consume the token
# after them. The splitter has to know these: without it, the argument of a
# value-taking option that precedes the positional is a bare token and gets
# read as the project dir.
# vibe-ic gatekeeper (#489/#490): this file used to carry its OWN
# `_VALUE_FLAGS` and `split_argv`. Both were correct when written and had
# ALREADY DRIFTED by the time this batch landed — the local copy read
# ("--mode", "--json") while the shared helper had gained "--under" (#485
# gives `eda_report_audit` a value-taking --under, so `--under sub/dir myproj`
# resolved the project to `sub/dir` and forwarded the real project as the
# scope). Two implementations of one question is exactly how this defect class
# propagated; #489 factored the helper and #490 flagged this copy before it
# could land beside it.
from _report_check_argv import split_and_pin


RC_FAIL = 1


def run(caller_argv) -> int:
    """Resolve the caller's argv and run the pinned power audit.

    EVERY non-audit exit maps to RC_FAIL, and that is the whole point of
    wrapping `main` instead of calling `sys.exit(main(...))` directly.
    `flow_compliance_check._check_program_exit_zero` credits rc 2 as a
    VACUOUS_PASS and `return True`s unconditionally, so argparse's own rc 2 —
    which it raises for an unknown flag, a flag missing its value, or a
    duplicate positional — turned Step 33 GREEN. `--help` was worse: rc 0,
    a sign-off credit spent on a program that audited nothing.

    Measured before this change, against `drc`/`lvs`, which already had it:

        power  --json=2  --under=2  --nonsuch=2  <proj> <proj>=2  --help=0
        drc    --json=1  --under=1  --nonsuch=1  <proj> <proj>=1  --help=1
        lvs    --json=1  --under=1  --nonsuch=1  <proj> <proj>=1  --help=1

    `power_report_check` adopted the shared splitter in this same batch but
    not the rc contract that goes with it. Nothing caught it because
    `test_wrapper_argv_forwarding._WRAPPERS` covers drc / ir_drop / antenna
    and power appears in neither arm.
    """
    # `split_and_pin`, not `split_argv`: the plain splitter FORWARDS a
    # caller's `--mode` verbatim, so it would arrive after the pinned pair and
    # argparse's last-wins would hand the caller whichever audit they named.
    # Measured: `--mode drc` produced `eda_report_audit:drc` under a wrapper
    # whose whole job is to pin power.
    proj, passthrough, rejected = split_and_pin(caller_argv, mode="power")
    if rejected is not None:
        print(f"REFUSED: this wrapper pins `--mode power`; the caller asked "
              f"for `{rejected}`. A sign-off auditor whose domain a caller "
              f"can change by flag spelling is a false-certificate vector. "
              f"NOTHING was certified.", file=sys.stderr)
        return RC_FAIL
    try:
        rc = main([proj, "--mode", "power", *passthrough])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else RC_FAIL
        if code == 0:
            # `--help` and friends: argparse exited cleanly having audited
            # NOTHING. Exiting 0 here spends a sign-off credit for it.
            print("REFUSED: this invocation printed usage/help and audited "
                  "nothing; it must not spend a sign-off credit.",
                  file=sys.stderr)
        else:
            print(f"REFUSED: the audit did not run (argument error, exit "
                  f"{code}). NOTHING was certified.", file=sys.stderr)
        return RC_FAIL
    return RC_FAIL if rc not in (0, 1) else rc


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
