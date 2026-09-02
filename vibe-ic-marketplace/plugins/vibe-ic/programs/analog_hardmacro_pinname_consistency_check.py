#!/usr/bin/env python3
"""analog_hardmacro_pinname_consistency_check.py — deterministic 3-way pin-name gate.

Extracted from the `analog-hardmacro-gen` skill (Step 5 validation:
"LEF pin names == Verilog port names == spec.json interface"). The skill
documented this as a manual check; this program turns it into a
deterministic set-equality assertion across the three hardmacro files
for each analog block:

    hardmacro/<block>/<block>.lef   — MACRO ... PIN <name> ... END <name>
    hardmacro/<block>/<block>.v     — module <block> (input/output <name>, ...)
    analog/<block>/spec.json        — interface.pins[].name

The defect this catches (real, documented in the skill "Do not" list):
a pin-name mismatch between LEF and Verilog causes LVS failure when the
hardmacro is integrated into digital PnR. The spec.json interface is the
golden source; LEF and Verilog must each expose exactly that pin set.

Honesty rules (NO vacuous PASS):
  * If a block has NO spec.json interface (no `interface.pins`) AND no
    LEF PINs AND no Verilog ports, there is nothing to compare ->
    SKIP for that block (recorded, not a PASS).
  * If a block has a spec interface but the LEF/Verilog files are
    missing or carry zero pins/ports, that is an honest FAIL (the
    hardmacro fails to expose the spec'd interface).
  * Garbage / unparseable input -> FAIL (not silently skipped).
  * No analog blocks at all -> VACUOUS (rc 2) — the design has no analog
    hardmacros to check.

Usage:
    python3 analog_hardmacro_pinname_consistency_check.py <project_dir>
    python3 analog_hardmacro_pinname_consistency_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS: at least one analog block was compared and every one is
        consistent across LEF / Verilog / spec
    1 = FAIL (>=1 block has a pin-name mismatch / missing interface exposure)
    2 = VACUOUS: nothing was examined — this project declares no analog block,
        so there is no pin set to compare. #521: the module header already
        said "Honesty rules (NO vacuous PASS)" and this branch was exactly
        that, exiting 0 on 197 of the 200 tracked project roots. Also rc 2 for
        an IO / argument error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Set

try:
    import _path_layout as _pl
except ImportError:  # pragma: no cover - allow standalone import
    _pl = None

import _vacuous_exit as _vx
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


# ---------------------------------------------------------------------------
# Parsers — each returns a *set* of pin/port names (lower-cased for the
# comparison; analog tool flows are case-insensitive on net names but we
# keep the original spelling in findings for readability).
# ---------------------------------------------------------------------------

_LEF_PIN_RE = re.compile(r"^\s*PIN\s+(\S+)", re.MULTILINE)


def parse_lef_pins(text: str) -> Set[str]:
    """Extract PIN names from a LEF MACRO body."""
    return {m.group(1).strip().lower() for m in _LEF_PIN_RE.finditer(text)}


_V_MODULE_RE = re.compile(
    r"\bmodule\b[^\(;]*\((?P<ports>.*?)\)\s*;", re.DOTALL)
_V_PORT_DECL_RE = re.compile(
    r"\b(?:input|output|inout)\b"
    r"(?:\s+(?:wire|reg|logic))?"
    r"(?:\s*\[[^\]]*\])?"
    r"\s+([A-Za-z_]\w*)")


#: A bare port name in a NON-ANSI module header: `module m (a, b, c);` with the
#: directions declared in the body. Verilog-95 style, and the style THIS FLOW's
#: own A8 hardmacro emitter writes.
_V_BARE_PORT_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*$")


def parse_verilog_ports(text: str) -> Set[str]:
    """Port names from the FIRST module header — ANSI or non-ANSI.

    ANSI (`module m (input a, output b);`) states the direction in the header.
    NON-ANSI (`module m (a, b); input a; output b;`) lists bare names there and
    declares them in the body. Reading only the ANSI form makes every non-ANSI
    module look like a module with NO PORTS, and this gate then reports every
    declared pin as `missing_in_v` — a mismatch it invented.

    MEASURED (u_hawaii_adc, 2026-09-02): `analog_a8_hardmacro_emit` writes the
    NON-ANSI form, so this gate reported
    `Block 'ldo': missing_in_v=['vin','vout','vref','vss'] extra_in_v=[]`
    for a Verilog view that declares exactly those four ports and nothing else
    — while the REAL disagreement, on another block, was reported beside it and
    read the same. A gate whose two verdicts are indistinguishable cannot be
    acted on.

    A name is taken from the non-ANSI header only when the body also declares
    it `input`/`output`/`inout`, so a stray identifier can never become a port.
    """
    m = _V_MODULE_RE.search(text)
    if not m:
        return set()
    ports_blob = m.group("ports")
    names: Set[str] = set()
    for pm in _V_PORT_DECL_RE.finditer(ports_blob):
        names.add(pm.group(1).strip().lower())
    if names:
        return names
    # Non-ANSI: bare names in the header, directions in the body.
    body = text[m.end():]
    declared = {d.group(1).strip().lower()
                for d in _V_PORT_DECL_RE.finditer(body)}
    for tok in ports_blob.split(","):
        bm = _V_BARE_PORT_RE.match(tok.strip().split("//")[0].strip()
                                   if tok.strip() else "")
        if bm and bm.group(1).lower() in declared:
            names.add(bm.group(1).lower())
    return names


def parse_spec_pins(data: dict) -> Set[str]:
    """Extract interface pin names from spec.json (interface.pins[].name)."""
    if not isinstance(data, dict):
        return set()
    iface = data.get("interface")
    if not isinstance(iface, dict):
        return set()
    pins = iface.get("pins")
    if not isinstance(pins, list):
        return set()
    out: Set[str] = set()
    for p in pins:
        if isinstance(p, dict) and isinstance(p.get("name"), str):
            out.add(p["name"].strip().lower())
        elif isinstance(p, str):
            out.add(p.strip().lower())
    return out


# ---------------------------------------------------------------------------


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    block: str = ""


@dataclass
class Result:
    program: str = "analog_hardmacro_pinname_consistency_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _discover_blocks(project: Path) -> List[str]:
    """Blocks that have a spec.json under analog/<block>/."""
    if _pl is not None:
        analog = _pl.analog_dir(project)
    else:
        analog = project / "analog"
    if not analog.is_dir():
        return []
    return sorted(p.parent.name for p in analog.glob("*/spec.json"))


def _hardmacro_dir(project: Path) -> Path:
    if _pl is not None:
        return _pl.hardmacro_dir(project)
    return project / "hardmacro"


def _analog_dir(project: Path) -> Path:
    if _pl is not None:
        return _pl.analog_dir(project)
    return project / "analog"


def run_audit(project: Path) -> Result:
    res = Result()
    blocks = _discover_blocks(project)
    if not blocks:
        res.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message="No analog blocks (analog/<block>/spec.json) found; nothing to check.",
        ))
        res.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return res

    hm_dir = _hardmacro_dir(project)
    an_dir = _analog_dir(project)
    checked = 0
    skipped: List[str] = []
    failed: List[str] = []

    for block in blocks:
        spec_path = an_dir / block / "spec.json"
        lef_path = hm_dir / block / f"{block}.lef"
        v_path = hm_dir / block / f"{block}.v"

        # spec interface
        try:
            spec_data = json.loads(spec_path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError) as exc:
            res.passed = False
            failed.append(block)
            res.findings.append(Finding(
                rule="SPEC_UNPARSEABLE", severity="ERROR", block=block,
                message=f"spec.json unreadable/garbage for '{block}': {exc}",
            ))
            continue
        spec_pins = parse_spec_pins(spec_data)

        # LEF pins
        lef_pins: Set[str] = set()
        lef_present = lef_path.exists()
        if lef_present:
            try:
                lef_pins = parse_lef_pins(lef_path.read_text(errors="replace"))
            except OSError:
                lef_present = False

        # Verilog ports
        v_ports: Set[str] = set()
        v_present = v_path.exists()
        if v_present:
            try:
                v_ports = parse_verilog_ports(v_path.read_text(errors="replace"))
            except OSError:
                v_present = False

        # Honest SKIP: nothing anywhere to compare.
        if not spec_pins and not lef_pins and not v_ports:
            skipped.append(block)
            res.findings.append(Finding(
                rule="BLOCK_SKIP_NO_INTERFACE", severity="INFO", block=block,
                message=(f"Block '{block}' exposes no interface pins in "
                         f"spec/LEF/Verilog; cannot compare (skip)."),
            ))
            continue

        checked += 1
        block_ok = True

        # Golden source = spec interface when present; else fall back to
        # requiring LEF==Verilog (both must agree even without a spec).
        if spec_pins:
            if v_present:
                missing_v = spec_pins - v_ports
                extra_v = v_ports - spec_pins
                if missing_v or extra_v:
                    block_ok = False
                    res.findings.append(Finding(
                        rule="VERILOG_SPEC_MISMATCH", severity="ERROR", block=block,
                        message=(f"Block '{block}': Verilog ports do not match "
                                 f"spec interface. missing_in_v={sorted(missing_v)} "
                                 f"extra_in_v={sorted(extra_v)}"),
                    ))
            else:
                block_ok = False
                res.findings.append(Finding(
                    rule="VERILOG_MISSING", severity="ERROR", block=block,
                    message=(f"Block '{block}': spec declares interface pins "
                             f"{sorted(spec_pins)} but {block}.v is absent/portless."),
                ))

            # LEF: PIN names must be a subset-or-equal of the spec pin set.
            # A LEF may legitimately omit power/ground PINs (modeled as
            # special-nets), so we require every declared LEF PIN to be a
            # spec pin (no foreign pins) AND that LEF is not empty when the
            # spec has signal pins. An empty-PIN LEF with a spec interface
            # is a FAIL (the abstract exposes nothing to route to).
            if lef_present:
                foreign_lef = lef_pins - spec_pins
                if foreign_lef:
                    block_ok = False
                    res.findings.append(Finding(
                        rule="LEF_FOREIGN_PIN", severity="ERROR", block=block,
                        message=(f"Block '{block}': LEF declares PIN(s) "
                                 f"{sorted(foreign_lef)} not in the spec interface "
                                 f"(LVS-integration hazard)."),
                    ))
                if not lef_pins:
                    block_ok = False
                    res.findings.append(Finding(
                        rule="LEF_NO_PINS", severity="ERROR", block=block,
                        message=(f"Block '{block}': spec declares interface pins "
                                 f"but the LEF abstract exposes zero PINs."),
                    ))
            else:
                block_ok = False
                res.findings.append(Finding(
                    rule="LEF_MISSING", severity="ERROR", block=block,
                    message=f"Block '{block}': {block}.lef absent (cannot place macro).",
                ))
        else:
            # No spec interface, but LEF and/or Verilog expose pins —
            # require LEF and Verilog to agree with each other.
            if lef_pins and v_ports:
                missing = v_ports - lef_pins
                extra = lef_pins - v_ports
                if missing or extra:
                    block_ok = False
                    res.findings.append(Finding(
                        rule="LEF_VERILOG_MISMATCH", severity="ERROR", block=block,
                        message=(f"Block '{block}': LEF PINs and Verilog ports "
                                 f"disagree. lef_only={sorted(extra)} "
                                 f"v_only={sorted(missing)}"),
                    ))
            elif v_ports and lef_present and not lef_pins:
                # Verilog declares ports the LEF abstract exposes ZERO of:
                # the gate-level sim expects N connections but PnR has
                # nothing to route to — the documented LVS-integration
                # hazard. This is exactly the A7 stub (portless LEF +
                # ported behavioral Verilog).
                block_ok = False
                res.findings.append(Finding(
                    rule="LEF_NO_PINS", severity="ERROR", block=block,
                    message=(f"Block '{block}': Verilog declares ports "
                             f"{sorted(v_ports)} but the LEF abstract exposes "
                             f"zero PINs (nothing for PnR to route to)."),
                ))

        if block_ok:
            res.findings.append(Finding(
                rule="PINNAME_CONSISTENT", severity="INFO", block=block,
                message=(f"Block '{block}': pin names consistent across "
                         f"spec/LEF/Verilog ({sorted(spec_pins or v_ports or lef_pins)})."),
            ))
        else:
            failed.append(block)

    if failed:
        res.passed = False

    res.summary = {
        "skipped": False,
        "total_blocks": len(blocks),
        "checked": checked,
        "skipped_blocks": skipped,
        "failed_blocks": failed,
        "pass": res.passed,
    }
    return res


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    res = run_audit(args.project_dir)
    out = json.dumps(asdict(res), indent=2, ensure_ascii=False)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(res.summary)
    reason = _vx.skip_reason(res.summary)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)
    else:
        print(_vx.verdict_line("analog_hardmacro_pinname_consistency_check",
                               res.passed, skipped, reason))
        for f in res.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if res.passed and skipped:
        _vx.announce_vacuous(res.program, reason)
    return _vx.exit_code(res.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
