#!/usr/bin/env python3
"""Neuter the fixture's gate: make its entry point return success at once.

The injected line is BUILT here rather than written as a literal, for the same
reason it is never stored in a tracked tree: `neutered_gate_tree_check` matches
it as a WHOLE line, so a literal anywhere under the plugin — in a fixture, in
prose that happened to wrap — becomes a finding against the real tree.
"""
from __future__ import annotations

import sys
from pathlib import Path

_INJECTED = "    return 0" + "  # " + "NEUTER" + "ED"


def main() -> int:
    tree = Path(sys.argv[1])
    target = tree / "programs" / "example_check.py"
    text = target.read_text(encoding="utf-8")
    marker = "def main() -> int:\n"
    if marker not in text:
        print(f"can_pass no longer contains {marker!r}", file=sys.stderr)
        return 1
    target.write_text(text.replace(marker, marker + _INJECTED + "\n", 1),
                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
