#!/usr/bin/env python3
"""phase1_provenance_presence_check.py — Phase 1 D6-traceability gate.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Verifies that every Phase-1 layer document (L1..L13) carries provenance
information at its top level. Specifically each L*.json must have AT
LEAST ONE of:

    - provenance       (dict, non-empty)
    - source_documents (list, non-empty)

This gate catches the v055 regression where `phase1-orchestrate`
bypassed `tools/phase1_engine/cli.py run-all` and let an agent
hand-author L2-L9 without provenance. Without this check, downstream
Phase 2 cannot trace which spec line came from which input doc / PM
dialog / class template default.

Layer set (matches tools/training/rubric_score.py EXPECTED_DOCS):
    L1 L2 L3 L4 L5 L6 L7 L8R L8T L9 L10 L11 L12 L13   (14 docs total)

Usage
-----
    python3 phase1_provenance_presence_check.py <generated_docs_dir>
        [--json <out>] [--strict]

    --strict  treat any missing file as FAIL (not just missing prov).
              Default: missing files are FAIL too, but the message
              distinguishes "file absent" from "file present but no prov".

Exit codes
----------
    0  — all 14 layers present AND each carries provenance/source_documents
    1  — one or more layers missing or missing prov fields
    2  — input error (not a directory, etc)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_DOCS = [
    ("L1",  "L1_DATASHEET.json"),
    ("L2",  "L2_FRS.json"),
    ("L3",  "L3_CMD_PROTOCOL.json"),
    ("L4",  "L4_REGMAP.json"),
    ("L5",  "L5_ADI_SPEC.json"),
    ("L6",  "L6_CONTROL_LOGIC.json"),
    ("L7",  "L7_TEST_DEBUG.json"),
    ("L8R", "L8_RTL_CONSTANTS.json"),
    ("L8T", "L8_TIMING_WAVEFORM.json"),
    ("L9",  "L9_INTEGRATION_SPEC.json"),
    ("L10", "L10_TEST_CASES.json"),
    ("L11", "L11_CALIBRATION.json"),
    ("L12", "L12_BEHAVIORAL_SEQUENCES.json"),
    ("L13", "L13_LAB_CALIBRATION.json"),
]

PROV_KEYS = ("provenance", "source_documents")


def _truthy(v: Any) -> bool:
    if v is None: return False
    if isinstance(v, (list, dict, str, bytes)): return len(v) > 0
    return bool(v)


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def check_dir(gen: Path) -> dict[str, Any]:
    per_layer = {}
    for tag, fname in EXPECTED_DOCS:
        path = gen / fname
        if not path.is_file():
            per_layer[tag] = {"status": "MISSING_FILE",
                              "reason": f"{fname} not found"}
            continue
        doc = _load(path)
        if doc is None:
            per_layer[tag] = {"status": "MISSING_FILE",
                              "reason": "JSON parse error"}
            continue
        found = [k for k in PROV_KEYS
                 if k in doc and _truthy(doc[k])]
        if found:
            per_layer[tag] = {"status": "PASS", "keys": found}
        else:
            per_layer[tag] = {"status": "FAIL_NO_PROV",
                              "reason": "no provenance/source_documents "
                                        "at top level"}
    passes = sum(1 for r in per_layer.values() if r["status"] == "PASS")
    total = len(EXPECTED_DOCS)
    return {
        "target": str(gen),
        "passes": passes,
        "total": total,
        "per_layer": per_layer,
    }


def _print_report(report: dict[str, Any]) -> None:
    print(f"\nPhase-1 provenance gate — {report['target']}\n")
    for tag, _ in EXPECTED_DOCS:
        r = report["per_layer"][tag]
        if r["status"] == "PASS":
            print(f"  [PASS] {tag:<4} carries: {', '.join(r['keys'])}")
        else:
            print(f"  [FAIL] {tag:<4} {r['status']} — {r['reason']}")
    print(f"\n  Summary: {report['passes']}/{report['total']} layers carry "
          f"provenance/source_documents")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="path to generated_docs/ dir")
    ap.add_argument("--json", help="write report JSON to this path")
    ap.add_argument("--strict", action="store_true",
                    help="reserved — already strict by default")
    args = ap.parse_args()

    gen = Path(args.target)
    if not gen.is_dir():
        print(f"error: not a directory: {gen}", file=sys.stderr)
        return 2

    report = check_dir(gen)
    _print_report(report)
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nwrote {args.json}")
    return 0 if report["passes"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
