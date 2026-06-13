#!/usr/bin/env python3
"""tools/core_agent/poll_open_issues.py — backwards-compat shim.

The canonical implementation has moved to:

    vibe-ic-marketplace/plugins/vibe-ic/skills/core-agent-loop/programs/poll.py

so the core-agent loop is packaged as a proper Claude Code skill
(see `vibe-ic:core-agent-loop` SKILL.md). This shim re-exports the
new program so legacy cron prompts that hard-code the old path
keep working — they should be migrated to invoke the skill's
canonical program path instead:

    python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py

CLI passthrough: all arguments forwarded unchanged.
Exit codes: identical (0 / 1 / 2).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_CANONICAL = (
    _REPO_ROOT
    / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    / "skills" / "core-agent-loop" / "programs" / "poll.py"
)


def _load_canonical():
    if not _CANONICAL.is_file():
        print(
            f"ERROR: canonical poll program not found at "
            f"{_CANONICAL}\n"
            f"Did the plugin checkout move? See "
            f"plugins/vibe-ic/skills/core-agent-loop/SKILL.md.",
            file=sys.stderr,
        )
        sys.exit(2)
    spec = importlib.util.spec_from_file_location(
        "core_agent_loop_poll", str(_CANONICAL))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    mod = _load_canonical()
    return mod.main(argv)


if __name__ == "__main__":
    sys.exit(main())
