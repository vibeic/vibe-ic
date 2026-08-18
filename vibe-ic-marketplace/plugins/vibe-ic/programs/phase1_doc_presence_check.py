#!/usr/bin/env python3
"""phase1_doc_presence_check.py — Fail if fewer than 10 Phase-1 layer docs exist.

Context: Fresh-agent runs have FAILed on <half-duplex-tester> because the workflow
skipped 6 of 10 Phase-1 doc-gen skills (frs-gen / regmap-gen / adi-spec-gen /
control-logic-gen / test-debug-gen / rtl-constants-gen). The resulting L9 was
produced without L5 (ADI boundary) and L6 (control logic) inputs, so it dropped
required submodules (dclk, drst, pad_ctrl, rx_chk, rx_cmd, dis_cnt, spare,
otp_ctrl, gen_wake). Fresh agent followed the simplified L9 → ASIC-grade clock
management missing → <half-duplex-tester> reject.

This check is a STRUCTURAL GUARDRAIL — it fails loud BEFORE RTL generation if
the Phase-1 doc stack is incomplete, preventing silent regressions of this kind.

Required layer documents (accepts case-insensitive and filename variants):
    L1_DATASHEET       (datasheet-gen output)
    L2_FRS             (frs-gen output)
    L3_CMD_PROTOCOL    (cmd-protocol-gen output)
    L4_REGMAP          (regmap-gen output)
    L5_ADI_SPEC        (adi-spec-gen output)
    L6_CONTROL_LOGIC   (control-logic-gen output)
    L7_TEST_DEBUG      (test-debug-gen output)
    L8_TIMING_WAVEFORM (timing-waveform-gen output)
    L8_RTL_CONSTANTS   (rtl-constants-gen output)
    L9_INTEGRATION_SPEC(integration-spec-gen output)

Usage:
    python3 phase1_doc_presence_check.py generated_docs/
    python3 phase1_doc_presence_check.py --json generated_docs/
    python3 phase1_doc_presence_check.py generated_docs/ --strict

`--strict` (v0.119.40, BACKLOG-v13 Wave 8) — promotes any layer that
the no-protocol sentinel would otherwise demote to severity=info
back to severity=error. Use when the orchestrator demands the full
10/10 stack (e.g. protocol-IC fresh-agent benchmarks). Default
behaviour is unchanged: sentinel-optional layers (L3, L8R) under an
active no-protocol sentinel are reported as `info` and do not fail
the gate.

Exit: 0 = all 10 present, 1 = missing layers.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


REQUIRED_LAYERS = [
    ("L1", r"L1.*(DATASHEET|datasheet)"),
    ("L2", r"L2.*(FRS|frs)"),
    ("L3", r"L3.*(CMD|cmd|PROTOCOL|protocol)"),
    ("L4", r"L4.*(REGMAP|regmap)"),
    ("L5", r"L5.*(ADI|adi)"),
    ("L6", r"L6.*(CONTROL|control)"),
    ("L7", r"L7.*(TEST|test|DEBUG|debug)"),
    ("L8T", r"L8.*(TIMING|timing|WAVEFORM|waveform)"),
    ("L8R", r"L8.*(CONSTANTS|constants|RTL_CONST|rtl_const)"),
    ("L9", r"L9.*(INTEGRATION|integration)"),
]


# Shared sentinel logic — see `_phase1_sentinel.py` for semantics.
sys.path.insert(0, str(Path(__file__).parent))
from _phase1_sentinel import (  # noqa: E402
    SENTINEL_OPTIONAL_LAYERS,
    is_no_protocol_sentinel_active_in_dir,
)


def check(docs_dir: Path, strict: bool = False) -> List[Finding]:
    findings: List[Finding] = []
    if not docs_dir.exists() or not docs_dir.is_dir():
        findings.append(Finding(
            rule="docs-dir-missing", severity="error",
            message=f"generated_docs directory not found: {docs_dir}",
        ))
        return findings

    no_protocol = is_no_protocol_sentinel_active_in_dir(docs_dir)
    files = [f.name for f in docs_dir.iterdir() if f.is_file()]
    for layer_id, pat in REQUIRED_LAYERS:
        regex = re.compile(pat, re.IGNORECASE)
        if any(regex.search(n) for n in files):
            continue
        # Skip presence requirement for sentinel-optional layers (L3/L8R)
        # when the no-protocol sentinel is in effect — UNLESS --strict
        # is set, in which case missing-but-soft items become hard FAIL.
        if layer_id in SENTINEL_OPTIONAL_LAYERS and no_protocol and not strict:
            findings.append(Finding(
                rule=f"skipped-{layer_id}-no-protocol",
                severity="info",
                message=(
                    f"Phase-1 layer {layer_id} skipped: project declares "
                    "the no-protocol sentinel (`protocol_present: false`). "
                    "Memory-access / register-pointer / analog-front-end "
                    "ICs don't need a command protocol or its derived "
                    "RTL constants."
                ),
                file=str(docs_dir),
            ))
            continue
        findings.append(Finding(
            rule=f"missing-{layer_id}",
            severity="error",
            message=(
                f"Required Phase-1 layer {layer_id} document not found in "
                f"{docs_dir}. Run the corresponding skill to generate it. "
                "Known regression root cause: skipping this layer "
                "produces a simplified L9 and <half-duplex-tester>-failing RTL."
            ),
            file=str(docs_dir),
        ))
    return findings


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docs_dir", help="Path to generated_docs/ directory")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON report to stdout")
    ap.add_argument("--json-out", default=None,
                    help="Write JSON report to this path (alternative to --json)")
    ap.add_argument("--strict", action="store_true",
                    help=("Promote sentinel-optional missing layers (L3 / "
                          "L8R when no-protocol sentinel is active) from "
                          "severity=info to severity=error. Default off — "
                          "the no-protocol sentinel still demotes those "
                          "layers. Use --strict for fresh-agent benchmarks "
                          "that demand the full 10/10 stack."))
    args = ap.parse_args(argv)

    findings = check(Path(args.docs_dir), strict=args.strict)
    errors = [f for f in findings if f.severity == "error"]

    report = {
        "passed": len(errors) == 0,
        "findings": [asdict(f) for f in findings],
        "stats": {"missing_layers": len(errors), "required_layers": len(REQUIRED_LAYERS)},
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")
    if args.json:
        print(json.dumps(report, indent=2))
    elif not args.json_out:
        for f in findings:
            print(f"[{f.severity.upper()}] {f.rule}: {f.message}")
        if not errors:
            print(f"\nAll {len(REQUIRED_LAYERS)} Phase-1 layer documents present.  Result: PASS")
        else:
            print(f"\n{len(errors)}/{len(REQUIRED_LAYERS)} required layers MISSING.  Result: FAIL")
            print("Fix: run the corresponding L*-gen skill for each missing layer "
                  "BEFORE running spec-to-rtl. The v041-v043 regression happened "
                  "because this guardrail did not exist.")
    return 0 if len(errors) == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
