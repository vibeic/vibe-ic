#!/usr/bin/env python3
"""
signoff_audit.py -- Multi-mode signoff evidence checker (LEGACY gate).

Deterministic compliance program that verifies signoff readiness by scanning
for evidence of completed pipeline stages and tapeout prerequisites.

This is the LEGACY coarse-grained gate. For the 33-step Vibe-IC canonical
flow, use `flow_compliance_check.py` instead — it validates every mandatory
step, not just 4 coarse buckets.

Modes:
  tapeout  -- Check for GDS, netlist, timing report, DRC report
  flow     -- Check for synth, pnr, gds, sta stage evidence

Default threshold (updated 2026-04-21): 4 of 4 (strict).
(Previously 3 of 4 — that was too lenient and let 7-of-28-step designs
pass as "signed off". The lenient mode was removed in v1.6.21.)

v0.52 (2026-04-24): file discovery now excludes `input/`, `pdk/`,
`vendor_ref/`, `references/` path segments. Prior versions counted
PDK standard-cell GDS under `input/pdk/gds/` as design GDS evidence
— a false-positive surfaced by the `phase2+3_v051` fresh-agent run.

Usage:
    python3 signoff_audit.py <project_dir> --mode tapeout
    python3 signoff_audit.py <project_dir> --mode flow --json out.json

Exit codes:
    0 = PASS (sufficient evidence found)
    1 = FAIL (insufficient evidence)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


def _resolve_threshold(default_strict: int, total: int) -> int:
    """Return the strict threshold (lenient mode removed in v1.6.21)."""
    return default_strict


# v1.6.178 (#72 P2-7) — DRC/LVS ENV_UNAVAILABLE waiver detection.
# When Calibre is absent (open-source containers don't ship it),
# `phase3_one_shot_runner` records DRC/LVS steps as
# `status: "ENV_UNAVAILABLE"`. The tapeout-mode signoff gate must
# treat that as a waiver tier (PASS_WITH_WAIVERS) rather than
# silently PASS — a tapeout checklist that couldn't run DRC is
# not really tapeout-ready. chip-AGNOSTIC: the marker is a
# structural property of the phase3 report, never a chip-class
# literal. The check looks at every plausible phase3_one_shot.json
# location since `_pl.report_path` has rotated across the post-
# Wave-91 canonical layout.
_PHASE3_REPORT_CANDIDATES = (
    "reports/phase3_one_shot.json",
    "reports/orchestrator/phase3_one_shot.json",
    "phase3/reports/phase3_one_shot.json",
)


def _read_phase3_env_unavailable_steps(project_dir: Path) -> List[str]:
    """Return the names of phase3 steps reported as ENV_UNAVAILABLE.

    Only DRC / LVS-relevant step names are returned (other ENV_UNAVAILABLE
    steps are not Step-33 waivers). Missing / unreadable / parse-error
    reports return an empty list — callers fall through to the strict
    threshold check.
    """
    for cand in _PHASE3_REPORT_CANDIDATES:
        p = project_dir / cand
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        steps = data.get("steps")
        if not isinstance(steps, list):
            continue
        env_unavail: List[str] = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip().lower()
            status = str(s.get("status", "")).strip()
            if status == "ENV_UNAVAILABLE" and name in (
                    "drc", "lvs", "perc"):
                env_unavail.append(name)
        return env_unavail
    return []


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------
# Path segments that contain INPUTS (PDK / vendor docs / OTP image / etc.) and
# must never be counted as design OUTPUT evidence. The 2026-04-24 v0.51 pilot
# exposed this bug: the gate accepted `input/pdk/gds/<stdcell>.gds` as proof
# of a tape-out-ready design GDS. PDK standard-cell views are inputs, not the
# chip you're shipping.
_INPUT_PATH_SEGMENTS = {"input", "inputs", "pdk", "vendor_ref",
                        "references", "ref"}


def _is_input_path(path: Path, project_dir: Path) -> bool:
    """True if any path segment between project_dir and the file is an input
    directory (case-insensitive)."""
    try:
        rel = path.relative_to(project_dir)
    except ValueError:
        return False
    for part in rel.parts[:-1]:  # exclude the file name itself
        if part.lower() in _INPUT_PATH_SEGMENTS:
            return True
    return False


def _has_files(project_dir: Path, patterns: List[str],
               exclude_inputs: bool = True) -> List[Path]:
    """Return list of matching files for any of the glob patterns.

    By default, excludes anything under input/ / inputs/ / pdk/ / vendor_ref/
    / references/ — those are design INPUTS, not output evidence. Set
    exclude_inputs=False for callers that legitimately want to scan inputs."""
    found: List[Path] = []
    for pat in patterns:
        for p in project_dir.rglob(pat):
            if exclude_inputs and _is_input_path(p, project_dir):
                continue
            found.append(p)
    return found


def _has_dir(project_dir: Path, name: str) -> bool:
    """Check if a stage directory exists (case-insensitive search). Looks
    at the top level and inside the canonical phase2/<stage>/ and
    phase3/<stage>/ subtrees, but NOT inside `input/`, `inputs/`, `pdk/`,
    `vendor_ref/`, `references/` — those are design INPUTS, not output
    evidence (so `input/pdk/gds/` does NOT count as a `gds` stage)."""
    name_l = name.lower()
    skip = {"input", "inputs", "pdk", "vendor_ref", "references"}
    # Top level
    for child in project_dir.iterdir():
        if child.is_dir() and child.name.lower() == name_l:
            return True
    # Canonical phase2/<stage*>/<name>/ and phase3/<stage*>/<name>/
    for phase in ("phase2", "phase3"):
        phase_dir = project_dir / phase
        if not phase_dir.is_dir():
            continue
        for stage_dir in phase_dir.iterdir():
            if not stage_dir.is_dir() or stage_dir.name.lower() in skip:
                continue
            for child in stage_dir.iterdir():
                if child.is_dir() and child.name.lower() == name_l:
                    return True
    return False


# ---------------------------------------------------------------------------
# Mode: tapeout
# ---------------------------------------------------------------------------
def _check_tapeout(project_dir: Path) -> AuditResult:
    result = AuditResult(program="signoff_audit:tapeout", passed=False)
    evidence: dict = {}
    evidence_count = 0

    # (a) GDS file exists
    gds_files = _has_files(project_dir, ["*.gds", "*.gds2", "*.gdsii",
                                          "*.GDS", "*.GDSII"])
    if gds_files:
        evidence["gds"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_GDS_EXISTS", severity="INFO",
            message=f"GDS file found: {gds_files[0].name}",
            file=str(gds_files[0])))
    else:
        evidence["gds"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_GDS_EXISTS", severity="ERROR",
            message="No GDS file found (*.gds, *.gds2, *.gdsii)"))

    # (b) Synthesis netlist exists
    netlist_files = _has_files(project_dir, ["*netlist*.v", "*synth*.v",
                                              "*gate*.v", "*mapped*.v"])
    if netlist_files:
        evidence["netlist"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_NETLIST_EXISTS", severity="INFO",
            message=f"Synthesis netlist found: {netlist_files[0].name}",
            file=str(netlist_files[0])))
    else:
        evidence["netlist"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_NETLIST_EXISTS", severity="ERROR",
            message="No synthesis netlist found (*netlist*.v, *synth*.v, *gate*.v)"))

    # (c) Timing report exists
    timing_files = _has_files(project_dir, ["*timing*.rpt", "*sta*.rpt",
                                             "*timing*.log", "*STA*.rpt"])
    if timing_files:
        evidence["timing"] = True
        evidence_count += 1
        result.findings.append(Finding(
            rule="TAPEOUT_TIMING_EXISTS", severity="INFO",
            message=f"Timing report found: {timing_files[0].name}",
            file=str(timing_files[0])))
    else:
        evidence["timing"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_TIMING_EXISTS", severity="ERROR",
            message="No timing report found (*timing*.rpt, *sta*.rpt)"))

    # (d) DRC — SUBSTANCE, not existence.
    # ORGANIC-20260606-existence-only-signoff-gates (#437a): the pre-fix
    # gate PASSed on the FIRST `*drc*` glob hit — in one audited project
    # that was the clean detailed-router DRC (0 items) while the KLayout
    # SIGNOFF DRC in the same project carried 204,079 violations the
    # checklist never read. The signoff deck's report is the authority:
    # prefer it explicitly, parse its violation count, and FAIL on a
    # nonzero count (waivable only via the documented step-waiver path,
    # never by pointing at a different report).
    drc_files = _has_files(project_dir, ["*drc*.rpt", "*drc*.log",
                                          "*DRC*.rpt", "*DRC*.log"])
    # signoff-first ordering: a report whose NAME or CONTENT marks it as
    # the signoff deck outranks router/projection reports.
    def _drc_rank(p: Path) -> int:
        n = p.name.lower()
        if "signoff" in n:
            return 0
        try:
            head = p.read_text(errors="replace")[:2000]
        except OSError:
            return 3
        if "<report-database>" in head:   # KLayout signoff database
            return 1
        if "detailed_route" in head or "openroad" in head.lower():
            return 2                       # router projection — last
        return 2
    drc_files = sorted(drc_files, key=_drc_rank)

    def _drc_violation_count(p: Path):
        """Best-effort violation count; None when unparseable."""
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            return None
        if "<report-database>" in txt[:2000]:
            return txt.count("<item>")
        m = (re.search(r"(?i)\btotal\s+(?:errors|violations)\s*[:=]?\s*(\d+)", txt)
             or re.search(r"(?i)\bviolations?\s*[:=]\s*(\d+)", txt))
        return int(m.group(1)) if m else None

    if drc_files:
        chosen = drc_files[0]
        vcount = _drc_violation_count(chosen)
        if vcount is not None and vcount > 0:
            evidence["drc"] = False
            result.findings.append(Finding(
                rule="TAPEOUT_DRC_VIOLATIONS", severity="ERROR",
                message=(f"signoff DRC report '{chosen.name}' carries "
                         f"{vcount} violation(s) — the tapeout checklist "
                         f"gates on the COUNT, not on file existence "
                         f"(#437a). Waivable only via the documented "
                         f"step-waiver path."),
                file=str(chosen)))
        elif vcount is None:
            evidence["drc"] = False
            result.findings.append(Finding(
                rule="TAPEOUT_DRC_UNPARSED", severity="ERROR",
                message=(f"DRC report '{chosen.name}' found but its "
                         f"violation count could not be parsed — refusing "
                         f"an existence-only PASS (#437a); verify the "
                         f"signoff deck output manually."),
                file=str(chosen)))
        else:
            evidence["drc"] = True
            evidence_count += 1
            result.findings.append(Finding(
                rule="TAPEOUT_DRC_CLEAN", severity="INFO",
                message=(f"signoff DRC report '{chosen.name}': "
                         f"0 violations (count parsed, not just "
                         f"existence)"),
                file=str(chosen)))
    else:
        evidence["drc"] = False
        result.findings.append(Finding(
            rule="TAPEOUT_DRC_EXISTS", severity="ERROR",
            message="No DRC report found (*drc*.rpt/log)"))

    threshold = _resolve_threshold(default_strict=4, total=4)
    result.passed = evidence_count >= threshold

    # v1.6.178 (#72 P2-7) — DRC/LVS ENV_UNAVAILABLE waiver.
    # When phase3 step records indicate DRC/LVS could not run for
    # environment reasons (no Calibre in container), demote a
    # passing tapeout-checklist to PASS_WITH_WAIVERS (still rc=0)
    # AND backfill evidence credit for any DRC slot still missing.
    # This makes the human-facing verdict honest — Step 33 cannot
    # be PASS in absolute terms when DRC didn't actually run.
    env_unavailable_steps = _read_phase3_env_unavailable_steps(project_dir)
    verdict_tier = "PASS" if result.passed else "FAIL"
    if env_unavailable_steps:
        # If DRC slot is missing but DRC step was ENV_UNAVAILABLE,
        # backfill credit so threshold can be reached.
        if not evidence.get("drc") and "drc" in env_unavailable_steps:
            evidence["drc"] = "env_unavailable"
            evidence_count += 1
            for f in result.findings:
                if (f.rule == "TAPEOUT_DRC_EXISTS"
                        and f.severity == "ERROR"):
                    f.severity = "WARNING"
                    f.message = (
                        f"DRC report missing AND phase3 step "
                        f"reports ENV_UNAVAILABLE — waived. "
                        f"Step 33 demoted to PASS_WITH_WAIVERS; "
                        f"explicit human signoff required before "
                        f"mask order.")
                    break
            else:
                result.findings.append(Finding(
                    rule="TAPEOUT_DRC_WAIVED_ENV_UNAVAILABLE",
                    severity="WARNING",
                    message=(
                        f"DRC step reported ENV_UNAVAILABLE in "
                        f"phase3_one_shot.json; tapeout checklist "
                        f"demoted to PASS_WITH_WAIVERS.")))
            result.passed = evidence_count >= threshold
        if result.passed:
            verdict_tier = "PASS_WITH_WAIVERS"
            result.findings.append(Finding(
                rule="TAPEOUT_ENV_UNAVAILABLE_DEMOTION",
                severity="WARNING",
                message=(
                    f"Phase 3 step(s) {env_unavailable_steps} reported "
                    f"ENV_UNAVAILABLE; tapeout checklist verdict is "
                    f"PASS_WITH_WAIVERS — explicit human waiver entry "
                    f"required before mask order.")))

    result.summary = {
        "evidence": evidence,
        "evidence_count": evidence_count,
        "threshold": threshold,
        "env_unavailable_steps": env_unavailable_steps,
        "verdict_tier": verdict_tier,
    }
    return result


# ---------------------------------------------------------------------------
# Mode: flow
# ---------------------------------------------------------------------------
def _check_flow(project_dir: Path) -> AuditResult:
    result = AuditResult(program="signoff_audit:flow", passed=False)
    stages: dict = {}
    stage_count = 0

    # synth stage
    synth_dir = _has_dir(project_dir, "synth")
    synth_logs = _has_files(project_dir, ["*synth*.log", "*synthesis*.log",
                                           "*synth*.rpt"])
    if synth_dir or synth_logs:
        stages["synth"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_SYNTH_EVIDENCE", severity="INFO",
            message="Synthesis stage evidence found"))
    else:
        stages["synth"] = False
        result.findings.append(Finding(
            rule="FLOW_SYNTH_EVIDENCE", severity="ERROR",
            message="No synthesis evidence (synth/ dir or synth log)"))

    # pnr stage
    pnr_dir = _has_dir(project_dir, "pnr")
    pnr_logs = _has_files(project_dir, ["*pnr*.log", "*place*.log",
                                          "*route*.log", "*floorplan*.log"])
    if pnr_dir or pnr_logs:
        stages["pnr"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_PNR_EVIDENCE", severity="INFO",
            message="Place-and-route stage evidence found"))
    else:
        stages["pnr"] = False
        result.findings.append(Finding(
            rule="FLOW_PNR_EVIDENCE", severity="ERROR",
            message="No P&R evidence (pnr/ dir or pnr log)"))

    # gds stage
    gds_dir = _has_dir(project_dir, "gds")
    gds_files = _has_files(project_dir, ["*.gds", "*.gds2", "*.gdsii"])
    if gds_dir or gds_files:
        stages["gds"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_GDS_EVIDENCE", severity="INFO",
            message="GDS stage evidence found"))
    else:
        stages["gds"] = False
        result.findings.append(Finding(
            rule="FLOW_GDS_EVIDENCE", severity="ERROR",
            message="No GDS evidence (gds/ dir or *.gds file)"))

    # sta stage
    sta_files = _has_files(project_dir, ["*sta*.rpt", "*timing*.rpt",
                                          "*STA*.rpt", "*timing*.log"])
    if sta_files:
        stages["sta"] = True
        stage_count += 1
        result.findings.append(Finding(
            rule="FLOW_STA_EVIDENCE", severity="INFO",
            message="STA stage evidence found"))
    else:
        stages["sta"] = False
        result.findings.append(Finding(
            rule="FLOW_STA_EVIDENCE", severity="ERROR",
            message="No STA evidence (*sta*.rpt, *timing*.rpt)"))

    threshold = _resolve_threshold(default_strict=4, total=4)
    result.passed = stage_count >= threshold
    result.summary = {
        "stages": stages,
        "stage_count": stage_count,
        "threshold": threshold,
    }
    return result


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------
MODE_MAP = {
    "tapeout": _check_tapeout,
    "flow": _check_flow,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-mode signoff evidence checker")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--mode", required=True, choices=list(MODE_MAP.keys()),
                        help="Signoff check mode")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        result = AuditResult(program=f"signoff_audit:{args.mode}", passed=False)
        result.findings.append(Finding(
            rule="PROJECT_DIR_EXISTS", severity="ERROR",
            message=f"Project directory does not exist: {project_dir}"))
        result.summary = {"evidence_count": 0, "threshold": _resolve_threshold(4, 4)}
    else:
        checker = MODE_MAP[args.mode]
        result = checker(project_dir)

    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
