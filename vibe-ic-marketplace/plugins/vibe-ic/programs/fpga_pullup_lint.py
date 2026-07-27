#!/usr/bin/env python3
"""
fpga_pullup_lint.py — Flag tristate inout ports without weak pull-up assignment.

Common bug class: an RTL tristate `inout` port wired to a single-wire bus
(I2C, ID-bus, Apple AID, OneWire, ...) requires a weak pull-up on the FPGA
pin to define the bus state when no driver is active. Without the pull-up,
the first power-up emits garbage until something pulls the bus, and the
host tester sees nothing or sees random framing → first-burn FAIL with no
diagnostic.

This gate cross-checks RTL `inout` ports against the FPGA constraints file
(.qsf for Quartus, .xdc for Vivado) and flags any inout pin that does not
have a weak-pullup directive.

Generality: ANY single-wire / open-drain protocol on FPGA prototype boards.
No chip / tester / PDK / vendor names baked in.

Usage:
    python3 fpga_pullup_lint.py \\
        --rtl-dir ./rtl/ \\
        --top-module my_top \\
        --constraint ./fpga/my_top.qsf

    python3 fpga_pullup_lint.py \\
        --rtl-dir ./rtl/ \\
        --top-module my_top \\
        --constraint ./fpga/my_top.xdc

Exit codes:
    0 = PASS (every inout has a weak pull-up directive)
    1 = FAIL (one or more inouts lack pull-up)
    2 = Usage / file error
"""
from __future__ import annotations
import argparse, json, re, sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Dict


# Match `inout [width] name` and `inout name` in module port lists.
INOUT_PORT_RE = re.compile(
    r'\binout\s+(?:wire\s+|reg\s+|logic\s+)?(?:\[[^\]]+\]\s*)?(\w+)\b',
    re.IGNORECASE,
)
# Module top-level: `module my_top (...)` or `module my_top #(...) (...)`
MODULE_RE = re.compile(r'^\s*module\s+(\w+)\b', re.IGNORECASE)

# Quartus QSF directives
# `set_location_assignment PIN_X -to my_signal`
QSF_PIN_RE = re.compile(
    r'set_location_assignment\s+\S+\s+-to\s+(\S+)',
    re.IGNORECASE,
)
# `set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON -to my_signal`
QSF_PULLUP_RE = re.compile(
    r'set_instance_assignment\s+-name\s+WEAK_PULL_UP_RESISTOR\s+ON\s+-to\s+(\S+)',
    re.IGNORECASE,
)

# Vivado XDC directives
# `set_property PACKAGE_PIN X -to [get_ports my_signal]`
XDC_PIN_RE = re.compile(
    r'set_property\s+PACKAGE_PIN\s+\S+\s+\[get_ports\s+\{?(\w+)',
    re.IGNORECASE,
)
# `set_property PULLUP TRUE [get_ports my_signal]` or `set_property PULLTYPE PULLUP`
XDC_PULLUP_RE = re.compile(
    r'set_property\s+(?:PULLUP\s+TRUE|PULLTYPE\s+PULLUP|IOSTANDARD\s+\w+\s+PULLUP\s+TRUE)\s+\[get_ports\s+\{?(\w+)',
    re.IGNORECASE,
)


@dataclass
class Finding:
    signal: str
    file: str
    line: int
    constraint_file: str
    has_pin_assignment: bool
    has_pullup: bool
    severity: str


@dataclass
class Result:
    status: str
    findings: List[Finding] = field(default_factory=list)
    inout_signals: List[str] = field(default_factory=list)
    constraint_format: str = ""


def find_inouts_in_top(rtl_dir: Path, top_module: str) -> List[tuple]:
    """Return [(signal, file, line)] for every inout port in the top module."""
    out: List[tuple] = []
    for ext in (".v", ".sv"):
        for f in sorted(rtl_dir.rglob(f"*{ext}")):
            try:
                lines = f.read_text(errors="replace").splitlines()
            except Exception:
                continue
            in_top = False
            for i, raw in enumerate(lines, 1):
                stripped = raw.strip()
                if stripped.startswith("//"):
                    continue
                m_mod = MODULE_RE.match(stripped)
                if m_mod:
                    in_top = (m_mod.group(1) == top_module)
                    continue
                if not in_top:
                    continue
                if "endmodule" in stripped:
                    in_top = False
                    continue
                m_in = INOUT_PORT_RE.search(raw)
                if m_in:
                    out.append((m_in.group(1), str(f), i))
    return out


def parse_constraint_qsf(path: Path) -> Dict[str, dict]:
    """Return {signal: {has_pin: bool, has_pullup: bool}} for Quartus QSF."""
    info: Dict[str, dict] = {}
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return info
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        m = QSF_PIN_RE.search(line)
        if m:
            sig = m.group(1)
            info.setdefault(sig, {"has_pin": False, "has_pullup": False})["has_pin"] = True
        m = QSF_PULLUP_RE.search(line)
        if m:
            sig = m.group(1)
            info.setdefault(sig, {"has_pin": False, "has_pullup": False})["has_pullup"] = True
    return info


def parse_constraint_xdc(path: Path) -> Dict[str, dict]:
    info: Dict[str, dict] = {}
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return info
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        m = XDC_PIN_RE.search(line)
        if m:
            sig = m.group(1)
            info.setdefault(sig, {"has_pin": False, "has_pullup": False})["has_pin"] = True
        m = XDC_PULLUP_RE.search(line)
        if m:
            sig = m.group(1)
            info.setdefault(sig, {"has_pin": False, "has_pullup": False})["has_pullup"] = True
    return info


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--rtl-dir", required=True, type=Path)
    ap.add_argument("--top-module", required=True, type=str,
                    help="Name of the top RTL module whose inout ports to lint")
    ap.add_argument("--constraint", required=True, type=Path,
                    help="Path to .qsf (Quartus) or .xdc (Vivado)")
    # #494 — a read-only validator writes NOTHING unless a caller asks for it.
    # See the sibling note in `sustained_vs_edge_check.py`: a hardcoded
    # `/tmp/<gatename>` default made every invocation deposit a report at a
    # fixed shared path, which concurrent runs overwrite without a trace and
    # which is a standing symlink-hijack target on a multi-user host. This gate
    # has TWO write sites — the no-inout early return below and the normal
    # verdict — and both are guarded.
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Directory to write the JSON report into. Omitted "
                         "(the default) = write no file at all; the verdict "
                         "goes to stdout only.")
    args = ap.parse_args(argv)

    if not args.rtl_dir.is_dir():
        print(f"ERROR: rtl-dir not found: {args.rtl_dir}", file=sys.stderr)
        return 2
    if not args.constraint.is_file():
        print(f"ERROR: constraint not found: {args.constraint}", file=sys.stderr)
        return 2
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Find every inout port in top module
    inouts = find_inouts_in_top(args.rtl_dir, args.top_module)
    if not inouts:
        # No inouts → trivially PASS
        res = Result(status="PASS", findings=[], inout_signals=[],
                     constraint_format=args.constraint.suffix.lower().lstrip("."))
        # #494 — write site 1 of 2. This path never printed a `json:` line, so
        # its stdout is unchanged either way.
        if args.out_dir is not None:
            out_json = args.out_dir / "fpga_pullup_lint.json"
            out_json.write_text(json.dumps(asdict(res), indent=2))
        print("fpga_pullup_lint: PASS — no inout ports in top module")
        return 0

    # 2. Parse constraint file
    suf = args.constraint.suffix.lower()
    if suf == ".qsf":
        ci = parse_constraint_qsf(args.constraint)
        cfmt = "qsf"
    elif suf == ".xdc":
        ci = parse_constraint_xdc(args.constraint)
        cfmt = "xdc"
    else:
        print(f"ERROR: unsupported constraint format: {suf} (need .qsf or .xdc)", file=sys.stderr)
        return 2

    # 3. Cross-check
    findings: List[Finding] = []
    for sig, fpath, lineno in inouts:
        meta = ci.get(sig, {"has_pin": False, "has_pullup": False})
        has_pin = meta["has_pin"]
        has_pullup = meta["has_pullup"]
        if has_pin and has_pullup:
            severity = "OK"
        elif has_pin and not has_pullup:
            severity = "ERROR"
        elif not has_pin:
            severity = "WARN"  # not pinned at all — maybe intentional (internal-only)
        if severity != "OK":
            findings.append(Finding(
                signal=sig, file=fpath, line=lineno,
                constraint_file=str(args.constraint),
                has_pin_assignment=has_pin,
                has_pullup=has_pullup,
                severity=severity,
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    status = "FAIL" if errors else "PASS"
    res = Result(
        status=status,
        findings=findings,
        inout_signals=[s for s, _, _ in inouts],
        constraint_format=cfmt,
    )
    # #494 — write site 2 of 2; position preserved so stdout is byte-identical
    # when --out-dir IS supplied.
    out_json = None
    if args.out_dir is not None:
        out_json = args.out_dir / "fpga_pullup_lint.json"
        out_json.write_text(json.dumps(asdict(res), indent=2))
    print(f"fpga_pullup_lint: {status} — {len(errors)} errors, {len(findings) - len(errors)} warnings")
    print(f"inout ports in top: {[s for s, _, _ in inouts]}")
    for f in findings:
        print(f"  [{f.severity}] {f.signal} (RTL {f.file}:{f.line}) — pinned={f.has_pin_assignment} pullup={f.has_pullup}")
    if out_json is not None:
        print(f"json: {out_json}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
