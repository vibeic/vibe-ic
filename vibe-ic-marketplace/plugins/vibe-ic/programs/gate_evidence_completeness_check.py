#!/usr/bin/env python3
"""
gate_evidence_completeness_check.py — v0.100 L1

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Every gate listed as PASS in a FINAL_REPORT.md (or flow compliance JSON)
must have a corresponding evidence file (stdout dump, JSON output, or log).

Without evidence, a PASS claim is unauditable. This program flags gates
that claim PASS but have no backing artefact.

Usage:
    python3 gate_evidence_completeness_check.py <project_dir>
    python3 gate_evidence_completeness_check.py <project_dir> --json report.json
    python3 gate_evidence_completeness_check.py <project_dir> --report FINAL_REPORT.md

Exit 0 = every PASS gate has evidence, 1 = gaps found, 2 = I/O error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import _path_layout as _pl


def find_report(project: Path) -> Optional[Path]:
    """Locate the flow compliance JSON or FINAL_REPORT.md."""
    candidates = [
        _pl.report_path(project, "flow_compliance.json"),
        project / "FINAL_REPORT.md",
        _pl.report_path(project, "FINAL_REPORT.md"),
    ]
    for c in candidates:
        if c.exists():
            return c
    for p in project.rglob("flow_compliance*.json"):
        return p
    for p in project.rglob("FINAL_REPORT*"):
        return p
    return None


def extract_pass_gates_from_json(path: Path) -> List[str]:
    """Extract gate names that claim PASS from flow compliance JSON."""
    data = json.loads(path.read_text())
    gates = []
    for step in data.get("steps", []):
        if step.get("status") == "PASS":
            name = step.get("name", f"step_{step.get('id', '?')}")
            gates.append(name)
    return gates


def extract_pass_gates_from_md(path: Path) -> List[str]:
    """Extract gate names that claim PASS from markdown report."""
    gates = []
    text = path.read_text(errors='replace')
    for m in re.finditer(r'[|✓✅]\s*(?:PASS)\s*[|]\s*(.+?)(?:\s*[|(])', text):
        gates.append(m.group(1).strip())
    for m in re.finditer(r'^[-*]\s+\**([\w_\s]+?)\**\s*[:—–-]\s*PASS', text, re.MULTILINE):
        gates.append(m.group(1).strip())
    for m in re.finditer(r'PASS\s*[-—:]\s*([\w_\s]+)', text):
        gates.append(m.group(1).strip())
    return gates


def collect_evidence_files(project: Path) -> Set[str]:
    """Collect all evidence file stems in standard locations."""
    evidence = set()
    for pattern in [
        "reports/gates/*.json",
        "reports/gates/*.log",
        "reports/gates/*.txt",
        "reports/*.json",
        "reports/*.log",
        "reports/sta/*.json",
        "reports/dft/*.json",
        "reports/pnr/*.json",
        "reports/drc*.json",
        "reports/lvs*.json",
        "reports/ir_drop*.json",
        "reports/em*.json",
        "reports/power*.json",
        "sim*/results.xml",
        "phase2/stage2/dft/*.rpt",
        "phase3/stage3/sta/*.rpt",
    ]:
        for f in project.glob(pattern):
            evidence.add(f.stem.lower())
            evidence.add(f.name.lower())

    return evidence


def gate_has_evidence(gate_name: str, evidence: Set[str]) -> bool:
    """Check if a gate name matches any evidence file."""
    norm = re.sub(r'[\s()\-–—]+', '_', gate_name).lower().strip('_')
    words = [w for w in re.split(r'[\s_]+', norm) if len(w) > 2]

    for e in evidence:
        if norm in e or e in norm:
            return True

    for e in evidence:
        matched = sum(1 for w in words if w in e)
        if matched >= max(1, len(words) * 0.5):
            return True

    return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir", help="Project directory to audit")
    p.add_argument("--report", help="Override path to FINAL_REPORT.md or flow compliance JSON")
    p.add_argument("--json", help="Write JSON report to this path")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"gate_evidence_completeness_check: not a directory: {project}",
              file=sys.stderr)
        return 2

    report_path = Path(args.report) if args.report else find_report(project)
    if not report_path or not report_path.exists():
        print("gate_evidence_completeness_check: no FINAL_REPORT or flow compliance JSON found")
        print("FAIL: nothing to audit")
        return 1

    if report_path.suffix == '.json':
        try:
            pass_gates = extract_pass_gates_from_json(report_path)
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"gate_evidence_completeness_check: cannot parse JSON: {exc}",
                  file=sys.stderr)
            return 2
    else:
        pass_gates = extract_pass_gates_from_md(report_path)

    if not pass_gates:
        print("gate_evidence_completeness_check: no PASS gates found in report")
        print("PASS: nothing to check (no PASS claims)")
        return 0

    evidence = collect_evidence_files(project)

    with_evidence = []
    without_evidence = []
    for gate in pass_gates:
        if gate_has_evidence(gate, evidence):
            with_evidence.append(gate)
        else:
            without_evidence.append(gate)

    print(f"Report: {report_path.name}")
    print(f"PASS gates: {len(pass_gates)} total, "
          f"{len(with_evidence)} with evidence, "
          f"{len(without_evidence)} without evidence")

    if without_evidence:
        print(f"\nMissing evidence for:")
        for g in without_evidence:
            print(f"  - {g}")
        verdict = "FAIL"
    else:
        verdict = "PASS"

    print(f"\n{verdict}: gate_evidence_completeness_check")

    if args.json:
        report = {
            "program": "gate_evidence_completeness_check",
            "report_path": str(report_path),
            "total_pass_gates": len(pass_gates),
            "with_evidence": len(with_evidence),
            "without_evidence_count": len(without_evidence),
            "without_evidence_items": without_evidence,
            "verdict": verdict,
        }
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2))

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
