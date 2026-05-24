#!/usr/bin/env python3
"""bitwidth_consistency_check.py — flag Verilog bit-selects that exceed the
register's declared width.

Catches the <chip-class> v042 fresh-agent bug: `reg [4:0] resp_data_idx;` indexed as
`resp_data_idx[6:0]` — a 5-bit register being used as a 7-bit value. Quartus
synthesis does catch this as an elaboration error, but early lint saves a
full compile iteration.

Exit: 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    passed: bool
    findings: List[Finding]
    stats: dict

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "findings": [asdict(f) for f in self.findings],
                "stats": self.stats,
            },
            indent=2,
        )


# Match `reg [HI:LO] name;` or `reg [HI:LO] name = expr;` or `wire [HI:LO] name;`
REG_DECL_RE = re.compile(
    r"\b(?:reg|wire|logic)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(\w+)\s*(?:=|;|,)",
)
# Match `name[HI:LO]` bit-select
BITSELECT_RE = re.compile(r"\b(\w+)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]")


def analyze_file(path: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        findings.append(
            Finding(
                rule="read-error",
                severity="error",
                message=f"Could not read: {e}",
                file=str(path),
            )
        )
        return findings

    # Build symbol table of declared widths
    widths: Dict[str, Tuple[int, int]] = {}  # name -> (hi, lo)
    for m in REG_DECL_RE.finditer(text):
        hi, lo, name = int(m.group(1)), int(m.group(2)), m.group(3)
        widths[name] = (hi, lo)

    # Scan for bit-selects referencing widths larger than declared
    for lineno, line in enumerate(text.splitlines(), start=1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        for m in BITSELECT_RE.finditer(line):
            name, sel_hi, sel_lo = m.group(1), int(m.group(2)), int(m.group(3))
            if name not in widths:
                continue
            decl_hi, decl_lo = widths[name]
            # Both [hi:lo] ordering assumed LSB-first (lo < hi)
            decl_width = abs(decl_hi - decl_lo) + 1
            sel_width = abs(sel_hi - sel_lo) + 1
            if sel_hi > max(decl_hi, decl_lo) or sel_lo < min(decl_hi, decl_lo):
                findings.append(
                    Finding(
                        rule="bitselect-out-of-range",
                        severity="error",
                        message=(
                            f"Register {name!r} declared [{decl_hi}:{decl_lo}] "
                            f"({decl_width}-bit) but indexed as [{sel_hi}:{sel_lo}] "
                            f"({sel_width}-bit). Fix: widen declaration or use "
                            f"concatenation e.g. `{{{sel_width - decl_width}'b0, {name}}}`."
                        ),
                        file=str(path),
                        line=lineno,
                    )
                )

    return findings


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="RTL file(s) or directory")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    files: List[Path] = []
    for p in args.paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend(sorted(pp.rglob("*.v")))
            files.extend(sorted(pp.rglob("*.sv")))
        elif pp.is_file():
            files.append(pp)

    all_findings: List[Finding] = []
    for f in files:
        all_findings.extend(analyze_file(f))

    errors = [f for f in all_findings if f.severity == "error"]
    result = AuditResult(
        passed=(len(errors) == 0),
        findings=all_findings,
        stats={
            "files_scanned": len(files),
            "errors": len(errors),
            "warnings": len(all_findings) - len(errors),
        },
    )

    if args.json:
        print(result.to_json())
    else:
        for f in all_findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity.upper()}] {f.rule}: {f.message} ({loc})")
        print(
            f"\nFiles: {result.stats['files_scanned']}  "
            f"Errors: {result.stats['errors']}  "
            f"Warnings: {result.stats['warnings']}  "
            f"Result: {'PASS' if result.passed else 'FAIL'}"
        )

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
