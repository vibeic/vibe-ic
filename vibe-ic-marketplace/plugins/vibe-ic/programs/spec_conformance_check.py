#!/usr/bin/env python3
"""spec_conformance_check.py — Spec↔RTL contract-conformance gate.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This gate is wired at flow step 2 as an
`advisory_program_exit_zero` clause, and the choice is a measurement rather
than caution: run over the five project trees carrying BOTH an L9 and an RTL
directory it reads 1 PASS / 4 FAIL, and neither failure mode is "the RTL is
wrong" — one is a `--top` that defaults to the first module found, the other is
an L9 that predates the port-width repair shipped beside this declaration.
Blocking today would redden four of five designs over their spec's age.

The step-2 clause carries the full measurement and the condition that would
promote this to `program_exit_zero`. Until then this runs, prints and cannot
deny the step its PASS tier — and it says so here, because until a gate states
its intent where the audit reads, "wired where it cannot block" and "nobody
decided" are the same record.

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
    zero-output-ports            : module parsed with >=1 port but ZERO
                                   output/inout ports — a sink no testbench can
                                   observe; deterministic signature of a
                                   mis-read interface (e.g. prompt direction
                                   typo). Fires on RTL structure alone, so a
                                   spec repeating the typo cannot mask it.
    reset-mode-spec-mismatch     : spec says sync, RTL is async (or vice-versa)
    reset-polarity-spec-mismatch : spec says active-high, RTL active-low (or v.v.)
    msbfirst-direction-mismatch  : spec says the serial data loads MSB-first but
                                   the RTL inserts the new bit at the MSB end of
                                   a parallel-consumed register
                                   (`vec <= {bit, vec[W-1:1]}`) — the word comes
                                   out bit-REVERSED; the first-received bit must
                                   END at the MSB (left-shift idiom).
    moore-output-reset-gated     : spec ties an N-cycle assertion window to
                                   RESET itself ("whenever ... reset, assert
                                   <sig> for N cycles") but the RTL ANDs that
                                   output with the negated reset — a held or
                                   re-asserted reset then eats assertion
                                   cycles (held-reset window N-1 instead of N).
    shift-implemented-as-rotate  : spec describes a SHIFTER (not explicitly
                                   rotate-only) but the RTL carries an
                                   unambiguous barrel-ROTATE wrap signature
                                   (`(x<<n)|(x>>m)` opposite shifts of one x,
                                   `{x[a:0], x[W-1:b]}` zero-fill-free self-wrap,
                                   `{x,x}>>k` doubled-vector shift, or a
                                   modulo/mask index wrap `x[(i+/-k) % W]` /
                                   `x[(i+/-k) & (W-1)]` — the RTLLM barrel_shifter
                                   generate form). A genuine rotate-only spec
                                   disarms it (§4.05).
    waveform-peak-hold-dropped   : spec describes a triangle/ramp/sawtooth
                                   generator that HOLDS the peak/trough but the
                                   RTL toggles direction the instant it hits the
                                   extreme with NO hold/dwell state. An explicit
                                   no-hold / plain-sawtooth spec disarms it.
    ordered-phase-monitoring-early: spec explicitly says to assert an output for
                                   one cycle and THEN monitor an input, but the
                                   RTL reads that input in the output-owning FSM
                                   state, collapsing the two ordered phases.
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
    from _specrtl_common import (Port, SpecContract, WIDTH_UNKNOWN,
                                 classify_rtl_resets,
                                 extract_spec_contract, parse_rtl_ports,
                                 strip_comments)
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _specrtl_common import (Port, SpecContract, WIDTH_UNKNOWN,
                                 classify_rtl_resets,
                                 extract_spec_contract, parse_rtl_ports,
                                 strip_comments)

# The canonical set of conformance rules whose ERROR finding is EMIT-BLOCKING in
# the Shape-C gate (benchmark/gates_atomic.py). Single source of truth: the gate
# AND the tier/stability pipeline both consult this so a "Tier-1 solved" emit must
# survive the SAME conformance the real blind run applies (no stability-test gap).
EMIT_BLOCKING_CONFORMANCE_RULES = frozenset({
    "onebased-port-range",
    "fsm-output-style-mismatch",
    "port-missing",
    "zero-output-ports",
    "msbfirst-direction-mismatch",
    "moore-output-reset-gated",
    "shift-implemented-as-rotate",
    "waveform-peak-hold-dropped",
    "fsm-onehot-missing-transition",
    "sync-reset-next-state-redundant-gate",
    "ordered-phase-monitoring-early",
    "spec-interface-empty-but-declared",
})


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


# ---------------------------------------------------------------------------
# ERROR: MSB-first serial-load direction inversion
# (ORGANIC-20260605-msbfirst-direction-conformance-rule) — the lesson→program
# promotion of the shift-direction expert lesson. Prose guidance cut the
# inversion rate from 2/2 relevant agents to 1/32 across a fully-audited
# campaign, but cannot reach zero; the residual wrong form is a STRUCTURAL
# signature detectable mechanically on both halves:
#   prompt half : an MSB-first / most-significant-bit-first serial-load phrase
#   RTL half    : `vec <= {bit, vec[W-1:1]}` — the new bit enters at the MSB
#                 end, so after W cycles the FIRST-received bit sits at the
#                 LSB: the assembled word is bit-REVERSED. Under MSB-first
#                 reception the first bit must END at the MSB → the correct
#                 idiom is the left shift `vec <= {vec[W-2:0], bit}`.
# Conservative guards (each kills a real legitimate idiom from the corpus):
#   * prompt must ALSO carry serial/shift vocabulary, and must NOT carry an
#     LSB-first phrase (configurable/dual-direction prompts are ambiguous);
#   * the inserted bit's base identifier must differ from the vector (a
#     rotate `q <= {q[0], q[W-1:1]}` / arithmetic shift `{q[W-1], q[W-1:1]}`
#     is not a serial load);
#   * a same-vector LEFT-entry form elsewhere means a runtime-muxed
#     dual-direction design — cannot statically conclude a mismatch;
#   * the vector must be CONSUMED AS A PARALLEL WORD (multi-bit output port
#     or whole-vector use): a delay line that only taps vec[0] re-emits bits
#     in arrival order, so its entry end is immaterial.
# chip-AGNOSTIC: pure phrase + expression structure; no IC/vendor literals.
# ---------------------------------------------------------------------------
_MSB_TOKEN = r'(?:msb|most[\s-]+significant[\s-]+bit)'
_LSB_TOKEN = r'(?:lsb|least[\s-]+significant[\s-]+bit)'


def _spec_declares_msbfirst_serial(spec_text: str) -> bool:
    """True iff the prompt declares an MSB-first serial load: an MSB-first
    phrase (either word order), NO LSB-first phrase, plus serial/shift
    vocabulary somewhere in the prose."""
    import re

    def _first_phrase(token: str) -> bool:
        return bool(re.search(
            r'\b' + token + r'\b(?:\W+\w+){0,5}?\W+first\b'
            r'|\bfirst\b(?:\W+\w+){0,6}?\W+' + token + r'\b',
            spec_text, re.IGNORECASE))

    if not _first_phrase(_MSB_TOKEN) or _first_phrase(_LSB_TOKEN):
        return False
    return bool(re.search(
        r'\b(?:shift(?:s|ed|ing)?|serial(?:ly)?|bit[\s-]?stream'
        r'|one\s+bit\s+(?:per|at\s+a\s+time)|bit\s+at\s+a\s+time)\b',
        spec_text, re.IGNORECASE))


def _vector_consumed_as_word(rtl_body: str, vec: str,
                             rtl_ports: List[Port]) -> bool:
    """True iff `vec` is read as a parallel word: it IS a multi-bit output
    port, or a bare whole-vector READ (no bit-select, not an assignment LHS)
    appears outside its own declaration (e.g. `assign data_out = vec;`,
    `vec == PATTERN`). `vec = …` / `vec <= …` are writes, not reads; `==`
    survives the lookahead because the first `=` is followed by `=`."""
    import re
    for p in rtl_ports:
        if p.name == vec and p.direction == 'output' and p.width > 1:
            return True
    for m in re.finditer(
            r'\b' + re.escape(vec) + r'\b(?!\s*(?:\[|<|=(?!=)))', rtl_body):
        ls = rtl_body.rfind('\n', 0, m.start()) + 1
        le = rtl_body.find('\n', m.start())
        line = rtl_body[ls:le if le != -1 else len(rtl_body)]
        if re.match(r'\s*(?:reg|wire|logic|input|output|inout|integer)\b', line):
            continue  # declaration occurrence
        return True
    return False


def _msb_entry_serial_loads(rtl_body: str,
                            rtl_ports: List[Port]) -> List[tuple]:
    """Return [(vec, bit_src)] for each nonblocking `vec <= {bit, vec[hi:1]}`
    whose inserted bit comes from OUTSIDE the vector and whose vector is
    consumed as a parallel word, with no same-vector left-entry form (see
    the rule comment for why each guard exists)."""
    import re
    out, seen = [], set()
    pat = re.compile(
        r'\b([A-Za-z_]\w*)\s*<=\s*\{\s*'
        r'([A-Za-z_]\w*)((?:\s*\[[^\[\]]+\])?)\s*,\s*'
        r'\1\s*\[\s*[^\]:]+?\s*:\s*1\s*\]\s*\}')
    for m in pat.finditer(rtl_body):
        vec, src_base = m.group(1), m.group(2)
        if src_base == vec:
            continue  # rotate / arithmetic-shift self-feedback
        if re.search(r'\b' + re.escape(vec) + r'\s*<=\s*\{\s*'
                     + re.escape(vec) + r'\s*\[', rtl_body):
            continue  # runtime-muxed dual-direction design
        if not _vector_consumed_as_word(rtl_body, vec, rtl_ports):
            continue  # delay line / single-bit tap — entry end immaterial
        t = (vec, (src_base + m.group(3)).replace(' ', ''))
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# ERROR: reset-tied assertion window AND-ed with the negated reset
# (ORGANIC-20260606-moore-output-reset-gated-rule) — lesson→program promotion,
# same capture-ladder shape as the MSB-first direction rule. Spec half: a
# clause of the form "when(ever) ... reset ..., assert <sig> for N cycles"
# ties the assertion window to the reset STATE — the canonical Moore reading
# asserts <sig> the cycle after any edge sampling reset high, INCLUDING while
# reset is held. RTL half: the named output's driver carries a conjunction
# with the negated reset (`assign <sig> = <expr> && !<reset>` / `& ~<reset>`,
# or the same RHS shape inside an always block). Together they are a
# deterministic mismatch signature: any acceptance run holding reset more
# than one cycle (or re-resetting mid-run) observes a missing assertion
# cycle (held-reset contiguous window N-1 instead of N).
# Conservative guards (per the filing):
#   (a) the spec clause must tie the window to reset ITSELF — clauses anchored
#       to reset RELEASE ("after reset is deasserted/released") never fire;
#   (b) only the spec-NAMED asserted output is examined;
#   (c) skipped entirely when the spec declares an ASYNCHRONOUS reset (an
#       async-clear contract is a different class).
# The deferred-window mis-reading (counter starts after release) has no
# negated-reset conjunction, so it stays lesson-covered — out of scope here.
# chip-AGNOSTIC: pure phrase + expression structure; no IC/vendor literals.
# ---------------------------------------------------------------------------
_RESET_TIED_ASSERT_RES = (
    # "when(ever) ... reset ..., assert <sig> for N cycles"
    __import__('re').compile(
        r'\bwhen(?:ever)?\b[^.!?]{0,60}?\breset\b[^.!?]{0,60}?'
        r'\bassert\s+`?([A-Za-z_]\w*)`?\s+for\s+(?:exactly\s+)?\d+\s+'
        r'(?:clock\s+)?cycles?', __import__('re').IGNORECASE),
    # "assert <sig> for N cycles when(ever) ... reset"
    __import__('re').compile(
        r'\bassert\s+`?([A-Za-z_]\w*)`?\s+for\s+(?:exactly\s+)?\d+\s+'
        r'(?:clock\s+)?cycles?[^.!?]{0,60}?\bwhen(?:ever)?\b'
        r'[^.!?]{0,40}?\breset\b', __import__('re').IGNORECASE),
)
_RESET_RELEASE_RE = __import__('re').compile(
    r'de-?assert|releas|removed|lifted|negated|cleared', __import__('re').IGNORECASE)


def _spec_reset_tied_assert_signals(spec_text: str) -> List[str]:
    """Signals whose N-cycle assertion window the spec ties to reset ITSELF.
    Sentence-scoped (soft-unwrapped); release-anchored sentences are excluded
    per guard (a)."""
    from _specrtl_common import _soft_unwrap_sentences
    out: List[str] = []
    for sent in _soft_unwrap_sentences(spec_text):
        if _RESET_RELEASE_RE.search(sent):
            continue
        for rx in _RESET_TIED_ASSERT_RES:
            for m in rx.finditer(sent):
                if m.group(1) not in out:
                    out.append(m.group(1))
    return out


def _output_reset_gated(rtl_body: str, sig: str,
                        rtl_ports: List[Port]) -> Optional[str]:
    """Return the reset name when `sig`'s driver RHS conjoins the negated
    reset (`... && !rst` / `... & ~rst`), else None. Only RHS conjunction
    shapes count — an `if (reset)` branch is ordinary reset structure."""
    import re
    reset_names = [p.name for p in rtl_ports
                   if re.search(r'rst|reset', p.name, re.IGNORECASE)]
    if not reset_names:
        return None
    for m in re.finditer(r'\b' + re.escape(sig) + r'\s*(?:<=|=)(?!=)\s*([^;]+);',
                         rtl_body):
        rhs = m.group(1)
        if '&' not in rhs:
            continue
        for rn in reset_names:
            if re.search(r'[!~]\s*\(?\s*' + re.escape(rn) + r'\b', rhs):
                return rn
    return None


# ---------------------------------------------------------------------------
# ERROR: a SHIFTER spec implemented as a ROTATE
# (ORGANIC-20260617-escalate-prose-mandatory-discriminator-selftbs — program-
# first escalation of the prose "MANDATORY pre-emit self-TB" discriminator).
# The lessons corpus already prescribes "'shifts or rotates' is NOT rotate-only
# → LOGICAL shift" + a mandatory all-ones>>max self-TB, but a fresh clean-room
# author repeatedly reads it, cites it, then overrides it. This mechanizes the
# discriminator the lesson names as a deterministic emit-assert the author
# cannot override.
#
# Spec half: the prose describes a SHIFTER ("shift" / "shifts or rotates" / a
# shift opcode/mode) and does NOT make the operation rotate-only. §4.05
# OVERRIDE — if the spec EXPLICITLY says the operation is rotate / rotate-only
# / circular / barrel-rotate, the rule is disarmed (a genuine rotate design is
# correct).
#
# RTL half: a HIGH-PRECISION barrel-ROTATE signature only — the unambiguous
# idioms that can ONLY be a wrap-around rotate, never a logical shift:
#   (1) OR of two OPPOSITE shifts of the SAME signal:
#       (x << n) | (x >> m)   /   (x >> n) | (x << m)
#       (a logical shift OR-fills with the OTHER end's bits of the SAME word —
#        the defining wrap of a rotate; a logical shift zero-fills.)
#   (2) a concat that wraps the SAME vector covering every bit with NO literal
#       zero/one fill:  {x[a:0], x[W-1:b]}  (both parts bit-selects of one x).
# A correct LOGICAL-shift design (`x >> n`, `x << n`, a zero-fill concat
# `{1'b0, x[..]}` / `{x[..], 1'b0}`) carries NEITHER signature, so it NEVER
# fires. ZERO-FALSE-FIRE is the binding constraint: when the structural form
# is anything but these two unambiguous rotate idioms, the rule stays silent.
# chip-AGNOSTIC: pure operator/concat structure + shift/rotate vocabulary.
# ---------------------------------------------------------------------------
_SHIFT_VERB_RE = __import__('re').compile(
    r'\b(?:shift(?:s|ed|ing|er)?|logical[\s-]+shift|arithmetic[\s-]+shift)\b',
    __import__('re').IGNORECASE)
# explicit rotate-only / circular intent → §4.05 disarm
_ROTATE_INTENT_RE = __import__('re').compile(
    r'\b(?:rotat(?:e|es|ed|ing|or|ion)|circular(?:ly)?\s+shift|'
    r'barrel[\s-]+rotat\w*|cyclic(?:ally)?\s+shift|wrap[\s-]?around)\b',
    __import__('re').IGNORECASE)
# ORGANIC-20260618 barrel_shifter (RTLLM round-19) HARDENING of the §784 carve-
# out. A spec that OFFERS BOTH operations in a disjunction — "shift OR rotate",
# "shifts or rotates [the bits]", "shift/rotate" — is NOT rotate-only: the
# lessons corpus (lessons.md "barrel shifter — default is LOGICAL shift") binds
# it to a LOGICAL shift with zero-fill for the asserted (default) test. The
# previous "ANY rotate token disarms" rule UNDER-FIRED on exactly this canonical
# case (a pure left-rotate RTL silently passed the right-shift hidden TB). This
# phrase RE-ARMS the gate ONLY for the BOTH-OFFERED disjunction; a genuine
# rotate-ONLY spec (rotate / circular present but NO shift-VERB-or-rotate
# disjunction) still disarms. Both word orders, short window, hyphen/slash form.
_SHIFT_OR_ROTATE_RE = __import__('re').compile(
    r'\b(?:'
    r'shift\w*\s*(?:/|\bor\b|\band\b)\s*rotat\w*'     # shift or/and/slash rotate
    r'|rotat\w*\s*(?:/|\bor\b|\band\b)\s*shift\w*'    # rotate or/and/slash shift
    r')',
    __import__('re').IGNORECASE)
# ORGANIC-20260618 ring_counter / parallel2serial §4.05 BASELINE FALSE-FIRE FIX.
# The baseline disarm vocabulary (`_ROTATE_INTENT_RE`) only matched a rotate
# token glued to "shift" ("circular SHIFT" / "cyclic SHIFT") plus a bare
# "rotate" / "wraparound". It UNDER-disarmed two CORRECT RTLLM designs whose
# specs legitimately describe a CYCLIC / WRAP-AROUND operation in OTHER words
# and whose golden RTL is a same-vector bijective concat (a true rotate):
#   • ring_counter  — "8-bit ring counter for cyclic state sequences ... it
#                      wraps around to the LSB, creating a cyclic sequence"
#                      (golden: `{state[6:0], state[7]}`)
#   • parallel2serial — "shifts the data register one bit to the left, with the
#                      most significant bit shifted to the least significant
#                      bit" (golden: `{data[2:0], data[3]}`)
# Neither spec carries the disjunction, both pass their own hidden TBs, so they
# are CORRECT and MUST emit. This widens the rotate/cyclic disarm vocabulary so
# such a spec DISARMS the gate (as a genuine rotate-only design must).
#   (1) _CYCLIC_WRAP_RE — bare cyclic / circular / rotational / ring-counter
#       vocabulary + a "wrap(s)? (a)round" phrase (the generic rotate idiom,
#       not requiring the word "shift" beside it).
#   (2) _MSB_TO_LSB_WRAP_RE — the STRUCTURAL prose signature of a wrap: a
#       most-significant-bit ↔ least-significant-bit move/shift/wrap/rotate/feed
#       within one sentence (either MSB→LSB or LSB→MSB order). This is exactly
#       the bijective self-wrap a rotate performs and is what the same-vector
#       concat in the golden RTL implements.
# ZERO-FALSE-DISARM is binding: a PLAIN shifter spec ("logical shift", "shift
# right/left", "shifted-in bits are zero", "insert d into the MSB") carries
# NEITHER signature, so it stays ARMED. A "shift OR rotate" disjunction spec
# (barrel_shifter) keeps `both_offered=True` so it STAYS ARMED regardless — the
# original #784/#790/#20 gate behaviour on the disjunction case is byte-for-byte
# preserved. chip-AGNOSTIC: pure rotate/cyclic vocabulary + MSB↔LSB structure.
#
# ORGANIC-20260618 round-2 (Step-2.7) — the round-1 vocabulary was FAR TOO BROAD
# and FALSE-DISARMED common LOGICAL-shift specs (a §4.05 FALSE-SKIP: a wrong
# rotate then ships under a plain-shifter spec). Three precision fixes:
#   (1) _CYCLIC_WRAP_RE no longer matches a BARE cyclic/circular/rotational token
#       (those hit "circular BUFFER", "CYCLIC redundancy" etc.); it requires a
#       ring-counter, OR a wrap-around whose target is a BIT POSITION
#       (LSB/MSB/bit/first|last bit/other end) — not a counter "wraps around to
#       zero/its max".
#   (2) _MSB_TO_LSB_WRAP_RE requires the bit to MOVE *to/into* the other end
#       (a genuine wrap: "MSB shifted TO the LSB"), NOT merely co-mention
#       ("MSB shifted OUT … LSB filled with zero" is a logical shift).
#   (3) _LOGICAL_FILL_VETO_RE — an explicit zero-fill / constant-fill / feedback-
#       load statement PROVES a logical shift, so it VETOES the widened disarm
#       (the genuine ring_counter / parallel2serial wraps carry no such fill).
# ORGANIC-20260618 round-3 (Step-2.7): reduced to the ring-counter token ONLY.
# The round-2 "wrap(s) around to a BIT" branch still false-disarmed a LOGICAL
# shifter feeding a "circular BUFFER" whose POINTER "wraps around to bit 0", and
# a bare cyclic/circular token hit unrelated prose. A genuine rotate is caught
# either by `_ROTATE_INTENT_RE` (rotate / circular-shift / wrap-around) or, for
# the ring_counter design, by this ring-counter token; parallel2serial is caught
# by `_MSB_TO_LSB_WRAP_RE`. For a bug-catching EMIT-BLOCK the §4.05 fail-safe is
# to STAY ARMED when ambiguous, so the vocabulary is kept tight.
_CYCLIC_WRAP_RE = __import__('re').compile(
    r'\bring[\s-]?counter\b',
    __import__('re').IGNORECASE)
# The destination bit carries a SAME-REGISTER constraint `(?!\s+of\b)` — a wrap
# is the shifted-out bit re-entering the SAME word, so a CROSS-register side-feed
# ("MSB carried to the LSB OF the CRC register") is NOT a self-wrap and must not
# disarm (ORGANIC-20260618 round-4 §4.05 false-skip fix).
# The "to/into" DESTINATION gap is TEMPERED — it stops at a conjunction
# (and/or) or a clause boundary (,;.!?), so the destination must be the LSB/MSB
# ITSELF, not a DIFFERENT named target in a separate clause. ORGANIC-20260618
# round-6 §4.05 false-skip fix: a plain SIPO/shift-register spec where the MSB
# is shifted into one destination ("…into the output register AND the least
# significant bit is loaded with d") must NOT match the self-wrap signature.
_MSB_TO_LSB_WRAP_RE = __import__('re').compile(
    r'\b(?:most[\s-]+significant[\s-]+bit|msb)\b[^.!?]{0,40}?'
    r'\b(?:shift|wrap|rotat|mov|cycl|carr|feed|rout|copy|copi)\w*\s+'
    r'(?:in)?to\b(?:(?!\b(?:and|or)\b)[^.!?,;]){0,25}?'
    r'\b(?:least[\s-]+significant[\s-]+bit|lsb)\b(?!\s+of\b)'
    r'|\b(?:least[\s-]+significant[\s-]+bit|lsb)\b[^.!?]{0,40}?'
    r'\b(?:shift|wrap|rotat|mov|cycl|carr|feed|rout|copy|copi)\w*\s+'
    r'(?:in)?to\b(?:(?!\b(?:and|or)\b)[^.!?,;]){0,25}?'
    r'\b(?:most[\s-]+significant[\s-]+bit|msb)\b(?!\s+of\b)',
    __import__('re').IGNORECASE)
# A negation/contrast token IMMEDIATELY before a disarm signal (only an optional
# article may intervene) suppresses it — "Unlike a ring counter" / "rather than a
# ring counter". ORGANIC-20260618 round-5: ADJACENCY-anchored, NOT a 28-char
# window — the wide window false-suppressed "Unlike a LFSR, the ring counter…"
# (the negation there targets a DIFFERENT device, so the ring-counter disarm must
# survive). The contrasted token must directly follow the negation+article.
_NEG_BEFORE_RE = __import__('re').compile(
    r'\b(?:not|never|unlike|other\s+than|rather\s+than|instead\s+of)\s+'
    r'(?:a|an|the|any|some|each|one)?\s*$',
    __import__('re').IGNORECASE)
# A LOGICAL-shift signal that PROVES the design is NOT rotate-only and so VETOES
# the (step-4) MSB↔LSB self-wrap disarm only (stay ARMED → the gate still fires
# on a rotate RTL). Two families: (a) an explicit zero / constant / feedback /
# set-to-0 / cleared fill of the vacated bit; (b) an explicit "logical|arithmetic
# shift" assertion. ORGANIC-20260618 round-4: the polarity-BLIND discard /
# negation arms were REMOVED (they false-fired on a genuine ring counter that
# said "nothing is dropped"); discard/negation is now handled by the polarity-
# aware `_affirmative_at` on the positive signals, and an affirmative wrap-back
# (`_RECIRCULATE_RE`) takes priority OVER this veto.
_LOGICAL_FILL_VETO_RE = __import__('re').compile(
    r'\bzero[\s-]?fill\w*'
    r'|\bfill\w*\b[^.!?]{0,30}?\b(?:0|zero|zeros|low|logic\s*0)\b'
    r'|\b(?:0|zero|zeros)\b[^.!?]{0,20}?\b(?:fill\w*|shift\w*\s+in(?:to)?|'
    r'inserted?|loaded|fed)\b'
    r'|\b(?:set|cleared?|becomes?|driven|forced?|tied)\b[^.!?]{0,15}?'
    r'\b(?:to\s+)?(?:0|zero|low|logic\s*0)\b'
    r'|\bshift\w*[\s-]+in(?:to)?\b[^.!?]{0,30}?\b(?:0|zero|zeros|low)\b'
    r'|\b(?:inserted?|loaded|fed)\b[^.!?]{0,30}?\b(?:0|zero|zeros|'
    r'feedback|xor|serial)\b'
    r'|\bloaded\s+with\b[^.!?]{0,30}?\b(?:feedback|xor|0|zero)\b'
    r'|\bvacated\b[^.!?]{0,20}?\b(?:0|zero)\b'
    r'|\b(?:logical|arithmetic)\b[\s-]*(?:left[\s-]+|right[\s-]+)?shift\w*'
    r'|\bshift\w*\b[^.!?]{0,15}?\b(?:logical|arithmetic)\b',
    __import__('re').IGNORECASE)


def _affirmative_at(spec_text: str, start: int) -> bool:
    """True iff the disarm signal at `start` is NOT negated/contrasted by a
    nearby preceding token (same sentence, ~28 chars) — so "Unlike a ring
    counter" / "rather than recirculated" do NOT disarm."""
    return _NEG_BEFORE_RE.search(spec_text[:start]) is None


def _spec_describes_rotate_or_cyclic(spec_text: str) -> bool:
    """True iff the prose expresses a genuine rotate / circular-shift / cyclic /
    wrap-around intent. PRIORITY-ORDERED (ORGANIC-20260618 round-5):
      (1) the precise rotate-token vocabulary (`_ROTATE_INTENT_RE`) always wins;
      (2) an AFFIRMATIVE ring-counter token (`_CYCLIC_WRAP_RE`, not negated);
      (3) a SAME-REGISTER MSB↔LSB self-wrap (`_MSB_TO_LSB_WRAP_RE`) UNLESS an
          explicit zero/constant/logical-shift fill (`_LOGICAL_FILL_VETO_RE`)
          proves a logical shift.
    The round-4 `_RECIRCULATE_RE` step was REMOVED — every genuine-rotate case
    already disarms via the ring-counter token or the MSB↔LSB self-wrap, so the
    bare "wraps back" arm only added a FALSE-SKIP surface (it matched a control-
    path POINTER/COUNTER "wraps back to zero" while the DATA path was a plain
    zero-fill shift). Step 2 is polarity-aware (`_affirmative_at`). Used by
    `_spec_describes_plain_shifter` as the §4.05 disarm predicate (gated by the
    BOTH-offered disjunction exception)."""
    if _ROTATE_INTENT_RE.search(spec_text) is not None:
        return True
    m = _CYCLIC_WRAP_RE.search(spec_text)
    if m is not None and _affirmative_at(spec_text, m.start()):
        return True
    if (_MSB_TO_LSB_WRAP_RE.search(spec_text) is not None
            and _LOGICAL_FILL_VETO_RE.search(spec_text) is None):
        return True
    return False


def _spec_describes_plain_shifter(spec_text: str) -> bool:
    """True iff the prose describes a SHIFTER (shift vocabulary present) and the
    operation is NOT rotate-only.

    §4.05 disarm: a genuine rotate / circular / barrel-rotate / wrap-around /
    cyclic-shift / cyclic / rotational / ring-counter intent, OR the structural
    MSB↔LSB wrap signature (`_spec_describes_rotate_or_cyclic`), normally disarms
    the rule — a genuine rotate/cyclic design must emit unblocked. (ORGANIC-
    20260618 widened the vocabulary so the CORRECT ring_counter /
    parallel2serial specs — which describe a cyclic / MSB↔LSB-wrap operation in
    words other than "circular shift" — DISARM instead of false-blocking.)

    EXCEPTION (ORGANIC-20260618): a spec that OFFERS BOTH operations in a
    disjunction ("shift or rotate" / "shifts or rotates" / "shift/rotate") is
    NOT rotate-only — the lessons corpus binds it to a LOGICAL shift with
    zero-fill, so the gate RE-ARMS even though a rotate token is present. Only
    the BOTH-offered disjunction re-arms; a rotate-only / cyclic spec stays
    disarmed."""
    if not _SHIFT_VERB_RE.search(spec_text):
        return False
    both_offered = _SHIFT_OR_ROTATE_RE.search(spec_text) is not None
    if _spec_describes_rotate_or_cyclic(spec_text) and not both_offered:
        return False
    return True


def _concat_assignment_lhs(rtl_body: str, concat_start: int):
    """The variable a `{a, b}` concat starting at `concat_start` is assigned to:
    `q_next = {q[0], q[31:1]};` -> 'q_next'. Returns the base name or None."""
    import re
    head = rtl_body[:concat_start].rstrip()
    m = re.search(r'([A-Za-z_]\w*)\s*(?:<=|=)\s*$', head)
    return m.group(1) if m else None


def _has_galois_tap_feedback(rtl_body: str, vec_base: str) -> bool:
    """A Galois LFSR uses the SAME `{q[0], q[W-1:1]}` wrap concat as a right-rotate
    but then XOR-modifies specific TAP bits of the assigned word with the fed-back
    bit (`q_next[21] ^= q[0]` or `q_next[21] = q_next[21] ^ q[0]`). That tap-XOR is
    LINEAR FEEDBACK — it breaks the bijection, so the wrap is NOT a data rotate.
    A PURE rotate has no such bit-indexed XOR-assignment of the rotated word, so it
    is unaffected (the §4.05 no-leak property). chip-AGNOSTIC: any vector name."""
    import re
    if not vec_base:
        return False
    v = re.escape(vec_base)
    # form 1: q_next[<idx>] ^= <fb>
    if re.search(rf'\b{v}\s*\[[^\]]+\]\s*\^=', rtl_body):
        return True
    # form 2: q_next[<idx>] = q_next[<idx>] ^ <fb>   (self bit-XOR feedback)
    if re.search(rf'\b{v}\s*\[[^\]]+\]\s*=\s*{v}\s*\[[^\]]+\]\s*\^', rtl_body):
        return True
    return False


def _rtl_rotate_signatures(rtl_body: str) -> List[str]:
    """Return the matched barrel-ROTATE idiom strings present in the RTL. Only
    the two unambiguous wrap signatures (see the rule comment); a logical-shift
    or zero-fill form matches NEITHER. Best-effort, zero-false-fire.

    §4.05 LFSR carve-out: a Galois LFSR's `{q[0], q[W-1:1]}` wrap is feedback, not a
    data rotate, when the assigned word is subsequently XOR-modified at tap bits
    (`_has_galois_tap_feedback`). Such a signature is excluded; a PURE rotate (no
    tap-XOR) still matches and still trips the rule (no leak)."""
    # COMMENTS ARE NOT RTL (folded in at merge). Every idiom below matches a
    # STRING, so a comment that DESCRIBES a wrap arms the detector as surely as
    # code that performs one. Measured across the corpus, 5 of 172 signatures
    # exist only inside a comment:
    #
    #   Prob094_gatesv / Prob092_gatesv100   // out_different[i] = in[i] ^ in[(i+1)%4]
    #   parallel2serial                      the concat idiom, in a comment
    #   ibex_alu.sv (x2)                     the OR-of-shifts idiom, in a comment
    #
    # The first two are this rule's new modulo form; the other three are the
    # pre-existing idioms, so the exposure is older than the form that surfaced
    # it. A design whose SPEC says shift and whose RTL merely COMMENTS a wrap
    # would be emit-blocked on the strength of prose — the failure this file
    # exists to prevent, arriving through its own input.
    #
    # Stripping leaves 167 of 172; the five that vanish are exactly the five
    # above.
    import re                      # this function already imports re locally,
                                   # which makes the name local for the whole body
    rtl_body = re.sub(r"/\*.*?\*/", " ", rtl_body, flags=re.S)
    rtl_body = re.sub(r"//[^\n]*", " ", rtl_body)

    import re
    out: List[str] = []
    # (1) OR of two OPPOSITE shifts of the SAME signal: (x<<n)|(x>>m) either order
    # Each operand is `( <ident> <shiftop> <expr> )` or bare `<ident> <shiftop> <expr>`.
    # The shift AMOUNT may itself be PARENTHESISED (`<< (8-shamt)`) and the form
    # may carry NO whitespace (`(din<<(8-shamt))`) — ORGANIC-20260618 round-4: the
    # old `[^()|;]+?` excluded parens, so a parenthesised amount silently dropped
    # the whole rotate signature (a functionally rotate-ONLY design then passed a
    # shifter spec). Allow ONE level of parens in the amount. zero-false-fire is
    # still guaranteed by the same-signal + opposite-direction check below.
    shift_operand = (r'\(?\s*([A-Za-z_]\w*)\s*(<<|>>)\s*'
                     r'(?:\([^()]*\)|[^()|^;])+?\)?')
    # The combiner is OR `|` or XOR `^` of the two opposite shifts: when the two
    # halves of a rotate are bit-disjoint (a+b == W) `^` is identically `|`, so
    # `(x<<a)^(x>>b)` is the same rotate as `(x<<a)|(x>>b)`. ORGANIC-20260618
    # round-5: the `|`-only combiner mislabeled the XOR form as a plain shift.
    # ADD `+` is deliberately NOT a combiner here — `(x<<a)+(x>>b)` can be real
    # arithmetic (e.g. 2.5*x), so recognising it risks a false-fire; the ADD-form
    # rotate is a documented honest UNDER-fire (fail-safe). zero-false-fire is
    # still guaranteed by the same-signal + opposite-direction check below.
    or_pat = re.compile(
        shift_operand + r'\s*[|^]\s*' + shift_operand)
    for m in or_pat.finditer(rtl_body):
        a_sig, a_op, b_sig, b_op = m.group(1), m.group(2), m.group(3), m.group(4)
        if a_sig == b_sig and a_op != b_op:   # same signal, OPPOSITE directions
            out.append(m.group(0).strip())
    # (2) concat wrapping the SAME vector with a GENUINE BIJECTIVE wrap, NO
    #     literal fill: {x[a:0], x[W-1:b]} (right rotate) / {x[W-2:0], x[W-1]}
    #     (left rotate). ORGANIC #790 §4.05 HARDENING of #784: a same-vector
    #     2-part concat is a rotate ONLY when the two bit-selects PARTITION x's
    #     index range — every index covered EXACTLY once (a bijection). A rotate
    #     of a W-bit word permutes all W bits with no loss; the partition test is
    #     exactly that. A sign-extending ARITHMETIC right shift `{x[MSB], x[MSB:1]}`
    #     DUPLICATES the MSB (it is in BOTH parts) and DROPS x[0] — NOT a partition
    #     → NOT a rotate (it is `$signed(x)>>>1`). A replicated sign-fill or a
    #     constant fill is also not a same-vector bijection. ZERO-FALSE-FIRE
    #     preserved: overlap, gap, or a literal operand → stay silent; a symbolic
    #     (non-literal) bit-select is not provably a partition → under-fire (safe).
    #     chip-AGNOSTIC: parameterised widths, any vector name.
    sel_pat = re.compile(
        r'^\s*([A-Za-z_]\w*)\s*\[\s*(\d+)\s*(?::\s*(\d+)\s*)?\]\s*$')

    def _sel_indices(operand: str, vec: str):
        sm = sel_pat.match(operand)
        if not sm or sm.group(1) != vec:
            return None
        hi = int(sm.group(2))
        lo = sm.group(3)
        if lo is None:                       # single bit  x[i]
            return {hi}
        lo = int(lo)
        a, b = (hi, lo) if hi >= lo else (lo, hi)
        return set(range(b, a + 1))          # inclusive range, either order

    concat_pat = re.compile(
        r'\{\s*([A-Za-z_]\w*\s*\[[^\[\]{}]*\])\s*,\s*'
        r'([A-Za-z_]\w*\s*\[[^\[\]{}]*\])\s*\}')
    for m in concat_pat.finditer(rtl_body):
        whole = m.group(0)
        # reject if a literal fill (1'b0 / 0 / 1'b1 / replication count) appears.
        if re.search(r"\b\d+'[bdh]|\{\s*\d", whole) or re.search(r"[,{]\s*\d", whole):
            continue
        op_a, op_b = m.group(1).strip(), m.group(2).strip()
        va, vb = sel_pat.match(op_a), sel_pat.match(op_b)
        if not va or not vb or va.group(1) != vb.group(1):
            continue                          # not two literal bit-selects of one vector
        idx_a = _sel_indices(op_a, va.group(1))
        idx_b = _sel_indices(op_b, vb.group(1))
        if idx_a is None or idx_b is None:
            continue
        if idx_a & idx_b:                     # overlap (e.g. arith MSB dup) → not a rotate
            continue
        union = idx_a | idx_b
        if union == set(range(0, max(union) + 1)):   # disjoint + gap-free [0..W-1]
            # §4.05 LFSR carve-out: skip if the assigned word is XOR-tap-modified
            # (Galois linear feedback, not a data rotate). A pure rotate has no
            # tap-XOR and is unaffected — it still trips the rule (no leak).
            lhs = _concat_assignment_lhs(rtl_body, m.start())
            if lhs and _has_galois_tap_feedback(rtl_body, lhs):
                continue
            out.append(whole.strip())
    # (3) a DOUBLED / REPLICATED same-vector fed into a SINGLE shift:
    #     {x, x} >> k   /   {N{x}} >> k   (N >= 2)   — the duplication supplies
    #     the wrap-around bits, so a single shift of the doubled vector is a
    #     ROTATE (right form keeps the low W bits, left form the high W bits).
    #     ORGANIC-20260618 round-4: this evaded (1) [no OR-of-opposite-shifts]
    #     and (2) [the concat is a DUPLICATION, not a fill-free PARTITION of x],
    #     so a {x,x}>>k rotate was mis-read as a plain shift. ZERO-FALSE-FIRE:
    #     requires the SAME vector duplicated (x,x or N{x}) AND a trailing shift;
    #     a {bit-select, literal} zero-fill or a {x,y} funnel will NOT match.
    #     chip-AGNOSTIC: any vector name / parameterised width.
    dbl_concat = re.compile(
        r'\{\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*\}\s*\)?\s*(?:>>|<<)')
    for m in dbl_concat.finditer(rtl_body):
        if m.group(1) == m.group(2):          # SAME vector doubled (not a funnel)
            out.append(m.group(0).strip())
    dbl_rep = re.compile(
        r'\{\s*(\d+)\s*\{\s*([A-Za-z_]\w*)\s*\}\s*\}\s*\)?\s*(?:>>|<<)')
    for m in dbl_rep.finditer(rtl_body):
        if int(m.group(1)) >= 2:              # {N{x}} with N>=2 is a duplication
            out.append(m.group(0).strip())
    # (4) a MODULO-ARITHMETIC WRAPPED bit index: x[(i +/- k) % W] or the
    #     power-of-two mask form x[(i +/- k) & (W-1)]. A barrel shifter built as a
    #     generate/for over per-bit muxes selects the source bit by index
    #     arithmetic; the `% W` (or `& (W-1)`) is what WRAPS the index around the
    #     word — the defining behaviour of a ROTATE. A logical shift never wraps
    #     the index: it uses a shift operator, a zero-fill concat, or a guarded
    #     `i+k < W ? x[i+k] : 1'b0`. So a bit-select whose index is reduced modulo
    #     (or masked to) the width is an unambiguous rotate wrap — the RTLLM
    #     barrel_shifter `in[(i+4)%8]` generate form, which idioms (1)-(3) [OR-of-
    #     opposite-shifts / concat partition / doubled-vector] all miss because it
    #     is neither a shift-operator OR nor a concat. ZERO-FALSE-FIRE: requires an
    #     OFFSET index `(<expr> +/- <expr>)` reduced by `% <int>` or `& (<int>-1)`
    #     — a bare `x[i]` or a zero-fill guard matches nothing. chip-AGNOSTIC: any
    #     vector name, any width literal.
    mod_idx = re.compile(
        r'[A-Za-z_]\w*\s*\[\s*\(\s*[^\[\]]*[+\-][^\[\]]*\)\s*'
        r'(?:%\s*\d+|&\s*\(?\s*\d+\s*-\s*1\s*\)?)\s*\]')
    for m in mod_idx.finditer(rtl_body):
        out.append(m.group(0).strip())
    return out


def _ternary_leaf_branches(expr: str) -> List[str]:
    """Split a top-level ternary `cond ? A : B` into its leaf branch exprs
    (recursively, right-associative). A non-ternary expr is its own only leaf.
    Paren/bracket/brace depth tracked so nested ?: and bit-selects don't fool
    the split."""
    def _find_top(e: str, ch_set, start: int = 0) -> int:
        depth = 0
        for i in range(start, len(e)):
            c = e[i]
            if c in '([{':
                depth += 1
            elif c in ')]}':
                depth -= 1
            elif depth == 0 and c in ch_set:
                return i
        return -1
    q = _find_top(expr, '?')
    if q < 0:
        return [expr.strip()]
    c = _find_top(expr, ':', q + 1)
    if c < 0:
        return [expr.strip()]
    return (_ternary_leaf_branches(expr[q + 1:c])
            + _ternary_leaf_branches(expr[c + 1:]))


def _rtl_dual_mode_shift_rotate(rtl_body: str, rotate_sigs: List[str],
                                out_names) -> bool:
    """True iff a MODULE OUTPUT is driven by a select (ternary / case) that
    genuinely muxes a plain-LOGICAL-SHIFT branch against a ROTATE branch.

    ORGANIC-20260618 round-2 §4.05 false-fire fix. A spec that OFFERS BOTH
    operations ("shift OR rotate", selected by a mode) is correctly implemented
    with BOTH a logical-shift branch AND a rotate branch, mux-selected; the
    rotate branch trips the rotate signature, so the re-armed gate must SKIP
    (fail-safe under-fire) on this dual-mode shape. Used ONLY on the disjunction
    re-arm path — a plain 'shifter' spec never reaches this guard, so the
    original #784/#790 gate behaviour is byte-for-byte preserved. (A leaf is
    'rotate' iff _rtl_rotate_signatures matches it — OR/XOR of opposite shifts,
    bijective same-vector concat, or doubled/replicated-vector shift; the rarer
    ADD-form rotate is a documented under-fire, see _rtl_rotate_signatures.)

    OUTPUT-AWARE NO-LAUNDER (§4.05, round-3): the decision looks ONLY at the
    expressions that drive the MODULE OUTPUT(s). A decoy mux on a dead/unused
    wire cannot launder a rotate-only output, because that wire is not an output
    driver. Branch exprs are FULLY (recursively) resolved through wire
    assignments before classification, so a split-wire rotate (`sh = (x<<n) |
    wrap; wrap = x>>(W-n)`) is correctly read as a rotate, not mis-labelled a
    plain shift.

    LIVE-MUX-ONLY NO-LAUNDER (§4.05, round-4): the shift and rotate leaves must
    be MUTUALLY-EXCLUSIVE LIVE branches of a genuine select — only three shapes
    qualify: (1) a TERNARY `cond ? A : B` driving the output (non-literal cond),
    (2) a CASE with a NON-CONSTANT selector whose items assign the output, (3) a
    simple `if(cond) out=..; else out=..;` (non-literal cond). A leaf is NEVER
    taken from a bare unconditional assignment, so a sequential dead-then-
    overwrite (`out=shift; out=rotate;` — last write wins, functionally
    rotate-ONLY) and a CONSTANT-selector case (`case(1'b1)`) cannot fake
    dual-mode; the gate fails SAFE (fires) on them. Any output-driver shape NOT
    in {ternary, non-const case, simple if/else} also fails safe to fire.
    dual-mode requires the output's OWN live-mux branches to contain BOTH a
    genuine shift AND a genuine rotate. chip-AGNOSTIC: any vector name /
    parameterised width.
    """
    import re
    out_names = set(out_names or ())
    if not rotate_sigs or not out_names:
        return False
    # resolution map: wire/reg/assign  name -> rhs expr (last assign wins for
    # continuous `assign`; first decl-init kept otherwise).
    assigns: dict = {}
    for am in re.finditer(r'\b(?:wire|reg|logic)\b[^=;]*?([A-Za-z_]\w*)\s*='
                          r'\s*([^;]+);', rtl_body):
        assigns.setdefault(am.group(1), am.group(2))
    for am in re.finditer(r'\bassign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);', rtl_body):
        assigns[am.group(1)] = am.group(2)

    def _resolve(expr: str, seen=None, depth: int = 0) -> str:
        """Recursively substitute resolvable wire names with their RHS so a
        split-wire rotate collapses to its inline form. Bounded + cycle-safe."""
        if depth > 12:
            return expr
        seen = seen or set()

        def _repl(m):
            nm = m.group(0)
            if nm in assigns and nm not in out_names and nm not in seen:
                return '(' + _resolve(assigns[nm], seen | {nm}, depth + 1) + ')'
            return nm
        return re.sub(r'\b[A-Za-z_]\w*\b', _repl, expr)

    def _class(expr: str):
        full = _resolve(expr.strip())
        if _rtl_rotate_signatures(full):
            return 'rotate'
        if re.search(r'<<|>>', full):
            return 'shift'
        return None

    def _is_literal_sel(sel: str) -> bool:
        """A constant case/ternary selector (`1'b1`, `2'd0`, `0`) — NOT a real
        runtime mux."""
        return re.fullmatch(r"\s*(?:\d+\s*'[bdhBDH][0-9a-fA-FxXzZ_]+|\d+)\s*",
                            sel or '') is not None

    # collect leaves ONLY from genuine mutually-exclusive LIVE mux structures.
    classes = set()
    for out in out_names:
        ow = re.escape(out)
        # FORM 1: a TERNARY (non-literal cond) drives the output — its leaves are
        # mutually exclusive. A bare non-ternary `out = expr;` yields ONE leaf →
        # never enough for dual-mode (kills the dead-overwrite launder).
        for dm in re.finditer(
                r'(?<![\w.])(?:assign\s+)?' + ow + r'\s*(?:<=|=)\s*([^;]+);',
                rtl_body):
            rhs = dm.group(1)
            leaves = _ternary_leaf_branches(rhs)
            if len(leaves) < 2:
                continue                          # not a ternary → not a mux
            qpos = rhs.find('?')
            if _is_literal_sel(rhs[:qpos]):
                continue                          # constant ternary selector
            for leaf in leaves:
                classes.add(_class(leaf))
        # FORM 3: a simple `if(cond) out=..; else out=..;` (non-literal cond)
        for im in re.finditer(
                r'\bif\s*\(\s*([^()]*?)\s*\)\s*(?:begin\b\s*)?(?<![\w.])' + ow +
                r'\s*(?:<=|=)\s*([^;]+);\s*(?:end\s*)?else\s*(?:begin\b\s*)?'
                r'(?<![\w.])' + ow + r'\s*(?:<=|=)\s*([^;]+);', rtl_body, re.S):
            if _is_literal_sel(im.group(1)):
                continue
            classes.add(_class(im.group(2)))
            classes.add(_class(im.group(3)))
    # FORM 2: a CASE with a NON-CONSTANT selector whose items assign the output.
    for cm in re.finditer(r'\bcase[zx]?\s*\(\s*([^()]*?)\s*\)(.*?)\bendcase',
                          rtl_body, re.S):
        sel, body = cm.group(1), cm.group(2)
        if _is_literal_sel(sel):
            continue                              # constant selector → not a mux
        for out in out_names:
            ow = re.escape(out)
            for im in re.finditer(
                    r'(?<![\w.])' + ow + r'\s*(?:<=|=)\s*([^;]+);', body):
                classes.add(_class(im.group(1)))
    return 'shift' in classes and 'rotate' in classes


# ---------------------------------------------------------------------------
# ERROR: a SYNCHRONOUS-reset FSM whose COMBINATIONAL next-state for the
# reset/initial state is REDUNDANTLY gated on the same reset signal
# (ORGANIC-20260618-sync-reset-next-state-redundant-gate) — lesson→program
# promotion from VerilogEval-Human Prob139_2013_q2bfsm.
#
# A synchronous-reset sequential block already forces  state <= <RESET_STATE>
# whenever <RESET> is asserted. If the COMBINATIONAL next-state logic ALSO
# conditions the transition OUT of <RESET_STATE> on the SAME <RESET> signal
# (`<RESET_STATE>: next = <RESET> ? <LAUNCH> : <RESET_STATE>;`  or
# `if(<RESET>) next = <RESET_STATE>`), the reset is double-counted: under a sync
# reset the FSM should leave the reset state on the first non-reset edge, but
# this keeps it in the reset state an extra/shifted cycle, corrupting the
# post-reset launch timing (Prob139: the f-pulse and g-window both slip).
#
# Conservative guards (chip-AGNOSTIC; the empirical false-positive surface over
# all 156 VerilogEval-Human golden references is EMPTY):
#   (a) ONLY a purely-SYNCHRONOUS reset signal qualifies — a signal used with an
#       asynchronous reset anywhere is skipped (async legitimately handles reset
#       in/around combinational logic, and reset-in-sensitivity is out of scope).
#   (b) the gated next-state arm must reference the SAME reset signal the
#       sequential block resets the state register with — a transition gated on
#       a DIFFERENT control (enable/start/etc.) is legitimate and never fires.
#   (c) the arm examined is the one for the RESET-VALUE state only — gating a
#       NON-reset state's transition on reset is a different (rarer) shape and
#       out of this structural rule's scope.
# ---------------------------------------------------------------------------
def _sync_reset_next_state_redundant_gate(rtl_body: str):
    """Return [(reset_sig, reset_state, arm_text), …] for each FSM whose
    synchronous-reset reset-state next-state arm is redundantly gated on the
    reset signal. chip-AGNOSTIC: purely structural."""
    import re as _re
    resets = classify_rtl_resets(rtl_body)
    sync_only = [r for r, rec in resets.items()
                 if 'synchronous' in rec['mode']
                 and 'asynchronous' not in rec['mode']]
    if not sync_only:
        return []
    _SEQ = _re.compile(r'\balways\s*@\s*\(\s*posedge\b', _re.I)
    _COMB = _re.compile(r'\balways(?:_comb\b|\s*@\s*\(\s*\*\s*\))', _re.I)

    def _blk(src, after):
        toks = list(_re.finditer(r'\b(begin|end)\b', src[after:]))
        depth = 0
        for t in toks:
            if t.group(1) == 'begin':
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return src[after:after + t.end()]
        semi = src.find(';', after)
        return src[after:semi + 1] if semi >= 0 else src[after:]

    def _comb_body(src, after):
        # Full body of an always block: a balanced begin/end, a complete
        # case…endcase (so a redundant arm in a NON-first position of a
        # begin/end-LESS `always @(*) case(…) endcase` is not truncated at the
        # first `;` — ORGANIC-20260618 round-3 §4.05 false-skip fix), else the
        # single trailing statement.
        m = _re.match(r'\s*', src[after:])
        pos = after + m.end()
        if _re.match(r'begin\b', src[pos:], _re.I):
            return _blk(src, pos)
        if _re.match(r'(?:unique\s+|priority\s+)?case[zx]?\b', src[pos:], _re.I):
            depth = 0
            for t in _re.finditer(r'\bcase[zx]?\b|\bendcase\b', src[pos:], _re.I):
                if t.group(0).lower().startswith('case'):
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        return src[pos:pos + t.end()]
            return src[pos:]
        semi = src.find(';', pos)
        return src[pos:semi + 1] if semi >= 0 else src[pos:]

    # a reset VALUE may be a named param OR a sized/plain numeric literal
    _RVAL = r"([A-Za-z_]\w*|\d+\s*'[sS]?[bdhoBDHO][0-9a-fA-FxXzZ_]+|\d+)"
    out = []
    for R in sync_only:
        rE = _re.escape(R)
        # collect EVERY FSM driven by this reset (a module may carry more than
        # one same-reset FSM; round-3 §4.05 false-skip fix — do not stop at the
        # first sequential block).
        fsms = []
        for sm in _SEQ.finditer(rtl_body):
            blk = _blk(rtl_body, sm.start())
            if not _re.search(r'\b' + rE + r'\b', blk):
                continue
            ra = _re.search(
                r'if\s*\(\s*[!~]?\s*' + rE + r'\b[^)]*\)\s*(?:begin)?\s*'
                r'(\w+)\s*<=\s*' + _RVAL, blk)
            if not ra:
                continue
            state_reg, reset_val = ra.group(1), ra.group(2)
            # The NEXT-STATE signal is the BARE-IDENTIFIER RHS of the OTHER
            # (non-reset) assignment to the state register in the same seq block
            # (`state <= next;`). Binding the redundancy check to THIS signal is
            # what makes the gate fire only on the real next-state datapath —
            # ORGANIC-20260618 round-2 §4.05: without it the gate false-fired on
            # an output-decode (`IDLE: out_valid = resetn;`) or an unrelated
            # `sel`-selected decoder (`RST_ST: dout = resetn ? din : RST_ST;`).
            # If the seq block computes the next state INLINE (`state<=state+1`),
            # there is no separate next-state reg → no redundant-comb pattern →
            # skip (fail-safe under-fire).
            # Scan the WHOLE body (not the begin/end-less seq block, which `_blk`
            # truncates at the first `;`) for the non-reset `state <= next;`.
            srE = _re.escape(state_reg)
            next_sig = None
            for nm in _re.finditer(srE + r'\s*<=\s*([A-Za-z_]\w*)\s*;', rtl_body):
                if nm.group(1) != reset_val:
                    next_sig = nm.group(1)
                    break
            if next_sig:
                fsms.append((state_reg, reset_val, next_sig))
        for state_reg, reset_val, next_sig in fsms:
            rvE = _re.escape(reset_val)
            nsE = _re.escape(next_sig)
            for cm in _COMB.finditer(rtl_body):
                body = _comb_body(rtl_body, cm.end())
                # only the comb block that actually DRIVES the next-state register
                if not _re.search(r'(?<![\w.])' + nsE + r'\s*=(?!=)', body):
                    continue
                # FORM A — the reset-VALUE state's case-arm gates the NEXT-STATE
                # register on the reset signal: `<reset_val> : [begin] next=…R…;`
                arm = _re.search(
                    r'\b' + rvE + r'\s*:\s*(?:begin\b\s*)?' + nsE +
                    r'\s*=\s*([^;]*\b' + rE + r'\b[^;]*);', body)
                # FORM B — a redundant `if(!R) next = <reset_val>` in the comb
                if not arm:
                    arm = _re.search(
                        r'if\s*\(\s*[!~]?\s*' + rE + r'\b[^)]*\)\s*'
                        r'(?:begin\b\s*)?' + nsE + r'\s*=\s*' + rvE +
                        r'\b[^;]*;', body)
                if arm:
                    out.append((R, reset_val, arm.group(0).strip()))
                    break
    return out


# ---------------------------------------------------------------------------
# ERROR: a triangle/ramp generator that DROPS the spec-required PEAK/TROUGH HOLD
# (same ORGANIC-20260617 program-first escalation). The lesson + anti-pattern
# block + §4-E reword all say "keep the peak-hold unless the spec EXPLICITLY
# forbids it", yet a fresh author drops it via §4-E. This mechanizes it.
#
# Spec half: describes a triangle / ramp / sawtooth waveform generator AND
# EXPLICITLY requires the extreme to be HELD ("hold the peak", "peak held for N
# cycles", "dwell at the top", "hold at the maximum"). §4.05 OVERRIDE — a spec
# that explicitly FORBIDS the hold ("no hold", "do not hold", "immediately
# reverse", "without dwell"), or a plain sawtooth / no-hold spec, must NOT
# fire. Both an explicit-forbid phrase AND the absence of an explicit-hold
# phrase disarm the rule.
#
# RTL half: an immediate direction REVERSAL at the extreme with NO hold/dwell
# state — the up/down direction register toggles the same cycle the value hits
# the peak/trough, and the design carries no `hold`/`dwell`/`pause` counter or
# flag. ZERO-FALSE-FIRE is binding: a design that HAS any hold/dwell/pause
# state never fires (we cannot prove the count without simulation, so any hold
# scaffolding is treated as compliant — under-firing is permitted).
# chip-AGNOSTIC: pure waveform vocabulary + structural direction-toggle shape.
# ---------------------------------------------------------------------------
_WAVEFORM_GEN_RE = __import__('re').compile(
    r'\b(?:triangle|triangular|ramp|saw[\s-]?tooth)\b'
    r'[^.!?]{0,40}?\b(?:wave(?:form)?|generat\w*|signal|counter|gen)\b'
    r'|\b(?:wave(?:form)?|generat\w*|signal)\b[^.!?]{0,40}?'
    r'\b(?:triangle|triangular|ramp|saw[\s-]?tooth)\b',
    __import__('re').IGNORECASE)
_HOLD_REQUIRE_RE = __import__('re').compile(
    r'\b(?:hold(?:s|ing)?|held|dwell(?:s|ing)?|pause(?:s|d)?|stay(?:s|ed)?|'
    r'remain(?:s|ed)?)\b[^.!?]{0,40}?'
    r'\b(?:peak|trough|maximum|minimum|max|min|top|bottom|extreme|apex)\b'
    r'|\b(?:peak|trough|maximum|minimum|max|min|top|bottom|extreme|apex)\b'
    r'[^.!?]{0,40}?\b(?:hold(?:s|ing)?|held|dwell(?:s|ing)?|pause(?:s|d)?|'
    r'stay(?:s|ed)?|remain(?:s|ed)?)\b',
    __import__('re').IGNORECASE)
# §4-E "explicit spec OVERRIDES genre convention": the peak/trough HOLD is a
# GENRE DEFAULT that fires only when the prose is silent (or merely
# consistent-with-hold, e.g. the FSM "increment; on reaching MAX transition to
# the decrement state" whose literal mutually-exclusive if/else naturally holds
# the extreme). An EXPLICIT plain-triangle / no-dwell spec must DISARM the
# convention. The explicit-forbid vocabulary is split into TWO strengths — this
# split is load-bearing (Step-2.7 §4.05 review, v1.3.43): a bare motion phrase
# ("advances every cycle", "then immediately reverse") is NOT strong enough to
# override an EXPLICIT hold-require, because it usually just describes the RAMP
# phase / a post-dwell reversal ("advances every clock cycle AND is held at the
# top for two cycles" is a HOLD spec, not a no-dwell one). Only a DIRECT no-hold
# statement overrides a hold-require.
#
# STRONG — a GENERIC/DIRECT no-hold statement that applies to the design's hold
# behaviour as a whole; overrides even an explicit hold-require (a direct
# contradiction the author resolved to no-hold):
#   (1) "no/without/never … hold/dwell/pause"
#   (4) "hold … forbidden/disallowed/prohibited"
# NB: the EXTREME-SPECIFIC one-cycle branches ("peak … one cycle wide/only",
# "peak … appears exactly one cycle") were MOVED to the WEAK tier (Step-2.7 §4.05
# MED review, v1.3.43): keyed on a SINGLE extreme, with STRONG "anywhere"
# precedence they let a no-dwell statement about the OPPOSITE extreme (e.g. "the
# trough appears for exactly one cycle") wrongly disarm a required PEAK hold on
# an ASYMMETRIC-dwell triangle. As WEAK they disarm only when NO hold-require is
# present, which stays correct for a genuine plain triangle.
_HOLD_FORBID_STRONG_RE = __import__('re').compile(
    r'\b(?:no|without|not|never|don.?t|do\s+not)\b[^.!?]{0,30}?'
    r'\b(?:hold(?:s|ing)?|dwell\w*|pause\w*)\b'
    r'|\b(?:hold(?:s|ing)?|dwell\w*|pause\w*)[^.!?]{0,20}?'
    r'\b(?:forbidden|disallowed|prohibited)\b',
    __import__('re').IGNORECASE)

# WEAK — no-dwell signals that describe MOTION or ONE extreme and can legitimately
# coexist with an explicit hold at the OTHER extreme / in a different phase, so
# they disarm the convention ONLY when NO sentence explicitly requires a hold:
#   (2) "immediately reverse/decrement/…"
#   (3) "advances/steps every cycle INCLUDING/EVEN/THROUGH/DURING the turn/peak"
#       (bare preposition "at" is intentionally NOT a connective — "held AT the
#        top" is a HOLD, not a no-dwell)
#   (D) "peak … one/single cycle WIDE/ONLY/LONG"        (extreme-specific)
#   (E) "peak … appears/stays/output EXACTLY/ONLY/JUST one/single cycle"
#       (bare "for one cycle" is DELIBERATELY excluded — ambiguous with a 1-cyc hold)
_HOLD_FORBID_WEAK_RE = __import__('re').compile(
    r'\bimmediately\b[^.!?]{0,15}?'
    r'\b(?:revers\w*|decrement\w*|increment\w*|turn\w*|chang\w*|switch\w*|drop\w*|step\w*)\b'
    r'|\b(?:advanc\w*|increment\w*|decrement\w*|step\w*|chang\w*|updat\w*|count\w*|move\w*)\w*\b'
    r'[^.!?]{0,30}?\bevery\b[^.!?]{0,15}?cycle[^.!?]{0,30}?'
    r'\b(?:includ\w*|even|through|during)\b[^.!?]{0,15}?'
    r'\b(?:turn|peak|revers\w*|extreme|maximum|minimum|top|bottom|apex|trough)\b'
    r'|\b(?:peak|trough|maximum|minimum|extreme|apex|top|bottom)\b[^.!?]{0,25}?'
    r'\b(?:one|single|1)\b[\s-]*cycle\b[^.!?]{0,15}?\b(?:wide|only|long)\b'
    r'|\b(?:peak|trough|maximum|minimum|extreme|apex|top|bottom)\b[^.!?]{0,30}?'
    r'\b(?:appear\w*|last\w*|present\w*|shown|output|stays?|remain\w*)\b[^.!?]{0,20}?'
    r'\b(?:exactly|only|just)\b[^.!?]{0,10}?\b(?:one|single|a\s+single)\b[\s-]*cycle\b',
    __import__('re').IGNORECASE)

# union — "is there ANY explicit no-hold signal" (kept for callers/tests that
# just want the predicate; the STRONG/WEAK precedence lives in the function).
_HOLD_FORBID_RE = __import__('re').compile(
    _HOLD_FORBID_STRONG_RE.pattern + "|" + _HOLD_FORBID_WEAK_RE.pattern,
    __import__('re').IGNORECASE)


def _spec_requires_peak_hold(spec_text: str) -> bool:
    """True iff the prose describes a triangle/ramp/sawtooth generator whose
    peak/trough must be HELD. §4-E precedence (v1.3.43, Step-2.7-hardened):
      1. a STRONG explicit no-hold statement overrides the convention outright;
      2. else an EXPLICIT hold-require (any sentence) fires the convention — a
         WEAK motion phrase does NOT disarm it (it usually just describes the
         ramp / a post-dwell reversal; disarming there re-opened the #776 leak);
      3. else a WEAK motion no-dwell phrase disarms (plain-triangle spec);
      4. else silent → the authoring default (peak-hold) still applies, but this
         GATE stays silent (returns False: it only ERRORs an EXPLICIT-require
         spec whose RTL drops the hold)."""
    from _specrtl_common import _soft_unwrap_sentences
    if not _WAVEFORM_GEN_RE.search(spec_text):
        return False
    if _HOLD_FORBID_STRONG_RE.search(spec_text):
        return False                          # §4.05: direct no-hold statement
    if any(_HOLD_REQUIRE_RE.search(s)
           for s in _soft_unwrap_sentences(spec_text)):
        return True                           # explicit hold-require is authoritative
    if _HOLD_FORBID_WEAK_RE.search(spec_text):
        return False                          # plain-triangle (no hold-require)
    return False


def _rtl_drops_peak_hold(rtl_body: str) -> Optional[str]:
    """Return the toggled direction signal when the RTL immediately reverses at
    the extreme with NO hold/dwell scaffolding, else None. Conservative: any
    hold/dwell/pause register or flag in the design disarms the check (we
    cannot count the hold without simulation). Looks for a direction/up-down
    register `dir <= ~dir` / `dir <= !dir` co-located with a peak/trough
    comparison, and the absence of a hold counter."""
    import re
    # disarm if any hold/dwell/pause state exists — cannot prove the count
    if re.search(r'\b\w*(?:hold|dwell|pause)\w*\b', rtl_body, re.IGNORECASE):
        return None
    # a direction toggle: `<sig> <= ~<sig>` / `<sig> <= !<sig>` / `<sig> <= <sig> ^ 1`
    toggles = set()
    for m in re.finditer(
            r'\b([A-Za-z_]\w*)\s*<=\s*(?:[!~]\s*\1\b|\1\s*\^\s*1\b)', rtl_body):
        toggles.add(m.group(1))
    if not toggles:
        return None
    # require a peak/trough comparison against an extreme in the same body
    # (==/>=/<= against a max/min literal or all-ones/zero pattern, or a named
    #  parameter that reads like a peak/max/min/top/bottom).
    has_extreme_cmp = bool(re.search(
        r'(?:==|>=|<=|>|<)\s*(?:'
        r"\{[^}]*1'b1[^}]*\}"                 # all-ones concat
        r"|\d+'[bdh][0-9a-fA-F_]+"            # sized literal
        r"|[A-Za-z_]\w*(?:MAX|MIN|PEAK|TOP|BOTTOM|HIGH|LOW|FULL|AMPL\w*)\b"
        r')', rtl_body, re.IGNORECASE))
    if not has_extreme_cmp:
        return None
    return sorted(toggles)[0]


# ---------------------------------------------------------------------------
# ERROR: the prose explicitly orders two FSM phases — assert an output for one
# cycle, THEN begin monitoring an input — while the output-owning state reads
# that later-phase input in its next-state arm.
#
# This is intentionally narrower than general temporal-language synthesis.  It
# fires only when all three independent anchors are present:
#   (a) prompt: an explicit one-cycle output assertion followed by THEN/AFTER and
#       an explicit monitor/sample/watch verb naming an input;
#   (b) RTL: a direct Moore decode `assign out = (state == PULSE_STATE)`;
#   (c) RTL: the case arm for that exact PULSE_STATE references the named input.
# Ambiguous prose, indirect output decode, multiple-state decode, and non-case
# FSM styles all SKIP.  This preserves the fail-closed/zero-false-positive
# contract while covering the recurring phase-collapse defect.
# ---------------------------------------------------------------------------
def _ordered_phase_monitoring_early(spec_text: str, rtl_body: str):
    """Return ``[(output, input, state, arm, cited_clause), ...]``.

    The implementation is chip/problem agnostic: only prompt grammar and RTL
    identifiers bind the three anchors; no benchmark or state-name literals are
    embedded.
    """
    import re as _re

    phase_re = _re.compile(
        r'\b(?:set|assert|drive|raise)\s+(?:the\s+)?(?:output\s+)?'
        r'(?P<out>[A-Za-z_]\w*)\s+(?:to\s+)?(?:1|high|asserted)\s+'
        r'for\s+(?:one|1|a\s+single)\s+(?:clock\s+)?cycle\b'
        r'\s*[.;,:-]?\s*'
        r'(?:then|after\s+(?:that|this|the\s+(?:pulse|one[- ]cycle)))\b'
        r'(?P<later>.{0,220}?)\b'
        r'(?:monitor|sample|observe|watch)\s+(?:the\s+)?'
        r'(?P<inp>[A-Za-z_]\w*)\s*(?:input|signal)?\b',
        _re.IGNORECASE | _re.DOTALL)

    out = []
    seen = set()
    for pm in phase_re.finditer(spec_text or ''):
        output, monitored = pm.group('out'), pm.group('inp')
        # Direct single-state Moore decode only.  Parentheses around the
        # equality are allowed, but extra boolean terms are deliberately not.
        oe, ie = _re.escape(output), r'([A-Za-z_]\w*)'
        decode_res = (
            _re.compile(r'\bassign\s+' + oe + r'\s*=\s*\(*\s*' + ie +
                        r'\s*==\s*([A-Za-z_]\w*)\s*\)*\s*;', _re.I),
            _re.compile(r'\bassign\s+' + oe + r'\s*=\s*\(*\s*'
                        r'([A-Za-z_]\w*)\s*==\s*' + ie +
                        r'\s*\)*\s*;', _re.I),
        )
        decodes = []
        for idx, dr in enumerate(decode_res):
            for dm in dr.finditer(rtl_body or ''):
                # normal: state_var == state_value; reversed: state_value == state_var
                state_var, owner = ((dm.group(1), dm.group(2)) if idx == 0
                                    else (dm.group(2), dm.group(1)))
                decodes.append((state_var, owner))

        for state_var, owner in decodes:
            for cm in _re.finditer(
                    r'\bcase[zx]?\s*\(\s*' + _re.escape(state_var) +
                    r'\s*\)(.*?)\bendcase\b', rtl_body or '',
                    _re.IGNORECASE | _re.DOTALL):
                arm_re = _re.compile(
                    r'^[ \t]*' + _re.escape(owner) + r'\s*:\s*(.*?)'
                    r'(?=^[ \t]*(?:[A-Za-z_]\w*|default)\s*:|\Z)',
                    _re.IGNORECASE | _re.MULTILINE | _re.DOTALL)
                am = arm_re.search(cm.group(1))
                if not am or not _re.search(
                        r'\b' + _re.escape(monitored) + r'\b', am.group(1)):
                    continue
                arm = ' '.join(am.group(1).split())[:240]
                clause = ' '.join(pm.group(0).split())[:360]
                key = (output.lower(), monitored.lower(), owner.lower())
                if key not in seen:
                    seen.add(key)
                    out.append((output, monitored, owner, arm, clause))
    return out


# ---------------------------------------------------------------------------
# FRAME CONTRACT (vibe-ic#2035 family F4) — mapping + temporal composition
#
# "Framed serial receiver forwards raw fields, adds latency or ignores
#  inter-frame space" packs THREE defects into one sentence, and this block
# keeps them apart because a single boolean is not a verdict a reader can act
# on:
#
#   1. MAPPING      the receiver hands on the raw field instead of applying the
#                   decode table the INPUT declares;
#   2. LATENCY      the output appears later than the contract states;
#   3. INTER-FRAME  the gap BETWEEN frames is part of the protocol and is not
#                   enforced, so back-to-back frames are accepted.
#
# (2) and (3) are two constraints on the SAME time axis, so a checker that only
# ever tests one of them at a time passes a design that violates their
# COMBINATION. They are therefore evaluated together and reported together in
# one `frame-contract-composition` line that names each element's state; each
# VIOLATED element additionally gets its own ERROR naming which half failed.
#
# The input side lives in `_frame_contract.py` (a shared library, so a table or
# counter emitter can consume the SAME typed contract this gate judges against).
# It never defaults a unit: a temporal claim needs a unit, a bound and an event
# pair, and any element the input does not structurally state is surfaced BY
# NAME as AI_REQUIRED instead of being completed with a guess.
#
# chip-AGNOSTIC: protocol English plus Verilog literal/assignment structure. No
# IC name, vendor, node, SKU or benchmark identifier.
# ---------------------------------------------------------------------------

_ASSIGN_STMT_RE = __import__('re').compile(
    r'\bassign\b\s+(?:#\s*\([^)]*\)\s*)?([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*='
    r'(?!=)([^;]*);')


def _rtl_regions(body: str):
    """Split the module body into (kind, text) regions.

    kind is 'seq' for an edge-sensitive always / always_ff and 'comb' for
    `always @(*)` / `always_comb`. A region runs to the next top-level always /
    assign / endmodule rather than a fixed character window, so a long clocked
    block is not silently truncated mid-way."""
    import re
    marks = []
    for m in re.finditer(r'\balways(?:_ff|_comb|_latch)?\b\s*(@\s*\(([^)]*)\))?',
                         body):
        sens = m.group(2) or ''
        kind = 'seq' if re.search(r'\b(?:pos|neg)edge\b', sens) else 'comb'
        if m.group(0).rstrip().endswith('always_ff'):
            kind = 'seq'
        marks.append((m.start(), m.end(), kind))
    for m in re.finditer(r'\bassign\b', body):
        marks.append((m.start(), m.start(), 'assign'))
    for m in re.finditer(r'\bendmodule\b', body):
        marks.append((m.start(), m.start(), 'end'))
    marks.sort()
    out = []
    for i, (st, en, kind) in enumerate(marks):
        if kind in ('assign', 'end'):
            continue
        stop = len(body)
        for st2, _, _ in marks[i + 1:]:
            if st2 > st:
                stop = st2
                break
        out.append((kind, body[en:stop]))
    return out


def _rtl_drivers(body: str):
    """name -> [(kind, rhs_text)] over the whole module.

    kind is 'seq' when the assignment is a nonblocking assignment inside an
    edge-sensitive block (one clock of latency) and 'comb' otherwise."""
    import re
    drivers = {}

    def add(nm, kind, rhs):
        drivers.setdefault(nm, []).append((kind, rhs.strip()))

    for m in _ASSIGN_STMT_RE.finditer(body):
        add(m.group(1), 'comb', m.group(2))
    for kind, text in _rtl_regions(body):
        if kind == 'seq':
            # A clocked assignment ARRIVES when its enable fires, not only when
            # its data changes, so the nearest enclosing `if (...)` / `case (...)`
            # condition is a real timing dependency and is recorded as one.
            # Without it a receiver that registers its output UNDER the
            # frame-done pulse shows no structural relation to that pulse at all,
            # and the whole latency question becomes undecidable exactly where it
            # matters. Clock/reset names are excluded: they gate every register.
            heads = [(m.start(), m.group(1))
                     for m in re.finditer(r'\b(?:if|case[zx]?)\s*\(([^;]*?)\)',
                                          text)]
            for m in re.finditer(
                    r'\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<=\s*'
                    r'(?:#\s*\d+\s*)?([^;]*);', text):
                add(m.group(1), 'seq', m.group(2))
                near = [h for h in heads if h[0] < m.start()]
                if near:
                    for ident in _rhs_idents(near[-1][1]):
                        if not _CLKRST_NAME.match(ident):
                            add(m.group(1), 'seq', ident)
        else:
            for m in re.finditer(
                    r'\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*=(?!=)([^;]*);',
                    text):
                add(m.group(1), 'comb', m.group(2))
    return drivers


_IDENT_ONLY_RE = __import__('re').compile(
    r'([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?')


def _rhs_idents(rhs: str):
    """Identifiers READ by an RHS expression, Verilog keywords removed."""
    import re
    kw = {'begin', 'end', 'if', 'else', 'case', 'endcase', 'default', 'posedge',
          'negedge', 'or', 'and', 'not', 'xor', 'nand', 'nor', 'xnor',
          'signed', 'unsigned'}
    return [t for t in re.findall(r"(?<![\w'])([A-Za-z_]\w*)", rhs)
            if t not in kw]


_LITERAL_ONLY_RE = __import__('re').compile(
    r"(?:\d+\s*)?'\s*[bBoOdDhH]\s*[0-9a-fA-FxXzZ_]+|0[xX][0-9a-fA-F_]+|\d+")


def _forward_source(rhs: str) -> Optional[str]:
    """The single signal `rhs` FORWARDS verbatim, or None if it computes.

    Three shapes forward a field unchanged and all three occur in real
    receivers, so all three are one hop:
      * a bare read, optionally bit-selected      `ftype` / `sh[2:0]`
      * a QUALIFIED read                          `done ? ftype : 4'h0`
      * a width-adjusting concat                  `{1'b0, ftype}`
    Reading only the first of them was measured to miss a genuine raw-field
    forward on this branch: the qualified form reported "computed, not
    forwarded" and the mapping rule went silent on a design that plainly
    forwarded the field. A shape with TWO identifiers is a computation and is
    not a hop."""
    import re
    rhs = rhs.strip()
    while rhs.startswith('(') and rhs.endswith(')'):
        rhs = rhs[1:-1].strip()
    m = _IDENT_ONLY_RE.fullmatch(rhs)
    if m:
        return m.group(1)
    tern = re.match(r'^[^?]*\?([^:]*):(.*)$', rhs)
    if tern:
        a, b = tern.group(1).strip(), tern.group(2).strip()
        for x, y in ((a, b), (b, a)):
            mx = _IDENT_ONLY_RE.fullmatch(x)
            if mx and _LITERAL_ONLY_RE.fullmatch(y):
                return mx.group(1)
        return None
    if rhs.startswith('{') and rhs.endswith('}'):
        parts = [q.strip() for q in rhs[1:-1].split(',')]
        idents = [q for q in parts if _IDENT_ONLY_RE.fullmatch(q)]
        lits = [q for q in parts if _LITERAL_ONLY_RE.fullmatch(q)]
        if len(idents) == 1 and len(idents) + len(lits) == len(parts):
            return _IDENT_ONLY_RE.fullmatch(idents[0]).group(1)
    return None


def _identity_forward_chain(drivers, dst: str, limit: int = 8):
    """[dst, a, b, ...] following SOLE drivers that FORWARD one signal.

    A chain of length >= 2 means `dst` carries another signal's bits VERBATIM —
    which is exactly "forwards the raw field" when the input declared a table."""
    chain = [dst]
    cur = dst
    for _ in range(limit):
        ds = drivers.get(cur, [])
        if len(ds) != 1:
            break
        nxt = _forward_source(ds[0][1])
        if not nxt or nxt in chain:
            break
        chain.append(nxt)
        cur = nxt
    return chain


def _assigned_inside_case(body: str, names) -> bool:
    """True if any of `names` is assigned inside a case/casez/casex statement —
    the canonical shape of an APPLIED lookup table."""
    import re
    want = set(names)
    for m in re.finditer(r'\bcase[zx]?\b\s*\(', body):
        end = body.find('endcase', m.end())
        seg = body[m.end():end if end != -1 else len(body)]
        for nm in re.findall(r'\b([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*<?=(?!=)',
                             seg):
            if nm in want:
                return True
    return False


def _rtl_contains_value(body: str, value: int) -> bool:
    """Does this RTL carry `value` as a numeric constant in ANY radix?

    Deliberately generous: a HIT only ever makes the caller STAY SILENT, so
    over-matching can suppress a finding but can never manufacture one.

    Bare decimals are matched against a body with every `[...]` removed: a
    `reg [3:0] q` declaration contains the digit 3 and would otherwise be read
    as evidence that the constant 3 is used as a VALUE. A sized literal
    (`4'h3`) and a C hex are unambiguous and are matched anywhere."""
    import re
    try:
        from _frame_contract import literal_forms
    except ImportError:
        return True                      # cannot tell -> never accuse
    debracketed = re.sub(r'\[[^\]]*\]', ' ', body)
    for form in literal_forms(value):
        if form.startswith("'"):
            if re.search(r"'\s*" + re.escape(form[1]) + r"\s*0*"
                         + re.escape(form[2:]) + r"\b", body, re.IGNORECASE):
                return True
        elif form.startswith('0x'):
            if re.search(re.escape(form) + r'\b', body, re.IGNORECASE):
                return True
        else:
            if re.search(r'(?<![\w.\'])' + re.escape(form) + r'(?![\w.])',
                         debracketed):
                return True
    return False


def _clocked_hop_depths(drivers, src: str, dst: str, limit: int = 12):
    """The SET of clocked-hop counts on every simple path src -> ... -> dst.

    A single-element set is an unambiguous latency in clock cycles. An empty set
    means `dst` does not structurally depend on `src` at all; more than one
    element means the design offers several depths and the relative timing is
    NOT decidable from structure — both are reported as such, never rounded to a
    number."""
    # `frame_done` is frequently a comb alias of an internal `done_q`, and the
    # data path names the internal one. Reaching any COMBINATIONAL alias of the
    # event is reaching the event; a SEQUENTIAL alias is NOT one, because it sits
    # a cycle away and folding it in would understate the measured latency.
    aliases = {src}
    cur = src
    for _ in range(8):
        ds = drivers.get(cur, [])
        if len(ds) != 1 or ds[0][0] != 'comb':
            break
        m = _IDENT_ONLY_RE.fullmatch(ds[0][1].strip())
        if not m or m.group(1) in aliases:
            break
        cur = m.group(1)
        aliases.add(cur)

    seen_states = {}

    def walk(node, path):
        if node in aliases:
            return {0}
        if node in path or len(path) > limit:
            return set()
        key = (node, frozenset(path))
        if key in seen_states:
            return seen_states[key]
        acc = set()
        for kind, rhs in drivers.get(node, []):
            add = 1 if kind == 'seq' else 0
            for ident in _rhs_idents(rhs):
                for d in walk(ident, path | {node}):
                    acc.add(d + add)
        seen_states[key] = acc
        return acc

    return walk(dst, frozenset())


_GAP_NAME_RE = __import__('re').compile(
    r'\b\w*(?:gap|idle|ifg|inter_?frame|dwell|guard|quiet|space)\w*\b',
    __import__('re').IGNORECASE)


def _rtl_interframe_evidence(body: str, value: int):
    """Evidence that this RTL enforces an inter-frame gap of `value`, or None.

    Two independent forms count, because legitimate architectures spell the same
    rule differently: a gap/idle/quiet/guard-named parameter, state or register;
    or the bound (or its off-by-one terminal-count neighbours) used as an operand
    of a COMPARISON, which is how a dwell is actually enforced.

    "the constant appears ANYWHERE" was the first version of the second leg and
    it was measured wrong on this branch: a decode table containing `4'h3`
    silently supplied evidence for a stated gap of 3 and the rule went quiet on
    a receiver with no inter-frame logic at all. A constant is evidence of a
    DURATION only where it is compared against."""
    import re
    m = _GAP_NAME_RE.search(body)
    if m:
        return f"gap/idle-named identifier '{m.group(0)}'"
    try:
        from _frame_contract import literal_forms
    except ImportError:
        return "constant scan unavailable"          # cannot tell -> never accuse
    ops = r'(?:==|!=|>=|<=|>|<)'
    for v in (value, value - 1, value + 1):
        if v < 2:
            continue
        for form in literal_forms(v):
            lit = (r"\d*'\s*" + re.escape(form[1]) + r"\s*0*" + re.escape(form[2:])
                   if form.startswith("'")
                   else re.escape(form))
            if re.search(ops + r'\s*' + lit + r'\b', body, re.IGNORECASE) or \
               re.search(lit + r'\s*' + ops, body, re.IGNORECASE):
                return (f"constant {v} compared against (the stated bound or its "
                        f"terminal-count neighbour)")
    return None


def _frame_contract_findings(input_prose: str, rtl_body: str,
                             rtl_ports: List[Port], path: str,
                             rtl_name: str) -> List['Finding']:
    """Judge the whole frame contract at once and report it COMPOSED.

    Returns one ERROR per VIOLATED element (so a reader is told WHICH of the
    three failed, and both are named when two fail together) plus a single
    `frame-contract-composition` INFO carrying the joint verdict."""
    try:
        import _frame_contract as _fc
    except ImportError:                       # noqa: BLE001 — library absent
        return []
    if not input_prose or not rtl_body:
        return []
    ins = [p.name for p in rtl_ports if p.direction == 'input']
    outs = [p.name for p in rtl_ports if p.direction in ('output', 'inout')]
    internals = sorted(set(__import__('re').findall(
        r'\b(?:reg|wire|logic)\b(?:\s*\[[^\]]*\])?\s+([A-Za-z_]\w*)',
        rtl_body)))
    contract = _fc.extract_frame_contract(input_prose, ins, outs, internals)
    if not contract.any_stated():
        return []

    drivers = _rtl_drivers(rtl_body)
    f: List[Finding] = []
    states = {}
    details = {}

    # ---- 1. MAPPING: is the declared decode table APPLIED, or forwarded raw?
    fm = contract.mapping
    if fm is not None:
        if fm.missing:
            states['mapping'] = _fc.AI_REQUIRED
            details['mapping'] = ("declared table not machine-checkable — "
                                  + "; ".join(fm.missing))
        else:
            chain = _identity_forward_chain(drivers, fm.dst)
            vals = fm.evidencable_outputs
            present = [v for v in vals if _rtl_contains_value(rtl_body, v)]
            has_case = _assigned_inside_case(rtl_body, chain)
            if len(chain) < 2:
                states['mapping'] = _fc.SATISFIED
                details['mapping'] = (
                    f"'{fm.dst}' is computed, not forwarded")
            elif present or has_case:
                _how = ('case/casez lookup' if has_case
                        else 'mapped values '
                             + ', '.join(str(v) for v in present))
                states['mapping'] = _fc.SATISFIED
                details['mapping'] = (
                    f"table evidence present in the RTL ({_how})")
            else:
                states['mapping'] = _fc.VIOLATED
                details['mapping'] = (
                    f"'{fm.dst}' forwards '{chain[-1]}' verbatim")
                f.append(Finding(path, 'ERROR', 'frame-field-mapping-not-applied',
                    fm.dst,
                    f"the input declares a {len(fm.entries)}-entry decode table "
                    f"for '{fm.dst}'"
                    + (f" from '{fm.src}'" if fm.src else "")
                    + f", but the RTL drives '{fm.dst}' by forwarding "
                    f"'{chain[-1]}' verbatim ({' <- '.join(chain)}) and carries "
                    f"none of the mapped output values "
                    f"({', '.join(str(v) for v in vals)}) anywhere in the "
                    f"module. The receiver hands on the RAW FIELD; apply the "
                    f"declared table (a case/casez over the field, or a "
                    f"constant lookup array) before driving '{fm.dst}'."))
    else:
        states['mapping'] = _fc.NOT_STATED

    # ---- 2. LATENCY: does the output arrive LATER than the contract states?
    tb = contract.latency
    if tb is not None:
        if tb.missing:
            states['latency'] = _fc.AI_REQUIRED
            details['latency'] = ("temporal bound incomplete — "
                                  + "; ".join(tb.missing)
                                  + " [route to AI: do NOT default it]")
        elif not tb.comparable_to_cycles:
            states['latency'] = _fc.AI_REQUIRED
            details['latency'] = (
                f"stated in {tb.unit}s, and the input does not state the "
                f"oversampling ratio, so it cannot be compared against a "
                f"register-stage count [route to AI]")
        else:
            depths = _clocked_hop_depths(drivers, tb.event_from, tb.event_to)
            if not depths:
                states['latency'] = _fc.AI_REQUIRED
                details['latency'] = (
                    f"no structural path '{tb.event_from}' -> '{tb.event_to}' "
                    f"in the RTL, so their relative timing is not decidable "
                    f"from structure [route to AI]")
            elif len(depths) > 1:
                states['latency'] = _fc.AI_REQUIRED
                details['latency'] = (
                    f"the RTL offers several depths {sorted(depths)} from "
                    f"'{tb.event_from}' to '{tb.event_to}'; not decidable "
                    f"from structure [route to AI]")
            else:
                d = next(iter(depths))
                over = (d > tb.value) if tb.bound in ('exactly', 'at_most') \
                    else False
                under = (d < tb.value) if tb.bound in ('exactly', 'at_least') \
                    else False
                if over:
                    states['latency'] = _fc.VIOLATED
                    details['latency'] = (
                        f"{d} cycle(s) measured vs {tb.bound} {tb.value}")
                    f.append(Finding(path, 'ERROR',
                        'frame-output-latency-added', tb.event_to,
                        f"the input states '{tb.event_to}' is valid "
                        f"{tb.bound.replace('_', ' ')} {tb.value} clock "
                        f"cycle(s) after '{tb.event_from}', but the RTL's "
                        f"clocked-assignment path '{tb.event_from}' -> "
                        f"'{tb.event_to}' carries {d} register stage(s) — the "
                        f"receiver ADDS {d - tb.value} cycle(s) of latency. "
                        f"Drive '{tb.event_to}' from the same stage that "
                        f"produces '{tb.event_from}' instead of registering it "
                        f"again. Input clause: \"{tb.raw.strip()}\""))
                elif under:
                    states['latency'] = _fc.VIOLATED
                    details['latency'] = (
                        f"{d} cycle(s) measured vs {tb.bound} {tb.value}")
                    f.append(Finding(path, 'INFO',
                        'frame-output-latency-short', tb.event_to,
                        f"the input states '{tb.event_to}' is valid "
                        f"{tb.bound.replace('_', ' ')} {tb.value} clock "
                        f"cycle(s) after '{tb.event_from}'; the RTL path "
                        f"carries only {d}. Advisory: too EARLY is a different "
                        f"defect from the one this rule owns."))
                else:
                    states['latency'] = _fc.SATISFIED
                    details['latency'] = (
                        f"{d} cycle(s) measured, contract {tb.bound} "
                        f"{tb.value}")
    else:
        states['latency'] = _fc.NOT_STATED

    # ---- 3. INTER-FRAME SPACE: is the gap between frames enforced at all?
    ib = contract.interframe
    if ib is not None:
        if ib.missing:
            states['interframe'] = _fc.AI_REQUIRED
            details['interframe'] = ("inter-frame bound incomplete — "
                                     + "; ".join(ib.missing)
                                     + " [route to AI: do NOT default it]")
        elif ib.value < 2:
            states['interframe'] = _fc.AI_REQUIRED
            details['interframe'] = (
                f"a stated gap of {ib.value} cannot be evidenced in source: "
                f"0 and 1 occur in every module [route to AI]")
        else:
            ev = _rtl_interframe_evidence(rtl_body, ib.value)
            if ev:
                states['interframe'] = _fc.SATISFIED
                details['interframe'] = f"enforcement evidence: {ev}"
            else:
                states['interframe'] = _fc.VIOLATED
                details['interframe'] = "no gap enforcement found"
                f.append(Finding(path, 'ERROR',
                    'frame-interframe-space-unenforced',
                    rtl_name or '<module>',
                    f"the input requires consecutive frames to be separated by "
                    f"{ib.bound.replace('_', ' ')} {ib.value} {ib.unit}(s), but "
                    f"the RTL carries NO inter-frame enforcement: no gap/idle/"
                    f"guard-named parameter, state or register, and none of the "
                    f"constants {ib.value - 1}/{ib.value}/{ib.value + 1} appears "
                    f"anywhere in the module. Back-to-back frames the input "
                    f"forbids are therefore accepted. The gap is part of the "
                    f"protocol, not of the testbench. Input clause: "
                    f"\"{ib.raw.strip()}\""))
    else:
        states['interframe'] = _fc.NOT_STATED

    f.append(Finding(path, 'INFO', 'frame-contract-composition',
                     rtl_name or '<module>',
                     _fc.FrameContract.composition_line(states, details)))
    return f


def check(spec: SpecContract, rtl_name: str, rtl_ports: List[Port],
          rtl_resets: dict, rtl_registered: Optional[bool],
          path: str, rtl_body: str = '', spec_text: str = '',
          renamed_groups: Optional[List[tuple]] = None,
          input_prose: str = '') -> List[Finding]:
    f: List[Finding] = []

    # ---- structural sanity: zero output-capable ports -----------------------
    # (ORGANIC-20260605-zero-output-module-not-emit-blocking) A module whose
    # every port parsed as input is a deterministic signature of a mis-read
    # interface (e.g. a prompt port-direction typo turned a storage element's
    # state pin into an input): no spec-to-RTL design is a pure sink — a module
    # with no output/inout ports cannot be observed by ANY testbench. This
    # fires on RTL structure alone, so a spec that repeats the typo cannot
    # mask it (the port-fidelity rules stay silent in exactly that case).
    # chip-AGNOSTIC: pure port-direction structure; no name/class literals.
    if rtl_ports and not any(p.direction in ('output', 'inout')
                             for p in rtl_ports):
        f.append(Finding(path, 'ERROR', 'zero-output-ports',
            rtl_name or '<module>',
            f"module '{rtl_name}' declares {len(rtl_ports)} port(s) but ZERO "
            "output/inout ports — a sink module no testbench can observe. "
            "Re-read the interface: a bullet-listed pin direction may be a "
            "prompt typo (the hidden testbench is the port-direction "
            "authority); flip the mis-read pin to an output."))

    # ---- the port comparison's own DENOMINATOR -----------------------------
    # (#2049 item 4) A zero denominator is NOT_MEASURED, never PASS. This is the
    # house rule of `gate_zero_denominator_refuses_check` (#564): "an empty scan
    # is not a result at all". Measured on this base: driven with an L9 whose
    # `ports` is empty, this program printed
    #     spec_conformance_check: PASS — findings: 0 (0 error, 0 warn, 0 info)
    #     [spec ports=0(json), rtl ports=5, spec reset=-/-]
    # and returned rc 0. Every port rule below had compared the RTL against an
    # empty interface. The zero WAS disclosed — `spec ports=0` — but in a shape
    # the house prober cannot read: its predicate wants `0 ports read`, and
    # `ports=0` matches nothing. So the disclosure existed and no instrument in
    # the repo could see it, and neither could a reader who reads the verdict
    # word. This says it in words, in both output channels.
    #
    # INFO, never ERROR, and that is deliberate: 110 of the 142 JSON contracts
    # carrying a `ports` key in the corpus on this base carry it EMPTY. A
    # port-less spec snippet is a legitimate input and must not be blocked. What
    # is NOT legitimate is calling the resulting silence conformance.
    if not spec.ports:
        f.append(Finding(path, 'INFO', 'spec-port-comparison-not-measured',
            rtl_name or '<module>',
            "port conformance: 0 port(s) read from the spec contract — "
            "NOT_MEASURED, not PASS. "
            f"The RTL declares {len(rtl_ports)} port(s) and the spec contract "
            "declares none, so every port rule below (name, direction, width, "
            "reset polarity) compared this RTL against an empty interface and "
            "could not have found anything. A clean verdict here states nothing "
            "about the interface."))

    # ---- structural sanity: a verdict over an EMPTY spec interface ----------
    # (#2049 item 4; czl9docs O5) "0 spec ports" has two causes and only one of
    # them is legitimate, exactly as `phase1_sufficiency_check` distinguishes
    # them one layer earlier:
    #   * the spec text declares no interface  -> a reset/latency-only snippet.
    #     Legitimate; port conformance stays silent, as it always has.
    #   * the spec text DOES declare an interface and the contract carries none
    #     -> an EXTRACTION GAP. Every port rule below then compares the RTL
    #     against nothing and this gate reports PASS with 0 findings — a verdict
    #     over an empty population.
    # The protection against the second case is currently the Phase-1 HALT, not
    # this step, so the clause stays reachable BY HAND (a hand-run of this
    # program over a blind L9) and by any caller that reaches step 2 without the
    # Phase-1 gate. This makes the step refuse it on its own evidence.
    #
    # The two causes are told apart by RE-READING THE SPEC TEXT with the SAME
    # grammars Phase 1 uses, so this cannot disagree with Phase 1 about what the
    # document declares. chip-AGNOSTIC: pure structural extraction, no
    # design/class literal.
    #
    # ONLY THE HIGH-CONFIDENCE TIERS OF THAT RE-READ ARM THIS RULE, and that
    # narrowing is measured, not assumed. `phase1_port_extract.extract_ports`
    # has two tiers: a markdown interface TABLE plus ports parsed out of real
    # Verilog regions (high confidence), and — reached only when those come back
    # empty — a PROSE fallback that reads heading-anchored and direction-keyword
    # bullets. Swept over 9064 documents on this base (benchmark-data +
    # benchmark_external, oracle/golden/solution paths excluded), the whole
    # re-read fires on 82 documents, of which 74 are PROSE-tier and 8 are
    # high-tier. EVERY ONE of the 16 fires on a genuine INPUT document is
    # PROSE-tier, and they are phantoms: a FlexRay state name (`DEFAULT_CONFIG`),
    # a SAS primitive (`ALIGN`, `HARD_RESET`), and two of a protocol narrative's
    # twenty-odd signals (`ACLK`, `ARESETn`) — narrative prose, not a module
    # interface. Firing an EMIT-BLOCKING ERROR on those would block legitimate
    # designs, so the prose tier is refused here. The high tier is principled as
    # well as clean: `extract_spec_contract` has those SAME two tiers, so a
    # high-tier disagreement means the two extractors read the same kind of
    # structured evidence and disagreed — which is an extraction gap by
    # construction. A prose-only hit means only the looser grammar saw anything.
    #
    # MEASURED COST, recorded rather than hidden: one real gap in that corpus
    # (a prompt declaring its pins as `- **`clk`** (1-bit): ...` bullets under an
    # `#### Inputs:` heading) is a PROSE-tier hit and is therefore NOT flagged
    # here. It is not flagged because the identical grammar produced
    # `DEFAULT_CONFIG` and `ALIGN` as ports on other inputs; a rule that cannot
    # tell those apart is a style rule, not a conformance check.
    if not spec.ports and (spec_text or input_prose):
        _spec_txt = spec_text or input_prose
        _declared = None
        try:
            import phase1_port_extract as _ppe
            from _specrtl_common import (_parse_md_table_ports as _mdt,
                                         parse_verilog_ports as _pvp)
            # The high-confidence tiers, in the same order and with the same
            # dedup `extract_ports` itself uses — reached through that module's
            # own helpers so the two cannot drift apart in what they accept as a
            # declaration (the same reason this file reuses
            # `l9_rtl_pin_consistency_check`'s manifest parser below).
            _tbl, _ = _mdt(_spec_txt, union=True)
            _inl = _pvp(_ppe._verilog_regions(_spec_txt))
            _declared = _ppe._dedup_ports(list(_tbl) + list(_inl))
        except Exception:  # noqa: BLE001 — degrade LOUDLY, never silently
            _declared = None
            print("spec_conformance_check: WARN could not re-read the spec "
                  "interface (phase1_port_extract unavailable) — the empty-"
                  "interface check is NOT_MEASURED for this file",
                  file=sys.stderr)
        if _declared:
            _names = sorted({(p.get("name") if isinstance(p, dict) else p)
                             for p in _declared})
            f.append(Finding(path, 'ERROR', 'spec-interface-empty-but-declared',
                rtl_name or '<module>',
                f"the spec contract carries ZERO ports, but the spec text "
                f"declares {len(_names)} in a structured interface "
                f"({', '.join(_names)}) — an extraction gap, not a port-less "
                "specification. Every port rule below compares this RTL against "
                "an empty interface, so a PASS here measures nothing. Fix the "
                "Phase-1 extraction (L9 interface) and re-run; do not read this "
                "verdict as conformance."))

    # ---- port conformance --------------------------------------------------
    # Only when the spec actually declares an interface — a reset/latency-only
    # spec snippet (0 ports) must not flag every RTL port as "extra".
    rmap = {p.name: p for p in rtl_ports}
    smap = {p.name: p for p in spec.ports} if spec.ports else {}

    # ---- ORGANIC — declared interface RENAME (SOURCE_MANIFEST #711) --------
    # The flow already HAS a way for a design to declare that an L9 illustrative
    # interface is delivered under different RTL name(s):
    # `phase2/stage1/rtl/SOURCE_MANIFEST.json -> renamed_interfaces`, documented
    # in `catalog-glue-author/SKILL.md` and parsed by
    # `l9_rtl_pin_consistency_check._manifest_renamed_groups()`. Nothing in the
    # 44-step flow consumed it, so an author who declared a rename (as the skill
    # instructs) still hard-ERRORed here with port-missing + port-extra. A
    # declaration mechanism with no consumer invites the right behaviour and
    # then punishes it. This is the SAME reconciliation this gate already
    # performs for the L9 `optional` flag above.
    #
    # ACCEPTED, never SUPPRESSED. A group reconciles ONLY when every name on
    # both sides is real and the electrical facts match:
    #   * every `l9` name is a SPEC port that is genuinely absent from the RTL;
    #   * every `rtl` name is an RTL port genuinely absent from the spec;
    #   * every RTL name carries the SAME direction as the L9 port(s) it serves,
    #     and the same width when both are literal.
    # Any other shape is reported as a defect IN THE DECLARATION and the
    # underlying port findings are still emitted, so the manifest can never be
    # used to wave an arbitrary mismatch through. An UNDECLARED missing/extra
    # port is untouched by all of this.
    # chip-AGNOSTIC: manifest grammar only, no chip/vendor/PDK literal.
    renamed_ok_spec: set = set()
    renamed_ok_rtl: set = set()
    for l9_set, rtl_set in (renamed_groups or []):
        if not l9_set or not rtl_set:
            continue
        bad = False
        for nm in sorted(l9_set):
            if nm not in smap:
                f.append(Finding(path, 'ERROR', 'port-rename-undeclared-spec-port', nm,
                    f"SOURCE_MANIFEST declares a rename FROM '{nm}', but the spec "
                    f"has no such port — a rename can only reconcile a port the "
                    f"spec actually declares."))
                bad = True
            elif nm in rmap:
                f.append(Finding(path, 'ERROR', 'port-rename-source-still-present', nm,
                    f"SOURCE_MANIFEST declares '{nm}' renamed, but the RTL still "
                    f"declares a port of that name — the declaration and the RTL "
                    f"disagree."))
                bad = True
        for nm in sorted(rtl_set):
            if nm not in rmap:
                f.append(Finding(path, 'ERROR', 'port-rename-missing-rtl-port', nm,
                    f"SOURCE_MANIFEST declares a rename TO '{nm}', but the RTL "
                    f"has no such port."))
                bad = True
            elif nm in smap:
                f.append(Finding(path, 'ERROR', 'port-rename-target-in-spec', nm,
                    f"SOURCE_MANIFEST declares '{nm}' as a rename TARGET, but the "
                    f"spec declares a port of that name — that is not a rename."))
                bad = True
        if bad:
            continue
        # electrical facts must survive the rename
        for rn in sorted(rtl_set):
            rp = rmap[rn]
            for sn in sorted(l9_set):
                sp = smap[sn]
                if rp.direction != sp.direction:
                    f.append(Finding(path, 'ERROR', 'port-rename-direction-mismatch', rn,
                        f"renamed port '{rn}' direction RTL={rp.direction} vs spec "
                        f"'{sn}'={sp.direction} — a rename may not change direction."))
                    bad = True
                if (rp.width != WIDTH_UNKNOWN and sp.width != WIDTH_UNKNOWN
                        and rp.width != sp.width):
                    f.append(Finding(path, 'ERROR', 'port-rename-width-mismatch', rn,
                        f"renamed port '{rn}' width RTL={rp.width} vs spec "
                        f"'{sn}'={sp.width} — a rename may not change width."))
                    bad = True
        if bad:
            continue
        renamed_ok_spec |= l9_set
        renamed_ok_rtl |= rtl_set
        f.append(Finding(path, 'INFO', 'port-renamed-by-manifest',
            ','.join(sorted(l9_set)),
            f"spec port(s) {sorted(l9_set)} are delivered as RTL port(s) "
            f"{sorted(rtl_set)}, declared in SOURCE_MANIFEST.renamed_interfaces "
            f"with matching direction and width — an accepted declared rename."))

    for nm, sp in smap.items():
        if nm in renamed_ok_spec:
            continue
        if nm not in rmap:
            # A pin the INPUT marks optional may be left out: not implementing an
            # offered pin is a declared design choice, not a conformance defect.
            # l9_rtl_pin_consistency_check already reads this same L9 flag and
            # reports it advisory; this gate hard-ERRORed on it, so the two gates
            # returned contradictory verdicts from the identical evidence.
            if getattr(sp, 'optional', False):
                f.append(Finding(path, 'INFO', 'port-optional-not-implemented', nm,
                    f"spec port '{nm}' ({sp.direction}[{sp.width}]) is marked "
                    f"optional by the input and is not implemented — a declared "
                    f"design choice, not a conformance defect."))
                continue
            f.append(Finding(path, 'ERROR', 'port-missing', nm,
                f"spec port '{nm}' ({sp.direction}[{sp.width}]) is not in the RTL."))
            continue
        rp = rmap[nm]
        if rp.direction != sp.direction:
            f.append(Finding(path, 'ERROR', 'port-direction-mismatch', nm,
                f"port '{nm}' direction RTL={rp.direction} vs spec={sp.direction}."))
        # Skip the width assertion when EITHER side is WIDTH_UNKNOWN (a
        # parameterized / symbolic bound that could not be resolved to a
        # literal). Asserting equality against an unknown fabricates a false
        # mismatch (the parameterized-width defect). Only compare two KNOWN
        # literal widths.
        if (rp.width != WIDTH_UNKNOWN and sp.width != WIDTH_UNKNOWN
                and rp.width != sp.width):
            f.append(Finding(path, 'ERROR', 'port-width-mismatch', nm,
                f"port '{nm}' width RTL={rp.width} vs spec={sp.width}."))
    if smap:
        for nm in rmap:
            if nm in renamed_ok_rtl:
                continue
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

    # ---- MSB-first serial-load direction (ERROR; lesson→program promotion) --
    # Spec says the serial data arrives MSB-first but the RTL inserts the new
    # bit at the MSB end of a parallel-consumed register — the assembled word
    # is bit-reversed. See the rule comment above _spec_declares_msbfirst_serial.
    if spec_text and rtl_body and _spec_declares_msbfirst_serial(spec_text):
        for vec, bit_src in _msb_entry_serial_loads(rtl_body, rtl_ports):
            f.append(Finding(path, 'ERROR', 'msbfirst-direction-mismatch', vec,
                f"spec says the serial data loads MSB-first, but the RTL "
                f"inserts the new bit '{bit_src}' at the MSB end of '{vec}' "
                f"({vec} <= {{{bit_src}, {vec}[W-1:1]}}) — after W cycles the "
                f"FIRST-received bit sits at the LSB: the word is bit-REVERSED. "
                f"Under MSB-first reception the first bit must END at the MSB; "
                f"use the left-shift idiom {vec} <= {{{vec}[W-2:0], {bit_src}}}."))

    # ---- reset-tied window AND-ed with !reset (ERROR; lesson→program) ------
    # Spec ties the N-cycle assertion window to reset ITSELF; the RTL gates
    # the named output off while reset is high — a held/re-asserted reset
    # eats assertion cycles. See _spec_reset_tied_assert_signals rule comment.
    if spec_text and rtl_body and spec.reset_mode != 'asynchronous':
        outs = {p.name for p in rtl_ports if p.direction == 'output'}
        for sig in _spec_reset_tied_assert_signals(spec_text):
            if sig not in outs:
                continue  # guard (b): only the spec-named asserted output
            rn = _output_reset_gated(rtl_body, sig, rtl_ports)
            if rn:
                f.append(Finding(path, 'ERROR', 'moore-output-reset-gated', sig,
                    f"spec ties '{sig}'s N-cycle assertion window to RESET "
                    f"itself (assert WHENEVER reset, including while it is "
                    f"held), but the RTL conjoins '{sig}' with !{rn} — a "
                    f"held or re-asserted reset then eats assertion cycles "
                    f"(held-reset contiguous window comes out N-1, not N). "
                    f"Drive '{sig}' from the FSM state alone; do not gate it "
                    f"with the reset."))

    # ---- sync-reset FSM next-state redundantly gated on reset (ERROR) -------
    # The sequential block's synchronous reset already holds the FSM in the
    # reset state; gating the comb next-state of that state on the SAME reset
    # double-counts it and slips the post-reset launch timing. See the rule
    # comment above _sync_reset_next_state_redundant_gate (Prob139_2013_q2bfsm).
    if rtl_body:
        for rsig, rstate, arm in _sync_reset_next_state_redundant_gate(rtl_body):
            f.append(Finding(path, 'ERROR',
                'sync-reset-next-state-redundant-gate', rstate,
                f"the sequential block already applies a SYNCHRONOUS reset "
                f"('{rsig}' holds the FSM in '{rstate}'), but the combinational "
                f"next-state for '{rstate}' is ALSO gated on '{rsig}' "
                f"(`{arm}`) — this double-counts the reset and slips the "
                f"post-reset launch by a cycle. Drive the reset-state "
                f"transition UNCONDITIONALLY (`{rstate}: next = <launch>;`); the "
                f"sync reset in the sequential block holds '{rstate}' on its own."))
            break  # one finding per module is enough to block emit

    # ---- ordered one-cycle phase samples its later input early (ERROR) ------
    # Prompt says OUTPUT for one cycle, THEN monitor INPUT.  If the Moore state
    # that owns OUTPUT already reads INPUT, the first monitored value is consumed
    # during the pulse and every later recognition window is shifted by a cycle.
    if spec_text and rtl_body:
        in_names = {p.name for p in rtl_ports if p.direction == 'input'}
        out_names = {p.name for p in rtl_ports if p.direction == 'output'}
        for output, monitored, owner, arm, clause in \
                _ordered_phase_monitoring_early(spec_text, rtl_body):
            if output not in out_names or monitored not in in_names:
                continue
            f.append(Finding(path, 'ERROR',
                'ordered-phase-monitoring-early', owner,
                f"spec explicitly orders `{clause}`: monitoring '{monitored}' "
                f"starts AFTER the one-cycle '{output}' phase, but the RTL "
                f"decodes '{output}' from state '{owner}' and that same state's "
                f"next-state arm already reads '{monitored}' (`{arm}`). Make "
                f"the '{owner}' transition unconditional into a separate "
                f"monitoring state; consume '{monitored}' only there."))
            break  # one phase-collapse finding per module is enough

    # ---- SHIFTER spec implemented as a ROTATE (ERROR; lesson→program) ------
    # Spec describes a shifter and is NOT explicitly rotate-only, but the RTL
    # carries an unambiguous barrel-ROTATE wrap signature. Mechanizes the prose
    # "MANDATORY all-ones>>max self-TB" discriminator. See _rtl_rotate_signatures.
    if spec_text and rtl_body and _spec_describes_plain_shifter(spec_text):
        rotate_sigs = _rtl_rotate_signatures(rtl_body)
        # §4.05 false-fire fix (ORGANIC-20260618 round-2): the disjunction re-arm
        # ("shift OR rotate") now recognises the spec, but a CORRECT mode-
        # selectable barrel shifter has BOTH a logical-shift datapath AND a
        # rotate datapath, mux-selected — its rotate branch trips the signature.
        # SKIP (fail-safe under-fire) when the spec OFFERS BOTH operations AND
        # the RTL is that dual-mode shape; only a rotate-ONLY RTL (no co-present
        # logical-shift mux) still fires. A plain 'shifter' spec is unaffected.
        _out_names = {p.name for p in rtl_ports if p.direction == 'output'}
        dual_mode_ok = (_SHIFT_OR_ROTATE_RE.search(spec_text) is not None
                        and _rtl_dual_mode_shift_rotate(rtl_body, rotate_sigs,
                                                        _out_names))
        for sig in ([] if dual_mode_ok else rotate_sigs):
            f.append(Finding(path, 'ERROR', 'shift-implemented-as-rotate',
                rtl_name or 'module',
                f"spec describes a SHIFTER (not explicitly rotate-only) but the "
                f"RTL implements a wrap-around ROTATE: `{sig}`. A logical shift "
                f"fills the vacated bits with zeros; this wraps the shifted-out "
                f"bits back in (the MANDATORY all-ones >> max self-TB exposes it: "
                f"a rotate yields all-ones, a logical shift yields a single set "
                f"bit). Use the zero-fill shift (`x >> n` / `x << n`) unless the "
                f"spec EXPLICITLY says rotate/circular."))
            break  # one finding per module is enough to block emit

    # ---- triangle/ramp generator drops the spec PEAK-HOLD (ERROR; lesson→prog)
    # Spec explicitly requires the extreme to be HELD; the RTL immediately
    # reverses at the peak/trough with no hold/dwell state. Mechanizes the prose
    # "keep peak-hold unless spec forbids" discriminator. See _rtl_drops_peak_hold.
    if spec_text and rtl_body and _spec_requires_peak_hold(spec_text):
        toggled = _rtl_drops_peak_hold(rtl_body)
        if toggled:
            f.append(Finding(path, 'ERROR', 'waveform-peak-hold-dropped',
                toggled,
                f"spec requires the waveform to HOLD the peak/trough, but the "
                f"RTL toggles the direction signal '{toggled}' the instant the "
                f"value reaches the extreme — there is no hold/dwell state, so "
                f"the peak is one cycle wide and the spec dwell is dropped. Add "
                f"a hold counter that pauses the direction toggle for the "
                f"spec-stated cycle(s) at the peak/trough (unless the spec "
                f"EXPLICITLY forbids the hold / is a plain sawtooth)."))

    # ---- FSM next-state transition completeness (ERROR; #522) --------------
    # Recurring across benchmark clean-room rounds 1-3: a fresh author makes a
    # next-state logic error on a different FSM each round. The Moore/Mealy check
    # above only validates OUTPUT STYLE — not that the next-state logic is sound.
    # This wires the deterministic, zero-false-positive STRUCTURAL check (an
    # inferred latch in the next-state case) into the gate so it fires on every
    # FSM design instead of living in unreliable agent prose (the #517/#518
    # prose-is-dormant lesson). Best-effort: a parser hiccup never fails the gate.
    if spec.fsm_output_style and rtl_body:
        try:
            import sys as _sys
            _here = str(Path(__file__).resolve().parent)
            if _here not in _sys.path:
                _sys.path.insert(0, _here)
            from fsm_transition_completeness_check import check_text as _fsm_chk
            _fsm_findings, _ = _fsm_chk(rtl_body)
            for _ff in _fsm_findings:
                if _ff.severity == 'ERROR':
                    f.append(Finding(path, 'ERROR', _ff.rule, _ff.state,
                                     _ff.detail))
        except Exception:  # nosec — structural check is best-effort
            pass

    # ---- one-hot continuous-assign next-state completeness (ERROR; #791) -----
    # The case-driven check above is BLIND to a one-hot FSM authored as pure
    # continuous-assigns (no `case`) — it never registers fsm_output_style and
    # check_text() SKIPs (-no-state-declarations). VerilogEval
    # Prob150_review2015_fsmonehot dropped a SPEC-DISCLOSED self-loop
    # (`Count --done_counting=0--> Count`) and shipped PASS. This wires the
    # deterministic, zero-false-fire one-hot check (it needs the spec's disclosed
    # transition table, so it takes BOTH rtl_body and spec_text). Gated on a
    # disclosed arrow-form transition table + parseable one-hot next-state
    # assigns — SKIPs otherwise (no false fire). Best-effort: a parser hiccup
    # never fails the gate.
    if rtl_body and spec_text:
        try:
            import sys as _sys
            _here = str(Path(__file__).resolve().parent)
            if _here not in _sys.path:
                _sys.path.insert(0, _here)
            from fsm_transition_completeness_check import (
                check_onehot_continuous_assign as _oh_chk)
            _oh_findings, _ = _oh_chk(rtl_body, spec_text)
            for _of in _oh_findings:
                if _of.severity == 'ERROR':
                    f.append(Finding(path, 'ERROR', _of.rule, _of.state,
                                     _of.detail))
        except Exception:  # nosec — structural check is best-effort
            pass

    # ---- multi-cycle valid/ready handshake structural checks (ERROR; #523) ---
    # Two recurring author bugs in an N-cycle valid/ready datapath that PASS the
    # author's own TB but hang / corrupt under an always-ready consumer:
    # a load-guard LIVELOCK (missing busy-exclusion) and a RESULT register
    # driven by a free-running working reg. Both are deterministic, zero-false-
    # positive STRUCTURAL checks gated on a `*valid` output + `*ready` input
    # handshake port pair (so streaming / register-mapped / bus designs SKIP).
    # Wired here instead of living in unreliable valid/ready prose (the #517/#518
    # prose-is-dormant lesson). Best-effort: a parser hiccup never fails the gate.
    if rtl_body:
        try:
            import sys as _sys
            _here = str(Path(__file__).resolve().parent)
            if _here not in _sys.path:
                _sys.path.insert(0, _here)
            from handshake_livelock_result_stability_check import (
                check_text as _hs_chk)
            _hs_findings, _ = _hs_chk(rtl_body)
            for _hf in _hs_findings:
                if _hf.severity == 'ERROR':
                    f.append(Finding(path, 'ERROR', _hf.rule, _hf.symbol,
                                     _hf.detail))
        except Exception:  # nosec — structural check is best-effort
            pass

    # ---- spec STRUCTURE representation (advisory) --------------------------
    # The rules above are the INTERFACE half of spec conformance: ports,
    # directions, widths, resets. The other half — is every register, enumerated
    # mode and FSM state the spec names actually REPRESENTED in the RTL — lives
    # in `spec_conformance_gate` and was enforced NOWHERE: that module's only
    # consumer was its own unit test. It is not a vacuous gate; measured over the
    # 302 CVDP code-generation records it distils 54 register names, 112 FSM
    # states, 153 transitions and 310 worked examples out of the prompts.
    #
    # ADVISORY (INFO), never ERROR, and the asymmetry is deliberate. The spec
    # here is recovered from PROSE, and `_token_represented` is satisfied by the
    # token appearing as a Verilog identifier anywhere — a design that spells a
    # state `ST_IDLE` where the prose wrote `IDLE` is CORRECT and would be
    # flagged. §4.05 forbids a false block on a fuzzy extraction, so this
    # reports and never refuses. `build_gate` omits any field the extractor did
    # not recover, so a prose spec with no structures produces no findings at
    # all rather than a vacuous pass.
    if rtl_body and spec_text:
        try:
            import sys as _sys
            _here = str(Path(__file__).resolve().parent)
            if _here not in _sys.path:
                _sys.path.insert(0, _here)
            import spec_complete_extract as _sce           # noqa: PLC0415
            import spec_conformance_gate as _scg           # noqa: PLC0415
            _ins = [p.name for p in rtl_ports if p.direction == 'input']
            _outs = [p.name for p in rtl_ports
                     if p.direction in ('output', 'inout')]
            _gate = _scg.build_gate(_sce.assess_spec(spec_text, _ins, _outs))
            for _v in _scg.gate_check_spec(_gate, rtl_body).get('violations', []):
                _kind = _v.get('kind', '')
                # ONLY the structure half. The interface half is enforced above,
                # by rules that have the RTL parse to reason from; re-reporting
                # it here would double-count and disagree at the edges.
                if _kind.startswith('missing_') and _kind != 'missing_port':
                    # symbol = the MISSING TOKEN, not the module. Three absent
                    # registers otherwise render as three identical lines naming
                    # the module, which says a count and not a fact.
                    f.append(Finding(path, 'INFO', _kind.replace('_', '-'),
                                     _v.get('token') or rtl_name or '<module>',
                                     _v.get('detail', '')))
        except Exception:  # nosec — advisory pass is best-effort
            pass

    # ---- frame contract: mapping + temporal composition (#2035 F4) ---------
    # `input_prose` defaults to `spec_text` so every existing caller keeps its
    # behaviour byte-for-byte; only `main()` supplies a DIFFERENT channel, for
    # the JSON contract case where `spec_text` is deliberately empty.
    f += _frame_contract_findings(input_prose or spec_text, rtl_body,
                                  rtl_ports, path, rtl_name)
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

    # A JSON CONTRACT IS NOT PROSE-FREE, and treating it as prose-free left
    # every prose-derived rule in this gate structurally DORMANT on the flow's
    # own invocation. Measured on this base, 2026-09-06, with one RTL body and
    # one wording carried in two containers:
    #   --spec spec.md   -> FAIL, 1 error (msbfirst-direction-mismatch)
    #   --spec spec.json -> PASS, 0 findings          (same RTL, same sentence)
    # and flow/phase1_phase2_phase3.yaml step 2 passes
    # `--spec phase1/generated_docs/L9_INTEGRATION_SPEC.json`. An L9 integration
    # spec carries a `description` on every port whose sibling `evidence` field
    # names the input doc it was recovered from; `main()` discarded all of it.
    #
    # `input_prose` is a SEPARATE channel from `spec_body` on purpose. The
    # existing prose rules were tuned against PROMPT prose and their false-fire
    # behaviour on L9 description fields is unmeasured, so opening that channel
    # to them wholesale is a change no measurement here supports. Only the
    # frame-contract rules — which are swept over the corpus in this same change
    # — read it. Widening it later is a separate decision with its own evidence.
    input_prose = spec_body
    if not input_prose:
        try:
            from _frame_contract import input_prose_from_json
            input_prose = input_prose_from_json(spec_raw)
        except ImportError:                      # library absent: no channel
            input_prose = ''

    top = args.top or spec.module
    files = collect_rtl_files(args.paths, args.rtl_dir)
    if not files:
        print('spec_conformance_check: FAIL — no RTL files found', file=sys.stderr)
        return 2

    # ORGANIC #186 — the reset/clock variant-alias step
    # (design_one_shot_runner.step_reset_clock_variant_aliases) may rename the
    # AUTHORED top to `<top>__rcvar_inner` and wrap it in a same-named wrapper
    # that can widen the port list (e.g. an additive dual-spelling reset synonym
    # → a 9th top port). The AUTHORED interface is the one the design docs pin, so
    # conformance must be judged against the inner authored module, NOT the
    # runner-introduced wrapper — otherwise the flow FAILs an IC for a port the
    # flow itself grafted on. When a `<top>__rcvar_inner` module is present in the
    # collected RTL, redirect the top to it. chip-AGNOSTIC: keys only on the
    # runner's own fixed `__rcvar_inner` suffix, no chip literal.
    import re as _re
    if top:
        _inner = f"{top}__rcvar_inner"
        _inner_decl = _re.compile(rf"\bmodule\s+{_re.escape(_inner)}\b")
        for f in files:
            try:
                if _inner_decl.search(strip_comments(f.read_text(errors='replace'))):
                    top = _inner
                    break
            except Exception:  # noqa: BLE001 — a bad file just isn't the inner
                continue

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
    # ORGANIC — read the DECLARED interface renames (SOURCE_MANIFEST #711).
    # Reuse `l9_rtl_pin_consistency_check`'s parser rather than re-implementing
    # it: the two gates must not drift apart in what they accept as a
    # declaration. Any import/read failure yields NO groups, so the gate keeps
    # its exact-name comparison (fail-closed, no-leak).
    _renamed_groups: List[tuple] = []
    try:
        import l9_rtl_pin_consistency_check as _l9pin
        # Derive the project root from the RESOLVED RTL FILES, never from which
        # ARG SHAPE the caller used. Keying on `--rtl-dir` made the verdict
        # depend on HOW the gate was invoked: the identical tree with the
        # identical declaration returned PASS via `--rtl-dir` and FAIL when the
        # same directory was passed positionally — a silent, invocation-shaped
        # difference in a conformance verdict. Walk each collected file's
        # ancestors and accept the first that actually carries the manifest at
        # the layout path; no match ⇒ no groups ⇒ exact-name comparison
        # (fail-closed). chip-AGNOSTIC: path layout only, no chip literal.
        _proj = None
        for _f in files:
            for _anc in Path(_f).resolve().parents:
                if (_anc / "phase2" / "stage1" / "rtl"
                        / "SOURCE_MANIFEST.json").is_file():
                    _proj = _anc
                    break
            if _proj is not None:
                break
        _mf = _l9pin.load_source_manifest(_proj) if _proj else None
        if _mf:
            _renamed_groups = _l9pin._manifest_renamed_groups(_mf)
    except Exception:  # noqa: BLE001 — no manifest ⇒ no relaxation
        _renamed_groups = []

    findings = check(spec, rtl_name, rtl_ports, rtl_resets, rtl_registered, chosen,
                     rtl_body, spec_text=spec_body,
                     renamed_groups=_renamed_groups, input_prose=input_prose)

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

    # The zero denominator said in the shape the house prober reads (#564):
    # `0 spec port(s) read`, not `ports=0`.
    _zero_ports_note = ('' if spec.ports else
                        ' — spec contract: 0 port(s) read,'
                        ' port comparison NOT_MEASURED')
    errs = [x for x in findings if x.severity == 'ERROR']
    warns = [x for x in findings if x.severity == 'WARN']
    infos = [x for x in findings if x.severity == 'INFO']
    fail = bool(errs) or (args.strict and bool(warns))
    verdict = 'FAIL' if fail else 'PASS'
    print(f"spec_conformance_check: {verdict} — findings: {len(findings)} "
          f"({len(errs)} error, {len(warns)} warn, {len(infos)} info) "
          f"[spec ports={len(spec.ports)}({spec.source})"
          f"{_zero_ports_note}, rtl ports={len(rtl_ports)}, "
          f"spec reset={spec.reset_mode or '-'}/{spec.reset_polarity or '-'}]")
    for fd in sorted(findings, key=lambda x: (x.severity, x.rule, x.symbol)):
        print(f"  [{fd.severity}] {fd.rule}: {fd.message}")
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(x) for x in findings], indent=2))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
