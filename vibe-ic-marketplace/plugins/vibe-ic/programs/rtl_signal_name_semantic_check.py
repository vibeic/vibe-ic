#!/usr/bin/env python3
"""rtl_signal_name_semantic_check.py — v1.6.232 (merged v229+v231).

Lint user RTL for "the name says X, the value says NOT X" signal
naming traps. The canonical example (which bit BENCH-A v5):

    assign id_bus_oe_low = id_bus_drive_low;

The signal NAME `*_oe_low` implies "active-low output enable"
(=0 means drive). The VALUE `id_bus_drive_low` is active-HIGH
("=1 means drive low"). Any downstream wrapper that reads the
NAME will use the WRONG polarity.

USAGE
-----
    python3 rtl_signal_name_semantic_check.py <rtl_file_or_dir> \\
        [--json <path>] [--fail-on-warn]

EXIT CODES
----------
    0  PASS
    1  FAIL when --fail-on-warn AND any WARN.
    2  IO / argument error.

chip-AGNOSTIC: rules depend only on suffix patterns + RHS tokens,
never on chip-class identifiers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional


# Active-LOW name suffixes (broad set from v231)
_LOW_NAME_SUFFIXES = (
    "_oe_low", "_oe_n",
    "_en_low", "_en_n",
    "_cs_low", "_cs_n",
    "_rst_low", "_rst_n", "_reset_n",
    "_active_low",
)

# RHS tokens implying active-HIGH semantic (extended from v229)
_HIGH_VALUE_TOKEN_PATTERNS = (
    re.compile(r"\b\w*_drive_low\b"),
    re.compile(r"\b\w*_drive_high\b"),
    re.compile(r"\b\w*_drv_low\b"),
    re.compile(r"\b\w*_active_high\b"),
    re.compile(r"\b\w*_enable_high\b"),
    re.compile(r"\b\w*_strobe\b"),
    re.compile(r"\b\w*_assert\b"),
    re.compile(r"\b\w*_pull_low\b"),
)


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    lhs: str
    rhs: str
    message: str


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _has_low_name(lhs: str) -> bool:
    base = lhs.strip().split("[", 1)[0].strip()
    return any(base.endswith(suf) for suf in _LOW_NAME_SUFFIXES)


def _rhs_implies_drive_low(rhs: str) -> Optional[str]:
    """Return matching token if RHS implies active-HIGH semantic."""
    for pat in _HIGH_VALUE_TOKEN_PATTERNS:
        m = pat.search(rhs)
        if m:
            return m.group(0)
    # Also flag literal 1'b1 assigned to active-LOW name
    if re.fullmatch(r"1'b1", rhs.strip()):
        return "1'b1"
    return None


_ASSIGN_RE = re.compile(
    r"(?P<lead>(?:^|;|\bbegin\b|\bend\b))"
    r"\s*(?:assign\s+)?"
    r"(?P<lhs>[A-Za-z_]\w*(?:\s*\[[^\]]+\])?)"
    r"\s*(?P<op>=|<=)\s*"
    r"(?P<rhs>[^;]+);",
    re.MULTILINE,
)


def _iter_assignments(text: str):
    for m in _ASSIGN_RE.finditer(text):
        yield m.start(), m.group("lhs"), m.group("rhs")


def check_file(path: Path) -> List[Finding]:
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return []
    text = _strip_comments(raw)
    findings: List[Finding] = []
    for off, lhs, rhs in _iter_assignments(text):
        lhs_s = lhs.strip()
        rhs_s = rhs.strip()
        if not _has_low_name(lhs_s):
            continue
        token = _rhs_implies_drive_low(rhs_s)
        if token is None:
            continue
        ln = text.count("\n", 0, off) + 1
        # Suggested-fix message format (from v229)
        renamed = (lhs_s.replace("_oe_low", "_drive_low")
                         .replace("_oe_n", "_drive")
                         .replace("_active_low", "_active_high"))
        findings.append(Finding(
            severity="WARN",
            rule="active_low_name_vs_active_high_value",
            file=str(path),
            line=ln,
            lhs=lhs_s,
            rhs=rhs_s[:120],
            message=(
                f"signal {lhs_s!r} is named active-LOW (suffix in "
                f"{_LOW_NAME_SUFFIXES}) but its value contains {token!r}, "
                f"which is active-HIGH by convention. Downstream wrappers "
                f"reading the name will use the WRONG polarity. Either:\n"
                f"  (a) rename lhs to `{renamed}`, OR\n"
                f"  (b) invert: `assign {lhs_s} = ~({rhs_s});`"
            ),
        ))
    return findings


def _iter_rtl_files(target: Path) -> Iterable[Path]:
    if target.is_file():
        yield target
        return
    for ext in ("*.v", "*.sv"):
        yield from sorted(target.rglob(ext))


def audit(target: Path) -> List[Finding]:
    out: List[Finding] = []
    for f in _iter_rtl_files(target):
        out.extend(check_file(f))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Lint RTL for active-low NAME vs active-high VALUE "
                    "polarity mismatches.",
    )
    ap.add_argument("rtl", help="RTL file or directory (recursive .v/.sv)")
    ap.add_argument("--json", default=None,
                    help="Write JSON report; '-' for stdout.")
    ap.add_argument("--fail-on-warn", action="store_true",
                    help="Exit 1 on any WARN (CI mode).")
    args = ap.parse_args(argv)

    target = Path(args.rtl)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target)
    warns = [f for f in findings if f.severity == "WARN"]

    report = {
        "target": str(target),
        "warns": len(warns),
        "findings": [asdict(f) for f in findings],
        "verdict": "WARN" if warns else "PASS",
    }

    if args.json:
        body = json.dumps(report, indent=2)
        if args.json == "-":
            print(body)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: "
                  f"{f.message}")
        print(f"\n{len(warns)} warn(s); verdict: {report['verdict']}")

    if args.fail_on_warn and warns:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
