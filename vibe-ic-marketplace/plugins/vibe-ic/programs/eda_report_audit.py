#!/usr/bin/env python3
"""
eda_report_audit.py -- Multi-mode EDA report checker for backend skills.

Deterministic compliance program that verifies EDA sign-off reports contain
the expected analysis categories and quantitative data.

Modes:
  drc      -- DRC report: violation categories + counts
  lvs      -- LVS report: mismatch categories
  power    -- Power report: leakage AND dynamic values
  em       -- EM report: current density values
  ir_drop  -- IR-drop report: voltage drop values
  sta      -- STA report: WNS/TNS + setup/hold

Usage:
    python3 eda_report_audit.py <project_dir> --mode drc
    python3 eda_report_audit.py <project_dir> --mode sta --json out.json

Exit codes:
    0 = PASS (report exists with expected content)
    1 = FAIL (missing report or missing categories)

No external tool dependencies -- pure Python.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import lvs_verdict_tokens as _lvt  # #524 — shared netgen terminal-verdict tokens


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


# v0.119.21: tool-unavailable-for-PDK waiver. Custom open-source PDKs
# (<foundry> PDKs etc.) lack characterization data the IR / EM
# / SI / power / SPEF tools need. Blocking the gate forever penalises
# honest projects; instead require a documented waiver with reason ≥20
# chars (matches the waivers schema's anti-rubber-stamp policy).
_UNAVAILABLE_KEYS = {
    "power":   "power_report_unavailable_reason",
    "ir_drop": "ir_drop_report_unavailable_reason",
    "em":      "em_report_unavailable_reason",
    "si":      "si_report_unavailable_reason",
}


def _waived_for_pdk(project_dir, mode: str) -> str:
    import json as _json
    waivers = project_dir / "waivers.json"
    if not waivers.is_file():
        return ""
    try:
        data = _json.loads(waivers.read_text())
    except Exception:
        return ""
    key = _UNAVAILABLE_KEYS.get(mode)
    if not key:
        return ""
    val = data.get(key, "")
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return "\n".join(str(x).strip() for x in val if str(x).strip())
    return ""


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------
# #525 (field round-4 adjacent finding) — recursive report discovery used to
# ingest STALE copies under backup/aside directories (a `_stale_bak/` antenna
# report with 56 violations was parsed alongside the clean live one and
# flipped the verdict). Exclude path components that are hidden (dot-dirs)
# or carry an explicit backup token. Token matching is boundary-aware so
# legitimate names ("golden", "bakery") never match.
# v1.3.94 (spm commercial-PDK sign-off) — added `snapshot`/`snap` and
# `prebuild`: an in-tree `_known_good_snapshot_v1393/` copy of a design's
# reports (a common human backup pattern) carried a STALE netgen lvs.rpt
# (mismatch) + a pre-repair antenna stub, and the recursive report scan
# ingested BOTH alongside the clean live sign-off — the snapshot's mismatch
# then flipped the LVS/antenna verdict. A canonical report tree never uses a
# "snapshot" component, so it is unambiguously a backup-flavored aside.
_BACKUP_TOKEN_RE = re.compile(
    r"(?:^|[._\-])(bak|backup|backups|stale|old|trash|movedaside|aside"
    r"|snapshots?|snap|prebuild)"
    r"(?:$|[._\-])", re.IGNORECASE)


def _is_backup_path(p: Path, root: Path) -> bool:
    """True when any path component between root and the file is hidden or
    backup-flavored (the canonical report tree never uses such names)."""
    try:
        parts = p.relative_to(root).parts
    except ValueError:
        parts = p.parts
    for part in parts:
        if part.startswith("."):
            return True
        if _BACKUP_TOKEN_RE.search(part):
            return True
    return False


def _discover(project_dir: Path, patterns: List[str]) -> List[Path]:
    """Glob for files matching any of the given patterns recursively,
    skipping hidden / backup-flavored directories (#525)."""
    found: List[Path] = []
    for pat in patterns:
        found.extend(project_dir.rglob(pat))
    # Deduplicate, preserve order
    seen = set()
    unique = []
    for p in found:
        if p in seen:
            continue
        seen.add(p)
        if _is_backup_path(p, project_dir):
            continue
        unique.append(p)
    return unique


# Tool signatures — a real EDA-tool report will contain AT LEAST one of these
# distinctive strings. Hand-authored stubs rarely reproduce them. Added
# 2026-04-22 after the <benchmark> v0.47 pilot where <1.5 KB hand-typed stubs
# passed every *_report_check via category-keyword matching alone.
TOOL_SIGNATURES = {
    "drc": [
        "klayout",             # KLayout DRC runset output
        "openroad",            # OpenROAD detailed-route DRC
        "detailed_route",
        "magic",               # Magic DRC
        "calibre",             # Calibre DRC
        "drt-",                # OpenROAD drt messages
        "lvs mismatch",        # DRC reports sometimes chain with LVS context
        "DRC clean",
        "violation report",
    ],
    "lvs": [
        "netgen",              # Netgen LVS
        "NET count",           # Netgen summary
        "Equivalence test",
        "Circuits match",
        "Circuits don't match",
        "Number of topologically valid",
        "calibre", "lvs_check",
    ],
    "power": [
        "openroad",
        "Power Report",        # OpenROAD report_power
        "Total Power",
        "Switching Power",
        "Leakage Power",
        "Internal Power",
        "Group: sequential",   # OpenROAD breakdown
        "Group: combinational",
        "mW\n", " uW\n", "  nW\n",
    ],
    "em": [
        "openroad",
        "Electromigration",
        "EM lifetime",
        "current density",
        "RMS current",
        "Peak current",
        "redhawk", "voltus",
    ],
    "ir_drop": [
        "openroad",
        "IR drop",
        "PSM",                 # Power Supply Metal (OpenROAD analyzer)
        "static IR",
        "dynamic IR",
        "worst voltage",
        "power grid",
        "voltage drop",
    ],
    "sta": [
        "OpenSTA",
        "Report",
        "Startpoint",
        "Endpoint",
        "data arrival time",
        "slack",
        "primetime",
    ],
    "antenna": [
        "openroad",            # OpenROAD check_antennas
        "check_antenna",
        "ANT-",                # OpenROAD ANT-0001/0002 message codes
        "antenna check",
        "net violations",      # "Found N net violations"
        "pin violations",
        "gate-oxide",
    ],
}

# Minimum reasonable file size (bytes) for a real report on a non-trivial
# design. A stub that only sums "violations: 0" across ~6 categories fits in
# well under 500 B, so the threshold filters obvious hand-typed cases while
# still allowing small open-flow outputs. Tuned from observed runs:
#   aon_timer OpenSTA pre-PnR:      5.2 KB
#   aon_timer Fault ATPG coverage:  225 KB
#   <benchmark>   Yosys synth stats:      3.1 KB
#   Agent's 2026-04-22 DRC stub:    0.62 KB  ← should be rejected
MIN_REPORT_BYTES = {
    "drc":     2048,
    "lvs":     1536,
    "power":   2048,
    "em":      1024,
    "ir_drop": 1024,
    "sta":     1024,
    "antenna": 200,   # OpenROAD check_antennas clean reports are short but real
}


def _has_tool_signature(text: str, mode: str) -> tuple[bool, str]:
    """Return (found, matched_pattern) — case-insensitive."""
    sigs = TOOL_SIGNATURES.get(mode, [])
    lower = text.lower()
    for sig in sigs:
        if sig.lower() in lower:
            return True, sig
    return False, ""


# A "strong" signature set per mode: distinctive multi-marker combinations
# that a hand-typed stub could not carry without effectively reproducing a
# real tool's content. When ALL markers of any group are present, the
# byte-size floor is waived (but the basic tool-signature requirement still
# applies). This prevents a genuinely real but COMPACT report from a SMALL
# design (e.g. an spm with a single timing path → a ~0.9 KB report_checks
# path table that legitimately carries Startpoint/Endpoint/arrival/slack)
# from being false-rejected as a "hand-typed stub". chip-AGNOSTIC: keyed on
# universal tool-output structure, not on any chip's signals.
STRONG_SIGNATURE_GROUPS = {
    "sta": [
        # A real OpenSTA report_checks path table.
        ["data arrival time", "data required time", "slack"],
        ["startpoint", "endpoint", "slack"],
    ],
    # v1.3.94 — a real KLayout NetlistComparer authoritative LVS report is
    # legitimately COMPACT (the comparer emits a verdict + device/net/pin
    # tallies, not a netgen-style multi-KB device-by-device transcript), so a
    # genuinely-clean small design (e.g. an spm on a commercial PDK) fell under
    # the 1536 B netgen-tuned floor and false-rejected as a "hand-typed stub".
    # The four-marker fingerprint below (engine name + comparer class + the
    # comparer-specific "power-only devices dropped" phrase + the terminal
    # verdict) is content a stub could not carry without reproducing the real
    # comparer's structured output. chip-AGNOSTIC.
    "lvs": [
        ["klayout", "netlistcomparer", "power-only devices dropped",
         "circuits match uniquely"],
    ],
}


def _has_strong_signature(text: str, mode: str) -> bool:
    lower = text.lower()
    for group in STRONG_SIGNATURE_GROUPS.get(mode, []):
        if all(marker.lower() in lower for marker in group):
            return True
    return False


def _check_tool_authenticity(files: List[Path], mode: str,
                              result: AuditResult) -> bool:
    """Append findings for missing tool signature + undersized reports.
    Returns True only if at least one candidate passed both checks."""
    any_authentic = False
    for fp in files:
        try:
            size = fp.stat().st_size
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        # Waive the byte-size floor when the report carries a strong,
        # multi-marker tool signature (a real-but-compact small-design
        # report). The tool-signature requirement below still gates.
        strong = _has_strong_signature(text, mode)
        ok_size = size >= MIN_REPORT_BYTES.get(mode, 1024) or strong
        ok_sig, matched = _has_tool_signature(text, mode)
        if ok_size and ok_sig:
            any_authentic = True
            continue
        rel = str(fp)
        if not ok_size:
            result.findings.append(Finding(
                rule=f"{mode.upper()}_REPORT_TOO_SMALL", severity="ERROR",
                message=(f"report {size} B is below minimum "
                         f"{MIN_REPORT_BYTES.get(mode,1024)} B — "
                         f"suggests a hand-typed stub, not a real "
                         f"{mode} tool output"),
                file=rel,
            ))
        if not ok_sig:
            result.findings.append(Finding(
                rule=f"{mode.upper()}_NO_TOOL_SIGNATURE", severity="ERROR",
                message=(f"report lacks any known {mode} tool signature "
                         f"(one of: {TOOL_SIGNATURES[mode][:4]}... ). "
                         f"Hand-typed reports rejected."),
                file=rel,
            ))
    return any_authentic


# ---------------------------------------------------------------------------
# Mode checkers
# ---------------------------------------------------------------------------
def _check_drc(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:drc", passed=False)
    files = _discover(project_dir, ["*drc*.rpt", "*drc*.log", "*drc*.txt",
                                     "*DRC*.rpt", "*DRC*.log", "*DRC*.txt"])
    if not files:
        result.findings.append(Finding(
            rule="DRC_REPORT_EXISTS", severity="ERROR",
            message="No DRC report found (searched *drc*.rpt/log/txt)"))
        result.summary = {"files_found": 0, "categories_found": []}
        return result

    categories_re = {
        "spacing": re.compile(r"spac", re.I),
        "width": re.compile(r"width|min\s*width", re.I),
        "density": re.compile(r"density", re.I),
        "antenna": re.compile(r"antenna", re.I),
        "via": re.compile(r"\bvia\b", re.I),
        "enclosure": re.compile(r"enclos", re.I),
    }
    count_re = re.compile(r"\b(\d+)\s*(violation|error|issue|total)", re.I)
    cats_found: List[str] = []
    has_count = False
    best_file = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        for cat, regex in categories_re.items():
            if regex.search(text) and cat not in cats_found:
                cats_found.append(cat)
        if count_re.search(text):
            has_count = True
        if not best_file:
            best_file = str(fp)

    for cat, regex in categories_re.items():
        if cat not in cats_found:
            result.findings.append(Finding(
                rule="DRC_CATEGORY_PRESENT", severity="WARNING",
                message=f"DRC category '{cat}' not found in reports",
                file=best_file))

    if not cats_found:
        result.findings.append(Finding(
            rule="DRC_CATEGORIES_EXIST", severity="ERROR",
            message="No DRC violation categories found in report",
            file=best_file))
    if not has_count:
        result.findings.append(Finding(
            rule="DRC_VIOLATION_COUNT", severity="WARNING",
            message="No violation count pattern found in DRC report",
            file=best_file))

    # Tool-authenticity check — rejects hand-typed stubs (added 2026-04-22)
    authentic = _check_tool_authenticity(files, "drc", result)

    result.passed = len(cats_found) > 0 and authentic
    result.summary = {"files_found": len(files), "categories_found": cats_found,
                      "has_count": has_count, "tool_authentic": authentic}
    return result


def _lvs_blocked_verdict(project_dir: Path) -> Optional[dict]:
    """The runner's BLOCKED LVS verdict, or None.

    Reads `reports/phase3/lvs_verdict.json` — the runner's own machine-readable
    verdict artifact — and returns it ONLY when it records a BLOCKED status.
    Any other status, or an absent/unreadable/malformed file, returns None so
    the caller behaves exactly as before. Read-only: the netgen transcript that
    the #189 classifier and this gate both parse is never touched.
    """
    p = Path(project_dir) / "reports" / "phase3" / "lvs_verdict.json"
    try:
        data = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    status = str(data.get("status") or data.get("result") or "").strip().upper()
    return data if status == "BLOCKED" else None


def _check_lvs(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:lvs", passed=False)
    files = _discover(project_dir, ["*lvs*.rpt", "*lvs*.log", "*LVS*.rpt",
                                     "*LVS*.log", "*comp*.out"])
    if not files:
        # A BLOCKED run produces NO netgen report by construction — extraction
        # never ran, because an input could not support it. "No LVS report
        # found" is true but says nothing about WHY, which is the ambiguity
        # BLOCKED exists to remove. When the runner recorded a BLOCKED verdict,
        # report THAT (with the offending file and the missing capability)
        # instead. This never grants a pass: `passed` stays False on both
        # paths — it only replaces an unattributed absence with the reason.
        blocked = _lvs_blocked_verdict(project_dir)
        if blocked:
            result.findings.append(Finding(
                rule="LVS_BLOCKED_INPUT_INCAPABLE", severity="ERROR",
                message=(
                    "LVS is BLOCKED, not failed and not clean: "
                    + str(blocked.get("message")
                          or "an extraction input cannot support extraction")
                    + " No netlist could be extracted, so no compare ran and "
                      "NOTHING is known about this design's LVS state. "
                      "Sign-off must not proceed."),
                file=str(blocked.get("tech_file") or "")))
            result.summary = {"files_found": 0, "categories_found": [],
                              "terminal_verdict": "BLOCKED",
                              "blocked": True,
                              "blocked_finding": blocked.get("finding"),
                              "blocked_input": blocked.get("tech_file")}
            return result
        result.findings.append(Finding(
            rule="LVS_REPORT_EXISTS", severity="ERROR",
            message="No LVS report found (searched *lvs*.rpt/log, *comp*.out)"))
        result.summary = {"files_found": 0, "categories_found": []}
        return result

    categories_re = {
        "instance": re.compile(r"instance", re.I),
        "net": re.compile(r"\bnet\b", re.I),
        "device": re.compile(r"device", re.I),
        "parameter": re.compile(r"parameter", re.I),
    }
    cats_found: List[str] = []
    best_file = ""
    blob = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        blob += "\n" + text
        for cat, regex in categories_re.items():
            if regex.search(text) and cat not in cats_found:
                cats_found.append(cat)
        if not best_file:
            best_file = str(fp)

    if not cats_found:
        result.findings.append(Finding(
            rule="LVS_CATEGORIES_EXIST", severity="ERROR",
            message="No LVS mismatch categories found in report",
            file=best_file))

    authentic = _check_tool_authenticity(files, "lvs", result)

    # ORGANIC-20260608 #507 (CRITICAL) — terminal-verdict gate. Pre-#507
    # `passed` was decided SOLELY by (category-keyword present + tool
    # signature), so a report whose netgen verdict is "Netlists do not
    # match." (41×, real spm_e2e) FALSE-PASSed Step-31 LVS sign-off. A
    # real netgen compare ALWAYS prints one of two terminal verdict
    # tokens; the gate must parse them, mirroring the runner's #477
    # step_lvs logic so gate and runner never disagree:
    #   * matched  = "Circuits/Netlists match uniquely" → eligible PASS
    #   * mismatch = "do not match" / "failed pin matching" / "NET
    #                MISMATCH" / "失配" → hard FAIL (named finding)
    #   * neither  = INCOMPLETE (compare killed mid-run) → FAIL (#477)
    # A mismatch token is AUTHORITATIVE: it FAILs even if sub-cells also
    # printed "match uniquely" and even if categories+signature are
    # present. chip-AGNOSTIC: pure netgen verdict-token parse.
    # #524 — the verdict now comes from the SHARED classifier
    # (lvs_verdict_tokens) so this gate and the phase3 runner can never drift
    # again; it also adds the netgen property-error terminal FAIL ('Property
    # errors were found' / 'match uniquely with property errors' — empirically
    # a real LVS fail even when the topology line says 'Circuits match
    # uniquely') and the Final-result guard (a per-subcell 'match uniquely'
    # line in a truncated hierarchical run is INCOMPLETE, never a PASS).
    _verdict_cls = _lvt.classify(blob)
    matched = _verdict_cls == "MATCH"
    mismatched = _verdict_cls == "MISMATCH"
    if mismatched:
        result.findings.append(Finding(
            rule="LVS_NETLISTS_DO_NOT_MATCH", severity="ERROR",
            message=("netgen terminal verdict is a MISMATCH ('Netlists do "
                     "not match.' / 'failed pin matching') — the layout is "
                     "NOT LVS-clean; Step-31 LVS sign-off must FAIL (#507)."),
            file=best_file))
        verdict = "MISMATCH"
    elif matched:
        verdict = "MATCH"
    else:
        result.findings.append(Finding(
            rule="LVS_NO_TERMINAL_VERDICT", severity="ERROR",
            message=("netgen report carries NEITHER 'Circuits match "
                     "uniquely' NOR a mismatch token — the compare did not "
                     "run to completion (INCOMPLETE, not a conclusive "
                     "result); sign-off must FAIL (#507/#477)."),
            file=best_file))
        verdict = "INCOMPLETE"

    # PASS requires: a conclusive MATCH verdict AND a mismatch category
    # keyword found (report structure) AND an authentic tool signature.
    result.passed = (verdict == "MATCH"
                     and len(cats_found) > 0 and authentic)
    result.summary = {"files_found": len(files), "categories_found": cats_found,
                      "tool_authentic": authentic,
                      "terminal_verdict": verdict}
    return result


def _check_power(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:power", passed=False)
    reason = _waived_for_pdk(project_dir, "power")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"power report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    files = _discover(project_dir, ["*power*.rpt", "*power*.log",
                                     "*Power*.rpt", "*Power*.log"])
    if not files:
        result.findings.append(Finding(
            rule="POWER_REPORT_EXISTS", severity="ERROR",
            message="No power report found (searched *power*.rpt/log)"))
        result.summary = {"files_found": 0, "has_leakage": False, "has_dynamic": False}
        return result

    leak_re = re.compile(r"leakage|static\s*power", re.I)
    dyn_re = re.compile(r"dynamic|switching|internal\s*power", re.I)
    has_leak = False
    has_dyn = False
    best_file = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if leak_re.search(text):
            has_leak = True
        if dyn_re.search(text):
            has_dyn = True
        if not best_file:
            best_file = str(fp)

    if not has_leak:
        result.findings.append(Finding(
            rule="POWER_LEAKAGE_REPORTED", severity="ERROR",
            message="No leakage/static power value found in report",
            file=best_file))
    if not has_dyn:
        result.findings.append(Finding(
            rule="POWER_DYNAMIC_REPORTED", severity="ERROR",
            message="No dynamic/switching power value found in report",
            file=best_file))

    authentic = _check_tool_authenticity(files, "power", result)
    result.passed = has_leak and has_dyn and authentic
    result.summary = {"files_found": len(files), "has_leakage": has_leak,
                      "has_dynamic": has_dyn, "tool_authentic": authentic}
    return result


def _check_em(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:em", passed=False)
    reason = _waived_for_pdk(project_dir, "em")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"EM report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    files = _discover(project_dir, ["*em*.rpt", "*electromigration*",
                                     "*EM*.rpt", "*ir*.rpt"])
    if not files:
        result.findings.append(Finding(
            rule="EM_REPORT_EXISTS", severity="ERROR",
            message="No EM report found (searched *em*.rpt, *electromigration*, *ir*.rpt)"))
        result.summary = {"files_found": 0, "has_density": False}
        return result

    density_re = re.compile(r"Javg|Jpeak|mA|A/cm|current\s*density", re.I)
    has_density = False
    best_file = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if density_re.search(text):
            has_density = True
        if not best_file:
            best_file = str(fp)

    if not has_density:
        result.findings.append(Finding(
            rule="EM_DENSITY_VALUES", severity="ERROR",
            message="No current density values (Javg/Jpeak/mA/A/cm) found",
            file=best_file))

    authentic = _check_tool_authenticity(files, "em", result)
    result.passed = has_density and authentic
    result.summary = {"files_found": len(files), "has_density": has_density,
                      "tool_authentic": authentic}
    return result


def _check_ir_drop(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:ir_drop", passed=False)
    reason = _waived_for_pdk(project_dir, "ir_drop")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"IR-drop report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    files = _discover(project_dir, ["*ir*.rpt", "*power_grid*", "*IR*.rpt",
                                     "*ir_drop*", "*voltage_drop*"])
    if not files:
        result.findings.append(Finding(
            rule="IR_REPORT_EXISTS", severity="ERROR",
            message="No IR-drop report found (searched *ir*.rpt, *power_grid*)"))
        result.summary = {"files_found": 0, "has_drop_value": False}
        return result

    drop_re = re.compile(r"mV|%\s*Vdd|voltage\s*drop|IR\s*drop", re.I)
    has_drop = False
    best_file = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if drop_re.search(text):
            has_drop = True
        if not best_file:
            best_file = str(fp)

    if not has_drop:
        result.findings.append(Finding(
            rule="IR_DROP_VALUES", severity="ERROR",
            message="No voltage drop values (mV / %Vdd) found in report",
            file=best_file))

    authentic = _check_tool_authenticity(files, "ir_drop", result)

    # ORGANIC-20260606 #444 — budget comparison: when the runner's
    # ir_drop.json carries worst_ir_uv + budget_uv, the step gate applies
    # the SAME comparison signoff_ladder_run uses, so the step verdict
    # can never PASS beside a memo that reads the same numbers as over
    # budget. Values-present-only reports (legacy) gate as before.
    budget_ok = True
    worst_uv = budget_uv = None
    for rel in ("reports/phase3/ir_drop.json", "reports/ir_drop.json"):
        jp = project_dir / rel
        if not jp.is_file():
            continue
        try:
            jd = json.loads(jp.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(jd, dict) and isinstance(
                jd.get("worst_ir_uv"), (int, float)) and isinstance(
                jd.get("budget_uv"), (int, float)):
            worst_uv, budget_uv = float(jd["worst_ir_uv"]), float(jd["budget_uv"])
            if worst_uv > budget_uv:
                budget_ok = False
                result.findings.append(Finding(
                    rule="IR_OVER_BUDGET", severity="ERROR",
                    message=(f"worst IR drop {worst_uv:.3g} µV exceeds the "
                             f"{budget_uv:.3g} µV budget (#444)"),
                    file=rel))
        break

    result.passed = has_drop and authentic and budget_ok
    result.summary = {"files_found": len(files), "has_drop_value": has_drop,
                      "tool_authentic": authentic,
                      "worst_ir_uv": worst_uv, "budget_uv": budget_uv,
                      "ir_within_budget": budget_ok}
    return result


def _check_sta(project_dir: Path) -> AuditResult:
    result = AuditResult(program="eda_report_audit:sta", passed=False)
    files = _discover(project_dir, ["*sta*.rpt", "*timing*.rpt",
                                     "*STA*.rpt", "*timing*.log"])
    # The `*sta*` glob substring-matches unrelated report classes whose names
    # merely CONTAIN "sta" — most notably "cro**sta**lk" (si_crosstalk.rpt).
    # A Signal-Integrity / crosstalk / noise report is NOT an STA timing
    # report and legitimately carries no OpenSTA/Startpoint signature, so it
    # must not be swept into the STA-mode authenticity check (it would force a
    # spurious STA_NO_TOOL_SIGNATURE FAIL for every project that emits an SI
    # report). Drop files whose names denote a different report class.
    # chip-AGNOSTIC: keyed on report-class name tokens, not any chip's signals.
    _STA_EXCLUDE = ("crosstalk", "si_", "_si.", "noise", "antenna", "drc",
                    "lvs", "_em.", "ir_drop", "power")
    files = [f for f in files
             if not any(tok in f.name.lower() for tok in _STA_EXCLUDE)]
    if not files:
        result.findings.append(Finding(
            rule="STA_REPORT_EXISTS", severity="ERROR",
            message="No STA report found (searched *sta*.rpt, *timing*.rpt)"))
        result.summary = {"files_found": 0, "has_wns_tns": False,
                          "has_setup_hold": False}
        return result

    wns_tns_re = re.compile(r"WNS|TNS|worst\s*negative\s*slack|total\s*negative\s*slack",
                            re.I)
    setup_hold_re = re.compile(r"setup|hold", re.I)
    # An OpenSTA `report_checks` PATH-TABLE report is the per-path equivalent of
    # a WNS/TNS summary: it ends each path with "slack (MET)" / "slack
    # (VIOLATED)" and labels the analysis with "Path Type: max" (= setup) or
    # "min" (= hold). Tiny designs (e.g. spm with a single timing path) emit
    # exactly this table and NEVER the literal "WNS"/"TNS" or "setup"/"hold"
    # summary words — so the strict token search false-FAILed a genuinely real
    # report. Accept the path-table form as satisfying both requirements.
    # chip-AGNOSTIC: matches universal OpenSTA report_checks structure.
    pathtable_slack_re = re.compile(r"slack\s*\((?:MET|VIOLATED)\)", re.I)
    pathtype_re = re.compile(r"Path\s*Type\s*:\s*(?:max|min)", re.I)
    has_wns_tns = False
    has_setup_hold = False
    best_file = ""

    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        has_pathtable = bool(pathtable_slack_re.search(text))
        if wns_tns_re.search(text) or has_pathtable:
            has_wns_tns = True
        if setup_hold_re.search(text) or pathtype_re.search(text) or has_pathtable:
            has_setup_hold = True
        if not best_file:
            best_file = str(fp)

    if not has_wns_tns:
        result.findings.append(Finding(
            rule="STA_WNS_TNS", severity="ERROR",
            message="No WNS/TNS slack values found in STA report",
            file=best_file))
    if not has_setup_hold:
        result.findings.append(Finding(
            rule="STA_SETUP_HOLD", severity="ERROR",
            message="No setup/hold analysis found in STA report",
            file=best_file))

    authentic = _check_tool_authenticity(files, "sta", result)

    # #437(c) — multi-corner SUBSTANCE: a per_corner/ directory IS a
    # multi-corner-STA claim, and the claim needs >= 2 NON-IDENTICAL
    # corner reports. The audited rot: per_corner dirs EMPTY, and corner
    # reports that are byte-identical single-corner copies. No per_corner
    # dir at all = honest single-corner run, no claim, no check.
    # chip-AGNOSTIC: canonical-layout paths + content hashing only.
    corners_ok = True
    corner_reports = 0
    corner_distinct = 0
    corner_dirs = sorted({Path(p) for pat in
                          ("phase*/stage*/sta/per_corner",
                           "reports/phase*/sta/per_corner")
                          for p in glob.glob(str(project_dir / pat))
                          if Path(p).is_dir()})
    for cd in corner_dirs:
        rpts = sorted(p for p in cd.glob("*.rpt")
                      if p.is_file() and p.stat().st_size > 0)
        if not rpts:
            corners_ok = False
            result.findings.append(Finding(
                rule="STA_PER_CORNER_EMPTY", severity="ERROR",
                message="per_corner/ claims multi-corner STA but contains "
                        "no corner report (#437c)",
                file=str(cd)))
            continue
        digests = {hashlib.sha256(p.read_bytes()).hexdigest() for p in rpts}
        corner_reports += len(rpts)
        corner_distinct += len(digests)
        if len(rpts) < 2 or len(digests) < 2:
            corners_ok = False
            result.findings.append(Finding(
                rule="STA_CORNERS_NOT_DISTINCT", severity="ERROR",
                message=f"multi-corner STA requires >=2 non-identical "
                        f"corner reports; found {len(rpts)} report(s), "
                        f"{len(digests)} distinct (#437c)",
                file=str(cd)))

    # ORGANIC-20260606 #442 — explicit single-corner DISCLOSURE: when no
    # per_corner evidence (>=2 distinct corner reports) exists, the STA
    # is single-corner and must say so — never silently wear the step's
    # "multi-corner sign-off" name. Advisory (does not flip passed); the
    # broken-claim cases above (empty dir / identical copies) still FAIL.
    multi_corner_executed = corners_ok and corner_distinct >= 2
    if not multi_corner_executed and corners_ok:
        result.findings.append(Finding(
            rule="STA_SINGLE_CORNER_ONLY", severity="WARNING",
            message=("no multi-corner STA evidence (>=2 distinct "
                     "per-corner reports) — this is a SINGLE-CORNER "
                     "analysis and must not be presented as multi-corner "
                     "sign-off (#442)")))

    result.passed = has_wns_tns and has_setup_hold and authentic and corners_ok
    result.summary = {"files_found": len(files), "has_wns_tns": has_wns_tns,
                      "has_setup_hold": has_setup_hold,
                      "tool_authentic": authentic,
                      "corner_dirs_found": len(corner_dirs),
                      "corner_reports": corner_reports,
                      "corner_reports_distinct": corner_distinct,
                      "multi_corner_substantiated": corners_ok,
                      "multi_corner_executed": multi_corner_executed}
    return result


def _check_antenna(project_dir: Path) -> AuditResult:
    """Antenna (gate-oxide) substance check — the missing sibling of em/ir_drop.
    Step 26 historically gated only on antenna.rpt PRESENCE; this parses the
    violation count so a present-but-violating report FAILs. Modeled on
    _check_em: PDK-waiver aware, FAILs on a missing report, and exactly mirrors
    the EM/IR `program_exit_zero` semantics so it does not regress projects whose
    antenna report is clean."""
    result = AuditResult(program="eda_report_audit:antenna", passed=False)
    reason = _waived_for_pdk(project_dir, "antenna")
    if reason and len(reason) >= 20:
        result.findings.append(Finding(
            rule="WAIVED_TOOL_UNAVAILABLE", severity="INFO",
            message=f"Antenna report waived for this PDK: {reason[:80]}"))
        result.passed = True
        result.summary = {"waived": True, "reason": reason}
        return result
    files = _discover(project_dir, ["*antenna*.rpt", "*antenna*.json",
                                     "*ANT*.rpt"])
    if not files:
        result.findings.append(Finding(
            rule="ANTENNA_REPORT_EXISTS", severity="ERROR",
            message="No antenna report found (searched *antenna*.rpt, *antenna*.json)"))
        result.summary = {"files_found": 0, "violations": None}
        return result

    # Parse violation counts from the OpenROAD check_antennas idiom:
    #   "Found N net violations." / "Found M pin violations."
    #   "antenna check: N net violations, M pin violations"
    #   "antenna clean: YES|NO"
    found_re = re.compile(r"Found\s+(\d+)\s+(?:net|pin|antenna)\s+violation", re.I)
    pair_re = re.compile(r"(\d+)\s+net\s+violations?,?\s+(\d+)\s+pin\s+violations?", re.I)
    clean_re = re.compile(r"antenna\s+clean\s*:\s*(YES|NO|TRUE|FALSE)", re.I)
    total_viol = None
    clean_flag = None
    best_file = ""
    for fp in files:
        try:
            text = fp.read_text(errors="replace")
        except OSError:
            continue
        if not best_file:
            best_file = str(fp)
        m = clean_re.search(text)
        if m:
            clean_flag = m.group(1).upper() in ("YES", "TRUE")
        # Prefer the authoritative "[INFO ANT] Found N net/pin violations" lines;
        # only fall back to the "N net violations, M pin violations" summary line
        # when the Found-lines are absent, so the two never double-count.
        found_hits = list(found_re.finditer(text))
        cnt = 0
        seen = False
        if found_hits:
            for mm in found_hits:
                cnt += int(mm.group(1)); seen = True
        else:
            for mm in pair_re.finditer(text):
                cnt += int(mm.group(1)) + int(mm.group(2)); seen = True
        if seen:
            total_viol = (total_viol or 0) + cnt

    authentic = _check_tool_authenticity(files, "antenna", result)
    # Determine pass: a parseable count of 0 (or an explicit "clean: YES") is a
    # clean antenna result; >0 is a real violation FAIL. A present report with NO
    # parseable count is treated like _check_em's missing-content case → ERROR
    # (catches a malformed/empty antenna report), consistent with the siblings.
    if total_viol is None and clean_flag is None:
        result.findings.append(Finding(
            rule="ANTENNA_VIOLATION_COUNT", severity="ERROR",
            message="No antenna violation count or clean-status found in report",
            file=best_file))
        result.passed = False
    elif (total_viol or 0) > 0 or clean_flag is False:
        result.findings.append(Finding(
            rule="ANTENNA_VIOLATIONS_ZERO", severity="ERROR",
            message=f"Antenna violations present: {total_viol or 'see report'} "
                    f"(net+pin); insert diode or re-route",
            file=best_file))
        result.passed = False
    else:
        result.passed = authentic
    result.summary = {"files_found": len(files), "violations": total_viol,
                      "clean": clean_flag, "tool_authentic": authentic}
    return result


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------
MODE_MAP = {
    "drc": _check_drc,
    "lvs": _check_lvs,
    "power": _check_power,
    "em": _check_em,
    "ir_drop": _check_ir_drop,
    "sta": _check_sta,
    "antenna": _check_antenna,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        description="Multi-mode EDA report compliance checker")
    parser.add_argument("project_dir", help="Project directory to scan")
    parser.add_argument("--mode", required=True, choices=list(MODE_MAP.keys()),
                        help="Report type to check")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        result = AuditResult(program=f"eda_report_audit:{args.mode}", passed=False)
        result.findings.append(Finding(
            rule="PROJECT_DIR_EXISTS", severity="ERROR",
            message=f"Project directory does not exist: {project_dir}"))
        result.summary = {"files_found": 0}
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
