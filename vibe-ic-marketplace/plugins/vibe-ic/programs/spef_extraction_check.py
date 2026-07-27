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

i.e. the one substance question this checker asks about net content was
answered "no" on a SPEF carrying 460 real nets, and would have been answered
"no" for every SPEF larger than 8 KB the plugin has ever produced. The file is
now scanned in full, in one streaming pass.

COUPLING DISCLOSURE (step 27's upstream). Step 22's own notes describe three
coupling tiers, and step 27 (Signal Integrity) ``blocks_on: [22]`` — but nothing
in this gate ever looked at whether the extraction carried lateral coupling
capacitance at all. On that same run every ``*CAP`` entry is a 3-field grounded
cap (2040 of them, zero 4-field coupling entries), so
``reports/phase3/si_crosstalk.json`` recorded "No SPEF coupling caps available
for this run" and ``si_mcf_sta_check`` reported ``coupling_pairs: 0`` — while
step 22 returned a clean PASS. The scan now counts coupling entries and DISCLOSES
their absence as a named WARNING at the step where it originates. It is advisory
by design: a grounded-cap-only extraction is a legitimate declared tier, not a
failure — what was wrong was that it was invisible.
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

    Returns the substance facts the gate reasons about. ``*CAP`` entries are
    IEEE-1481 ``idx node value`` (grounded) or ``idx node1 node2 value``
    (coupling, i.e. lateral Cc between two nets) — the NODE count between the
    index and the value is what distinguishes them.

    The classification deliberately mirrors the plugin's canonical SPEF cap
    reader, ``phase3_one_shot_runner._parse_spef_caps`` (index must be an
    integer, value must parse as a float, one node = grounded / two = coupling),
    so the counter and the emitter cannot drift into disagreeing about what a
    coupling cap is. It is reimplemented rather than imported because importing
    the runner to count fields in a text file is a 30k-line dependency.
    """
    facts = {"has_header": False, "has_design": False,
             "d_nets": 0, "r_nets": 0,
             "ground_caps": 0, "coupling_caps": 0}
    in_cap = False
    try:
        with path.open(errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("//"):
                    continue
                if line.startswith("*"):
                    # A keyword line always ends any *CAP block it is not.
                    if "*SPEF" in line:
                        facts["has_header"] = True
                    if line.startswith("*DESIGN") or line.startswith("*DATE"):
                        facts["has_design"] = True
                    if line.startswith("*D_NET"):
                        facts["d_nets"] += 1
                    elif line.startswith("*R_NET"):
                        facts["r_nets"] += 1
                    in_cap = line.startswith("*CAP")
                    continue
                if in_cap:
                    toks = line.split()
                    if len(toks) < 3 or not toks[0].lstrip("-").isdigit():
                        continue
                    try:
                        float(toks[-1])
                    except ValueError:
                        continue
                    nodes = len(toks) - 2
                    if nodes == 1:
                        facts["ground_caps"] += 1
                    elif nodes >= 2:
                        facts["coupling_caps"] += 1
    except OSError:
        pass
    return facts


def audit(project_dir: Path) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    extracted = _pl.extracted_dir(project_dir)
    stats = {"spef_files": 0, "total_bytes": 0, "has_nets": False,
             "waived": False, "d_nets": 0, "r_nets": 0,
             "ground_caps": 0, "coupling_caps": 0}

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
        for key in ("d_nets", "r_nets", "ground_caps", "coupling_caps"):
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

        # Coupling tier disclosure — advisory. A grounded-cap-only extraction
        # is step 22's declared tier (1); it is a legitimate result. What is
        # NOT legitimate is that step 27 (Signal Integrity) `blocks_on: [22]`
        # and then reports a clean crosstalk PASS off an extraction that
        # carries no lateral Cc at all, with the absence recorded nowhere
        # upstream. Naming it here is what makes the downstream vacuity
        # traceable to its cause.
        if has_nets and facts["coupling_caps"] == 0:
            findings.append(Finding(
                "WARNING", "NO_COUPLING_CAPS",
                f"{sf.name} carries no lateral coupling capacitance "
                f"(0 coupling *CAP entries, {facts['ground_caps']} grounded)",
                details=(
                    "Grounded-cap-only extraction (step 22 tier 1). Crosstalk "
                    "/ SI analysis downstream (step 27) has no coupling data "
                    "to work from, so a clean SI verdict off this SPEF is "
                    "vacuous, not a measurement. Tier 2 (analytical lateral "
                    "coupling, VIBEIC_SPEF_COUPLING) is the default augment "
                    "and is NONFATAL — it silently no-ops when the routed "
                    "geometry yields no adjacent same-layer wire pairs."),
            ))

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
            "ground_caps": stats.get("ground_caps", 0),
            "coupling_caps": stats.get("coupling_caps", 0),
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
