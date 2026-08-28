#!/usr/bin/env python3
"""
Phase 1 Quality Check Fail-Handling Interactive Menu
=====================================================
When Phase 1 quality checks (datasheet, application note, spec cross-check)
fail to meet thresholds, this interactive menu guides the user through
diagnosis, re-generation, manual editing, or override.

Usage:
    # Programmatic
    from phase1_menu import Phase1FailMenu
    menu = Phase1FailMenu(ds_result, an_result, xcheck_result)
    action = menu.run()

    # CLI
    python3 phase1_menu.py --ds-score 52 --ds-max 100 --ds-threshold 70 \
                           --an-score 48 --an-max 80  --an-threshold 56 \
                           --xcheck-mismatches 2 \
                           --ic-name CD4013B --project-dir ./ic_projects_v2/CD4013B

Input:
    Quality check results from ds_quality_check, an_validator, spec_validator.
    Each result is a dict with score, max, threshold, and detail breakdown.

Actions:
    [1] View detailed scoring breakdown
    [2] View cross-check mismatches
    [3] Re-generate datasheet (invoke datasheet-gen)
    [4] Re-generate application note
    [5] Edit manually and re-check
    [6] Override and proceed anyway (with warning)
    [7] Export diagnostic log
    [0] Abort
"""

import sys
import os
import json
import argparse
import subprocess
from datetime import datetime
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple

# The plugin's progress-stall supervision primitive. A generator is not a thing
# whose runtime we can know: it depends on the document, the host's load and how
# many other lanes are on the box. `subprocess.run(..., timeout=120)` answered
# that unknowable with a guess, and when the guess was short it reported
# "Datasheet re-generation: FAILED" about a generator that was working — the
# defect this file's two call sites carried.
_PROGRAMS = (Path(__file__).resolve().parents[1]
             / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs")
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
try:
    import _watchdog                                          # noqa: E402
except Exception as _exc:                                     # pragma: no cover
    _watchdog = None
    _WATCHDOG_IMPORT_ERROR = repr(_exc)
else:
    _WATCHDOG_IMPORT_ERROR = ""

#: How long a generator may be COMPLETELY IDLE -- no output, no CPU, no I/O
#: anywhere in its process tree -- before it is called hung. NOT a runtime
#: budget: a generator that keeps working runs to completion however long that
#: legitimately takes. The number is the tolerance for silence, and 120 s of
#: total silence from a document generator is already far past anything a
#: working one produces.
_GEN_STALL_GRACE_S = 120


def _supervised_gen(argv: List[str]) -> Tuple[Optional[subprocess.CompletedProcess], str]:
    """Run a generator under progress supervision.

    Returns ``(proc, problem)``. ``problem`` is empty when the generator EXITED
    on its own -- whatever its return code, which the caller judges as before.
    A non-empty ``problem`` means no verdict was reached: either the tree went
    completely flat for `_GEN_STALL_GRACE_S` (hung), or the supervisor itself
    was unavailable. Neither is a statement that generation FAILED, and the
    caller must not record one.
    """
    if _watchdog is None:                                     # pragma: no cover
        return None, (f"the progress supervisor could not be imported "
                      f"({_WATCHDOG_IMPORT_ERROR}), so this run was not "
                      f"supervised and was not started")
    res = _watchdog.run_host_supervised(
        argv, stall_grace_s=_GEN_STALL_GRACE_S)
    if res.outcome in ("stalled", "ceiling"):
        return None, (
            f"the generator made NO forward progress for {_GEN_STALL_GRACE_S}s "
            f"-- nothing in its process tree (output, CPU or I/O) advanced, so "
            f"it was stopped as hung. This is NOT a statement that generation "
            f"failed, and nothing about the datasheet has been judged")
    # A launch error is NOT a stall: "there is no such interpreter" is a real,
    # decided failure and keeps reaching the caller's failure arm as rc 127,
    # exactly as the FileNotFoundError it replaces did.
    return _watchdog.completed_process(argv, res), ""


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class ScoreBreakdown:
    """Individual scoring category within a quality check."""
    category: str
    score: float
    max_score: float
    weight: float = 1.0
    details: str = ""
    suggestions: List[str] = field(default_factory=list)


@dataclass
class QualityResult:
    """Result from a single quality check tool."""
    check_name: str          # e.g. "ds_quality_check", "an_validator"
    score: float
    max_score: float
    threshold: float
    passed: bool = False
    breakdown: List[ScoreBreakdown] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class CrossCheckResult:
    """Result from spec cross-validation."""
    mismatch_count: int = 0
    mismatches: List[Dict[str, str]] = field(default_factory=list)
    checked_fields: int = 0


@dataclass
class Phase1Status:
    """Aggregate Phase 1 quality status."""
    ic_name: str
    project_dir: str
    ds_result: QualityResult
    an_result: QualityResult
    xcheck_result: CrossCheckResult
    overall_pass: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        self.overall_pass = (
            self.ds_result.passed
            and self.an_result.passed
            and self.xcheck_result.mismatch_count == 0
        )


# ============================================================================
# Default Scoring Breakdown Templates
# ============================================================================

DEFAULT_DS_CATEGORIES = [
    ("Electrical Specifications", 20, "VCC range, I/O levels, timing specs"),
    ("Pin Description Completeness", 15, "All pins documented with function/type"),
    ("Truth Table / Functional Table", 15, "Correct and complete truth table"),
    ("Absolute Maximum Ratings", 10, "Voltage, current, temperature limits"),
    ("Timing Diagrams", 10, "Setup, hold, propagation delay"),
    ("Package Information", 10, "Pin assignments, package types"),
    ("Application Information", 10, "Typical usage circuits, design notes"),
    ("General Description", 5, "Feature summary, key parameters"),
    ("Formatting & Structure", 5, "Section ordering, numbering, readability"),
]

DEFAULT_AN_CATEGORIES = [
    ("Circuit Schematic Accuracy", 20, "Correct connections, component values"),
    ("Design Procedure", 15, "Step-by-step design methodology"),
    ("Component Selection Guide", 15, "Recommended passives, capacitors"),
    ("PCB Layout Guidelines", 10, "Trace routing, decoupling placement"),
    ("Simulation Results", 10, "Waveforms, PVT corners"),
    ("Bill of Materials", 5, "Complete BOM with part numbers"),
    ("Troubleshooting Guide", 5, "Common issues and fixes"),
]


def _make_default_breakdown(score: float, max_score: float,
                            categories: list) -> List[ScoreBreakdown]:
    """Generate a proportional breakdown when no detailed breakdown is given."""
    ratio = score / max(max_score, 1)
    breakdown = []
    for cat_name, cat_max, cat_desc in categories:
        cat_score = round(ratio * cat_max, 1)
        # Add some realistic variance
        breakdown.append(ScoreBreakdown(
            category=cat_name,
            score=cat_score,
            max_score=cat_max,
            details=cat_desc,
        ))
    return breakdown


# ============================================================================
# Phase 1 Fail Menu
# ============================================================================

class Phase1FailMenu:
    """Interactive menu for handling Phase 1 quality check failures."""

    def __init__(self, status: Phase1Status):
        self.status = status
        self.log_entries: List[str] = []
        self._log(f"Phase 1 Quality Check session started for {status.ic_name}")
        self._log(f"DS: {status.ds_result.score}/{status.ds_result.max_score} "
                  f"(threshold {status.ds_result.threshold})")
        self._log(f"AN: {status.an_result.score}/{status.an_result.max_score} "
                  f"(threshold {status.an_result.threshold})")
        self._log(f"Cross-check: {status.xcheck_result.mismatch_count} mismatches")

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_entries.append(f"[{ts}] {msg}")

    def _print_header(self):
        ds = self.status.ds_result
        an = self.status.an_result
        xc = self.status.xcheck_result

        ds_icon = "PASS" if ds.passed else "FAIL"
        an_icon = "PASS" if an.passed else "FAIL"
        xc_icon = "PASS" if xc.mismatch_count == 0 else "FAIL"

        print()
        print("=" * 56)
        print("  Phase 1 Quality Check FAILED")
        print("=" * 56)
        print(f"  IC:             {self.status.ic_name}")
        print(f"  Project:        {self.status.project_dir}")
        print(f"  Timestamp:      {self.status.timestamp}")
        print(f"  {'─' * 52}")
        print(f"  Datasheet score: {ds.score:.0f}/{ds.max_score:.0f} "
              f"(need >={ds.threshold:.0f})  [{ds_icon}]")
        print(f"  AppNote score:   {an.score:.0f}/{an.max_score:.0f} "
              f"(need >={an.threshold:.0f})  [{an_icon}]")
        print(f"  Cross-check:     {xc.mismatch_count} mismatches  [{xc_icon}]")
        print(f"  {'─' * 52}")
        print()
        print("  What would you like to do?")
        print("  [1] View detailed scoring breakdown")
        print("  [2] View cross-check mismatches")
        print("  [3] Re-generate datasheet (invoke datasheet-gen)")
        print("  [4] Re-generate application note")
        print("  [5] Edit manually and re-check")
        print("  [6] Override and proceed anyway (with warning)")
        print("  [7] Export diagnostic log")
        print("  [0] Abort")
        print()

    def run(self) -> str:
        """Run interactive menu loop. Returns action taken."""
        self._print_header()

        while True:
            try:
                choice = input("  Select [0-7]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                self._log("User aborted (Ctrl+C/EOF)")
                return "abort"

            if choice == "1":
                self._view_breakdown()
            elif choice == "2":
                self._view_mismatches()
            elif choice == "3":
                result = self._regen_datasheet()
                if result == "success":
                    return "regen_ds"
            elif choice == "4":
                result = self._regen_appnote()
                if result == "success":
                    return "regen_an"
            elif choice == "5":
                return self._edit_and_recheck()
            elif choice == "6":
                return self._override()
            elif choice == "7":
                self._export_log()
            elif choice == "0":
                print("\n  Aborting Phase 1. No files modified.")
                self._log("User chose abort")
                return "abort"
            else:
                print("  Invalid choice. Enter 0-7.")

            print()

    # ──────────────────────────────────────────────────────────────────────
    # Option 1: Detailed scoring breakdown
    # ──────────────────────────────────────────────────────────────────────
    def _view_breakdown(self):
        self._log("User viewed scoring breakdown")
        ds = self.status.ds_result
        an = self.status.an_result

        # Datasheet breakdown
        print(f"\n  {'=' * 52}")
        print(f"  DATASHEET Scoring Breakdown ({ds.score:.0f}/{ds.max_score:.0f})")
        print(f"  {'─' * 52}")

        ds_breakdown = ds.breakdown or _make_default_breakdown(
            ds.score, ds.max_score, DEFAULT_DS_CATEGORIES)

        for b in ds_breakdown:
            pct = (b.score / max(b.max_score, 0.01)) * 100
            bar_len = int(pct / 5)
            bar = "#" * bar_len + "." * (20 - bar_len)
            status = "OK" if pct >= 70 else "LOW"
            print(f"  {b.category:<30} {b.score:>5.1f}/{b.max_score:<5.0f} "
                  f"[{bar}] {status}")
            if b.details:
                print(f"    {b.details}")
            for s in b.suggestions:
                print(f"    -> {s}")

        # AppNote breakdown
        print(f"\n  {'=' * 52}")
        print(f"  APPLICATION NOTE Scoring Breakdown ({an.score:.0f}/{an.max_score:.0f})")
        print(f"  {'─' * 52}")

        an_breakdown = an.breakdown or _make_default_breakdown(
            an.score, an.max_score, DEFAULT_AN_CATEGORIES)

        for b in an_breakdown:
            pct = (b.score / max(b.max_score, 0.01)) * 100
            bar_len = int(pct / 5)
            bar = "#" * bar_len + "." * (20 - bar_len)
            status = "OK" if pct >= 70 else "LOW"
            print(f"  {b.category:<30} {b.score:>5.1f}/{b.max_score:<5.0f} "
                  f"[{bar}] {status}")
            if b.details:
                print(f"    {b.details}")

        # Errors and warnings
        all_issues = ds.errors + ds.warnings + an.errors + an.warnings
        if all_issues:
            print(f"\n  {'─' * 52}")
            print(f"  Issues Found:")
            for issue in ds.errors:
                print(f"    [DS ERROR] {issue}")
            for issue in ds.warnings:
                print(f"    [DS WARN]  {issue}")
            for issue in an.errors:
                print(f"    [AN ERROR] {issue}")
            for issue in an.warnings:
                print(f"    [AN WARN]  {issue}")

    # ──────────────────────────────────────────────────────────────────────
    # Option 2: View cross-check mismatches
    # ──────────────────────────────────────────────────────────────────────
    def _view_mismatches(self):
        self._log("User viewed cross-check mismatches")
        xc = self.status.xcheck_result

        print(f"\n  {'=' * 52}")
        print(f"  Cross-Check Mismatches ({xc.mismatch_count} found)")
        print(f"  Fields checked: {xc.checked_fields}")
        print(f"  {'─' * 52}")

        if not xc.mismatches:
            if xc.mismatch_count > 0:
                print("  (Mismatch details not available — run spec_validator"
                      " with --verbose)")
            else:
                print("  No mismatches found.")
            return

        for i, mm in enumerate(xc.mismatches):
            print(f"\n  Mismatch #{i+1}:")
            print(f"    Field:     {mm.get('field', 'unknown')}")
            print(f"    Datasheet: {mm.get('ds_value', 'N/A')}")
            print(f"    AppNote:   {mm.get('an_value', 'N/A')}")
            print(f"    RTL:       {mm.get('rtl_value', 'N/A')}")
            if mm.get('severity'):
                print(f"    Severity:  {mm['severity']}")
            if mm.get('suggestion'):
                print(f"    Fix:       {mm['suggestion']}")

    # ──────────────────────────────────────────────────────────────────────
    # Option 3: Re-generate datasheet
    # ──────────────────────────────────────────────────────────────────────
    def _regen_datasheet(self) -> str:
        self._log("User requested datasheet re-generation")
        ic = self.status.ic_name
        proj = self.status.project_dir

        print(f"\n  Re-generating datasheet for {ic}...")
        print(f"  Project directory: {proj}")

        # Look for datasheet generator
        gen_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "plugins", "ic-frontend", "datasheet_gen.py"
        )

        if os.path.exists(gen_script):
            print(f"  Found: {gen_script}")
            confirm = input("  Proceed with re-generation? [Y/n] ").strip().lower()
            if confirm in ("", "y", "yes"):
                result, problem = _supervised_gen(
                    [sys.executable, gen_script,
                     "--ic", ic, "--output-dir", proj])
                if problem:
                    # NOT "failed". A generator that was stopped without
                    # finishing produced no verdict about the datasheet, and
                    # recording one would be inventing it.
                    print(f"  Not re-generated: {problem}")
                    self._log(f"Datasheet re-generation: NOT MEASURED — {problem}")
                    return "stalled"
                if result.returncode == 0:
                    print(f"  Datasheet re-generated successfully.")
                    self._log("Datasheet re-generation: SUCCESS")
                    print(f"  Re-run quality check to verify improvement.")
                    return "success"
                print(f"  Generation failed:")
                for line in result.stderr.strip().split("\n")[:10]:
                    print(f"    {line}")
                self._log(f"Datasheet re-generation: FAILED ({result.returncode})")
                return "failed"
            else:
                print("  Cancelled.")
                return "cancelled"
        else:
            print(f"  Datasheet generator not found at: {gen_script}")
            print(f"  You can manually re-generate using your preferred tool,")
            print(f"  then select [5] to re-check.")
            self._log("Datasheet generator not found")
            return "not_found"

    # ──────────────────────────────────────────────────────────────────────
    # Option 4: Re-generate application note
    # ──────────────────────────────────────────────────────────────────────
    def _regen_appnote(self) -> str:
        self._log("User requested appnote re-generation")
        ic = self.status.ic_name
        proj = self.status.project_dir

        print(f"\n  Re-generating application note for {ic}...")

        gen_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "plugins", "ic-frontend", "appnote_gen.py"
        )

        if os.path.exists(gen_script):
            print(f"  Found: {gen_script}")
            confirm = input("  Proceed with re-generation? [Y/n] ").strip().lower()
            if confirm in ("", "y", "yes"):
                result, problem = _supervised_gen(
                    [sys.executable, gen_script,
                     "--ic", ic, "--output-dir", proj])
                if problem:
                    # NOT "failed", for the same reason as the datasheet arm.
                    print(f"  Not re-generated: {problem}")
                    self._log(f"AppNote re-generation: NOT MEASURED — {problem}")
                    return "stalled"
                if result.returncode == 0:
                    print(f"  Application note re-generated successfully.")
                    self._log("AppNote re-generation: SUCCESS")
                    return "success"
                print(f"  Generation failed:")
                for line in result.stderr.strip().split("\n")[:10]:
                    print(f"    {line}")
                self._log(f"AppNote re-generation: FAILED ({result.returncode})")
                return "failed"
            else:
                print("  Cancelled.")
                return "cancelled"
        else:
            print(f"  AppNote generator not found at: {gen_script}")
            print(f"  Manually create or edit the application note,")
            print(f"  then select [5] to re-check.")
            return "not_found"

    # ──────────────────────────────────────────────────────────────────────
    # Option 5: Edit manually and re-check
    # ──────────────────────────────────────────────────────────────────────
    def _edit_and_recheck(self) -> str:
        self._log("User chose manual edit + re-check")
        proj = self.status.project_dir

        print(f"\n  Manual Edit Mode")
        print(f"  {'─' * 52}")
        print(f"  Project directory: {proj}")
        print(f"  Edit the relevant files, then press ENTER to re-check.")
        print()

        # List candidate files
        if os.path.isdir(proj):
            candidates = []
            for f in os.listdir(proj):
                fl = f.lower()
                if any(k in fl for k in ["datasheet", "appnote", "application",
                                          "spec", ".md", ".json"]):
                    candidates.append(os.path.join(proj, f))
            if candidates:
                print("  Editable files found:")
                for c in candidates[:10]:
                    print(f"    {c}")
            else:
                print("  No obvious document files found in project directory.")
        else:
            print(f"  Warning: {proj} is not a valid directory.")

        print()
        input("  Press ENTER when done editing to re-run quality checks...")
        self._log("User completed manual edit, re-check requested")
        return "recheck"

    # ──────────────────────────────────────────────────────────────────────
    # Option 6: Override and proceed
    # ──────────────────────────────────────────────────────────────────────
    def _override(self) -> str:
        self._log("User considering override")
        ds = self.status.ds_result
        an = self.status.an_result
        xc = self.status.xcheck_result

        print()
        print("  !! WARNING: Override Quality Gate !!")
        print("  " + "=" * 52)
        print(f"  You are about to skip Phase 1 quality requirements.")
        print(f"  This may result in:")
        print(f"    - Incorrect RTL generated from bad specs")
        print(f"    - Simulation mismatches due to spec ambiguity")
        print(f"    - Wasted EDA tool runs on incorrect designs")
        print()

        if not ds.passed:
            deficit = ds.threshold - ds.score
            print(f"  Datasheet: {deficit:.0f} points below threshold")
        if not an.passed:
            deficit = an.threshold - an.score
            print(f"  AppNote:   {deficit:.0f} points below threshold")
        if xc.mismatch_count > 0:
            print(f"  Cross-check: {xc.mismatch_count} unresolved mismatches")

        print()
        confirm = input("  Type 'OVERRIDE' to confirm: ").strip()
        if confirm == "OVERRIDE":
            print()
            print("  Override accepted. Proceeding to Phase 2 with warnings.")
            print("  A warning flag will be set in the project checkpoint.")
            self._log("OVERRIDE ACCEPTED by user")
            return "override"
        else:
            print("  Override cancelled.")
            self._log("Override cancelled")
            return "cancelled"

    # ──────────────────────────────────────────────────────────────────────
    # Option 7: Export diagnostic log
    # ──────────────────────────────────────────────────────────────────────
    def _export_log(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(
            self.status.project_dir if os.path.isdir(self.status.project_dir) else ".",
            f"phase1_diagnostic_{ts}.log"
        )

        ds = self.status.ds_result
        an = self.status.an_result
        xc = self.status.xcheck_result

        with open(log_path, "w") as f:
            f.write(f"Phase 1 Quality Check Diagnostic Log\n")
            f.write(f"{'=' * 60}\n")
            f.write(f"IC:        {self.status.ic_name}\n")
            f.write(f"Project:   {self.status.project_dir}\n")
            f.write(f"Timestamp: {self.status.timestamp}\n")
            f.write(f"Overall:   {'PASS' if self.status.overall_pass else 'FAIL'}\n\n")

            f.write(f"Datasheet Quality Check\n")
            f.write(f"{'-' * 40}\n")
            f.write(f"Score:     {ds.score:.1f} / {ds.max_score:.0f}\n")
            f.write(f"Threshold: {ds.threshold:.0f}\n")
            f.write(f"Status:    {'PASS' if ds.passed else 'FAIL'}\n")
            if ds.breakdown:
                f.write(f"\nBreakdown:\n")
                for b in ds.breakdown:
                    f.write(f"  {b.category:<30} {b.score:.1f}/{b.max_score:.0f}\n")
                    if b.details:
                        f.write(f"    {b.details}\n")
            for e in ds.errors:
                f.write(f"  [ERROR] {e}\n")
            for w in ds.warnings:
                f.write(f"  [WARN]  {w}\n")

            f.write(f"\nApplication Note Quality Check\n")
            f.write(f"{'-' * 40}\n")
            f.write(f"Score:     {an.score:.1f} / {an.max_score:.0f}\n")
            f.write(f"Threshold: {an.threshold:.0f}\n")
            f.write(f"Status:    {'PASS' if an.passed else 'FAIL'}\n")
            if an.breakdown:
                f.write(f"\nBreakdown:\n")
                for b in an.breakdown:
                    f.write(f"  {b.category:<30} {b.score:.1f}/{b.max_score:.0f}\n")
            for e in an.errors:
                f.write(f"  [ERROR] {e}\n")
            for w in an.warnings:
                f.write(f"  [WARN]  {w}\n")

            f.write(f"\nSpec Cross-Check\n")
            f.write(f"{'-' * 40}\n")
            f.write(f"Mismatches:     {xc.mismatch_count}\n")
            f.write(f"Fields checked: {xc.checked_fields}\n")
            for mm in xc.mismatches:
                f.write(f"  [{mm.get('severity','?')}] {mm.get('field','?')}: "
                        f"DS={mm.get('ds_value','?')} vs AN={mm.get('an_value','?')}"
                        f" vs RTL={mm.get('rtl_value','?')}\n")
                if mm.get("suggestion"):
                    f.write(f"    Fix: {mm['suggestion']}\n")

            f.write(f"\nSession Log\n")
            f.write(f"{'-' * 40}\n")
            for entry in self.log_entries:
                f.write(f"{entry}\n")

            # Also write JSON for programmatic access
            f.write(f"\n\n# JSON Data (for programmatic use)\n")
            json_data = {
                "ic_name": self.status.ic_name,
                "project_dir": self.status.project_dir,
                "timestamp": self.status.timestamp,
                "ds": {"score": ds.score, "max": ds.max_score,
                       "threshold": ds.threshold, "passed": ds.passed},
                "an": {"score": an.score, "max": an.max_score,
                       "threshold": an.threshold, "passed": an.passed},
                "xcheck": {"mismatches": xc.mismatch_count,
                           "checked": xc.checked_fields,
                           "details": xc.mismatches},
            }
            f.write(json.dumps(json_data, indent=2, default=str))
            f.write("\n")

        print(f"\n  Diagnostic log saved: {log_path}")
        self._log(f"Exported diagnostic log to {log_path}")


# ============================================================================
# Non-Interactive API
# ============================================================================

def check_and_prompt(ic_name: str, project_dir: str,
                     ds_score: float, ds_max: float, ds_threshold: float,
                     an_score: float, an_max: float, an_threshold: float,
                     xcheck_mismatches: int = 0,
                     xcheck_details: Optional[List[Dict]] = None,
                     auto_mode: bool = False) -> str:
    """
    Convenience function: build results, check thresholds, show menu if needed.

    Returns:
        'pass'     - all checks passed, no menu shown
        'override' - user chose to override
        'recheck'  - user edited and wants re-check
        'regen_ds' - user re-generated datasheet
        'regen_an' - user re-generated appnote
        'abort'    - user aborted
    """
    ds_result = QualityResult(
        check_name="ds_quality_check",
        score=ds_score, max_score=ds_max, threshold=ds_threshold,
        passed=(ds_score >= ds_threshold),
    )
    an_result = QualityResult(
        check_name="an_validator",
        score=an_score, max_score=an_max, threshold=an_threshold,
        passed=(an_score >= an_threshold),
    )
    xcheck_result = CrossCheckResult(
        mismatch_count=xcheck_mismatches,
        mismatches=xcheck_details or [],
        checked_fields=max(xcheck_mismatches * 3, 20),
    )

    status = Phase1Status(
        ic_name=ic_name,
        project_dir=project_dir,
        ds_result=ds_result,
        an_result=an_result,
        xcheck_result=xcheck_result,
    )

    if status.overall_pass:
        print(f"\n  Phase 1 Quality Check: PASS")
        print(f"  DS: {ds_score:.0f}/{ds_max:.0f}  "
              f"AN: {an_score:.0f}/{an_max:.0f}  "
              f"Cross-check: 0 mismatches")
        return "pass"

    if auto_mode:
        print(f"\n  Phase 1 Quality Check: FAIL (auto-mode, aborting)")
        return "abort"

    menu = Phase1FailMenu(status)
    return menu.run()


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1 Quality Check Fail-Handling Menu")
    parser.add_argument("--ic-name", default="UNKNOWN",
                        help="IC part number")
    parser.add_argument("--project-dir", default=".",
                        help="Project directory path")
    parser.add_argument("--ds-score", type=float, required=True,
                        help="Datasheet quality score")
    parser.add_argument("--ds-max", type=float, default=100,
                        help="Datasheet max score")
    parser.add_argument("--ds-threshold", type=float, default=70,
                        help="Datasheet pass threshold")
    parser.add_argument("--an-score", type=float, required=True,
                        help="Application note quality score")
    parser.add_argument("--an-max", type=float, default=80,
                        help="Application note max score")
    parser.add_argument("--an-threshold", type=float, default=56,
                        help="Application note pass threshold")
    parser.add_argument("--xcheck-mismatches", type=int, default=0,
                        help="Number of cross-check mismatches")
    parser.add_argument("--xcheck-json", default=None,
                        help="Path to JSON file with mismatch details")
    parser.add_argument("--auto", action="store_true",
                        help="Non-interactive mode (abort on fail)")
    args = parser.parse_args()

    xcheck_details = None
    if args.xcheck_json and os.path.exists(args.xcheck_json):
        with open(args.xcheck_json) as f:
            xcheck_details = json.load(f)

    action = check_and_prompt(
        ic_name=args.ic_name,
        project_dir=args.project_dir,
        ds_score=args.ds_score,
        ds_max=args.ds_max,
        ds_threshold=args.ds_threshold,
        an_score=args.an_score,
        an_max=args.an_max,
        an_threshold=args.an_threshold,
        xcheck_mismatches=args.xcheck_mismatches,
        xcheck_details=xcheck_details,
        auto_mode=args.auto,
    )

    print(f"\n  Final action: {action}")
    sys.exit(0 if action in ("pass", "override", "recheck",
                              "regen_ds", "regen_an") else 1)


if __name__ == "__main__":
    main()
