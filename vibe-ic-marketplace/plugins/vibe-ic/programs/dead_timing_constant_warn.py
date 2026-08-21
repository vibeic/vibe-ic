#!/usr/bin/env python3
"""dead_timing_constant_warn.py — R4 cheap WARN gate

Scan all RTL files for `define macros and localparam declarations whose
identifier matches a configurable timing-constant naming convention.
For each, count references across all other RTL files. If 0 references
outside the declaration line → WARN, escalates to ERROR via O3 unless
silenced.

Default naming regex: /^T_[A-Z0-9_]+_(CYC|TICKS|NS|US|MS)$/
Project can override via --regex flag or a .timing_constant_regex file.

Confidence on bus turnaround bug class: ~30% standalone, but composes
well with R1 — catches ANY unused timing constant, not just turnaround.

Usage:
    python3 dead_timing_constant_warn.py <project_dir>
    python3 dead_timing_constant_warn.py <project_dir> --json
    python3 dead_timing_constant_warn.py <project_dir> --regex '^CLK_.*_CYC$'

Exit codes:
    0 = no dead timing constants
    1 = one or more dead timing constants (WARNING-level)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# Kimi-scale fix — this WARN-tier gate audits AUTHORED RTL SOURCE. Collection
# routes through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the per-constant reference scan again
# (see _specrtl_common.rtl_source_files for the full scale rationale). The
# .timing_constant_regex config read and the --regex override are untouched.
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files

DEFAULT_TIMING_REGEX = r"^T_[A-Z0-9_]+_(CYC|TICKS|NS|US|MS)$"

DEFINE_RE = re.compile(r"^\s*`define\s+(\w+)")
LOCALPARAM_RE = re.compile(r"\blocalparam\b.*?\b(\w+)\s*=")
PARAMETER_RE = re.compile(r"\bparameter\b.*?\b(\w+)\s*=")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "dead_timing_constant_warn"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def discover_rtl_files(base: Path) -> List[Path]:
    # Kimi-scale fix: shared authored-RTL collector. This gate has always
    # also scanned *.vh/*.svh headers (`define/localparam timing constants
    # live there), so the suffix set is widened accordingly.
    return rtl_source_files(base, exts=("*.v", "*.sv", "*.vh", "*.svh"))


def load_custom_regex(base: Path) -> Optional[str]:
    cfg = base / ".timing_constant_regex"
    if cfg.exists():
        return cfg.read_text().strip()
    return None


def extract_timing_decls(rtl_files: List[Path], pattern: re.Pattern) -> List[dict]:
    decls = []
    for fpath in rtl_files:
        try:
            lines = fpath.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            for regex in (DEFINE_RE, LOCALPARAM_RE, PARAMETER_RE):
                m = regex.search(line)
                if m:
                    name = m.group(1)
                    if pattern.match(name):
                        decls.append({
                            "name": name,
                            "file": str(fpath),
                            "line": i,
                            "raw": line.strip(),
                        })
    return decls


def count_references(name: str, rtl_files: List[Path], decl_file: str, decl_line: int) -> int:
    word_re = re.compile(r"\b" + re.escape(name) + r"\b")
    refs = 0
    for fpath in rtl_files:
        try:
            lines = fpath.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            if str(fpath) == decl_file and i == decl_line:
                continue
            if word_re.search(line):
                refs += 1
    return refs


def run_audit(base: Path, regex_str: Optional[str] = None) -> AuditResult:
    result = AuditResult()
    rtl_files = discover_rtl_files(base)

    if not rtl_files:
        result.findings.append(Finding(
            rule="NO_RTL_FILES",
            severity="INFO",
            message="No RTL files found; skipping dead timing constant check",
        ))
        result.summary = {"rtl_files": 0, "timing_constants": 0, "dead": 0}
        return result

    if regex_str is None:
        regex_str = load_custom_regex(base) or DEFAULT_TIMING_REGEX

    try:
        pattern = re.compile(regex_str)
    except re.error as e:
        result.passed = False
        result.findings.append(Finding(
            rule="BAD_REGEX",
            severity="ERROR",
            message=f"Invalid timing constant regex: {e}",
        ))
        return result

    decls = extract_timing_decls(rtl_files, pattern)
    dead_count = 0

    for d in decls:
        refs = count_references(d["name"], rtl_files, d["file"], d["line"])
        if refs == 0:
            dead_count += 1
            result.findings.append(Finding(
                rule="DEAD_TIMING_CONSTANT",
                severity="WARNING",
                message=(
                    f"Timing constant '{d['name']}' defined but referenced 0 times. "
                    f"Either consume it in RTL or remove it to avoid spec-drift."
                ),
                file=d["file"],
                line=d["line"],
            ))
        else:
            result.findings.append(Finding(
                rule="TIMING_CONSTANT_OK",
                severity="INFO",
                message=f"Timing constant '{d['name']}' referenced {refs} time(s)",
                file=d["file"],
                line=d["line"],
            ))

    if dead_count > 0:
        result.passed = False

    result.summary = {
        "rtl_files": len(rtl_files),
        "timing_constants": len(decls),
        "dead": dead_count,
        "regex": regex_str,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--regex", type=str, default=None,
                    help="Override timing constant regex (default: T_*_(CYC|TICKS|NS|US|MS))")
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir, args.regex)

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        status = "PASS" if result.passed else "WARN"
        print(f"[{status}] dead_timing_constant_warn")
        print(f"  RTL files: {result.summary.get('rtl_files', 0)}")
        print(f"  Timing constants: {result.summary.get('timing_constants', 0)}")
        print(f"  Dead: {result.summary.get('dead', 0)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                loc = f"{f.file}:{f.line}" if f.file else ""
                print(f"  [{f.severity}] {f.rule}: {f.message} {loc}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
