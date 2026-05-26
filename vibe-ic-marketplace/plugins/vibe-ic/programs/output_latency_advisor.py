#!/usr/bin/env python3
"""output_latency_advisor.py — output sampling/latency advisor.

Surfaces the "output is one cycle late / sampled on the wrong edge" failure
family behind VerilogEval-v2 Prob089 (Moore FSM async-reset output timing) and
Prob104 (mux+DFF sampling cycle). A spec usually states the cycle at which an
output must be valid; a blind RTL pass often registers an output that the spec
wants combinational (or vice-versa). This is hard to *prove* statically, so the
lint is ADVISORY: it classifies each output and flags the latency choice for
explicit confirmation against the spec.

Per module (chip-AGNOSTIC, structural):
  - For every `output` port, decide whether it is REGISTERED (assigned with
    `<=` inside a sequential `always`/`always_ff` → valid one cycle after its
    inputs) or COMBINATIONAL (driven by `assign` / `always_comb`/`always @*`).
  - Flag every REGISTERED output as an INFO latency note ("valid +1 cycle —
    confirm the spec wants registered timing, not combinational").
  - Flag a `reg`-typed output that is NEVER assigned in any always block as a
    WARN (declared registered but undriven sequentially).

CLI (dual interface):
    python3 output_latency_advisor.py <file.v|dir ...>
    python3 output_latency_advisor.py --rtl-dir <dir> [--strict]

Exit codes:
    0 = PASS (advisory; default)   1 = FAIL (only with --strict and a WARN)
    2 = no RTL found / parse error
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple


def strip_comments(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        if src[i:i + 2] == '/*':
            end = src.find('*/', i + 2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end + 2]))
            i = end + 2
        elif src[i:i + 2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def collect_rtl_files(paths: List[str], rtl_dir: str | None) -> List[Path]:
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
    line: int
    severity: str   # INFO / WARN
    rule: str
    symbol: str
    message: str


def _segment_modules(src: str) -> List[Tuple[str, str, int]]:
    out = []
    for m in re.finditer(r'\bmodule\s+(\w+)\b', src):
        end = re.search(r'\bendmodule\b', src[m.end():])
        body = src[m.end():m.end() + end.start()] if end else src[m.end():]
        out.append((m.group(1), body, src[:m.start()].count('\n') + 1))
    return out


# output ports, in both ANSI (`output reg [..] foo`) and non-ANSI styles.
_OUTPUT = re.compile(
    r'\boutput\b\s*(reg|wire|logic)?\s*(?:signed\s+)?(?:\[[^\]]*\]\s*)?'
    r'([A-Za-z_]\w*'
    r'(?:\s*,\s*(?!(?:input|output|inout|reg|wire|logic)\b)[A-Za-z_]\w*)*)')
# sequential always blocks: posedge/negedge in sensitivity
_SEQ_ALWAYS = re.compile(r'\balways(?:_ff)?\b\s*@\s*\([^)]*\b(?:pos|neg)edge\b[^)]*\)')


def _seq_assigned_names(body: str) -> set:
    """Names assigned with `<=` anywhere (proxy for sequential assignment)."""
    return set(re.findall(r'([A-Za-z_]\w*)(?:\s*\[[^\]]*\])?\s*<=', body))


def analyse_module(name: str, body: str, base_line: int, path: str) -> List[Finding]:
    findings: List[Finding] = []
    outputs: List[Tuple[str, str]] = []  # (signal, declared_kind)
    for m in _OUTPUT.finditer(body):
        kind = (m.group(1) or '').strip()
        for nm in re.split(r'\s*,\s*', m.group(2)):
            outputs.append((nm, kind))
    if not outputs:
        return findings

    nb_assigned = _seq_assigned_names(body)
    has_seq = bool(_SEQ_ALWAYS.search(body))

    for sig, kind in outputs:
        line = base_line + body[:body.find(sig)].count('\n') if sig in body \
            else base_line
        registered = sig in nb_assigned and has_seq
        if registered:
            findings.append(Finding(
                path, line, 'INFO', 'registered-output', sig,
                f"module '{name}': output '{sig}' is REGISTERED — valid one "
                f"clock AFTER its inputs change. Confirm the spec wants "
                f"registered latency (Moore/pipelined) and not combinational "
                f"timing; an off-by-one-cycle output is a classic spec miss."))
        elif kind == 'reg' and sig not in nb_assigned \
                and not re.search(r'\bassign\s+' + re.escape(sig) + r'\b', body):
            findings.append(Finding(
                path, line, 'WARN', 'reg-output-undriven', sig,
                f"module '{name}': output '{sig}' is declared `reg` but is "
                f"never assigned in a sequential block nor via `assign` — it "
                f"holds X. Drive it or change its type."))
    return findings


def lint_file(path: Path) -> List[Finding]:
    src = strip_comments(path.read_text(errors='replace'))
    out: List[Finding] = []
    for name, body, line in _segment_modules(src):
        out += analyse_module(name, body, line, str(path))
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Output latency / sampling advisor.')
    ap.add_argument('paths', nargs='*', help='RTL files or directories')
    ap.add_argument('--rtl-dir', help='Directory of .v/.sv to scan recursively')
    ap.add_argument('--strict', action='store_true',
                    help='Exit 1 on WARN findings (default: advisory, exit 0)')
    ap.add_argument('--json', help='Write findings as JSON')
    args = ap.parse_args(argv)

    files = collect_rtl_files(args.paths, args.rtl_dir)
    if not files:
        print('output_latency_advisor: no RTL files found', file=sys.stderr)
        return 2

    findings: List[Finding] = []
    for f in files:
        try:
            findings += lint_file(f)
        except Exception as e:  # noqa: BLE001
            print(f'output_latency_advisor: parse error in {f}: {e}',
                  file=sys.stderr)
            return 2

    warns = [f for f in findings if f.severity == 'WARN']
    fail = args.strict and bool(warns)
    verdict = 'FAIL' if fail else 'PASS'
    note = '' if fail else ' (advisory)'
    print(f"output_latency_advisor: {verdict}{note} — findings: {len(findings)} "
          f"({len(warns)} warn)")
    for fd in sorted(findings, key=lambda x: (x.file, x.line)):
        print(f"  {fd.file}:{fd.line}: [{fd.severity}] {fd.rule}: {fd.message}")
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(f) for f in findings],
                                              indent=2))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
