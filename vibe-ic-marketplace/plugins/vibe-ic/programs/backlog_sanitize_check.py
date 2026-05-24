#!/usr/bin/env python3
"""
backlog_sanitize_check.py — Organic Plugin gate: verify that a community
backlog submission is IC-agnostic and contains no vendor/confidential data.

General pattern:

    Vibe-IC is an Organic Plugin — community agents contribute backlogs
    that describe general capability gaps.  Every submission MUST be
    IC-agnostic: no chip names, vendor names, proprietary protocol
    details, confidential OTP content, or tester-specific command bytes.

    This gate scans all text fields of a YAML backlog file against a
    catalogue of HARD (reject) and SOFT (warn) patterns, reusing the
    same rule set as ``practical_notes_specificity_check.py``.

Usage:
    python3 backlog_sanitize_check.py --file <backlog.yaml> [--json <report.json>]
    python3 backlog_sanitize_check.py --dir <backlogs_dir> [--json <report.json>]

Exit: 0 = PASS (clean), 1 = FAIL (specificity violations found), 2 = IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    field: str = ""
    line: int = 0
    matched: str = ""


HARD_RULES: List[Tuple[str, str, str]] = [
    ("chip_name",
     r"\bEXAMPLE_CHIP\b|\bBENCHMARK_A\b|\bSC16IS750\b|\bLM75\b|\bDS1307\b"
     r"|\bPCA9685\b|\bTCA9534\b|\bMCP4725\b|\b24LC256\b|\bBME280\b",
     "Chip/IC product name — describe the IC class instead"),
    ("vendor_name",
     r"\bApple\b|\bMaxim\b|\bTexas Instruments\b|\bAnalog Devices\b"
     r"|\bMicrochip\b|\bNXP\b|\bSTMicro\b|\bInfineon\b|\bBosch\b",
     "Vendor company name — describe the protocol or IC class instead"),
    ("vendor_product",
     r"\bLightning\b|\bThunderbolt\b|\bMFi\b",
     "Vendor product/certification name"),
    ("tester_sku",
     r"MD[-_ ]?905\b|\bDE10[-_ ]?Lite\b|\bKeysight\b",
     "Test equipment SKU — describe the test methodology instead"),
    ("otp_content",
     r"(?:0x[0-9A-Fa-f]{2}\s*,?\s*){8,}",
     "Raw OTP/hex dump (≥8 bytes) — likely confidential content"),
    ("vendor_pdf",
     r"\b[A-Z][A-Za-z0-9_-]*\.(pdf|PDF)\b",
     "Vendor document filename — describe the information, not the source"),
    ("pdk_codename",
     r"\bm18e80(pm180su)?\b|\bHP18E80\b",
     "PDK/process codename specific to one project"),
    ("hid_cmd_byte",
     r"0x[0-9A-Fa-f]{2}\s*(?://|#)?\s*CMD_[A-Z_]+",
     "Hard-coded tester command byte — describe the test action instead"),
    ("pass_marker",
     r"\bbyte\s*\[\s*\d+\s*\]\s*=\s*0x[0-9A-Fa-f]+\b",
     "Tester-specific PASS/FAIL byte marker"),
    ("project_version",
     r"\bv0[5-9]\d\b(?!\.\d)",
     "Project iteration codename (v052/v068/...) — use 'prior version' instead"),
    ("chip_pin_name",
     r"\bACC_ID\b|\bPIN_V[0-9]+\b|\bPIN_W[0-9]+\b",
     "Chip-specific pin name"),
    ("register_address",
     r"\b(?:reg|register)\s*(?:0x[0-9A-Fa-f]{1,4}|addr\s*=\s*0x[0-9A-Fa-f]{1,4})",
     "Specific register address from a proprietary register map"),
    ("dated_validation",
     r"validated.*\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}\s+(MD-?905|DE10)",
     "Dated test-rig validation stamp"),
    ("file_path_leak",
     r"/home/\w+/|/Users/\w+/|C:\\Users\\",
     "Local file path leaks user/project structure"),
]

SOFT_RULES: List[Tuple[str, str, str]] = [
    ("provenance_chip",
     r"(real bug|known incident|observed in|debug session)\s+"
     r"(from|of|on)\s+\w+",
     "Provenance line may reference a specific chip — verify it's generalized"),
    ("specific_timing",
     r"\b\d+\s*[uµn]s\b",
     "Specific timing value — ensure it describes a general constraint, not one IC's spec"),
    ("specific_frequency",
     r"\b\d+(\.\d+)?\s*(MHz|kHz|GHz)\b",
     "Specific frequency — ensure it's a general protocol requirement, not one IC's clock"),
]

REQUIRED_FIELDS = ["type", "component", "title", "pattern", "plugin_version"]
VALID_TYPES = {"bug", "issue", "enhancement"}
COMPONENT_RE = re.compile(
    r"^(skill|program|mcp|flow):[\w_-]+$", re.IGNORECASE
)


def _parse_yaml(path: Path) -> Dict:
    text = path.read_text(errors="replace")
    if HAS_YAML:
        return yaml.safe_load(text) or {}
    result = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val and not val.startswith('|') and not val.startswith('>'):
                result[key] = val
    if not result:
        result["_raw"] = text
    return result


def _check_text(text: str, fname: str, field: str) -> List[Finding]:
    findings = []
    for rule_id, pattern, desc in HARD_RULES:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            findings.append(Finding(
                "ERROR", rule_id, desc,
                file=fname, field=field, matched=m.group(),
            ))
    for rule_id, pattern, desc in SOFT_RULES:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            findings.append(Finding(
                "WARN", rule_id, desc,
                file=fname, field=field, matched=m.group(),
            ))
    return findings


def _check_structure(data: Dict, fname: str) -> List[Finding]:
    findings = []
    for field in REQUIRED_FIELDS:
        val = data.get(field, "")
        if not val or val == '""' or val.startswith("<"):
            findings.append(Finding(
                "ERROR", "MISSING_FIELD",
                f"Required field '{field}' is missing or empty",
                file=fname, field=field,
            ))

    btype = data.get("type", "")
    if btype and btype not in VALID_TYPES:
        findings.append(Finding(
            "ERROR", "INVALID_TYPE",
            f"type must be one of {VALID_TYPES}, got '{btype}'",
            file=fname, field="type",
        ))

    component = data.get("component", "")
    if component and not COMPONENT_RE.match(component):
        findings.append(Finding(
            "ERROR", "INVALID_COMPONENT",
            f"component must match 'skill:<name>' | 'program:<name>' | "
            f"'mcp:<tool>' | 'flow:<step>', got '{component}'",
            file=fname, field="component",
        ))

    return findings


def audit_file(path: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    fname = str(path)

    try:
        data = _parse_yaml(path)
    except Exception as e:
        findings.append(Finding(
            "ERROR", "PARSE_ERROR", f"Cannot parse YAML: {e}", file=fname
        ))
        return findings, {}

    findings.extend(_check_structure(data, fname))

    text_fields = ["title", "pattern", "suggested_fix",
                    "steps_to_reproduce", "gate_output",
                    "session_context", "_raw"]
    for field in text_fields:
        val = data.get(field, "")
        if isinstance(val, str) and val:
            findings.extend(_check_text(val, fname, field))

    return findings, {
        "file": fname,
        "type": data.get("type", ""),
        "component": data.get("component", ""),
        "title": data.get("title", ""),
    }


def audit(paths: List[Path]) -> Tuple[List[Finding], Dict]:
    all_findings: List[Finding] = []
    summaries = []

    for p in paths:
        findings, summary = audit_file(p)
        all_findings.extend(findings)
        summaries.append(summary)

    return all_findings, {
        "files_checked": len(paths),
        "files": summaries,
        "hard_violations": sum(1 for f in all_findings if f.severity == "ERROR"),
        "soft_warnings": sum(1 for f in all_findings if f.severity == "WARN"),
    }


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify community backlog submissions are IC-agnostic "
                    "and contain no vendor/confidential data."
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--file", dest="file_path", help="Single YAML backlog file")
    grp.add_argument("--dir", dest="dir_path", help="Directory of YAML backlog files")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Treat SOFT warnings as errors")
    args = ap.parse_args(argv)

    paths: List[Path] = []
    if args.file_path:
        p = Path(args.file_path)
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            return 2
        paths = [p]
    else:
        d = Path(args.dir_path)
        if not d.exists():
            print(f"ERROR: directory not found: {d}", file=sys.stderr)
            return 2
        paths = sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))
        if not paths:
            print(json.dumps({"program": "backlog_sanitize_check",
                              "summary": {"pass": True, "files_checked": 0,
                                          "note": "no YAML files found"}}))
            return 0

    try:
        findings, summary = audit(paths)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.strict:
        is_pass = len(findings) == 0
    else:
        is_pass = not any(f.severity == "ERROR" for f in findings)

    report = {
        "program": "backlog_sanitize_check",
        "version": "1.0.0",
        "summary": {"pass": is_pass, "findings_count": len(findings), **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(out)
    print(out)
    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
