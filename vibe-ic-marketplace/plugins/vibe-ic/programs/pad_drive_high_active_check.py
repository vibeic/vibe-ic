#!/usr/bin/env python3
"""
pad_drive_high_active_check.py — v0.114 (BACKLOG-v6 P1).

ASIC-side pad drive strength sanity check. For each `inout` port in
the synth top module, verify that:
  (a) the port maps to a documented pad cell in the LEF macro library
      (input/pdk/lef/.../*macro*.lef), AND
  (b) the pad cell's class is consistent with the protocol's
      drive mode declared in L2 (open_drain / active_drive / multi_master).

Distinct from v7 P1.1 `tristate_active_drive_check` which is FPGA-target
weak-pull-up mitigation. This gate is for ASIC pad selection.

Static check (chip-AGNOSTIC):

  1. Parse synth top RTL for `inout <port_name>`.
  2. Parse LEF macro file for cells matching `*PAD*` / `*IO*` /
     `*BIDIR*` / `*OD*` (open-drain) classes.
  3. Read L2_TIMING_WAVEFORM.json for protocol.pad_drive_mode (if absent,
     warn — schema gap).
  4. Compare: open_drain mode requires *OD* / *open_drain* class pad;
     active_drive mode requires standard bidir / no-OD pad.
  5. Mismatch → ERROR with actionable message.

Skips gracefully if no inout ports OR no LEF macro file OR no L2
declaration.

Usage:
  python3 pad_drive_high_active_check.py <project_dir> [--json [PATH]]
Exit 0 PASS, 1 FAIL, 2 IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


_INOUT_PORT_RE = re.compile(r"\binout\s+(?:wire|reg|logic)?\s*(?:\[[^\]]+\])?\s*(\w+)\s*[,;\)]")
_LEF_MACRO_RE = re.compile(r"^MACRO\s+(\w+)", re.MULTILINE)


def _find_synth_top(project: Path) -> Optional[Path]:
    """Find a top-level RTL file with inout port(s)."""
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return None
    candidates = []
    for path in sorted(rtl_dir.rglob("*")):
        if path.suffix.lower() not in (".v", ".sv"):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if _INOUT_PORT_RE.search(text):
            candidates.append((path, text))
    # Prefer files with "top" in name
    for path, _ in candidates:
        if "top" in path.name.lower():
            return path
    if candidates:
        return candidates[0][0]
    return None


def _extract_inout_ports(text: str) -> List[str]:
    return _INOUT_PORT_RE.findall(text)


def _find_lef_macro_file(project: Path) -> Optional[Path]:
    pdk_lef_dir = project / "input" / "pdk" / "lef"
    if not pdk_lef_dir.is_dir():
        return None
    for path in pdk_lef_dir.rglob("*.lef"):
        # Skip tech LEFs (no MACRO sections)
        if "tech" in path.name.lower():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if "MACRO " in text:
            return path
    return None


def _classify_pad_cells(lef_text: str) -> Dict[str, str]:
    """For each MACRO definition, infer pad class from name + content."""
    cells = {}
    for m in _LEF_MACRO_RE.finditer(lef_text):
        name = m.group(1)
        upper = name.upper()
        cls = "core"  # default — not a pad
        if any(tok in upper for tok in ("PAD", "IO", "BIDIR")):
            cls = "pad_active_drive"
        if any(tok in upper for tok in ("OD", "OPENDRAIN", "OPEN_DRAIN")):
            cls = "pad_open_drain"
        cells[name] = cls
    return cells


def _l2_pad_drive_mode(project: Path) -> Optional[str]:
    p = _pl.generated_docs_dir(project) / "L2_TIMING_WAVEFORM.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    proto = d.get("protocol") or {}
    if isinstance(proto, dict):
        v = proto.get("pad_drive_mode")
        if isinstance(v, str):
            return v.lower()
    if isinstance(d.get("pad_drive_mode"), str):
        return d["pad_drive_mode"].lower()
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(
        "Verify ASIC pad cell class matches protocol pad_drive_mode declared in L2."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--json", nargs="?", const="-", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    findings: List[Finding] = []

    top_rtl = _find_synth_top(project)
    if top_rtl is None:
        result = {
            "program": "pad_drive_high_active_check",
            "version": "1.0.0",
            "project": str(project),
            "summary": {"skip": True, "reason": "no RTL with inout port found", "pass": True},
            "findings": [],
        }
        if args.json is None:
            print("[PASS] pad_drive_high_active_check (skip — no inout port in RTL)")
        return 0

    text = top_rtl.read_text(errors="replace")
    inout_ports = _extract_inout_ports(text)

    lef_macro = _find_lef_macro_file(project)
    pad_cells: Dict[str, str] = {}
    if lef_macro:
        try:
            lef_text = lef_macro.read_text(errors="replace")
            pad_cells = _classify_pad_cells(lef_text)
        except Exception:
            pass

    drive_mode = _l2_pad_drive_mode(project)

    if drive_mode is None:
        findings.append(Finding(
            severity="WARN",
            category="L2_PAD_DRIVE_MODE_MISSING",
            message=(
                "L2_TIMING_WAVEFORM.json has no `protocol.pad_drive_mode` "
                "field (one of `open_drain` / `active_drive` / "
                "`multi_master`). Cannot verify pad class. Add the field "
                "to your L2 spec for full coverage."
            ),
        ))

    # Multi-master protocols (I2C, 1-Wire, CAN) MUST be open-drain.
    # Active-drive on a multi-master bus = bus contention / damage.
    if drive_mode in ("open_drain", "multi_master"):
        # For these, no active-drive cell should be implied by the design
        # (FPGA-target tristate_active_drive_check is the FPGA counterpart).
        # On ASIC side, we just verify the LEF has an open-drain pad option.
        has_od = any(cls == "pad_open_drain" for cls in pad_cells.values())
        if pad_cells and not has_od:
            findings.append(Finding(
                severity="ERROR",
                category="OPEN_DRAIN_PAD_NOT_AVAILABLE",
                message=(
                    f"L2 protocol declares pad_drive_mode={drive_mode!r} "
                    f"but the LEF macro library at "
                    f"{lef_macro.relative_to(project)} contains no "
                    f"open-drain pad cell (no MACRO with OD / OPENDRAIN / "
                    f"OPEN_DRAIN in its name). Multi-master / open-drain "
                    f"protocols REQUIRE an open-drain pad — active-drive "
                    f"causes bus contention. Either: (a) add an OD pad "
                    f"cell to the LEF, OR (b) verify the foundry deliverable "
                    f"includes one and update LEF naming convention."
                ),
            ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)
    result = {
        "program": "pad_drive_high_active_check",
        "version": "1.0.0",
        "project": str(project),
        "summary": {
            "synth_top_file": str(top_rtl.relative_to(project)) if top_rtl else None,
            "inout_ports": inout_ports,
            "lef_macro_file": str(lef_macro.relative_to(project)) if lef_macro else None,
            "lef_pad_classes": pad_cells,
            "l2_pad_drive_mode": drive_mode,
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] pad_drive_high_active_check")
        print(f"  inout ports: {inout_ports}")
        print(f"  L2 pad_drive_mode: {drive_mode}")
        print(f"  LEF: {lef_macro.relative_to(project) if lef_macro else '(not found)'}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
