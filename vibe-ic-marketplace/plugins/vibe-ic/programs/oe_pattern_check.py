#!/usr/bin/env python3
"""
oe_pattern_check.py — Analyze output-enable (OE) patterns for tristate bus drivers.

Parses Verilog/SystemVerilog RTL and classifies every OE signal into one of four
pattern types, each with a distinct risk profile:

  1. COMBINATIONAL — OE driven by combinational logic (no register).
     Risk: HIGH. Combinational OE is susceptible to glitches on every input
     transition. Any hazard on the enable path can momentarily tri-state the
     bus, causing bus contention or data corruption.

  2. SINGLE_EDGE — OE registered on one clock edge only (posedge or negedge).
     Risk: MEDIUM. Safe against combinational glitches, but during the half-
     cycle between the registering edge and the opposite edge, the OE and data
     outputs may disagree, creating a brief window where the bus is driven
     with stale data or the driver turns on/off at the wrong time.

  3. DUAL_EDGE — OE uses separate posedge and negedge registers, combined
     with AND/OR logic. Both edges must agree before OE changes state.
     Risk: LOW. This is the vendor-quality pattern found in the <half-duplex-tester> TX_PHY:
       tx_oe_pos (posedge) & tx_oe_neg (negedge) for H1 bits.
     Eliminates glitch windows because the output only transitions when both
     edge-domain registers agree.

  4. GATED — OE is conditionally enabled/disabled based on data bit position
     or other qualifying signals. Example: vendor H1 bits use dual-edge OE,
     H0 bits use posedge-only OE.
     Risk: INFO. Not inherently bad, but the gating condition must be verified
     to ensure all bit positions are covered. Missing bits → floating bus lines.

Background:
  During <half-duplex-tester> debugging (2026-04-16), the vendor TX_PHY used a dual-edge OE
  pattern (tx_oe_pos & tx_oe_neg) for glitch-free enable control. The AI-
  generated version initially used SINGLE_EDGE, causing half-cycle timing issues
  on the bidirectional bus.

Usage:
    python3 oe_pattern_check.py --rtl-files tx_phy.v rx_phy.v --out-dir /tmp/audit
    python3 oe_pattern_check.py --rtl-files *.v --out-dir /tmp/audit --verbose

Output:
    /tmp/audit/oe_pattern_report.json — structured findings for each OE signal.

Generality: works for ANY tristate bus driver in ANY IC. Identifies OE signals
by naming convention (*_oe_*, *_oen_*, *_oeb_*, *tri_en*, etc.) and by usage
in tristate assign patterns (assign bus = oe ? data : {W{1'bz}}).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Set, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class OESignal:
    name: str
    file: str
    decl_line: int
    pattern: str        # COMBINATIONAL | SINGLE_EDGE | DUAL_EDGE | GATED
    risk: str           # HIGH | MEDIUM | LOW | INFO
    edges: List[str]    # e.g. ["posedge"] or ["posedge", "negedge"]
    gating_condition: str = ""
    recommendation: str = ""
    details: str = ""


@dataclass
class OEReport:
    files_analyzed: List[str]
    total_oe_signals: int
    signals: List[OESignal]
    summary: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Comment stripper (reused pattern from rtl_hygiene_lint.py)
# ---------------------------------------------------------------------------
def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, preserving newlines for line tracking."""
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
# OE signal discovery
# ---------------------------------------------------------------------------
# Naming patterns that indicate an output-enable signal
OE_NAME_PATTERNS = [
    re.compile(r'\b\w*_oe\b'),
    re.compile(r'\b\w*_oe_\w+\b'),
    re.compile(r'\boe_\w+\b'),
    re.compile(r'\b\w*_oen\b'),
    re.compile(r'\b\w*_oen_\w+\b'),
    re.compile(r'\b\w*_oeb\b'),
    re.compile(r'\b\w*_oeb_\w+\b'),
    re.compile(r'\b\w*tri_en\w*\b'),
    re.compile(r'\b\w*tristate_en\w*\b'),
    re.compile(r'\b\w*bus_en\w*\b'),
    re.compile(r'\b\w*drv_en\w*\b'),
]

# Combined regex for matching any OE-like identifier
OE_NAME_RE = re.compile(
    r'\b(\w*(?:_oe(?:_\w+)?|_oen(?:_\w+)?|_oeb(?:_\w+)?|'
    r'tri_en\w*|tristate_en\w*|bus_en\w*|drv_en\w*)\w*)\b',
    re.IGNORECASE
)


#: Infixes that carry their own left boundary: the leading '_' IS the token
#: separator, so a bare substring test is already anchored.
_OE_SELF_ANCHORED_INFIXES = ('_oe_', '_oen_', '_oeb_')

#: Infixes that do NOT carry a left boundary. These must match at an
#: underscore-delimited token boundary — see `_infix_at_token_boundary`.
_OE_TOKEN_INFIXES = ('tri_en', 'tristate_en', 'bus_en', 'drv_en')


def _infix_at_token_boundary(low: str, infix: str) -> bool:
    """True when `infix` occurs in `low` starting at an underscore-delimited
    token boundary — the start of the identifier, or just after a '_'.

    WHY THIS IS NOT A BARE SUBSTRING TEST. The unanchored infixes name a BUS
    ('bus_en' = "the bus output-enable"), and a bare `in` test also matches
    every identifier whose token merely ENDS in those letters: 'bus_en' is a
    substring of 'dbus_en', 'ibus_en', 'sbus_en', 'abus_en'. Those decompose as
    dbus/ibus/sbus/abus + '_en' — a data/instruction/system bus REQUEST enable,
    which is an ordinary synchronous control signal, not an output-enable
    driving a tristate. Measured: on a RISC-V core with ZERO tristate drivers
    (no `inout`, no high-Z literal anywhere in 25 files) the bare test reported
    4 findings, 3 of them HIGH "must be registered to avoid glitches", and
    exited 1 — including on an INPUT PORT, which by construction is driven from
    outside the module. Anchoring drops exactly those and keeps every genuine
    OE: 'bus_en', 'io_bus_en', 'wb_bus_en' still match, and the '_oe'/'_oen'/
    '_oeb' suffix rule that catches the real-world 3-wire pad convention
    ('gpio_oe', 'mdio_oe') is untouched.

    A name rule can only ever be a heuristic, so this deliberately does NOT
    carry the whole gate: `find_oe_declarations` ALSO discovers OE signals
    STRUCTURALLY from `assign bus = oe ? data : 'bz`, which is name-independent.
    An identifier this rule now declines still reaches the report when it
    actually drives a tristate — asserted by the reverse control in
    `tests/test_oe_pattern_check_token_boundary.py`.
    """
    start = 0
    while True:
        i = low.find(infix, start)
        if i < 0:
            return False
        if i == 0 or low[i - 1] == '_':
            return True
        start = i + 1


def is_oe_name(name: str) -> bool:
    """Check if an identifier looks like an output-enable signal by name."""
    low = name.lower()
    # Direct match patterns
    suffixes = ('_oe', '_oen', '_oeb')
    if any(low.endswith(s) for s in suffixes):
        return True
    if any(low.startswith(s.lstrip('_') + '_') for s in suffixes):
        return True
    # Infix patterns
    if any(s in low for s in _OE_SELF_ANCHORED_INFIXES):
        return True
    if any(_infix_at_token_boundary(low, s) for s in _OE_TOKEN_INFIXES):
        return True
    # Exact match
    if low in ('oe', 'oen', 'oeb'):
        return True
    return False


def find_oe_declarations(src: str, filepath: str) -> List[Dict]:
    """
    Find all declared signals whose names match OE patterns.
    Scans both module port declarations AND body declarations.
    Returns list of dicts: {name, line, kind}.
    """
    results = []
    lines = src.split('\n')
    seen = set()

    # Regex uses finditer so it works when the declaration appears mid-line
    # (e.g. "module m(input a, output wire pad_oe);")
    decl_re = re.compile(
        r'(?:input|output|inout)?\s*'
        r'(wire|reg|logic)\s+'
        r'(?:(?:signed|unsigned)\s+)?'
        r'(?:\[[^\]]+\]\s*)?'
        r'(?:\[[^\]]+\]\s*)?'
        r'(\w+)')

    for lineno, line in enumerate(lines, start=1):
        for m in decl_re.finditer(line):
            kind = m.group(1)
            name = m.group(2)
            if name and is_oe_name(name) and name not in seen:
                seen.add(name)
                results.append({'name': name, 'line': lineno, 'kind': kind})

    # Also find OE signals from tristate assign patterns:
    #   assign bus = oe_sig ? data : {W{1'bz}};
    for m in re.finditer(
            r'\bassign\s+\w+\s*=\s*(\w+)\s*\?\s*\w+\s*:\s*'
            r'(?:\{?\s*\d+\s*\{?\s*1\'bz\s*\}?\s*\}?|\d+\'bz)',
            src):
        sig = m.group(1)
        if sig not in seen:
            seen.add(sig)
            pos = src[:m.start()].count('\n') + 1
            results.append({'name': sig, 'line': pos, 'kind': 'inferred'})

    return results


# ---------------------------------------------------------------------------
# Edge analysis: determine which clock edges register a signal
# ---------------------------------------------------------------------------
def find_always_blocks(src: str) -> List[Dict]:
    """
    Parse always blocks and return list of dicts:
      {edge: "posedge"|"negedge"|"comb", clk: str|None, start_line: int, body: str}
    """
    blocks = []
    # Match: always @(posedge clk) or always @(negedge clk) or always @(*)
    pattern = re.compile(
        r'\balways(?:_ff|_comb|_latch)?\s*@\s*\('
        r'(posedge|negedge)?\s*(\w+)?'
        r'[^)]*\)',
        re.DOTALL
    )
    for m in pattern.finditer(src):
        edge = m.group(1) or 'comb'
        clk = m.group(2)
        start = src[:m.start()].count('\n') + 1

        # Extract body: find matching begin/end or single statement
        rest = src[m.end():]
        body = _extract_block_body(rest)
        blocks.append({
            'edge': edge,
            'clk': clk,
            'start_line': start,
            'body': body,
        })

    return blocks


def _extract_block_body(text: str) -> str:
    """Extract the body of an always block (handles begin/end nesting)."""
    stripped = text.lstrip()
    if stripped.startswith('begin'):
        depth = 0
        i = 0
        while i < len(text):
            # Check for 'begin' keyword (not inside an identifier)
            if text[i:i+5] == 'begin' and (i == 0 or not text[i-1].isalnum()):
                after = i + 5
                if after >= len(text) or not text[after].isalnum():
                    depth += 1
            if text[i:i+3] == 'end' and (i == 0 or not text[i-1].isalnum()):
                after = i + 3
                if after >= len(text) or not text[after].isalnum():
                    depth -= 1
                    if depth == 0:
                        return text[:after + 3]
            i += 1
        return text  # fallback: return everything
    else:
        # Single statement — find the next semicolon
        semi = text.find(';')
        if semi >= 0:
            return text[:semi + 1]
        return text


def classify_oe_signal(name: str, src: str, filepath: str,
                       always_blocks: List[Dict]) -> OESignal:
    """
    Classify a single OE signal into one of the four pattern types.
    """
    decl_line = 1
    # Find declaration line
    dm = re.search(
        r'\b(?:wire|reg|logic|input|output|inout)\s+'
        r'(?:(?:signed|unsigned)\s+)?'
        r'(?:\[[^\]]+\]\s*)?'
        r'(?:\w+\s*,\s*)*' + re.escape(name) + r'\b',
        src)
    if dm:
        decl_line = src[:dm.start()].count('\n') + 1

    # Determine which edges register this signal
    edges_found = set()
    registered = False
    for blk in always_blocks:
        # Check if this signal is assigned (LHS) in this block
        lhs_pattern = re.compile(
            r'\b' + re.escape(name) + r'\b\s*(?:\[[^\]]+\]\s*)?(?:<=|=)(?!=)')
        if lhs_pattern.search(blk['body']):
            if blk['edge'] in ('posedge', 'negedge'):
                edges_found.add(blk['edge'])
                registered = True
            elif blk['edge'] == 'comb':
                # Assigned in combinational always block
                pass

    # Check continuous assign (combinational)
    assign_lhs = re.compile(
        r'\bassign\s+' + re.escape(name) + r'\b\s*(?:\[[^\]]+\]\s*)?=')
    is_continuous_assign = bool(assign_lhs.search(src))

    # Check for gating: OE depends on a conditional related to bit index or
    # data-dependent conditions.
    gating = _detect_gating(name, src, always_blocks)

    # Classification logic
    edges_list = sorted(edges_found)

    if gating:
        pattern = 'GATED'
        risk = 'INFO'
        recommendation = (
            f"OE signal '{name}' is conditionally gated by '{gating}'. "
            "Verify that all bit positions / conditions are covered to avoid "
            "floating bus lines. The gating pattern itself is not dangerous if "
            "the condition is registered."
        )
        details = f"Gating condition: {gating}"

    elif len(edges_found) >= 2:
        pattern = 'DUAL_EDGE'
        risk = 'LOW'
        recommendation = (
            f"OE signal '{name}' uses dual-edge registration "
            f"({', '.join(edges_list)}). This is the recommended pattern for "
            "glitch-free OE transitions (vendor TX_PHY style). No action needed."
        )
        details = f"Registered on edges: {', '.join(edges_list)}"

    elif len(edges_found) == 1:
        pattern = 'SINGLE_EDGE'
        risk = 'MEDIUM'
        edge = edges_list[0]
        recommendation = (
            f"OE signal '{name}' is registered on {edge} only. During the "
            f"half-cycle between {edge} and the opposite edge, the OE and "
            "data may disagree, creating a glitch window. Consider adding a "
            "complementary edge register (dual-edge pattern) for glitch-free "
            "transitions on high-speed bidirectional buses."
        )
        details = f"Registered on: {edge} only"

    else:
        # Not in any always block — check continuous assign or pure wire
        if is_continuous_assign:
            pattern = 'COMBINATIONAL'
            risk = 'HIGH'
            recommendation = (
                f"OE signal '{name}' is driven by combinational logic "
                "(continuous assign). Any glitch on the input logic will "
                "propagate directly to the bus enable. Register the OE signal "
                "on at least one clock edge to prevent bus contention."
            )
            details = "Driven by continuous assign (no register)"
        else:
            pattern = 'COMBINATIONAL'
            risk = 'HIGH'
            recommendation = (
                f"OE signal '{name}' appears unregistered — no always block "
                "assignment found. Verify it is not simply a wire alias. If it "
                "controls a tristate buffer, it must be registered to avoid "
                "glitches."
            )
            details = "No registered or continuous assignment found"

    return OESignal(
        name=name,
        file=filepath,
        decl_line=decl_line,
        pattern=pattern,
        risk=risk,
        edges=edges_list,
        gating_condition=gating,
        recommendation=recommendation,
        details=details,
    )


def _detect_gating(name: str, src: str, always_blocks: List[Dict]) -> str:
    """
    Detect if OE signal is conditionally assigned based on bit index,
    data value, or other qualifying signal.

    Returns the gating condition string, or empty string if no gating found.
    """
    for blk in always_blocks:
        body = blk['body']
        # Look for pattern: if (condition) name <= ...
        # where condition involves a bit index or select
        lhs_pat = re.compile(
            r'\b' + re.escape(name) + r'\b\s*(?:\[[^\]]+\]\s*)?(?:<=|=)(?!=)')
        if not lhs_pat.search(body):
            continue

        # Find if-conditions surrounding the assignment
        # Simple heuristic: find `if (expr)` on a line before the assignment
        lines = body.split('\n')
        for i, line in enumerate(lines):
            if lhs_pat.search(line):
                # Walk backward to find nearest if-condition
                for j in range(i - 1, max(i - 5, -1), -1):
                    if_m = re.search(r'\bif\s*\(([^)]+)\)', lines[j])
                    if if_m:
                        cond = if_m.group(1).strip()
                        # Filter out reset conditions
                        if re.search(r'rst|reset', cond, re.IGNORECASE):
                            continue
                        return cond
        # Also check: different assignments to name[bit_a] vs name[bit_b]
        bit_assigns = re.findall(
            r'\b' + re.escape(name) + r'\[([^\]]+)\]\s*(?:<=|=)',
            body)
        if len(set(bit_assigns)) > 1:
            return f"bit-indexed: [{'], ['.join(sorted(set(bit_assigns)))}]"

    return ""


# ---------------------------------------------------------------------------
# Cross-signal dual-edge detection
# ---------------------------------------------------------------------------
def detect_dual_edge_combinations(src: str, oe_signals: List[Dict],
                                  always_blocks: List[Dict]) -> Dict[str, Set[str]]:
    """
    Detect when two separate OE-related signals are combined with AND/OR,
    suggesting a dual-edge pattern across separate registers.

    Example (vendor TX_PHY):
      always @(posedge clk) tx_oe_pos <= ...;
      always @(negedge clk) tx_oe_neg <= ...;
      assign final_oe = tx_oe_pos & tx_oe_neg;

    Returns: {combined_signal: {component_a, component_b, ...}}
    """
    combinations: Dict[str, Set[str]] = {}
    oe_names = {s['name'] for s in oe_signals}

    # Check continuous assigns that AND/OR two or more OE signals
    for m in re.finditer(r'\bassign\s+(\w+)\s*=\s*([^;]+);', src):
        target = m.group(1)
        expr = m.group(2)
        # Find all OE signal references in the expression
        refs = set()
        for oe in oe_names:
            if re.search(r'\b' + re.escape(oe) + r'\b', expr):
                refs.add(oe)
        if len(refs) >= 2:
            combinations[target] = refs

    return combinations


# ---------------------------------------------------------------------------
# Top-level analysis
# ---------------------------------------------------------------------------
def analyze_file(filepath: str, src: str, verbose: bool = False) -> List[OESignal]:
    """Analyze a single file for OE patterns."""
    cleaned = strip_comments(src)
    oe_decls = find_oe_declarations(cleaned, filepath)
    always_blocks = find_always_blocks(cleaned)

    if verbose and oe_decls:
        print(f"  {filepath}: found {len(oe_decls)} OE signal(s): "
              f"{', '.join(d['name'] for d in oe_decls)}")

    results = []
    for decl in oe_decls:
        sig = classify_oe_signal(decl['name'], cleaned, filepath, always_blocks)
        results.append(sig)

    # Post-pass: detect cross-signal dual-edge combinations
    combos = detect_dual_edge_combinations(cleaned, oe_decls, always_blocks)
    if combos:
        for target, components in combos.items():
            # Upgrade component signals if they were classified as SINGLE_EDGE
            comp_edges = set()
            for sig in results:
                if sig.name in components:
                    comp_edges.update(sig.edges)
            if 'posedge' in comp_edges and 'negedge' in comp_edges:
                # The combined signal is effectively DUAL_EDGE
                for sig in results:
                    if sig.name in components and sig.pattern == 'SINGLE_EDGE':
                        sig.pattern = 'DUAL_EDGE'
                        sig.risk = 'LOW'
                        sig.details = (
                            f"Part of dual-edge combination: "
                            f"{' & '.join(sorted(components))} -> {target}")
                        sig.recommendation = (
                            f"OE signal '{sig.name}' is part of a dual-edge "
                            f"combination (combined into '{target}'). This is "
                            "the recommended glitch-free pattern. No action needed.")

    return results


def generate_report(all_signals: List[OESignal],
                    files: List[str]) -> OEReport:
    """Generate the final structured report."""
    summary = {}
    for sig in all_signals:
        summary[sig.pattern] = summary.get(sig.pattern, 0) + 1

    return OEReport(
        files_analyzed=files,
        total_oe_signals=len(all_signals),
        signals=all_signals,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description='Analyze output-enable (OE) patterns in tristate bus drivers.')
    ap.add_argument('--rtl-files', nargs='+', required=True,
                    help='Verilog/SystemVerilog source files to analyze')
    ap.add_argument('--out-dir', required=True,
                    help='Directory for output report')
    ap.add_argument('--verbose', action='store_true',
                    help='Print progress and per-file details')
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    all_signals: List[OESignal] = []
    analyzed_files: List[str] = []

    for f in args.rtl_files:
        p = Path(f)
        if not p.exists():
            print(f"WARNING: file not found: {f}", file=sys.stderr)
            continue
        try:
            src = p.read_text(errors='replace')
            signals = analyze_file(str(p), src, verbose=args.verbose)
            all_signals.extend(signals)
            analyzed_files.append(str(p))
        except Exception as e:
            print(f"ERROR parsing {f}: {e}", file=sys.stderr)
            return 2

    report = generate_report(all_signals, analyzed_files)

    # Write JSON report
    report_path = out / 'oe_pattern_report.json'
    report_dict = asdict(report)
    report_path.write_text(json.dumps(report_dict, indent=2))

    # Console summary
    print(f"oe_pattern_check: analyzed {len(analyzed_files)} file(s), "
          f"found {report.total_oe_signals} OE signal(s)")
    print("-" * 70)
    for pat in ('COMBINATIONAL', 'SINGLE_EDGE', 'DUAL_EDGE', 'GATED'):
        count = report.summary.get(pat, 0)
        if count:
            risk = {'COMBINATIONAL': 'HIGH', 'SINGLE_EDGE': 'MEDIUM',
                    'DUAL_EDGE': 'LOW', 'GATED': 'INFO'}[pat]
            print(f"  {pat:16s}: {count:3d} signal(s)  [risk: {risk}]")
    print("-" * 70)
    for sig in all_signals:
        marker = {'HIGH': '!!!', 'MEDIUM': '**', 'LOW': '', 'INFO': '(i)'}
        print(f"  {marker.get(sig.risk, '')} {sig.file}:{sig.decl_line}: "
              f"{sig.name} -> {sig.pattern} ({sig.risk})")
        if args.verbose:
            print(f"       {sig.details}")
            print(f"       {sig.recommendation}")
    print()
    print(f"Report written to: {report_path}")

    # Nothing was read, so "found 0 OE signals" is not a result about any
    # design. Every path that skips a file already WARNs (`file not found`),
    # but the verdict was `1 if high_count > 0 else 0`, so a run whose entire
    # --rtl-files list was missing exited 0 with `analyzed 0 file(s)` — the
    # same rc as a real scan that found nothing. rc 2 is "could not check",
    # which the CI dispatcher separates from a finding (#559).
    if not analyzed_files:
        print("VACUOUS_PASS: oe_pattern_check examined nothing "
              f"(reason: none of the {len(args.rtl_files)} path(s) given could "
              f"be read) — this is not a clean result", file=sys.stderr)
        return 2

    # Return non-zero if any HIGH risk signals found
    high_count = report.summary.get('COMBINATIONAL', 0)
    return 1 if high_count > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
