#!/usr/bin/env python3
"""
binary_doc_low_extraction_warn.py — gate (LL-36).

For projects whose vendor docs include figure-heavy PDFs, the default
`pdftotext` extractor will silently produce a near-empty .txt because
all the data lives in embedded raster figures. Downstream skills then
look at the .txt, see no relevant content, and silently skip
extraction — which is much worse than a hard FAIL because the agent
believes the doc was processed.

This gate scans the doc-extract manifest (`reports/pdf/INDEX.json` or
`<project>/input_doc/INDEX.json`) for entries that report a
`coverage_score = char_count / file_size` below the 2% threshold and
emits a per-file WARN to stderr. Exit 0 by default — the agent should
either install pdfplumber/PyMuPDF and re-run extraction, or open the
file manually.

This is a WARN gate, not a FAIL gate, because:
  * many low-coverage PDFs are intentional (cover sheets, blank
    appendices) and there's no chip-agnostic way to tell
  * pip-installing a fallback extractor is a host-environment
    decision, not something the plugin should force.

Honors waiver `binary_doc_low_extraction_acknowledged` (≥40 chars).

Usage
-----
    python3 binary_doc_low_extraction_warn.py <project_dir>

Returns 0 always (warning, not failure) unless usage error or the
project dir is missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


THRESHOLD = 0.02


def _candidate_manifests(project: Path) -> list[Path]:
    out: list[Path] = []
    for rel in (
        Path("reports") / "pdf" / "INDEX.json",
        Path("extracted_docs") / "INDEX.json",
        Path("reports") / "doc_extract" / "INDEX.json",
    ):
        p = project / rel
        if p.is_file():
            out.append(p)
    return out


def _waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
    except Exception:
        return False
    v = d.get("binary_doc_low_extraction_acknowledged", "")
    return isinstance(v, str) and len(v.strip()) >= 40


def _coverage_score(entry: dict) -> float | None:
    """Returns the coverage_score for a manifest entry.

    Prefers an explicit `coverage_score` field if doc_extract.py was
    upgraded to emit it. Otherwise computes char_count / file_size if
    both are present. Returns None if undecidable."""
    if "coverage_score" in entry:
        try:
            return float(entry["coverage_score"])
        except (TypeError, ValueError):
            pass
    cc = entry.get("char_count")
    fs = entry.get("file_size") or entry.get("input_size")
    if (isinstance(cc, (int, float))
            and isinstance(fs, (int, float)) and fs > 0):
        return float(cc) / float(fs)
    # Fallback: stat the input file when the path is recorded.
    ip = entry.get("input_path")
    if isinstance(ip, str) and isinstance(cc, (int, float)):
        try:
            sz = Path(ip).stat().st_size
            if sz > 0:
                return float(cc) / float(sz)
        except OSError:
            return None
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: binary_doc_low_extraction_warn.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    manifests = _candidate_manifests(project)
    if not manifests:
        print("PASS — no doc-extract manifest present "
              "(gate skipped)")
        return 0

    warns: list[tuple[str, float]] = []
    inspected = 0
    for m in manifests:
        try:
            data = json.loads(m.read_text(errors="replace"))
        except Exception:
            print(f"WARN — could not parse manifest {m}",
                  file=sys.stderr)
            continue
        entries = data if isinstance(data, list) else [data]
        for e in entries:
            if not isinstance(e, dict):
                continue
            ip = e.get("input_path") or ""
            fmt = (e.get("format") or "").lower()
            # Only care about binary PDF-like formats.
            if not (ip.lower().endswith(".pdf") or fmt == "pdf"):
                continue
            if (e.get("status") or "").upper() != "PASS":
                continue
            inspected += 1
            score = _coverage_score(e)
            if score is None:
                continue
            if score < THRESHOLD:
                warns.append((ip, score))

    if not warns:
        print(f"PASS — inspected {inspected} PDF entries; none "
              f"below coverage threshold {THRESHOLD:.0%}")
        return 0

    if _waived(project):
        print(f"PASS_WITH_WAIVER — {len(warns)} PDF(s) below "
              f"coverage threshold {THRESHOLD:.0%} (waived)")
        for ip, sc in warns:
            print(f"    coverage={sc:.2%}  {ip}", file=sys.stderr)
        return 0

    # Default behaviour: WARN to stderr, exit 0.
    print(f"WARN — {len(warns)} PDF(s) below coverage threshold "
          f"{THRESHOLD:.0%}; install pdfplumber or PyMuPDF and "
          f"re-run extraction to capture figure-heavy content:",
          file=sys.stderr)
    for ip, sc in warns:
        print(f"    coverage={sc:.2%}  {ip}", file=sys.stderr)
    print(f"PASS — {inspected} PDF entries inspected, "
          f"{len(warns)} WARN-flagged (see stderr)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
