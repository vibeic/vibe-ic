#!/usr/bin/env python3
"""otp_image_layer_consistency_check.py — P1.3 deterministic gate

Static check: compares OTP / ROM initial values baked into RTL
(mem[X] = 8'hYY assignments or .mem/.hex init files) against the
address map declared in L11_OTP_CONTENT.json.

Catches hex/decimal transcription errors (e.g. agent writes 0x0A
when spec says 0x10) that pass all structural gates but produce
wrong byte-stream on hardware.

Per-line ``// otp-test-override`` annotation suppresses individual
mismatches (for dev/test images that intentionally diverge).

Usage:
    python3 otp_image_layer_consistency_check.py <project_dir>
    python3 otp_image_layer_consistency_check.py <project_dir> --json [PATH]
    python3 otp_image_layer_consistency_check.py <project_dir> --l11-json L11.json

Exit codes:
    0 = PASS: an L11 address map and RTL/hex initialisers were both found and
        every declared address matches
    1 = FAIL (one or more mismatches)
    2 = VACUOUS: nothing was examined — no L11_OTP_CONTENT.json (or it
        declares no address), or no OTP/ROM initialiser in the RTL, so no
        address was ever compared. #521: both used to be rc 0, on 200 of the
        200 tracked project roots. Also rc 2 for an IO / parse error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional
import _path_layout as _pl
import _vacuous_exit as _vx

MEM_INIT_RE = re.compile(
    r"mem\s*\[\s*(?:\d+'[hHdDbB])?\s*([0-9a-fA-F]+)\s*\]\s*"
    r"(?:=|<=)\s*(?:\d+'[hH])\s*([0-9a-fA-F]+)",
)

OVERRIDE_MARKER = "otp-test-override"


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "otp_image_layer_consistency_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def discover_rtl_files(base: Path) -> List[Path]:
    exts = {".v", ".sv", ".vh", ".svh"}
    return sorted(p for p in base.rglob("*") if p.suffix.lower() in exts)


def _load_l11(project_dir: Path, l11_path: Optional[Path]) -> Optional[Dict[int, int]]:
    candidates: list[Path] = []
    if l11_path and l11_path.is_file():
        candidates.append(l11_path)
    gen = _pl.generated_docs_dir(project_dir)
    if gen.is_dir():
        candidates.extend(sorted(gen.glob("L11_*.json")))
    for p in candidates:
        try:
            data = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        addr_map = data.get("address_map") or data.get("otp_map") or data.get("entries")
        if not isinstance(addr_map, list):
            continue
        result: Dict[int, int] = {}
        for entry in addr_map:
            addr_raw = entry.get("address") or entry.get("addr") or entry.get("offset")
            val_raw = entry.get("value") or entry.get("decoded_hex") or entry.get("hex")
            if addr_raw is None or val_raw is None:
                continue
            try:
                addr = int(str(addr_raw), 0)
            except (ValueError, TypeError):
                continue
            try:
                val = int(str(val_raw), 0)
            except (ValueError, TypeError):
                try:
                    val = int(str(val_raw), 16)
                except (ValueError, TypeError):
                    continue
            result[addr] = val & 0xFF
        if result:
            return result
    return None


def _parse_rtl_mem_inits(rtl_files: List[Path]) -> Dict[int, dict]:
    inits: Dict[int, dict] = {}
    for fpath in rtl_files:
        fname = fpath.name.lower()
        if not any(k in fname for k in ("otp", "rom", "mem", "nvm", "fuse")):
            continue
        try:
            lines = fpath.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            m = MEM_INIT_RE.search(line)
            if m:
                addr = int(m.group(1), 16)
                val = int(m.group(2), 16) & 0xFF
                overridden = OVERRIDE_MARKER in line
                inits[addr] = {
                    "value": val,
                    "file": str(fpath),
                    "line": i,
                    "overridden": overridden,
                }
    return inits


def _parse_hex_files(project_dir: Path) -> Dict[int, dict]:
    inits: Dict[int, dict] = {}
    for pattern in ("phase2/stage1/rtl/*.hex", "phase2/stage1/rtl/*.mem", "*.hex", "*.mem"):
        for fpath in project_dir.glob(pattern):
            fname = fpath.name.lower()
            if not any(k in fname for k in ("otp", "rom", "mem", "nvm", "fuse", "image")):
                continue
            try:
                lines = fpath.read_text(errors="replace").splitlines()
            except Exception:
                continue
            addr = 0
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                    continue
                try:
                    val = int(stripped, 16) & 0xFF
                    inits[addr] = {
                        "value": val,
                        "file": str(fpath),
                        "line": i,
                        "overridden": False,
                    }
                    addr += 1
                except ValueError:
                    for tok in stripped.split():
                        try:
                            val = int(tok, 16) & 0xFF
                            inits[addr] = {
                                "value": val,
                                "file": str(fpath),
                                "line": i,
                                "overridden": False,
                            }
                            addr += 1
                        except ValueError:
                            pass
    return inits


def run_audit(project_dir: Path, l11_path: Optional[Path] = None) -> AuditResult:
    result = AuditResult()

    l11_map = _load_l11(project_dir, l11_path)
    if l11_map is None:
        result.findings.append(Finding(
            rule="SKIP_NO_L11",
            severity="INFO",
            message="No L11_OTP_CONTENT.json found or no address_map entries; skipping.",
        ))
        result.summary = {"skipped": True, "reason": "no_l11"}
        return result

    rtl_dir = _pl.rtl_dir(project_dir)
    base = rtl_dir if rtl_dir.is_dir() else project_dir
    rtl_files = discover_rtl_files(base)
    rtl_inits = _parse_rtl_mem_inits(rtl_files)

    hex_inits = _parse_hex_files(project_dir)
    for addr, info in hex_inits.items():
        if addr not in rtl_inits:
            rtl_inits[addr] = info

    if not rtl_inits:
        result.findings.append(Finding(
            rule="SKIP_NO_OTP_MODULE",
            severity="INFO",
            message="No OTP/ROM mem init patterns found in RTL; skipping.",
        ))
        result.summary = {"skipped": True, "reason": "no_otp_module"}
        return result

    matches = 0
    mismatches = 0
    missing = 0
    overridden = 0

    for addr, expected_val in sorted(l11_map.items()):
        if addr not in rtl_inits:
            missing += 1
            result.passed = False
            result.findings.append(Finding(
                rule="OTP_VALUE_MISMATCH",
                severity="ERROR",
                message=(
                    f"L11 address 0x{addr:02X} expects 0x{expected_val:02X} "
                    f"but no mem init found in RTL for this address."
                ),
            ))
            continue

        info = rtl_inits[addr]
        actual_val = info["value"]

        if info["overridden"]:
            overridden += 1
            result.findings.append(Finding(
                rule="OTP_MATCH_OK",
                severity="INFO",
                message=(
                    f"Address 0x{addr:02X}: mismatch suppressed by otp-test-override "
                    f"(L11=0x{expected_val:02X}, RTL=0x{actual_val:02X})"
                ),
                file=info["file"],
                line=info["line"],
            ))
            continue

        if actual_val != expected_val:
            mismatches += 1
            result.passed = False
            result.findings.append(Finding(
                rule="OTP_VALUE_MISMATCH",
                severity="ERROR",
                message=(
                    f"Address 0x{addr:02X}: L11 expects 0x{expected_val:02X}, "
                    f"RTL has 0x{actual_val:02X}. "
                    f"Add '// otp-test-override' to suppress if intentional."
                ),
                file=info["file"],
                line=info["line"],
            ))
        else:
            matches += 1
            result.findings.append(Finding(
                rule="OTP_MATCH_OK",
                severity="INFO",
                message=f"Address 0x{addr:02X}: 0x{expected_val:02X} matches RTL.",
                file=info["file"],
                line=info["line"],
            ))

    result.summary = {
        "l11_addresses": len(l11_map),
        "rtl_inits": len(rtl_inits),
        "matches": matches,
        "mismatches": mismatches,
        "missing_in_rtl": missing,
        "overridden": overridden,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    ap.add_argument("--l11-json", type=Path, default=None)
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir, l11_path=args.l11_json)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    if args.json is not None:
        out = asdict(result)
        txt = json.dumps(out, indent=2)
        if args.json == "-":
            print(txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(txt + "\n")
    else:
        print(_vx.verdict_line("otp_image_layer_consistency_check",
                               result.passed, skipped, reason))
        s = result.summary
        print(f"  L11 addresses: {s.get('l11_addresses', 0)}")
        print(f"  RTL inits found: {s.get('rtl_inits', 0)}")
        print(f"  Matches: {s.get('matches', 0)}")
        print(f"  Mismatches: {s.get('mismatches', 0)}")
        print(f"  Missing in RTL: {s.get('missing_in_rtl', 0)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                loc = f"{f.file}:{f.line}" if f.file else ""
                print(f"  [{f.severity}] {f.rule}: {f.message} {loc}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
