#!/usr/bin/env python3
"""
fpga_top_pin_completeness_check.py — gate that catches an FPGA top module
declaring fewer pins than the L2 spec demands.

Why this gate exists
====================
v3 <benchmark> root cause: a fresh-agent fpga_top declared only GPIO_id_bus
+ KEY_rstn + LED — missing the WAKE input pin, the CC_I / CC_O cable-
sense pins, and the OUT1 / OUT2 GPIO outputs that L2 functional
requirements named. The host rig physically routed those wires;
without the corresponding fpga_top ports the rig could not wake the
chip and the host-side connect_test failed deterministically.

The class of bug is general (any IC family): L2 names hardware pins
the silicon must expose, the fpga_top wrapper must declare them.

How required pins are derived (v0.119.15 — chip-agnostic)
=========================================================
The gate reads required pins from L2 spec. Two canonical schemas are
accepted; the gate silent-skips when neither is present (the project
opts in to this check by declaring its pin set in L2):

  1) `l2.pad_definitions[]` — list of objects, each with at least
     `{ "name": "<PIN_NAME>" }`. Optional `"mandatory": true` (default
     true) lets the project mark some pads as informational only.
  2) `l2.required_pins[]` — simpler list. Each entry may be a bare
     string ("WAKE") or an object {"name": "WAKE", "requirement_id":
     "FR-07"}.

No hard-coded chip/family pin whitelist exists in this gate's code.
Earlier versions baked <chip-class>/<half-duplex-tester> pin names (WAKE, CC_I, CC_O,
ACC_ID, …) into a regex; v0.119.15 removed that so the gate is
useful on any IC whose L2 declares its pad list.

Usage
-----
python3 fpga_top_pin_completeness_check.py <project_dir>

Honors waivers.json["fpga_pin_intentionally_omitted"] (per-pin
rationale list).

Returns 0 on PASS / silent-skip, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def find_l2(project_dir: Path) -> Path | None:
    """Prefer L2_FRS.json (functional requirements schema) over
    L2_TIMING_WAVEFORM.json — the pad list belongs in FRS."""
    for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir),
                 project_dir / "input" / "docs"):
        for n in ("L2_FRS.json", "L2_TIMING_WAVEFORM.json"):
            p = base / n
            if p.exists():
                return p
    return None


def find_fpga_top(project_dir: Path) -> Path | None:
    """Locate FPGA top RTL. Generic name patterns only — no chip-
    specific filename hard-codes."""
    rtl = _pl.rtl_dir(project_dir)
    if not rtl.exists():
        return None
    for n in ("fpga_top.sv", "fpga_top.v"):
        p = rtl / n
        if p.exists():
            return p
    # Generic *_fpga_top / *_top fallback
    for pattern in ("*_fpga_top.sv", "*_fpga_top.v",
                    "*_top.sv", "*_top.v",
                    "*top*.sv", "*top*.v"):
        matches = sorted(rtl.glob(pattern))
        if matches:
            return matches[0]
    return None


def extract_required_pins(l2: dict) -> tuple[dict[str, str], int]:
    """Return ({pin_name_uppercase: requirement_id_or_origin}, n_skipped_nonmandatory).

    Reads from L2 in priority order:
      1. l2.pad_definitions[] — preferred; richer schema with optional
         mandatory flag.
      2. l2.required_pins[] — alternate; bare strings or {name, ...}
         dicts.

    The second return value is the count of pads that were dropped because
    `mandatory: false` was set explicitly. The caller uses this to detect
    under-classification (most common false-pass mode: agent marks every
    L2 pad mandatory:false → gate "passes" with 0 required pins). A pad
    with `requirement_id` is treated as mandatory regardless of any
    `mandatory: false` flag — FR-tied pins are not optional by definition.

    Returns ({}, 0) if neither schema is present.
    """
    out: dict[str, str] = {}
    n_skipped_nonmandatory = 0

    pad_defs = l2.get("pad_definitions")
    if isinstance(pad_defs, list):
        for pad in pad_defs:
            if not isinstance(pad, dict):
                continue
            name = pad.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            mandatory = pad.get("mandatory", True)
            req_id = pad.get("requirement_id")
            # FR-tied pads are mandatory by definition — overrides any
            # mandatory:false set by mistake.
            if mandatory is False and not req_id:
                n_skipped_nonmandatory += 1
                continue
            origin = (req_id or pad.get("origin") or "L2.pad_definitions")
            out.setdefault(name.strip().upper(), str(origin))
        if out or n_skipped_nonmandatory > 0:
            return out, n_skipped_nonmandatory

    required = l2.get("required_pins")
    if isinstance(required, list):
        for entry in required:
            if isinstance(entry, str) and entry.strip():
                out.setdefault(entry.strip().upper(), "L2.required_pins")
            elif isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str) and name.strip():
                    origin = (entry.get("requirement_id")
                              or entry.get("origin")
                              or "L2.required_pins")
                    out.setdefault(name.strip().upper(), str(origin))
    return out, n_skipped_nonmandatory


def extract_pin_aliases(l2: dict) -> dict[str, list[str]]:
    """Build {canonical_name_upper: [alias_upper, ...]} from L2.

    Two declaration paths supported, both project-driven (no hard-coded
    chip- or board-specific synonym lists in this gate's code):

    1. `pad_definitions[].fpga_alias` — list of strings or single string.
       e.g. {"name": "RSTN", "fpga_alias": ["KEY[0]", "BTN_RESET"]}
    2. Top-level `fpga_pin_aliases` dict — {"RSTN": ["KEY[0]"], ...}.

    The fresh agent on a DE10-Lite project drove the project-level
    declaration: L2's `RSTN` pad mapped to fpga_top's `KEY[0]` port.
    Earlier code looked only for substring containment which failed on
    bracket-form ports — explicit aliases close the gap generally."""
    aliases: dict[str, list[str]] = {}

    def _add(name: str, alist):
        if not isinstance(alist, list):
            alist = [alist]
        cleaned = [str(x).strip().upper() for x in alist
                   if isinstance(x, (str,)) and str(x).strip()]
        if cleaned:
            aliases.setdefault(name.strip().upper(), []).extend(cleaned)

    pad_defs = l2.get("pad_definitions")
    if isinstance(pad_defs, list):
        for pad in pad_defs:
            if not isinstance(pad, dict):
                continue
            name = pad.get("name")
            alist = pad.get("fpga_alias") or pad.get("fpga_aliases")
            if isinstance(name, str) and alist:
                _add(name, alist)

    top_aliases = l2.get("fpga_pin_aliases")
    if isinstance(top_aliases, dict):
        for canon, alist in top_aliases.items():
            if isinstance(canon, str):
                _add(canon, alist)

    return aliases


def extract_top_ports(rtl_path: Path) -> set[str]:
    src = rtl_path.read_text()
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    # v0.119.25: SystemVerilog allows package import statements between
    # the module name and the port list:
    #     module fpga_top
    #         import aid_pkg::*;
    #         import other_pkg::sym;
    #         (input wire clk, ...);
    # The earlier regex didn't account for the optional import block and
    # silently extracted ZERO ports — a false PASS that hid real missing
    # pins (caught by v0.119.24 vendor benchmark).
    m = re.search(
        r"module\s+\w+\s*"
        r"(?:#\s*\([^)]*\)\s*)?"          # optional parameter port list
        r"(?:import\s+[\w:\*\s,]+;\s*)*"  # zero-or-more SV import stmts
        r"\(([^;]+?)\)\s*;",
        src, flags=re.DOTALL,
    )
    if not m:
        return set()
    body = m.group(1)
    ports = set()
    for line in body.split(","):
        toks = line.split()
        if not toks:
            continue
        # Last token of each port line is the port name (after type / width).
        ports.add(toks[-1].strip("[],"))
    return {p.upper() for p in ports if p}


def waived(project_dir: Path, name: str) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        omitted = d.get("fpga_pin_intentionally_omitted", [])
        if isinstance(omitted, list):
            return any(name in str(item) for item in omitted)
        return name in str(omitted)
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: fpga_top_pin_completeness_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    l2_path = find_l2(project_dir)
    if not l2_path:
        print("PASS — no L2 doc (gate not applicable)")
        sys.exit(0)
    try:
        l2 = json.loads(l2_path.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse L2: {e}")
        sys.exit(1)

    required, n_nonmandatory = extract_required_pins(l2)
    aliases = extract_pin_aliases(l2)
    if not required and n_nonmandatory == 0:
        print("PASS — L2 declares no pad_definitions[] / required_pins[] "
              "(gate opt-in: project must list its pins in L2 to enable "
              "completeness checking)")
        sys.exit(0)

    # Under-classification guard: when a project declares pad_definitions[]
    # but marks the majority of them mandatory:false (without a backing
    # requirement_id), the resulting "PASS — N pins present" is misleading
    # because the gate is checking ~nothing. The fresh-agent failure mode
    # we caught: 6 of 8 pads marked mandatory:false, gate reports
    # "all 2 pins present", missing 6 FR-mentioned pins entirely.
    underclassified = (
        n_nonmandatory > 0
        and (len(required) == 0 or n_nonmandatory >= 2 * len(required))
    )

    fpga_top = find_fpga_top(project_dir)
    if not fpga_top:
        print("PASS — no FPGA top RTL yet (gate skipped)")
        sys.exit(0)

    ports = extract_top_ports(fpga_top)

    def _ports_match(pin_upper: str) -> bool:
        if pin_upper in ports:
            return True
        # Subsuming names: GPIO_<pin> etc. Handles bracket-form ports
        # by stripping `[N]` for the substring check.
        for p in ports:
            p_base = p.split("[")[0]
            if pin_upper in p or pin_upper in p_base:
                return True
        # v0.119.24: project-declared FPGA aliases (e.g. RSTN→KEY[0]).
        # Aliases bypass substring matching — exact (or bracketed) form.
        for alias in aliases.get(pin_upper, []):
            alias_base = alias.split("[")[0]
            if alias in ports or alias_base in ports:
                return True
            for p in ports:
                p_base = p.split("[")[0]
                if alias in p or alias_base == p_base:
                    return True
        return False

    missing = []
    for pin, rid in sorted(required.items()):
        if _ports_match(pin):
            continue
        if waived(project_dir, pin):
            continue
        missing.append((pin, rid))

    if not missing:
        if underclassified:
            print(f"WARN — {len(required)} mandatory pad(s) present, but "
                  f"{n_nonmandatory} L2 pad(s) are marked mandatory:false. "
                  "If those pads are tied to functional requirements (FR-*), "
                  "add `requirement_id` to elevate them — otherwise this "
                  "gate is checking very little.")
            # Soft-warn, not a hard FAIL: project may legitimately have
            # informational-only pads. Caller decides via stdout text.
            sys.exit(0)
        print(f"PASS — all {len(required)} L2-declared hardware pins present "
              "in fpga_top")
        sys.exit(0)

    print(f"FAIL — {len(missing)} L2-mandated hardware pin(s) absent from "
          "fpga_top:")
    for pin, rid in missing:
        print(f"  • {pin} (required by {rid})")
    print()
    print(f"  fpga_top file: {fpga_top.relative_to(project_dir)}")
    print(f"  declared ports: {sorted(ports)}")
    print()
    print("Why this matters:")
    print("  L2 names pins the silicon must expose for the host rig to")
    print("  interact with it. Missing wake / cable-sense / GPIO pins")
    print("  means the rig cannot drive the chip's response path and")
    print("  on-board tests fail deterministically — no amount of")
    print("  internal-RTL fix recovers it.")
    print()
    print("Fix: add the missing pins to fpga_top's port list AND wire them")
    print("     through to the corresponding chip-top module input/output.")
    print("     Update QSF / XDC pin assignments to bind each new pin to")
    print("     the physical board wire.")
    print()
    print('Or document an intentional omission per pin:')
    print('    {"fpga_pin_intentionally_omitted": ["<PIN_NAME> — rationale"]}')
    sys.exit(1)


if __name__ == "__main__":
    main()
