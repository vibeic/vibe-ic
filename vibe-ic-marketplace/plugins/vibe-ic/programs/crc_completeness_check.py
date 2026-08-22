#!/usr/bin/env python3
"""crc_completeness_check.py — deterministic compliance check derived from <chip-class> v040 debug.

Verifies that a CRC accumulator is fed EVERY byte that is transmitted, not just
the first/opcode byte. A classic bug: the opcode is fed to `crc_calc`, but
subsequent payload bytes are pushed into `tx_byte` without a matching
`crc_calc <= 1'b1` pulse, producing a correct header with a garbage CRC.

Heuristic:
  - Identify modules that both feed a CRC (signals named crc_calc / crc_data_in /
    crc_update / crc_en) AND emit tx bytes (signals named tx_byte / tx_data /
    tx_byte_valid).
  - For every place where the TX-byte strobe is asserted (e.g.
    `tx_byte_valid <= 1'b1;`), find the enclosing `begin ... end` block (i.e.
    the same case branch / if branch) and verify that a CRC-feed strobe is
    also asserted in the same scope.
  - Flag any TX strobe that has no accompanying CRC feed in the same scope.

Exit: 0 = PASS, 1 = FAIL.
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


# Patterns for CRC-feed strobes
CRC_FEED_NAMES = re.compile(
    r'\b(crc_calc|crc_data_in|crc_update|crc_en|crc_valid|crc_byte_valid)\b'
)
CRC_FEED_ASSERT = re.compile(
    r'\b(crc_calc|crc_update|crc_en|crc_valid|crc_byte_valid)\s*<=\s*1\'?b?1\b'
)
# Patterns for TX-byte emission strobes
TX_BYTE_NAMES = re.compile(r'\b(tx_byte|tx_data|tx_byte_valid|tx_valid)\b')
TX_BYTE_ASSERT = re.compile(
    r'\b(tx_byte_valid|tx_valid|tx_strobe)\s*<=\s*1\'?b?1\b'
)


def module_has_both(src: str) -> bool:
    return bool(CRC_FEED_NAMES.search(src) and TX_BYTE_NAMES.search(src))


def get_line_for_pos(src: str, pos: int) -> int:
    return src[:pos].count('\n') + 1


def enclosing_begin_block(src: str, pos: int) -> Tuple[int, int]:
    """
    Return (start, end) character offsets of the innermost `begin ... end`
    block that strictly contains `pos`. If no enclosing begin/end is found,
    fall back to a ±200 char window.
    """
    # Walk backward from pos, counting begin/end tokens
    before = src[:pos]
    begins = [m.start() for m in re.finditer(r'\bbegin\b', before)]
    ends = [m.start() for m in re.finditer(r'\bend\b(?!\w)(?!module)(?!case)(?!function)(?!task)(?!generate)', before)]
    depth = 0
    start = -1
    # Iterate combined events in order; track depth, remember innermost unmatched begin
    events = [(b, 'begin') for b in begins] + [(e, 'end') for e in ends]
    events.sort()
    stack = []
    for p, kind in events:
        if kind == 'begin':
            stack.append(p)
        else:
            if stack:
                stack.pop()
    if stack:
        start = stack[-1]
    # Walk forward from pos to find the matching end
    after = src[pos:]
    depth = 1
    end = -1
    for m in re.finditer(r'\b(begin|end)\b', after):
        if m.group(1) == 'begin':
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = pos + m.end()
                break
    if start == -1 or end == -1:
        return max(0, pos - 200), min(len(src), pos + 200)
    return start, end


def audit_file(path: Path, project_root: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        raw = path.read_text(errors='replace')
    except Exception:
        return findings
    src = strip_comments(raw)

    if not module_has_both(src):
        return findings

    rel = str(path.relative_to(project_root)) if path.is_relative_to(project_root) else str(path)

    # Module-level fallback: combinational CRC feed (`assign crc_data_in = tx_byte;`)
    combinational_crc_feed = bool(re.search(
        r'\bassign\s+(crc_data_in|crc_byte)\b\s*=\s*tx_byte\b', src
    ))

    for m in TX_BYTE_ASSERT.finditer(src):
        lineno = get_line_for_pos(src, m.start())
        # Determine enclosing begin/end scope (same case branch)
        blk_start, blk_end = enclosing_begin_block(src, m.start())
        scope = src[blk_start:blk_end]
        if CRC_FEED_ASSERT.search(scope):
            continue
        if combinational_crc_feed:
            continue
        findings.append(Finding(
            rule='TX_WITHOUT_CRC_FEED',
            severity='ERROR',
            message=(f"'{m.group(1)}' asserted without a CRC-feed strobe in the "
                     "same begin/end scope. Transmitted byte may be excluded "
                     "from CRC — producing a correct header with a wrong CRC."),
            file=rel,
            line=lineno,
        ))
    return findings


def audit(project_dir: str) -> AuditResult:
    root = Path(project_dir).resolve()
    result = AuditResult(program='crc_completeness_check', passed=True)
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
