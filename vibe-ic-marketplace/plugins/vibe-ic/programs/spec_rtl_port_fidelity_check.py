#!/usr/bin/env python3
"""spec_rtl_port_fidelity_check.py — spec↔RTL port-fidelity + garbled-port lint.

Closes the prompt/spec port-fidelity gap behind VerilogEval-v2 Prob099, where a
garbled spec led the generator to emit ports `Y1,Y3` when the design needed
`Y2,Y4`. Two modes:

  STANDALONE (default): structural "port sanity" on the RTL alone —
    - indexed-name GAP: a port family like `Y1, Y3` with a missing interior
      index `Y2` (the Prob099 signature) → WARN.
    - duplicate port names → WARN.

  SPEC COMPARE (`--spec FILE`): exact match of the RTL port list against an
    integration-spec port list (name + direction + width). Any missing / extra
    / direction-mismatch / width-mismatch port → ERROR. This is the L9↔RTL
    contract for the full flow; `module_port_audit` and
    `l9_rtl_pin_consistency_check` cover parts of this — this adds exact
    width+direction diffing and the garbled-index detector.

Spec file: JSON list `[{"name":..,"direction":"input|output|inout","width":N}]`
or a plain-text port list (`input [7:0] foo` lines).

CLI (dual interface):
    python3 spec_rtl_port_fidelity_check.py <file.v|dir ...>
    python3 spec_rtl_port_fidelity_check.py --rtl-dir <dir> [--top NAME] [--spec FILE]

Exit codes:
    0 = PASS   1 = ERROR (spec mismatch) or, with --strict, any WARN
    2 = no RTL found / parse error
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Shared Spec↔RTL parsing primitives (single source of truth — see
# _specrtl_common). load_spec now auto-handles NL prompts + markdown so the
# `--spec` port-list need not be hand-built.
try:
    from _specrtl_common import (Port, WIDTH_UNKNOWN, extract_spec_contract,
                                 parse_rtl_ports,
                                 parse_verilog_ports, strip_comments)
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _specrtl_common import (Port, WIDTH_UNKNOWN, extract_spec_contract,
                                 parse_rtl_ports,
                                 parse_verilog_ports, strip_comments)


def collect_rtl_files(paths: List[str], rtl_dir: Optional[str]) -> List[Path]:
    files: List[Path] = []
    roots = list(paths) + ([rtl_dir] if rtl_dir else [])
    for r in roots:
        p = Path(r)
        if p.is_dir():
            files += sorted(p.rglob('*.v')) + sorted(p.rglob('*.sv'))
        elif p.is_file():
            files.append(p)
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


@dataclass
class Finding:
    file: str
    severity: str   # ERROR / WARN
    rule: str
    symbol: str
    message: str


def load_spec(path: Path) -> List[Port]:
    """Expected port list from a spec. Accepts a canonical .json contract, a
    natural-language prompt ("- input d (8 bits)"), a markdown ```verilog
    module(...)``` header, or a plain Verilog file — via the shared extractor."""
    txt = path.read_text(errors='replace')
    return extract_spec_contract(txt, is_json=path.suffix == '.json').ports


def check_index_gaps(ports: List[Port], path: str) -> List[Finding]:
    """Detect indexed port families with a missing interior index."""
    fam: Dict[str, List[int]] = {}
    for p in ports:
        m = re.match(r'^(.*?)(\d+)$', p.name)
        if m:
            fam.setdefault(m.group(1), []).append(int(m.group(2)))
    findings = []
    for prefix, idxs in fam.items():
        s = sorted(set(idxs))
        if len(s) < 2:
            continue
        full = set(range(s[0], s[-1] + 1))
        missing = sorted(full - set(s))
        if missing:
            findings.append(Finding(
                path, 'WARN', 'port-index-gap', prefix,
                f"port family '{prefix}*' has indices {s} with interior "
                f"gap(s) {missing} — a garbled/misread spec often drops a port "
                f"this way (VerilogEval Prob099 signature). Confirm "
                f"'{prefix}{missing[0]}' is genuinely absent."))
    return findings


def check_duplicates(ports: List[Port], path: str) -> List[Finding]:
    seen: Dict[str, int] = {}
    for p in ports:
        seen[p.name] = seen.get(p.name, 0) + 1
    return [Finding(path, 'WARN', 'duplicate-port', n,
                    f"port '{n}' declared {c} times.")
            for n, c in seen.items() if c > 1]


def compare_to_spec(rtl: List[Port], spec: List[Port], path: str) -> List[Finding]:
    rmap = {p.name: p for p in rtl}
    smap = {p.name: p for p in spec}
    findings = []
    for nm, sp in smap.items():
        if nm not in rmap:
            findings.append(Finding(path, 'ERROR', 'port-missing', nm,
                f"spec port '{nm}' ({sp.direction}[{sp.width}]) is not in the RTL."))
            continue
        rp = rmap[nm]
        if rp.direction != sp.direction:
            findings.append(Finding(path, 'ERROR', 'port-direction-mismatch', nm,
                f"port '{nm}' direction RTL={rp.direction} vs spec={sp.direction}."))
        # Skip when EITHER side is WIDTH_UNKNOWN (an unresolved parameterized /
        # symbolic bound) — asserting against an unknown fabricates a false
        # width-mismatch. Only compare two known literal widths.
        if (rp.width != WIDTH_UNKNOWN and sp.width != WIDTH_UNKNOWN
                and rp.width != sp.width):
            findings.append(Finding(path, 'ERROR', 'port-width-mismatch', nm,
                f"port '{nm}' width RTL={rp.width} vs spec={sp.width}."))
    for nm in rmap:
        if nm not in smap:
            findings.append(Finding(path, 'ERROR', 'port-extra', nm,
                f"RTL port '{nm}' is not in the spec."))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='Spec↔RTL port-fidelity lint.')
    ap.add_argument('paths', nargs='*', help='RTL files or directories')
    ap.add_argument('--rtl-dir', help='Directory of .v/.sv to scan recursively')
    ap.add_argument('--top', help='Top module name (default: first module)')
    ap.add_argument('--spec', help='Spec port-list file (.json or text) to compare against')
    ap.add_argument('--strict', action='store_true',
                    help='Exit 1 on WARN findings too')
    ap.add_argument('--json', help='Write findings as JSON')
    args = ap.parse_args(argv)

    files = collect_rtl_files(args.paths, args.rtl_dir)
    if not files:
        print('spec_rtl_port_fidelity_check: FAIL — no RTL files found',
              file=sys.stderr)
        return 2

    # Pick the file holding the top module (or the first file).
    findings: List[Finding] = []
    chosen_ports: List[Port] = []
    chosen_path = str(files[0])
    for f in files:
        try:
            src = strip_comments(f.read_text(errors='replace'))
        except Exception as e:  # noqa: BLE001
            print(f'spec_rtl_port_fidelity_check: parse error in {f}: {e}',
                  file=sys.stderr)
            return 2
        nm, ports = parse_rtl_ports(src, args.top)
        if ports and (not chosen_ports or (args.top and nm == args.top)):
            chosen_ports, chosen_path = ports, str(f)
            if args.top and nm == args.top:
                break

    findings += check_index_gaps(chosen_ports, chosen_path)
    findings += check_duplicates(chosen_ports, chosen_path)
    if args.spec:
        spec_ports = load_spec(Path(args.spec))
        findings += compare_to_spec(chosen_ports, spec_ports, chosen_path)

    errs = [f for f in findings if f.severity == 'ERROR']
    warns = [f for f in findings if f.severity == 'WARN']
    fail = bool(errs) or (args.strict and bool(warns))
    verdict = 'FAIL' if fail else 'PASS'
    print(f"spec_rtl_port_fidelity_check: {verdict} — findings: {len(findings)} "
          f"({len(errs)} error, {len(warns)} warn) [{len(chosen_ports)} ports]")
    for fd in sorted(findings, key=lambda x: (x.severity, x.symbol)):
        print(f"  [{fd.severity}] {fd.rule}: {fd.message}")
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(f) for f in findings],
                                              indent=2))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
