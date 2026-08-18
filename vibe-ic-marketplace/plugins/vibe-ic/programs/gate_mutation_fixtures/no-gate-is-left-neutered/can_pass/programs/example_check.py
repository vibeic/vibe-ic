#!/usr/bin/env python3
"""A gate-shaped program whose entry point really does look at something."""
from __future__ import annotations

import sys


def main() -> int:
    """Return 1 when the subject is empty, so this entry point can fail."""
    return 0 if sys.argv[1:] else 1


if __name__ == "__main__":
    raise SystemExit(main())
