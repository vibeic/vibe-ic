#!/usr/bin/env python3
"""fpga_gate_level_attestation_check.py — v1.6.232 (merged v229+v231).

Verify Quartus actually compiled the GATE-LEVEL netlist rather than
silently falling back to RTL.

THE PROBLEM
-----------
When a project's QSF carries BOTH the gate-level netlist
(`chip_top_asic_pnr.v`) AND the RTL source (`chip_top.sv`), Quartus
can silently pick the RTL — and the SOF still works but the gate
netlist NEVER reached the device. v3 (BENCH-A ORGANIC-20260512) hit
this: BIST passed on bench, but `*.map.rpt` revealed `main_fsm:u_fsm`
proving RTL fallback.

CHECK RULES
-----------
A genuine gate-level compile of `<gate_top>` must:

  1. Show `<gate_top>` as a hierarchy node (e.g. `chip_top_asic:u_*`).
  2. NOT show ANY RTL submodule names (main_fsm:, rx_phy:, tx_phy:,
     otp_mem:, byte_assembler:, crc8:, control_logic:, wake_gen:).
  3. Show at least one PDK std-cell signature (matches either a
     prefix family OR a real cell-name regex like DFF[A-Z]*\\d*,
     AOI\\d+, OAI\\d+, NAND\\dD\\d, NOR\\dD\\d, INVD\\d, CLKBUFD\\d+).

USAGE
-----
    python3 fpga_gate_level_attestation_check.py \\
        --map-rpt phase3/quartus/de10lite_top.map.rpt \\
        [--gate-top chip_top_asic] \\
        [--rtl-submodules main_fsm,rx_phy,...] \\
        [--json reports/fpga_gate_attestation.json]

EXIT CODES
----------
    0  PASS — all 3 rules satisfied (or only rule 3 warned).
    1  FAIL — rule 1 or 2 violated.
    2  IO error.

chip-AGNOSTIC: every rule key is netlist hygiene, never chip class.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional

try:  # config-driven commercial-PDK id (NDA: no SKU literal in source)
    import _commercial_pdk as _cpdk
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _commercial_pdk as _cpdk


# Default RTL submodule names that would prove fallback to source.
# chip-AGNOSTIC defaults (BENCH-A-class names) — override per project.
_DEFAULT_RTL_SUBMODULES = (
    "main_fsm", "rx_phy", "tx_phy",
    "regbank", "regfile", "otp_ctrl", "otp_mem",
    "byte_assembler", "crc8", "control_logic", "wake_gen",
    "uart_rx", "uart_tx", "spi_ctrl", "i2c_ctrl",
)

# PDK std-cell prefix families (v231). The commercial-PDK prefix is
# reconstructed at runtime from the encoded NDA token (no SKU literal here).
_PDK_CELL_PREFIXES = (
    "sg13g2_", "gf180mcu_", "sky130_fd_sc_",
    "tsmc", "asap7sc",
) + _cpdk.nda_cell_prefixes()

# Real cell-name regex patterns (v229) — catches commercial-PDK / generic libs
_STDCELL_PATTERNS = (
    re.compile(r"\bDFF[A-Z]*\d+"),
    re.compile(r"\bAOI\d+"),
    re.compile(r"\bOAI\d+"),
    re.compile(r"\bNAND\d[A-Z]?D\d"),
    re.compile(r"\bNOR\d[A-Z]?D\d"),
    re.compile(r"\bINVD\d"),
    re.compile(r"\bCLKBUFD\d+"),
    re.compile(r"\bCLKINVD\d+"),
)


@dataclass
class Finding:
    severity: str
    rule: str
    detail: str
    evidence: List[str] = field(default_factory=list)


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError as e:
        raise SystemExit(f"error: cannot read {path}: {e}")


def _grep_instances(text: str, name: str) -> List[str]:
    pat = re.compile(r"\b" + re.escape(name) + r":[A-Za-z_]\w*", re.MULTILINE)
    return list({m.group(0) for m in pat.finditer(text)})[:5]


def _pdk_cell_evidence(text: str) -> List[str]:
    hits: List[str] = []
    for pfx in _PDK_CELL_PREFIXES:
        pat = re.compile(r"\b" + re.escape(pfx) + r"\w+", re.IGNORECASE)
        for m in pat.finditer(text):
            tok = m.group(0)
            if tok not in hits:
                hits.append(tok)
            if len(hits) >= 5:
                return hits
    if hits:
        return hits
    for pat in _STDCELL_PATTERNS:
        for m in pat.finditer(text):
            tok = m.group(0)
            if tok not in hits:
                hits.append(tok)
            if len(hits) >= 5:
                return hits
    return hits


def audit(map_rpt: Path, gate_top: str,
           rtl_submodules: List[str]) -> List[Finding]:
    text = _read(map_rpt)
    out: List[Finding] = []

    top_hits = _grep_instances(text, gate_top)
    if not top_hits:
        out.append(Finding(
            severity="ERROR",
            rule="GATE_TOP_NOT_INSTANTIATED",
            detail=(f"gate-level top {gate_top!r} not found as an "
                    f"instance in {map_rpt}. Quartus likely compiled "
                    f"the RTL source instead. Remove RTL .sv from QSF "
                    f"except the FPGA top-level wrapper."),
        ))

    leaked: List[str] = []
    for sub in rtl_submodules:
        hits = _grep_instances(text, sub)
        leaked.extend(hits)
    if leaked:
        out.append(Finding(
            severity="ERROR",
            rule="RTL_SUBMODULE_LEAKED",
            detail=(f"{len(leaked)} RTL submodule instance(s) leaked into "
                    f"the gate-level compile — proof of RTL fallback. "
                    f"Remove the RTL .sv files from the QSF or rename "
                    f"the gate netlist top to avoid name collision."),
            evidence=leaked[:10],
        ))

    pdk_ev = _pdk_cell_evidence(text)
    if not pdk_ev:
        out.append(Finding(
            severity="WARN",
            rule="NO_STDCELL_EVIDENCE",
            detail=(f"No recognised PDK std-cell prefix or regex match "
                    f"found in map.rpt (checked prefixes: "
                    f"{_PDK_CELL_PREFIXES}, regex families: DFF*/AOI*/"
                    f"OAI*/NAND*/NOR*/INV*/CLK*). Either the netlist is "
                    f"flattened to Yosys primitives, or it never "
                    f"elaborated."),
        ))

    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify Quartus compiled gate-level (not RTL fallback).",
    )
    ap.add_argument("--map-rpt", required=True, help="Quartus *.map.rpt")
    ap.add_argument("--gate-top", default="chip_top_asic")
    ap.add_argument("--rtl-submodules", default=None,
                    help="Comma-separated submodule names overriding defaults.")
    ap.add_argument("--json", default=None,
                    help="Write JSON report; '-' for stdout.")
    args = ap.parse_args(argv)

    map_rpt = Path(args.map_rpt)
    if not map_rpt.is_file():
        print(f"error: map.rpt not found: {map_rpt}", file=sys.stderr)
        return 2

    rtl_subs = (
        [s.strip() for s in args.rtl_submodules.split(",") if s.strip()]
        if args.rtl_submodules else list(_DEFAULT_RTL_SUBMODULES)
    )

    findings = audit(map_rpt, args.gate_top, rtl_subs)
    errors = [f for f in findings if f.severity == "ERROR"]
    report = {
        "map_rpt": str(map_rpt),
        "gate_top": args.gate_top,
        "rtl_submodules_checked": rtl_subs,
        "errors": len(errors),
        "warnings": len(findings) - len(errors),
        "findings": [asdict(f) for f in findings],
        "verdict": "PASS" if not errors else "FAIL",
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
            print(f"[{f.severity}] {f.rule}: {f.detail}")
            for ev in f.evidence:
                print(f"  evidence: {ev}")
        print(f"\nverdict: {report['verdict']} "
              f"({len(errors)} error(s), "
              f"{len(findings) - len(errors)} warn(s))")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
