#!/usr/bin/env python3
"""spec_conformance_check.py — Spec↔RTL contract-conformance gate.

The Phase-1→Phase-2 hand-off declares a *contract*: the interface (ports +
widths + directions), the reset semantics (synchronous vs asynchronous,
active-high vs active-low), and the output latency (registered vs
combinational). The RTL must *conform*. This is distinct from the RTL-only
structural lints (`spec_rtl_port_fidelity_check`, `reset_discipline_check`),
which can pass while the implementation silently contradicts the spec.

Two real failures motivate every rule here:
  • A CVDP arbiter spec said "Active-high *synchronous* reset" while the
    reference RTL implemented an *asynchronous* reset — a blind spec-faithful
    solution then failed the bench. `reset-mode-spec-mismatch` catches that.
  • VerilogEval-v2 port-interface misses needed an *automatically extracted*
    expected port list (the prompt's "- input d (8 bits)" bullets), not a
    hand-built one. The contract extractor supplies it.

Findings:
  ERROR (fails the gate):
    port-missing / port-extra / port-direction-mismatch / port-width-mismatch
    reset-mode-spec-mismatch     : spec says sync, RTL is async (or vice-versa)
    reset-polarity-spec-mismatch : spec says active-high, RTL active-low (or v.v.)
  WARN:
    reset-not-found              : spec declares a reset but no reset block found
  INFO (advisory; never fails):
    latency-mismatch             : spec says registered/1-cycle, RTL output looks
                                   combinational (or vice-versa) — confirm timing

chip-AGNOSTIC: all matching is structural/keyword. No IC/vendor/SKU literals.

CLI:
    python3 spec_conformance_check.py --spec SPEC --rtl-dir DIR [--top NAME]
    python3 spec_conformance_check.py --spec SPEC <rtl files...> [--json out] [--strict]
  SPEC may be .json (canonical contract), .md/.txt (natural-language bullets or
  a fenced Verilog module header), or a Verilog file.

Exit codes:
    0 = no ERROR (PASS)   1 = ERROR (FAIL) or, with --strict, any WARN
    2 = no RTL / no spec / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

try:
    from _specrtl_common import (Port, SpecContract, classify_rtl_resets,
                                 extract_spec_contract, parse_rtl_ports,
                                 strip_comments)
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _specrtl_common import (Port, SpecContract, classify_rtl_resets,
                                 extract_spec_contract, parse_rtl_ports,
                                 strip_comments)


@dataclass
class Finding:
    file: str
    severity: str   # ERROR / WARN / INFO
    rule: str
    symbol: str
    message: str


def collect_rtl_files(paths: List[str], rtl_dir: Optional[str]) -> List[Path]:
    files: List[Path] = []
    for r in list(paths) + ([rtl_dir] if rtl_dir else []):
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


def _rtl_output_is_registered(body: str, ports: List[Port]) -> Optional[bool]:
    """Best-effort: are the module's named outputs driven by a clocked block?

    True if any output is `<=`-assigned inside a sequential always; False if
    outputs are only `assign`/`=`-driven; None if undetermined."""
    import re
    outs = {p.name for p in ports if p.direction == 'output'}
    if not outs:
        return None
    seq_lhs, comb_driven = set(), set()
    # sequential blocks
    for am in re.finditer(r'\balways(?:_ff)?\b\s*@\s*\(([^)]*)\)', body):
        if not re.search(r'\b(?:pos|neg)edge\b', am.group(1)):
            continue
        seg = body[am.end():am.end() + 4000]
        for nm in re.findall(r'(\w+)(?:\s*\[[^\]]*\])?\s*<=', seg):
            if nm in outs:
                seq_lhs.add(nm)
    for nm in re.findall(r'\bassign\s+(\w+)', body):
        if nm in outs:
            comb_driven.add(nm)
    for am in re.finditer(r'\balways\b\s*@\s*\(\s*\*\s*\)', body):
        seg = body[am.end():am.end() + 4000]
        for nm in re.findall(r'(\w+)(?:\s*\[[^\]]*\])?\s*=(?!=)', seg):
            if nm in outs:
                comb_driven.add(nm)
    if seq_lhs:
        return True
    if comb_driven:
        return False
    return None


_CLKRST_NAME = __import__('re').compile(r'^(clk|clock|rst|reset|areset|nreset|rst_n|resetn|por|en|enable)$', __import__('re').I)


def _mealy_outputs(body: str, ports: List[Port]) -> List[tuple]:
    """Output ports driven COMBINATIONALLY by an expression that references a
    data input port → a Mealy output. (Clock/reset/enable refs are ignored.)

    Used only to enforce a *Moore* spec: a Moore machine's outputs must be a
    function of state alone, so a combinational output cone reaching a data
    input is a Moore-vs-Mealy violation (the classic VerilogEval Prob089 miss).
    Registered outputs never appear here (they are `<=`-driven in a clocked
    block), so this never flags a correct Moore design."""
    import re
    outs = {p.name for p in ports if p.direction == 'output'}
    ins = {p.name for p in ports if p.direction == 'input' and not _CLKRST_NAME.match(p.name)}
    if not outs or not ins:
        return []
    bad: List[tuple] = []

    def scan(seg: str, assign_op: str):
        pat = r'\b(\w+)(?:\s*\[[^\]]*\])?\s*' + assign_op + r'\s*([^;]+);'
        for m in re.finditer(pat, seg):
            nm, rhs = m.group(1), m.group(2)
            if nm in outs:
                refd = sorted({t for t in re.findall(r'\b([A-Za-z_]\w*)\b', rhs)} & ins)
                if refd:
                    bad.append((nm, refd))

    for m in re.finditer(r'\bassign\s+([^;]+);', body):
        scan('assign ' + m.group(1) + ';', '=')
    for am in re.finditer(r'\balways\b\s*@\s*\(\s*\*\s*\)', body):
        scan(body[am.end():am.end() + 4000], r'=(?!=)')
    # de-dup
    seen, out = set(), []
    for nm, refd in bad:
        key = (nm, tuple(refd))
        if key not in seen:
            seen.add(key)
            out.append((nm, refd))
    return out


def check(spec: SpecContract, rtl_name: str, rtl_ports: List[Port],
          rtl_resets: dict, rtl_registered: Optional[bool],
          path: str) -> List[Finding]:
    f: List[Finding] = []

    # ---- port conformance --------------------------------------------------
    # Only when the spec actually declares an interface — a reset/latency-only
    # spec snippet (0 ports) must not flag every RTL port as "extra".
    rmap = {p.name: p for p in rtl_ports}
    smap = {p.name: p for p in spec.ports} if spec.ports else {}
    for nm, sp in smap.items():
        if nm not in rmap:
            f.append(Finding(path, 'ERROR', 'port-missing', nm,
                f"spec port '{nm}' ({sp.direction}[{sp.width}]) is not in the RTL."))
            continue
        rp = rmap[nm]
        if rp.direction != sp.direction:
            f.append(Finding(path, 'ERROR', 'port-direction-mismatch', nm,
                f"port '{nm}' direction RTL={rp.direction} vs spec={sp.direction}."))
        if rp.width != sp.width:
            f.append(Finding(path, 'ERROR', 'port-width-mismatch', nm,
                f"port '{nm}' width RTL={rp.width} vs spec={sp.width}."))
    if smap:
        for nm in rmap:
            if nm not in smap:
                f.append(Finding(path, 'ERROR', 'port-extra', nm,
                    f"RTL port '{nm}' is not declared in the spec."))

    # ---- reset conformance -------------------------------------------------
    if spec.reset_mode or spec.reset_polarity:
        # Pick the RTL reset to compare against: the spec-named one if present,
        # else the sole reset signal, else every reset signal.
        targets = {}
        if spec.reset_signal and spec.reset_signal in rtl_resets:
            targets = {spec.reset_signal: rtl_resets[spec.reset_signal]}
        elif len(rtl_resets) == 1:
            targets = dict(rtl_resets)
        elif rtl_resets:
            targets = dict(rtl_resets)
        if not targets:
            f.append(Finding(path, 'WARN', 'reset-not-found',
                spec.reset_signal or 'reset',
                f"spec declares a {spec.reset_mode or ''} "
                f"{spec.reset_polarity or ''} reset but no matching reset block "
                f"was found in the RTL."))
        for sig, rec in targets.items():
            if spec.reset_mode and rec['mode'] and spec.reset_mode not in rec['mode']:
                f.append(Finding(path, 'ERROR', 'reset-mode-spec-mismatch', sig,
                    f"reset '{sig}': spec says {spec.reset_mode} but RTL implements "
                    f"{'/'.join(sorted(rec['mode']))}. (A blind spec-faithful design "
                    f"will mismatch the bench — reconcile spec vs reference.)"))
            if (spec.reset_polarity and rec['polarity']
                    and spec.reset_polarity not in rec['polarity']):
                f.append(Finding(path, 'ERROR', 'reset-polarity-spec-mismatch', sig,
                    f"reset '{sig}': spec says {spec.reset_polarity} but RTL tests "
                    f"{'/'.join(sorted(rec['polarity']))}."))

    # ---- latency conformance (advisory) -----------------------------------
    if spec.latency_registered is not None and rtl_registered is not None \
            and spec.latency_registered != rtl_registered:
        want = 'registered (≥1-cycle)' if spec.latency_registered else 'combinational'
        got = 'registered' if rtl_registered else 'combinational'
        f.append(Finding(path, 'INFO', 'latency-mismatch', rtl_name,
            f"spec implies a {want} output but the RTL output looks {got} — "
            f"confirm the intended valid-cycle (off-by-one is a classic spec miss)."))
    return f


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='Spec↔RTL contract-conformance gate.')
    ap.add_argument('paths', nargs='*', help='RTL files or directories')
    ap.add_argument('--rtl-dir', help='Directory of .v/.sv to scan recursively')
    ap.add_argument('--spec', required=True,
                    help='Spec file (.json contract, .md/.txt NL/markdown, or .v)')
    ap.add_argument('--top', help='Top module name (default: first/spec module)')
    ap.add_argument('--strict', action='store_true',
                    help='Exit 1 on WARN findings too')
    ap.add_argument('--json', help='Write findings as JSON')
    args = ap.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f'spec_conformance_check: FAIL — spec not found: {args.spec}',
              file=sys.stderr)
        return 2
    spec_raw = spec_path.read_text(errors='replace')
    spec = extract_spec_contract(spec_raw, is_json=spec_path.suffix == '.json')
    import re as _re
    spec_is_moore = spec_path.suffix != '.json' and bool(_re.search(r'\bmoore\b', spec_raw, _re.I))

    top = args.top or spec.module
    files = collect_rtl_files(args.paths, args.rtl_dir)
    if not files:
        print('spec_conformance_check: FAIL — no RTL files found', file=sys.stderr)
        return 2

    rtl_name, rtl_ports, rtl_body, chosen = '', [], '', str(files[0])
    for f in files:
        try:
            src = strip_comments(f.read_text(errors='replace'))
        except Exception as e:  # noqa: BLE001
            print(f'spec_conformance_check: parse error in {f}: {e}', file=sys.stderr)
            return 2
        nm, ports = parse_rtl_ports(src, top)
        if ports and (not rtl_ports or (top and nm == top)):
            rtl_name, rtl_ports, rtl_body, chosen = nm, ports, src, str(f)
            if top and nm == top:
                break

    rtl_resets = classify_rtl_resets(rtl_body)
    rtl_registered = _rtl_output_is_registered(rtl_body, rtl_ports)
    findings = check(spec, rtl_name, rtl_ports, rtl_resets, rtl_registered, chosen)

    # ---- Moore output discipline (only when the spec declares a Moore FSM) ----
    if spec_is_moore:
        for nm, refd in _mealy_outputs(rtl_body, rtl_ports):
            findings.append(Finding(chosen, 'WARN', 'moore-output-mealy', nm,
                f"spec declares a Moore FSM but output '{nm}' is combinationally "
                f"dependent on input(s) {', '.join(refd)} (Mealy). A Moore output "
                f"must be a function of state only — register it (e.g. z_reg <= "
                f"f(state); assign {nm} = z_reg). Mealy-vs-Moore timing is the "
                f"classic VerilogEval Prob089 miss."))

    errs = [x for x in findings if x.severity == 'ERROR']
    warns = [x for x in findings if x.severity == 'WARN']
    infos = [x for x in findings if x.severity == 'INFO']
    fail = bool(errs) or (args.strict and bool(warns))
    verdict = 'FAIL' if fail else 'PASS'
    print(f"spec_conformance_check: {verdict} — findings: {len(findings)} "
          f"({len(errs)} error, {len(warns)} warn, {len(infos)} info) "
          f"[spec ports={len(spec.ports)}({spec.source}), rtl ports={len(rtl_ports)}, "
          f"spec reset={spec.reset_mode or '-'}/{spec.reset_polarity or '-'}]")
    for fd in sorted(findings, key=lambda x: (x.severity, x.rule, x.symbol)):
        print(f"  [{fd.severity}] {fd.rule}: {fd.message}")
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(x) for x in findings], indent=2))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
