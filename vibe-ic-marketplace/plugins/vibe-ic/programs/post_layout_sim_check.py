#!/usr/bin/env python3
"""Verify post-layout gate-level simulation with SDF back-annotation."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


_SDF_MARKERS = re.compile(
    r"\$sdf_annotate|\+sdf|SDF\s+back.?annot|\.sdf\b|sdf_file",
    re.IGNORECASE,
)
_FATAL_RE = re.compile(r"^\s*(\*\*\s*)?(FATAL|ERROR)\b", re.IGNORECASE | re.MULTILINE)
# #437(d): markers a flag/self-report uses to admit it is an
# approximation / skipped condition rather than an executed SDF sim.
_APPROX_RE = re.compile(
    r"approximation|SKIPPED.CONDITION|requires\s+SDF|no\s+SDF",
    re.IGNORECASE,
)


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    sim_dir = _pl.sim_postlayout_dir(project_dir)
    stats = {"sim_dir_exists": False, "sdf_found": False,
             "log_found": False, "sdf_referenced": False,
             "flag_only": False, "approximation_flag": False}

    if not sim_dir.is_dir():
        findings.append(Finding("ERROR", "NO_SIM_DIR",
                                "sim_postlayout/ directory not found"))
        return findings, stats
    stats["sim_dir_exists"] = True

    sdf_files = (list(sim_dir.glob("*.sdf"))
                 + list((_pl.extracted_dir(project_dir)).glob("*.sdf"))
                 if (_pl.extracted_dir(project_dir)).is_dir() else
                 list(sim_dir.glob("*.sdf")))
    # ORGANIC-20260606 #441: a stub/fallback SDF (self-marked "NOT a
    # real SDF" / fallback DELAYFILE with no cell entries) is not an
    # SDF — exclude it so presence of the fabricated file never
    # satisfies the gate.
    real_sdf = []
    for sf in sdf_files:
        try:
            head = sf.read_text(errors="replace")[:1500]
        except OSError:
            continue
        if re.search(r"NOT a real SDF|\(fallback\)|write_sdf \(fallback",
                     head, re.IGNORECASE):
            findings.append(Finding(
                "ERROR", "STUB_SDF",
                f"{sf.name} is a fallback/stub SDF (self-marked), not a "
                f"real write_sdf output (#441)"))
            continue
        real_sdf.append(sf)
    stats["sdf_found"] = len(real_sdf) > 0

    if not real_sdf:
        if not any(f.category == "STUB_SDF" for f in findings):
            findings.append(Finding("ERROR", "NO_SDF",
                                    "No .sdf files found in sim_postlayout/ or extracted/"))

    log_path = sim_dir / "results.log"
    flag_path = sim_dir / "pass.flag"
    stats["log_found"] = log_path.exists() or flag_path.exists()

    if not stats["log_found"]:
        findings.append(Finding("ERROR", "NO_RESULTS",
                                "Neither results.log nor pass.flag found in sim_postlayout/"))
        return findings, stats

    if log_path.exists():
        text = log_path.read_text(errors="replace")
        fatal_matches = _FATAL_RE.findall(text)
        if fatal_matches:
            findings.append(Finding("ERROR", "SIM_ERRORS",
                                    f"Simulation log contains {len(fatal_matches)} FATAL/ERROR lines"))

        if _SDF_MARKERS.search(text):
            stats["sdf_referenced"] = True
        else:
            # #437(d): escalated WARNING→ERROR — a "post-layout sim"
            # whose log never annotates SDF is an RTL sim, not a
            # gate-level timing sim; existence of a log is not substance.
            findings.append(Finding("ERROR", "NO_SDF_REF",
                                    "Simulation log does not reference SDF "
                                    "annotation — not a gate-level timing sim "
                                    "(#437d)"))
    else:
        # #437(d): pass.flag WITHOUT a simulation log is existence, not
        # evidence. A flag that self-declares an approximation maps to
        # SKIPPED-CONDITION (honest, but still not a PASS); any other
        # bare flag is unsubstantiated.
        stats["flag_only"] = True
        flag_text = flag_path.read_text(errors="replace")
        if _APPROX_RE.search(flag_text):
            stats["approximation_flag"] = True
            findings.append(Finding(
                "ERROR", "APPROX_FLAG_NOT_SDF_SIM",
                "pass.flag self-declares an approximation — no "
                "SDF-annotated simulation ran (#437d)"))
        else:
            findings.append(Finding(
                "ERROR", "FLAG_WITHOUT_LOG",
                "pass.flag without results.log is not simulation "
                "evidence (#437d)"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    ok = all(f.severity != "ERROR" for f in findings)
    # #437(d): top-level verdict — SKIPPED-CONDITION when the only
    # artifact is an honest approximation self-report (still exit 1 /
    # pass=false: an approximation never PASSes the gate).
    verdict = ("PASS" if ok else
               "SKIPPED-CONDITION" if stats.get("approximation_flag")
               else "FAIL")
    return {
        "program": "post_layout_sim_check",
        "version": "1.1.0",
        "project_dir": project_dir,
        "verdict": verdict,
        "summary": {
            "sim_dir_exists": stats["sim_dir_exists"],
            "sdf_found": stats["sdf_found"],
            "sdf_referenced": stats["sdf_referenced"],
            "flag_only": stats.get("flag_only", False),
            "approximation_flag": stats.get("approximation_flag", False),
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": ok,
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Check post-layout gate-level simulation")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(project_dir)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
