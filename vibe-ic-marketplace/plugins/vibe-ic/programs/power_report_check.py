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


if __name__ == "__main__":
    # `split_and_pin`, not `split_argv`: the plain splitter FORWARDS a
    # caller's `--mode` verbatim, so it would arrive after the pinned pair and
    # argparse's last-wins would hand the caller whichever audit they named.
    # Measured while making this change: `--mode drc` produced
    # `eda_report_audit:drc` under a wrapper whose whole job is to pin power.
    _proj, _passthrough, _rejected = split_and_pin(sys.argv[1:], mode="power")
    if _rejected is not None:
        print(f"REFUSED: this wrapper pins `--mode power`; the caller asked "
              f"for `{_rejected}`. A sign-off auditor whose domain a caller "
              f"can change by flag spelling is a false-certificate vector. "
              f"NOTHING was certified.", file=sys.stderr)
        sys.exit(1)
    sys.exit(main([_proj, "--mode", "power", *_passthrough]))
