#!/usr/bin/env python3
"""Bake one developer's home directory into a shipped default.

The offending path is assembled at runtime: this gate scans shipped source for
exactly this shape, so a literal in a tracked fixture is a finding against the
real tree.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    tree = Path(sys.argv[1])
    target = tree / "programs" / "example_runner.py"
    text = target.read_text(encoding="utf-8")
    good = '    env = os.environ.get("VIBEIC_DESIGNS_ROOT")\n' \
           '    return Path(env) if env else Path.home() / "vibeic-designs"\n'
    baked = "/" + "home" + "/" + "dlaurent" + "/vibeic-designs"
    bad = f'    return Path("{baked}")\n'
    if good not in text:
        print("can_pass no longer contains the resolved default",
              file=sys.stderr)
        return 1
    target.write_text(text.replace(good, bad, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
