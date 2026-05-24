#!/usr/bin/env python3
"""analog_pre_vs_post_layout_check.py — deterministic gate for pre/post-layout comparison

Validates that post-layout analog specs don't degrade beyond acceptable
limits compared to pre-layout SPICE results.

For each spec in pre_vs_post.json:
  - ≤20 % degradation → INFO (acceptable)
  - >20 % degradation → WARNING
  - >30 % degradation → ERROR (layout severely impacts performance)

Self-skips (exit 0 + INFO) when:
  - No analog/*/pre_vs_post.json files found

Usage:
    python3 analog_pre_vs_post_layout_check.py <project_dir>
    python3 analog_pre_vs_post_layout_check.py <project_dir> --json reports/gates/pre_vs_post.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (severe degradation)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import _path_layout as _pl


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_pre_vs_post_layout_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR",
            severity="INFO",
            message="No analog/ directory; skipping pre-vs-post layout check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    pvp_files = sorted(analog_dir.glob("*/pre_vs_post.json"))
    if not pvp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_PRE_VS_POST",
            severity="INFO",
            message="No pre_vs_post.json files; post-layout comparison not performed",
        ))
        result.summary = {"skipped": True, "reason": "no_pre_vs_post_data"}
        return result

    total_specs = 0
    errors = 0
    max_degradation = 0.0

    for pvp_path in pvp_files:
        block = pvp_path.parent.name
        try:
            data = json.loads(pvp_path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            result.findings.append(Finding(
                rule="PRE_VS_POST_PARSE_ERROR",
                severity="WARNING",
                message=f"Cannot parse pre_vs_post.json for block '{block}'",
                file=str(pvp_path),
            ))
            continue

        comparisons = data.get("comparisons", data.get("specs", {}))
        if isinstance(comparisons, list):
            comp_iter = comparisons
        elif isinstance(comparisons, dict):
            comp_iter = [{"name": k, **v} for k, v in comparisons.items()]
        else:
            continue

        for item in comp_iter:
            if isinstance(item, dict):
                name = item.get("name", item.get("spec", "?"))
                pre_val = item.get("pre_layout", item.get("pre"))
                post_val = item.get("post_layout", item.get("post"))
            else:
                continue

            if pre_val is None or post_val is None:
                continue
            if not isinstance(pre_val, (int, float)) or not isinstance(post_val, (int, float)):
                continue
            if pre_val == 0:
                continue

            total_specs += 1
            pct = abs(post_val - pre_val) / abs(pre_val) * 100
            max_degradation = max(max_degradation, pct)

            if pct > 30:
                errors += 1
                result.findings.append(Finding(
                    rule="LAYOUT_SEVERE_DEGRADATION",
                    severity="ERROR",
                    message=(
                        f"Block '{block}' spec '{name}': "
                        f"pre={pre_val}, post={post_val} "
                        f"({pct:.1f}% degradation — layout severely impacts performance)"
                    ),
                ))
            elif pct > 20:
                result.findings.append(Finding(
                    rule="LAYOUT_MODERATE_DEGRADATION",
                    severity="WARNING",
                    message=(
                        f"Block '{block}' spec '{name}': "
                        f"pre={pre_val}, post={post_val} "
                        f"({pct:.1f}% degradation)"
                    ),
                ))
            else:
                result.findings.append(Finding(
                    rule="LAYOUT_ACCEPTABLE",
                    severity="INFO",
                    message=(
                        f"Block '{block}' spec '{name}': "
                        f"pre={pre_val}, post={post_val} "
                        f"({pct:.1f}% — acceptable). OK."
                    ),
                ))

    if errors:
        result.passed = False

    result.summary = {
        "skipped": False,
        "blocks_checked": len(pvp_files),
        "specs_compared": total_specs,
        "max_degradation_pct": max_degradation,
        "errors": errors,
        "pass": result.passed,
    }
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    if not args.json:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] analog_pre_vs_post_layout_check")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
