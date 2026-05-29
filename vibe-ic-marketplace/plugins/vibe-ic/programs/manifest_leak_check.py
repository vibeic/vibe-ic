#!/usr/bin/env python3
"""
manifest_leak_check.py — Detect benchmark-value leaks in fact manifests.

A fact manifest (lessons/manifests/L<N>_manifest.json) MAY cite a
benchmark-value as a reference, but the `ic_expert_default` field MUST
NOT reproduce that benchmark value verbatim for non-generic fields.
Doing so turns the plugin into an answer-key for the benchmark IC:

    fact.benchmark_value == fact.ic_expert_default  (non-trivial string)
    ⇒ an agent with no user input still fills in the correct benchmark
      answer and "passes" Phase-1 regression without actually soliciting
      from the user.

This is the manifest-level analogue of
`plugins/vibe-ic/skills/spec-to-rtl/references/aid/` — the
verbatim RTL bundle removed in v0.47.6.

Rules applied
-------------
A fact is considered LEAKY when ALL of:

  (a) benchmark_value and ic_expert_default are both strings
  (b) their values are equal
  (c) length >= 5 (excludes "V", "1", "OK"-style generic tokens)
  (d) path is NOT in SAFE_GENERIC_FIELDS (document_id, layer,
      schema_version, etc. — these are fixed by format, not by IC)

Usage
-----
    manifest_leak_check.py <manifests_dir>
    manifest_leak_check.py <file1.json> [<file2.json> ...]

Exit codes
----------
    0 = no leaks
    1 = at least one leaky fact found
    2 = io / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List


# Fields where a fixed default is legitimate (schema-level, not IC-level).
SAFE_GENERIC_FIELDS = {
    "document_id", "layer", "schema_version", "generated_by",
    "metadata.extraction_method", "version",
}

MIN_LENGTH = 5  # values shorter than this are considered too generic to be a leak


@dataclass
class LeakFinding:
    manifest: str
    path: str
    benchmark_value: str
    ic_expert_default: str


def inspect_file(path: Path) -> List[LeakFinding]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        print(f"manifest_leak_check: cannot parse {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)

    findings: List[LeakFinding] = []
    facts = data.get("facts", [])
    if not isinstance(facts, list):
        return findings

    for f in facts:
        if not isinstance(f, dict):
            continue
        fpath = f.get("path", "")
        bv = f.get("benchmark_value")
        dv = f.get("ic_expert_default")
        if fpath in SAFE_GENERIC_FIELDS:
            continue
        if not isinstance(bv, str) or not isinstance(dv, str):
            continue
        if bv != dv:
            continue
        if len(dv) < MIN_LENGTH:
            continue
        findings.append(LeakFinding(
            manifest=str(path),
            path=fpath,
            benchmark_value=bv[:80],
            ic_expert_default=dv[:80],
        ))
    return findings


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("targets", nargs="+",
                   help="Manifest file(s) or a directory containing L*_manifest.json")
    p.add_argument("--json", help="Write JSON report to this path")
    args = p.parse_args(argv)

    files: List[Path] = []
    for t in args.targets:
        tp = Path(t)
        if tp.is_dir():
            files.extend(sorted(tp.rglob("L*_manifest.json")))
        elif tp.is_file():
            files.append(tp)
        else:
            print(f"manifest_leak_check: not found: {t}", file=sys.stderr)
            return 2

    if not files:
        print("manifest_leak_check: no manifest files found")
        return 0

    all_findings: List[LeakFinding] = []
    for f in files:
        all_findings.extend(inspect_file(f))

    print(f"\n=== manifest_leak_check ===")
    print(f"  manifests checked: {len(files)}")
    print(f"  leaky facts:       {len(all_findings)}")

    for f in all_findings[:30]:
        mn = Path(f.manifest).name
        print(f"  ✗ {mn}:{f.path}  default={f.ic_expert_default[:60]}")
    if len(all_findings) > 30:
        print(f"  ... ({len(all_findings) - 30} more)")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(
            {"files": [str(f) for f in files],
             "leaky_count": len(all_findings),
             "findings": [asdict(f) for f in all_findings]},
            indent=2))

    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
