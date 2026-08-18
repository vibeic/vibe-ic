#!/usr/bin/env python3
"""Qbank coverage matrix + fallback verification (v0.74 E+F-implement).

Prints the class × layer coverage matrix and exits non-zero if any
(class, layer) combination has no reachable qbank via the K1 template
`parent:` fallback chain. Fallback rule:

    Look up qbank <class>_<layer>.yaml.
    Not found? Walk the K1 template's `parent:` chain (class.yaml `parent:`
    field → parent class) and re-try. Repeat until any-ic. If any-ic's
    layer also has no qbank, it's a dead end → exit 1.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml


LAYERS = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L8R",
          "L9", "L10", "L11", "L12", "L13"]


def _parent_of(cls: str, templates_dir: Path) -> Optional[str]:
    f = templates_dir / f"{cls}.yaml"
    if not f.exists():
        return None
    data = yaml.safe_load(f.read_text()) or {}
    return data.get("parent")


def _qbank_exists(cls: str, layer: str, qbank_dir: Path) -> bool:
    return (qbank_dir / f"{cls}_{layer}.yaml").is_file()


def _fallback_hit(cls: str, layer: str, templates_dir: Path,
                  qbank_dir: Path) -> Optional[str]:
    """Walk parent chain until we find a qbank for this layer.
    Returns the class that owns the hit, or None if dead end.
    """
    cur: Optional[str] = cls
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        if _qbank_exists(cur, layer, qbank_dir):
            return cur
        cur = _parent_of(cur, templates_dir)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--templates",
                    default="vibe-ic-marketplace/plugins/vibe-ic/"
                            "agents/class_kb/templates")
    ap.add_argument("--qbank",
                    default="vibe-ic-marketplace/plugins/vibe-ic/"
                            "agents/qbank")
    ap.add_argument("--fail-on-unreachable", action="store_true",
                    help="exit 1 if any (class, layer) has no fallback hit")
    args = ap.parse_args()

    templates_dir = Path(args.templates)
    qbank_dir = Path(args.qbank)
    if not templates_dir.is_dir():
        print(f"error: templates dir not found: {templates_dir}",
              file=sys.stderr)
        return 2
    if not qbank_dir.is_dir():
        print(f"error: qbank dir not found: {qbank_dir}", file=sys.stderr)
        return 2

    classes = sorted(
        p.stem for p in templates_dir.glob("*.yaml") if p.is_file()
    )

    # Print coverage matrix
    col_w = max(len(c) for c in classes) + 1
    print(f"{'class':<{col_w}}", " ".join(f"{L:>4}" for L in LAYERS))
    print("-" * (col_w + 5 * len(LAYERS)))
    direct_hits = 0
    unreachable: List[str] = []
    for c in classes:
        row = f"{c:<{col_w}}"
        for L in LAYERS:
            if _qbank_exists(c, L, qbank_dir):
                row += " ✓  "
                direct_hits += 1
            else:
                owner = _fallback_hit(c, L, templates_dir, qbank_dir)
                if owner:
                    row += "  .   "[:4]  # inherited
                else:
                    row += " ✗  "
                    unreachable.append(f"{c}.{L}")
        print(row)

    total = len(classes) * len(LAYERS)
    print()
    print(f"TOTAL: {total} slots  |  direct qbanks: {direct_hits}  |  "
          f"unreachable: {len(unreachable)}")

    if unreachable:
        print()
        print("UNREACHABLE (class, layer) combos — no qbank anywhere in "
              "fallback chain:")
        for slot in unreachable:
            print(f"  ✗ {slot}")

    if args.fail_on_unreachable and unreachable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
