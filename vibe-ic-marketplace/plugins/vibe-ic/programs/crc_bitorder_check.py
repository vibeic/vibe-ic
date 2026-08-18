#!/usr/bin/env python3
"""
crc_bitorder_check.py — Detect CRC bit-ordering mismatches in TX data loading.

A critical protocol compliance bug class: the CRC result is computed correctly,
but the bit order is wrong when loaded into the TX shift register. The receiver
computes the correct CRC over received bits, but the transmitted CRC has its
bits reversed, causing CRC validation failure on the far end.

During <half-duplex-tester> debugging (2026-04-16) we found:
  - Vendor TX_PHY bit-reverses CRC when loading into the shift register:
      tx_data_byte <= {crc8_result[0], crc8_result[1], ..., crc8_result[7]};
  - AI-generated TX_PHY used direct assignment:
      tx_data_byte <= crc8_result;
  This caused every packet's CRC to fail validation on the host receiver.

This program parses Verilog/SystemVerilog RTL and detects three CRC loading
patterns:

  1. DIRECT:   tx_reg <= crc_result;                         (no reversal)
  2. REVERSED: tx_reg <= {crc[0], crc[1], ..., crc[N-1]};   (bit-reversed concat)
  3. FUNCTION: tx_reg <= reverse_bits(crc);                  (reverse via function)
  4. PARTIAL:  tx_reg <= {crc[3:0], crc[7:4]};               (partial reorder)

Reports PASS if a CRC loading pattern is found, WARN if the pattern looks
ambiguous, or INFO if no CRC loading is detected (may mean the CRC signal
name is wrong or the file doesn't contain TX logic).

Usage:
    python3 crc_bitorder_check.py --rtl-files tx_phy.v --crc-signal crc8_result --out-dir /tmp/audit
    python3 crc_bitorder_check.py --rtl-files tx_phy.v mac.sv --crc-signal crc_out --out-dir /tmp/audit

Generality: works for ANY CRC-protected protocol TX module. Parameterized by
CRC signal name. Not tied to any specific protocol, CRC width, or IC.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class CrcLoadFinding:
    file: str
    line: int
    target_reg: str
    crc_signal: str
    loading_method: str   # DIRECT | REVERSED | FUNCTION | PARTIAL | UNKNOWN
    bit_order: str        # MSB_FIRST | LSB_FIRST | UNKNOWN
    raw_rhs: str          # the actual RHS text from the source
    status: str           # PASS | WARN
    message: str


@dataclass
class AuditReport:
    crc_signal: str
    files_scanned: List[str]
    findings: List[CrcLoadFinding]
    summary_status: str   # PASS | WARN | INFO
    summary_message: str


# ---------------------------------------------------------------------------
# Comment stripping (reuse pattern from rtl_hygiene_lint.py)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    """Remove // line comments and /* block */ comments, preserving newlines."""
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


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------
def find_crc_assignments(src: str, crc_signal: str, filepath: str) -> List[CrcLoadFinding]:
    """
    Find all assignments where `crc_signal` appears on the RHS and the LHS
    is a register/wire (potential TX data register).

    Returns a list of CrcLoadFinding with the detected loading method.
    """
    findings: List[CrcLoadFinding] = []
    lines = src.split('\n')
    crc_esc = re.escape(crc_signal)

    for lineno, line in enumerate(lines, start=1):
        # Skip lines where crc_signal is not present
        if crc_signal not in line:
            continue

        # Skip declarations (wire/reg/logic/input/output)
        if re.match(r'\s*(?:wire|reg|logic|input|output|inout)\b', line):
            continue

        # Match: target <= RHS;  or  target = RHS;  (procedural or continuous)
        # Also match: assign target = RHS;
        # Use re.search to handle lines with always/begin prefixes
        m = re.search(
            r'(?:^|\s|;)(?:assign\s+)?(\w+)(?:\s*\[[^\]]*\])?\s*(<=|=)\s*(.+?)\s*;',
            line)
        if not m:
            continue

        target = m.group(1)
        rhs = m.group(3).strip()

        # Skip if target is a Verilog keyword (e.g., 'always' captured by broad regex)
        _KEYWORDS = {
            'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
            'logic', 'assign', 'always', 'always_ff', 'always_comb',
            'always_latch', 'begin', 'end', 'if', 'else', 'case', 'endcase',
            'default', 'for', 'while', 'posedge', 'negedge', 'parameter',
            'localparam', 'integer', 'genvar', 'generate', 'endgenerate',
            'initial', 'function', 'endfunction', 'task', 'endtask',
        }
        if target in _KEYWORDS:
            continue

        # Check that the CRC signal actually appears in the RHS
        if not re.search(r'\b' + crc_esc + r'\b', rhs):
            continue

        # Skip self-assignments (CRC computation, not loading)
        if target == crc_signal:
            continue

        # Classify the loading method
        method, bit_order, status, message = classify_rhs(rhs, crc_signal)

        findings.append(CrcLoadFinding(
            file=filepath,
            line=lineno,
            target_reg=target,
            crc_signal=crc_signal,
            loading_method=method,
            bit_order=bit_order,
            raw_rhs=rhs,
            status=status,
            message=message,
        ))

    return findings


def classify_rhs(rhs: str, crc_signal: str) -> tuple:
    """
    Classify the RHS of an assignment that loads a CRC result.

    Returns: (loading_method, bit_order, status, message)
    """
    crc_esc = re.escape(crc_signal)

    # --- Pattern 1: DIRECT assignment ---
    # tx_reg <= crc_result;
    # tx_reg <= crc_result[7:0];  (slice but MSB:LSB order = no reversal)
    if re.match(r'^' + crc_esc + r'$', rhs.strip()):
        return (
            'DIRECT', 'MSB_FIRST', 'PASS',
            f"Direct assignment of {crc_signal} — no bit reversal applied. "
            "Verify this matches the protocol spec's expected CRC bit order on the wire."
        )

    # Direct with full-width MSB:LSB slice (no reversal)
    m = re.match(r'^' + crc_esc + r'\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]$', rhs.strip())
    if m:
        msb, lsb = int(m.group(1)), int(m.group(2))
        if msb > lsb:
            return (
                'DIRECT', 'MSB_FIRST', 'PASS',
                f"Direct slice [{msb}:{lsb}] — standard MSB:LSB order, no reversal."
            )
        else:
            return (
                'PARTIAL', 'UNKNOWN', 'WARN',
                f"Non-standard slice [{msb}:{lsb}] — LSB:MSB order is unusual. "
                "Check if this is intentional bit reversal."
            )

    # --- Pattern 2: BIT-REVERSED concatenation ---
    # tx_reg <= {crc[0], crc[1], crc[2], ..., crc[7]};
    # Detect: concatenation of individual bit selects in ascending order
    concat_m = re.match(r'^\{(.+)\}$', rhs.strip())
    if concat_m:
        inner = concat_m.group(1)
        bit_selects = re.findall(
            r'\b' + crc_esc + r'\s*\[\s*(\d+)\s*\]', inner)
        if bit_selects:
            indices = [int(b) for b in bit_selects]
            # Check if indices are ascending (0,1,2,...N = bit-reversed)
            if indices == sorted(indices) and len(indices) > 1:
                if indices[0] < indices[-1]:
                    return (
                        'REVERSED', 'LSB_FIRST', 'PASS',
                        f"Bit-reversed concatenation detected: indices {indices} "
                        f"(ascending = LSB-first = bit-reversed from standard [N:0] order). "
                        "This reverses the CRC bit order when loading into the TX register."
                    )
            # Check if indices are descending (N,N-1,...,0 = normal order)
            if indices == sorted(indices, reverse=True) and len(indices) > 1:
                return (
                    'DIRECT', 'MSB_FIRST', 'PASS',
                    f"Concatenation with descending indices {indices} "
                    f"— same as direct assignment (MSB-first, no reversal)."
                )
            # Partial reorder or non-standard permutation
            return (
                'PARTIAL', 'UNKNOWN', 'WARN',
                f"Non-standard bit permutation detected: indices {indices}. "
                "This is neither direct nor fully reversed — verify against protocol spec."
            )

        # Concatenation with slice ranges (e.g., {crc[3:0], crc[7:4]})
        slice_selects = re.findall(
            r'\b' + crc_esc + r'\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]', inner)
        if slice_selects:
            return (
                'PARTIAL', 'UNKNOWN', 'WARN',
                f"Concatenation with slice ranges detected: "
                f"{[(int(a), int(b)) for a, b in slice_selects]}. "
                "This is a partial reordering — verify against protocol spec."
            )

    # --- Pattern 3: FUNCTION-based reversal ---
    # tx_reg <= reverse_bits(crc_result);
    # tx_reg <= bit_reverse(crc_result);
    # tx_reg <= {<<{crc_result}};   (SystemVerilog streaming operator)
    reverse_funcs = [
        r'reverse_bits\s*\(\s*' + crc_esc + r'\s*\)',
        r'bit_reverse\s*\(\s*' + crc_esc + r'\s*\)',
        r'rev_bits\s*\(\s*' + crc_esc + r'\s*\)',
        r'reverse\s*\(\s*' + crc_esc + r'\s*\)',
        r'\{\s*<<\s*\{\s*' + crc_esc + r'\s*\}\s*\}',       # {<<{sig}}
        r'\{\s*<<\s*1\s*\{\s*' + crc_esc + r'\s*\}\s*\}',   # {<<1{sig}}
    ]
    for pat in reverse_funcs:
        if re.search(pat, rhs):
            return (
                'FUNCTION', 'LSB_FIRST', 'PASS',
                f"Bit-reversal via function/operator detected in: {rhs}. "
                "This reverses the CRC bit order when loading into the TX register."
            )

    # --- Pattern 4: Tilde / bitwise NOT (NOT a bit reversal, common confusion) ---
    if re.match(r'^~\s*' + crc_esc + r'$', rhs.strip()):
        return (
            'UNKNOWN', 'UNKNOWN', 'WARN',
            f"Bitwise NOT (~) applied to {crc_signal} — this is NOT bit reversal, "
            "it is bit inversion. If bit reversal was intended, this is a bug."
        )

    # --- Fallback: CRC signal present but pattern not recognized ---
    return (
        'UNKNOWN', 'UNKNOWN', 'WARN',
        f"CRC signal '{crc_signal}' found in RHS but loading pattern not recognized: "
        f"'{rhs}'. Manual review recommended."
    )


# ---------------------------------------------------------------------------
# Multi-line pattern support
# ---------------------------------------------------------------------------
def normalize_multiline_assignments(src: str) -> str:
    """
    Collapse multi-line assignments into single lines for simpler regex matching.
    Handles patterns like:
        tx_data <= {crc[0],
                    crc[1],
                    ...
                    crc[7]};
    """
    result = []
    accumulator = ""
    brace_depth = 0
    in_assignment = False

    for line in src.split('\n'):
        stripped = line.strip()

        if not in_assignment:
            # Check if this line starts an assignment
            if re.match(r'\s*(?:assign\s+)?\w+(?:\s*\[[^\]]*\])?\s*(<=|=)', stripped):
                accumulator = line
                brace_depth += line.count('{') - line.count('}')
                if ';' in stripped and brace_depth <= 0:
                    # Single-line assignment
                    result.append(accumulator)
                    accumulator = ""
                    brace_depth = 0
                elif ';' not in stripped or brace_depth > 0:
                    in_assignment = True
                else:
                    result.append(accumulator)
                    accumulator = ""
            else:
                result.append(line)
        else:
            # Continue accumulating
            accumulator += ' ' + stripped
            brace_depth += line.count('{') - line.count('}')
            if ';' in stripped and brace_depth <= 0:
                result.append(accumulator)
                accumulator = ""
                brace_depth = 0
                in_assignment = False

    if accumulator:
        result.append(accumulator)

    return '\n'.join(result)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------
def analyze_file(filepath: str, crc_signal: str) -> List[CrcLoadFinding]:
    """Analyze a single RTL file for CRC bit-order loading patterns."""
    path = Path(filepath)
    if not path.exists():
        return [CrcLoadFinding(
            file=filepath, line=0, target_reg='', crc_signal=crc_signal,
            loading_method='ERROR', bit_order='UNKNOWN', raw_rhs='',
            status='WARN', message=f"File not found: {filepath}",
        )]

    src = path.read_text(errors='replace')
    src = strip_comments(src)
    src = normalize_multiline_assignments(src)
    return find_crc_assignments(src, crc_signal, filepath)


def build_report(crc_signal: str, files: List[str],
                 all_findings: List[CrcLoadFinding]) -> AuditReport:
    """Build the final audit report from all findings."""
    if not all_findings:
        return AuditReport(
            crc_signal=crc_signal,
            files_scanned=files,
            findings=[],
            summary_status='INFO',
            summary_message=(
                f"No CRC loading pattern found for signal '{crc_signal}' in "
                f"{len(files)} file(s). Check that the --crc-signal name matches "
                "the actual signal name in the RTL, or that these files contain "
                "the TX data loading logic."
            ),
        )

    # Determine overall status
    statuses = [f.status for f in all_findings]
    methods = [f.loading_method for f in all_findings]

    if 'WARN' in statuses:
        summary_status = 'WARN'
    else:
        summary_status = 'PASS'

    # Check for conflicting loading methods across files
    unique_methods = set(m for m in methods if m not in ('UNKNOWN', 'ERROR'))
    if len(unique_methods) > 1:
        summary_status = 'WARN'
        summary_message = (
            f"Multiple CRC loading methods detected: {sorted(unique_methods)}. "
            "Inconsistent bit ordering across modules may cause protocol errors. "
            "All TX paths must use the same CRC bit order."
        )
    elif len(unique_methods) == 1:
        method = unique_methods.pop()
        if method == 'DIRECT':
            summary_message = (
                f"CRC signal '{crc_signal}' loaded via DIRECT assignment "
                f"(no bit reversal) in {len(all_findings)} location(s). "
                "Verify this matches the protocol spec's expected wire bit order."
            )
        elif method in ('REVERSED', 'FUNCTION'):
            summary_message = (
                f"CRC signal '{crc_signal}' loaded with BIT REVERSAL "
                f"({method}) in {len(all_findings)} location(s). "
                "Verify this matches the protocol spec's expected wire bit order."
            )
        elif method == 'PARTIAL':
            summary_message = (
                f"CRC signal '{crc_signal}' loaded with PARTIAL reordering "
                f"in {len(all_findings)} location(s). Manual review required."
            )
        else:
            summary_message = (
                f"CRC loading pattern for '{crc_signal}': {method}."
            )
    else:
        summary_message = (
            f"CRC signal '{crc_signal}' found but loading pattern could not "
            "be classified. Manual review required."
        )

    return AuditReport(
        crc_signal=crc_signal,
        files_scanned=files,
        findings=all_findings,
        summary_status=summary_status,
        summary_message=summary_message,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description='Detect CRC bit-ordering mismatches in TX data loading.')
    ap.add_argument('--rtl-files', required=True, nargs='+',
                    help='Verilog/SystemVerilog file(s) to analyze')
    ap.add_argument('--crc-signal', required=True,
                    help='Name of the CRC result signal (e.g., crc8_result)')
    ap.add_argument('--out-dir', required=True,
                    help='Output directory for JSON report')
    args = ap.parse_args()

    all_findings: List[CrcLoadFinding] = []
    for f in args.rtl_files:
        all_findings += analyze_file(f, args.crc_signal)

    report = build_report(args.crc_signal, args.rtl_files, all_findings)

    # Write JSON report
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / 'crc_bitorder_report.json'
    report_dict = asdict(report)
    report_path.write_text(json.dumps(report_dict, indent=2))

    # Console summary
    print(f"crc_bitorder_check: [{report.summary_status}] {report.summary_message}")
    print(f"  CRC signal : {report.crc_signal}")
    print(f"  Files      : {len(report.files_scanned)}")
    print(f"  Findings   : {len(report.findings)}")
    for f in report.findings:
        print(f"    {f.file}:{f.line} [{f.status}] {f.loading_method} "
              f"→ {f.target_reg} = {f.raw_rhs}")
    print(f"\nReport written to: {report_path}")

    # Exit code: 0 = PASS/INFO, 1 = WARN
    return 1 if report.summary_status == 'WARN' else 0


if __name__ == '__main__':
    sys.exit(main())
