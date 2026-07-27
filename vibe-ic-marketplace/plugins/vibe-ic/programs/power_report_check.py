#!/usr/bin/env python3
"""Power report check — wrapper for eda_report_audit --mode power.

Forwards every extra CLI arg through to eda_report_audit (so ``--json <path>``
etc. work), while defaulting the project dir to ``.`` and always pinning
``--mode power``.

Before this the wrapper rebuilt argv as
``[argv[1] or ".", "--mode", "power"]`` and dropped everything else, so the
``--json`` the flow yaml declared for Step 33 was silently discarded and the
checker's audit trail was never written to disk — only printed. Same shape, and
same fix, as lvs_report_check (#507).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from eda_report_audit import main


def split_argv(rest):
    """Split argv into (project_dir, passthrough_flags).

    The first bare (non-flag) token is the project dir; every other token is
    forwarded. A caller-supplied ``--mode`` (and its value) is dropped — this
    wrapper always pins power mode.
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
        if tok.startswith("-"):
            passthrough.append(tok)
        elif not proj_seen:
            proj = tok               # first bare token = project dir
            proj_seen = True
        else:
            passthrough.append(tok)
        i += 1
    return proj, passthrough


if __name__ == "__main__":
    _proj, _passthrough = split_argv(sys.argv[1:])
    sys.exit(main([_proj, "--mode", "power", *_passthrough]))
