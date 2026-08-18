#!/usr/bin/env python3
"""Plant one real NDA token in shipped source.

THE TOKEN IS NEVER WRITTEN DOWN. It is decoded at runtime from
`_commercial_pdk`'s encoded store — the same mechanism the guard's own
regression tests use, and for the same reason: a literal in a tracked file is
precisely what this gate exists to forbid, so a stored fixture would make the
guard red over its own evidence.

That is not a workaround. It is the measurement that decided this registry's
shape: a mutated tree cannot be committed for any gate whose subject is a
pattern in source, and the NDA panel is the extreme case where it cannot be
committed at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROGRAMS))

import _commercial_pdk as _cpdk  # noqa: E402


def main() -> int:
    tree = Path(sys.argv[1])
    tokens = _cpdk.nda_tokens()
    if not tokens:
        print("no NDA token available to plant — the encoded store is empty, "
              "so this fixture cannot prove the guard discriminates",
              file=sys.stderr)
        return 1
    token = sorted(tokens, key=len, reverse=True)[0]
    target = tree / "programs" / "example_pdk_read.py"
    text = target.read_text(encoding="utf-8")
    marker = '    return os.environ.get("PDK", "open-pdk")\n'
    if marker not in text:
        print(f"can_pass no longer contains {marker!r}", file=sys.stderr)
        return 1
    target.write_text(text.replace(marker, f'    return "{token}"\n', 1),
                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
