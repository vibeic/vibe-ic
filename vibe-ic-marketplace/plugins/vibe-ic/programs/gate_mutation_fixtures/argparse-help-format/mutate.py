#!/usr/bin/env python3
"""Make one help string carry a bare percent sign.

argparse percent-expands every help string, so a bare `%` raises
`ValueError: incomplete format` the moment anyone types `--help`. The bad
string is assembled here rather than committed: a literal in a tracked file
is a finding for this very gate over the real tree.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    tree = Path(sys.argv[1])
    target = tree / "programs" / "example_cli.py"
    text = target.read_text(encoding="utf-8")
    good = 'help="headroom, in percent (default: %(default)s)"'
    bad = 'help="headroom, in ' + "%" + ' of the budget"'
    if good not in text:
        print(f"can_pass no longer contains {good!r}", file=sys.stderr)
        return 1
    target.write_text(text.replace(good, bad, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
