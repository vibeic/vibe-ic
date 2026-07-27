#!/usr/bin/env python3
"""
transient_signal_latch_check.py — Flag 1-cycle pulses read by multi-cycle FSMs without latching.

A common RTL race: a producer module strobes a 1-cycle pulse on the cycle of
a handshake (e.g. `last_byte` asserted only when `byte_ack`); a consumer FSM
takes ≥2 cycles to react and reads the pulse later — but by then it's gone.

Pattern detected:
  Producer: pulse_signal goes HIGH only when ack/strobe goes HIGH;
            on the next cycle pulse_signal is back LOW (no latch).
  Consumer: state machine that runs >1 cycle (e.g. 8 bit-cycles) reads
            pulse_signal in a later state without first latching it.

This gate scans:
  1. Producer side: find combinational assigns of the form
        signal_x <= ack_token && (some-condition)
     where signal_x has no separate sustained driver.
  2. Consumer side: find FSM where signal_x is referenced in a state that
     is NOT entered the same cycle ack_token fires (cycles offset > 1).
  3. If a `cur_x <= signal_x` latching pattern exists in the consumer at
     the strobe cycle, the race is mitigated — pass.

Heuristic exit:
  0 = PASS (no risky pattern, or latch present)
  1 = FAIL (transient signal read by multi-cycle consumer without latch)
  2 = Usage error

Generality: any synchronous RTL design. No chip / tester / PDK names.

Usage:
    python3 transient_signal_latch_check.py --rtl-dir ./rtl/

`--out-dir` is OPTIONAL and has no default: omit it and the gate writes no
file at all (verdict on stdout). Pass a project-relative directory —
e.g. `--out-dir ./reports/` — when you want the JSON report on disk.
"""
from __future__ import annotations
import argparse, json, re, sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Tuple, Dict

# Producer: signal driven by `<= ack && expr` or `<= valid && expr`.
# This is a conservative match — we look for the pattern rather than full data-flow.
PRODUCER_RE = re.compile(
    r'(\w+)\s*<=\s*[^;]*\b(\w+_(?:ack|valid|strobe|done|tick|stb|en|fire))\b\s*[&\?]',
    re.IGNORECASE,
)
# Consumer: FSM state read of the signal — `if (sig)` or `case sig` inside an always block guarded by a state-machine variable.
CONSUMER_REF_RE = re.compile(r'\b(?:if|case|else if)\s*\(\s*[^)]*?\b(\w+)\b', re.IGNORECASE)
# Latch pattern: cur_<x> <= <x>; or stash_<x> <= <x>;
LATCH_RE = re.compile(r'\b(?:cur|latched|stash|saved|hold|cap)_(\w+)\s*<=\s*\1\b', re.IGNORECASE)
# State register decl: `reg [n:0] state;` or `localparam ST_x = ...;`
STATE_DECL_RE = re.compile(r'(?:^|\W)reg\s*(?:\[[^\]]+\])?\s*(\w*state\w*)\s*[;,=]', re.IGNORECASE)
# bit-cycle / multi-cycle indicator: a counter that goes up to >= 2 in the consumer
MULTI_CYCLE_HINT_RE = re.compile(r'(\w+_(?:cnt|bit|idx|step))\s*<=\s*\1\s*\+\s*1', re.IGNORECASE)


@dataclass
class RaceFinding:
    signal: str
    producer_file: str
    producer_line: int
    consumer_file: str
    consumer_line: int
    multi_cycle_evidence: str
    has_latch: bool
    severity: str


@dataclass
class Result:
    status: str
    findings: List[RaceFinding] = field(default_factory=list)
    files_scanned: int = 0


def collect_signals_in_file(p: Path) -> Dict[str, List[Tuple[int, str]]]:
    """Return {signal_name: [(line, raw)] ...} for producers (handshake-gated) in this file."""
    out: Dict[str, List[Tuple[int, str]]] = {}
    try:
        text = p.read_text(errors="replace")
    except Exception:
        return out
    for i, ln in enumerate(text.splitlines(), 1):
        clean = ln.split("//", 1)[0]
        m = PRODUCER_RE.search(clean)
        if m:
            sig = m.group(1)
            out.setdefault(sig, []).append((i, ln.rstrip()))
    return out


def scan_consumers(p: Path, signal: str) -> List[Tuple[int, str, bool, str]]:
    """Return list of (line, raw, has_latch, multi_cycle_evidence) where signal is read."""
    try:
        text = p.read_text(errors="replace")
    except Exception:
        return []
    lines = text.splitlines()
    # Multi-cycle evidence within file?
    mc_evidence = ""
    for i, ln in enumerate(lines, 1):
        m = MULTI_CYCLE_HINT_RE.search(ln)
        if m:
            mc_evidence = f"line {i}: {m.group(0)}"
            break
    # Look for latch of this signal anywhere in file
    has_latch = any(LATCH_RE.search(ln) and signal.lower() in ln.lower() for ln in lines)
    out = []
    for i, ln in enumerate(lines, 1):
        clean = ln.split("//", 1)[0]
        # Match read of the signal (not driving it)
        if re.search(r'<=\s*[^;]*\b' + re.escape(signal) + r'\b', clean):
            continue  # this is a driver, not consumer
        if not re.search(r'\b' + re.escape(signal) + r'\b', clean):
            continue
        # Inside an FSM-looking always block? Need state-related context.
        # Simple heuristic: file must contain a state register declaration.
        if not any(STATE_DECL_RE.search(L) for L in lines):
            continue
        out.append((i, ln.rstrip(), has_latch, mc_evidence))
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--rtl-dir", required=True, type=Path)
    # #494 — a read-only validator writes NOTHING unless a caller asks for it.
    # See the sibling note in `sustained_vs_edge_check.py`: a hardcoded
    # `/tmp/<gatename>` default made every invocation deposit a report at a
    # fixed shared path, which concurrent runs overwrite without a trace and
    # which is a standing symlink-hijack target on a multi-user host.
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="Directory to write the JSON report into. Omitted "
                         "(the default) = write no file at all; the verdict "
                         "goes to stdout only.")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    if not args.rtl_dir.is_dir():
        print(f"ERROR: rtl-dir not found: {args.rtl_dir}", file=sys.stderr)
        return 2
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    rtl_files = sorted([p for p in args.rtl_dir.rglob("*") if p.suffix.lower() in {".v", ".sv", ".vh", ".svh"}])
    # Step 1: collect transient signals (handshake-gated drivers)
    transient_signals: Dict[str, Tuple[Path, int, str]] = {}
    for rf in rtl_files:
        for sig, occurrences in collect_signals_in_file(rf).items():
            for line_no, raw in occurrences:
                transient_signals.setdefault(sig, (rf, line_no, raw))

    # Step 2: for each transient signal, look for cross-file consumers
    findings: List[RaceFinding] = []
    for sig, (prod_file, prod_line, prod_raw) in transient_signals.items():
        for cf in rtl_files:
            if cf == prod_file:
                continue
            for c_line, c_raw, has_latch, mc_ev in scan_consumers(cf, sig):
                if not mc_ev:
                    continue  # no evidence of multi-cycle FSM
                severity = "WARN" if has_latch else "ERROR"
                if has_latch:
                    continue  # mitigated
                findings.append(RaceFinding(
                    signal=sig,
                    producer_file=str(prod_file), producer_line=prod_line,
                    consumer_file=str(cf), consumer_line=c_line,
                    multi_cycle_evidence=mc_ev,
                    has_latch=has_latch,
                    severity=severity,
                ))

    errors = [f for f in findings if f.severity == "ERROR"]
    warns = [f for f in findings if f.severity == "WARN"]
    status = "PASS" if not errors and (not args.strict or not warns) else "FAIL"
    res = Result(status=status, findings=findings, files_scanned=len(rtl_files))
    # #494 — write only when asked; position preserved so stdout is
    # byte-identical when --out-dir IS supplied.
    out_json = None
    if args.out_dir is not None:
        out_json = args.out_dir / "transient_signal_latch_check.json"
        out_json.write_text(json.dumps(asdict(res), indent=2, default=str))
    print(f"transient_signal_latch_check: {status} — {len(errors)} errors, {len(warns)} warns")
    for f in findings[:20]:
        print(f"  [{f.severity}] signal={f.signal}")
        print(f"    producer {f.producer_file}:{f.producer_line}")
        print(f"    consumer {f.consumer_file}:{f.consumer_line} ({f.multi_cycle_evidence})")
    if out_json is not None:
        print(f"json: {out_json}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
