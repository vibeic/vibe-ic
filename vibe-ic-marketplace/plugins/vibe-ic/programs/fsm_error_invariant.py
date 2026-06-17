#!/usr/bin/env python3
"""
fsm_error_invariant.py — Detect FSMs where an error signal can break upper-layer
invariants.

Pattern (general, learned from <half-duplex-tester> bug #4):
    An RX PHY FSM asserts `rx_error` when a bit can't be decoded. The MAC
    FSM above it terminates the current packet on `rx_error`. But:
      - If `rx_error` fires for a RECOVERABLE noise event (1-cycle glitch),
        the perfectly valid rest of the packet is discarded.
      - Any upper-layer invariant ("packet is contiguous") breaks.

This script scans RTL for the anti-pattern:
    error_signal <= 1'b1;     // fired inside a DEEP FSM state (not idle)
    → consumed by upper layer as packet-terminating event

And reports WARN when:
  - A signal named *error*, *err*, *fail*, *abort* is asserted inside a
    non-idle state of a module
  - That signal crosses module boundaries (in a port list)
  - No comment near the assignment clarifies "recoverable" vs "fatal"

This is a heuristic INFO/WARN check, not a proof. The goal is to raise the
question: "is this error fatal or should upstream tolerate it?"

Usage:
    python3 fsm_error_invariant.py <files.sv ...>

Generality: applies to any hierarchical FSM design. Not tied to any protocol.
"""
from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List


ERROR_NAMES = re.compile(
    r'\b(\w*(?:error|err|fail|abort|timeout|reject|invalid)\w*)\b',
    re.IGNORECASE)


# v1.1.1 (R9C2) — a fault/error STATE is a state whose label name itself
# denotes a fault/error/abort condition (e.g. FAULT, ERROR, ERR, FAIL,
# ABORT, FATAL, TIMEOUT, REJECT, INVALID, S_ERROR, ST_FAULT). When an
# error output is asserted INSIDE such a state branch, that is the literal
# spec requirement for an error/fault state ("FAULT: Asserts o_error to
# indicate a fault condition") — NOT the cross-layer anti-pattern this gate
# targets (a recoverable error fired mid-operation that an upper FSM
# wrongly treats as packet-terminating). Reuses the same error-semantic
# vocabulary as ERROR_NAMES plus `fault`/`fatal`, so the recognition is
# symmetric: `o_error <= 1'b1` in a FAULT/ERROR/FAIL state is spec-mandated;
# the same assignment in IDLE/RUN/PROCESS/RX (a non-error-named operational
# state) still fires. Chip-AGNOSTIC: keyed only on the state LABEL's name.
_FAULT_STATE_NAME = re.compile(
    r'(?:error|err|fail|fault|abort|fatal|timeout|reject|invalid)',
    re.IGNORECASE)
# ORGANIC #786 r2 (Step-2.7 §4.05) — whole-TOKEN fault vocab (NOT a substring).
_FAULT_WORDS = frozenset({
    'error', 'err', 'fail', 'fault', 'abort', 'fatal', 'timeout', 'reject',
    'invalid', 'exception', 'panic', 'halt', 'illegal', 'violation'})
# A token that makes the state OPERATIONAL (a recovery / wait / negation /
# control state), so even if another token is a fault word the state is NOT a
# terminal fault state and the error-assertion anti-pattern must still fire.
_FAULT_NEGATER_WORDS = frozenset({
    'no', 'non', 'not', 'clear', 'cleared', 'recover', 'recovery', 'recovered',
    'less', 'safe', 'free', 'wait', 'waiting', 'check', 'checking', 'validate',
    'validating', 'handle', 'handling', 'handler', 'exit', 'done', 'ack',
    'default', 'resync', 'retry', 'normal', 'ok', 'pass', 'idle', 'run'})

# ORGANIC #804 (Step-2.7 §4.05) — standard BUS-PROTOCOL error-RESPONSE outputs.
# When one of these is asserted in the `default:` branch of an address-DECODE
# case (a case whose selector is an *addr*/*adr* expression), that is the
# protocol-mandated bad-address error response — APB PSLVERR, AXI BRESP/RRESP
# (SLVERR/DECERR), AHB HRESP, Wishbone ERR_O — NOT the cross-layer
# recoverable-mid-FSM-error anti-pattern this gate targets. Keyed only on generic
# bus-protocol vocabulary; chip-AGNOSTIC. A spurious error assertion in a NORMAL
# operational state (numbered FSM state, or a non-addr case, or a generic `err`
# in the addr default) still fires — the default-branch-of-an-address-decode is
# the narrow, protocol-grounded exemption.
_BUS_ERR_RESP = re.compile(
    r'^(?:'
    r'\w*pslverr\w*|'              # APB PSLVERR (any prefix/suffix)
    r'\w*slverr\w*|'              # generic SLVERR
    r'\w*bresp\w*|\w*rresp\w*|'   # AXI write/read response (SLVERR/DECERR)
    r'\w*hresp\w*|'              # AHB response
    r'err_o|'                    # Wishbone err_o — BARE/EXACT only
    r'\w*decerr\w*|\w*slv_err\w*|\w*bus_err\w*|\w*dec_err\w*'
    r')$', re.IGNORECASE)
# ORGANIC #804 Step-2.7 §4.05 — the Wishbone `err_o` arm is EXACT (bare `err_o`,
# the Wishbone convention), NOT the generic functional-error `_o`/`_out` output
# convention. A prefixed/suffixed form (`crc_err_o`, `parity_err_o`,
# `rx_err_out`, `timeout_err_o`, `err_overflow`) is a genuine error flag, NOT a
# protocol bus-error RESPONSE — it MUST still fire. A bus-prefixed `wb_err_o`
# falling through to a (false) hard-block is the SAFE direction (§4.05: a false
# block is a field reopen; masking a real recoverable-error anti-pattern is a
# silent leak).

# An address-DECODE case selector: a *addr* / *adr* expression (paddr, haddr,
# awaddr, address, mem_adr, …). Step-2.7 §4.05 — `addr`/`adr` must be a real
# address TOKEN (at end, or followed by `_`/digit), or the word `address` — NOT a
# substring buried inside another word (squadron / quadrant / cadre / padre).
_ADDR_SELECTOR_RE = re.compile(
    r'a(?:ddr|dr)(?![a-z])|address', re.IGNORECASE)


# ORGANIC #786 r3 (Step-2.7 §4.05) — SIGNAL-NAME error vocabulary as a
# whole-TOKEN set (mirrors the state-LABEL fix of #786 r2). The assignment-LHS
# locator regex below (`\w*(?:error|err|...)\w*`) is a SUBSTRING match: it fires
# on any identifier that merely CONTAINS an error word — most notably the whole
# `interrupt_*` family, because "int-ERR-upt" embeds `err` (cpu_interrupt,
# interrupt_valid, interrupt_idx, interrupt_requests, nvic_interrupt, ...). Those
# are normal functional outputs, not error flags, so a `cpu_interrupt <= 1'b1`
# was wrongly hard-blocked. Fix: after the locator finds a candidate, confirm the
# LHS is GENUINELY an error signal by underscore/camelCase segment membership —
# an EXACT segment must be one of these words. This retains prefix/suffix forms
# (err_o, o_error, timeout_err, fail_flag, rx_error, crc_err_o, errorFlag) while
# exempting names that only embed an error word as a substring (interrupt,
# terror, merrily). chip-AGNOSTIC: keyed on generic error vocabulary only.
_SIGNAL_ERR_TOKENS = frozenset({
    'error', 'err', 'fail', 'abort', 'timeout', 'reject', 'invalid'})
# UNAMBIGUOUS multi-letter error words that may appear GLUED inside a single
# segment as a derivational form — `rxfailure`, `txaborted`, `pktrejected`,
# `parityfailure`, `crcfailure`, `rxtimeout`, `dataerror`. Unlike the short
# `err` (embedded in the common non-error word `interrupt`), these full words do
# NOT occur inside ordinary non-error identifiers, so they are safe to match as a
# substring ANYWHERE in the name. This restores detection of glued all-lowercase
# error flags that the segment prefix/suffix rule alone drops (Step-2.7 §4.05:
# a genuine mid-FSM error/abort/reject/failure flag must fire regardless of
# naming convention). `interrupt`/`interrupt_valid` carry none of these and stay
# exempt. chip-AGNOSTIC.
_LONG_ERR_SUBSTRINGS = ('error', 'failure', 'abort', 'reject', 'timeout')


def _signal_segments(name: str) -> List[str]:
    """Split a signal identifier into lower-cased segments on underscore,
    non-word, and camelCase / letter<->digit boundaries."""
    segs: List[str] = []
    for chunk in re.split(r'[_\W]+', name):
        if not chunk:
            continue
        sub = re.findall(
            r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+', chunk)
        segs.extend(sub if sub else [chunk])
    return [s.lower() for s in segs]


def _signal_is_error(name: str) -> bool:
    """True iff an underscore/camelCase segment of `name` is an error-vocabulary
    word, or carries one as a segment PREFIX or SUFFIX — but NOT when the error
    word is strictly INTERNAL to a segment (letters on both sides). So `err_o`/
    `o_error`/`timeout_err`/`rx_error`/`fail_flag` (whole segment) and `pslverr`
    (the APB slave-error signal: `err` as a segment SUFFIX, ORGANIC #804) fire,
    while `cpu_interrupt`/`interrupt_valid`/`interrupt_idx` (where `err` is
    strictly internal: int-ERR-upt) and `merrily` (m-ERR-ily) do not.

    The suffix rule that is required to catch `pslverr` necessarily also matches
    a word like `terror` (ends with `error`); this is benign — no real non-error
    hardware signal is named `terror` — and pure tokenization cannot separate the
    two, so we bias toward NOT regressing the shipped #804 pslverr detection."""
    for seg in _signal_segments(name):
        for tok in _SIGNAL_ERR_TOKENS:
            if seg == tok or seg.startswith(tok) or seg.endswith(tok):
                return True
    # Glued derivational forms (rxfailure / txaborted / pktrejected) where the
    # error word is internal to the segment: caught via the unambiguous
    # multi-letter substrings (never present inside `interrupt`-style non-error
    # names). §4.05 no-leak.
    low = name.lower()
    return any(sub in low for sub in _LONG_ERR_SUBSTRINGS)


def _is_fault_state(label) -> bool:
    """True iff the case-state label name semantically denotes a
    fault/error/abort state — i.e. a state the spec would mandate to
    assert an error output. A numeric/literal label (e.g. 2'b11) or a
    missing label carries no such semantics -> False (the genuine
    mid-FSM spurious-error anti-pattern is preserved)."""
    if not label:
        return False
    # A sized numeric literal (e.g. 2'b11 / 3'd5) carries no fault
    # semantics — only a NAMED localparam/parameter label can.
    if re.match(r"^\d+'[sS]?[dbhoxDBHOX]\w+$", label):
        return False
    # Strip an optional leading state-prefix (S_/ST_/STATE_) so e.g.
    # S_FAULT / ST_ERROR resolve correctly.
    name = re.sub(r'^(?:s|st|state)_', '', label, flags=re.IGNORECASE)
    # ORGANIC #786 r2 (Step-2.7 §4.05) — WHOLE-TOKEN semantics, not a substring.
    # The prior `_FAULT_STATE_NAME.search(name)` SUBSTRING match wrongly exempted
    # operational states whose name merely CONTAINS a fault word — ERROR_RECOVERY,
    # WAIT_TIMEOUT, FAILSAFE, NO_FAULT, CLEAR_ERROR, FAULT_CLEAR, S_FAULTLESS,
    # DEFAULT — silently suppressing genuine mid-FSM spurious-error anti-patterns.
    # Split on `_`/non-word and judge tokens: a negater/operational token ANYWHERE
    # forces NOT-a-fault-state (still fires); exempt ONLY when a WHOLE token is
    # exactly a fault word. chip-AGNOSTIC: general error vocabulary.
    tokens = [tok.lower() for tok in re.split(r'[_\W]+', name) if tok]
    if not tokens:
        return False
    if any(tok in _FAULT_NEGATER_WORDS for tok in tokens):
        return False
    return any(tok in _FAULT_WORDS for tok in tokens)


@dataclass
class Finding:
    file: str
    line: int
    signal: str
    state_context: str
    message: str


def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, preserving newlines."""
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i+2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' '
                               for c in src[i:end+2]))
            i = end + 2
        elif src[i:i+2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


_ANNOTATION_RE = re.compile(
    r"//\s*fsm_error\s*[:=]\s*(recoverable|fatal|intentional|tolerated)\b",
    re.IGNORECASE,
)


def _has_intent_comment(raw_lines: list, lineno: int, label: str) -> bool:
    """v0.119.25: scan raw (un-stripped) source within ±2 lines of the
    error-assignment line for an intent annotation:

        err <= 1'b1;  // fsm_error: recoverable
        // fsm_error: fatal
        err <= 1'b1;

    `label` is one of: "recoverable", "fatal", "intentional", "tolerated".
    Returns True only when an annotation matching `label` (or
    "intentional"/"tolerated" as universal silencers) is present nearby.
    """
    start = max(0, lineno - 3)
    end = min(len(raw_lines), lineno + 2)
    for i in range(start, end):
        m = _ANNOTATION_RE.search(raw_lines[i])
        if not m:
            continue
        kind = m.group(1).lower()
        if kind == label.lower():
            return True
        if kind in ("intentional", "tolerated"):
            return True
    return False


def find_error_assertions(src: str, path: str) -> List[Finding]:
    findings: List[Finding] = []
    raw_lines = src.split('\n')
    src = strip_comments(src)
    lines = src.split('\n')

    # Track current case-state context for each line
    state_stack = []  # list of (case_expr, state_label)

    current_state_label = None
    in_case = 0
    # ORGANIC #804 — per-case selector stack + a default-branch flag, so a
    # bus-error RESPONSE asserted in the `default:` of an address-decode case is
    # exempted (the protocol-mandated bad-address response), while every other
    # site still fires.
    selector_stack: List[str] = []
    in_default = False

    for lineno, line in enumerate(lines, start=1):
        # Detect case open
        case_m = re.search(r'\bcase[szx]?\s*\(([^)]+)\)', line)
        if case_m:
            in_case += 1
            selector_stack.append(case_m.group(1))
            in_default = False
        # Detect endcase
        if 'endcase' in line:
            in_case = max(0, in_case - 1)
            current_state_label = None
            if selector_stack:
                selector_stack.pop()
            in_default = False
        # Detect state label within case. v1.1.1 (R9C2): widened to also
        # recognise NAMED (localparam/parameter) case labels — e.g.
        # `FAULT:`, `S_ERROR:`, `READY:` — not only `S_\w+`/numeric
        # literals. The prior regex left localparam-named labels
        # unresolved (current_state_label stayed None), so a spec-mandated
        # FAULT branch was mis-attributed to "<not in case branch>" and the
        # gate could not tell it was the error state. Matches a bare
        # identifier label or a sized numeric literal at branch start;
        # avoids `default:` and statement labels by requiring the line to
        # be only `<label> :` optionally followed by `begin`.
        if in_case > 0:
            lm = re.match(
                r'\s*([A-Za-z_]\w*|\d+\'[sS]?[dbhoxDBHOX]\w+)\s*:'
                r'\s*(?:begin\b)?\s*$', line)
            if lm and lm.group(1).lower() != 'default':
                current_state_label = lm.group(1)
            # ORGANIC #804 — track the default branch ROBUSTLY: a `default:` whose
            # body is on the SAME line (`default: pslverr <= 1'b1;`) is missed by
            # the label-ALONE `lm` regex above. Detect a label at line START
            # (trailing body allowed); `default:` opens the default branch (and
            # does NOT inherit the prior numeric case label — the mis-attribution
            # bug), any other label at line-start ends it.
            _lbl0 = re.match(
                r'\s*(default|[A-Za-z_]\w*|\d+\'[sS]?[dbhoxDBHOX]\w+)\s*:', line)
            if _lbl0:
                if _lbl0.group(1).lower() == 'default':
                    in_default = True
                    current_state_label = None
                else:
                    in_default = False
        # Find: errSig <= 1'b1;
        assign = re.search(
            r'\b(\w*(?:error|err|fail|abort|timeout|reject|invalid)\w*)\s*<=\s*1(?:\'b1|b1|\'d1)',
            line, re.IGNORECASE)
        if assign:
            sig = assign.group(1)
            # ORGANIC #786 r3 (Step-2.7 §4.05) — the locator regex matches the
            # error vocabulary as a SUBSTRING (`\w*err\w*`), so it also fires on
            # the whole `interrupt_*` family ("int-ERR-upt" embeds `err`) and any
            # name that merely contains an error word. Confirm the LHS is a
            # GENUINE error signal by whole-TOKEN (underscore/camelCase segment)
            # membership; otherwise it is a normal functional output (cpu_interrupt,
            # interrupt_valid, interrupt_idx) and must NOT be flagged. Real error
            # flags (err_o, o_error, timeout_err, rx_error, fail_flag) still fire.
            if not _signal_is_error(sig):
                continue
            # Skip if context is reset-block clause (rst_n / !rst_n)
            # Heuristic: check last 5 lines for rst_n
            ctx = '\n'.join(lines[max(0, lineno-6):lineno])
            if re.search(r'if\s*\(\s*!?\s*rst_n', ctx):
                continue
            # v0.119.25: comment annotation override. Designer can add
            #     err <= 1'b1;  // fsm_error: recoverable
            # within ±2 lines and the gate skips. Or "fatal" / "intentional"
            # / "tolerated" — any of those silences the warning. Without
            # an annotation, the warning fires (default behavior).
            if _has_intent_comment(raw_lines, lineno, "recoverable"):
                continue
            if _has_intent_comment(raw_lines, lineno, "intentional"):
                continue
            # v1.1.1 (R9C2): skip when the error output is asserted inside
            # a fault/error-named state branch. Asserting an error signal in
            # a state whose label literally denotes a fault/error condition
            # (FAULT/ERROR/FAIL/ABORT/...) is the spec's literal requirement
            # for that state, not the cross-layer recoverable-error anti-
            # pattern this gate targets. A spurious error assertion in a
            # NON-error-named operational state (IDLE/RUN/PROCESS/RX/...) or
            # under a numeric/unknown label still fires (no-leak).
            if _is_fault_state(current_state_label):
                continue
            # ORGANIC #804 (Step-2.7 §4.05) — a standard bus-protocol error
            # RESPONSE (PSLVERR/SLVERR/BRESP/RRESP/HRESP/ERR_O/DECERR) asserted in
            # the `default:` branch of an ADDRESS-DECODE case is the
            # protocol-mandated unmapped-address response, NOT the
            # recoverable-mid-FSM-error anti-pattern. Exempt ONLY that narrow
            # site: in_default AND the enclosing case selector is an *addr*/*adr*
            # expression AND the signal is bus-error-response vocabulary. A
            # generic `err` in the addr default, a bus-resp in a non-addr case, a
            # bus-resp in a MAPPED (non-default) branch, and any mid-FSM error all
            # still fire (no-leak).
            _sel = selector_stack[-1] if selector_stack else ""
            if (in_default and _ADDR_SELECTOR_RE.search(_sel)
                    and _BUS_ERR_RESP.match(sig)):
                continue
            state = current_state_label or "<not in case branch>"
            findings.append(Finding(
                path, lineno, sig, state,
                f"'{sig}' asserted inside FSM state '{state}'. "
                "Verify upper-layer tolerates this error gracefully; "
                "if fatal, document why — if recoverable, consider "
                "skip-and-continue. Add `// fsm_error: recoverable` "
                "next to the assignment to silence this warning."))
    return findings


def main():
    ap = argparse.ArgumentParser(description='FSM error invariant check')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--json', help='write findings as JSON')
    args = ap.parse_args()

    # Expand directories to (.v, .sv, .vh) files for directory inputs.
    # v0.1.62 — this gate audits DESIGN-RTL FSM error invariants. Generated
    # test/BIST/FPGA/sim scaffolding (e.g. `fpga/<top>_fpga_bist.v`) legitimately
    # latches a `fail`/`error` flag — that IS its purpose — so scanning it
    # produced a false-positive on spm/sha256. When a project root is given,
    # prefer the design RTL dir and exclude generated verification scaffolding.
    _SCAFFOLD_DIR_PARTS = {"fpga", "sim", "sim_full_stack", "tb", "test",
                           "tests", "testbench", "bench", "verif",
                           "verification", "formal"}

    def _is_scaffold(path: Path) -> bool:
        parts = {seg.lower() for seg in path.parts}
        if parts & _SCAFFOLD_DIR_PARTS:
            return True
        stem = path.stem.lower()
        return (stem.startswith(("tb_", "test_")) or
                stem.endswith(("_tb", "_test", "_bist", "_bench",
                               "_tb_full", "_harness")))

    def _dir_rtl_files(d: Path) -> List[Path]:
        # Prefer the canonical design-RTL directory if present.
        for cand in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
            sub = d / cand
            if sub.is_dir() and (any(sub.glob("*.v")) or any(sub.glob("*.sv"))):
                return [f for f in sorted(sub.rglob("*"))
                        if f.is_file() and f.suffix in (".v", ".sv", ".vh", ".svh")
                        and not _is_scaffold(f)]
        # Fall back to a filtered project-wide scan.
        return [f for f in sorted(d.rglob("*"))
                if f.is_file() and f.suffix in (".v", ".sv", ".vh", ".svh")
                and not _is_scaffold(f)]

    expanded: List[Path] = []
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"WARNING: {f} not found", file=sys.stderr)
            continue
        if p.is_dir():
            expanded.extend(_dir_rtl_files(p))
        else:
            expanded.append(p)

    all_f: List[Finding] = []
    for p in expanded:
        try:
            # v0.119.25: pass RAW text so the comment-annotation scanner
            # can see `// fsm_error: recoverable` next to assignments.
            # find_error_assertions strips comments internally for the
            # state-machine analysis it actually does.
            raw = p.read_text(errors='replace')
        except (OSError, UnicodeDecodeError):
            continue
        all_f += find_error_assertions(raw, str(p))

    print(f"fsm_error_invariant: {len(all_f)} error-assertion sites found")
    print('-' * 70)
    for fd in all_f:
        print(f"{fd.file}:{fd.line}: [{fd.signal} in {fd.state_context}] {fd.message}")

    if args.json:
        import json
        Path(args.json).write_text(
            json.dumps([f.__dict__ for f in all_f], indent=2))

    return 1 if all_f else 0


if __name__ == '__main__':
    sys.exit(main())
