#!/usr/bin/env python3
"""
behavioral_evidence_per_spec_item_check.py — v0.100 J1

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Verify that every behavioural requirement in L9 (Integration Spec) has
at least one piece of verifiable evidence in the project directory.

Evidence types recognised:
  - Simulation trace    : sim*/*.vcd, sim*/*.fst, sim*/*.log containing the requirement ID
  - LED capture         : led_captures/*.jpg, led_captures/*.png
  - Tester raw frame    : reports/*tester*.log, reports/*<half-duplex-tester>*.log
  - cocotb assertion    : sim*/results.xml containing the requirement ID
  - Scope screenshot    : scope_captures/*.png
  - Manual attestation  : reports/behavioral_evidence.json (explicit per-item sign-off)

Usage:
    python3 behavioral_evidence_per_spec_item_check.py <project_dir>
    python3 behavioral_evidence_per_spec_item_check.py <project_dir> --json report.json
    python3 behavioral_evidence_per_spec_item_check.py <project_dir> --spec path/to/L9.json

Exit 0 = every requirement has evidence, 1 = gaps found, 2 = I/O error.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
import _path_layout as _pl
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


def find_l9(project: Path) -> Optional[Path]:
    """Locate the L9 integration spec JSON."""
    candidates = [
        _pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json",
        _pl.generated_docs_dir(project) / "L9.json",
        project / "docs" / "L9_INTEGRATION_SPEC.json",
        project / "L9_INTEGRATION_SPEC.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    for p in project.rglob("L9*.json"):
        return p
    return None


_REQUIREMENT_LIST_KEYS = (
    "behavioral_requirements",
    "test_scenarios",
    "functional_requirements",
    "verification_requirements",
    "requirements",
    "scenarios",
)


def extract_requirements(l9: dict) -> List[str]:
    """Extract explicitly declared behavioural requirement IDs/names.

    Do not fall back to every list of dictionaries in L9.  Structural arrays
    such as ``ports``, ``top_ports``, ``top_module_pins`` and
    ``clock_domains`` are declarations consumed by integration/build gates,
    not behavioural requirements that need a waveform or assertion.  The old
    broad fallback counted those arrays as 68 missing behaviours on a real
    data-converter run (a producer/consumer scope defect, not design evidence).
    """
    reqs: List[str] = []

    if "behavioral_requirements" in l9:
        br = l9["behavioral_requirements"]
        if isinstance(br, list):
            for item in br:
                if isinstance(item, dict):
                    reqs.append(item.get("id") or item.get("name") or str(item))
                elif isinstance(item, str):
                    reqs.append(item)
        elif isinstance(br, dict):
            reqs.extend(br.keys())

    if "test_scenarios" in l9:
        ts = l9["test_scenarios"]
        if isinstance(ts, list):
            for item in ts:
                if isinstance(item, dict):
                    reqs.append(item.get("id") or item.get("name") or str(item))

    if "functional_requirements" in l9:
        fr = l9["functional_requirements"]
        if isinstance(fr, list):
            for item in fr:
                if isinstance(item, dict):
                    reqs.append(item.get("id") or item.get("name") or str(item))

    # Generic aliases are accepted only when their key explicitly denotes a
    # requirement/scenario list.  Never infer behavioural intent from an
    # arbitrary object array: L9's structural arrays are intentionally broad.
    for key in _REQUIREMENT_LIST_KEYS:
        if key in ("behavioral_requirements", "test_scenarios",
                   "functional_requirements") or key not in l9:
            continue
        val = l9[key]
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    rid = item.get("id") or item.get("name")
                    if rid:
                        reqs.append(rid)
                elif isinstance(item, str) and item.strip():
                    reqs.append(item)
        elif isinstance(val, dict):
            reqs.extend(str(k) for k in val if str(k).strip())

    return [r for r in reqs if r]


def scan_evidence(project: Path) -> Set[str]:
    """Collect all text from evidence files to match against requirement IDs."""
    evidence_text = set()
    evidence_files: List[Path] = []

    for pattern in [
        "sim*/*.log", "sim*/*.vcd", "sim*/*.fst",
        "sim*/results.xml", "reports/*.log", "reports/*.json",
        "led_captures/*", "scope_captures/*",
        "reports/behavioral_evidence.json",
        "**/*tester*.log", "**/*bist*.log",
    ]:
        evidence_files.extend(project.glob(pattern))

    for f in evidence_files:
        evidence_text.add(f.name.lower())
        if f.suffix in ('.log', '.json', '.xml', '.txt', '.csv'):
            try:
                content = f.read_text(errors='replace')[:50000]
                evidence_text.add(content.lower())
            except Exception:
                pass

    return evidence_text


def check_evidence(req_id: str, evidence: Set[str]) -> bool:
    """Check if a requirement ID appears in any evidence."""
    rid_lower = req_id.lower().strip()
    for e in evidence:
        if rid_lower in e:
            return True
    rid_norm = re.sub(r'[\s_-]+', '', rid_lower)
    for e in evidence:
        if rid_norm in re.sub(r'[\s_-]+', '', e):
            return True
    return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir", help="Project directory to audit")
    p.add_argument("--spec", help="Override path to L9 integration spec JSON")
    p.add_argument("--json", help="Write JSON report to this path")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"behavioral_evidence_per_spec_item_check: not a directory: {project}",
              file=sys.stderr)
        return 2

    l9_path = Path(args.spec) if args.spec else find_l9(project)
    if not l9_path or not l9_path.exists():
        print("behavioral_evidence_per_spec_item_check: L9 integration spec not found")
        print("FAIL: no L9 to extract requirements from")
        return 1

    try:
        l9 = json.loads(l9_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"behavioral_evidence_per_spec_item_check: cannot parse L9: {exc}",
              file=sys.stderr)
        return 2

    reqs = extract_requirements(l9)
    if not reqs:
        # No explicit behavioural list is a legitimate declaration shape for
        # integration-only/non-protocol designs.  Name the condition and
        # return the disclosed skip tier; do not warn about structural fields.
        print(f"SKIPPED-CONDITION: no explicit behavioural requirements in {l9_path}")
        if args.json:
            report = {
                "program": "behavioral_evidence_per_spec_item_check",
                "l9_path": str(l9_path),
                "total_requirements": 0,
                "covered": 0,
                "missing_count": 0,
                "missing_items": [],
                "covered_items": [],
                "verdict": "SKIPPED-CONDITION",
                "reason_class": "DESIGN_DECLARED_NA",
            }
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(Path(args.json), json.dumps(report, indent=2))
        return 2

    evidence = scan_evidence(project)

    covered = []
    missing = []
    for req in reqs:
        if check_evidence(req, evidence):
            covered.append(req)
        else:
            missing.append(req)

    print(f"L9 spec: {l9_path.name}")
    print(f"Requirements: {len(reqs)} total, {len(covered)} with evidence, {len(missing)} missing")

    if missing:
        print(f"\nMissing evidence for:")
        for m in missing:
            print(f"  - {m}")
        verdict = "FAIL"
    else:
        verdict = "PASS"

    print(f"\n{verdict}: behavioral_evidence_per_spec_item_check")

    if args.json:
        report = {
            "program": "behavioral_evidence_per_spec_item_check",
            "l9_path": str(l9_path),
            "total_requirements": len(reqs),
            "covered": len(covered),
            "missing_count": len(missing),
            "missing_items": missing,
            "covered_items": covered,
            "verdict": verdict,
        }
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), json.dumps(report, indent=2))

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
