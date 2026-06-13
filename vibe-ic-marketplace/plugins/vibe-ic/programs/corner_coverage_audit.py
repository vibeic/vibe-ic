#!/usr/bin/env python3
"""
corner_coverage_audit.py — Audit PVT corner coverage in IC design flows.

Critical production signoff gap: many AI-generated IC design flows only run
the typical (TT) corner during STA, synthesis, and timing analysis. Production
signoff requires at minimum SS (slow-slow) and FF (fast-fast) corners. Full
PVT coverage includes:

  Process: SS, TT, FF (minimum 3; some flows add SF, FS)
  Voltage: low (0.9×nominal), nominal, high (1.1×nominal)
  Temperature: -40°C, 25°C, 125°C (or 0°C/85°C for commercial)

This program:
  1. Scans a project directory for STA reports, synthesis logs, timing
     constraint files (.sdc), and Liberty file references (.lib)
  2. Detects corner names from file names, file contents, and log messages
     using general patterns (not hardcoded to any specific PDK)
  3. Classifies coverage level:
     - MINIMAL: Only TT found → WARNING
     - BASIC: TT + SS + FF found → PASS with note
     - FULL: 3+ process × 2+ voltage × 2+ temperature → PASS
  4. Reports which corners are covered and which are missing

Usage:
    python3 corner_coverage_audit.py --project-dir /path/to/project --out-dir /tmp/audit

Output: JSON report with corners found, coverage level, and recommendations.

Generality: works for ANY IC project using ANY PDK (GF180, SKY130, TSMC,
Samsung, Intel, etc.). Detects corner names from file patterns, not hardcoded
PDK names.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class CornerEvidence:
    """A single piece of evidence that a PVT corner was exercised."""
    corner_name: str          # e.g. "ss", "tt", "ff", "ss_0p72v_m40c"
    process: str              # "SS", "TT", "FF", "SF", "FS", or "UNKNOWN"
    voltage: Optional[str]    # e.g. "0.72V", "1.8V", or None
    temperature: Optional[str]  # e.g. "-40C", "25C", "125C", or None
    source_type: str          # "liberty_filename", "sdc_content", "sta_report",
                              # "openroad_log", "synthesis_log", "directory_name"
    source_file: str          # path to the file where evidence was found
    source_line: int          # line number (0 if from filename)
    snippet: str              # the text fragment that matched


@dataclass
class AuditResult:
    """Final audit result."""
    coverage_level: str       # "NONE", "MINIMAL", "BASIC", "FULL"
    verdict: str              # "PASS", "WARNING", "FAIL"
    process_corners: List[str]   # unique process corners found
    voltage_points: List[str]    # unique voltage points found
    temperature_points: List[str]  # unique temperature points found
    total_evidence: int
    evidence: List[dict]      # list of CornerEvidence as dicts
    missing_corners: List[str]
    recommendations: List[str]


# ---------------------------------------------------------------------------
# Corner detection patterns (PDK-agnostic)
# ---------------------------------------------------------------------------

# Process corner patterns — match in filenames, liberty headers, log messages
# These capture the process corner designator from various naming conventions:
#   sky130_fd_sc_hd__ss_...
#   gf180mcu_fd_sc_mcu7t5v0__ss_...
#   slow_slow, fast_fast, typical
#   ss_0p72v_m40c, tt_1p80v_25c, ff_1p98v_m40c
PROCESS_CORNER_MAP = {
    'ss': 'SS', 'slow_slow': 'SS', 'slowslow': 'SS', 'slow': 'SS',
    'tt': 'TT', 'typical': 'TT', 'typ': 'TT', 'nom': 'TT',
    'ff': 'FF', 'fast_fast': 'FF', 'fastfast': 'FF', 'fast': 'FF',
    'sf': 'SF', 'slow_fast': 'SF', 'slowfast': 'SF',
    'fs': 'FS', 'fast_slow': 'FS', 'fastslow': 'FS',
}

# Pattern to extract process corner from filenames/strings
# Matches: __ss_, _ss_, /ss_, -ss-, _ss., ss_0p, " ss ", ":ss_", etc.
PROCESS_RE = re.compile(
    r'(?:^|[_/\-.\s:,])'
    r'(ss|tt|ff|sf|fs|slow_slow|fast_fast|typical|slowslow|fastfast|'
    r'slow_fast|fast_slow|slowfast|fastslow|slow|fast|typ|nom)'
    r'(?:[_/\-.\s:,]|$)',
    re.IGNORECASE
)

# Voltage pattern: 0p72v, 1p8v, 0.72v, 1.8v, 3p3v, 0p9v, etc.
VOLTAGE_RE = re.compile(
    r'(\d+[pP.]\d+)\s*[vV]',
)

# Temperature pattern: m40c, n40c, 25c, 125c, -40c, -40C, 0c, 85c
TEMPERATURE_RE = re.compile(
    r'([mnMN]?\-?\d+)\s*[cC](?:[^a-zA-Z]|$)',
)

# Explicit MCMM / multi-corner references in SDC or TCL
MCMM_KEYWORDS = [
    'create_scenario', 'define_corner', 'set_pvt_corner',
    'create_corner', 'add_corner', 'define_operating_conditions',
    'set_operating_conditions', 'corner_name', 'pvt_corner',
    'multi_corner', 'mcmm',
]

# File extensions and globs to scan
TIMING_FILE_EXTS = {'.sdc', '.lib', '.log', '.rpt', '.txt', '.tcl'}
LIBERTY_EXTS = {'.lib', '.lib.gz', '.db'}
STA_REPORT_PATTERNS = [
    '*sta*', '*timing*', '*setup*', '*hold*', '*slack*',
    '*report_checks*', '*report_timing*',
]
SYNTHESIS_LOG_PATTERNS = [
    '*synth*', '*synthesis*', '*yosys*', '*genus*', '*dc_shell*',
    '*design_compiler*',
]
OPENROAD_LOG_PATTERNS = [
    '*openroad*', '*opensta*', '*innovus*', '*icc2*', '*primetime*',
]


# ---------------------------------------------------------------------------
# Utility: normalize voltage string
# ---------------------------------------------------------------------------
def normalize_voltage(raw: str) -> str:
    """Convert '0p72' or '0.72' or '1p8' → '0.72V', '1.8V'."""
    v = raw.replace('p', '.').replace('P', '.')
    try:
        fv = float(v)
        return f"{fv:.2f}V"
    except ValueError:
        return f"{v}V"


def normalize_temperature(raw: str) -> str:
    """Convert 'm40' or 'n40' or '-40' or '25' → '-40C', '25C'."""
    t = raw.strip()
    t = t.replace('m', '-').replace('M', '-').replace('n', '-').replace('N', '-')
    # Handle double negative from e.g. "m-40" → "--40"
    while '--' in t:
        t = t.replace('--', '-')
    try:
        tv = int(t)
        return f"{tv}C"
    except ValueError:
        return f"{t}C"


# ---------------------------------------------------------------------------
# Core scanning functions
# ---------------------------------------------------------------------------
def extract_corner_from_string(
    text: str,
    source_type: str,
    source_file: str,
    source_line: int = 0,
) -> List[CornerEvidence]:
    """
    Extract PVT corner information from a text string (filename or content line).
    Returns a list of CornerEvidence objects found.
    """
    results = []

    # Find process corners
    for m in PROCESS_RE.finditer(text):
        raw_process = m.group(1).lower()
        process = PROCESS_CORNER_MAP.get(raw_process, 'UNKNOWN')
        if process == 'UNKNOWN':
            continue

        # Look for voltage near this match
        voltage = None
        vm = VOLTAGE_RE.search(text)
        if vm:
            voltage = normalize_voltage(vm.group(1))

        # Look for temperature near this match
        temperature = None
        tm = TEMPERATURE_RE.search(text)
        if tm:
            temperature = normalize_temperature(tm.group(1))

        # Build corner name
        parts = [process.lower()]
        if voltage:
            parts.append(voltage)
        if temperature:
            parts.append(temperature)
        corner_name = '_'.join(parts)

        results.append(CornerEvidence(
            corner_name=corner_name,
            process=process,
            voltage=voltage,
            temperature=temperature,
            source_type=source_type,
            source_file=source_file,
            source_line=source_line,
            snippet=text.strip()[:200],
        ))

    return results


def scan_liberty_files(project_dir: Path) -> List[CornerEvidence]:
    """Scan for Liberty (.lib) files and extract corner info from filenames."""
    evidence = []
    # Search for .lib files (may be deep in PDK directories)
    for ext in ('*.lib', '*.lib.gz'):
        for lib_file in project_dir.rglob(ext):
            fname = lib_file.name
            evs = extract_corner_from_string(
                fname, 'liberty_filename', str(lib_file), 0)
            evidence.extend(evs)

            # Also check first ~50 lines of .lib files for corner info
            # (Liberty headers often contain operating_conditions)
            if lib_file.suffix == '.lib':
                try:
                    with open(lib_file, 'r', errors='replace') as f:
                        for lineno, line in enumerate(f, 1):
                            if lineno > 100:
                                break
                            if any(kw in line.lower() for kw in
                                   ['operating_conditions', 'process', 'voltage',
                                    'temperature', 'nom_']):
                                evs2 = extract_corner_from_string(
                                    line, 'liberty_content', str(lib_file), lineno)
                                evidence.extend(evs2)
                except (PermissionError, OSError):
                    pass
    return evidence


def scan_sdc_files(project_dir: Path) -> List[CornerEvidence]:
    """Scan SDC/TCL files for multi-corner references."""
    evidence = []
    for pattern in ('*.sdc', '*.tcl'):
        for sdc_file in project_dir.rglob(pattern):
            try:
                lines = sdc_file.read_text(errors='replace').split('\n')
            except (PermissionError, OSError):
                continue
            for lineno, line in enumerate(lines, 1):
                lower = line.lower()
                # Check for MCMM keywords
                if any(kw in lower for kw in MCMM_KEYWORDS):
                    evs = extract_corner_from_string(
                        line, 'sdc_content', str(sdc_file), lineno)
                    evidence.extend(evs)
                # Check for corner references even without MCMM keywords
                elif PROCESS_RE.search(line):
                    evs = extract_corner_from_string(
                        line, 'sdc_content', str(sdc_file), lineno)
                    evidence.extend(evs)
    return evidence


def scan_sta_reports(project_dir: Path) -> List[CornerEvidence]:
    """Scan STA report files for evidence of multi-corner analysis."""
    evidence = []
    # Look for report files
    for pattern in ('*.rpt', '*.report', '*.txt', '*.log'):
        for rpt_file in project_dir.rglob(pattern):
            fname_lower = rpt_file.name.lower()
            # Only scan files that look like STA/timing reports
            is_timing_file = any(
                kw in fname_lower
                for kw in ['sta', 'timing', 'setup', 'hold', 'slack',
                           'report_check', 'report_timing', 'corner']
            )
            if not is_timing_file:
                continue

            # Check filename for corner info
            evs = extract_corner_from_string(
                rpt_file.name, 'sta_report', str(rpt_file), 0)
            evidence.extend(evs)

            # Check file content (first 200 lines)
            try:
                with open(rpt_file, 'r', errors='replace') as f:
                    for lineno, line in enumerate(f, 1):
                        if lineno > 200:
                            break
                        if PROCESS_RE.search(line):
                            evs2 = extract_corner_from_string(
                                line, 'sta_report', str(rpt_file), lineno)
                            evidence.extend(evs2)
            except (PermissionError, OSError):
                pass
    return evidence


def scan_synthesis_logs(project_dir: Path) -> List[CornerEvidence]:
    """Scan synthesis logs for Liberty file references with corner info."""
    evidence = []
    for pattern in ('*.log', '*.txt'):
        for log_file in project_dir.rglob(pattern):
            fname_lower = log_file.name.lower()
            is_synth = any(
                kw in fname_lower
                for kw in ['synth', 'synthesis', 'yosys', 'genus',
                           'dc_shell', 'design_compiler']
            )
            if not is_synth:
                continue

            try:
                with open(log_file, 'r', errors='replace') as f:
                    for lineno, line in enumerate(f, 1):
                        if lineno > 5000:
                            break
                        lower = line.lower()
                        # Look for liberty file reads
                        if '.lib' in lower or 'liberty' in lower:
                            evs = extract_corner_from_string(
                                line, 'synthesis_log', str(log_file), lineno)
                            evidence.extend(evs)
                        # Look for corner/operating_conditions settings
                        if any(kw in lower for kw in
                               ['operating_conditions', 'corner',
                                'set_pvt', 'read_liberty']):
                            evs = extract_corner_from_string(
                                line, 'synthesis_log', str(log_file), lineno)
                            evidence.extend(evs)
            except (PermissionError, OSError):
                pass
    return evidence


def scan_openroad_logs(project_dir: Path) -> List[CornerEvidence]:
    """Scan OpenROAD/OpenSTA/EDA tool logs for corner references."""
    evidence = []
    for pattern in ('*.log', '*.txt', '*.rpt'):
        for log_file in project_dir.rglob(pattern):
            fname_lower = log_file.name.lower()
            is_eda = any(
                kw in fname_lower
                for kw in ['openroad', 'opensta', 'innovus', 'icc2',
                           'primetime', 'tempus', 'pnr', 'place',
                           'route', 'cts']
            )
            if not is_eda:
                continue

            try:
                with open(log_file, 'r', errors='replace') as f:
                    for lineno, line in enumerate(f, 1):
                        if lineno > 5000:
                            break
                        lower = line.lower()
                        if ('.lib' in lower or 'corner' in lower or
                                'define_corner' in lower or
                                'create_corner' in lower or
                                PROCESS_RE.search(line)):
                            evs = extract_corner_from_string(
                                line, 'openroad_log', str(log_file), lineno)
                            evidence.extend(evs)
            except (PermissionError, OSError):
                pass
    return evidence


def scan_directory_names(project_dir: Path) -> List[CornerEvidence]:
    """Scan directory names for corner indicators (e.g. results/ss/, runs/ff/)."""
    evidence = []
    try:
        for d in project_dir.rglob('*'):
            if not d.is_dir():
                continue
            evs = extract_corner_from_string(
                d.name, 'directory_name', str(d), 0)
            evidence.extend(evs)
    except (PermissionError, OSError):
        pass
    return evidence


# ---------------------------------------------------------------------------
# Coverage classification
# ---------------------------------------------------------------------------
REQUIRED_PROCESS_BASIC = {'SS', 'TT', 'FF'}
REQUIRED_PROCESS_FULL = {'SS', 'TT', 'FF'}  # SF/FS are bonus


def classify_coverage(
    evidence: List[CornerEvidence],
) -> AuditResult:
    """Classify PVT corner coverage based on collected evidence."""
    if not evidence:
        return AuditResult(
            coverage_level='NONE',
            verdict='FAIL',
            process_corners=[],
            voltage_points=[],
            temperature_points=[],
            total_evidence=0,
            evidence=[],
            missing_corners=['SS', 'TT', 'FF'],
            recommendations=[
                'No timing/corner evidence found in the project directory.',
                'Ensure STA reports, Liberty files, or synthesis logs are present.',
                'For production signoff, at minimum SS + TT + FF corners are required.',
            ],
        )

    # Collect unique process corners, voltages, temperatures
    process_set: Set[str] = set()
    voltage_set: Set[str] = set()
    temperature_set: Set[str] = set()

    for ev in evidence:
        process_set.add(ev.process)
        if ev.voltage:
            voltage_set.add(ev.voltage)
        if ev.temperature:
            temperature_set.add(ev.temperature)

    process_corners = sorted(process_set)
    voltage_points = sorted(voltage_set)
    temperature_points = sorted(temperature_set)

    # Determine coverage level
    has_ss = 'SS' in process_set
    has_tt = 'TT' in process_set
    has_ff = 'FF' in process_set
    has_basic_process = has_ss and has_tt and has_ff

    n_voltages = len(voltage_set)
    n_temperatures = len(temperature_set)

    # FULL: 3+ process × 2+ voltage × 2+ temperature
    if has_basic_process and n_voltages >= 2 and n_temperatures >= 2:
        coverage_level = 'FULL'
        verdict = 'PASS'
    # BASIC: SS + TT + FF found (regardless of voltage/temperature)
    elif has_basic_process:
        coverage_level = 'BASIC'
        verdict = 'PASS'
    # MINIMAL: Only TT (or only 1-2 process corners but not all 3)
    elif process_set:
        coverage_level = 'MINIMAL'
        verdict = 'WARNING'
    else:
        coverage_level = 'NONE'
        verdict = 'FAIL'

    # Determine missing corners
    missing = []
    for pc in ['SS', 'TT', 'FF']:
        if pc not in process_set:
            missing.append(pc)

    # Build recommendations
    recommendations = []
    if coverage_level == 'MINIMAL':
        found_str = ', '.join(process_corners)
        recommendations.append(
            f"Only {found_str} process corner(s) found. "
            f"Production signoff requires at minimum SS + TT + FF."
        )
        if not has_ss:
            recommendations.append(
                "MISSING SS (slow-slow): worst-case setup timing. "
                "Add SS corner Liberty files and run STA at SS conditions."
            )
        if not has_ff:
            recommendations.append(
                "MISSING FF (fast-fast): worst-case hold timing. "
                "Add FF corner Liberty files and run STA at FF conditions."
            )
    elif coverage_level == 'BASIC':
        recommendations.append(
            "Basic 3-corner process coverage (SS/TT/FF) achieved."
        )
        if n_voltages < 2:
            recommendations.append(
                "Consider adding voltage variation (low/nominal/high) "
                "for more robust signoff."
            )
        if n_temperatures < 2:
            recommendations.append(
                "Consider adding temperature variation (-40C/25C/125C) "
                "for full PVT coverage."
            )
    elif coverage_level == 'FULL':
        recommendations.append(
            f"Full PVT coverage achieved: {len(process_corners)} process × "
            f"{n_voltages} voltage × {n_temperatures} temperature."
        )
        # Check for SF/FS bonus corners
        if 'SF' not in process_set and 'FS' not in process_set:
            recommendations.append(
                "Consider adding SF (slow-fast) and FS (fast-slow) skew "
                "corners for advanced signoff."
            )

    return AuditResult(
        coverage_level=coverage_level,
        verdict=verdict,
        process_corners=process_corners,
        voltage_points=voltage_points,
        temperature_points=temperature_points,
        total_evidence=len(evidence),
        evidence=[asdict(ev) for ev in evidence],
        missing_corners=missing,
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def deduplicate_evidence(evidence: List[CornerEvidence]) -> List[CornerEvidence]:
    """
    Deduplicate evidence by (process, voltage, temperature, source_file).
    Keep the first occurrence of each unique combination.
    """
    seen: Set[Tuple] = set()
    deduped = []
    for ev in evidence:
        key = (ev.process, ev.voltage, ev.temperature, ev.source_file)
        if key not in seen:
            seen.add(key)
            deduped.append(ev)
    return deduped


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------
def run_audit(project_dir: str) -> AuditResult:
    """
    Run the full PVT corner coverage audit on a project directory.
    Returns an AuditResult.
    """
    proj_path = Path(project_dir)
    if not proj_path.exists():
        return AuditResult(
            coverage_level='NONE',
            verdict='FAIL',
            process_corners=[],
            voltage_points=[],
            temperature_points=[],
            total_evidence=0,
            evidence=[],
            missing_corners=['SS', 'TT', 'FF'],
            recommendations=[
                f'Project directory not found: {project_dir}',
            ],
        )

    # Collect evidence from all sources
    all_evidence: List[CornerEvidence] = []

    all_evidence.extend(scan_liberty_files(proj_path))
    all_evidence.extend(scan_sdc_files(proj_path))
    all_evidence.extend(scan_sta_reports(proj_path))
    all_evidence.extend(scan_synthesis_logs(proj_path))
    all_evidence.extend(scan_openroad_logs(proj_path))
    all_evidence.extend(scan_directory_names(proj_path))

    # Deduplicate
    all_evidence = deduplicate_evidence(all_evidence)

    # Classify
    result = classify_coverage(all_evidence)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description=(
            'Audit PVT corner coverage in an IC design flow. '
            'Detects whether the design has been analyzed at multiple '
            'process/voltage/temperature corners for production signoff.'
        ))
    ap.add_argument('--project-dir', required=True,
                    help='Root directory of the IC design project')
    ap.add_argument('--out-dir', required=True,
                    help='Output directory for JSON report')
    args = ap.parse_args()

    result = run_audit(args.project_dir)

    # Console summary
    print(f"corner_coverage_audit: {result.coverage_level} coverage — "
          f"{result.verdict}")
    print("-" * 70)
    print(f"  Process corners: {', '.join(result.process_corners) or 'none'}")
    print(f"  Voltage points:  {', '.join(result.voltage_points) or 'none'}")
    print(f"  Temperature pts: {', '.join(result.temperature_points) or 'none'}")
    print(f"  Total evidence:  {result.total_evidence}")
    print("-" * 70)

    if result.missing_corners:
        print(f"  MISSING: {', '.join(result.missing_corners)}")

    for rec in result.recommendations:
        print(f"  → {rec}")

    # Write JSON report
    out_path = Path(args.out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_file = out_path / 'corner_coverage_audit_report.json'

    report = asdict(result)
    report['tool'] = 'corner_coverage_audit'
    report['version'] = '1.0.0'
    report['project_dir'] = args.project_dir

    report_file.write_text(json.dumps(report, indent=2))
    print(f"\nJSON report written to: {report_file}")

    # Exit code: 0 = PASS, 1 = WARNING, 2 = FAIL
    if result.verdict == 'PASS':
        return 0
    elif result.verdict == 'WARNING':
        return 1
    else:
        return 2


if __name__ == '__main__':
    sys.exit(main())
