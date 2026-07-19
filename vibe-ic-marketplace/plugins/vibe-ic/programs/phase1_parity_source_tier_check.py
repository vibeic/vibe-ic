#!/usr/bin/env python3
"""
phase1_parity_source_tier_check.py — Keep the Phase-1 parity source-tier record honest.

A Phase-1 protocol-parity sweep publishes ONE uniform parity number over N
protocols, but the INPUT DOCUMENTS behind those protocols are not uniform. Some
are the real specification from the issuing body; some are an encyclopedia
(Wikipedia) article print; some are a vendor application note, datasheet, IP user
manual, brochure, or slide deck. A parity score measured against an encyclopedia
article or a vendor app note is NOT evidence of parity against the real
specification, so the tier must be recorded as data and surfaced in the published
result.

This checker asserts two things, so the record cannot silently rot:

  (1) COVERAGE — every protocol directory under the parity root has a tier
      assigned in `source_tier.json`, every assigned tier is a known tier, and
      the file's own `counts` block agrees with its `protocols` block. Entries
      for protocols that no longer exist are also flagged.

  (2) PUBLICATION — every RESULT markdown under the parity root that publishes
      tier counts publishes counts that MATCH the data. A markdown is considered
      to publish tier counts when it contains a line of the shape

          - **<tier>** — <N> ...   (or `<tier>: <N>`, `<N> <tier>`)

      inside a section introduced by the marker `<!-- source-tier-counts -->`.
      Markdowns without that marker are ignored (not every RESULT reports tiers).

The checker is chip-AGNOSTIC and deterministic: it reads only the tier JSON and
the markdown, never the input documents themselves. That is deliberate — the
input documents are subject to removal for licensing reasons, and the tier record
must outlive them.

Usage
-----
    phase1_parity_source_tier_check.py <parity_root> [--json OUT]
    phase1_parity_source_tier_check.py <parity_root> --tier-file other.json

Exit codes
----------
    0 = all protocols tiered + published counts match
    1 = at least one violation
    2 = io / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

TIER_FILE_DEFAULT = "source_tier.json"
COUNTS_MARKER = "<!-- source-tier-counts -->"

KNOWN_TIERS = (
    "specification",
    "encyclopedia",
    "vendor_document",
    "reconstructed_text",
    "unknown",
)

# A directory under the parity root is a protocol when it carries either the
# Phase-1 artifacts or the input documents. Helper/scratch dirs have neither.
def _is_protocol_dir(d: Path) -> bool:
    if not d.is_dir() or d.name.startswith((".", "_")):
        return False
    return (d / "input" / "docs").is_dir() or (d / "phase1").is_dir()


def discover_protocols(root: Path) -> List[str]:
    return sorted(d.name for d in root.iterdir() if _is_protocol_dir(d))


# Matches the three shapes a tier count can legitimately take in prose.
def _count_patterns(tier: str) -> List[re.Pattern]:
    t = re.escape(tier)
    return [
        re.compile(rf"\*\*`?{t}`?\*\*[^0-9\n]{{0,40}}?(\d+)"),
        re.compile(rf"`?{t}`?\s*[:=]\s*\*?\*?(\d+)"),
        re.compile(rf"(\d+)\s+\*?\*?`?{t}`?"),
    ]


def published_counts(md_text: str) -> Dict[str, int]:
    """Extract tier counts from the marked section of a RESULT markdown.

    Returns {} when the markdown carries no counts marker.
    """
    idx = md_text.find(COUNTS_MARKER)
    if idx < 0:
        return {}
    section = md_text[idx + len(COUNTS_MARKER):]
    # The marked section ends at the next markdown heading, if any.
    end = re.search(r"\n#{1,6} ", section)
    if end:
        section = section[: end.start()]
    found: Dict[str, int] = {}
    for tier in KNOWN_TIERS:
        for pat in _count_patterns(tier):
            m = pat.search(section)
            if m:
                found[tier] = int(m.group(1))
                break
    return found


def check(root: Path, tier_file: Path) -> dict:
    violations: List[str] = []

    if not tier_file.is_file():
        return {
            "root": str(root),
            "tier_file": str(tier_file),
            "ok": False,
            "violations": [f"tier file missing: {tier_file}"],
            "protocols_total": 0,
            "counts": {},
            "untiered": [],
            "unknown_list": [],
            "result_md_checked": [],
        }

    data = json.loads(tier_file.read_text())
    entries = data.get("protocols", {})

    dirs = discover_protocols(root)
    untiered = [p for p in dirs if p not in entries]
    orphaned = [p for p in entries if p not in dirs]

    for p in untiered:
        violations.append(f"protocol '{p}' has no source-tier entry in {tier_file.name}")
    for p in orphaned:
        violations.append(f"{tier_file.name} tiers '{p}', which is not a protocol directory")

    # Every entry must carry a known tier, and a non-empty evidence string, so
    # that a tier can always be traced back to what substantiated it.
    for name, rec in sorted(entries.items()):
        tier = rec.get("tier")
        if tier not in KNOWN_TIERS:
            violations.append(f"protocol '{name}' has unknown tier value {tier!r}")
        if not str(rec.get("evidence", "")).strip():
            violations.append(f"protocol '{name}' has a tier but no evidence string")

    actual: Dict[str, int] = {t: 0 for t in KNOWN_TIERS}
    for rec in entries.values():
        t = rec.get("tier")
        if t in actual:
            actual[t] += 1

    declared = data.get("counts")
    if declared is not None:
        for tier in KNOWN_TIERS:
            if int(declared.get(tier, 0)) != actual[tier]:
                violations.append(
                    f"{tier_file.name} counts.{tier}={declared.get(tier)} but "
                    f"protocols block has {actual[tier]}"
                )

    declared_total = data.get("protocols_total")
    if declared_total is not None and int(declared_total) != len(entries):
        violations.append(
            f"{tier_file.name} protocols_total={declared_total} but protocols "
            f"block has {len(entries)}"
        )

    # Publication: every RESULT markdown that publishes counts must match.
    checked_md: List[str] = []
    for md in sorted(root.glob("RESULT*.md")):
        pub = published_counts(md.read_text(errors="replace"))
        if not pub:
            continue
        checked_md.append(md.name)
        for tier, n in sorted(pub.items()):
            if n != actual[tier]:
                violations.append(
                    f"{md.name} publishes {tier}={n} but the data says {actual[tier]}"
                )
        missing = [t for t in KNOWN_TIERS if actual[t] and t not in pub]
        for t in missing:
            violations.append(
                f"{md.name} publishes tier counts but omits '{t}' ({actual[t]} protocols)"
            )

    return {
        "root": str(root),
        "tier_file": str(tier_file),
        "ok": not violations,
        "violations": violations,
        "protocols_total": len(entries),
        "counts": actual,
        "untiered": untiered,
        "orphaned": orphaned,
        "unknown_list": sorted(n for n, r in entries.items() if r.get("tier") == "unknown"),
        "result_md_checked": checked_md,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else None)
    ap.add_argument("parity_root", help="directory holding the per-protocol parity dirs")
    ap.add_argument("--tier-file", default=None,
                    help=f"tier JSON (default: <parity_root>/{TIER_FILE_DEFAULT})")
    ap.add_argument("--json", dest="json_out", default=None, help="write the report as JSON")
    args = ap.parse_args(argv)

    root = Path(args.parity_root)
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2
    tier_file = Path(args.tier_file) if args.tier_file else root / TIER_FILE_DEFAULT

    try:
        report = check(root, tier_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")

    print(f"protocols: {report['protocols_total']}")
    for tier in KNOWN_TIERS:
        print(f"  {tier:<20} {report['counts'].get(tier, 0)}")
    if report["unknown_list"]:
        print(f"  unknown protocols: {', '.join(report['unknown_list'])}")
    if report["result_md_checked"]:
        print(f"RESULT md checked: {', '.join(report['result_md_checked'])}")
    else:
        print("RESULT md checked: none (no markdown carries the counts marker)")

    if report["ok"]:
        print("PASS — every protocol is tiered and published counts match the data")
        return 0
    print(f"FAIL — {len(report['violations'])} violation(s):")
    for v in report["violations"]:
        print(f"  - {v}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
