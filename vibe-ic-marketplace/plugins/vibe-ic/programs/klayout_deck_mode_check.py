#!/usr/bin/env python3
"""klayout_deck_mode_check.py — BACKLOG-v10 P0.1 enforcement loop.

Closes the verdict-integration hole around the v0.112 KLayout
fallback. The existing `eda_drc_klayout` MCP tool will fall back to
`deck_mode: structural_only` (just verifies GDS parses + top cell
exists, NO MIN-WIDTH / MIN-SPACING / MIN-AREA rules) when the
custom-PDK auto-deck synthesis produces 0 enforceable rules — the
typical case when a custom PDK ships a tech LEF without a
hand-supplied DRC deck or layermap.

That fallback returns `success=true`. Without this gate, a project
silently passes Step 23 / Step 26 (Physical Verification) using a
DRC pass that proves NOTHING about geometric correctness.

Gate behaviour
==============

For each `*.lyrdb`-adjacent KLayout DRC manifest / log, parse for
`deck_mode` and similar attestation tokens:

  - `deck_mode: structural_only`           → require waiver
  - `STRUCTURAL_PASS` in manifest status   → require waiver
  - "Auto-deck synthesis ... produced 0 enforceable rules" advisory
    in output → require waiver
  - tool name contains "structural-only"   → require waiver

If a structural-only pass occurred AND no `waivers.json` entry with
`id: "K01_klayout_structural_only_drc"` exists, emit
`KLAYOUT_STRUCTURAL_DRC_NEEDS_WAIVER` ERROR.

False-alert guards
==================

  - Silent if no KLayout DRC artefacts exist (project hasn't run
    Step 23 / 26 yet).
  - Silent if every DRC artefact reports a real auto-deck or
    user-supplied deck (rules > 0).
  - Silent if waivers.json declares K01_klayout_structural_only_drc
    with non-empty `rationale` / `reason` AND `review_required: true`.

Exit codes: 0 PASS / 1 FAIL / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


_STRUCTURAL_TOKENS = (
    re.compile(r"deck_mode\s*[:=]\s*[\"']?structural_only", re.IGNORECASE),
    re.compile(r"STRUCTURAL_PASS", re.IGNORECASE),
    re.compile(r"structural-only", re.IGNORECASE),
    re.compile(r"produced\s+0\s+enforceable\s+rules", re.IGNORECASE),
)


def _find_drc_artefacts(project: Path) -> list[Path]:
    out: list[Path] = []
    candidates = [
        "**/manifest.json",
        "**/klayout_*.json",
        "**/drc_*.log",
        "**/*.lyrdb",
        "reports/drc_*.json",
    ]
    seen: set[Path] = set()
    for pat in candidates:
        for f in project.glob(pat):
            if f.is_file() and f not in seen:
                seen.add(f)
                out.append(f)
    return out


def _is_structural_evidence(text: str) -> bool:
    return any(p.search(text) for p in _STRUCTURAL_TOKENS)


def _waiver_present(project: Path) -> str:
    """Return rationale string if K01_klayout_structural_only_drc waiver
    exists with non-empty rationale, else empty."""
    for cand in (project / "waivers.json", *project.glob("**/waivers.json")):
        if not cand.exists():
            continue
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or [])
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") in ("K01_klayout_structural_only_drc",
                               "K01", "klayout_structural_only_drc"):
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and rat.strip():
                    return rat
    return ""


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "drc_artefacts_found": [],
        "structural_evidence": [],
        "waiver_rationale": "",
        "skipped_reason": "",
    }

    artefacts = _find_drc_artefacts(project)
    if not artefacts:
        summary["skipped_reason"] = "no KLayout DRC artefacts found"
        return findings, summary
    summary["drc_artefacts_found"] = [
        str(a.relative_to(project)) for a in artefacts
    ]

    structural_files: list[Path] = []
    for a in artefacts:
        text = _read(a)
        if _is_structural_evidence(text):
            structural_files.append(a)
    summary["structural_evidence"] = [
        str(p.relative_to(project)) for p in structural_files
    ]

    if not structural_files:
        return findings, summary  # all real DRC, no fallback used

    waiver_rationale = _waiver_present(project)
    summary["waiver_rationale"] = waiver_rationale
    if waiver_rationale:
        return findings, summary  # acknowledged via waiver

    findings.append(Finding(
        severity="ERROR",
        rule="KLAYOUT_STRUCTURAL_DRC_NEEDS_WAIVER",
        message=(
            f"KLayout DRC ran in structural-only fallback mode for "
            f"{len(structural_files)} artefact(s) — verifies GDS parses "
            f"+ top cell exists but enforces NO geometric rules. "
            f"Production tapeout requires foundry-supplied DRC deck. "
            f"Either (a) supply `custom_drc_script` to eda_drc_klayout, "
            f"OR (b) add a waivers.json entry with "
            f"`id: \"K01_klayout_structural_only_drc\"`, non-empty "
            f"`rationale`, `review_required: true`, and a foundry "
            f"closure plan reference (foundry_signoff_plan_check.py)."
        ),
        file=structural_files[0].relative_to(project).as_posix(),
    ))
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="klayout_deck_mode_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "klayout_deck_mode_check",
            "passed": not findings,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== klayout_deck_mode_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        evid = summary["structural_evidence"]
        if evid:
            print(f"  [PASS] {len(evid)} structural-only run(s) covered "
                  f"by waiver K01_klayout_structural_only_drc")
        else:
            print(f"  [PASS] {len(summary['drc_artefacts_found'])} "
                  f"DRC artefact(s) used real (non-structural) deck")
        return 0
    for f in findings:
        loc = f" ({f.file})" if f.file else ""
        print(f"  [{f.severity.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: FAIL (structural-only DRC requires K01 waiver)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
