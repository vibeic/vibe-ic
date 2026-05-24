#!/usr/bin/env python3
"""
rx_tolerance_sweep.py — General RX boundary-width tolerance sweep.

Any pulse-width-encoded or PPM-encoded protocol (UART, Lightning, DALI,
PMBus, IR-NEC, etc.) has decode windows for each symbol:

    Symbol '1': low pulse width in [H1_MIN .. H1_MAX]
    Symbol '0': low pulse width in [H0_MIN .. H0_MAX]
    Break:      low pulse width in [BRK_MIN .. BRK_MAX]

During <half-duplex-tester> debug (2026-04-16) we found the H1/H0 boundary at width=8 was
unmapped (H1 = 1..7, H0 = 9..23), so pulses at exactly 8 cycles silently
failed to decode.

This tool reads a protocol decode table (JSON) and sweeps pulse widths from
0..MAX, reporting:

  - Coverage gaps (widths with no decode)
  - Overlap zones (widths claimed by multiple symbols)
  - Asymmetry at boundaries (width=N → '1' but width=N+1 → nothing)

Usage:
    python3 rx_tolerance_sweep.py --decode-table table.json

table.json format:
    {
      "max_width": 50,
      "symbols": [
        {"name": "H1",    "widths": [1, 2, 3, 4, 5, 6, 7]},
        {"name": "H0",    "widths": [9, 10, 11, 12, 13, 14, 15,
                                     16, 17, 18, 19, 20, 21, 22, 23]},
        {"name": "BREAK", "widths": [24, 25, 26, 27, 28, 29, 30, 31,
                                     32, 33, 34, 35, 36, 37, 38, 39,
                                     40, 41, 42, 43, 44, 45, 46]}
      ]
    }

Output: coverage report + JSON with findings.

Generality: works for ANY pulse-width-encoded protocol. Decode table is the
input, no hard-coded symbols.
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set


@dataclass
class Finding:
    kind: str          # "gap" / "overlap" / "boundary-asymmetry"
    width: int
    symbols: List[str]
    message: str


def analyze(table: dict) -> List[Finding]:
    max_w = table['max_width']
    symbols = table['symbols']

    # Build width -> list of symbol names that accept this width
    width_map: Dict[int, Set[str]] = {}
    for s in symbols:
        for w in s['widths']:
            width_map.setdefault(w, set()).add(s['name'])

    findings: List[Finding] = []

    # Check coverage gaps
    for w in range(1, max_w + 1):
        if w not in width_map:
            findings.append(Finding('gap', w, [],
                f"width={w} has NO decode (protocol hole — pulses of this width "
                "will fail silently or trigger rx_error)"))
        elif len(width_map[w]) > 1:
            findings.append(Finding('overlap', w, sorted(width_map[w]),
                f"width={w} claimed by multiple symbols: {sorted(width_map[w])} "
                "— priority rule required"))

    # Check boundary asymmetry: if width w decodes to symbol S but w+1 has no
    # decode, that's a single-point gap that will cause jitter-induced failures.
    widths_sorted = sorted(width_map.keys())
    for i, w in enumerate(widths_sorted[:-1]):
        next_w = widths_sorted[i + 1]
        if next_w - w > 1:
            findings.append(Finding('boundary-asymmetry', w,
                list(width_map[w]),
                f"width={w} → {sorted(width_map[w])} then width={w+1}..{next_w-1} "
                "undecoded — pulses at boundary will randomly fail"))

    return findings


def simulate_jitter(table: dict, jitter_cycles: int = 1) -> Dict[str, float]:
    """
    For each symbol, compute: fraction of that symbol's nominal widths
    that would STILL decode correctly if the receiver sees width ± jitter_cycles.

    Returns {symbol_name: fraction_robust}
    """
    max_w = table['max_width']
    symbols = table['symbols']
    width_map: Dict[int, Set[str]] = {}
    for s in symbols:
        for w in s['widths']:
            width_map.setdefault(w, set()).add(s['name'])

    robust = {}
    for s in symbols:
        name = s['name']
        nominal = s['widths']
        total = 0
        ok = 0
        for w in nominal:
            for dw in range(-jitter_cycles, jitter_cycles + 1):
                neighbor = w + dw
                if 1 <= neighbor <= max_w:
                    total += 1
                    if neighbor in width_map and name in width_map[neighbor]:
                        ok += 1
        robust[name] = ok / total if total else 0.0
    return robust


def fmt_report(findings: List[Finding], robust: Dict[str, float]) -> str:
    lines = []
    gaps = sum(1 for f in findings if f.kind == 'gap')
    overlaps = sum(1 for f in findings if f.kind == 'overlap')
    asymmetries = sum(1 for f in findings if f.kind == 'boundary-asymmetry')
    lines.append(f"rx_tolerance_sweep: {gaps} gaps, {overlaps} overlaps, {asymmetries} boundary asymmetries")
    lines.append('-' * 70)
    for f in findings:
        lines.append(f"[{f.kind}] width={f.width} {f.symbols}: {f.message}")
    lines.append('')
    lines.append("Jitter robustness (fraction of nominal widths that stay decodable with ±1 cycle jitter):")
    for sym, frac in sorted(robust.items()):
        lines.append(f"  {sym}: {frac:.2%}")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='RX boundary tolerance sweep')
    ap.add_argument('--decode-table', required=True,
                    help='JSON file describing symbol decode widths')
    ap.add_argument('--jitter', type=int, default=1,
                    help='jitter tolerance in clock cycles (default 1)')
    ap.add_argument('--json-out', help='write findings as JSON')
    args = ap.parse_args()

    table = json.loads(Path(args.decode_table).read_text())
    findings = analyze(table)
    robust = simulate_jitter(table, args.jitter)

    report = fmt_report(findings, robust)
    print(report)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            'findings': [f.__dict__ for f in findings],
            'jitter_robustness': robust,
        }, indent=2))

    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
