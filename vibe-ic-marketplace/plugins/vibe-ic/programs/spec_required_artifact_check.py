#!/usr/bin/env python3
"""spec_required_artifact_check.py — generic gate.

Scans Phase-1 input docs (input/docs/*.md) and generated L*.json files for
imperative "Plugin MUST emit/produce/declare <path>" clauses (English and
Traditional-Chinese forms).  For each clause it asserts the declared artifact
exists in the run dir and is non-empty.

Emits: reports/phase2/gates/spec_required_artifacts.json

Exit codes:
  0  — all declared artifacts present and non-empty (or VACUOUS-PASS)
  1  — one or more declared artifacts absent or empty
  2  — usage / I/O error

Chip-agnostic: no hard-coded design names, file names, or field names.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Clause extraction
# ---------------------------------------------------------------------------

# English: "MUST emit/produce/declare `some/path.json`"
# Also covers "shall emit", "is required to emit" etc.
_EN_PATTERN = re.compile(
    r'(?:MUST|shall|required\s+to)\s+(?:emit|produce|declare|generate|write|output)\s+[`\'""]([^\s`\'"">]+)[`\'""]]?',
    re.IGNORECASE,
)

# Traditional-Chinese form (as used in these docs):
# "**必須**於 `plugin_output/declaration.json` 聲明" or
# "必須 emit `path`" or "必須產出 `path`"
_ZH_PATTERN = re.compile(
    r'(?:\*\*)?必須(?:\*\*)?\s*(?:於\s*)?[`\'""]([^\s`\'"">]+)[`\'""]]?\s*(?:聲明|宣告|emit|產出|寫出|輸出)?'
    r'|'
    r'(?:\*\*)?必須(?:\*\*)?\s*(?:emit|produce|declare|generate|write|output)\s+[`\'""]([^\s`\'"">]+)[`\'""]]?',
    re.IGNORECASE,
)


def _extract_clauses_from_text(text: str, source: str) -> list[dict]:
    """Return list of {clause_text, artifact_path, source} dicts."""
    clauses = []
    for m in _EN_PATTERN.finditer(text):
        path = m.group(1).strip("/").rstrip(")")
        clauses.append({
            "clause_text": m.group(0),
            "artifact_path": path,
            "source": source,
            "pattern": "english_imperative",
        })
    for m in _ZH_PATTERN.finditer(text):
        path = (m.group(1) or m.group(2) or "").strip("/").rstrip(")")
        if path:
            clauses.append({
                "clause_text": m.group(0),
                "artifact_path": path,
                "source": source,
                "pattern": "zh_tw_imperative",
            })
    return clauses


def _collect_clauses(run_dir: Path) -> list[dict]:
    """Scan input/docs/*.md and phase1/generated_docs/L*.json."""
    clauses: list[dict] = []
    seen_paths: set[str] = set()

    # Markdown input docs
    input_docs_dir = run_dir / "input" / "docs"
    if input_docs_dir.is_dir():
        for md in sorted(input_docs_dir.glob("*.md")):
            text = md.read_text(errors="replace")
            for c in _extract_clauses_from_text(text, str(md.relative_to(run_dir))):
                key = c["artifact_path"]
                if key not in seen_paths:
                    seen_paths.add(key)
                    clauses.append(c)

    # Generated L-doc JSON (look in text values only, avoid false positives
    # from structured fields whose keys happen to match)
    l_doc_dir = run_dir / "phase1" / "generated_docs"
    if l_doc_dir.is_dir():
        for jf in sorted(l_doc_dir.glob("L*.json")):
            try:
                text = jf.read_text(errors="replace")
                for c in _extract_clauses_from_text(text, str(jf.relative_to(run_dir))):
                    key = c["artifact_path"]
                    if key not in seen_paths:
                        seen_paths.add(key)
                        clauses.append(c)
            except Exception:
                pass

    return clauses


# ---------------------------------------------------------------------------
# Assertion
# ---------------------------------------------------------------------------

def _check_artifact(run_dir: Path, artifact_path: str) -> dict:
    """Return {artifact_path, resolved, exists, non_empty, status}."""
    resolved = run_dir / artifact_path
    exists = resolved.exists()
    non_empty = exists and resolved.stat().st_size > 0
    if exists and non_empty:
        status = "PASS"
    elif exists and not non_empty:
        status = "FAIL_EMPTY"
    else:
        status = "FAIL_ABSENT"
    return {
        "artifact_path": artifact_path,
        "resolved": str(resolved),
        "exists": exists,
        "non_empty": non_empty,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check spec-declared required artifacts exist and are non-empty."
    )
    parser.add_argument("run_dir", nargs="?", default=".",
                        help="Run directory (default: cwd)")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"ERROR: run_dir not found: {run_dir}", file=sys.stderr)
        return 2

    clauses = _collect_clauses(run_dir)

    results: list[dict] = []
    for c in clauses:
        check = _check_artifact(run_dir, c["artifact_path"])
        results.append({**c, **check})

    # Determine overall verdict
    fails = [r for r in results if r["status"] != "PASS"]
    if not results:
        verdict = "VACUOUS_PASS"
        note = "No MUST-emit clauses found in input docs — nothing to assert."
    elif fails:
        verdict = "FAIL"
        note = f"{len(fails)} declared artifact(s) absent or empty."
    else:
        verdict = "PASS"
        note = f"All {len(results)} declared artifact(s) present and non-empty."

    report = {
        "schema_version": 1,
        "program": "spec_required_artifact_check",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "verdict": verdict,
        "note": note,
        "clauses_found": len(results),
        "failed_count": len(fails),
        "results": results,
    }

    # Write report
    out_dir = run_dir / "reports" / "phase2" / "gates"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "spec_required_artifacts.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    print(f"spec_required_artifact_check: {verdict} — {note}")
    print(f"  Report: {out_path}")

    return 0 if verdict in ("PASS", "VACUOUS_PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
