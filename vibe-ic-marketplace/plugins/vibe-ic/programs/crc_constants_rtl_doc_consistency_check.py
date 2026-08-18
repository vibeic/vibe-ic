#!/usr/bin/env python3
"""
crc_constants_rtl_doc_consistency_check.py — gate (LL-37) cross-checks
CRC constants between RTL Verilog source and L8_RTL_CONSTANTS.json.

Why this gate exists
====================
BACKLOG-v13 Wave 2, audit item #4. v0.119.32 vendor run shipped:
  - rtl/crc8.v line 51:  `crc_out <= 8'hFF;`            (init = 0xFF)
  - L8.crc8_constants:   `{"name": "CRC_SEED", "value": 0}`  (says 0x00)

Doc and RTL disagreed. Either L11/L8 doc was wrong (typical: agent
re-derived seed from CRC test-vectors-only) or the RTL was using the
wrong literal. Result: downstream gates (`crc_seed_consistency_check`)
PASSed because they checked RTL against test-vectors, missing the
spec-document drift.

This gate adds the missing leg: RTL CRC literals must match L8
(spec) CRC constants. Catches silent doc/RTL drift before tape-out.

Rule
----
Trigger condition (silent-skip when none hit):
  - rtl/*crc*.v / *.sv (or *.v with `crc_out <=` literal) found, AND
  - L8_RTL_CONSTANTS.json has a `crc8_constants` array, OR a
    `crc_parameters` block.

When triggered, parse:
  - RTL `crc_out <= 8'hXX;` → init literal.
  - RTL `^ 8'hXX` literal → reflected polynomial (LSB-first form).
  - L8 `crc8_constants[].name == "CRC_SEED" .value` → init.
  - L8 `crc8_constants[].name == "CRC_REFLECTED_POLY" .value` →
    reflected.
  - L8 `crc8_constants[].name == "CRC_POLY" .value` → forward poly
    (informational; we re-derive reflected for cross-check).

If any RTL/L8 pair disagrees → FAIL with the offending field.

Honors waivers.json key `crc_constants_rtl_doc_drift_intentional`
(≥40 chars).

Usage
-----
python3 crc_constants_rtl_doc_consistency_check.py <project_dir>

Returns 0 PASS / silent-skip / waived, 1 FAIL, 2 input error.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


CRC_INIT_RE = re.compile(
    r"crc_out\s*<=\s*8'h([0-9A-Fa-f]{1,2})",
)
# Reflected poly literal: e.g. `^ 8'h8C` or `XOR 8'h8C`. Avoid matching
# the init literal — require it appears NOT immediately after `<=`.
CRC_REFL_RE = re.compile(
    r"\^\s*8'h([0-9A-Fa-f]{1,2})",
)


def _find_crc_rtl(project: Path) -> list[Path]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        rtl_dir = project
    out: list[Path] = []
    for p in rtl_dir.rglob("*.v"):
        if "crc" in p.name.lower():
            out.append(p)
    for p in rtl_dir.rglob("*.sv"):
        if "crc" in p.name.lower():
            out.append(p)
    if not out:
        # Fallback: any .v / .sv with `crc_out <=` literal.
        for p in list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv")):
            try:
                if "crc_out" in p.read_text(errors="replace"):
                    out.append(p)
            except Exception:
                continue
    return out


def _parse_rtl(p: Path) -> dict:
    """Return {init_hex, reflected_polys[]} from a CRC RTL file."""
    try:
        text = p.read_text(errors="replace")
    except Exception:
        return {}
    out: dict = {"file": str(p.name)}
    inits = [m.group(1).upper() for m in CRC_INIT_RE.finditer(text)]
    if inits:
        out["init_hex_set"] = sorted(set("0x" + i for i in inits))
        # Choose the first init literal as canonical.
        out["init_hex"] = "0x" + inits[0].upper()
    refls = [m.group(1).upper() for m in CRC_REFL_RE.finditer(text)]
    out["reflected_poly_hex_set"] = sorted(set("0x" + r for r in refls))
    return out


def _find_l8(project: Path) -> Path | None:
    for stem in ("L8_RTL_CONSTANTS.json", "L8_TIMING_WAVEFORM.json"):
        for base in (_pl.generated_docs_dir(project),
                     project / "docs", project):
            p = base / stem
            if p.is_file():
                return p
    return None


def _parse_l8(p: Path) -> dict:
    """Pull {init_hex, reflected_poly_hex, poly_hex, bit_order} from L8.

    Accepts both `crc8_constants` array and `crc_parameters` block.
    """
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {}
    out: dict = {"file": str(p.name)}

    arr = data.get("crc8_constants") or []
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).upper()
        v = entry.get("value")
        if name == "CRC_SEED" and isinstance(v, (int, float)):
            out["init_hex"] = f"0x{int(v):02X}"
        elif name == "CRC_POLY" and isinstance(v, (int, float)):
            out["poly_hex"] = f"0x{int(v):02X}"
        elif name == "CRC_REFLECTED_POLY" and isinstance(v, (int, float)):
            out["reflected_poly_hex"] = f"0x{int(v):02X}"
        elif name == "CRC_BIT_ORDER" and isinstance(v, str):
            out["bit_order"] = v.lower()

    cp = data.get("crc_parameters")
    if isinstance(cp, dict):
        for k_src, k_dst in (
            ("init_hex", "init_hex"),
            ("polynomial_hex", "poly_hex"),
            ("polynomial_reflected_hex", "reflected_poly_hex"),
            ("bit_order", "bit_order"),
        ):
            v = cp.get(k_src)
            if isinstance(v, str):
                out.setdefault(k_dst, v.lower() if k_dst == "bit_order"
                               else v.upper())
    return out


def _waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        v = d.get("crc_constants_rtl_doc_drift_intentional", "")
        return isinstance(v, str) and len(v.strip()) >= 40
    except Exception:
        return False


def _normalize_hex(s: str) -> str:
    if not s:
        return s
    s = s.strip().upper()
    if s.startswith("0X"):
        s = "0x" + s[2:]
    return s


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: crc_constants_rtl_doc_consistency_check.py "
              "<project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    rtl_files = _find_crc_rtl(project)
    l8 = _find_l8(project)

    if not rtl_files and not l8:
        print("PASS — no CRC RTL nor L8 found (gate skipped)")
        return 0
    if not rtl_files:
        print("PASS — no CRC RTL found in project (gate skipped)")
        return 0
    if not l8:
        print("PASS — no L8 found in project (gate skipped)")
        return 0

    rtl_view = {}
    for f in rtl_files:
        d = _parse_rtl(f)
        if d:
            rtl_view = d
            break
    if not rtl_view or "init_hex" not in rtl_view:
        print(f"PASS — RTL {rtl_files[0].name} has no `crc_out <= 8'hXX` "
              f"literal (gate skipped)")
        return 0

    l8_view = _parse_l8(l8)
    if not l8_view:
        print(f"PASS — L8 {l8.name} has no `crc8_constants` / "
              f"`crc_parameters` block (gate skipped)")
        return 0

    # Cross-consistency comparisons.
    fails: list[str] = []

    rtl_init = _normalize_hex(rtl_view.get("init_hex", ""))
    l8_init = _normalize_hex(l8_view.get("init_hex", ""))
    if rtl_init and l8_init and rtl_init != l8_init:
        fails.append(
            f"  • CRC init: RTL says {rtl_init} (rtl/{rtl_view['file']} "
            f"`crc_out <=`), L8 says {l8_init} (CRC_SEED). MISMATCH."
        )

    rtl_refls = set(rtl_view.get("reflected_poly_hex_set", []))
    l8_refl = _normalize_hex(l8_view.get("reflected_poly_hex", ""))
    if rtl_refls and l8_refl:
        rtl_refls_norm = {_normalize_hex(x) for x in rtl_refls}
        if l8_refl not in rtl_refls_norm:
            fails.append(
                f"  • CRC reflected polynomial: RTL has "
                f"{sorted(rtl_refls_norm)} (rtl/{rtl_view['file']} "
                f"`^ 8'hXX`), L8 says {l8_refl} "
                f"(CRC_REFLECTED_POLY). MISMATCH."
            )

    if fails:
        if _waived(project):
            print("PASS_WITH_WAIVER — RTL/L8 CRC drift waived")
            return 0
        print(f"FAIL — RTL/L8 CRC constants disagree:")
        for f in fails:
            print(f)
        print()
        print("Fix: align rtl/crc8.v literals with L8.crc8_constants")
        print("     (or align L8 with the RTL — whichever is the spec).")
        return 1

    print(f"PASS — RTL ({rtl_view['file']}) CRC literals "
          f"{rtl_init} / {sorted(rtl_view.get('reflected_poly_hex_set', []))} "
          f"match L8 ({l8.name}) {l8_init} / {l8_refl or '<not set>'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
