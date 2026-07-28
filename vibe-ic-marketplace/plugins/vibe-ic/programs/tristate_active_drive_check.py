#!/usr/bin/env python3
"""tristate_active_drive_check.py — P1.1 deterministic gate

Static check for FPGA designs with half-duplex bidirectional buses.
Detects pure open-drain tristate patterns (drive-low + tristate-high)
that rely on weak pull-ups for bus-HIGH transitions.  On FPGAs with
internal weak pull-ups and cable capacitance, the rise time may exceed
the protocol's BIT_HIGH timing window.

Multi-master protocols (I2C, 1-Wire, CAN, SMBus) legitimately require
open-drain — those are auto-skipped via L2 JSON protocol_type.

Usage:
    python3 tristate_active_drive_check.py <project_dir>
    python3 tristate_active_drive_check.py <project_dir> --json [PATH]

Exit codes:
    0 = PASS: inout ports were found and audited, and the drive form is
        acceptable
    1 = FAIL (pure open-drain on single-master protocol)
    2 = VACUOUS: nothing was examined — no RTL, no inout port in it, or the
        declared protocol makes open-drain correct so this gate holds no
        opinion. #521: all four used to be rc 0, on 171 of the 200 tracked
        project roots. Also rc 2 for an IO / parse error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List
import _path_layout as _pl
import _vacuous_exit as _vx

# Wave 36 (v0.119.68) — LIN is a single-master multi-slave protocol;
# strictly speaking it does not belong in MULTI_MASTER_PROTOCOLS.
# The current code path treats both sets identically (auto-skip),
# so behaviour is preserved; only the taxonomy is corrected.
MULTI_MASTER_PROTOCOLS = {"i2c", "1-wire", "one-wire", "onewire",
                          "can", "smbus"}
SINGLE_MASTER_MULTI_SLAVE_PROTOCOLS = {"lin"}
# Combined set used by the actual SKIP logic — preserves prior
# behaviour (LIN was auto-skipped before; still auto-skipped now).
OPEN_DRAIN_PROTOCOLS = MULTI_MASTER_PROTOCOLS | \
    SINGLE_MASTER_MULTI_SLAVE_PROTOCOLS

# L2 timing keys that indicate a half-duplex single-wire protocol whose
# pad form is governed by half_duplex_wrapper_open_drain_check (LL-17).
# When any of these are present, LL-17 owns the open-drain verdict (the
# empirically-validated form is `(oe && !tx) ? 1'b0 : 1'bz` — drive-low +
# Hi-Z, **NOT** active-drive). This gate must skip rather than emit a
# contradicting WARN/FAIL on the same pad.
HALF_DUPLEX_L2_KEYS = (
    "tSRS_us", "tSRS_min_us", "tSRS_max_us",
    "ibt_us", "ibt_min_us", "ibt_max_us",
    "frame_end_gap_us",
)

# v0.119.20: skip optional type qualifier (`wire`/`logic`/`reg`/`tri`)
# so we capture the actual port name, not the type. Earlier regex
# captured the literal `wire` for `inout wire id_bus` declarations.
INOUT_RE = re.compile(
    r"\binout\b\s+"
    r"(?:(?:wire|logic|reg|tri|tri0|tri1|wand|wor)\s+)?"
    r"(?:\[\s*[\w\d:]+\s*\]\s*)?"
    r"(\w+)",
    re.IGNORECASE,
)

# v0.119.20: capture LHS pad name so SKIP can be applied per-pad rather
# than for the whole project. Mirrors the LL-17 PIN_NAME_HINTS set so a
# half-duplex pad in a mixed-pad project is correctly handed to LL-17
# while other tristate pads continue to be checked here.
TRISTATE_ACTIVE_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*\w+\s*\?\s*\w+\s*:\s*1'bz",
    re.IGNORECASE,
)

OPEN_DRAIN_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*\w+\s*\?\s*1'b0\s*:\s*1'bz",
    re.IGNORECASE,
)

OE_ACTIVE_HIGH_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*\w+\s*\?\s*(?!1'b0\b)\w+\s*:\s*1'bz",
    re.IGNORECASE,
)

# Mirror of half_duplex_wrapper_open_drain_check.py PIN_NAME_HINTS.
# When LL-17 detects a half-duplex single-wire pad by these substrings,
# this gate must defer to LL-17's verdict on that specific pad.
HALF_DUPLEX_PIN_HINTS = (
    "id_bus", "lin_bus", "kline_bus",
    "owire", "1wire", "single_wire", "halfduplex_bus",
)


def _is_half_duplex_pad_name(name: str) -> bool:
    nl = name.lower()
    return any(h in nl for h in HALF_DUPLEX_PIN_HINTS)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "tristate_active_drive_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def discover_rtl_files(base: Path) -> List[Path]:
    exts = {".v", ".sv", ".vh", ".svh"}
    return sorted(p for p in base.rglob("*") if p.suffix.lower() in exts)


def _load_l2_protocol(project_dir: Path, l2_path: Path | None) -> str | None:
    candidates: list[Path] = []
    if l2_path and l2_path.is_file():
        candidates.append(l2_path)
    gen = _pl.generated_docs_dir(project_dir)
    if gen.is_dir():
        candidates.extend(sorted(gen.glob("L2_*.json")))
    for p in candidates:
        try:
            data = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        for key in ("protocol_type", "bus_type", "interface_type"):
            val = data.get(key, "")
            if isinstance(val, str):
                return val.lower()
            if isinstance(val, list):
                return " ".join(str(v) for v in val).lower()
        pad = data.get("pad_drive_mode", "")
        if isinstance(pad, str) and pad.lower() == "open_drain":
            return "open_drain"
    return None


def _is_half_duplex_single_wire(project_dir: Path, l2_path: Path | None) -> bool:
    """Detect projects where LL-17 (half_duplex_wrapper_open_drain_check) is
    the authoritative gate for pad-form. Returns True if any L2 file
    contains half-duplex timing keys (tSRS / ibt / frame_end_gap)."""
    candidates: list[Path] = []
    if l2_path and l2_path.is_file():
        candidates.append(l2_path)
    gen = _pl.generated_docs_dir(project_dir)
    if gen.is_dir():
        candidates.extend(sorted(gen.glob("L2_*.json")))
    for p in candidates:
        try:
            data = json.loads(p.read_text(errors="replace"))
        except Exception:
            continue
        if any(k in data for k in HALF_DUPLEX_L2_KEYS):
            return True
    return False


def run_audit(project_dir: Path, l2_path: Path | None = None) -> AuditResult:
    result = AuditResult()

    # v0.119.20: SKIP is now PAD-SCOPED rather than project-wide.
    # When the project is half-duplex single-wire, LL-17 owns the pad-
    # form verdict for half-duplex pads (id_bus / lin_bus / owire / ...).
    # Other tristate pads in the same project (e.g. a debug GPIO with
    # `oe ? 1'b0 : 1'bz`) are still analyzed here.
    #
    # Wave 35 (v0.119.67) — behavior-based fix: an inout port whose
    # name is a half-duplex hint (id_bus / kline_bus / owire / ...) is
    # ITSELF determinative evidence of half-duplex single-wire pad form
    # regardless of L2 schema content. Earlier the L2 schema check was
    # the sole gate for is_hd_project; agents that emit non-canonical
    # L2 schemas got false-positive FAILs on the open-drain pad. The
    # pad-name evidence is now sufficient.
    is_hd_project = _is_half_duplex_single_wire(project_dir, l2_path)

    protocol = _load_l2_protocol(project_dir, l2_path)
    if protocol:
        for mm in OPEN_DRAIN_PROTOCOLS:
            if mm in protocol:
                cat = ("multi-master" if mm in MULTI_MASTER_PROTOCOLS
                       else "single-master multi-slave")
                result.findings.append(Finding(
                    rule="SKIP_MULTI_MASTER",
                    severity="INFO",
                    message=(f"Protocol '{protocol}' is {cat}; "
                             f"open-drain is correct. Skipping."),
                ))
                result.summary = {"skipped": True, "reason": "multi_master_protocol"}
                return result
        if protocol == "open_drain":
            result.findings.append(Finding(
                rule="SKIP_MULTI_MASTER",
                severity="INFO",
                message="L2 pad_drive_mode is open_drain; open-drain is intentional. Skipping.",
            ))
            result.summary = {"skipped": True, "reason": "pad_drive_mode_open_drain"}
            return result

    rtl_dir = _pl.rtl_dir(project_dir)
    base = rtl_dir if rtl_dir.is_dir() else project_dir
    rtl_files = discover_rtl_files(base)

    if not rtl_files:
        result.findings.append(Finding(
            rule="SKIP_NO_INOUT",
            severity="INFO",
            message="No RTL files found; skipping tristate active-drive check.",
        ))
        result.summary = {"skipped": True, "reason": "no_rtl"}
        return result

    inout_ports: list[dict] = []
    for fpath in rtl_files:
        try:
            lines = fpath.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            # v0.119.20: use finditer so a single line declaring multiple
            # inout ports (e.g. `inout wire id_bus, inout wire dbg_pad`)
            # captures both, not just the first.
            for m in INOUT_RE.finditer(line):
                inout_ports.append({"name": m.group(1), "file": str(fpath), "line": i})

    if not inout_ports:
        result.findings.append(Finding(
            rule="SKIP_NO_INOUT",
            severity="INFO",
            message="No inout ports found in RTL; tristate check not applicable.",
        ))
        result.summary = {"skipped": True, "reason": "no_inout"}
        return result

    # v0.119.20: pad-scoped skip — emit SKIP per half-duplex-named inout
    # port. This catches both `oe ? 1'b0 : 1'bz` (the simple tristate
    # OPEN_DRAIN_RE matches) AND the canonical LL-17 form
    # `(oe && !tx) ? 1'b0 : 1'bz` (parenthesized condition that
    # OPEN_DRAIN_RE intentionally doesn't match — that form is the
    # endorsed split-data open-drain that synth places as a pin-local
    # LUT).
    hd_pads_skipped: list[str] = []
    # Wave 35 (v0.119.67): an inout port name in HALF_DUPLEX_PIN_HINTS
    # is itself sufficient to defer pad-form verdict to LL-17 — even
    # when L2 schema doesn't explicitly carry tSRS/ibt timing keys.
    # The pad name itself proves half-duplex single-wire intent.
    for port in inout_ports:
        if is_hd_project or _is_half_duplex_pad_name(port["name"]):
            if _is_half_duplex_pad_name(port["name"]):
                hd_pads_skipped.append(port["name"])
                result.findings.append(Finding(
                    rule="SKIP_HALF_DUPLEX_SINGLE_WIRE",
                    severity="INFO",
                    message=(
                        f"Pad '{port['name']}' is a half-duplex single-wire "
                        "bus; half_duplex_wrapper_open_drain_check (LL-17) "
                        "owns the verdict for this pad."
                    ),
                    file=port["file"],
                    line=port["line"],
                ))
    hd_pad_names = set(hd_pads_skipped)

    open_drain_found = 0
    active_drive_found = 0

    for fpath in rtl_files:
        try:
            text = fpath.read_text(errors="replace")
            lines = text.splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            m_od = OPEN_DRAIN_RE.search(line)
            if m_od:
                pad_name = m_od.group(1)
                # Skip the WARN for pads already handed to LL-17.
                if pad_name in hd_pad_names:
                    continue
                open_drain_found += 1
                result.findings.append(Finding(
                    rule="OPEN_DRAIN_FPGA_WARN",
                    severity="WARNING",
                    message=(
                        "Pure open-drain tristate pattern detected "
                        "(drive-low + tristate-high). On FPGAs with weak pull-up, "
                        "bus rise time may exceed protocol BIT_HIGH window. "
                        "Consider active-drive-high during BIT_HIGH/IBT phases."
                    ),
                    file=str(fpath),
                    line=i,
                ))
            else:
                m_ad = OE_ACTIVE_HIGH_RE.search(line)
                if m_ad:
                    pad_name = m_ad.group(1)
                    if pad_name in hd_pad_names:
                        continue
                    active_drive_found += 1
                    result.findings.append(Finding(
                        rule="ACTIVE_DRIVE_OK",
                        severity="INFO",
                        message="Active-drive tristate pattern (data-driven HIGH) detected.",
                        file=str(fpath),
                        line=i,
                    ))

    if open_drain_found > 0 and active_drive_found == 0:
        result.passed = False

    result.summary = {
        "inout_ports": len(inout_ports),
        "open_drain_patterns": open_drain_found,
        "active_drive_patterns": active_drive_found,
        "half_duplex_pads_skipped": hd_pads_skipped,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    ap.add_argument("--l2-json", type=Path, default=None)
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir, l2_path=args.l2_json)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    # The examined path builds a summary with COUNTS and no `skipped` key at
    # all, which `summary_is_skipped` reads as "examined something" — the
    # fail-safe direction, and why a real audit here still exits 0.
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
        print(_vx.verdict_line("tristate_active_drive_check", result.passed,
                               skipped, reason))
        print(f"  inout ports: {result.summary.get('inout_ports', 0)}")
        print(f"  open-drain patterns: {result.summary.get('open_drain_patterns', 0)}")
        print(f"  active-drive patterns: {result.summary.get('active_drive_patterns', 0)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                loc = f"{f.file}:{f.line}" if f.file else ""
                print(f"  [{f.severity}] {f.rule}: {f.message} {loc}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
