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
    pipelined-width-not-parameterized : spec says "pipelined N-bit adder/mul" but
                                   the RTL hardcodes N with no parameter (the
                                   canonical TB's `#(.DATA_WIDTH(N))` won't elaborate)
    onebased-port-range          : prompt references S[k] up to k==width while the
                                   port is declared zero-based [W-1:0]; declare [W:1]
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


_CLKRST_NAME = __import__('re').compile(
    r'^(clk|clock|rst|reset|areset|nreset|rst_n|resetn|por|en|enable)$', __import__('re').I)


def _mealy_outputs(body: str, ports: List[Port]) -> List[tuple]:
    """Output ports driven COMBINATIONALLY by an expression that references a data
    input port → a Mealy output. (Clock/reset/enable refs ignored; registered
    outputs never appear since they are `<=`-driven in a clocked block.)

    Pure structural analysis — general for any RTL. It is only consulted when the
    spec itself declares a Moore requirement (see SpecContract.fsm_output_style);
    on its own a Mealy output is a valid design choice, not a defect."""
    import re
    outs = {p.name for p in ports if p.direction == 'output'}
    ins = {p.name for p in ports if p.direction == 'input' and not _CLKRST_NAME.match(p.name)}
    if not outs or not ins:
        return []
    bad: List[tuple] = []

    def scan(seg: str, assign_op: str):
        for m in re.finditer(r'\b(\w+)(?:\s*\[[^\]]*\])?\s*' + assign_op + r'\s*([^;]+);', seg):
            nm, rhs = m.group(1), m.group(2)
            if nm in outs:
                refd = sorted({t for t in re.findall(r'\b([A-Za-z_]\w*)\b', rhs)} & ins)
                if refd:
                    bad.append((nm, refd))

    for m in re.finditer(r'\bassign\s+([^;]+);', body):
        scan('assign ' + m.group(1) + ';', '=')
    for am in re.finditer(r'\balways\b\s*@\s*\(\s*\*\s*\)', body):
        scan(body[am.end():am.end() + 4000], r'=(?!=)')
    seen, out = set(), []
    for nm, refd in bad:
        if (nm, tuple(refd)) not in seen:
            seen.add((nm, tuple(refd)))
            out.append((nm, refd))
    return out


# ---------------------------------------------------------------------------
# WARN: pipelined arithmetic module hardcodes its data width instead of
# parameterizing it (ORGANIC-20260528-pipelined-adder-canonical-params).
# RTLLM-style pipelined adder/multiplier benchmarks canonically parameterize
# DATA_WIDTH (+ a stage width); the TB then instantiates `#(.DATA_WIDTH(N))`.
# A from-scratch RTL that hardcodes the width fails TB elaboration. This is
# advisory: a hardcoded width is functionally valid, only a portability nit.
# ---------------------------------------------------------------------------
def _pipelined_width_not_parameterized(spec_text: str, rtl_body: str,
                                       rtl_ports: List[Port]) -> Optional[tuple]:
    """Return (width, msg_widths) when the spec calls the design a *pipelined*
    N-bit arithmetic block AND the RTL hardcodes that width N on a port WITHOUT
    declaring any module parameter; else None.

    Conservative / corpus-clean:
      • The canonical RTLLM construction — '<N>-bit pipelined <arith>' or
        'pipelined <N>-bit <arith>' — must appear as ONE tight phrase. Requiring
        co-location (not just the three tokens scattered across a multi-KB
        protocol datasheet) is what keeps a JTAG/USB/SD spec that merely happens
        to contain "pipeline", "adder" and "64-bit" in unrelated sentences from
        false-firing. The arithmetic vocabulary is chip-AGNOSTIC, never a literal.
      • Requires the module to declare NO parameter at all — if a `parameter`
        exists the design is already parameterized (do not second-guess its name).
      • Requires the named width N to actually be hardcoded on a port (so we are
        sure the RTL pinned that exact figure rather than computing it).
    """
    import re
    low = spec_text.lower()
    arith = r'(?:adder|multiplier|subtractor|subtracter|alu|accumulator|mac|multiply|divider)'
    bit = r'(\d{1,4})[\s-]*bits?'
    # Two canonical orderings, each requiring the width, "pipelined" and the
    # arithmetic noun within one short phrase (≤~24 chars of filler between).
    pats = [
        re.compile(bit + r'[\s-]{0,3}pipelined?[\w\s,-]{0,24}?' + arith),   # "64-bit pipelined adder"
        re.compile(r'\bpipelined?[\s-]{0,3}' + bit + r'[\w\s,-]{0,24}?' + arith),  # "pipelined 64-bit adder"
    ]
    widths = set()
    for pat in pats:
        for m in pat.finditer(low):
            widths.add(int(m.group(1)))
    if not widths:
        return None
    # If the RTL already declares any parameter, it IS parameterized -> no WARN.
    if re.search(r'\bparameter\b', rtl_body):
        return None
    port_widths = {p.width for p in rtl_ports if p.width > 1}
    hit = sorted(widths & port_widths)
    if not hit:
        return None
    return (hit[0], sorted(hit))


# ---------------------------------------------------------------------------
# WARN: 1-based bit indexing — the prompt references S[k] up to k == width but
# the port is declared zero-based [W-1:0] instead of [W:1]
# (ORGANIC-20260528-spec-conformance-onebased-port-range). Declaring [W-1:0]
# then shifts every index, so a K-map / bit-mapping comes out wrong even though
# the RTL "looks" right. Advisory: pin the convention without blocking emit.
# ---------------------------------------------------------------------------
def _rtl_port_is_zero_based(rtl_body: str, name: str, width: int) -> bool:
    """True iff port `name` is declared with an explicit zero-based range whose
    span is `width` (i.e. `[width-1:0]`). Parsed straight from the RTL so we
    know the *declared* low bound (the Port dataclass keeps only the span)."""
    import re
    for m in re.finditer(
            r'\b(?:input|output|inout)\b[^;,()]*?\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*'
            r'(?:reg|wire|logic|signed|unsigned|\s)*\b' + re.escape(name) + r'\b',
            rtl_body):
        hi, lo = int(m.group(1)), int(m.group(2))
        if lo == 0 and (hi - lo + 1) == width and hi == width - 1:
            return True
    return False


# ORGANIC-20260605 corpus-sweep tightening: a width-equal index reference that
# sits in a BOUNDARY-CONDITION sentence is the out-of-range neighbour of a
# zero-based vector, not 1-based indexing evidence. Real shapes from the two
# 156-problem atomic suites (all on PASSING zero-based designs):
#   "(q[-1] and q[512]) are both zero (off)"          <- assumed-zero boundary
#   "we don't need to know out_both[3]."              <- not-needed boundary
#   "simply set out_both[99] to be zero."             <- set-to-zero boundary
_BOUNDARY_CONTEXT_RE = None  # compiled lazily below (module-level re import)


def _is_boundary_context(line: str) -> bool:
    """True iff the line containing an index reference reads as a boundary-
    condition statement (assumed-zero / set-to-zero / not-needed / out-of-range
    / non-existent) rather than normal signal indexing."""
    import re
    global _BOUNDARY_CONTEXT_RE
    if _BOUNDARY_CONTEXT_RE is None:
        _BOUNDARY_CONTEXT_RE = re.compile(
            r"(?:are|is|be|being|to\s+be|set(?:\s+\w+){0,2}\s+to)\s+"
            r"(?:both\s+|all\s+)?(?:zero|0\b|'0'|off)"
            r"|(?:don'?t|do\s+not|no)\s+need"
            r"|out\s+of\s+(?:range|bounds)"
            r"|does\s+not\s+exist|non-?existent|doesn'?t\s+exist",
            re.IGNORECASE)
    return bool(_BOUNDARY_CONTEXT_RE.search(line))


def _onebased_index_warnings(spec_text: str, rtl_body: str,
                             rtl_ports: List[Port]) -> List[tuple]:
    """Return [(name, width, maxidx)] for each port whose declared width is W,
    is declared zero-based [W-1:0] in the RTL, yet the spec body references the
    signal up to S[k] with maxidx == W (a clean 1-based signal → should be
    [W:1]). Conservative: fires only when maxidx is EXACTLY the bit-count W.

    ORGANIC-20260605 tightenings (corpus-swept over both 156-problem atomic
    suites — zero false fires on passing designs):
      * an index occurrence on a BOUNDARY-CONDITION line (assumed-zero /
        set-to-zero / not-needed / out-of-range) is excluded — it describes the
        out-of-range neighbour of a zero-based vector;
      * a prose reference to <sig>[-1] anywhere excludes the signal entirely
        (negative-neighbour talk is definitive zero-based boundary semantics)."""
    import re
    out: List[tuple] = []
    seen = set()
    lines = spec_text.splitlines()
    for p in rtl_ports:
        if p.width <= 1 or p.name in seen:
            continue
        seen.add(p.name)
        # negative-index boundary talk anywhere → definitively zero-based
        if re.search(r'\b' + re.escape(p.name) + r'\s*\[\s*-\s*1\s*\]',
                     spec_text):
            continue
        # collect every literal single-bit index S[k] referenced in the prose,
        # EXCLUDING occurrences on boundary-condition lines.
        idxs = []
        pat = re.compile(r'\b' + re.escape(p.name) + r'\s*\[\s*(\d+)\s*\]')
        for ln in lines:
            for m in pat.finditer(ln):
                if _is_boundary_context(ln):
                    continue
                idxs.append(int(m.group(1)))
        if not idxs:
            continue
        maxidx = max(idxs)
        # Only the clean 1-based case: the largest index equals the bit-COUNT
        # (not width-1). e.g. width 4 and x[4] referenced -> 1-based.
        if maxidx != p.width:
            continue
        if _rtl_port_is_zero_based(rtl_body, p.name, p.width):
            out.append((p.name, p.width, maxidx))
    return out


def check(spec: SpecContract, rtl_name: str, rtl_ports: List[Port],
          rtl_resets: dict, rtl_registered: Optional[bool],
          path: str, rtl_body: str = '', spec_text: str = '') -> List[Finding]:
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

    # ---- FSM output-style conformance (only when the spec DECLARES Moore) ----
    # Sibling of the reset-mode check: the spec picked an output style, so verify
    # the RTL honors it. Mealy-vs-Moore is otherwise a free design choice, so this
    # fires ONLY when spec.fsm_output_style == 'moore' (semantically extracted).
    #
    # ORGANIC-20260605 corpus-sweep tightenings (zero false fires across both
    # 156-problem atomic suites after these):
    #   * SKIP the whole check when the module takes its FSM state as an INPUT
    #     port (externally-stated, combinational next-state/output-logic-only
    #     modules — e.g. one-hot derive-by-inspection problems). With the state
    #     register outside the module, every output is "combinationally
    #     dependent on an input" by construction and f(state-input) is exactly
    #     the correct Moore output shape — the check cannot distinguish it
    #     from Mealy and must not try.
    #   * NEVER flag next-state-like outputs (next_state / *_next / next_*):
    #     the Moore property constrains the OUTPUT function only; next-state
    #     logic is input-dependent in every FSM, Moore included.
    if spec.fsm_output_style == 'moore' and rtl_body:
        import re as _re
        _state_input = any(
            p.direction == 'input'
            and _re.search(r'(?:^|_)state$', p.name, _re.IGNORECASE)
            for p in rtl_ports)
        _next_like = lambda nm: bool(_re.search(  # noqa: E731
            r'(?:^|_)next(?:_|$)', nm, _re.IGNORECASE))
        if not _state_input:
            for nm, refd in _mealy_outputs(rtl_body, rtl_ports):
                if _next_like(nm):
                    continue
                f.append(Finding(path, 'WARN', 'fsm-output-style-mismatch', nm,
                    f"spec declares a Moore FSM but output '{nm}' is combinationally "
                    f"dependent on input(s) {', '.join(refd)} (Mealy). A Moore output "
                    f"must be a function of state only — register it as f(state)."))

    # ---- pipelined data-width parameterization (advisory) ------------------
    # Spec calls it a pipelined N-bit adder/multiplier but the RTL hardcodes N
    # with no parameter — the canonical TB's `#(.DATA_WIDTH(N))` won't elaborate.
    if spec_text and rtl_body:
        pw = _pipelined_width_not_parameterized(spec_text, rtl_body, rtl_ports)
        if pw:
            width, all_widths = pw
            stg = max(1, width // 4)
            f.append(Finding(path, 'WARN', 'pipelined-width-not-parameterized',
                rtl_name or 'module',
                f"spec describes a pipelined {('/'.join(str(w) for w in all_widths))}-bit "
                f"arithmetic block but the RTL hardcodes width {width} with no module "
                f"parameter — add `parameter DATA_WIDTH = {width}` (+ canonical "
                f"`parameter STG_WIDTH = {stg}`) so a testbench instantiating "
                f"`#(.DATA_WIDTH({width}))` elaborates. (Defaulting to the hardcoded "
                f"width keeps behavior unchanged.)"))

    # ---- 1-based bit-indexing port range (advisory) -----------------------
    # Prompt references S[k] up to k == width while the port is declared
    # zero-based [W-1:0]; that shifts every index → declare it [W:1] instead.
    if spec_text and rtl_body:
        for name, width, maxidx in _onebased_index_warnings(spec_text, rtl_body, rtl_ports):
            f.append(Finding(path, 'WARN', 'onebased-port-range', name,
                f"'{name}' is referenced up to {name}[{maxidx}] with width {width} "
                f"(1-based indexing) but the RTL declares it zero-based [{width-1}:0] "
                f"— declare the port as [{width}:1], not [{width-1}:0], or every bit "
                f"index is off by one (K-map / bit-mapping comes out wrong)."))
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
    ap.add_argument('--semantic-manifest',
                    help='Write the LLM double-confirm records for prose-inferred '
                         'semantic fields (reset/latency/fsm-style) as JSON')
    args = ap.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f'spec_conformance_check: FAIL — spec not found: {args.spec}',
              file=sys.stderr)
        return 2
    spec_raw = spec_path.read_text(errors='replace')
    spec = extract_spec_contract(spec_raw, is_json=spec_path.suffix == '.json')
    # The two advisory body-scan WARNs (pipelined-width / 1-based index) need the
    # prompt prose, not just the extracted contract. A JSON contract carries no
    # prose body, so pass it only for natural-language / markdown / Verilog specs.
    spec_body = '' if spec_path.suffix == '.json' else spec_raw

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
    findings = check(spec, rtl_name, rtl_ports, rtl_resets, rtl_registered, chosen,
                     rtl_body, spec_text=spec_body)

    # Per the semantic-confirm rule: a finding resting on a prose-inferred field that an
    # LLM has NOT confirmed is a CANDIDATE, not truth — annotate it so the agent confirms.
    _rule_field = {'reset-mode-spec-mismatch': 'reset_mode',
                   'reset-polarity-spec-mismatch': 'reset_polarity',
                   'latency-mismatch': 'latency_registered',
                   'fsm-output-style-mismatch': 'fsm_output_style'}
    unconfirmed = {d['field'] for d in spec.semantic_confirmations if d.get('source') != 'llm'}
    for fd in findings:
        if _rule_field.get(fd.rule) in unconfirmed:
            fd.message += (" [semantic candidate — NOT LLM-confirmed (no backend); "
                           "AI must double-confirm this spec reading before acting]")
    if args.semantic_manifest:
        Path(args.semantic_manifest).write_text(json.dumps(spec.semantic_confirmations, indent=2))

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
