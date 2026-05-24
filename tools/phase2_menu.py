#!/usr/bin/env python3
"""
Phase 2 EDA Tool Fail-Handling Interactive Menu
================================================
When Phase 2 EDA tools (Yosys synthesis, OpenROAD P&R) fail, this menu
provides diagnosis from synth_doctor / pnr_doctor and options to fix,
re-run, or skip.

Usage:
    # Programmatic
    from phase2_menu import Phase2FailMenu
    menu = Phase2FailMenu(stage, tool, error_log, synth_report, pnr_report)
    action = menu.run()

    # CLI
    python3 phase2_menu.py --stage synthesis --tool Yosys --log synth.log
    python3 phase2_menu.py --stage pnr --tool OpenROAD --log pnr.log --drc route_drc.rpt

Actions:
    [1] Apply suggested fix automatically
    [2] View full error log
    [3] View fix code snippet
    [4] Re-run stage (synthesis / P&R)
    [5] Skip this stage
    [6] Run pnr-doctor (if P&R failed)
    [7] Export diagnostic log
    [0] Abort
"""

import sys
import os
import re
import json
import argparse
import subprocess
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from pathlib import Path

# Import doctor modules (try relative, fallback to path-based)
try:
    from synth_doctor import analyze_log as synth_analyze, SynthReport, Diagnosis
except ImportError:
    _tools_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _tools_dir)
    try:
        from synth_doctor import analyze_log as synth_analyze, SynthReport, Diagnosis
    except ImportError:
        synth_analyze = None
        SynthReport = None
        Diagnosis = None

try:
    from pnr_doctor import analyze_pnr as pnr_analyze, PnrReport, PnrDiagnosis
except ImportError:
    try:
        from pnr_doctor import analyze_pnr as pnr_analyze, PnrReport, PnrDiagnosis
    except ImportError:
        pnr_analyze = None
        PnrReport = None
        PnrDiagnosis = None


# ============================================================================
# Auto-Fix Patterns
# ============================================================================

AUTO_FIX_PATTERNS = {
    "UNPACKED_ARRAY": {
        "description": "Flatten unpacked array ports to packed vectors",
        "regex": r"(logic\s*\[\s*(\d+)\s*:\s*(\d+)\s*\])\s+(\w+)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]",
        "fix_fn": "_fix_unpacked_array",
    },
    "MULTI_DRIVER": {
        "description": "Merge multiple always_ff blocks driving the same register",
        "regex": r"always_ff\s+@\s*\(\s*posedge\s+(\w+)\s*\)",
        "fix_fn": "_fix_multi_driver",
        "manual": True,
    },
    "RETURN_IN_FUNC": {
        "description": "Replace 'return value;' with function-name assignment",
        "regex": r"return\s+(\w+)\s*;",
        "replacement": r"__FUNCNAME__ = \1;",
        "fix_fn": "_fix_return_in_func",
    },
    "PAST_IN_COMB": {
        "description": "Replace $past() with shadow register",
        "regex": r"\$past\s*\(\s*(\w+)\s*\)",
        "fix_fn": "_fix_past_in_comb",
        "manual": True,
    },
    "AUTOMATIC_IN_FF": {
        "description": "Move 'automatic' variable declarations to module level",
        "regex": r"automatic\s+(logic|reg|wire)\s+(\[\d+:\d+\]\s+)?(\w+)",
        "fix_fn": "_fix_automatic_in_ff",
        "manual": True,
    },
    "LATCH_INFERENCE": {
        "description": "Add default assignments at top of always_comb",
        "fix_fn": "_fix_latch_inference",
        "manual": True,
    },
}


# ============================================================================
# Auto-Fix Implementations
# ============================================================================

def _fix_unpacked_array(file_path: str, line_num: int) -> Dict:
    """Fix unpacked array by flattening to packed vector."""
    if not os.path.exists(file_path):
        return {"success": False, "reason": f"File not found: {file_path}"}

    with open(file_path, "r") as f:
        lines = f.readlines()

    changes = []
    pattern = re.compile(
        r"(input|output|inout)?\s*(logic|wire|reg)\s*"
        r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+(\w+)\s*"
        r"\[\s*(\d+)\s*:\s*(\d+)\s*\]"
    )

    for i, line in enumerate(lines):
        m = pattern.search(line)
        if m:
            direction = m.group(1) or ""
            sigtype = m.group(2)
            hi_bit = int(m.group(3))
            lo_bit = int(m.group(4))
            name = m.group(5)
            arr_hi = int(m.group(6))
            arr_lo = int(m.group(7))

            elem_width = hi_bit - lo_bit + 1
            arr_size = arr_hi - arr_lo + 1
            total_width = elem_width * arr_size

            new_line = line[:m.start()]
            if direction:
                new_line += f"{direction} "
            new_line += f"{sigtype} [{total_width - 1}:0] {name}_flat"
            new_line += line[m.end():]

            changes.append({
                "line": i + 1,
                "old": line.rstrip(),
                "new": new_line.rstrip(),
                "note": f"// Flatten: {name}[{arr_hi}:{arr_lo}] x [{hi_bit}:{lo_bit}] "
                        f"-> {name}_flat[{total_width - 1}:0]"
            })
            lines[i] = new_line

    if changes:
        with open(file_path, "w") as f:
            f.writelines(lines)
        return {"success": True, "changes": changes}
    return {"success": False, "reason": "Pattern not found in file"}


def _fix_return_in_func(file_path: str, line_num: int) -> Dict:
    """Replace 'return val;' with function-name assignment."""
    if not os.path.exists(file_path):
        return {"success": False, "reason": f"File not found: {file_path}"}

    with open(file_path, "r") as f:
        lines = f.readlines()

    # Find the enclosing function name
    func_name = None
    for i in range(min(line_num - 1, len(lines) - 1), -1, -1):
        m = re.search(r"function\s+(?:automatic\s+)?(?:\w+\s+)?(?:\[[\d:]+\]\s+)?(\w+)\s*[;(]",
                      lines[i])
        if m:
            func_name = m.group(1)
            break

    if not func_name:
        return {"success": False, "reason": "Could not find enclosing function name"}

    changes = []
    for i, line in enumerate(lines):
        m = re.search(r"\breturn\s+(.+?)\s*;", line)
        if m:
            val = m.group(1)
            new_line = line[:m.start()] + f"{func_name} = {val};" + line[m.end():]
            changes.append({
                "line": i + 1,
                "old": line.rstrip(),
                "new": new_line.rstrip(),
            })
            lines[i] = new_line

    if changes:
        with open(file_path, "w") as f:
            f.writelines(lines)
        return {"success": True, "changes": changes}
    return {"success": False, "reason": "'return' statement not found"}


# ============================================================================
# Phase 2 Fail Menu
# ============================================================================

class Phase2FailMenu:
    """Interactive menu for handling Phase 2 EDA tool failures."""

    def __init__(self, stage: str, tool: str, log_path: str,
                 rtl_files: Optional[List[str]] = None,
                 synth_report=None, pnr_report=None,
                 drc_path: Optional[str] = None,
                 project_dir: str = "."):
        self.stage = stage          # "synthesis" or "pnr"
        self.tool = tool            # "Yosys" or "OpenROAD"
        self.log_path = log_path
        self.rtl_files = rtl_files or []
        self.synth_report = synth_report
        self.pnr_report = pnr_report
        self.drc_path = drc_path
        self.project_dir = project_dir
        self.log_entries: List[str] = []

        # Auto-analyze if reports not provided
        if stage == "synthesis" and synth_report is None and synth_analyze:
            self.synth_report = synth_analyze(log_path)
        elif stage == "pnr" and pnr_report is None and pnr_analyze:
            self.pnr_report = pnr_analyze(log_path, drc_path)

        # Extract primary error info
        self.primary_error = self._extract_primary_error()
        self.doctor_diagnosis = self._extract_diagnosis()

        self._log(f"Phase 2 menu opened: stage={stage} tool={tool}")
        self._log(f"Log: {log_path}")

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_entries.append(f"[{ts}] {msg}")

    def _extract_primary_error(self) -> str:
        """Extract the most relevant error message from the log."""
        if not os.path.exists(self.log_path):
            return "Log file not found"

        with open(self.log_path, "r") as f:
            lines = f.readlines()

        for line in lines:
            stripped = line.strip()
            if "ERROR" in stripped or "Error" in stripped:
                return stripped[:120]
        return "Unknown error (no ERROR line found in log)"

    def _extract_diagnosis(self) -> Dict:
        """Extract doctor diagnosis summary."""
        diag = {"pattern": "UNKNOWN", "fix": "Manual review needed",
                "snippet": None, "auto_fixable": False,
                "file_name": None, "line_num": None}

        if self.synth_report and hasattr(self.synth_report, "diagnoses"):
            for d in self.synth_report.diagnoses:
                if d.severity == "ERROR":
                    diag["pattern"] = d.pattern
                    diag["fix"] = d.fix_suggestion
                    diag["snippet"] = d.fix_command
                    diag["file_name"] = d.file_name
                    diag["line_num"] = d.line_num
                    diag["auto_fixable"] = (
                        d.pattern in AUTO_FIX_PATTERNS
                        and not AUTO_FIX_PATTERNS[d.pattern].get("manual", False)
                    )
                    break

        if self.pnr_report and hasattr(self.pnr_report, "diagnoses"):
            for d in self.pnr_report.diagnoses:
                if d.severity == "ERROR":
                    diag["pattern"] = d.pattern
                    diag["fix"] = d.fix_suggestion
                    diag["snippet"] = d.fix_param
                    diag["auto_fixable"] = False
                    break

        return diag

    def _print_header(self):
        diag = self.doctor_diagnosis
        doctor_name = "synth-doctor" if self.stage == "synthesis" else "pnr-doctor"

        print()
        print("=" * 56)
        print(f"  Phase 2 EDA Tool FAILED")
        print("=" * 56)
        print(f"  Stage: {self.stage}")
        print(f"  Tool:  {self.tool}")
        print(f"  Error: {self.primary_error[:70]}")
        if len(self.primary_error) > 70:
            print(f"         {self.primary_error[70:140]}")
        print()
        print(f"  {doctor_name} diagnosis:")
        print(f"    Pattern: {diag['pattern']}")
        print(f"    Fix: {diag['fix']}")
        if diag["file_name"]:
            print(f"    File: {diag['file_name']}:{diag['line_num']}")
        if diag["auto_fixable"]:
            print(f"    Auto-fix: AVAILABLE")
        print()
        print(f"  {'─' * 52}")
        print()
        print("  What would you like to do?")
        print("  [1] Apply suggested fix automatically")
        print("  [2] View full error log")
        print("  [3] View fix code snippet")
        print("  [4] Re-run " + self.stage)
        print("  [5] Skip this stage")
        print("  [6] Run pnr-doctor (if P&R failed)")
        print("  [7] Export diagnostic log")
        print("  [0] Abort")
        print()

    def run(self) -> str:
        """Run interactive menu loop. Returns action string."""
        self._print_header()

        while True:
            try:
                choice = input("  Select [0-7]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                self._log("User aborted (Ctrl+C/EOF)")
                return "abort"

            if choice == "1":
                result = self._apply_fix()
                if result == "fixed":
                    return "fixed_rerun"
            elif choice == "2":
                self._view_log()
            elif choice == "3":
                self._view_snippet()
            elif choice == "4":
                return self._rerun_stage()
            elif choice == "5":
                return self._skip_stage()
            elif choice == "6":
                self._run_pnr_doctor()
            elif choice == "7":
                self._export_log()
            elif choice == "0":
                print("\n  Aborting Phase 2.")
                self._log("User aborted")
                return "abort"
            else:
                print("  Invalid choice. Enter 0-7.")

            print()

    # ──────────────────────────────────────────────────────────────────────
    # Option 1: Apply suggested fix
    # ──────────────────────────────────────────────────────────────────────
    def _apply_fix(self) -> str:
        self._log("User requested auto-fix")
        diag = self.doctor_diagnosis
        pattern = diag["pattern"]

        if pattern not in AUTO_FIX_PATTERNS:
            print(f"\n  No auto-fix available for pattern: {pattern}")
            print(f"  Suggestion: {diag['fix']}")
            self._log(f"No auto-fix for {pattern}")
            return "no_fix"

        fix_info = AUTO_FIX_PATTERNS[pattern]
        if fix_info.get("manual", False):
            print(f"\n  Pattern {pattern} requires manual fix:")
            print(f"  {fix_info['description']}")
            print(f"  Suggestion: {diag['fix']}")
            if diag.get("snippet"):
                print(f"\n  Fix snippet:")
                for line in str(diag["snippet"]).split("\n"):
                    print(f"    {line}")
            self._log(f"Manual fix required for {pattern}")
            return "manual"

        target_file = diag.get("file_name")
        target_line = diag.get("line_num")

        if not target_file:
            # Try to find the RTL file
            if self.rtl_files:
                target_file = self.rtl_files[0]
                print(f"\n  No specific file identified. Using: {target_file}")
            else:
                print(f"\n  Cannot determine target file for fix.")
                print(f"  Please specify the RTL file to fix.")
                target_file = input("  File path: ").strip()
                if not target_file:
                    return "no_fix"

        # Resolve relative path
        if not os.path.isabs(target_file):
            candidates = []
            for root, dirs, files in os.walk(self.project_dir):
                for f in files:
                    if f == os.path.basename(target_file):
                        candidates.append(os.path.join(root, f))
            if candidates:
                target_file = candidates[0]
            else:
                # Try rtl subdirectory
                for prefix in ["rtl/", "src/", ""]:
                    p = os.path.join(self.project_dir, prefix, target_file)
                    if os.path.exists(p):
                        target_file = p
                        break

        if not os.path.exists(target_file):
            print(f"\n  File not found: {target_file}")
            return "no_fix"

        print(f"\n  Applying {pattern} fix to: {target_file}")
        print(f"  Fix: {fix_info['description']}")

        confirm = input("  Proceed? [Y/n] ").strip().lower()
        if confirm not in ("", "y", "yes"):
            print("  Cancelled.")
            return "cancelled"

        # Execute fix
        fix_fn_name = fix_info["fix_fn"]
        fix_fn = globals().get(fix_fn_name)
        if fix_fn:
            result = fix_fn(target_file, target_line or 0)
            if result.get("success"):
                print(f"\n  Fix applied successfully!")
                for ch in result.get("changes", []):
                    print(f"    Line {ch['line']}:")
                    print(f"      - {ch['old']}")
                    print(f"      + {ch['new']}")
                self._log(f"Auto-fix applied: {pattern} in {target_file}")
                print(f"\n  Re-run {self.stage} to verify the fix.")
                return "fixed"
            else:
                print(f"\n  Fix failed: {result.get('reason', 'unknown')}")
                self._log(f"Auto-fix failed: {result.get('reason')}")
                return "fix_failed"
        else:
            print(f"\n  Fix function {fix_fn_name} not found.")
            return "no_fix"

    # ──────────────────────────────────────────────────────────────────────
    # Option 2: View full error log
    # ──────────────────────────────────────────────────────────────────────
    def _view_log(self):
        self._log("User viewed full log")

        if not os.path.exists(self.log_path):
            print(f"\n  Log file not found: {self.log_path}")
            return

        with open(self.log_path, "r") as f:
            lines = f.readlines()

        print(f"\n  {'=' * 52}")
        print(f"  Full Log: {self.log_path} ({len(lines)} lines)")
        print(f"  {'─' * 52}")

        # Show error/warning lines highlighted, with context
        error_lines = set()
        for i, line in enumerate(lines):
            if "ERROR" in line or "Error" in line or "WARNING" in line:
                error_lines.update(range(max(0, i - 2), min(len(lines), i + 3)))

        if error_lines:
            print(f"  Showing {len(error_lines)} relevant lines:\n")
            for i in sorted(error_lines):
                prefix = ">>>" if ("ERROR" in lines[i] or "Error" in lines[i]) else "   "
                print(f"  {prefix} {i+1:4d} | {lines[i].rstrip()}")
        else:
            # Show last 30 lines
            print(f"  (No ERROR lines found. Showing last 30 lines)\n")
            start = max(0, len(lines) - 30)
            for i in range(start, len(lines)):
                print(f"       {i+1:4d} | {lines[i].rstrip()}")

        print(f"\n  Full log: {self.log_path}")

    # ──────────────────────────────────────────────────────────────────────
    # Option 3: View fix code snippet
    # ──────────────────────────────────────────────────────────────────────
    def _view_snippet(self):
        self._log("User viewed fix snippet")
        diag = self.doctor_diagnosis

        print(f"\n  {'=' * 52}")
        print(f"  Fix Snippet for: {diag['pattern']}")
        print(f"  {'─' * 52}")

        if diag.get("snippet"):
            print()
            for line in str(diag["snippet"]).split("\n"):
                print(f"    {line}")
        else:
            print(f"  No code snippet available for this pattern.")

        print(f"\n  Suggestion: {diag['fix']}")

        # Show auto-fix info if available
        pattern = diag["pattern"]
        if pattern in AUTO_FIX_PATTERNS:
            info = AUTO_FIX_PATTERNS[pattern]
            print(f"\n  Auto-fix: {info['description']}")
            if info.get("manual"):
                print(f"  Note: This fix requires manual intervention.")
            else:
                print(f"  This can be applied automatically with option [1].")

        # Show all diagnoses if multiple
        report = self.synth_report or self.pnr_report
        if report and hasattr(report, "diagnoses") and len(report.diagnoses) > 1:
            print(f"\n  All diagnoses ({len(report.diagnoses)}):")
            for i, d in enumerate(report.diagnoses):
                sev = d.severity if hasattr(d, "severity") else "?"
                pat = d.pattern if hasattr(d, "pattern") else "?"
                fix = (d.fix_suggestion if hasattr(d, "fix_suggestion")
                       else d.fix_suggestion if hasattr(d, "fix_suggestion") else "?")
                print(f"    [{sev}] {pat}: {fix}")

    # ──────────────────────────────────────────────────────────────────────
    # Option 4: Re-run stage
    # ──────────────────────────────────────────────────────────────────────
    def _rerun_stage(self) -> str:
        self._log(f"User requested re-run of {self.stage}")
        print(f"\n  Requesting re-run of {self.stage} stage...")
        print(f"  Tool: {self.tool}")

        if self.stage == "synthesis":
            print(f"  The flow orchestrator will re-invoke Yosys synthesis.")
            print(f"  Make sure any RTL fixes have been applied first.")
        elif self.stage == "pnr":
            print(f"  The flow orchestrator will re-invoke OpenROAD P&R.")
            print(f"  Ensure synthesis output (.json netlist) is valid.")

        confirm = input(f"  Re-run {self.stage}? [Y/n] ").strip().lower()
        if confirm in ("", "y", "yes"):
            self._log(f"Re-run {self.stage} confirmed")
            return "rerun"
        else:
            print("  Cancelled.")
            return "cancelled"

    # ──────────────────────────────────────────────────────────────────────
    # Option 5: Skip stage
    # ──────────────────────────────────────────────────────────────────────
    def _skip_stage(self) -> str:
        self._log("User considering skip")

        print(f"\n  !! WARNING: Skip {self.stage} Stage !!")
        print(f"  {'=' * 52}")

        if self.stage == "synthesis":
            print(f"  Skipping synthesis means:")
            print(f"    - No gate-level netlist will be produced")
            print(f"    - P&R, STA, and GDS flow cannot proceed")
            print(f"    - Only RTL simulation is available")
        elif self.stage == "pnr":
            print(f"  Skipping P&R means:")
            print(f"    - No physical layout or GDS")
            print(f"    - Post-layout STA not available")
            print(f"    - Gate-level simulation still possible")

        confirm = input(f"  Type 'SKIP' to confirm: ").strip()
        if confirm == "SKIP":
            self._log(f"Stage {self.stage} SKIPPED by user")
            print(f"  {self.stage} stage skipped. Continuing to next phase.")
            return "skip"
        else:
            print("  Skip cancelled.")
            return "cancelled"

    # ──────────────────────────────────────────────────────────────────────
    # Option 6: Run pnr-doctor
    # ──────────────────────────────────────────────────────────────────────
    def _run_pnr_doctor(self):
        self._log("User ran pnr-doctor")

        if self.stage != "pnr":
            print(f"\n  pnr-doctor is for P&R failures.")
            print(f"  Current stage is '{self.stage}'. Use synth-doctor instead.")

            if self.synth_report and hasattr(self.synth_report, "diagnoses"):
                print(f"\n  synth-doctor results already available:")
                for d in self.synth_report.diagnoses:
                    icon = "!!" if d.severity == "ERROR" else "--"
                    print(f"    {icon} [{d.pattern}] {d.root_cause}")
                    print(f"       Fix: {d.fix_suggestion}")
            return

        # Run pnr-doctor
        if self.pnr_report:
            print(f"\n  pnr-doctor results:")
            print(f"  Status: {self.pnr_report.status}")
            if hasattr(self.pnr_report, "area"):
                print(f"  Area:   {self.pnr_report.area:.0f} um^2")
            if hasattr(self.pnr_report, "drc_violations"):
                print(f"  DRC:    {self.pnr_report.drc_violations} violations")
            if hasattr(self.pnr_report, "timing_slack") and self.pnr_report.timing_slack is not None:
                print(f"  Slack:  {self.pnr_report.timing_slack:.2f} ns")

            if hasattr(self.pnr_report, "diagnoses"):
                for d in self.pnr_report.diagnoses:
                    print(f"\n    [{d.pattern}] {d.severity}")
                    print(f"    Cause: {d.root_cause}")
                    print(f"    Fix:   {d.fix_suggestion}")
                    if hasattr(d, "fix_param") and d.fix_param:
                        print(f"    Cmd:   {d.fix_param}")
        else:
            # Try to run pnr_doctor as subprocess
            doctor_path = os.path.join(os.path.dirname(__file__), "pnr_doctor.py")
            if os.path.exists(doctor_path):
                print(f"\n  Running pnr-doctor on {self.log_path}...")
                cmd = [sys.executable, doctor_path, self.log_path]
                if self.drc_path:
                    cmd.extend(["--drc", self.drc_path])
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    print(result.stdout)
                    if result.stderr:
                        print(f"  stderr: {result.stderr[:200]}")
                except subprocess.TimeoutExpired:
                    print(f"  pnr-doctor timed out.")
            else:
                print(f"  pnr-doctor not found at: {doctor_path}")

    # ──────────────────────────────────────────────────────────────────────
    # Option 7: Export diagnostic log
    # ──────────────────────────────────────────────────────────────────────
    def _export_log(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = self.project_dir if os.path.isdir(self.project_dir) else "."
        log_path = os.path.join(out_dir, f"phase2_diagnostic_{ts}.log")

        diag = self.doctor_diagnosis
        with open(log_path, "w") as f:
            f.write(f"Phase 2 EDA Tool Diagnostic Log\n")
            f.write(f"{'=' * 60}\n")
            f.write(f"Stage:     {self.stage}\n")
            f.write(f"Tool:      {self.tool}\n")
            f.write(f"Log file:  {self.log_path}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n\n")

            f.write(f"Primary Error\n")
            f.write(f"{'-' * 40}\n")
            f.write(f"{self.primary_error}\n\n")

            f.write(f"Doctor Diagnosis\n")
            f.write(f"{'-' * 40}\n")
            f.write(f"Pattern:     {diag['pattern']}\n")
            f.write(f"Fix:         {diag['fix']}\n")
            f.write(f"File:        {diag.get('file_name', 'N/A')}\n")
            f.write(f"Line:        {diag.get('line_num', 'N/A')}\n")
            f.write(f"Auto-fixable: {diag.get('auto_fixable', False)}\n")
            if diag.get("snippet"):
                f.write(f"\nFix snippet:\n{diag['snippet']}\n")

            # All diagnoses
            report = self.synth_report or self.pnr_report
            if report and hasattr(report, "diagnoses"):
                f.write(f"\nAll Diagnoses ({len(report.diagnoses)})\n")
                f.write(f"{'-' * 40}\n")
                for d in report.diagnoses:
                    pat = d.pattern if hasattr(d, "pattern") else "?"
                    sev = d.severity if hasattr(d, "severity") else "?"
                    f.write(f"[{sev}] {pat}\n")
                    if hasattr(d, "root_cause"):
                        f.write(f"  Cause: {d.root_cause}\n")
                    if hasattr(d, "fix_suggestion"):
                        f.write(f"  Fix:   {d.fix_suggestion}\n")
                    f.write("\n")

            # Session log
            f.write(f"\nSession Log\n")
            f.write(f"{'-' * 40}\n")
            for entry in self.log_entries:
                f.write(f"{entry}\n")

        print(f"\n  Diagnostic log saved: {log_path}")
        self._log(f"Exported diagnostic log to {log_path}")


# ============================================================================
# Non-Interactive API
# ============================================================================

def handle_eda_failure(stage: str, tool: str, log_path: str,
                       rtl_files: Optional[List[str]] = None,
                       drc_path: Optional[str] = None,
                       project_dir: str = ".",
                       auto_mode: bool = False) -> str:
    """
    Convenience function: analyze failure and show menu.

    Returns:
        'fixed_rerun' - auto-fix applied, re-run recommended
        'rerun'       - user wants to re-run
        'skip'        - user wants to skip stage
        'abort'       - user aborted
    """
    menu = Phase2FailMenu(
        stage=stage, tool=tool, log_path=log_path,
        rtl_files=rtl_files, drc_path=drc_path,
        project_dir=project_dir,
    )

    if auto_mode:
        # Try auto-fix if available
        diag = menu.doctor_diagnosis
        if diag.get("auto_fixable") and diag.get("file_name"):
            pattern = diag["pattern"]
            fix_info = AUTO_FIX_PATTERNS.get(pattern, {})
            fix_fn = globals().get(fix_info.get("fix_fn", ""))
            if fix_fn:
                print(f"\n  [AUTO] Attempting fix for {pattern}...")
                result = fix_fn(diag["file_name"], diag.get("line_num", 0))
                if result.get("success"):
                    print(f"  [AUTO] Fix applied. Re-running {stage}.")
                    return "fixed_rerun"
        print(f"\n  [AUTO] No auto-fix available. Aborting.")
        return "abort"

    return menu.run()


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase 2 EDA Tool Fail-Handling Menu")
    parser.add_argument("--stage", required=True,
                        choices=["synthesis", "pnr"],
                        help="EDA stage that failed")
    parser.add_argument("--tool", default=None,
                        help="Tool name (default: Yosys/OpenROAD)")
    parser.add_argument("--log", required=True,
                        help="Path to error log file")
    parser.add_argument("--drc", default=None,
                        help="Path to DRC report (for P&R)")
    parser.add_argument("--rtl", nargs="*", default=[],
                        help="RTL source files")
    parser.add_argument("--project-dir", default=".",
                        help="Project directory")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-fix mode (no interaction)")
    args = parser.parse_args()

    if args.tool is None:
        args.tool = "Yosys" if args.stage == "synthesis" else "OpenROAD"

    action = handle_eda_failure(
        stage=args.stage, tool=args.tool, log_path=args.log,
        rtl_files=args.rtl, drc_path=args.drc,
        project_dir=args.project_dir, auto_mode=args.auto,
    )

    print(f"\n  Final action: {action}")
    sys.exit(0 if action in ("fixed_rerun", "rerun", "skip") else 1)


if __name__ == "__main__":
    main()
