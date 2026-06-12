#!/usr/bin/env python3
"""
l12_sequence_implementation_check.py — Enforce that each declared L12
behavioral sequence has a corresponding RTL implementation module.

Rule (derived from v052 rtl/testmode_entry.v for TEST_MODE_ENTRY, and
v052 rtl/cc_reset_ctrl.v for CC_RESET_700MS):

    For every entry ``sequences[*].id`` in L12_BEHAVIORAL_SEQUENCES.json,
    there SHOULD be:

      1. An RTL file whose basename contains a substring derived from the
         sequence id (normalised to lower-case, after stripping obvious
         timing suffixes like ``_700MS`` / ``_FULL`` / ``_SEQUENCE`` / ...).
      2. That file MUST contain at least one conditional construct
         (``case (`` statement, or 2+ ``if (`` blocks). A file with zero
         conditional logic is essentially a stub.

    Sequences whose ``category`` field contains ``info_only`` or
    ``documentation_only`` are skipped — they are descriptive entries not
    intended to be directly implemented as their own module.

Edge cases:
  * ``--l12-json`` not given, file missing, or ``sequences`` key absent
    → exit 0 with a single INFO note ("no L12 sequences declared").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    sequence_id: str = ""
    file: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Suffixes stripped from sequence id when deriving the module-name substring.
_STRIP_SUFFIXES: Tuple[str, ...] = (
    "_700ms", "_500ms", "_200ms", "_100ms", "_ms",
    "_full", "_sequence", "_seq", "_flow", "_chain",
    "_validation", "_validate", "_check",
    "_step", "_steps", "_9step", "_9_step",
)

# Categories that are NOT required to have an implementation module.
_SKIP_CATEGORIES: Tuple[str, ...] = (
    "info_only", "documentation_only",
)


def _normalise_id(seq_id: str) -> str:
    base = seq_id.strip().lower()
    changed = True
    # Strip known suffixes greedily (may strip multiple times).
    while changed:
        changed = False
        for suf in _STRIP_SUFFIXES:
            if base.endswith(suf) and len(base) > len(suf):
                base = base[: -len(suf)]
                changed = True
    # Keep the first alnum token so e.g. ENGR_MODE_UNLOCK → "engr_mode_unlock"
    # still matches either half when we substring-scan file basenames.
    return base


def _candidate_substrings(norm_id: str) -> List[str]:
    """Substring variants we'll scan file basenames for."""
    variants = {norm_id, norm_id.replace("_", "")}
    # Individual tokens too — they help find files like cc_reset_ctrl.v
    # when the id is CC_RESET_700MS (norm → "cc_reset").
    toks = [t for t in norm_id.split("_") if len(t) >= 2]
    variants.update(toks)
    # Also multi-token prefixes of len 2..N.
    for i in range(2, len(toks) + 1):
        variants.add("_".join(toks[:i]))
    return sorted(variants, key=len, reverse=True)


_CASE_RE = re.compile(r"\bcase\s*\(", re.IGNORECASE)
_IF_RE = re.compile(r"\bif\s*\(")


def _has_conditional_logic(text: str) -> bool:
    if _CASE_RE.search(text):
        return True
    if len(_IF_RE.findall(text)) >= 2:
        return True
    return False


def _find_impl_file(rtl_files: List[Path], norm_id: str) -> Path | None:
    cands = _candidate_substrings(norm_id)
    # Prefer longer matches first (sorted by _candidate_substrings above).
    for cand in cands:
        if len(cand) < 3:  # too short to be discriminating
            continue
        for p in rtl_files:
            if cand in p.stem.lower():
                return p
    return None


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def audit(rtl_dir: Path, l12_json: Path | None) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    summary: Dict = {
        "l12_json": str(l12_json) if l12_json else "",
        "sequences_total": 0,
        "sequences_checked": 0,
        "sequences_skipped": 0,
    }

    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding(
            severity="ERROR",
            category="IO",
            message=f"RTL directory not found: {rtl_dir}",
        ))
        return findings, summary

    if l12_json is None or not l12_json.exists():
        findings.append(Finding(
            severity="INFO",
            category="NO_L12",
            message=("no L12 sequences declared — "
                     "--l12-json not provided or file missing."),
        ))
        return findings, summary

    try:
        data = json.loads(l12_json.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        findings.append(Finding(
            severity="ERROR",
            category="INVALID_JSON",
            message=f"Cannot parse L12 JSON: {e}",
            file=str(l12_json),
        ))
        return findings, summary

    sequences = data.get("sequences") if isinstance(data, dict) else None
    if not isinstance(sequences, list) or not sequences:
        findings.append(Finding(
            severity="INFO",
            category="NO_L12",
            message="no L12 sequences declared — 'sequences' key is empty.",
            file=str(l12_json),
        ))
        return findings, summary

    summary["sequences_total"] = len(sequences)

    rtl_files = sorted(
        [p for p in rtl_dir.rglob("*")
         if p.is_file() and p.suffix.lower() in (".v", ".sv")]
    )

    for entry in sequences:
        if not isinstance(entry, dict):
            continue
        seq_id = str(entry.get("id", "")).strip()
        if not seq_id:
            continue
        category = str(entry.get("category", "")).lower()
        if any(sk in category for sk in _SKIP_CATEGORIES):
            summary["sequences_skipped"] += 1
            continue

        summary["sequences_checked"] += 1

        # If the L12 entry names an rtl_module explicitly, trust it first.
        impl: Path | None = None
        hint = entry.get("rtl_module") or entry.get("rtl_file")
        if isinstance(hint, str) and hint.strip():
            # Extract the first filename-like token from free-form text,
            # e.g. "rx_cmd.v — FSM drives ..." → "rx_cmd.v" ; or a bare
            # identifier like "cc_reset_ctrl" → "cc_reset_ctrl".
            stem_re = re.compile(
                r"(?:rtl/)?([A-Za-z_][\w]*)(?:\.(?:s?v))?"
            )
            hint_stems: List[str] = []
            for m in stem_re.finditer(hint):
                s = m.group(1)
                if len(s) >= 3 and s.lower() not in (
                    "rtl", "fsm", "new", "the", "and", "for"
                ):
                    hint_stems.append(s)
                if len(hint_stems) >= 4:
                    break
            for hs in hint_stems:
                for p in rtl_files:
                    if hs.lower() == p.stem.lower():
                        impl = p
                        break
                if impl is not None:
                    break
            if impl is None:
                for hs in hint_stems:
                    for p in rtl_files:
                        if hs.lower() in p.stem.lower() and len(hs) >= 4:
                            impl = p
                            break
                    if impl is not None:
                        break

        if impl is None:
            norm = _normalise_id(seq_id)
            impl = _find_impl_file(rtl_files, norm)
        else:
            norm = _normalise_id(seq_id)

        if impl is None:
            findings.append(Finding(
                severity="ERROR",
                category="NO_IMPL_MODULE",
                message=(
                    f"L12 sequence '{seq_id}' has no implementing RTL "
                    f"module. Searched for basename containing a "
                    f"substring of '{norm}'."
                ),
                sequence_id=seq_id,
            ))
            continue

        try:
            text = impl.read_text(errors="replace")
        except OSError as e:
            findings.append(Finding(
                severity="ERROR",
                category="IO",
                message=f"Cannot read {impl}: {e}",
                sequence_id=seq_id,
                file=str(impl),
            ))
            continue

        if not _has_conditional_logic(text):
            findings.append(Finding(
                severity="ERROR",
                category="STUB_MODULE",
                message=(
                    f"Implementing file for sequence '{seq_id}' exists "
                    "but has no conditional logic (no 'case (' and "
                    "fewer than 2 'if (' blocks) — looks like a stub."
                ),
                sequence_id=seq_id,
                file=str(impl),
            ))

    return findings, summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], rtl_dir: Path, summary: Dict) -> Dict:
    has_err = any(f.severity == "ERROR" for f in findings)
    return {
        "program": "l12_sequence_implementation_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {
            **summary,
            "findings_count": len(findings),
            "pass": not has_err,
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Verify each L12 behavioural sequence has a "
                     "corresponding RTL implementation module.")
    )
    parser.add_argument("--rtl-dir", required=True,
                        help="Directory containing .v / .sv RTL files")
    parser.add_argument("--l12-json", default=None,
                        help="Path to L12_BEHAVIORAL_SEQUENCES.json "
                             "(optional; absent → PASS).")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="Optional path to write machine-readable report")
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    l12_json = Path(args.l12_json) if args.l12_json else None

    try:
        findings, summary = audit(rtl_dir, l12_json)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    report = build_report(findings, rtl_dir, summary)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(report_json)

    print(report_json)

    # IO errors (missing RTL dir / missing L12 json) → exit 2 per the
    # gate exit-code contract (0 PASS / 1 FAIL / 2 input-missing).
    if any(getattr(f, "category", "") == "IO" for f in findings):
        return 2
    # INFO-only result (no L12) → PASS
    if not any(f.severity == "ERROR" for f in findings):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
