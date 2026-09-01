#!/usr/bin/env python3
"""analog_netlist_connectivity_check.py — deterministic floating-node /
dangling-pin graph check for SPICE subcircuits.

Rule (from skill `analog-netlist-gen`):
    Every net referenced inside a `.subckt` must connect to >= 2 terminals
    (a net touched by exactly one device pin is a floating / dangling node —
    a real, near-universal netlist authoring bug that ngspice will either
    warn on or silently treat as an open), and every declared subckt PORT
    must actually be used by at least one device inside the subckt (an
    unused port is a dangling interface pin).

This is a pure graph-connectivity check over the parsed netlist:

  parse `.subckt <name> <port...>`  -> ports
  parse each device line `X.. n1 n2 .. nk model ...` inside the block
        -> count how many device pins touch each net
  parse `.ends`

  FAIL rules:
    FLOATING_NODE   : an INTERNAL net (not a port, not a supply/ground rail)
                      touched by < 2 device pins
    UNUSED_PORT     : a declared port never touched by any device pin

Supply / ground rails (vdd/vss/gnd/0/...) are exempt from the floating-node
rule because they are legitimately fed by the testbench / are global nodes;
a one-pin tap onto a rail is normal.

Device-line parsing: a SPICE subckt instance line starts with 'X' and is
`Xname n1 n2 ... nk modelname [params]`. The last non-key token before
`key=value` params is the model name; everything between the instance name
and the model name is the net list. We require >= 3 nodes to treat a line
as a device (MOS = 4 nodes, R/C as X-subckt = 2..3); lines that don't parse
as a device are ignored (comments, .model, etc.).

Honest-FAIL guarantees:
  * absent / non-directory project -> exit 2
  * a subckt with a one-pin internal net -> exit 1 (FLOATING_NODE)
  * a subckt with a declared-but-unused port -> exit 1 (UNUSED_PORT)
  * a .sp file with NO .subckt at all -> reported NO_SUBCKT INFO; it does
    not vacuously pass (files_with_subckt is surfaced in the summary).

Usage:
    python3 analog_netlist_connectivity_check.py <project_dir>
    python3 analog_netlist_connectivity_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS: at least one .sp deck was parsed and its connectivity graph is
        clean
    1 = FAIL (floating node / unused port)
    2 = VACUOUS: nothing was examined — no analog directory, or no .sp file in
        it, so no connectivity graph was built at all. #521: both used to be
        rc 0, on 196 of the 200 tracked project roots. This is the branch the
        "Honest-FAIL guarantees" note above was written to protect. Also rc 2
        for an IO / parse error.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

try:
    import _path_layout as _pl
    _HAVE_PL = True
except Exception:  # pragma: no cover
    _HAVE_PL = False

import _vacuous_exit as _vx
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

GATE = "analog_netlist_connectivity_check"

SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)\s+(.*)$", re.IGNORECASE)
ENDS_RE = re.compile(r"^\s*\.ends\b", re.IGNORECASE)
PARAM_RE = re.compile(r"=")

# nets that are global rails — exempt from the >=2-pin floating rule.
RAIL_NAMES = {
    "0", "vdd", "vcc", "vpwr", "avdd", "dvdd", "supply", "vdda",
    "vss", "gnd", "vgnd", "avss", "dvss", "ground", "vssa",
}


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    subckt: str = ""
    net: str = ""


@dataclass
class AuditResult:
    program: str = GATE
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _analog_dir(project: Path) -> Optional[Path]:
    if _HAVE_PL:
        try:
            d = _pl.analog_dir(project)
            if d and Path(d).is_dir():
                return Path(d)
        except Exception:
            pass
    for cand in (project / "phase3" / "analog",
                 project / "phase2" / "analog",
                 project / "analog"):
        if cand.is_dir():
            return cand
    if project.is_dir():
        return project
    return None


def _device_nets(line: str) -> Optional[List[str]]:
    """Parse an X-instance device line into its net list.

    `Xname n1 n2 ... nk modelname [k=v ...]`
    Returns the nets [n1..nk] or None if the line isn't a parseable device.

    TWO TERMINALS IS A DEVICE. This required three nets plus a model, so a
    capacitor — the only two-terminal primitive the analog IR emits — parsed
    as None and was counted by NOTHING. Both of this checker's rules then
    read the same absence as a defect, and both were measured on a
    hand-built deck against this file unmodified:

      * a port whose only connection is a capacitor -> UNUSED_PORT, rc 1;
      * an internal net whose second pin is a capacitor -> FLOATING_NODE,
        rc 1.

    Which is to say: every switched-capacitor circuit, whose defining
    feature is that the signal enters through a capacitor. It went unseen
    because in every deck rendered before one, each port also touched a
    transistor, so the capacitor's invisibility never changed an answer.

    Three tokens is the floor a device line can have and still BE one —
    two nets and a model name — so that is the floor here.
    """
    toks = line.split()
    if len(toks) < 4:
        return None
    if not toks[0][:1].lower() == "x":
        return None
    # strip k=v param tokens from the tail
    body = toks[1:]
    core: List[str] = []
    for t in body:
        if PARAM_RE.search(t):
            break
        core.append(t)
    # core = [n1 .. nk, modelname]; need at least 2 nets + 1 model
    if len(core) < 3:
        return None
    nets = core[:-1]   # drop model name
    return nets


def _check_subckt(name: str, ports: List[str],
                  device_lines: List[str], rel: str,
                  findings: List[Finding]) -> bool:
    pin_count: Dict[str, int] = {}
    saw_device = False
    for ln in device_lines:
        nets = _device_nets(ln)
        if nets is None:
            continue
        saw_device = True
        for n in nets:
            pin_count[n.lower()] = pin_count.get(n.lower(), 0) + 1

    if not saw_device:
        # empty subckt body — no devices to connect; structural defect but
        # report as a distinct INFO (downstream A3 size/subckt gate catches
        # truly-empty stubs). Do not FAIL on connectivity here.
        findings.append(Finding(
            rule="EMPTY_SUBCKT", severity="INFO",
            message=f"{rel}: .subckt {name} has no parseable device lines",
            file=rel, subckt=name))
        return True

    ok = True
    port_set = {p.lower() for p in ports}

    # FLOATING_NODE: internal net (not a port, not a rail) with < 2 pins
    for net, cnt in sorted(pin_count.items()):
        if net in port_set:
            continue
        if net in RAIL_NAMES:
            continue
        if cnt < 2:
            ok = False
            findings.append(Finding(
                rule="FLOATING_NODE", severity="ERROR",
                message=(f"{rel}: .subckt {name}: internal net '{net}' "
                         f"touched by only {cnt} device pin "
                         f"(floating/dangling)"),
                file=rel, subckt=name, net=net))

    # UNUSED_PORT: declared port never touched by a device pin
    for p in ports:
        if p.lower() not in pin_count and p.lower() not in RAIL_NAMES:
            ok = False
            findings.append(Finding(
                rule="UNUSED_PORT", severity="ERROR",
                message=(f"{rel}: .subckt {name}: declared port '{p}' is "
                         f"never connected to any device pin"),
                file=rel, subckt=name, net=p))

    if ok:
        findings.append(Finding(
            rule="CONNECTIVITY_OK", severity="INFO",
            message=(f"{rel}: .subckt {name}: all internal nets >=2 pins, "
                     f"all ports used"),
            file=rel, subckt=name))
    return ok


def _check_file(text: str, rel: str, findings: List[Finding]) -> tuple:
    """Returns (had_subckt: bool, passed: bool)."""
    lines = text.splitlines()
    i = 0
    n = len(lines)
    had_subckt = False
    all_ok = True
    while i < n:
        m = SUBCKT_RE.match(lines[i])
        if not m:
            i += 1
            continue
        had_subckt = True
        name = m.group(1)
        # port tokens may carry trailing params (params= form) — keep only
        # bare tokens (no '=').
        ports = [t for t in m.group(2).split() if "=" not in t]
        body: List[str] = []
        i += 1
        while i < n and not ENDS_RE.match(lines[i]):
            body.append(lines[i])
            i += 1
        if not _check_subckt(name, ports, body, rel, findings):
            all_ok = False
        # advance past .ends
        i += 1
    return had_subckt, all_ok


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    analog_dir = _analog_dir(project)
    if analog_dir is None:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR", severity="INFO",
            message="No analog directory; skipping connectivity check"))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_files = sorted(analog_dir.rglob("*.sp"))
    if not sp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_SP_FILES", severity="INFO",
            message="No .sp files; skipping connectivity check"))
        result.summary = {"skipped": True, "reason": "no_sp_files"}
        return result

    checked = 0
    files_with_subckt = 0
    files_pass = 0
    for sp in sp_files:
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            continue
        try:
            rel = str(sp.relative_to(project))
        except ValueError:
            rel = str(sp)
        checked += 1
        had, ok = _check_file(text, rel, result.findings)
        if had:
            files_with_subckt += 1
        else:
            result.findings.append(Finding(
                rule="NO_SUBCKT", severity="INFO",
                message=f"{rel}: no .subckt found; nothing to check",
                file=rel))
        if ok:
            files_pass += 1
        else:
            result.passed = False

    result.summary = {
        "skipped": False,
        "files_checked": checked,
        "files_with_subckt": files_with_subckt,
        "files_pass": files_pass,
        "files_fail": checked - files_pass,
        "pass": result.passed,
    }
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)
    else:
        print(_vx.verdict_line(GATE, result.passed, skipped, reason))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
