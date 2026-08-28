#!/usr/bin/env python3
"""
flow-runner -- Vibe-IC Pipeline Orchestrator (Phase 1 -> 2 -> 3)
==================================================================
Orchestrates the full three-phase Vibe-IC flow with automatic error
handling, doctor diagnosis, and interactive menus on failure.

Usage:
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --auto
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --phase 1
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --phase 2 --auto

Phase 1 flow (Specification Quality):
    1. Check if 04_datasheet.md exists
    2. Run ds_quality_check.py -> if score < 70, call phase1_menu
    3. Run an_validator.py -> if score < 56, call phase1_menu
    4. Run spec_validator.py -> if mismatches > 0, call phase1_menu
    5. Log results to pipeline.jsonl via vibe_ic_log

Phase 2 flow (RTL -> Synthesis -> P&R):
    1. Check if RTL exists
    2. Run yosys synthesis
    3. If synth fails -> run synth_doctor.py -> call phase2_menu
    4. If synth passes -> log cell count
    5. Check SVA count >= 8
    6. Log results to pipeline.jsonl

Phase 3 flow (FPGA Verification):
    1. Check if SOF exists or Quartus available
    2. Log results

All steps logged via vibe_ic_log.py.
--auto flag runs without interactive menus (use defaults).
Exit code 0 if all pass, 1 if any fail.
"""

import os
import re
import sys
import time
import glob
import json
import argparse
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

# ---------------------------------------------------------------------------
# Resolve imports from the same directory
# ---------------------------------------------------------------------------
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from vibe_ic_log import VibeICLog
from ds_quality_check import score_datasheet
from an_validator import score_appnote
from spec_validator import validate_consistency
from synth_doctor import analyze_log as synth_analyze
from pnr_doctor import analyze_pnr as pnr_analyze
from phase1_menu import check_and_prompt as phase1_prompt
from phase2_menu import handle_eda_failure as phase2_prompt

# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, so
# this works from `tools/` and from inside the flattened plugin cache.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402


# ============================================================================
# Constants
# ============================================================================

DS_THRESHOLD = 70       # datasheet score must be >= 70/100
AN_THRESHOLD = 56       # appnote score must be >= 56/80
SVA_MIN_COUNT = 8       # minimum SVA assertion count

PHASE_NAMES = {1: "Specification Quality", 2: "RTL/Synth/P&R", 3: "FPGA Verification"}


# ============================================================================
# Helper utilities
# ============================================================================

def _icon(status: str) -> str:
    """Return a status icon string."""
    return {"PASS": "\u2705", "FAIL": "\u274c", "WARN": "\u26a0\ufe0f",
            "SKIP": "\u23ed\ufe0f"}.get(status, "?")


def _ic_name_from_dir(ic_dir: str) -> str:
    """Extract IC name from directory path like ic_001_CD4013B -> CD4013B."""
    base = os.path.basename(os.path.normpath(ic_dir))
    # Pattern: ic_NNN_NAME or just the dir name
    m = re.match(r'ic_\d+_(.+)', base)
    return m.group(1) if m else base


def _find_file(ic_dir: str, *candidates: str) -> Optional[str]:
    """Find the first existing file from a list of relative candidates."""
    for c in candidates:
        p = os.path.join(ic_dir, c)
        if os.path.exists(p):
            return p
    return None


def _count_sva_assertions(rtl_dir: str) -> int:
    """Count SVA assertion statements in all .sv files under rtl_dir."""
    count = 0
    if not os.path.isdir(rtl_dir):
        return 0
    for sv_file in glob.glob(os.path.join(rtl_dir, "*.sv")):
        try:
            text = Path(sv_file).read_text(encoding='utf-8', errors='replace')
            # Count assert property, assume, cover property
            count += len(re.findall(
                r'\b(?:assert|assume|cover)\s+property\b', text, re.IGNORECASE))
            # Also count simple immediate assertions
            count += len(re.findall(
                r'\b(?:assert)\s*\(', text))
        except Exception:
            pass
    return count


def _log_step(ic_name: str, phase: int, stage: str, tool: str,
              status: str, metrics: Dict[str, Any],
              errors: List[str], duration: float,
              log_path: str):
    """Create and append a VibeICLog entry."""
    entry = VibeICLog(
        ic_name=ic_name,
        phase=phase,
        stage=stage,
        tool=tool,
        status=status,
        metrics=metrics,
        errors=errors,
        duration_sec=duration,
    )
    entry.append(log_path)
    return entry


def _print_step(phase: int, step: str, status: str, detail: str = ""):
    """Print a formatted step result."""
    icon = _icon(status)
    prefix = f"  [Phase {phase}]"
    msg = f"{prefix} {icon} {step}"
    if detail:
        msg += f" -- {detail}"
    print(msg)


# ============================================================================
# Phase 1: Specification Quality
# ============================================================================

def run_phase1(ic_dir: str, ic_name: str, log_path: str,
               auto: bool = False) -> bool:
    """Run Phase 1 quality checks. Returns True if all pass."""
    print(f"\n{'='*60}")
    print(f"  Phase 1: Specification Quality -- {ic_name}")
    print(f"{'='*60}")

    all_pass = True

    # ── Step 1.1: Check datasheet exists ──
    t0 = time.time()
    ds_path = _find_file(ic_dir, "04_datasheet.md",
                         "docs/datasheet/datasheet.md",
                         f"docs/datasheet/{ic_name.lower()}-datasheet.md")
    if not ds_path:
        _print_step(1, "Datasheet exists", "FAIL", "04_datasheet.md not found")
        _log_step(ic_name, 1, "ds_exists", "flow_runner", "FAIL",
                  {}, ["04_datasheet.md not found"], time.time() - t0, log_path)
        return False
    _print_step(1, "Datasheet exists", "PASS", os.path.basename(ds_path))
    _log_step(ic_name, 1, "ds_exists", "flow_runner", "PASS",
              {"file": ds_path}, [], time.time() - t0, log_path)

    # ── Step 1.2: Check appnote exists ──
    t0 = time.time()
    an_path = _find_file(ic_dir, "05_appnote.md",
                         "docs/appnote/appnote.md",
                         f"docs/appnote/{ic_name.lower()}-appnote.md")
    if not an_path:
        _print_step(1, "Application Note exists", "FAIL", "05_appnote.md not found")
        _log_step(ic_name, 1, "an_exists", "flow_runner", "FAIL",
                  {}, ["05_appnote.md not found"], time.time() - t0, log_path)
        return False
    _print_step(1, "Application Note exists", "PASS", os.path.basename(an_path))
    _log_step(ic_name, 1, "an_exists", "flow_runner", "PASS",
              {"file": an_path}, [], time.time() - t0, log_path)

    # ── Step 1.3: ds_quality_check ──
    t0 = time.time()
    ds_result = score_datasheet(ds_path)
    ds_score = ds_result.get("total_score", 0)
    ds_max = ds_result.get("max_score", 100)
    ds_dur = time.time() - t0

    ds_status = "PASS" if ds_score >= DS_THRESHOLD else "FAIL"
    _print_step(1, "Datasheet quality", ds_status,
                f"{ds_score}/{ds_max} (threshold {DS_THRESHOLD})")
    _log_step(ic_name, 1, "ds_quality", "ds_quality_check", ds_status,
              {"score": ds_score, "max": ds_max, "threshold": DS_THRESHOLD},
              [] if ds_status == "PASS" else [f"Score {ds_score} < {DS_THRESHOLD}"],
              ds_dur, log_path)

    if ds_status == "FAIL":
        all_pass = False

    # ── Step 1.4: an_validator ──
    t0 = time.time()
    an_result = score_appnote(an_path)
    an_score = an_result.get("total_score", 0)
    an_max = an_result.get("max_score", 80)
    an_dur = time.time() - t0

    an_status = "PASS" if an_score >= AN_THRESHOLD else "FAIL"
    _print_step(1, "Application Note quality", an_status,
                f"{an_score}/{an_max} (threshold {AN_THRESHOLD})")
    _log_step(ic_name, 1, "an_quality", "an_validator", an_status,
              {"score": an_score, "max": an_max, "threshold": AN_THRESHOLD},
              [] if an_status == "PASS" else [f"Score {an_score} < {AN_THRESHOLD}"],
              an_dur, log_path)

    if an_status == "FAIL":
        all_pass = False

    # ── Step 1.5: spec_validator (cross-check DS vs AN) ──
    t0 = time.time()
    spec_path = _find_file(ic_dir, "03_spec_confirmed.md",
                           "docs/spec/spec.md")
    xcheck_result = validate_consistency(ds_path, an_path,
                                         spec_path if spec_path else None)
    xcheck_errors = xcheck_result.get("summary", {}).get("errors", 0)
    xcheck_dur = time.time() - t0

    xcheck_status = "PASS" if xcheck_errors == 0 else "FAIL"
    _print_step(1, "Spec cross-check (DS vs AN)", xcheck_status,
                f"{xcheck_errors} ERROR-level mismatches")
    _log_step(ic_name, 1, "spec_xcheck", "spec_validator", xcheck_status,
              {"error_mismatches": xcheck_errors,
               "total_findings": xcheck_result.get("summary", {}).get("total_checks", 0)},
              [m["message"] for m in xcheck_result.get("mismatches", [])
               if m.get("severity") == "ERROR"][:5],
              xcheck_dur, log_path)

    if xcheck_errors > 0:
        all_pass = False

    # ── Handle failures: invoke phase1_menu ──
    if not all_pass:
        print(f"\n  {_icon('FAIL')} Phase 1 has failures.")
        action = phase1_prompt(
            ic_name=ic_name,
            project_dir=ic_dir,
            ds_score=ds_score,
            ds_max=ds_max,
            ds_threshold=DS_THRESHOLD,
            an_score=an_score,
            an_max=an_max,
            an_threshold=AN_THRESHOLD,
            xcheck_mismatches=xcheck_errors,
            xcheck_details=xcheck_result.get("mismatches"),
            auto_mode=auto,
        )
        _log_step(ic_name, 1, "phase1_menu", "phase1_menu",
                  "PASS" if action in ("pass", "override") else "FAIL",
                  {"action": action}, [], 0, log_path)

        if action == "override":
            print(f"  {_icon('WARN')} Phase 1 overridden by user. Proceeding with warnings.")
            return True
        elif action in ("abort",):
            print(f"  {_icon('FAIL')} Phase 1 aborted.")
            return False
        # recheck / regen cases -- for now treat as fail (user should re-run)
        elif action in ("recheck", "regen_ds", "regen_an"):
            print(f"  Action '{action}' completed. Please re-run flow_runner to re-check.")
            return False
        else:
            return False

    print(f"\n  {_icon('PASS')} Phase 1 PASSED: all quality checks met.")
    return True


# ============================================================================
# Phase 2: RTL -> Synthesis -> P&R
# ============================================================================

def run_phase2(ic_dir: str, ic_name: str, log_path: str,
               auto: bool = False) -> bool:
    """Run Phase 2 EDA flow. Returns True if all pass."""
    print(f"\n{'='*60}")
    print(f"  Phase 2: RTL / Synthesis / P&R -- {ic_name}")
    print(f"{'='*60}")

    all_pass = True

    # ── Step 2.1: Check RTL exists ──
    t0 = time.time()
    rtl_dir = os.path.join(ic_dir, "phase2_design", "rtl")
    rtl_files = glob.glob(os.path.join(rtl_dir, "*.sv")) + \
                glob.glob(os.path.join(rtl_dir, "*.v"))

    if not rtl_files:
        _print_step(2, "RTL files exist", "FAIL",
                    f"No .sv/.v files in {rtl_dir}")
        _log_step(ic_name, 2, "rtl_exists", "flow_runner", "FAIL",
                  {}, [f"No RTL in {rtl_dir}"], time.time() - t0, log_path)
        return False

    _print_step(2, "RTL files exist", "PASS",
                f"{len(rtl_files)} file(s) in phase2_design/rtl/")
    _log_step(ic_name, 2, "rtl_exists", "flow_runner", "PASS",
              {"file_count": len(rtl_files),
               "files": [os.path.basename(f) for f in rtl_files]},
              [], time.time() - t0, log_path)

    # ── Step 2.2: Synthesis (Yosys) ──
    t0 = time.time()
    synth_dir = os.path.join(ic_dir, "phase2_design", "synth")
    synth_log = os.path.join(synth_dir, "synth.log")
    synth_netlist = None

    # Look for existing synth.log or try to run synthesis
    if os.path.exists(synth_log):
        _print_step(2, "Synthesis log found", "PASS", synth_log)
    else:
        # Attempt to run yosys synthesis
        _print_step(2, "Synthesis", "WARN",
                    "No synth.log found. Attempting yosys synthesis...")
        os.makedirs(synth_dir, exist_ok=True)

        # Build a simple yosys script
        top_module = ic_name.lower()
        sv_files = " ".join(rtl_files)
        # security hardening: run yosys via argv (shell=False) with the log
        # redirected through a file handle instead of a shell `>`. The former
        # shell=True form interpolated top_module / RTL file paths straight into
        # a shell command — a command-injection vector if either contained
        # shell metacharacters.
        yosys_script = (
            f"read_verilog -sv {sv_files}; "
            f"synth -top {top_module}; "
            f"stat; "
            f"write_verilog {synth_dir}/synth_{top_module}.v"
        )

        # Check if yosys is available
        yosys_avail = subprocess.run(
            ["which", "yosys"], capture_output=True, text=True
        ).returncode == 0

        if yosys_avail:
            # The 300 s bound here was a guess about a HOST, spent as a claim
            # about the synthesis: on a busy machine a yosys run that was
            # working got killed and `synth_analyze` then read a truncated log
            # as a synthesis result. Supervised by forward progress instead —
            # yosys is chatty, so its own output is the progress signal, and a
            # run that is merely slow now finishes.
            #
            # The combined stream is captured and then written to `synth_log`,
            # which is the artefact `synth_analyze` reads below. A stall writes
            # what the child DID emit before going quiet, because a partial log
            # is evidence and an absent one is not.
            try:
                result = _pr.run(
                    ["yosys", "-p", yosys_script],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                _synth_out = result.stdout
            except _pr.Stalled as _exc:
                _synth_out = (_exc.stdout or "") + f"\n[flow_runner] {_exc}\n"
                result = subprocess.CompletedProcess(
                    ["yosys"], _pr.RC_STALLED, _synth_out, "")
            with open(synth_log, "w") as _logf:
                _logf.write(_synth_out)
        else:
            _print_step(2, "Yosys available", "SKIP",
                        "yosys not installed, checking existing logs only")
            _log_step(ic_name, 2, "synth", "yosys", "SKIP",
                      {}, ["yosys not installed"], time.time() - t0, log_path)

    # Analyze synthesis results
    synth_dur = time.time() - t0
    if os.path.exists(synth_log):
        synth_report = synth_analyze(synth_log)
        cell_count = synth_report.cell_count
        synth_status = synth_report.status  # PASS, WARN, or FAIL

        _print_step(2, "Synthesis result", synth_status,
                    f"{cell_count} cells, {synth_report.error_count} errors, "
                    f"{synth_report.warning_count} warnings")
        _log_step(ic_name, 2, "synth", "yosys", synth_status,
                  {"cells": cell_count,
                   "errors": synth_report.error_count,
                   "warnings": synth_report.warning_count},
                  [d.message[:80] for d in synth_report.diagnoses
                   if d.severity == "ERROR"][:3],
                  synth_dur, log_path)

        # If synthesis failed, invoke synth_doctor + phase2_menu
        if synth_status == "FAIL":
            all_pass = False
            print(f"\n  {_icon('FAIL')} Synthesis failed. Running synth-doctor...")

            # Print synth-doctor diagnoses
            for d in synth_report.diagnoses:
                if d.severity == "ERROR":
                    print(f"    {_icon('FAIL')} [{d.pattern}] {d.root_cause}")
                    print(f"       Fix: {d.fix_suggestion}")

            # Invoke phase2_menu
            action = phase2_prompt(
                stage="synthesis",
                tool="Yosys",
                log_path=synth_log,
                rtl_files=rtl_files,
                project_dir=ic_dir,
                auto_mode=auto,
            )
            _log_step(ic_name, 2, "synth_menu", "phase2_menu",
                      "PASS" if action in ("fixed_rerun", "rerun", "skip") else "FAIL",
                      {"action": action}, [], 0, log_path)

            if action == "skip":
                _print_step(2, "Synthesis", "SKIP", "Skipped by user")
            elif action in ("abort",):
                return False
            elif action in ("fixed_rerun", "rerun"):
                print(f"  Please re-run flow_runner after applying fixes.")
                return False

        # Check for netlist
        netlist_candidates = glob.glob(os.path.join(synth_dir, "synth_*.v")) + \
                             glob.glob(os.path.join(synth_dir, "*.json"))
        if netlist_candidates:
            synth_netlist = netlist_candidates[0]
            _print_step(2, "Synthesis netlist", "PASS",
                        os.path.basename(synth_netlist))
    else:
        _print_step(2, "Synthesis log", "SKIP", "No synth.log available")
        _log_step(ic_name, 2, "synth", "yosys", "SKIP",
                  {}, ["No synth.log"], synth_dur, log_path)

    # ── Step 2.3: SVA assertion count ──
    t0 = time.time()
    sva_count = _count_sva_assertions(rtl_dir)
    sva_status = "PASS" if sva_count >= SVA_MIN_COUNT else "WARN"
    _print_step(2, "SVA assertions", sva_status,
                f"{sva_count} found (minimum {SVA_MIN_COUNT})")
    _log_step(ic_name, 2, "sva_count", "flow_runner", sva_status,
              {"sva_count": sva_count, "minimum": SVA_MIN_COUNT},
              [] if sva_status == "PASS"
              else [f"Only {sva_count} SVA assertions (need >= {SVA_MIN_COUNT})"],
              time.time() - t0, log_path)

    if sva_count < SVA_MIN_COUNT:
        # This is a warning, not a hard failure
        pass

    # ── Step 2.4: P&R (check existing results) ──
    t0 = time.time()
    pnr_dir = os.path.join(ic_dir, "phase2_design", "pnr")
    pnr_log = os.path.join(pnr_dir, "pnr.log")
    drc_rpt = os.path.join(pnr_dir, "route_drc.rpt")

    if os.path.exists(pnr_log):
        pnr_report = pnr_analyze(pnr_log,
                                 drc_rpt if os.path.exists(drc_rpt) else None)
        pnr_status = pnr_report.status

        _print_step(2, "P&R result", pnr_status,
                    f"area={pnr_report.area:.0f}um\u00b2, "
                    f"DRC={pnr_report.drc_violations}")
        _log_step(ic_name, 2, "pnr", "openroad", pnr_status,
                  {"area": pnr_report.area,
                   "drc_violations": pnr_report.drc_violations,
                   "utilization": pnr_report.utilization},
                  [d.message[:80] for d in pnr_report.diagnoses
                   if d.severity == "ERROR"][:3],
                  time.time() - t0, log_path)

        if pnr_status == "FAIL":
            all_pass = False
            print(f"\n  {_icon('FAIL')} P&R failed. Running pnr-doctor...")

            for d in pnr_report.diagnoses:
                if d.severity == "ERROR":
                    print(f"    {_icon('FAIL')} [{d.pattern}] {d.root_cause}")
                    print(f"       Fix: {d.fix_suggestion}")

            action = phase2_prompt(
                stage="pnr",
                tool="OpenROAD",
                log_path=pnr_log,
                drc_path=drc_rpt if os.path.exists(drc_rpt) else None,
                project_dir=ic_dir,
                auto_mode=auto,
            )
            _log_step(ic_name, 2, "pnr_menu", "phase2_menu",
                      "PASS" if action in ("fixed_rerun", "rerun", "skip") else "FAIL",
                      {"action": action}, [], 0, log_path)

            if action == "skip":
                _print_step(2, "P&R", "SKIP", "Skipped by user")
            elif action in ("abort",):
                return False
    else:
        _print_step(2, "P&R", "SKIP", "No pnr.log found (P&R not run)")
        _log_step(ic_name, 2, "pnr", "openroad", "SKIP",
                  {}, ["No pnr.log"], time.time() - t0, log_path)

    # ── Phase 2 summary ──
    if all_pass:
        print(f"\n  {_icon('PASS')} Phase 2 PASSED: RTL and synthesis checks met.")
    else:
        print(f"\n  {_icon('FAIL')} Phase 2 has failures (see above).")
    return all_pass


# ============================================================================
# Phase 3: FPGA Verification
# ============================================================================

def run_phase3(ic_dir: str, ic_name: str, log_path: str,
               auto: bool = False) -> bool:
    """Run Phase 3 FPGA verification checks. Returns True if pass/skip."""
    print(f"\n{'='*60}")
    print(f"  Phase 3: FPGA Verification -- {ic_name}")
    print(f"{'='*60}")

    t0 = time.time()

    # ── Step 3.1: Check for SOF/FPGA output ──
    fpga_dir = os.path.join(ic_dir, "phase3_verify")
    sof_files = glob.glob(os.path.join(fpga_dir, "**", "*.sof"), recursive=True) + \
                glob.glob(os.path.join(fpga_dir, "**", "*.bit"), recursive=True) + \
                glob.glob(os.path.join(fpga_dir, "**", "*.rbf"), recursive=True)

    if sof_files:
        _print_step(3, "FPGA bitstream", "PASS",
                    f"{len(sof_files)} file(s): {', '.join(os.path.basename(f) for f in sof_files[:3])}")
        _log_step(ic_name, 3, "fpga_bitstream", "flow_runner", "PASS",
                  {"files": [os.path.basename(f) for f in sof_files]},
                  [], time.time() - t0, log_path)
    else:
        _print_step(3, "FPGA bitstream", "SKIP",
                    "No .sof/.bit/.rbf files found")
        _log_step(ic_name, 3, "fpga_bitstream", "flow_runner", "SKIP",
                  {}, ["No FPGA bitstream files"], time.time() - t0, log_path)

    # ── Step 3.2: Check for Quartus / Vivado availability ──
    t0 = time.time()
    quartus_avail = subprocess.run(
        ["which", "quartus_sh"], capture_output=True, text=True
    ).returncode == 0
    vivado_avail = subprocess.run(
        ["which", "vivado"], capture_output=True, text=True
    ).returncode == 0

    fpga_tool = "Quartus" if quartus_avail else ("Vivado" if vivado_avail else None)
    if fpga_tool:
        _print_step(3, "FPGA tool available", "PASS", fpga_tool)
        _log_step(ic_name, 3, "fpga_tool", fpga_tool.lower(), "PASS",
                  {"tool": fpga_tool}, [], time.time() - t0, log_path)
    else:
        _print_step(3, "FPGA tool available", "SKIP",
                    "Neither Quartus nor Vivado found")
        _log_step(ic_name, 3, "fpga_tool", "flow_runner", "SKIP",
                  {}, ["No FPGA tool installed"], time.time() - t0, log_path)

    # ── Step 3.3: Check for SDC constraints ──
    t0 = time.time()
    sdc_files = glob.glob(os.path.join(fpga_dir, "*.sdc")) + \
                glob.glob(os.path.join(fpga_dir, "*.xdc"))
    if sdc_files:
        _print_step(3, "Constraint files", "PASS",
                    f"{len(sdc_files)} file(s)")
        _log_step(ic_name, 3, "fpga_constraints", "flow_runner", "PASS",
                  {"files": [os.path.basename(f) for f in sdc_files]},
                  [], time.time() - t0, log_path)
    else:
        _print_step(3, "Constraint files", "WARN",
                    "No .sdc/.xdc files found")
        _log_step(ic_name, 3, "fpga_constraints", "flow_runner", "WARN",
                  {}, ["No constraint files"], time.time() - t0, log_path)

    # Phase 3 is informational -- doesn't block the pipeline
    print(f"\n  {_icon('PASS')} Phase 3 check complete (informational).")
    return True


# ============================================================================
# Main Orchestrator
# ============================================================================

def run_flow(ic_dir: str, auto: bool = False,
             phase_filter: Optional[int] = None) -> int:
    """
    Run the full Vibe-IC pipeline flow.

    Args:
        ic_dir: Path to IC project directory.
        auto: If True, skip interactive menus (use auto-abort/fix).
        phase_filter: If set, run only that phase (1, 2, or 3).

    Returns:
        0 if all pass, 1 if any fail.
    """
    ic_dir = os.path.abspath(ic_dir)
    if not os.path.isdir(ic_dir):
        print(f"\n  {_icon('FAIL')} IC directory not found: {ic_dir}")
        return 1

    ic_name = _ic_name_from_dir(ic_dir)
    log_path = os.path.join(ic_dir, "pipeline.jsonl")

    print(f"\n{'#'*60}")
    print(f"  Vibe-IC Flow Runner")
    print(f"  IC:      {ic_name}")
    print(f"  Dir:     {ic_dir}")
    print(f"  Mode:    {'auto' if auto else 'interactive'}")
    print(f"  Log:     {log_path}")
    if phase_filter:
        print(f"  Phase:   {phase_filter} ({PHASE_NAMES.get(phase_filter, '?')})")
    else:
        print(f"  Phases:  1 -> 2 -> 3")
    print(f"{'#'*60}")

    results = {}
    overall_start = time.time()

    # ── Phase 1 ──
    if phase_filter is None or phase_filter == 1:
        results[1] = run_phase1(ic_dir, ic_name, log_path, auto)
        if not results[1] and phase_filter is None:
            # Phase 1 failure blocks Phase 2
            print(f"\n  Phase 1 failed -- skipping Phase 2 and 3.")
            results[2] = False
            results[3] = False

    # ── Phase 2 ──
    if (phase_filter is None and results.get(1, False)) or phase_filter == 2:
        results[2] = run_phase2(ic_dir, ic_name, log_path, auto)

    # ── Phase 3 ──
    if (phase_filter is None and results.get(1, False)) or phase_filter == 3:
        results[3] = run_phase3(ic_dir, ic_name, log_path, auto)

    # ── Final Summary ──
    total_dur = time.time() - overall_start
    print(f"\n{'='*60}")
    print(f"  Flow Run Summary -- {ic_name}")
    print(f"{'='*60}")
    for phase_num in sorted(results.keys()):
        status = "PASS" if results[phase_num] else "FAIL"
        name = PHASE_NAMES.get(phase_num, f"Phase {phase_num}")
        print(f"  {_icon(status)} Phase {phase_num}: {name} -- {status}")
    print(f"\n  Total duration: {total_dur:.1f}s")
    print(f"  Pipeline log:   {log_path}")

    any_fail = any(not v for v in results.values())
    exit_code = 1 if any_fail else 0
    final_icon = _icon("FAIL" if any_fail else "PASS")
    print(f"\n  {final_icon} Overall: {'FAIL' if any_fail else 'PASS'}")
    print(f"{'='*60}\n")

    return exit_code


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="flow-runner: Vibe-IC Pipeline Orchestrator (Phase 1->2->3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --auto
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --phase 1
    python3 flow_runner.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --phase 2 --auto
""",
    )
    parser.add_argument("--ic-dir", required=True,
                        help="Path to IC project directory "
                             "(e.g., ic_projects_v2/ic_001_CD4013B/)")
    parser.add_argument("--auto", action="store_true",
                        help="Non-interactive mode (auto-abort on fail, "
                             "attempt auto-fix where available)")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], default=None,
                        help="Run only a specific phase (default: all)")
    args = parser.parse_args()

    exit_code = run_flow(
        ic_dir=args.ic_dir,
        auto=args.auto,
        phase_filter=args.phase,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
