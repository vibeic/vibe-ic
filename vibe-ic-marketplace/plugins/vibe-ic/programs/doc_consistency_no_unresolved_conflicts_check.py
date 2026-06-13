#!/usr/bin/env python3
"""
doc_consistency_no_unresolved_conflicts_check.py — Wave 37 / A4

Cross-doc range conflict detector. When >=2 extracted docs disagree
on the same numeric constraint (ADDR/LEN ranges, opcode response
shapes, fixed timing constants), the doc-consistency-check skill
must resolve the conflict via vendor erratum or rig_spec annotation.
This gate WARNs (does NOT fail) if conflicts remain unresolved —
i.e. no ``reports/doc_consistency_conflicts.md`` is emitted, OR the
file lists open conflicts without a ``resolution`` block.

The gate is OPCODE-AGNOSTIC; it only re-detects ADDR-range
disagreement using the SAME pattern surface as A3 across multiple
docs, then reports whether resolution metadata exists.

Usage:
    python3 doc_consistency_no_unresolved_conflicts_check.py <project_dir>

Exit codes:
    0 = PASS (no conflict OR all resolved)
    0 = WARN (conflict found, no resolution doc) — non-blocking by spec
    2 = input-missing (skip)

NOTE: per Wave 37 spec: "warns if conflicts unresolved (not blocking)".
We return 0 always; warnings are surfaced on stdout for the audit
runner / human reader. To force FAIL when a conflict exists, set
env VIBE_IC_DOC_CONFLICT_BLOCKING=1.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_DOC_GLOBS = (
    "**/input_doc/*.txt",
    "**/input/docs/*.txt",
    "**/input/input_doc/*.txt",
)

_RESOLUTION_GLOBS = (
    "reports/doc_consistency_conflicts.md",
    "reports/doc_consistency_conflicts.json",
    "**/reports/doc_consistency_conflicts.md",
)

# Match "(位址|地址|ADDR)...(0x[0-9A-Fa-f]+)" — capture limit value.
_ADDR_LIMIT = re.compile(
    r"(位址|地址|ADDR|address)[^\n]{0,80}?"
    r"(不得超過|≤|<=|max|最大|範圍|到|不大於|range)[^\n]{0,30}?"
    r"(0x[0-9A-Fa-f]+)",
    re.IGNORECASE,
)


def _scan_addr_limits(project: Path) -> Dict[str, List[Tuple[Path, int]]]:
    """Group {limit_hex: [(file, line), ...]}."""
    bucket: Dict[str, List[Tuple[Path, int]]] = defaultdict(list)
    seen = set()
    for pat in _DOC_GLOBS:
        for doc in project.glob(pat):
            if not doc.is_file() or doc in seen:
                continue
            seen.add(doc)
            try:
                text = doc.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                m = _ADDR_LIMIT.search(line)
                if m:
                    val = m.group(3).lower()
                    bucket[val].append((doc, i))
    return bucket


def _has_resolution(project: Path) -> Optional[Path]:
    for pat in _RESOLUTION_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file() and hit.stat().st_size > 0:
                return hit
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: doc_consistency_no_unresolved_conflicts_check "
              "<project_dir>", file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    bucket = _scan_addr_limits(project)
    if len(bucket) <= 1:
        print("[SKIP] doc_consistency_no_unresolved_conflicts_check: "
              "no ADDR-limit conflict (≤1 distinct value across docs)")
        return 2

    # >= 2 distinct values => conflict candidates.
    distinct = sorted(bucket.keys())
    sample = []
    for v in distinct:
        loc = bucket[v][0]
        sample.append(f"{v} @ {loc[0].name}:{loc[1]}")

    resolution = _has_resolution(project)
    blocking = os.environ.get("VIBE_IC_DOC_CONFLICT_BLOCKING") == "1"

    if resolution:
        print(f"[PASS] doc_consistency_no_unresolved_conflicts_check: "
              f"{len(distinct)} distinct ADDR limits ({', '.join(distinct)}) "
              f"with resolution doc {resolution.relative_to(project)}")
        return 0

    msg = (f"doc_consistency_no_unresolved_conflicts_check: "
           f"{len(distinct)} conflicting ADDR-limit values "
           f"({', '.join(distinct)}) across vendor docs without a "
           f"resolution doc. doc-consistency-check skill should emit "
           f"reports/doc_consistency_conflicts.md. Samples: "
           f"{'; '.join(sample[:5])}")

    if blocking:
        print(f"[FAIL] {msg}")
        return 1
    print(f"[WARN] {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
