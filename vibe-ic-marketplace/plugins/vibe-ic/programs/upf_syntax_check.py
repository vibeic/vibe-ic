#!/usr/bin/env python3
"""
upf_syntax_check.py -- Deterministic UPF file syntax checker.

For skill: upf-author

Verifies that UPF (Unified Power Format) files exist and contain
the minimum required power-intent commands.

Checks:
  1. At least 1 UPF file (*.upf) exists in project_dir
  2. Contains create_power_domain command
  3. Contains at least 1 supply definition (create_supply_net or create_supply_port)
  4. Is not a stub file (< 3 non-empty lines)

Usage:
    python3 upf_syntax_check.py <project_dir>
    python3 upf_syntax_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS (valid UPF found)
    1 = FAIL (no UPF or missing required commands)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
POWER_DOMAIN_RE = re.compile(r"\bcreate_power_domain\b", re.I)
SUPPLY_RE = re.compile(r"\bcreate_supply_net\b|\bcreate_supply_port\b", re.I)


def audit_upf(project_dir: Path) -> AuditResult:
    result = AuditResult(program="upf_syntax_check", passed=False)

    if not project_dir.is_dir():
        result.findings.append(Finding(
            rule="PROJECT_DIR_EXISTS", severity="ERROR",
            message=f"Project directory does not exist: {project_dir}"))
        result.summary = {"files_found": 0, "valid_files": []}
        return result

    # Discover UPF files
    upf_files = list(project_dir.rglob("*.upf"))
    # Also check *.UPF
    upf_files.extend(project_dir.rglob("*.UPF"))

    # Deduplicate
    seen = set()
    unique: List[Path] = []
    for p in upf_files:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    if not unique:
        result.findings.append(Finding(
            rule="UPF_FILE_EXISTS", severity="ERROR",
            message="No UPF file found (searched *.upf)"))
        result.summary = {"files_found": 0, "valid_files": []}
        return result

    result.findings.append(Finding(
        rule="UPF_FILE_EXISTS", severity="INFO",
        message=f"Found {len(unique)} UPF file(s)",
        file=str(unique[0])))

    # Validate each UPF file
    valid_files: List[str] = []
    any_has_domain = False
    any_has_supply = False
    any_not_stub = False

    for fp in unique:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            result.findings.append(Finding(
                rule="UPF_FILE_READABLE", severity="WARNING",
                message=f"Cannot read file: {fp.name}",
                file=str(fp)))
            continue

        # Stub check: count non-empty, non-comment lines
        lines = [l.strip() for l in text.split("\n")
                 if l.strip() and not l.strip().startswith("#")]
        if len(lines) < 3:
            result.findings.append(Finding(
                rule="UPF_NOT_STUB", severity="WARNING",
                message=f"UPF file appears to be a stub ({len(lines)} content lines): {fp.name}",
                file=str(fp)))
            continue
        any_not_stub = True

        has_domain = bool(POWER_DOMAIN_RE.search(text))
        has_supply = bool(SUPPLY_RE.search(text))

        if not has_domain:
            result.findings.append(Finding(
                rule="UPF_HAS_POWER_DOMAIN", severity="ERROR",
                message=f"No create_power_domain command in {fp.name}",
                file=str(fp)))
        else:
            any_has_domain = True

        if not has_supply:
            result.findings.append(Finding(
                rule="UPF_HAS_SUPPLY", severity="ERROR",
                message=f"No create_supply_net/create_supply_port in {fp.name}",
                file=str(fp)))
        else:
            any_has_supply = True

        if has_domain and has_supply:
            valid_files.append(fp.name)

    if not any_not_stub:
        result.findings.append(Finding(
            rule="UPF_NOT_STUB", severity="ERROR",
            message="All UPF files are stubs (< 3 content lines)"))

    result.passed = any_has_domain and any_has_supply and any_not_stub
    result.summary = {
        "files_found": len(unique),
        "valid_files": valid_files,
        "has_power_domain": any_has_domain,
        "has_supply_def": any_has_supply,
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="UPF file syntax checker")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    result = audit_upf(Path(args.project_dir))

    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
