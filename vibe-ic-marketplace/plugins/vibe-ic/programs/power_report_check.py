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
_VALUE_FLAGS = ("--mode", "--json")


def split_argv(rest):
    """Split argv into (project_dir, passthrough_flags).

    The project dir is the first bare token that is not the ARGUMENT of a
    preceding value-taking option; every other token is forwarded verbatim.

    A caller-supplied ``--mode`` is dropped in BOTH spellings — ``--mode lvs``
    and ``--mode=lvs`` — so power mode is genuinely pinned. Only the
    space-separated spelling used to be dropped: ``--mode=lvs`` starts with
    "-", so it was forwarded and, arriving after the pinned pair, argparse's
    last-wins gave `eda_report_audit:lvs`. Measured: `power_report_check.py
    <proj> --mode=lvs` audited LVS.

    And ``--json out.json <proj>`` used to resolve the project dir to
    `out.json` (first bare token) while `--json` took `<proj>` as its value —
    the run then died with IsADirectoryError before writing any audit.
    """
    proj = "."
    proj_seen = False
    passthrough: list = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--mode":          # drop caller's --mode AND its value
            i += 2
            continue
        if tok.startswith("--mode="):   # ... and its `=` spelling
            i += 1
            continue
        if tok.startswith("-"):
            passthrough.append(tok)
            if tok in _VALUE_FLAGS and i + 1 < len(rest):
                # the next token is this option's ARGUMENT, not the project dir
                passthrough.append(rest[i + 1])
                i += 2
                continue
            i += 1
            continue
        if not proj_seen:
            proj = tok               # first bare token = project dir
            proj_seen = True
        else:
            passthrough.append(tok)
        i += 1
    return proj, passthrough


if __name__ == "__main__":
    _proj, _passthrough = split_argv(sys.argv[1:])
    sys.exit(main([_proj, "--mode", "power", *_passthrough]))
