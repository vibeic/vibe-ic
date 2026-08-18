#!/usr/bin/env python3
"""A CLI whose help strings survive argparse's percent expansion."""
from __future__ import annotations

import argparse


def main() -> int:
    ap = argparse.ArgumentParser(description="Example.")
    ap.add_argument("--margin", help="headroom, in percent (default: %(default)s)",
                    default="5")
    ap.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
