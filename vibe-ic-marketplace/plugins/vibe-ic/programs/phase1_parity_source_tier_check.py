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

This checker asserts three things, so the record cannot silently rot:

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

  (3) CITATION FOLLOWABILITY (vibe-ic#456) — the L-docs cite their input document
      by PATH (`"evidence": "input/docs/<doc>"`). When the document is withheld,
      that pointer resolves to nothing and the reader is told nothing. This
      dimension classifies every such pointer and requires that an unfollowable
      one be EXPLAINED by the tier record rather than left dangling. See
      `classify_citation` for the decisions and why the distinction matters.

The checker is chip-AGNOSTIC and deterministic. Dimensions (1) and (2) read only
the tier JSON and the markdown, never the input documents themselves. That is
deliberate — the input documents are subject to removal for licensing reasons,
and the tier record must outlive them. Dimension (3) asks only whether a cited
path EXISTS; it never opens the document either.

Usage
-----
    phase1_parity_source_tier_check.py <parity_root> [--json OUT]
    phase1_parity_source_tier_check.py <parity_root> --tier-file other.json
    phase1_parity_source_tier_check.py <parity_root> --emit-routing

Exit codes
----------
    0 = all protocols tiered + published counts match + no dangling citation
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


# ---------------------------------------------------------------------------
# (3) CITATION FOLLOWABILITY  (vibe-ic#456)
# ---------------------------------------------------------------------------
ROUTING_FILENAME = "INPUT_DOC_CITATION_ROUTING.txt"

ROUTING_HEADER = (
    "# INPUT_DOC_CITATION_ROUTING — every INPUT DOCUMENT the published L-docs\n"
    "# cite as their evidence, and whether a reader of this tree can follow it\n"
    "# (vibe-ic#456). Generated by phase1_parity_source_tier_check.py.\n"
    "#\n"
    "#   <protocol> :: <cited path> <DECISION> <detail>\n"
    "#\n"
    "# WITHHELD_ON_RECORD is the one that needed a name. An L-doc cites the\n"
    "# document it was extracted FROM; the extractor held that document, so the\n"
    "# pointer was true when written. Publication is where it goes stale: the\n"
    "# input documents are subject to removal for licensing reasons (the reason\n"
    "# source_tier.json exists and carries a durability_note saying so). The\n"
    "# pointer was then published unchanged, so a reader following it finds\n"
    "# nothing and is told nothing.\n"
    "#\n"
    "# This does NOT say the value is unverifiable. source_tier.json names the\n"
    "# document, its tier, and the title/page-count that identifies it, so a\n"
    "# reader can obtain the document themselves. Unfollowable HERE, obtainable\n"
    "# THERE — which is a different fact from a pointer nobody can resolve at\n"
    "# all, and the whole reason the two get separate names.\n"
    "#\n"
    "# ABSENT_* are the states that are somebody's bug: a cited document that\n"
    "# the record does not account for. If a document was ever DROPPED rather\n"
    "# than withheld, it lands there and stays loud — which is what keeps this\n"
    "# repair from freezing a fixable gap as 'inherently unfollowable'.\n"
    "#\n"
    "# Emitted even when every citation resolves: a record that only appears on\n"
    "# failure cannot be used to prove there were none.\n")

# A string is a citation only when it is ENTIRELY a relative path under the
# protocol's own input tree. Substring matching would sweep in prose that merely
# mentions a filename, and logs that record WHERE a run read something — the
# false-positive class #448 measured (914 text matches vs 108 real citations).
CITED_INPUT_RE = re.compile(r"input/[\w./ -]+\.[A-Za-z0-9]{1,5}")

# Keys whose value something is expected to FOLLOW. Same discipline as #448:
# key-based, not text-based. Any key CONTAINING 'evidence' also qualifies, which
# is what admits versioned and qualified variants (`primary_evidence_v*`,
# `*_measurement_evidence`) without naming them.
CITE_KEYS = frozenset({"source", "file", "source_documents", "document",
                       "input_document", "input_documents", "citation"})

_MAX_JSON_BYTES = 8 * 1024 * 1024


def _is_cite_key(key) -> bool:
    if not isinstance(key, str):
        return False
    return key in CITE_KEYS or "evidence" in key


def _cited_paths(obj, key=None):
    """Yield every fully-qualified input-tree path sitting under a citation key."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _cited_paths(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _cited_paths(v, key)
    elif isinstance(obj, str) and _is_cite_key(key):
        s = obj.strip()
        # fullmatch, not match/search: the value must BE the path. `match` alone
        # would accept "input/docs/Spec.pdf, section 4" and mine a citation out
        # of a sentence.
        if CITED_INPUT_RE.fullmatch(s):
            yield s


def collect_input_doc_citations(protocol_dir: Path) -> Dict[str, List[str]]:
    """{cited path -> sorted docs citing it} for one protocol directory.

    Keyed by the cited PATH, not by mention: a document cited in 10 L-docs is
    one thing a reader can or cannot follow, not ten.
    """
    found: Dict[str, set] = {}
    for j in sorted(protocol_dir.rglob("*.json")):
        try:
            if j.stat().st_size > _MAX_JSON_BYTES:
                continue
            data = json.loads(j.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        for cited in _cited_paths(data):
            found.setdefault(cited, set()).add(j.relative_to(protocol_dir).as_posix())
    return {k: sorted(v) for k, v in sorted(found.items())}


def classify_citation(protocol_dir: Path, cited: str, entry: dict | None) -> str:
    """How a reader of THIS tree fares following `cited`.

    RESOLVES              the document is here.
    WITHHELD_ON_RECORD    not here, and the tier record names this document and
                          identifies it well enough to be obtained elsewhere.
    ABSENT_UNRECORDED     not here, and the record for this protocol does not
                          name it. Nobody can tell what the pointer meant.
    ABSENT_NO_RECORD      not here, and the protocol has no record at all.
    ABSENT_UNIDENTIFIABLE not here, named, but nothing identifies WHICH document
                          it was — so it cannot be obtained, only guessed at.

    Only the ABSENT_* states are defects. Blessing an absence merely because it
    is absent would be the error the issue warns about: it would label a dropped
    file 'inherently unfollowable' and freeze a fixable gap.
    """
    if (protocol_dir / cited).exists():
        return "RESOLVES"
    if not entry:
        return "ABSENT_NO_RECORD"
    declared = {str(d).strip() for d in (entry.get("input_documents") or [])}
    if cited.rsplit("/", 1)[-1] not in declared:
        return "ABSENT_UNRECORDED"
    if not str(entry.get("evidence", "")).strip():
        return "ABSENT_UNIDENTIFIABLE"
    return "WITHHELD_ON_RECORD"


def citation_records(root: Path, entries: Dict[str, dict]) -> List[Dict[str, str]]:
    """One record per (protocol, cited document) over the whole parity root."""
    out: List[Dict[str, str]] = []
    for name in discover_protocols(root):
        d = root / name
        entry = entries.get(name)
        for cited, docs in collect_input_doc_citations(d).items():
            out.append({
                "protocol": name,
                "cited": cited,
                "decision": classify_citation(d, cited, entry),
                "tier": (entry or {}).get("tier", "-"),
                "cited_in": len(docs),
            })
    return out


def render_citation_routing(records: List[Dict[str, str]]) -> str:
    body = "".join(
        f"{r['protocol']} :: {r['cited']} {r['decision']} "
        f"tier={r['tier']} cited_in={r['cited_in']}\n"
        for r in sorted(records, key=lambda r: (r["protocol"], r["cited"])))
    return ROUTING_HEADER + body


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

    # (3) Citation followability. An unfollowable pointer is only acceptable
    # when the record accounts for the document; a dangling one is a defect.
    cites = citation_records(root, entries)
    cite_counts: Dict[str, int] = {}
    for r in cites:
        cite_counts[r["decision"]] = cite_counts.get(r["decision"], 0) + 1
    for r in sorted(cites, key=lambda r: (r["protocol"], r["cited"])):
        if r["decision"].startswith("ABSENT_"):
            violations.append(
                f"protocol '{r['protocol']}' cites '{r['cited']}', which is not "
                f"in the tree and not accounted for by {tier_file.name} "
                f"({r['decision']})"
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
        "citation_counts": cite_counts,
        "citations": cites,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else None)
    ap.add_argument("parity_root", help="directory holding the per-protocol parity dirs")
    ap.add_argument("--tier-file", default=None,
                    help=f"tier JSON (default: <parity_root>/{TIER_FILE_DEFAULT})")
    ap.add_argument("--json", dest="json_out", default=None, help="write the report as JSON")
    ap.add_argument("--emit-routing", action="store_true",
                    help=f"write <parity_root>/{ROUTING_FILENAME} recording, per cited "
                         "input document, whether a reader can follow it")
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

    if args.emit_routing:
        (root / ROUTING_FILENAME).write_text(
            render_citation_routing(report["citations"]), encoding="utf-8")
        print(f"wrote {root / ROUTING_FILENAME}")

    print(f"protocols: {report['protocols_total']}")
    for tier in KNOWN_TIERS:
        print(f"  {tier:<20} {report['counts'].get(tier, 0)}")
    cc = report.get("citation_counts") or {}
    print(f"input-document citations: {sum(cc.values())}")
    for dec in sorted(cc):
        print(f"  {dec:<22} {cc[dec]}")
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
