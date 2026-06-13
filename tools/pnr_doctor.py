#!/usr/bin/env python3
"""
pnr-doctor — OpenROAD P&R Error Auto-Classifier + Fix Suggester
================================================================
Parses OpenROAD P&R logs and DRC reports, classifies issues,
and outputs actionable fix suggestions.

Known patterns (from 135-IC campaign):
    1. GPL_DIVERGE     — Placement diverges (design too small, <5 cells)
    2. DRT_POWER_NET   — Power net routing conflict (tie-cell net as POWER)
    3. FLOORPLAN_FAIL  — Cannot create floorplan (bad site name or utilization)
    4. DRC_SPACING     — Metal spacing violation
    5. DRC_WIDTH       — Metal width violation
    6. DRC_VIA         — Via enclosure violation
    7. TIMING_FAIL     — Setup/hold violation in STA
    8. NO_CLOCK        — No clock defined (combinational design)
    9. CONGESTION      — Routing congestion > threshold
   10. UNKNOWN         — Unclassified error
"""

import re
import sys
import json
import argparse
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class PnrDiagnosis:
    pattern: str
    severity: str
    message: str
    root_cause: str
    fix_suggestion: str
    fix_param: Optional[str] = None


@dataclass
class PnrReport:
    log_file: str
    drc_file: Optional[str] = None
    status: str = 'UNKNOWN'
    area: float = 0.0
    utilization: float = 0.0
    drc_violations: int = 0
    timing_slack: Optional[float] = None
    diagnoses: List[PnrDiagnosis] = field(default_factory=list)
    summary: str = ""


PNR_PATTERNS = [
    {
        'name': 'GPL_DIVERGE',
        'regex': r'GPL-0304.*diverged|RePlAce diverged',
        'severity': 'ERROR',
        'root_cause': 'Design too small (<5 cells) for OpenROAD placement algorithm',
        'fix_suggestion': 'Skip P&R for trivial designs, or add padding cells',
        'fix_param': 'Mark as TRIVIAL_SKIP in checkpoint',
    },
    {
        'name': 'DRT_POWER_NET',
        'regex': r'DRT-0305.*POWER.*not routable|signal type POWER is not routable',
        'severity': 'ERROR',
        'root_cause': 'PDN generated a tie-cell net marked as POWER, blocking detailed route',
        'fix_suggestion': 'Use global_route only (skip detailed_route), or edit DEF to change net type',
        'fix_param': 'Remove detailed_route from pnr.tcl, use global_route DEF for GDS',
    },
    {
        'name': 'FLOORPLAN_FAIL',
        'regex': r'cannot.*floorplan|invalid.*site|site.*not found',
        'severity': 'ERROR',
        'root_cause': 'Wrong site name for this PDK (GF180=GF018hv5v_mcu_sc7, SKY130=unithd)',
        'fix_suggestion': 'Check site name matches PDK: GF180→GF018hv5v_mcu_sc7, SKY130→unithd',
        'fix_param': 'initialize_floorplan -site GF018hv5v_mcu_sc7',
    },
    {
        'name': 'DRC_SPACING',
        'regex': r'spacing.*violation|min.*space',
        'severity': 'WARNING',
        'root_cause': 'Metal traces too close together',
        'fix_suggestion': 'Reduce utilization (-utilization 30) or increase core_space',
        'fix_param': 'initialize_floorplan -utilization 30 -core_space 15',
    },
    {
        'name': 'DRC_WIDTH',
        'regex': r'width.*violation|min.*width',
        'severity': 'WARNING',
        'root_cause': 'Metal trace narrower than PDK minimum',
        'fix_suggestion': 'Check routing layer constraints, ensure Metal1-Metal5 only',
    },
    {
        'name': 'DRC_VIA',
        'regex': r'via.*enclosure|via.*violation',
        'severity': 'WARNING',
        'root_cause': 'Via metal enclosure insufficient',
        'fix_suggestion': 'Let detailed_route auto-fix, or reduce routing density',
    },
    {
        'name': 'TIMING_FAIL',
        'regex': r'slack.*negative|VIOLATED|setup.*fail|hold.*fail',
        'severity': 'WARNING',
        'root_cause': 'Timing constraint not met (setup or hold violation)',
        'fix_suggestion': 'Relax clock period or optimize critical path in RTL',
        'fix_param': 'create_clock -period 300 (increase from 200)',
    },
    {
        'name': 'NO_CLOCK',
        'regex': r'no.*clock.*defined|cannot.*find.*clock',
        'severity': 'INFO',
        'root_cause': 'Combinational design has no clock port',
        'fix_suggestion': 'Create virtual clock: create_clock -name vclk -period 200',
        'fix_param': 'create_clock -name virtual_clk -period 200',
    },
    {
        'name': 'CONGESTION',
        'regex': r'congestion.*overflow|routing.*overflow|overflow.*\d+%',
        'severity': 'WARNING',
        'root_cause': 'Too many routes in a small area',
        'fix_suggestion': 'Reduce utilization or increase die area',
        'fix_param': 'initialize_floorplan -utilization 25 -density 0.35',
    },
]


def analyze_pnr(log_path: str, drc_path: str = None) -> PnrReport:
    """Parse P&R log and optional DRC report."""
    report = PnrReport(log_file=log_path, drc_file=drc_path)

    try:
        with open(log_path, 'r') as f:
            log_text = f.read()
    except FileNotFoundError:
        report.status = 'FAIL'
        report.summary = f'Log not found: {log_path}'
        return report

    # Extract metrics
    m = re.search(r'Design area:\s*([\d.]+)', log_text)
    if m: report.area = float(m.group(1))

    m = re.search(r'Utilization:\s*([\d.]+)', log_text)
    if m: report.utilization = float(m.group(1))

    m = re.search(r'[Ss]lack\s*[:=]\s*([-\d.]+)', log_text)
    if m: report.timing_slack = float(m.group(1))

    # Classify errors
    has_error = False
    for pat in PNR_PATTERNS:
        matches = re.findall(pat['regex'], log_text, re.IGNORECASE)
        if matches:
            report.diagnoses.append(PnrDiagnosis(
                pattern=pat['name'],
                severity=pat['severity'],
                message=matches[0][:100],
                root_cause=pat['root_cause'],
                fix_suggestion=pat['fix_suggestion'],
                fix_param=pat.get('fix_param'),
            ))
            if pat['severity'] == 'ERROR':
                has_error = True

    # Parse DRC file
    if drc_path:
        try:
            with open(drc_path, 'r') as f:
                drc_text = f.read()
            report.drc_violations = len(re.findall(r'violation', drc_text, re.IGNORECASE))
            if report.drc_violations == 0 and len(drc_text.strip()) == 0:
                report.drc_violations = 0  # empty = clean
        except FileNotFoundError:
            pass

    report.status = 'FAIL' if has_error else ('WARN' if report.diagnoses else 'PASS')
    diag_str = ", ".join(set(d.pattern for d in report.diagnoses))
    report.summary = (
        f"{report.status}: area={report.area:.0f}um², "
        f"util={report.utilization:.0f}%, DRC={report.drc_violations}"
        + (f" [{diag_str}]" if diag_str else "")
    )
    return report


def print_report(report: PnrReport):
    icon = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}.get(report.status, '?')
    print(f"\n{'='*60}")
    print(f"  pnr-doctor — P&R Diagnosis Report")
    print(f"{'='*60}")
    print(f"  Log:       {report.log_file}")
    print(f"  Status:    {icon} {report.status}")
    print(f"  Area:      {report.area:.0f} um²")
    print(f"  DRC:       {report.drc_violations} violations")
    if report.timing_slack is not None:
        print(f"  Slack:     {report.timing_slack:.2f} ns")

    if report.diagnoses:
        print(f"\n  Diagnoses:")
        for d in report.diagnoses:
            si = '❌' if d.severity == 'ERROR' else '⚠️' if d.severity == 'WARNING' else 'ℹ️'
            print(f"    {si} [{d.pattern}] {d.root_cause}")
            print(f"       Fix: {d.fix_suggestion}")
            if d.fix_param:
                print(f"       Cmd: {d.fix_param}")
    elif report.status == 'PASS':
        print(f"\n  ✅ P&R clean, no issues.")
    print(f"\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='pnr-doctor: OpenROAD P&R classifier')
    parser.add_argument('log_file', help='Path to pnr.log')
    parser.add_argument('--drc', default=None, help='Path to route_drc.rpt')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    report = analyze_pnr(args.log_file, args.drc)
    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print_report(report)
    sys.exit(0 if report.status == 'PASS' else 1)


if __name__ == '__main__':
    main()
