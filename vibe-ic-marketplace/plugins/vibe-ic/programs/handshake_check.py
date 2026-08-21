#!/usr/bin/env python3
"""handshake_check.py — deterministic compliance check derived from <chip-class> v040 debug.

Detects producer-consumer races where a producer emits a single-cycle pulse
on a signal named *_valid / *_done / *_ready, but the consumer samples that
signal only at the end of a multi-cycle countdown (`if (timer == 0)`),
potentially missing the pulse.

Pattern:
  - Producer: `sig_valid <= 1'b1;` under a conditional, with `sig_valid <= 1'b0;`
    as the default at the top of its always block → classic 1-cycle pulse.
  - Consumer: samples `sig_valid` inside a branch gated by a timer/counter
    reaching zero (e.g. `if (timer == 0) ... sig_valid ...`).

Recommended fix: latch-on-arrival — the consumer should set a `pending` flag
the moment it sees `sig_valid`, not re-read `sig_valid` at the end of a wait.

Exit: 0 = PASS (no races), 1 = FAIL.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Set, Tuple

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Collection routes
# through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the char-level comment strip again
# (see _specrtl_common.rtl_source_files for the full scale rationale).
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def strip_comments(src: str) -> str:
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i+2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end+2]))
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


def find_rtl_files(project_dir: Path) -> List[Path]:
    # Kimi-scale fix: shared authored-RTL collector.
    return rtl_source_files(project_dir)


HANDSHAKE_SUFFIX = re.compile(r'\b(\w+_(?:valid|done|ready))\b')
PULSE_HIGH = re.compile(r'\b(\w+_(?:valid|done|ready))\s*<=\s*1\'?b?1\b')
PULSE_LOW = re.compile(r'\b(\w+_(?:valid|done|ready))\s*<=\s*1\'?b?0\b')


def find_pulse_producers(src: str) -> Set[str]:
    """
    Return set of handshake signal names that are assigned 1'b1 inside a
    conditional AND assigned 1'b0 as a default at the top of an always block.
    """
    pulses: Set[str] = set()
    highs = {m.group(1) for m in PULSE_HIGH.finditer(src)}
    lows = {m.group(1) for m in PULSE_LOW.finditer(src)}
    # Classic pulse = assigned both 0 and 1 in the module
    for sig in highs & lows:
        pulses.add(sig)
    return pulses


def find_countdown_consumers(src: str, producers: Set[str]) -> List[Tuple[str, int]]:
    """
    Find places where a producer-pulse signal is read near an
    `if (<counter> == 0)` or similar countdown test.
    Returns list of (signal_name, line).
    """
    findings: List[Tuple[str, int]] = []
    # Find every `if (<x> == 0)` / `if (<x> == N)` gate
    for m in re.finditer(
        r'\bif\s*\(\s*(\w+)\s*==\s*(?:0|\d+\'?[bdh]?\d*)\s*\)',
        src
    ):
        counter = m.group(1)
        # Look ahead up to 400 chars for any use of a producer signal
        tail = src[m.end(): m.end() + 400]
        for sig in producers:
            if re.search(r'\b' + re.escape(sig) + r'\b', tail):
                # Skip if sig is being ASSIGNED (not read) in the branch
                assign_pat = re.compile(
                    r'\b' + re.escape(sig) + r'\s*<=(?!=)'
                )
                if assign_pat.search(tail):
                    continue
                # Heuristic: counter name looks like timer/cnt/wait
                if not re.search(r'(timer|cnt|count|wait|delay|tick)',
                                 counter, re.I):
                    continue
                lineno = src[:m.start()].count('\n') + 1
                findings.append((sig, lineno))
    return findings


def audit_file(path: Path, project_root: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        raw = path.read_text(errors='replace')
    except Exception:
        return findings
    src = strip_comments(raw)

    producers = find_pulse_producers(src)
    if not producers:
        return findings

    rel = str(path.relative_to(project_root)) if path.is_relative_to(project_root) else str(path)

    seen: Set[Tuple[str, int]] = set()
    for sig, lineno in find_countdown_consumers(src, producers):
        key = (sig, lineno)
        if key in seen:
            continue
        seen.add(key)
        findings.append(Finding(
            rule='POTENTIAL_HANDSHAKE_RACE',
            severity='ERROR',
            message=(f"pulse signal '{sig}' is read near a countdown gate — "
                     "pulse may fire while consumer is still counting. "
                     "Recommend latch-on-arrival: set a 'pending' flag the moment "
                     f"'{sig}' is seen, instead of re-checking it at end of wait."),
            file=rel,
            line=lineno,
        ))
    return findings


def audit(project_dir: str) -> AuditResult:
    root = Path(project_dir).resolve()
    result = AuditResult(program='handshake_check', passed=True)
    if not root.exists():
        result.findings.append(Finding(
            rule='PROJECT_DIR_MISSING', severity='ERROR',
            message=f"project_dir not found: {project_dir}"))
        result.passed = False
        result.summary = {'files_scanned': 0, 'violations': 1}
        return result

    files = find_rtl_files(root)
    for f in files:
        result.findings.extend(audit_file(f, root))

    result.passed = len(result.findings) == 0
    result.summary = {
        'files_scanned': len(files),
        'violations': len(result.findings),
    }
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    result = audit(args.project_dir)
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        for f in result.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity}] {f.rule} ({loc}): {f.message}")
        print(f"\n{'PASS' if result.passed else 'FAIL'} — {result.summary}")
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
