#!/usr/bin/env python3
"""
phy_counter_audit.py — Detect bus-state-sampling anti-pattern in TX PHY counters.

Critical TX PHY design anti-pattern: using bus-state sampling (reading back the
bus to decide timing) instead of time-based counting (counting clock cycles
directly) for TX timing control.

Background (<half-duplex-tester> Apple Lightning debug, 2026-04-16):
  The AI-generated TX_PHY used `~id_bus_rx_syn2` (bus LOW) to gate the low
  counter and `id_bus_rx_syn2` (bus HIGH) to gate the high counter. The correct
  approach (vendor-verified) is to count clock cycles unconditionally during
  `tx_data_enable`, then switch from low counting to high counting only after the
  low count target is reached — never reading the bus to decide the switch.

  Bus-sampling creates:
    - Feedback loops: TX drives the bus, then reads it back to decide timing
    - Pull-up rise time dependency: bus LOW→HIGH transition time varies with
      capacitance, pull-up strength, and loading — making counting non-deterministic
    - Race conditions: sync latency means the readback is stale by N cycles

This tool:
  1. Parses Verilog/SystemVerilog RTL files
  2. Finds always blocks containing TX-related counter logic
  3. Checks if counter increment conditions reference bus read-back signals
  4. Flags WARNING for bus-state-gated counters with a time-based suggestion

Usage:
    python3 phy_counter_audit.py \\
        --rtl-files tx_phy.v mac_controller.sv \\
        --out-dir /tmp/audit

Generality: works for ANY TX PHY design (Lightning/AID, I2C, SPI, UART, etc.).
The bus-sampling anti-pattern applies wherever a transmitter reads its own bus
to time its drive — the correct approach is always time-based counting.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class Finding:
    file: str
    line: int
    severity: str       # WARNING / INFO / CLEAN
    rule: str           # bus-sampled-counter / time-based-counter
    signal: str         # the counter signal name
    bus_signal: str     # the bus readback signal used in gating (or "")
    context: str        # surrounding code snippet
    suggestion: str     # recommended fix


# ---------------------------------------------------------------------------
# Comment stripping (same approach as rtl_hygiene_lint.py)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    """Remove // line comments and /* block */ comments, preserving newlines."""
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


# ---------------------------------------------------------------------------
# Always-block extraction
# ---------------------------------------------------------------------------
def extract_always_blocks(src: str) -> List[dict]:
    """
    Extract always blocks from source, returning a list of dicts:
      { 'start_line': int, 'end_line': int, 'text': str }

    Handles `always @(...)`, `always_ff @(...)`, `always_comb`, `always_latch`.
    Uses begin/end balancing to find block boundaries.
    """
    blocks = []
    lines = src.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        # Match always block start
        if re.search(r'\balways(?:_ff|_comb|_latch)?\b', line):
            start = i
            # Find the begin/end scope
            depth = 0
            block_lines = []
            j = i
            found_begin = False
            while j < len(lines):
                block_lines.append(lines[j])
                # Count begin/end
                # Strip strings to avoid false matches inside string literals
                clean = re.sub(r'"[^"]*"', '', lines[j])
                begins = len(re.findall(r'\bbegin\b', clean))
                ends = len(re.findall(r'\bend\b', clean))
                depth += begins - ends
                if begins > 0:
                    found_begin = True
                if found_begin and depth <= 0:
                    break
                # Single-statement always (no begin): ends at semicolon
                if not found_begin and j > i and ';' in clean:
                    break
                j += 1
            blocks.append({
                'start_line': start + 1,  # 1-indexed
                'end_line': j + 1,
                'text': '\n'.join(block_lines),
            })
            i = j + 1
        else:
            i += 1
    return blocks


# ---------------------------------------------------------------------------
# TX counter detection
# ---------------------------------------------------------------------------
# Keywords that indicate a counter is TX-related
TX_COUNTER_PATTERNS = [
    r'tx_low',
    r'tx_high',
    r'low_cnt',
    r'high_cnt',
    r'tx_cnt',
    r'tx_count',
    r'low_count',
    r'high_count',
    r'bit_low',
    r'bit_high',
    r'drive_low',
    r'drive_high',
    r'tx_timer',
    r'tx_bit_cnt',
    r'tx_bit_count',
    r'lo_cnt',
    r'hi_cnt',
    r'lo_count',
    r'hi_count',
]

TX_COUNTER_RE = re.compile(
    r'\b(' + '|'.join(TX_COUNTER_PATTERNS) + r')\b', re.IGNORECASE
)

# Broader TX context indicators (block must have at least one of these
# besides the counter name to confirm it's TX-related)
TX_CONTEXT_PATTERNS = re.compile(
    r'\b(tx_|transmit|tx_data|tx_phy|tx_en|tx_busy|tx_active|'
    r'tx_state|tx_oe|tx_drive|tx_data_enable|data_enable|'
    r'drive_bus|bus_drive|bus_oe)\b', re.IGNORECASE
)

# Bus readback signals — the anti-pattern is gating counter increments
# on these instead of counting clock cycles unconditionally
BUS_READBACK_PATTERNS = [
    r'bus_in',
    r'bus_rx',
    r'bus_sample',
    r'bus_read',
    r'bus_readback',
    r'bus_state',
    r'bus_level',
    r'bus_val',
    r'bus_sampled',
    r'sda_in',          # I2C readback
    r'scl_in',          # I2C readback
    r'miso',            # SPI readback
    r'mosi_in',         # SPI readback
    r'rx_data_in',
    r'rxd_sync',
    r'rx_sync',
    r'rx_syn',
    r'din_sync',
    r'line_state',
]

BUS_READBACK_RE = re.compile(
    r'\b(' + '|'.join(BUS_READBACK_PATTERNS) + r'(?:\w*)?)\b', re.IGNORECASE
)


def find_counter_increments(block_text: str, counter_name: str) -> List[dict]:
    """
    Find lines where counter_name is incremented or loaded, returning
    the condition context (the if/else-if branch guarding the increment).

    Returns list of:
      { 'line_offset': int, 'line_text': str, 'condition': str }
    """
    increments = []
    lines = block_text.split('\n')
    # Pattern: counter <= counter + 1  or  counter = counter + 1  or
    #          counter <= value  (load)
    inc_re = re.compile(
        r'\b' + re.escape(counter_name) + r'\s*(?:<=|=)\s*'
        r'(?:' + re.escape(counter_name) + r'\s*[\+\-]|'  # cnt <= cnt +/- ...
        r'[^;]*)',                                          # cnt <= <expr>
        re.IGNORECASE
    )
    # Track the most recent if/else-if condition
    current_condition = ""
    for offset, line in enumerate(lines):
        stripped = line.strip()
        # Track conditions
        cond_match = re.match(r'(?:end\s+)?(?:else\s+)?if\s*\((.+?)\)', stripped)
        if cond_match:
            current_condition = cond_match.group(1)
        elif re.match(r'\belse\b', stripped):
            current_condition = "(else)"
        if inc_re.search(line):
            increments.append({
                'line_offset': offset,
                'line_text': stripped,
                'condition': current_condition,
            })
    return increments


def check_bus_sampling_in_condition(condition: str) -> Optional[str]:
    """
    Check if a condition string references bus readback signals.
    Returns the matched bus signal name, or None if clean.
    """
    m = BUS_READBACK_RE.search(condition)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------
def audit_file(filepath: Path) -> List[Finding]:
    """
    Audit a single Verilog/SystemVerilog file for bus-sampling counter
    anti-patterns.
    """
    findings: List[Finding] = []
    src = filepath.read_text(errors='replace')
    src_clean = strip_comments(src)
    blocks = extract_always_blocks(src_clean)

    for block in blocks:
        text = block['text']

        # Find TX counter names in this block
        counter_matches = TX_COUNTER_RE.findall(text)
        if not counter_matches:
            continue

        # Deduplicate
        counter_names = list(dict.fromkeys(counter_matches))

        for counter_name in counter_names:
            increments = find_counter_increments(text, counter_name)
            if not increments:
                continue

            found_bus_sampling = False
            for inc in increments:
                bus_sig = check_bus_sampling_in_condition(inc['condition'])
                if bus_sig:
                    found_bus_sampling = True
                    # Extract a few lines around the increment for context
                    block_lines = text.split('\n')
                    start_ctx = max(0, inc['line_offset'] - 2)
                    end_ctx = min(len(block_lines), inc['line_offset'] + 3)
                    context_snippet = '\n'.join(
                        block_lines[start_ctx:end_ctx]).strip()

                    findings.append(Finding(
                        file=str(filepath),
                        line=block['start_line'] + inc['line_offset'],
                        severity='WARNING',
                        rule='bus-sampled-counter',
                        signal=counter_name,
                        bus_signal=bus_sig,
                        context=context_snippet,
                        suggestion=(
                            f"Counter '{counter_name}' increment is gated by "
                            f"bus readback signal '{bus_sig}'. This creates a "
                            f"feedback loop: TX drives the bus, then reads it "
                            f"back to decide timing. Use time-based counting "
                            f"instead — count clock cycles unconditionally "
                            f"during tx_data_enable, then switch from low to "
                            f"high counting when the low count target is "
                            f"reached (not when the bus state changes)."
                        ),
                    ))

            if not found_bus_sampling and increments:
                # This counter uses time-based counting — report as clean
                findings.append(Finding(
                    file=str(filepath),
                    line=block['start_line'] + increments[0]['line_offset'],
                    severity='CLEAN',
                    rule='time-based-counter',
                    signal=counter_name,
                    bus_signal='',
                    context=increments[0]['line_text'],
                    suggestion='',
                ))

    return findings


def generate_report(all_findings: List[Finding]) -> dict:
    """Generate a structured JSON report from all findings."""
    warnings = [f for f in all_findings if f.severity == 'WARNING']
    clean = [f for f in all_findings if f.severity == 'CLEAN']

    return {
        'tool': 'phy_counter_audit',
        'version': '1.0.0',
        'summary': {
            'total_counters_analyzed': len(all_findings),
            'bus_sampled_warnings': len(warnings),
            'time_based_clean': len(clean),
            'verdict': 'FAIL' if warnings else 'PASS',
        },
        'findings': [asdict(f) for f in all_findings],
        'guidance': {
            'anti_pattern': (
                'Bus-state sampling: TX counter increment gated by bus '
                'readback (e.g., if (~bus_rx) low_cnt <= low_cnt + 1). '
                'The bus value depends on pull-up rise time, loading, and '
                'sync latency — making timing non-deterministic.'
            ),
            'correct_pattern': (
                'Time-based counting: counter increments unconditionally '
                'during tx_data_enable. Switch from low phase to high phase '
                'when low_cnt reaches the target count, not when the bus '
                'state changes. Example: if (low_cnt < TARGET) low_cnt <= '
                'low_cnt + 1; else high_cnt <= high_cnt + 1;'
            ),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description=(
            'Detect bus-state-sampling anti-pattern in TX PHY counters. '
            'Flags TX counters whose increment is gated by bus readback '
            'signals instead of unconditional time-based counting.'
        ))
    ap.add_argument('project', nargs='?', default=None,
                    help='Optional project dir; auto-derives --rtl-files from '
                         '<project>/rtl/*.{v,sv} and --out-dir from '
                         '<project>/reports/. SKIP rc=0 if rtl/ empty.')
    ap.add_argument('--rtl-files', nargs='+',
                    help='Verilog/SystemVerilog files to audit')
    ap.add_argument('--out-dir',
                    help='Directory for JSON report output')
    args = ap.parse_args()

    # v1.6.7: positional <project> auto-derive (dead-wire fix)
    if args.project is not None:
        proj = Path(args.project)
        if not args.rtl_files:
            rtl_dir = proj / 'rtl'
            globbed = sorted(list(rtl_dir.glob('*.v')) + list(rtl_dir.glob('*.sv')))
            if not globbed:
                skip_report = {
                    'verdict': 'SKIP',
                    'reason': f'no RTL files in {rtl_dir}/',
                    'pass': True,
                }
                print(json.dumps(skip_report, indent=2))
                return 0
            args.rtl_files = [str(p) for p in globbed]
        if not args.out_dir:
            args.out_dir = str(proj / 'reports')

    if not args.rtl_files:
        ap.error('--rtl-files is required when no <project> positional given')
    if not args.out_dir:
        ap.error('--out-dir is required when no <project> positional given')

    all_findings: List[Finding] = []
    for f in args.rtl_files:
        p = Path(f)
        if not p.exists():
            print(f"WARNING: file not found: {f}", file=sys.stderr)
            continue
        try:
            all_findings += audit_file(p)
        except Exception as e:
            print(f"ERROR parsing {f}: {e}", file=sys.stderr)
            return 2

    report = generate_report(all_findings)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_file = out / 'phy_counter_audit_report.json'
    report_file.write_text(json.dumps(report, indent=2))

    # Console summary
    warnings = report['summary']['bus_sampled_warnings']
    clean = report['summary']['time_based_clean']
    verdict = report['summary']['verdict']
    print(f"phy_counter_audit: {warnings} bus-sampled warnings, "
          f"{clean} time-based clean")
    print("-" * 70)
    for fd in all_findings:
        if fd.severity == 'WARNING':
            print(f"{fd.file}:{fd.line}: [{fd.severity}] {fd.rule}: "
                  f"counter '{fd.signal}' gated by bus signal '{fd.bus_signal}'")
            print(f"  Suggestion: {fd.suggestion}")
        elif fd.severity == 'CLEAN':
            print(f"{fd.file}:{fd.line}: [CLEAN] {fd.rule}: "
                  f"counter '{fd.signal}' — time-based (OK)")
    print("-" * 70)
    print(f"Verdict: {verdict}")
    print(f"Report: {report_file}")

    return 1 if warnings > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
