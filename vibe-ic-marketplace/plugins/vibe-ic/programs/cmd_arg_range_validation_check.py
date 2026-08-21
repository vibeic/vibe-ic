#!/usr/bin/env python3
"""
cmd_arg_range_validation_check.py — M4: Verify that command argument fields
(address, length, channel, etc.) are explicitly bounds-checked before use,
not silently truncated via bit-slicing.

General pattern (IC-agnostic):

    When a command carries a numeric argument (memory address, read length,
    channel index, register offset), the dispatcher must explicitly compare
    the argument against its valid range and reject out-of-range values.

    Silent truncation via Verilog bit-slicing — e.g. ``addr <= cmd[6:0]``
    when the field is 8 bits — is the canonical anti-pattern: it maps
    out-of-range values into the valid range without signaling an error,
    producing silently wrong behavior (wrap-around reads, aliased writes).

    Correct implementations compare first, then slice:
        if (cmd_arg > MAX) reject;
        else addr <= cmd_arg[6:0];

Static heuristic check.  Scans RTL for:
  - Dispatcher modules with opcode case/if blocks
  - Bit-sliced assignments from command buffer to address/length/index signals
  - Presence (or absence) of a bounds comparison before the slice

Usage:
    python3 cmd_arg_range_validation_check.py --rtl-dir <dir> [--json <report.json>]

Exit: 0 = PASS, 1 = findings, 2 = IO error.

#496 — DENOMINATOR DISCLOSURE
----------------------------
This gate's summary used to carry only ``pass`` / ``findings_count`` /
``dispatcher_files`` / ``truncations``, so a reader could not tell whether a
PASS meant "the dispatchers are clean" or "the rule was never applied". It was
the second. Measured over the 107 tracked ``rtl`` directories under
``benchmark-data``: 4 files in 4 directories are recognised as dispatchers, and
**0 of them** reach the body of the rule, because the rule additionally needs a
command-buffer signal AND a range-checkable target signal in the same file, and
no dispatcher in the corpus has the command-buffer half.

Note that ``dispatcher_files`` is NOT the denominator, even though it is the
only count the gate published and it is non-zero. Publishing it as though it
were would have overstated coverage 4-to-0. The denominator is the number of
files the truncation rule was actually applied to, and it is disclosed as such.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

import _gate_denominator as GD


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    details: str = ""


DISPATCH_RE = re.compile(
    r'\bcase[szx]?\s*\(\s*(?:\w+\.)?'
    r'(cmd_op|opcode|cmd|op|cmd_code|rx_cmd|cmd_byte)\b',
    re.IGNORECASE,
)

IF_CMD_RE = re.compile(
    r'\bif\s*\(\s*\w*(?:cmd|opcode)\w*\s*==\s*',
    re.IGNORECASE,
)

TARGET_SIGNALS = re.compile(
    r'\b(\w*addr\w*|\w*address\w*|\w*adr\w*|\w*offset\w*|'
    r'\w*base\w*|\w*index\w*|\w*idx\w*|'
    r'\w*length\w*|\w*len\w*|\w*count\w*|\w*cnt\w*|'
    r'\w*channel\w*|\w*ch_sel\w*|\w*page\w*)\b',
    re.IGNORECASE,
)

CMD_BUF_RE = re.compile(
    r'\b(cmd_buf|rx_buf|cmd_data|rx_data|pkt_buf|rx_payload)\b',
    re.IGNORECASE,
)

BIT_SLICE_RE = re.compile(
    r'\b(cmd_buf|rx_buf|cmd_data|rx_data|pkt_buf|rx_payload)'
    r'\s*\[\s*\d+\s*\]'
    r'\s*\[\s*(\d+)\s*:\s*0\s*\]',
    re.IGNORECASE,
)

BIT_SLICE_DIRECT_RE = re.compile(
    r'\b(cmd_buf|rx_buf|cmd_data|rx_data|pkt_buf|rx_payload)'
    r'\s*\[\s*\d+\s*\]\s*\[\s*(\d+)\s*:\s*0\s*\]',
    re.IGNORECASE,
)

BOUNDS_CHECK_RE = re.compile(
    r'(\w*addr\w*|\w*address\w*|\w*adr\w*|\w*offset\w*|'
    r'\w*base\w*|\w*index\w*|\w*idx\w*|'
    r'\w*length\w*|\w*len\w*|\w*count\w*|\w*cnt\w*|'
    r'\w*channel\w*|\w*ch_sel\w*|\w*page\w*|'
    r'cmd_buf\s*\[\s*\d+\s*\]|rx_buf\s*\[\s*\d+\s*\])'
    r'\s*(?:>|>=|<=|<)\s*'
    r'(?:\d+|\w+_MAX|\w+_LIMIT|\w+_SIZE|\w+_DEPTH|'
    r"\d*'[hbdHBD][0-9a-fA-F_]+)",
    re.IGNORECASE,
)

MSB_CHECK_RE = re.compile(
    r'(cmd_buf|rx_buf|cmd_data|rx_data|pkt_buf|rx_payload)'
    r'\s*\[\s*\d+\s*\]\s*\[\s*7\s*\]',
    re.IGNORECASE,
)

# #496 — one unit of this gate's denominator, in the gate's own terms.
_DENOM_UNIT = ("dispatcher files carrying both a command buffer and a "
               "range-checkable argument signal")


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        p for p in rtl_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".v", ".sv")
    )


def _strip_comments(src: str) -> str:
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i + 2)
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


def _denominator(examined: int, considered: int,
                 no_cmd_buf: int, no_target: int) -> GD.Denominator:
    """Say what the truncation rule was applied to, and why not more."""
    if examined:
        return GD.Denominator(unit=_DENOM_UNIT, examined=examined,
                              considered=considered)
    if considered == 0:
        reason = ("no file contains a command dispatcher — searched for a "
                  "`case (cmd/opcode/...)` statement or 3+ `if (cmd == ...)` "
                  "comparisons. Nothing in this RTL decodes a command, so the "
                  "argument-truncation rule has no subject here.")
    else:
        reason = (
            f"{considered} dispatcher file(s) found, but none also carries the "
            "two signals the rule needs: a command buffer "
            "(cmd_buf/rx_buf/cmd_data/rx_data/pkt_buf/rx_payload) and a "
            "range-checkable target (addr/offset/index/length/count/channel/"
            f"page). {no_cmd_buf} lacked the command buffer, {no_target} "
            "lacked a target signal. The dispatchers here decode commands "
            "that carry no numeric argument to bounds-check.")
    return GD.Denominator(unit=_DENOM_UNIT, examined=0, considered=considered,
                          not_applicable_reason=reason)


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding("ERROR", "IO", f"RTL directory not found: {rtl_dir}"))
        return findings, GD.attach({}, GD.Denominator(
            unit=_DENOM_UNIT, examined=0, considered=0,
            not_applicable_reason=(
                f"RTL directory not found: {rtl_dir} — nothing was read, so "
                "this result is an input error, not a verdict.")))

    dispatcher_files: List[str] = []
    truncations_found: List[Dict] = []
    examined = 0
    no_cmd_buf = 0
    no_target = 0

    for p in _find_v_files(rtl_dir):
        try:
            text = _strip_comments(p.read_text(errors="replace"))
        except OSError:
            continue
        fname = str(p)

        is_dispatcher = bool(DISPATCH_RE.search(text)) or \
            len(IF_CMD_RE.findall(text)) >= 3
        if not is_dispatcher:
            continue
        dispatcher_files.append(fname)

        has_cmd_buf = bool(CMD_BUF_RE.search(text))
        has_target = bool(TARGET_SIGNALS.search(text))
        if not (has_cmd_buf and has_target):
            # #496 — count WHY the rule stopped. A dispatcher that never
            # reaches the rule body is not evidence that the rule passed.
            if not has_cmd_buf:
                no_cmd_buf += 1
            if not has_target:
                no_target += 1
            continue
        examined += 1

        lines = text.split('\n')
        has_any_bounds = bool(BOUNDS_CHECK_RE.search(text)) or \
            bool(MSB_CHECK_RE.search(text))

        for lineno, line in enumerate(lines, 1):
            if not TARGET_SIGNALS.search(line):
                continue
            if not re.search(r'<=', line):
                continue
            if not CMD_BUF_RE.search(line):
                continue

            slice_m = BIT_SLICE_DIRECT_RE.search(line)
            if not slice_m:
                continue

            hi_bit = int(slice_m.group(2))
            if hi_bit >= 7:
                continue

            ctx_start = max(0, lineno - 15)
            ctx_end = min(len(lines), lineno + 2)
            context_block = '\n'.join(lines[ctx_start:ctx_end])

            local_bounds = bool(BOUNDS_CHECK_RE.search(context_block)) or \
                bool(MSB_CHECK_RE.search(context_block))

            if not local_bounds:
                truncations_found.append({
                    "file": fname, "line": lineno,
                    "code": line.strip(), "hi_bit": hi_bit,
                })
                findings.append(Finding(
                    "ERROR", "SILENT_TRUNCATION",
                    f"Command argument is bit-sliced to [{hi_bit}:0] "
                    f"(loses upper bits) with no bounds comparison in "
                    f"the preceding 15 lines. Out-of-range values will "
                    f"silently wrap instead of being rejected. Add an "
                    f"explicit comparison (e.g. 'if (arg > MAX) drop') "
                    f"before the bit-slice assignment.",
                    file=fname, line=lineno,
                    details=line.strip(),
                ))

    summary: Dict = {
        "dispatcher_files": dispatcher_files,
        "truncations": truncations_found,
    }
    GD.attach(summary, _denominator(examined, len(dispatcher_files),
                                    no_cmd_buf, no_target))
    return findings, summary


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Detect silent bit-truncation of command arguments "
                    "without bounds validation."
    )
    ap.add_argument("--rtl-dir", required=True)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    is_pass = not any(f.severity == "ERROR" for f in findings)
    report = {
        "program": "cmd_arg_range_validation_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {"pass": is_pass, "findings_count": len(findings), **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(out)
    print(out)
    if any(f.category == "IO" for f in findings):
        return 2
    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
