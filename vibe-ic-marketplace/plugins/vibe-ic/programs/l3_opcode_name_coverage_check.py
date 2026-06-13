#!/usr/bin/env python3
"""l3_opcode_name_coverage_check.py — v1.6.131 (#51 Fix 6)

Phase 1 verify gate that fails when L3.opcodes contains structurally-
present entries (count > 0) but per-entry names are predominantly
placeholders. Closes the false-PASS path field-agent observed at
v1.6.130:

  L3.opcodes = 18 entries
  9 entries:  name="OPCODE_NAME_UNKNOWN"
  9 entries:  real names

Without this gate, downstream consumers see ``len(L3.opcodes) == 18``
and assume the dispatcher table is complete; phase2 spec-to-RTL emit
then runs against half-placeholder data and emits a default-only
dispatcher that leaves the DUT silent on every opcode in reference_tb.

Verdict tiers (chip-AGNOSTIC):

  PASS         — placeholder ratio == 0 (every opcode has a real name).
  FAIL         — any placeholder name (ratio > 0).
                 v1.6.132 (#51 Fix 7c) tightened from 5% to 0%
                 because protocol-spec docs always declare a name
                 for every opcode; any UNKNOWN means the extractor
                 missed it, not a legitimate vendor quirk.
  VACUOUS_PASS — len(L3.opcodes) == 0 (no command protocol in input,
                 covered by `no_opcodes_in_input: true`).

Exit codes:
  0 PASS / PASS_WITH_WAIVERS / VACUOUS_PASS
  1 FAIL
  2 input error / silent skip (L3 absent — phase1 hadn't run yet)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

GATE = "l3_opcode_name_coverage_check"
# v1.6.137 (#51 Fix 12) — `RESERVED` is the canonical protocol-spec
# mnemonic for unimplemented / placeholder rows in command tables
# (the v1.6.136 `無` → RESERVED alias surfaces this), NOT an
# extractor-miss sentinel. Treating it as placeholder caused a
# false-FAIL on rows that have a perfectly valid mnemonic.
# Real placeholder names = TODO / TBD / TBA / UNKNOWN / "" / null /
# the OPCODE_NAME_UNKNOWN sentinel from `_infer_opcode_name`.
PLACEHOLDER_NAMES = frozenset({
    "OPCODE_NAME_UNKNOWN", "TODO", "TBD", "TBA",
    "UNKNOWN", "PLACEHOLDER", "",
})
PLACEHOLDER_THRESHOLD = 0.0  # v1.6.132 — 100% coverage required

import _path_layout as _pl


def _is_placeholder(op: Dict[str, Any]) -> bool:
    name = op.get("name")
    if name is None:
        return True
    if isinstance(name, str) and name.upper() in PLACEHOLDER_NAMES:
        return True
    return False


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=GATE, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None,
                    help="write JSON verdict to this path")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    l3_path = _pl.generated_docs_dir(project) / "L3_CMD_PROTOCOL.json"
    if not l3_path.is_file():
        print(f"SILENT_SKIP: {l3_path} not found "
              f"(phase1 hasn't run yet?)", file=sys.stderr)
        return 2

    try:
        l3 = json.loads(l3_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: cannot parse {l3_path}: {e}", file=sys.stderr)
        return 2

    opcodes = l3.get("opcodes") or []
    if not isinstance(opcodes, list) or not opcodes:
        # No opcodes — this is the no_opcodes_in_input case.
        verdict = "VACUOUS_PASS"
        report = {
            "gate": GATE, "verdict": verdict,
            "reason": "L3.opcodes empty — no command protocol in input "
                      "(structurally correct for non-protocol IPs).",
            "total": 0, "placeholders": 0, "placeholder_ratio": 0.0,
            "threshold": PLACEHOLDER_THRESHOLD,
        }
    else:
        total = len(opcodes)
        placeholders = sum(1 for op in opcodes
                            if isinstance(op, dict) and _is_placeholder(op))
        ratio = placeholders / total
        if ratio <= PLACEHOLDER_THRESHOLD:
            # ratio == 0 — every opcode has a real name.
            verdict = "PASS"
        else:
            verdict = "FAIL"
        report = {
            "gate": GATE, "verdict": verdict,
            "reason": (f"{placeholders}/{total} opcode(s) carry placeholder "
                       f"names (threshold {PLACEHOLDER_THRESHOLD:.0%})."),
            "total": total, "placeholders": placeholders,
            "placeholder_ratio": round(ratio, 4),
            "threshold": PLACEHOLDER_THRESHOLD,
            "placeholder_hexes": [
                op.get("hex") for op in opcodes
                if isinstance(op, dict) and _is_placeholder(op)
            ][:32],
        }

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False)
                        + "\n", encoding="utf-8")

    if verdict == "FAIL":
        print(f"FAIL: {report['reason']}", file=sys.stderr)
        return 1
    if verdict == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {report['reason']}")
        return 0
    print(f"{verdict}: {report['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
