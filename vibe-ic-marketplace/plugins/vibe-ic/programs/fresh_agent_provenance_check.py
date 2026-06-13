#!/usr/bin/env python3
"""fresh_agent_provenance_check.py — honesty check for "fresh-agent" claims.

When a project claims a Verilog file was "fresh-agent-generated" from spec,
it is often actually copied verbatim from a plugin-shipped reference template.
Both are valid outcomes, but they carry different meanings:
  - "regenerated from spec" = plugin guided the agent to synthesize logic
  - "copied from reference"  = plugin provided a pre-vetted template

Confusing these inflates plugin capability claims and hides regressions.

This program computes a SHA-256 over each RTL file and compares against every
reference file under the plugin's `references/` directory. For each match it
emits a provenance record: `copied-from-reference` (exact match) or
`modified-from-reference` (≥80% line overlap).

Usage:
    python3 fresh_agent_provenance_check.py <rtl_dir> <plugin_references_dir>

Exit: 0 (always). The goal is informational labeling, not a pass/fail gate.

Learned from <chip-class> v041-v044: v044 fresh-agent "PASS" was achieved by copying
17 reference files verbatim. That's legitimate but should be reported as
"reference-reuse PASS", NOT "spec-generation PASS". This program makes the
distinction explicit and un-game-able.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class Record:
    rtl_file: str
    provenance: str              # "copied-from-reference" | "modified-from-reference" | "spec-generated"
    reference_file: str = ""
    line_overlap_pct: float = 0.0


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def line_overlap(a: Path, b: Path) -> float:
    try:
        la = set(l.strip() for l in a.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip())
        lb = set(l.strip() for l in b.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip())
    except Exception:
        return 0.0
    if not la or not lb:
        return 0.0
    inter = la & lb
    return 100.0 * len(inter) / max(len(la), len(lb))


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rtl_dir", help="Directory with generated RTL (.v files)")
    ap.add_argument("reference_dir", help="Plugin references/ directory")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    ref_dir = Path(args.reference_dir)

    if not rtl_dir.is_dir():
        print(f"ERROR: rtl dir not found: {rtl_dir}", file=sys.stderr)
        return 2
    if not ref_dir.is_dir():
        print(f"ERROR: reference dir not found: {ref_dir}", file=sys.stderr)
        return 2

    # Index references
    ref_files: List[Path] = [f for f in ref_dir.rglob("*.v")]
    ref_hashes: Dict[str, Path] = {sha256_file(f): f for f in ref_files}

    rtl_files: List[Path] = sorted([f for f in rtl_dir.rglob("*.v")])

    records: List[Record] = []
    for r in rtl_files:
        h = sha256_file(r)
        if h in ref_hashes:
            records.append(Record(
                rtl_file=str(r),
                provenance="copied-from-reference",
                reference_file=str(ref_hashes[h]),
                line_overlap_pct=100.0,
            ))
            continue
        # Check partial overlap
        best_ref: Path = Path("")
        best_overlap = 0.0
        for ref in ref_files:
            o = line_overlap(r, ref)
            if o > best_overlap:
                best_overlap = o
                best_ref = ref
        if best_overlap >= 80.0:
            records.append(Record(
                rtl_file=str(r),
                provenance="modified-from-reference",
                reference_file=str(best_ref),
                line_overlap_pct=round(best_overlap, 1),
            ))
        else:
            records.append(Record(
                rtl_file=str(r),
                provenance="spec-generated",
                reference_file="",
                line_overlap_pct=round(best_overlap, 1),
            ))

    if args.json:
        print(json.dumps({"records": [asdict(r) for r in records]}, indent=2))
    else:
        counts = {"copied": 0, "modified": 0, "spec": 0}
        for r in records:
            if r.provenance == "copied-from-reference":
                counts["copied"] += 1
                tag = "COPIED"
            elif r.provenance == "modified-from-reference":
                counts["modified"] += 1
                tag = f"MODIFIED ({r.line_overlap_pct}%)"
            else:
                counts["spec"] += 1
                tag = "SPEC-GENERATED"
            print(f"  [{tag}] {Path(r.rtl_file).name}"
                  + (f"  <-- {Path(r.reference_file).name}" if r.reference_file else ""))

        total = len(records)
        print(f"\nProvenance summary for {total} files:")
        print(f"  {counts['copied']} copied-from-reference (verbatim)")
        print(f"  {counts['modified']} modified-from-reference (≥80%)")
        print(f"  {counts['spec']} spec-generated (no significant reference overlap)")

        if counts["copied"] == total and total > 0:
            print("\nHonest claim: 'plugin-reference-reuse PASS' — agent copied")
            print("  from plugin's references/. NOT a from-scratch spec-generation PASS.")
        elif counts["spec"] == total and total > 0:
            print("\nHonest claim: 'spec-generation PASS' — agent produced RTL")
            print("  without leaning on any plugin reference.")
        else:
            print("\nHonest claim: 'hybrid PASS' — agent copied some references,")
            print("  generated others. Document which in your report.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
