#!/usr/bin/env python3
"""Tapeout signoff check — wrapper for signoff_audit --mode tapeout.

Forwards all passthrough arguments (--json, --lenient, --strict, etc.) to
the underlying signoff_audit entry point. Prior versions hardcoded only
the project_dir + --mode and silently dropped --json PATH, preventing
reports/tapeout_checklist.json from being written when called via the
33-step flow gate. Fix recorded 2026-04-22 via <benchmark> full-flow pilot."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signoff_audit import main  # noqa: E402

if __name__ == "__main__":
    user_args = sys.argv[1:]
    if not user_args:
        user_args = ["."]
    # Inject --mode tapeout if the user hasn't explicitly overridden it
    if "--mode" not in user_args:
        user_args = user_args + ["--mode", "tapeout"]
    sys.exit(main(user_args))
