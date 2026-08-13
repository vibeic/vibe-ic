#!/usr/bin/env python3
"""arith_ss_corner_risk_check.py — slow-corner arithmetic-architecture advisor.

Predicts a timing-closure re-architecture: a wide single-cycle ripple-carry
add / accumulate / compare chain closes at TT but blows the SS (slow-slow,
cold, low-V) corner, forcing a carry-save / carry-select / pipelined rebuild.
Today that is only discovered *after* a full multi-corner STA round-trip. This
surfaces the risk from RTL, before synthesis.

CORRECTION, measured when this was wired (it previously claimed BOTH the spm
and sha256 benchmark ICs as motivating cases): on sha256 it fires — 21 HIGH on
the published RTL, on the real 32-bit round adders. On spm it finds NOTHING,
and NOT because a mitigation marker silences it: stripping every marker from
the published spm RTL still yields 0 findings, because that datapath is an
XOR/AND carry-save array containing no `+`, `-` or `*` at all. The rebuild spm
needed is therefore outside what this heuristic can see. Only the sha256 half
of the original claim is demonstrable from the published corpus.

It is an ADVISORY lint (a risk predictor, not a proof): default exit is 0 and
findings are WARN/INFO. `--strict` makes a HIGH-risk finding fail (exit 1) so
it can act as a gate where desired.

ENFORCEMENT: advisory

HOW `--strict` IS USED IN THE FLOW, and why it is not a promotion
-----------------------------------------------------------------
Wired at Step 2 in the `advisory_program_exit_zero` slot, which RUNS the
program, RECORDS the verdict and returns True unconditionally. That slot judges
by EXIT CODE ONLY: rc=0 is recorded as the single word `ok`. Without `--strict`
this program always exits 0, so a run with ninety-odd HIGH findings and a run
with none would produce byte-identical evidence — the disclosure the wiring
exists for would be discarded at the moment of recording. `--strict` is
therefore the RECORDING channel here, not a tightening: rc=1 is the only way the
findings reach the compliance report, and the advisory slot still cannot fail
the step.

Heuristic, per module (chip-AGNOSTIC, purely structural):
  1. Build a width table from `reg/wire/logic [H:L] name` declarations.
  2. Scan every combinational arithmetic expression that feeds state —
     RHS of a non-blocking `<=` (a registered result) or of an `assign`.
  3. For each, estimate the carry-chain width = max width of the operands /
     LHS, and the add-chain depth = number of chained +/- operators.
  4. Risk tiers (when NO mitigation marker is present in the module):
       HIGH : width >= --high-width (default 32), OR
              (width >= --warn-width AND add-chain-depth >= 3)
       MED  : width >= --warn-width (default 16)
     `*` (multiply) at width >= --warn-width is HIGH unless a DSP / compressor
     marker is present.
  5. Mitigation markers (any → the chain is assumed already structured):
       csa, carry_save, carry_select, kogge, brent_kung, han_carlson,
       sklansky, prefix, pipelin, dsp, wallace, dadda, compressor, ladner.

Recommendation emitted with every finding: replace the ripple chain with a
carry-save / carry-select adder, a parallel-prefix adder, or pipeline the add.

CLI (dual interface):
    python3 arith_ss_corner_risk_check.py <file.v|dir ...>
    python3 arith_ss_corner_risk_check.py --rtl-dir <dir> [--strict]

Exit codes:
    0 = PASS (no findings, or advisory only)   1 = FAIL (HIGH risk + --strict)
    2 = no RTL found / parse error
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


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


# Leading word-boundary only (no trailing \b) so the abbreviations also match
# as name prefixes — `csa_s`, `csa_c`, `cpa_q`, `compressor_tree`, etc. Detected
# against the RAW module text (comments included): if the author documents a
# carry-save / carry-select / prefix / pipelined strategy, this advisory trusts
# it and stays quiet. Naive undocumented wide `+` chains still fire.
MITIGATIONS = re.compile(
    r'\b(csa|cpa|carry[_-]?save|carry[_-]?select|carryselect|kogge|'
    r'brent[_-]?kung|han[_-]?carlson|sklansky|prefix[_-]?adder|prefix[_-]?add|'
    r'pipelin|dsp|wallace|dadda|compressor|ladner|fischer|3:2|3to2)', re.I)


@dataclass
class Finding:
    file: str
    line: int
    severity: str   # WARN (HIGH risk) / INFO (MED risk)
    rule: str
    symbol: str
    risk: str       # HIGH / MED
    width: int
    depth: int
    message: str


def _width_table(src: str) -> Dict[str, int]:
    """name -> bit width, from declarations with an explicit [H:L] range."""
    widths: Dict[str, int] = {}
    decl = re.compile(
        r'\b(?:reg|wire|logic|output|input|inout)\b'
        r'(?:\s+(?:reg|wire|logic))?(?:\s+(?:signed|unsigned))?\s*'
        r'\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*'
        r'([A-Za-z_]\w*(?:\s*,\s*(?!(?:input|output|inout)\b)[A-Za-z_]\w*)*)')
    for m in decl.finditer(src):
        hi, lo = int(m.group(1)), int(m.group(2))
        w = abs(hi - lo) + 1
        for nm in re.split(r'\s*,\s*', m.group(3)):
            widths[nm] = max(widths.get(nm, 0), w)
    return widths


def _segment_modules(src: str) -> List[Tuple[str, str, int]]:
    out = []
    for m in re.finditer(r'\bmodule\s+(\w+)\b', src):
        end = re.search(r'\bendmodule\b', src[m.end():])
        body = src[m.end():m.end() + end.start()] if end else src[m.end():]
        out.append((m.group(1), body, src[:m.start()].count('\n') + 1))
    return out


# An assignment statement we care about: `lhs <= rhs ;`  or  `assign lhs = rhs ;`
_ASSIGN = re.compile(
    r'(?:assign\s+)?([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(<=|=)(?!=)([^;]*);')
_ARITH = re.compile(r'[+\-](?![=>-])|\*(?!\*)')   # + - * but not ++ -> *= **
_FOR_HEADER = re.compile(r'\bfor\s*\([^)]*\)')
# a name optionally followed by a bracketed select, to read its effective width
_NAME_SEL = re.compile(r'([A-Za-z_]\w*)\s*(\[[^\]]*\])?')


def _strip_index_math(expr: str) -> str:
    """Remove bracketed sub-expressions so index/part-select math
    (`x[(a-b)*32 +: 32]`) is not mistaken for a datapath carry chain.
    Repeated to peel nested brackets."""
    prev = None
    while prev != expr:
        prev = expr
        expr = re.sub(r'\[[^\[\]]*\]', '', expr)
    return expr


#: A parenthesised SHIFT AMOUNT. Same principle as `_strip_index_math`: the
#: operand of `<<` / `>>` is a shift distance of at most log2(width) bits, so
#: arithmetic inside it is not a datapath carry chain.
#:
#: MEASURED FALSE POSITIVE this removes, on real published RTL — a rotate
#: helper written as
#:     function [31:0] rotr; input [31:0] x; input [4:0] n;
#:         begin rotr = (x >> n) | (x << (6'd32 - n)); end
#: was reported as a "32-bit add/compare chain feeding 'rotr'". The only `-` in
#: it is a 6-bit shift-amount subtraction; the datapath is two shifts and an OR.
_SHIFT_AMOUNT = re.compile(r'(<<<?|>>>?)\s*\(([^()]*)\)')


def _strip_shift_amount_math(expr: str) -> str:
    """Blank out arithmetic that only computes a shift distance."""
    prev = None
    while prev != expr:
        prev = expr
        expr = _SHIFT_AMOUNT.sub(r'\1 0', expr)
    return expr


def _paren_depths(text: str) -> List[int]:
    """Depth of `(` nesting at each character index."""
    depths = [0] * (len(text) + 1)
    d = 0
    for i, ch in enumerate(text):
        if ch == '(':
            d += 1
        depths[i] = d
        if ch == ')':
            d = max(0, d - 1)
    depths[len(text)] = d
    return depths


def _expr_carry_width(lhs: str, rhs: str, widths: Dict[str, int]) -> int:
    """Effective carry-chain width of `rhs`: widest operand used WHOLE, or the
    declared width of a `[H:L]` slice. A name used only as an index target
    (`mem[idx]`, `digest[ofs +: 32]`) contributes its SLICE width, not the
    full array/vector width."""
    w = widths.get(lhs, 0)
    for mm in _NAME_SEL.finditer(rhs):
        nm, brk = mm.group(1), mm.group(2)
        if brk:
            sm = re.match(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*$', brk)
            if sm:                       # explicit [H:L] slice → that width
                w = max(w, abs(int(sm.group(1)) - int(sm.group(2))) + 1)
            # single index `[i]` / part-select `[ofs +: n]` → element/part,
            # not a wide operand → contributes nothing.
        else:
            w = max(w, widths.get(nm, 0))
    return w


def analyse_module(name: str, body: str, base_line: int, path: str,
                   warn_w: int, high_w: int, raw_body: str = '') -> List[Finding]:
    widths = _width_table(body)
    mitigated = bool(MITIGATIONS.search(name)) or \
        bool(MITIGATIONS.search(raw_body or body))
    # for-loop induction (`for(i=0;i<N;i=i+1)`) is not a datapath adder.
    body = _FOR_HEADER.sub(' ', body)
    # The module header (`#(parameter ...) (ports);`) ends at the first ';';
    # parameter/port defaults there are not datapath and their `[^;]*` rhs can
    # over-run a comma-separated list. Skip everything before that terminator.
    header_end = body.find(';')
    if header_end < 0:
        header_end = 0
    depths = _paren_depths(body)
    findings: List[Finding] = []
    for m in _ASSIGN.finditer(body):
        if m.start() < header_end:
            continue
        # A non-blocking assignment and an `assign` are STATEMENTS: their
        # operator sits at paren depth 0. A `<=` at depth > 0 is a COMPARISON —
        # inside an assertion macro, a function call argument, an `if (…)`.
        #
        # MEASURED FALSE POSITIVE this removes, on real published RTL:
        #   `ASSERT_INIT(MaxLfsrWidth_A, LfsrDw <= $high(LFSR_COEFFS)+LUT_OFF)
        # has no terminating `;`, so `([^;]*);` swallowed every following line
        # until the next statement and reported a "168-bit add/compare chain
        # feeding 'LfsrDw'" — for a parameter, in an assertion, that is not a
        # datapath at all.
        if depths[m.start(2)] != 0:
            continue
        lhs, _op, rhs = m.group(1), m.group(2), m.group(3)
        if '"' in rhs or re.search(r'\b(?:parameter|localparam)\b', rhs):
            continue   # string-valued / over-ran into a parameter list
        # ignore index math and shift-distance math
        ops = _ARITH.findall(
            _strip_shift_amount_math(_strip_index_math(rhs)))
        if not ops:
            continue
        has_mul = '*' in ops
        add_depth = sum(1 for o in ops if o in '+-')
        width = _expr_carry_width(lhs, rhs, widths)
        if width == 0:
            continue  # width unknown — don't guess
        line = base_line + body[:m.start()].count('\n')

        risk = None
        if has_mul and width >= warn_w and not mitigated:
            risk = 'HIGH'
            kind = 'wide-mult-comb'
            why = f"{width}-bit combinational multiply"
        elif not mitigated and (width >= high_w or
                                (width >= warn_w and add_depth >= 3)):
            risk = 'HIGH'
            kind = 'wide-ripple-add'
            why = (f"{width}-bit add/compare chain (depth {add_depth}) in a "
                   f"single-cycle path")
        elif not mitigated and width >= warn_w:
            risk = 'MED'
            kind = 'ripple-add'
            why = f"{width}-bit add/compare chain (depth {add_depth})"
        if not risk:
            continue
        sev = 'WARN' if risk == 'HIGH' else 'INFO'
        findings.append(Finding(
            path, line, sev, kind, lhs, risk, width, add_depth,
            # SAY ONLY WHAT IS DEMONSTRABLE. This sentence used to end
            # "(This is the spm/sha256 re-architecture pattern.)" and shipped
            # on all 85 HIGH findings the published corpus produces — while
            # the module docstring's own CORRECTION records that only the
            # sha256 half reproduces: on spm this heuristic finds NOTHING even
            # with every mitigation marker stripped, because that datapath is
            # a carry-save XOR/AND array with no `+`, `-` or `*` in it. A
            # user-facing message must not carry a claim the program's own
            # measurement has already retracted.
            f"module '{name}': {why} feeding '{lhs}' is a slow-corner (SS) "
            f"timing risk — consider a carry-save / carry-select / "
            f"parallel-prefix adder or pipelining. Predicted from RTL "
            f"STRUCTURE, not measured: confirm on a slow-corner STA run. "
            f"(Reproduced on this repo's corpus for a 32-bit round-adder "
            f"datapath; a carry-save array containing no +/-/* is invisible "
            f"to this heuristic.)"))
    return findings


def lint_file(path: Path, warn_w: int, high_w: int) -> List[Finding]:
    raw = path.read_text(errors='replace')
    src = strip_comments(raw)
    raw_mods = {nm: b for nm, b, _ in _segment_modules(raw)}
    out: List[Finding] = []
    for name, body, line in _segment_modules(src):
        out += analyse_module(name, body, line, str(path), warn_w, high_w,
                              raw_mods.get(name, ''))
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Slow-corner arithmetic risk advisor.')
    ap.add_argument('paths', nargs='*', help='RTL files or directories')
    ap.add_argument('--rtl-dir', help='Directory of .v/.sv to scan recursively')
    ap.add_argument('--warn-width', type=int, default=16,
                    help='Width at/above which a ripple chain is MED risk')
    ap.add_argument('--high-width', type=int, default=32,
                    help='Width at/above which a ripple chain is HIGH risk')
    ap.add_argument('--strict', action='store_true',
                    help='Exit 1 if any HIGH-risk finding (default: advisory, exit 0)')
    ap.add_argument('--json', help='Write findings as JSON')
    args = ap.parse_args(argv)

    files = collect_rtl_files(args.paths, args.rtl_dir)
    if not files:
        print('arith_ss_corner_risk_check: no RTL files found', file=sys.stderr)
        return 2

    findings: List[Finding] = []
    for f in files:
        try:
            findings += lint_file(f, args.warn_width, args.high_width)
        except Exception as e:  # noqa: BLE001
            print(f'arith_ss_corner_risk_check: parse error in {f}: {e}',
                  file=sys.stderr)
            return 2

    high = [f for f in findings if f.risk == 'HIGH']
    med = [f for f in findings if f.risk == 'MED']
    fail = args.strict and bool(high)
    # Advisory default never prints the token FAIL (keeps the MCP PASS contract).
    verdict = 'FAIL' if fail else 'PASS'
    note = '' if fail else ' (advisory)'
    print(f"arith_ss_corner_risk_check: {verdict}{note} — findings: "
          f"{len(findings)} ({len(high)} HIGH, {len(med)} MED)")
    for fd in sorted(findings, key=lambda x: (x.file, x.line)):
        print(f"  {fd.file}:{fd.line}: [{fd.risk}] {fd.rule}: {fd.message}")
    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(outp, json.dumps([asdict(f) for f in findings], indent=2))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
