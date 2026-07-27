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


# ── accepted pre_vs_post.json schema ──────────────────────────────────────
# Single source of truth for the key names, mirrored in
# `skills/analog-extraction-resim/SKILL.md`. The two drifted once (the skill
# documented "comparison", singular; this gate has only ever read
# "comparisons"/"specs"), which made a result authored exactly per the skill's
# own example FAIL as if it contained no data.
_CONTAINER_KEYS: tuple = ("comparisons", "specs")
_PRE_KEYS: tuple = ("pre_layout", "pre")
_POST_KEYS: tuple = ("post_layout", "post")


def _first_key(item: dict, keys: tuple):
    for k in keys:
        if k in item:
            return item[k]
    return None


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
    # Blocks whose pre_vs_post.json parsed as JSON but exposed NO container
    # under a key this gate reads. Kept so the zero-compared verdict can name
    # the cause (schema drift) instead of implying the file held no data.
    unreadable_schema: List[str] = []

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

        # ONLY these container keys are read. `skills/analog-extraction-resim`
        # documents the same list; when they drift, a spec-compliant result is
        # scored as zero comparisons, so the drift is named explicitly below
        # rather than surfacing as a bare "no numeric pre/post pairs".
        container_key = next(
            (k for k in _CONTAINER_KEYS if isinstance(data, dict) and k in data),
            None)
        comparisons = data.get(container_key) if container_key else None
        if isinstance(comparisons, list):
            comp_iter = comparisons
        elif isinstance(comparisons, dict):
            comp_iter = [{"name": k, **v} for k, v in comparisons.items()]
        else:
            if isinstance(data, dict):
                unreadable_schema.append(
                    f"{block}: top-level keys "
                    f"{sorted(str(k) for k in data)} — none of "
                    f"{list(_CONTAINER_KEYS)} present")
            continue

        for item in comp_iter:
            if isinstance(item, dict):
                name = item.get("name", item.get("spec", "?"))
                pre_val = _first_key(item, _PRE_KEYS)
                post_val = _first_key(item, _POST_KEYS)
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

    # ORGANIC-20260606 #438(c): pre_vs_post.json existed (past the
    # self-skip) but zero numeric pre/post pairs were comparable — a
    # comparison gate must FAIL, never PASS, with items_compared==0.
    if total_specs == 0:
        result.passed = False
        detail = ""
        if unreadable_schema:
            # Name the schema drift. Without this the message read as "the
            # file holds no data", which sent readers looking at the SPICE
            # run when the real cause was a container key this gate does not
            # read (measured: SKILL.md documented "comparison", singular).
            detail = (" — SCHEMA: " + "; ".join(unreadable_schema)
                      + f". Recognised container keys: {list(_CONTAINER_KEYS)};"
                        f" per-item value keys: {list(_PRE_KEYS)} /"
                        f" {list(_POST_KEYS)}")
        result.findings.append(Finding(
            rule="PRE_VS_POST_ZERO_COMPARED",
            severity="ERROR",
            message=("pre_vs_post.json present but 0 specs were "
                     "compared (no numeric pre/post pairs) — a "
                     "comparison gate must FAIL (or self-skip), never "
                     "PASS, with items_compared==0 (#438c)" + detail),
        ))

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
