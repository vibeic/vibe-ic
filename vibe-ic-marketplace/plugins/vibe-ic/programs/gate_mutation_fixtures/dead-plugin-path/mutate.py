#!/usr/bin/env python3
"""Reintroduce the retired second-plugin path into shipped doctrine.

The retired token is assembled at runtime, never written whole: the gate under
test scans the shipped bundle for it, so a literal in a tracked fixture is a
finding against the real tree. `dead_plugin_path_check` builds its own needle
the same way, for the same reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

_RETIRED = "vibe-ic-" + "d"


def main() -> int:
    tree = Path(sys.argv[1])
    target = tree / "skills" / "example" / "SKILL.md"
    text = target.read_text(encoding="utf-8")
    marker = "There is one plugin tree, so there is no edition to branch on.\n"
    if marker not in text:
        print(f"can_pass no longer contains {marker!r}", file=sys.stderr)
        return 1
    revived = (f"If you have the deterministic edition installed, run "
               f"`plugins/{_RETIRED}/programs/example_check.py` instead.\n")
    target.write_text(text.replace(marker, revived, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
