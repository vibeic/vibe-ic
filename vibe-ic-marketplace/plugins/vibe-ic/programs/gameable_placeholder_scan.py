#!/usr/bin/env python3
"""gameable_placeholder_scan.py — deterministic half of the
compliance-gate-spot-check "gameability scan" (Step 3, first three
bullets).

The compliance-gate-spot-check skill used to describe THREE literal
token / structural anti-patterns as a manual AI eyeball pass:

  (1) PLACEHOLDER_TOKEN — any generated L*.json under
      ``phase1/generated_docs/`` (or legacy ``generated_docs/``)
      that still carries the raw template-scaffold strings
      ``__TODO__`` or ``<unknown>``. These tokens mean an extractor
      field was never resolved; a gate that greps them as "present"
      false-PASSes.

  (2) AUTO_ALIAS — an L1 ``pin_table`` / ``pins`` entry whose
      ``aliases`` list contains a value equal to ``name.lower()`` or
      ``name.replace("_","")``. These are evidence-free auto-synth
      aliases (closed in the runner by #258); when they reappear in a
      generated doc they game any "pin has aliases" depth gate without
      carrying real datasheet/RTL/board synonyms.

  (3) VERDICT_PLACEHOLDER — an L9 ``expected_verdict_byte_hex`` (or the
      ``usb_hid_tester_verdict_byte_hex`` alias) whose literal value is
      the placeholder ``0x__todo__`` (case-insensitive). The half-duplex
      / HID tester oracle byte was never resolved, so a TB that compares
      against it can never honestly PASS.

All three are fixed string / structural matches over deterministic
artifact paths — i.e. a classic Bucket-A grep. This program owns them
so the skill no longer asks the AI to eyeball them. The remaining two
gameability bullets ("copy-pasted sim tokens not actually exercised",
"reference TB always prints PASS regardless of input") are genuine
semantic judgment and stay in the skill prose.

NO FABRICATION: this scan only flags artifacts that ACTUALLY contain
the placeholder tokens / auto-alias shapes. A project with no generated
docs is reported honestly (NO_GENERATED_DOCS, exit 1) rather than a
vacuous PASS — an empty scan must not be mistaken for a clean one.

chip-AGNOSTIC: no chip / vendor / protocol literal participates. The
only knobs are the placeholder-token set and the verdict field names.

Usage:
    python3 gameable_placeholder_scan.py <project_dir> [--json [PATH]]

Exit codes:
    0 = CLEAN (generated docs present, no gameable pattern found)
    1 = FAIL  (>=1 gameable pattern found, OR no generated docs to scan)
    2 = argument / I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# Raw scaffold tokens that must never survive into a "complete" L doc.
PLACEHOLDER_TOKENS = ("__TODO__", "<unknown>")

# L9 oracle-byte placeholder (the half-duplex / HID tester verdict).
VERDICT_PLACEHOLDER = "0x__todo__"
VERDICT_FIELDS = ("expected_verdict_byte_hex",
                  "usb_hid_tester_verdict_byte_hex")

# L1 pin-table candidate keys + alias candidate keys.
_PIN_TABLE_KEYS = ("pin_table", "pins", "pinout")
_ALIAS_KEYS = ("aliases", "alias", "alt_names", "synonyms")


@dataclass
class Finding:
    pattern: str        # PLACEHOLDER_TOKEN | AUTO_ALIAS | VERDICT_PLACEHOLDER
    file: str           # path relative to project
    detail: str         # human-readable specifics


def _generated_docs_dir(project: Path) -> Optional[Path]:
    """Canonical phase1/generated_docs, falling back to legacy
    generated_docs/. Returns None when neither exists."""
    canonical = project / "phase1" / "generated_docs"
    if canonical.is_dir():
        return canonical
    legacy = project / "generated_docs"
    if legacy.is_dir():
        return legacy
    return None


def _scan_placeholder_tokens(rel: str, raw_text: str) -> List[Finding]:
    out: List[Finding] = []
    for tok in PLACEHOLDER_TOKENS:
        n = raw_text.count(tok)
        if n:
            out.append(Finding(
                pattern="PLACEHOLDER_TOKEN",
                file=rel,
                detail=f"raw scaffold token {tok!r} appears {n}x — "
                       f"an unresolved extractor field",
            ))
    return out


def _iter_pin_entries(doc: Any):
    if not isinstance(doc, dict):
        return
    for key in _PIN_TABLE_KEYS:
        table = doc.get(key)
        if isinstance(table, list):
            for entry in table:
                if isinstance(entry, dict):
                    yield entry


def _alias_values(entry: Dict[str, Any]) -> List[str]:
    vals: List[str] = []
    for key in _ALIAS_KEYS:
        v = entry.get(key)
        if isinstance(v, str):
            vals.append(v)
        elif isinstance(v, list):
            vals.extend(a for a in v if isinstance(a, str))
    return vals


def _scan_auto_aliases(rel: str, doc: Any) -> List[Finding]:
    out: List[Finding] = []
    for entry in _iter_pin_entries(doc):
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        gamey = sorted({
            a for a in _alias_values(entry)
            if a == name.lower() or a == name.replace("_", "")
        })
        if gamey:
            out.append(Finding(
                pattern="AUTO_ALIAS",
                file=rel,
                detail=f"pin {name!r} carries evidence-free auto-alias(es) "
                       f"{gamey} (== name.lower()/name.replace('_','')) — "
                       f"games the pin-alias depth gate (#258)",
            ))
    return out


def _scan_verdict_placeholder(rel: str, doc: Any) -> List[Finding]:
    out: List[Finding] = []
    if not isinstance(doc, dict):
        return out
    for fld in VERDICT_FIELDS:
        val = doc.get(fld)
        if isinstance(val, str) and val.strip().lower() == VERDICT_PLACEHOLDER:
            out.append(Finding(
                pattern="VERDICT_PLACEHOLDER",
                file=rel,
                detail=f"{fld} == {val!r}; the tester oracle byte was never "
                       f"resolved, so a TB comparing against it can never "
                       f"honestly PASS",
            ))
    return out


def scan(project: Path) -> tuple[str, List[Finding], Dict[str, Any]]:
    summary: Dict[str, Any] = {
        "generated_docs_dir": None,
        "l_docs_scanned": 0,
        "findings_count": 0,
    }
    gdir = _generated_docs_dir(project)
    if gdir is None:
        # No artifacts to scan. NOT a clean pass — report honestly.
        return "NO_GENERATED_DOCS", [], summary

    summary["generated_docs_dir"] = str(gdir)
    findings: List[Finding] = []
    l_files = sorted(gdir.glob("L*.json"))
    for f in l_files:
        rel = str(f.relative_to(project))
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        summary["l_docs_scanned"] += 1
        # (1) raw-token grep operates on the serialized text.
        findings.extend(_scan_placeholder_tokens(rel, raw))
        # (2) + (3) structural checks operate on the parsed object.
        try:
            doc = json.loads(raw)
        except Exception:
            # Non-JSON L file is itself suspect, but token grep above
            # already covered placeholder strings; skip structural part.
            continue
        findings.extend(_scan_auto_aliases(rel, doc))
        findings.extend(_scan_verdict_placeholder(rel, doc))

    summary["findings_count"] = len(findings)
    if summary["l_docs_scanned"] == 0:
        # generated_docs dir exists but holds no L*.json — also not clean.
        return "NO_GENERATED_DOCS", findings, summary
    verdict = "FAIL" if findings else "CLEAN"
    return verdict, findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic gameable-placeholder scan over "
                    "generated L*.json (compliance-gate-spot-check Step 3).")
    ap.add_argument("project_dir")
    ap.add_argument("--json", nargs="?", const="-", default=None,
                    help="write JSON report to PATH (or stdout if bare)")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"error: project dir not found: {project}", file=sys.stderr)
        return 2

    verdict, findings, summary = scan(project)
    report = {
        "program": "gameable_placeholder_scan",
        "version": "1.0.0",
        "project": str(project),
        "verdict": verdict,
        "summary": summary,
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        print(f"[{verdict}] gameable_placeholder_scan")
        print(f"  generated_docs: {summary['generated_docs_dir']}")
        print(f"  L*.json scanned: {summary['l_docs_scanned']}")
        print(f"  gameable patterns: {summary['findings_count']}")
        for fnd in findings:
            print(f"  ✗ {fnd.pattern} @ {fnd.file}: {fnd.detail}")
        if verdict == "NO_GENERATED_DOCS":
            print("  ! no phase1/generated_docs/L*.json to scan — "
                  "cannot claim clean; run Phase 1 first")
    elif args.json == "-":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(f"json: {out}")

    # CLEAN → 0; FAIL and NO_GENERATED_DOCS → 1 (honest non-pass).
    return 0 if verdict == "CLEAN" else 1


if __name__ == "__main__":
    sys.exit(main())
