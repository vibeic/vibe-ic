#!/usr/bin/env python3
"""LVS report check — wrapper for eda_report_audit --mode lvs.

Forwards every extra CLI arg through to eda_report_audit (so
``--json <path>`` etc. work, #507), while defaulting the project dir to
``.`` and always pinning ``--mode lvs``."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main
if __name__ == "__main__":
    # Split argv into the project-dir positional (first non-flag token,
    # default ".") and the pass-through flags (everything else). `--mode`
    # is pinned to lvs and never taken from the caller.
    rest = sys.argv[1:]
    proj = "."
    proj_seen = False
    passthrough: list = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--mode":          # drop caller's --mode AND its value
            i += 2
            continue
        if tok.startswith("-"):
            passthrough.append(tok)
        elif not proj_seen:
            proj = tok               # first bare token = project dir
            proj_seen = True
        else:
            passthrough.append(tok)
        i += 1
    sys.exit(main([proj, "--mode", "lvs", *passthrough]))
