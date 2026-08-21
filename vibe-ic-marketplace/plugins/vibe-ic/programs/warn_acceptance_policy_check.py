#!/usr/bin/env python3
"""
warn_acceptance_policy_check.py — O3: Enforce that every WARN finding from
gate programs is explicitly addressed before the flow can declare PASS.

General pattern (IC-agnostic):

    After all gate programs run, their JSON reports may contain findings
    with severity "WARN".  A WARN that is not acted on is the single most
    common failure mode in fresh-agent flows — the agent sees the advisory,
    treats it as PASS, and ships.

    This gate scans the project's reports directory for all JSON gate
    outputs, collects every WARN finding, and checks that each is paired
    with ONE of:

    1. Silence comment — an inline RTL comment matching the gate's
       documented silence pattern (e.g. ``// crc-isolation-ok``,
       ``// single-clear-path-ok``).  Checked at ±5 lines of the
       referenced file:line.
    2. Acceptance log entry — a row in ``WARN_ACCEPTANCE_LOG.md`` with
       matching gate + file + rule columns.

    If any WARN lacks both, the overall verdict is WARN_PRESENT (not PASS).
    With --threshold N, exceeding N unaddressed WARNs escalates to FAIL.

Usage:
    python3 warn_acceptance_policy_check.py --project-dir <dir> [--reports-dir <dir>] [--json <report.json>] [--threshold N]

Exit codes:
    0 = PASS: gate reports were read and every WARN in them is addressed
    1 = WARN_PRESENT or FAIL
    2 = VACUOUS: nothing was examined — the project has no reports directory,
        so not a single gate report was read and "every WARN is addressed" is
        true only because no WARN was ever loaded. #521: this used to be
        rc 0. It was one of three leads #515 could not reproduce, because a
        probe that passes a bare project directory is rejected by this gate's
        argparse (it takes `--project-dir`). Driven through its documented
        interface it reproduces on a tracked project root. Also rc 2 for an
        IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import _vacuous_exit as _vx


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    details: str = ""


def _load_gate_reports(reports_dir: Path) -> List[Dict]:
    warns: List[Dict] = []
    for f in sorted(reports_dir.rglob("*.json")):
        try:
            data = json.loads(f.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        program = data.get("program", f.stem)
        for finding in data.get("findings", []):
            if not isinstance(finding, dict):
                continue
            if finding.get("severity") == "WARN":
                warns.append({
                    "program": program,
                    "category": finding.get("category", ""),
                    "file": finding.get("file", ""),
                    "line": finding.get("line", 0),
                    "message": finding.get("message", ""),
                    "source_report": str(f),
                })
    return warns


def _check_silence_comment(warn: Dict, project_dir: Path) -> bool:
    fpath = Path(warn["file"])
    if not fpath.is_absolute():
        fpath = project_dir / fpath
    if not fpath.exists():
        return False
    try:
        lines = fpath.read_text(errors="replace").split('\n')
    except OSError:
        return False

    category = warn["category"].lower().replace("_", "-")
    silence_re = re.compile(rf'//\s*{re.escape(category)}-ok', re.IGNORECASE)

    target_line = warn["line"]
    start = max(0, target_line - 6)
    end = min(len(lines), target_line + 5)
    for line in lines[start:end]:
        if silence_re.search(line):
            return True
    return False


def _check_acceptance_log(warn: Dict, project_dir: Path) -> bool:
    log_path = project_dir / "WARN_ACCEPTANCE_LOG.md"
    if not log_path.exists():
        return False
    try:
        content = log_path.read_text(errors="replace")
    except OSError:
        return False

    for line in content.split('\n'):
        if '|' not in line:
            continue
        cells = [c.strip() for c in line.split('|')]
        if len(cells) < 5:
            continue
        gate_col = cells[1] if len(cells) > 1 else ""
        rule_col = cells[3] if len(cells) > 3 else ""
        if warn["program"] in gate_col and warn["category"] in rule_col:
            return True
    return False


def audit(
    project_dir: Path,
    reports_dir: Optional[Path] = None,
) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []

    if reports_dir is None:
        reports_dir = project_dir / "reports"

    if not reports_dir.exists():
        return findings, {
            "skipped": True,
            "reason": "No reports directory found",
        }

    warns = _load_gate_reports(reports_dir)

    if not warns:
        return findings, {
            "total_warns": 0,
            "unaddressed": 0,
            "addressed": 0,
        }

    addressed: List[Dict] = []
    unaddressed: List[Dict] = []

    for w in warns:
        silenced = _check_silence_comment(w, project_dir)
        accepted = _check_acceptance_log(w, project_dir)

        if silenced or accepted:
            resolution = "silence_comment" if silenced else "acceptance_log"
            addressed.append({**w, "resolution": resolution})
        else:
            unaddressed.append(w)
            findings.append(Finding(
                "WARN", "UNADDRESSED_WARN",
                f"WARN from {w['program']}/{w['category']} at "
                f"{w['file']}:{w['line']} has no silence comment "
                f"or WARN_ACCEPTANCE_LOG.md entry. Address the "
                f"finding or document acceptance before declaring done.",
                file=w["file"],
                line=w["line"],
                details=w["message"],
            ))

    return findings, {
        "total_warns": len(warns),
        "unaddressed": len(unaddressed),
        "addressed": len(addressed),
        "unaddressed_details": unaddressed,
        "addressed_details": addressed,
    }


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Enforce that every WARN finding from gate programs "
                    "is explicitly addressed (silence comment or "
                    "WARN_ACCEPTANCE_LOG.md entry)."
    )
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--reports-dir", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument(
        "--threshold", type=int, default=0,
        help="Max unaddressed WARNs before verdict becomes FAIL "
             "(0 = any unaddressed → WARN_PRESENT, not FAIL)",
    )
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    reports_dir = Path(args.reports_dir) if args.reports_dir else None

    try:
        findings, summary = audit(project_dir, reports_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    unaddressed_count = summary.get("unaddressed", 0)
    threshold = args.threshold

    if unaddressed_count == 0:
        verdict = "PASS"
    elif threshold > 0 and unaddressed_count > threshold:
        verdict = "FAIL"
    else:
        verdict = "WARN_PRESENT"

    is_pass = verdict == "PASS"
    report = {
        "program": "warn_acceptance_policy_check",
        "version": "1.0.0",
        "project_dir": str(project_dir),
        "summary": {
            "pass": is_pass,
            "verdict": verdict,
            "findings_count": len(findings),
            **summary,
        },
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(out)
    print(out)
    # #521 — routed from the gate's OWN `skipped` flag, never from the report
    # text (which is printed to STDOUT here, so the sentinel goes to stderr to
    # keep that document parseable).
    skipped = _vx.summary_is_skipped(report["summary"])
    if is_pass and skipped:
        _vx.announce_vacuous("warn_acceptance_policy_check",
                             _vx.skip_reason(report["summary"]))
    return _vx.exit_code(is_pass, skipped)


if __name__ == "__main__":
    sys.exit(main())
