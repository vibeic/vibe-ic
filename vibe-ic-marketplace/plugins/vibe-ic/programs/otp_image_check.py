#!/usr/bin/env python3
"""
otp_image_check.py — Validate an OTP/NVM .ver image against an L4 register map.

What it catches
---------------
  1. FILE_MISSING        — .ver or L4 JSON path does not exist
  2. SIZE_MISMATCH       — bytes in .ver exceed L4's otp_size_bytes
  3. ADDRESS_OUT_OF_RANGE — any @<addr> is >= otp_size_bytes
  4. DUPLICATE_ADDRESS   — same address written twice
  5. BYTE_OUT_OF_RANGE   — a value is outside 0..255
  6. FIELD_COVERAGE      — an L4 field marked required=true has no bytes written
  7. MALFORMED_LINE      — a non-comment, non-empty line fails the @addr byte pattern
  8. OTP_SIZE_UNDETERMINED — neither L4 nor L11 declares OTP size (Wave 73 / v0.128 S2)

Usage
-----
    python3 otp_image_check.py --regmap generated_docs/L4_REGMAP.json path/to/image.ver
    python3 otp_image_check.py --regmap L4.json --json image.ver

Exit codes
----------
    0 — image is structurally valid against L4
    1 — one or more findings reported
    2 — argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

VER_LINE_RE = re.compile(r"^@([0-9a-fA-F]+)\s+([0-9a-fA-F]{1,2})\s*$")


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    location: str = ""


def lenient_load(path: Path) -> Any:
    """Load JSON tolerating 0xNN hex literals (benchmark quirk)."""
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        patched = re.sub(
            r'(?P<pfx>[:\[\,\s])0x([0-9a-fA-F]+)',
            lambda m: m.group("pfx") + str(int(m.group(2), 16)),
            text,
        )
        return json.loads(patched)


def extract_otp_size(regmap: Dict[str, Any]) -> Optional[int]:
    """Find the declared OTP size, tolerating multiple L4 schema variants.

    Wave 73 (v0.128) S2 — return None instead of silently defaulting to
    128. The previous default coincidentally matched <chip-class> but masked
    SIZE_MISMATCH / ADDRESS_OUT_OF_RANGE on every other IC. Callers
    must now treat None as "size could not be determined" and surface
    a FAIL.
    """
    for key in ("otp_size_bytes", "otp_size", "size_bytes",
                "otp_macro_size"):
        if key in regmap and isinstance(regmap[key], int):
            return regmap[key]
    # v045 <chip-class> style: "otp_map_128x8" — infer 128 from key name
    for k in regmap.keys():
        m = re.match(r"otp_map_(\d+)x(\d+)", k)
        if m:
            return int(m.group(1))
    # otp_table_layout: support {"size_bytes": N} or {"end": N} etc.
    layout = regmap.get("otp_table_layout")
    if isinstance(layout, dict):
        for key in ("size_bytes", "size", "bytes", "length"):
            v = layout.get(key)
            if isinstance(v, int):
                return v
        end = layout.get("end")
        start = layout.get("start", 0)
        if isinstance(end, int) and isinstance(start, int) and end >= start:
            return end - start + 1
    return None


def extract_fields(regmap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract the per-field list regardless of schema variant."""
    if "fields" in regmap and isinstance(regmap["fields"], list):
        return regmap["fields"]
    # v045 style: otp_map_128x8 contains a list of field dicts
    for k, v in regmap.items():
        if k.startswith("otp_map_") and isinstance(v, list):
            return v
    return []


def parse_ver(path: Path) -> (Dict[int, int], List[Finding]):
    """Parse a Verilog readmemh .ver; return (addr->byte, findings)."""
    findings: List[Finding] = []
    image: Dict[int, int] = {}
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("//"):
            continue
        m = VER_LINE_RE.match(stripped)
        if not m:
            findings.append(Finding(
                rule="MALFORMED_LINE",
                severity="error",
                message=f"Unparseable line: {stripped!r}",
                location=f"{path}:{lineno}",
            ))
            continue
        addr = int(m.group(1), 16)
        val = int(m.group(2), 16)
        if val > 0xFF:
            findings.append(Finding(
                rule="BYTE_OUT_OF_RANGE",
                severity="error",
                message=f"Byte value 0x{val:X} > 0xFF at addr 0x{addr:X}",
                location=f"{path}:{lineno}",
            ))
            continue
        if addr in image:
            findings.append(Finding(
                rule="DUPLICATE_ADDRESS",
                severity="error",
                message=f"Address 0x{addr:X} written twice",
                location=f"{path}:{lineno}",
            ))
            continue
        image[addr] = val
    return image, findings


def check_coverage(
    image: Dict[int, int],
    fields: List[Dict[str, Any]],
) -> List[Finding]:
    findings: List[Finding] = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        if not f.get("required", False):
            continue
        offset = f.get("offset")
        length = f.get("length", 1)
        name = f.get("name", "<unnamed>")
        if offset is None:
            continue
        missing = [a for a in range(offset, offset + length) if a not in image]
        if missing:
            findings.append(Finding(
                rule="FIELD_COVERAGE",
                severity="error",
                message=(
                    f"Required field '{name}' ({offset}..{offset + length - 1}) "
                    f"missing bytes at {[hex(a) for a in missing]}"
                ),
            ))
    return findings


def check(ver_path: Path, regmap_path: Path) -> List[Finding]:
    findings: List[Finding] = []

    if not ver_path.exists():
        findings.append(Finding("FILE_MISSING", "error", f"OTP image not found: {ver_path}"))
        return findings
    if not regmap_path.exists():
        findings.append(Finding("FILE_MISSING", "error", f"L4 regmap not found: {regmap_path}"))
        return findings

    try:
        regmap = lenient_load(regmap_path)
    except json.JSONDecodeError as exc:
        findings.append(Finding("INVALID_JSON", "error",
                                f"L4 regmap not valid JSON: {exc}", str(regmap_path)))
        return findings

    otp_size = extract_otp_size(regmap)

    # Wave 73 (v0.128) S2 — fall back to L11 sibling for otp_macro_size.
    # No longer silently default to 128 (<chip-class>-only coincidence).
    if otp_size is None:
        l11_path = regmap_path.parent / "L11_CALIBRATION.json"
        if l11_path.is_file():
            try:
                l11 = lenient_load(l11_path)
                if isinstance(l11, dict):
                    for key in ("otp_macro_size", "otp_size_bytes",
                                "otp_size"):
                        v = l11.get(key)
                        if isinstance(v, int):
                            otp_size = v
                            break
            except Exception:  # noqa: BLE001
                pass

    image, parse_findings = parse_ver(ver_path)
    findings.extend(parse_findings)

    if otp_size is None:
        findings.append(Finding(
            rule="OTP_SIZE_UNDETERMINED",
            severity="error",
            message=(
                "OTP image size could not be determined; declare in "
                "L11.otp_macro_size or L4.otp_table_layout "
                "(or otp_size_bytes / otp_map_<N>x<W>)."
            ),
            location=str(regmap_path),
        ))
        # Without a known size we cannot run address-range / size-mismatch
        # checks; still run coverage on declared fields so the user gets
        # everything we can prove.
        findings.extend(check_coverage(image, extract_fields(regmap)))
        return findings

    # Address range check
    for addr in image:
        if addr >= otp_size:
            findings.append(Finding(
                rule="ADDRESS_OUT_OF_RANGE",
                severity="error",
                message=f"Address 0x{addr:X} exceeds OTP size {otp_size} bytes",
            ))

    if len(image) > otp_size:
        findings.append(Finding(
            rule="SIZE_MISMATCH",
            severity="error",
            message=f"Image has {len(image)} bytes, L4 declares {otp_size}",
        ))

    findings.extend(check_coverage(image, extract_fields(regmap)))
    return findings


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ver_path", help="Path to .ver OTP image")
    ap.add_argument("--regmap", required=True, help="Path to L4_REGMAP.json")
    ap.add_argument("--json", action="store_true", help="Emit JSON findings")
    args = ap.parse_args(argv)

    try:
        findings = check(Path(args.ver_path), Path(args.regmap))
    except Exception as exc:  # noqa: BLE001
        print(f"Internal error: {exc}", file=sys.stderr)
        return 2

    errors = [f for f in findings if f.severity == "error"]

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        if not findings:
            print(f"OK: {args.ver_path} passes OTP image check against {args.regmap}")
        else:
            for f in findings:
                print(f"[{f.severity.upper()}] {f.rule}: {f.message}"
                      + (f"  ({f.location})" if f.location else ""))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
