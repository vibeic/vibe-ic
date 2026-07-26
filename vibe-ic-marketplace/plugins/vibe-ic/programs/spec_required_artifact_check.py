#!/usr/bin/env python3
"""spec_required_artifact_check.py — generic gate.

Scans Phase-1 input docs (input/docs/*.md) and generated L*.json files for
imperative "Plugin MUST emit/produce/declare <path>" clauses (English and
Traditional-Chinese forms).  For each clause it asserts the declared artifact
exists in the run dir and is non-empty.

Only PATH-SHAPED tokens are asserted on -- see `_is_path_shaped`.  A
backticked token after a MUST-verb is very often a SIGNAL name, not a
filesystem path, and asserting on those failed legitimate designs (see the
false-positive note on `_is_path_shaped`).  Rejected tokens are reported in
`ignored_tokens` so the narrowing is visible rather than silent.

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


# ---------------------------------------------------------------------------
# Path-shape filter
# ---------------------------------------------------------------------------

# CONFIRMED FALSE POSITIVE this filter closes.  Both regexes above match ANY
# backticked token that follows a MUST-verb, so a SIGNAL name reads as a
# filesystem path.  Prose lifted verbatim from this plugin's own knowledge
# base -- "A streaming run-length counter must emit `valid` for exactly one
# cycle ..." plus "MUST declare `rst_n`" -- made the gate return rc=1 /
# verdict FAIL with FAIL_ABSENT 'valid' and FAIL_ABSENT 'rst_n' on a run that
# DID contain every artifact its spec required.  Any legitimate valid/ready
# design whose spec names its signals in backticks was failed by this gate.
#
# A declared ARTIFACT is a file, so the token must look like one: it carries a
# directory separator, or it carries a known artifact extension.  Everything
# else is recorded in the report's `ignored_tokens` -- narrowed, never
# silently dropped, so a reviewer can see exactly what the gate declined to
# assert on and why.
_ARTIFACT_EXTENSIONS = frozenset({
    # structured data / reports
    "json", "yaml", "yml", "toml", "ini", "cfg", "csv", "tsv", "xml",
    "md", "txt", "log", "rpt", "html", "pdf",
    # HDL / EDA source and sign-off artifacts
    "v", "sv", "vh", "svh", "vhd", "vhdl", "tcl", "sdc", "sdf", "upf",
    "lef", "lib", "def", "gds", "gds2", "oas", "spef", "cdl", "cir",
    "spi", "sp", "vcd", "fst", "saif", "net", "eqn", "qsf", "sof", "bit",
    # generic build outputs
    "py", "sh", "zip", "tar", "gz",
})


def _is_path_shaped(token: str) -> bool:
    """True when `token` looks like a filesystem artifact rather than a name.

    Path-shaped == carries a directory separator, or ends in a known
    artifact extension.  `plugin_output/declaration.json` and
    `declaration.json` qualify; `valid`, `rst_n`, `p` do not.
    """
    if not token:
        return False
    if "/" in token or "\\" in token:
        return True
    head, dot, ext = token.rpartition(".")
    return bool(dot) and bool(head) and ext.lower() in _ARTIFACT_EXTENSIONS


def _extract_clauses_from_text(text: str, source: str) -> tuple[list[dict], list[dict]]:
    """Return (clauses, ignored) — ignored holds non-path-shaped tokens."""
    clauses: list[dict] = []
    ignored: list[dict] = []

    def _record(raw: str, token: str, pattern: str) -> None:
        path = token.strip("/").rstrip(")")
        if not path:
            return
        entry = {
            "clause_text": raw,
            "artifact_path": path,
            "source": source,
            "pattern": pattern,
        }
        if _is_path_shaped(path):
            clauses.append(entry)
        else:
            ignored.append({
                **entry,
                "reason": ("token is not path-shaped (no directory separator "
                           "and no known artifact extension) — reads as a "
                           "signal/identifier name, not a required artifact"),
            })

    for m in _EN_PATTERN.finditer(text):
        _record(m.group(0), m.group(1), "english_imperative")
    for m in _ZH_PATTERN.finditer(text):
        _record(m.group(0), (m.group(1) or m.group(2) or ""), "zh_tw_imperative")
    return clauses, ignored


def _collect_clauses(run_dir: Path) -> tuple[list[dict], list[dict]]:
    """Scan input/docs/*.md and phase1/generated_docs/L*.json.

    Returns (clauses, ignored_tokens).
    """
    clauses: list[dict] = []
    ignored: list[dict] = []
    seen_paths: set[str] = set()
    seen_ignored: set[str] = set()

    def _absorb(found: list[dict], dropped: list[dict]) -> None:
        for c in found:
            key = c["artifact_path"]
            if key not in seen_paths:
                seen_paths.add(key)
                clauses.append(c)
        for c in dropped:
            key = c["artifact_path"]
            if key not in seen_ignored:
                seen_ignored.add(key)
                ignored.append(c)

    # Markdown input docs
    input_docs_dir = run_dir / "input" / "docs"
    if input_docs_dir.is_dir():
        for md in sorted(input_docs_dir.glob("*.md")):
            text = md.read_text(errors="replace")
            _absorb(*_extract_clauses_from_text(text, str(md.relative_to(run_dir))))

    # Generated L-doc JSON (look in text values only, avoid false positives
    # from structured fields whose keys happen to match)
    l_doc_dir = run_dir / "phase1" / "generated_docs"
    if l_doc_dir.is_dir():
        for jf in sorted(l_doc_dir.glob("L*.json")):
            try:
                text = jf.read_text(errors="replace")
                _absorb(*_extract_clauses_from_text(text, str(jf.relative_to(run_dir))))
            except Exception:
                pass

    return clauses, ignored


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

    clauses, ignored = _collect_clauses(run_dir)

    results: list[dict] = []
    for c in clauses:
        check = _check_artifact(run_dir, c["artifact_path"])
        results.append({**c, **check})

    # Determine overall verdict
    fails = [r for r in results if r["status"] != "PASS"]
    if not results:
        verdict = "VACUOUS_PASS"
        note = ("No path-shaped MUST-emit clauses found in input docs — "
                "nothing to assert.")
        if ignored:
            note += (f" ({len(ignored)} non-path-shaped token(s) ignored: "
                     f"{', '.join(sorted(t['artifact_path'] for t in ignored)[:8])})")
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
        # Tokens the regexes matched but that are not path-shaped (signal
        # names such as `valid` / `rst_n`).  Reported so the narrowing is
        # auditable — the gate asserts on none of them.
        "ignored_token_count": len(ignored),
        "ignored_tokens": ignored,
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
