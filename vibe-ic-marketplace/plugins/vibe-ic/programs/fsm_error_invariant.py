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

    for lineno, line in enumerate(lines, start=1):
        # Detect case open
        case_m = re.search(r'\bcase[szx]?\s*\(([^)]+)\)', line)
        if case_m:
            in_case += 1
        # Detect endcase
        if 'endcase' in line:
            in_case = max(0, in_case - 1)
            current_state_label = None
        # Detect state label within case: S_XXX: or 3'dN:
        if in_case > 0:
            lm = re.match(r'\s*(S_\w+|\d+\'[dbh]\w+)\s*:', line)
            if lm:
                current_state_label = lm.group(1)
        # Find: errSig <= 1'b1;
        assign = re.search(
            r'\b(\w*(?:error|err|fail|abort|timeout|reject|invalid)\w*)\s*<=\s*1(?:\'b1|b1|\'d1)',
            line, re.IGNORECASE)
        if assign:
            sig = assign.group(1)
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
    expanded: List[Path] = []
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"WARNING: {f} not found", file=sys.stderr)
            continue
        if p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file() and sub.suffix in (".v", ".sv", ".vh", ".svh"):
                    expanded.append(sub)
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
