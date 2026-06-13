#!/usr/bin/env python3
"""reset_discipline_check.py — deterministic reset-discipline lint.

Closes the reset-semantics gap behind the VerilogEval-v2 DFF/FSM failures
(sync-vs-async reset, reset polarity, partially-reset state). The existing
`reset_dependency_check.py` only finds *circular* reset dependencies; this
checks that a module's reset is *consistent and complete*.

Per module, classifies every sequential `always` / `always_ff` block by:
  - reset MODE: async (reset edge in the sensitivity list) vs sync (reset
    only tested inside the body) vs none.
  - reset POLARITY: active-low (`if(!rst)`, `~rst`, `rst==0`) vs
    active-high (`if(rst)`, `rst==1`).
  - which state regs are assigned in the reset branch vs only outside it.

Findings (verdict tiers):
  ERROR (fails the gate):
    - reset-mode-mismatch : the SAME reset signal is async in one block and
      sync in another → the design has two contradictory reset strategies.
    - reset-polarity-mismatch : the SAME reset signal is tested active-low in
      one place and active-high in another.
  WARN (reported; fails only with --strict):
    - incomplete-reset : a state reg (`<=` assigned) in a block WITH a reset
      branch is never assigned a reset value.
    - flop-without-reset : a sequential block holds state but has no reset at
      all (often intentional for pipeline regs — hence WARN, not ERROR).

chip-AGNOSTIC: detection is purely structural (sensitivity lists, `if`
polarity, LHS sets). No IC / vendor / signal-name literals.

CLI (dual interface, like the precheck-gate auditors AND the hygiene lint):
    python3 reset_discipline_check.py <file.v|dir ...>
    python3 reset_discipline_check.py --rtl-dir <dir>
    python3 reset_discipline_check.py --json out.json [--strict] <paths...>

Exit codes:
    0 = no ERROR findings (PASS)   1 = ERROR findings (FAIL) or, with
    --strict, any WARN             2 = no RTL found / parse error
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Shared helpers (kept inline so the program is dependency-free)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, preserving newlines for line tracking."""
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
    """Resolve CLI paths (files or dirs) + --rtl-dir into a flat file list."""
    files: List[Path] = []
    roots: List[str] = list(paths)
    if rtl_dir:
        roots.append(rtl_dir)
    for r in roots:
        p = Path(r)
        if p.is_dir():
            files += sorted(p.rglob('*.v')) + sorted(p.rglob('*.sv'))
        elif p.is_file():
            files.append(p)
    # de-dup, keep order
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


_OPENERS = re.compile(r'\b(begin|case[zx]?|fork)\b')
_CLOSERS = re.compile(r'\b(end|endcase|join(?:_any|_none)?)\b')


def extract_block(src: str, after: int) -> Tuple[str, int]:
    """Given a position just after `always @(...)`, return (body, end_pos).

    If the statement starts with `begin`, return up to the matching `end`
    (tracking nested begin/case/fork). Otherwise return up to the next `;`.
    """
    m = re.compile(r'\S').search(src, after)
    if not m:
        return '', len(src)
    if not re.match(r'begin\b', src[m.start():]):
        semi = src.find(';', m.start())
        end = semi if semi != -1 else len(src)
        return src[m.start():end + 1], end + 1
    # balanced begin/end walk
    depth = 0
    pos = m.start()
    tok = re.compile(r'\b\w+\b')
    last = len(src)
    while pos < last:
        t = tok.search(src, pos)
        if not t:
            break
        w = t.group(0)
        if _OPENERS.fullmatch(w):
            depth += 1
        elif _CLOSERS.fullmatch(w):
            depth -= 1
            if depth == 0:
                return src[m.start():t.end()], t.end()
        pos = t.end()
    return src[m.start():], len(src)


# ---------------------------------------------------------------------------
@dataclass
class Finding:
    file: str
    line: int
    severity: str  # ERROR / WARN
    rule: str
    symbol: str
    message: str


def _segment_modules(src: str) -> List[Tuple[str, str, int]]:
    """Return [(module_name, module_body, start_line), ...]."""
    out = []
    for m in re.finditer(r'\bmodule\s+(\w+)\b', src):
        name = m.group(1)
        end = re.search(r'\bendmodule\b', src[m.end():])
        body = src[m.end():m.end() + end.start()] if end else src[m.end():]
        start_line = src[:m.start()].count('\n') + 1
        out.append((name, body, start_line))
    return out


_ALWAYS = re.compile(r'\balways(?:_ff)?\b')
_SENS = re.compile(r'@\s*\(([^)]*)\)', re.S)
# active-low: !rst, ~rst, rst==1'b0/0, !rst_n ; active-high: bare rst / rst==1
_RST_EDGE = re.compile(r'\b(?:pos|neg)edge\s+(\w+)')
# Generic (chip-AGNOSTIC) reset-name shapes: rst, rst_n, reset, resetn, nrst,
# arst, srst, clr, clear, por. Used only to gate SYNC-reset classification so
# an enable (`if(en)`) is never mistaken for a reset.
_RESET_NAME = re.compile(r'rst|reset|clr|clear|\bpor\b', re.I)


def _classify_polarity(cond: str) -> Tuple[str | None, str | None]:
    """Return (reset_signal, polarity) parsed from a reset `if` condition,
    or (None, None) if it doesn't look like a reset test."""
    cond = cond.strip()
    # active-low forms
    m = re.match(r'^[!~]\s*(\w+)\s*$', cond)
    if m:
        return m.group(1), 'low'
    m = re.match(r'^(\w+)\s*==\s*1?\'?[bdh]?0+\s*$', cond) or \
        re.match(r"^(\w+)\s*==\s*0\s*$", cond)
    if m:
        return m.group(1), 'low'
    # active-high forms
    m = re.match(r'^(\w+)\s*==\s*1?\'?[bdh]?0*1\s*$', cond) or \
        re.match(r"^(\w+)\s*==\s*1\s*$", cond)
    if m:
        return m.group(1), 'high'
    m = re.match(r'^(\w+)\s*$', cond)
    if m:
        return m.group(1), 'high'
    return None, None


def _lhs_assigns(block: str, op: str) -> set:
    """Names on the LHS of `<=` (op='nb') or `=` (op='b') within block."""
    pat = r'(\w+)(?:\s*\[[^\]]*\])?\s*<=' if op == 'nb' \
          else r'(\w+)(?:\s*\[[^\]]*\])?\s*=(?!=)'
    return set(re.findall(pat, block))


def analyse_module(name: str, body: str, base_line: int, path: str) -> List[Finding]:
    findings: List[Finding] = []
    # reset signal -> set of modes ('async'/'sync'), set of polarities
    sig_modes: Dict[str, set] = {}
    sig_pol: Dict[str, set] = {}

    pos = 0
    while True:
        am = _ALWAYS.search(body, pos)
        if not am:
            break
        sm = _SENS.search(body, am.end())
        if not sm or sm.start() > am.end() + 8:  # sensitivity must follow
            pos = am.end()
            continue
        sens = sm.group(1)
        edges = _RST_EDGE.findall(sens)
        is_seq = bool(edges)
        if not is_seq:
            pos = sm.end()
            continue
        block, end_pos = extract_block(body, sm.end())
        line = base_line + body[:am.start()].count('\n')

        # async reset = a non-clock edge signal in sensitivity that is also
        # the subject of the first reset `if`. Find first `if (...)`.
        ifm = re.search(r'\bif\s*\(([^)]*)\)', block)
        rst_sig, pol = (None, None)
        if ifm:
            rst_sig, pol = _classify_polarity(ifm.group(1))

        mode = None
        if rst_sig and rst_sig in edges:
            # async reset is unambiguous: the signal is a sensitivity-list edge.
            mode = 'async'
        elif rst_sig and rst_sig not in edges and pol is not None and ifm \
                and ifm.start() < 60 and _RESET_NAME.search(rst_sig):
            # sync reset: the first `if` tests a RESET-named signal in the body
            # (not in the sensitivity list). The name guard avoids mistaking an
            # enable (`if(en)`) for a reset — which would otherwise raise a
            # spurious polarity/mode mismatch and break the gate.
            mode = 'sync'

        if rst_sig and mode:
            sig_modes.setdefault(rst_sig, set()).add(mode)
            if pol:
                sig_pol.setdefault(rst_sig, set()).add(pol)

            # incomplete-reset: regs in reset branch vs all NB-assigned regs
            then_block, _ = extract_block(block, ifm.end())
            reset_regs = _lhs_assigns(then_block, 'nb')
            all_regs = _lhs_assigns(block, 'nb')
            missing = all_regs - reset_regs
            for r in sorted(missing):
                findings.append(Finding(
                    path, line, 'WARN', 'incomplete-reset', r,
                    f"module '{name}': state reg '{r}' is sequentially assigned "
                    f"but has no reset value in the reset branch — it powers up "
                    f"undefined (X in sim, tool-dependent in synth)."))
        elif is_seq and not rst_sig:
            # flop without any reset
            regs = _lhs_assigns(block, 'nb')
            if regs:
                findings.append(Finding(
                    path, line, 'WARN', 'flop-without-reset',
                    sorted(regs)[0],
                    f"module '{name}': sequential block holds state "
                    f"({', '.join(sorted(regs)[:4])}"
                    f"{'…' if len(regs) > 4 else ''}) with no reset — confirm "
                    f"this is an intentional unreset pipeline register."))
        pos = end_pos

    # cross-block consistency on the same reset signal
    for sig, modes in sig_modes.items():
        if len(modes) > 1:
            findings.append(Finding(
                path, base_line, 'ERROR', 'reset-mode-mismatch', sig,
                f"module '{name}': reset '{sig}' is used as {'/'.join(sorted(modes))} "
                f"across different blocks — pick one reset strategy per signal."))
    for sig, pols in sig_pol.items():
        if len(pols) > 1:
            findings.append(Finding(
                path, base_line, 'ERROR', 'reset-polarity-mismatch', sig,
                f"module '{name}': reset '{sig}' is tested both active-low and "
                f"active-high — polarity is contradictory."))
    return findings


def lint_file(path: Path) -> List[Finding]:
    src = strip_comments(path.read_text(errors='replace'))
    out: List[Finding] = []
    for name, body, line in _segment_modules(src):
        out += analyse_module(name, body, line, str(path))
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Reset-discipline lint.')
    ap.add_argument('paths', nargs='*', help='RTL files or directories')
    ap.add_argument('--rtl-dir', help='Directory of .v/.sv to scan recursively')
    ap.add_argument('--json', help='Write findings as JSON to this path')
    ap.add_argument('--strict', action='store_true',
                    help='Fail (exit 1) on WARN findings too, not just ERROR')
    args = ap.parse_args(argv)

    files = collect_rtl_files(args.paths, args.rtl_dir)
    if not files:
        print('reset_discipline_check: FAIL — no RTL files found', file=sys.stderr)
        return 2

    findings: List[Finding] = []
    for f in files:
        try:
            findings += lint_file(f)
        except Exception as e:  # noqa: BLE001
            print(f'reset_discipline_check: parse error in {f}: {e}',
                  file=sys.stderr)
            return 2

    errs = [f for f in findings if f.severity == 'ERROR']
    warns = [f for f in findings if f.severity == 'WARN']
    fail = bool(errs) or (args.strict and bool(warns))
    verdict = 'FAIL' if fail else 'PASS'
    print(f"reset_discipline_check: {verdict} — findings: {len(findings)} "
          f"({len(errs)} error, {len(warns)} warn)")
    for fd in sorted(findings, key=lambda x: (x.file, x.line, x.severity)):
        print(f"  {fd.file}:{fd.line}: [{fd.severity}] {fd.rule}: {fd.message}")
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(f) for f in findings],
                                              indent=2))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
