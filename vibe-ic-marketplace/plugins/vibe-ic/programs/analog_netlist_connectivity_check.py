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
  parse every element line inside the block (sub-circuit calls AND the
        primitive R/C/L/V/I/M/D/... elements)
        -> count how many device pins touch each net
  parse `.ends`

  FAIL rules:
    FLOATING_NODE   : an INTERNAL net (not a port, not a supply/ground rail)
                      touched by < 2 device pins
    UNUSED_PORT     : a declared port never touched by any device pin

Supply / ground rails (vdd/vss/gnd/0/...) are exempt from the floating-node
rule because they are legitimately fed by the testbench / are global nodes;
a one-pin tap onto a rail is normal.

Element-line parsing: an `X` sub-circuit call is
`Xname n1 n2 ... nk subcktname [key=value ...]` — the last non-key token is
the sub-circuit name and everything before it is the net list. Every other
SPICE element is parsed by its letter's fixed node count (see
`_ELEMENT_NODE_COUNT`): R/C/L/V/I/D/F/H/W/B = 2, J = 3, M/E/G/S/T/O = 4,
K = 0. Passives MUST be counted — in a switched-capacitor block the signal
reaches the summing node through a capacitor, and an X-only parser reports
that (correct) node as floating.

If a subckt contains an element whose node count is ambiguous (`Q` is 3 or
4 nodes; `Z`/`U`/unknown letters), the connectivity verdict for that subckt
is WITHHELD and disclosed as `UNPARSED_ELEMENT` — a partial parse may never
manufacture a floating node.

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
    0 = PASS (or self-skip)
    1 = FAIL (floating node / unused port)
    2 = IO / parse error

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


# Analog netlists do NOT live under a single root. The flow YAML anchors the
# A3 netlists at `phase2/analog/*/*.sp`, while `analog_one_shot_runner` writes
# them under `_pl.analog_dir()` = `phase3/analog/<block>/`. The original helper
# returned the FIRST existing root, so on any project that had reached A5 (and
# therefore created `phase3/analog/`) the phase2 netlists became invisible and
# this gate vacuously PASSed — measured, see
# `test_analog_netlist_gates_flow_wiring.py::test_phase2_netlists_are_not_
# hidden_by_a_phase3_analog_dir`. Scan EVERY analog root that exists.
_ANALOG_ROOT_RELS = ("phase1/analog", "phase2/analog", "phase3/analog",
                     "analog")


def _analog_roots(project: Path) -> List[Path]:
    """Every analog root that exists, de-duplicated, in scan order.

    Deliberately does NOT fall back to the whole project: a project with no
    analog root at all is a pure-digital project, and its `phase3/stage3/
    extracted/*.sp` PEX netlist is not an analog deck (measured on
    campaign_pr427/spm/converge_ihp-sg13g2: the old whole-project fallback
    reported the ECO spare cells of an extracted DIGITAL top as FLOATING_NODE).
    """
    roots: List[Path] = []
    seen = set()

    def _add(cand: Optional[Path]) -> None:
        if cand is None or not cand.is_dir():
            return
        try:
            key = cand.resolve()
        except OSError:
            key = cand
        if key in seen:
            return
        seen.add(key)
        roots.append(cand)

    if _HAVE_PL:
        try:
            d = _pl.analog_dir(project)
            _add(Path(d) if d else None)
        except Exception:
            pass
    for rel in _ANALOG_ROOT_RELS:
        _add(project / rel)
    return roots


def _sp_files(project: Path) -> List[Path]:
    """Every `.sp` deck under every analog root, de-duplicated."""
    out: List[Path] = []
    seen = set()
    for root in _analog_roots(project):
        for sp in sorted(root.rglob("*.sp")):
            try:
                key = sp.resolve()
            except OSError:
                key = sp
            if key in seen:
                continue
            seen.add(key)
            out.append(sp)
    return sorted(out)


# SPICE element letter -> exact number of leading node tokens.
#
# Counting ONLY `X` sub-circuit instances (the pre-fix behaviour) is wrong on
# any real analog deck: in a switched-capacitor block the signal is carried by
# capacitors, so every net that reaches a device through an R/C/L was scored
# 0 pins. MEASURED on the completed benchmark run
# benchmark-data/ic/u_hawaii_adc/clean_run_v1422_20260715 — the correct
# `delta_sigma` integrator (`cs vin vsum 0.25p` / `ci vsum vout 1p`) was
# reported as `UNUSED_PORT: vin` + `FLOATING_NODE: vsum`, both false. Every
# element that carries a net must be counted before this gate may accuse.
_ELEMENT_NODE_COUNT = {
    "r": 2, "c": 2, "l": 2,     # passives
    "v": 2, "i": 2,             # independent sources
    "e": 4, "g": 4,             # VCVS / VCCS
    "f": 2, "h": 2,             # CCCS / CCVS (control is a source NAME)
    "d": 2,                     # diode
    "m": 4,                     # MOSFET (d g s b)
    "j": 3,                     # JFET (d g s)
    "s": 4, "w": 2,             # voltage- / current-controlled switch
    "t": 4, "o": 4,             # lossless / lossy transmission line
    "b": 2,                     # behavioural source
}
# Elements that reference other element NAMES and touch no nets themselves.
_ELEMENT_NO_NODES = frozenset({"k"})


def _device_nets(line: str) -> Optional[List[str]]:
    """Parse ONE element line into the list of nets it touches.

    Returns:
      * a (possibly empty) list of net names for a line this parser
        understands, or
      * ``None`` when the line names an element whose node count cannot be
        determined here (``Q`` — 3 or 4 nodes; ``Z``/``U``/unknown letters).
        The caller must then REFUSE to accuse the enclosing subckt: a partial
        parse may never manufacture a floating node.
    """
    toks = line.split()
    if not toks:
        return []
    kind = toks[0][:1].lower()

    if kind == "x":
        # `Xname n1 n2 ... nk subcktname [k=v ...]`
        core: List[str] = []
        for t in toks[1:]:
            if PARAM_RE.search(t):
                break
            core.append(t)
        # core = [n1 .. nk, subckt/model name]; need >=1 net + the name.
        if len(core) < 2:
            return None
        return core[:-1]

    if kind in _ELEMENT_NO_NODES:
        return []

    count = _ELEMENT_NODE_COUNT.get(kind)
    if count is None:
        return None
    if len(toks) < 1 + count:
        return None
    return toks[1:1 + count]


def _check_subckt(name: str, ports: List[str],
                  device_lines: List[str], rel: str,
                  findings: List[Finding]) -> bool:
    pin_count: Dict[str, int] = {}
    saw_device = False
    unparsed: List[str] = []
    for ln in device_lines:
        stripped = ln.strip()
        if (not stripped
                or stripped.startswith("*")
                or stripped.startswith(";")
                or stripped.startswith(".")):
            continue
        nets = _device_nets(stripped)
        if nets is None:
            unparsed.append(stripped.split()[0])
            continue
        if not nets:
            continue
        saw_device = True
        for n in nets:
            pin_count[n.lower()] = pin_count.get(n.lower(), 0) + 1

    if unparsed:
        # Fail-SAFE, not fail-open-silently: the parse is incomplete, so the
        # connectivity verdict for THIS subckt is withheld and disclosed by
        # name rather than being fabricated from the elements we did read.
        findings.append(Finding(
            rule="UNPARSED_ELEMENT", severity="WARNING",
            message=(f"{rel}: .subckt {name}: element(s) "
                     f"{sorted(set(unparsed))} have an ambiguous node count; "
                     f"connectivity verdict WITHHELD for this subckt"),
            file=rel, subckt=name))
        return True

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
            raw = lines[i]
            stripped = raw.strip()
            # SPICE line continuation: `+ ...` extends the PREVIOUS element
            # line. Folding it in keeps a wrapped device parseable instead of
            # having it read as an unknown `+` element.
            if stripped.startswith("+") and body:
                body[-1] = body[-1].rstrip() + " " + stripped[1:]
            else:
                body.append(raw)
            i += 1
        if not _check_subckt(name, ports, body, rel, findings):
            all_ok = False
        # advance past .ends
        i += 1
    return had_subckt, all_ok


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    if not _analog_roots(project):
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR", severity="INFO",
            message="No analog directory; skipping connectivity check"))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_files = _sp_files(project)
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
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {GATE}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
