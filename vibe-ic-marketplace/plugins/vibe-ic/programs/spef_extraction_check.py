#!/usr/bin/env python3
"""Verify parasitic extraction (SPEF) was produced after routing.

READ WINDOW. The substance checks used to run against
``sf.read_text()[:8192]`` — the first 8 KB of the file. A SPEF's first 8 KB is
its header, name map and port list; the ``*D_NET`` records start well past it on
any real design. Measured on the real completed run
``campaign_pr427/spm/converge_ihp-sg13g2``::

    $ ls -l phase3/stage3/extracted/spm.spef        196741 bytes
    $ grep -bo '*D_NET' spm.spef | head -1          50386   <- first record
    $ grep -c '*D_NET' spm.spef                     460     <- records present
    $ spef_extraction_check <project>
      summary.has_nets = false
      WARNING NO_NETS: spm.spef has no *D_NET/*R_NET entries

DENOMINATOR — this is not one run's accident. Over the whole tracked corpus
(``git ls-files benchmark-data`` -> 20 ``.spef`` files), the first ``*D_NET``
record lies beyond byte 8192 in **20 of 20**: first-record offsets span
12,834 - 109,782 bytes in files carrying 351 - 2,563 nets. The old window
answered "no nets" for EVERY SPEF this plugin has ever published. Removing
those ``NO_NETS`` findings is not a relaxation; it deletes a finding that was
false in every measured instance. The file is now scanned in full, in one
streaming pass.

THE WINDOW ALSO MOVED THE rc-BEARING PREDICATE — stated because it is not
covered by the ``NO_NETS`` story above. ``BAD_HEADER`` is an ERROR (rc 1) and
``MISSING_METADATA`` is a WARNING; both were decided on the same 8 KB prefix and
are now decided over the whole file. So a VALID SPEF whose ``*SPEF`` header
happens to sit past byte 8192 — e.g. behind a long comment banner — was
``ERROR BAD_HEADER`` rc 1 on the pre-change tree and is clean rc 0 here. That is
a rc 1 -> 0 move, i.e. a RELAXATION in the strict sense, and it is the intended
one: the file was always well-formed. The guard did NOT go blind — a genuinely
headerless SPEF still FAILs on both trees (pinned by
``test_spef_full_scan_and_coupling_disclosure.py``). No tracked SPEF exercises
the late-header case; it is constructed in the test.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


def _waiver_reason(project_dir: Path) -> str:
    """Return the spef_extraction_unavailable_reason waiver text, or ""."""
    waivers = project_dir / "waivers.json"
    if not waivers.is_file():
        return ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return ""
    val = d.get("spef_extraction_unavailable_reason", "")
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return "\n".join(str(x).strip() for x in val if str(x).strip())
    return ""


def scan_spef(path: Path) -> dict:
    """One streaming pass over the WHOLE SPEF; never a fixed-size window.

    Returns the substance facts the gate reasons about: whether the ``*SPEF``
    header and the ``*DESIGN``/``*DATE`` metadata are present anywhere in the
    file, and how many ``*D_NET`` / ``*R_NET`` records it carries.

    Streaming rather than ``read_text()``: a routed SPEF is routinely tens of
    MB, and the questions asked here are all answerable line by line.
    """
    facts = {"has_header": False, "has_design": False,
             "d_nets": 0, "r_nets": 0}
    try:
        with path.open(errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                if not line.startswith("*"):
                    continue
                if "*SPEF" in line:
                    facts["has_header"] = True
                if line.startswith("*DESIGN") or line.startswith("*DATE"):
                    facts["has_design"] = True
                if line.startswith("*D_NET"):
                    facts["d_nets"] += 1
                elif line.startswith("*R_NET"):
                    facts["r_nets"] += 1
    except OSError:
        pass
    return facts


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    extracted = _pl.extracted_dir(project_dir)
    stats = {"spef_files": 0, "total_bytes": 0, "has_nets": False,
             "waived": False, "d_nets": 0, "r_nets": 0}

    # v0.119.21: tool-unavailable-for-PDK waiver. Custom PDKs without a
    # Magic .tech file (<foundry> PDKs, etc.) cannot run
    # parasitic extraction in the open-source flow. The honest path is
    # a documented waiver with a reason ≥20 chars (matches the waivers
    # schema's anti-rubber-stamp policy). No content fabrication.
    reason = _waiver_reason(project_dir)
    if reason and len(reason) >= 20:
        stats["waived"] = True
        findings.append(Finding(
            "INFO", "WAIVED_TOOL_UNAVAILABLE",
            "SPEF extraction waived: open-source toolchain has no extraction "
            "path for this PDK",
            details=reason,
        ))
        return findings, stats

    if not extracted.is_dir():
        findings.append(Finding("ERROR", "NO_EXTRACTED_DIR",
                                "extracted/ directory not found"))
        return findings, stats

    spef_files = sorted(extracted.glob("*.spef"))
    stats["spef_files"] = len(spef_files)

    if not spef_files:
        findings.append(Finding("ERROR", "NO_SPEF",
                                "No .spef files in extracted/"))
        return findings, stats

    for sf in spef_files:
        size = sf.stat().st_size
        stats["total_bytes"] += size

        if size == 0:
            findings.append(Finding("ERROR", "EMPTY_SPEF",
                                    f"Empty SPEF: {sf.name}"))
            continue

        if size < 1024:
            findings.append(Finding("ERROR", "TOO_SMALL",
                                    f"SPEF file {sf.name} is {size} bytes (<1 KB)"))
            continue

        facts = scan_spef(sf)
        for key in ("d_nets", "r_nets"):
            stats[key] += facts[key]
        has_nets = bool(facts["d_nets"] or facts["r_nets"])

        if not facts["has_header"]:
            findings.append(Finding("ERROR", "BAD_HEADER",
                                    f"{sf.name} missing *SPEF header"))
        if not facts["has_design"]:
            findings.append(Finding("WARNING", "MISSING_METADATA",
                                    f"{sf.name} missing *DESIGN or *DATE"))
        if has_nets:
            stats["has_nets"] = True
        else:
            findings.append(Finding("WARNING", "NO_NETS",
                                    f"{sf.name} has no *D_NET/*R_NET entries"))

    return findings, stats


def build_report(findings: List[Finding], stats: dict,
                 project_dir: str) -> dict:
    return {
        "program": "spef_extraction_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "summary": {
            "spef_files": stats["spef_files"],
            "total_bytes": stats["total_bytes"],
            "has_nets": stats["has_nets"],
            "d_nets": stats.get("d_nets", 0),
            "r_nets": stats.get("r_nets", 0),
            "waived": stats.get("waived", False),
            "findings_count": len(findings),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "pass": all(f.severity != "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="Check SPEF extraction artifacts")
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
        Path(args.json).write_text(out)

    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
