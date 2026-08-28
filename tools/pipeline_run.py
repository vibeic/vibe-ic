#!/usr/bin/env python3
"""
Pipeline Runner -- One Command IC Flow (R2#9)
===============================================
Single command to run an IC through the entire 3-phase Vibe-IC design flow.

Usage:
    # Start a new IC from scratch
    python3 pipeline_run.py --ic CD4013B --brief "Dual D flip-flop with set/reset" [--auto]

    # Resume/verify an existing IC project
    python3 pipeline_run.py --ic-dir ic_projects_v2/ic_001_CD4013B/ [--auto]

    # Run specific phases only
    python3 pipeline_run.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --phase 1,2

Flow:
    Phase 1: Check/create prompt -> dialog -> spec -> DS -> AN -> quality check -> checkpoint1
    Phase 2: Check/create RTL -> SVA -> synth (local Yosys) -> checkpoint2
    Phase 3: Check FPGA harness -> checkpoint3
    Final:   Generate project_summary.md + pipeline.jsonl log

Progress Display:
    Pipeline: CD4013B
      Phase 1: [OK] DS=85/100 AN=72/80 CrossCheck=0 mismatches
      Phase 2: [OK] RTL=720 lines SVA=10 Synth=1975 cells
      Phase 3: [WARN] FPGA harness not generated (no Quartus)
      Result: PASS (2/3 phases complete)
"""

import argparse
import importlib.util
import glob
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, so
# this works from `tools/`, from `tools/<sub>/`, and from inside the flattened
# plugin cache where the marketplace path does not exist.
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

SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = SCRIPT_DIR / "vibe_ic_tools"
PROJECT_BASE = SCRIPT_DIR.parent / "ic_projects_v2"


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class PhaseResult:
    phase: int
    status: str         # PASS, FAIL, WARN, SKIP
    icon: str = ""      # [OK], [WARN], [FAIL], [SKIP]
    summary: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    elapsed_sec: float = 0.0

    def __post_init__(self):
        icons = {'PASS': '[OK]', 'FAIL': '[FAIL]', 'WARN': '[WARN]', 'SKIP': '[SKIP]'}
        self.icon = icons.get(self.status, '[??]')


@dataclass
class PipelineResult:
    ic_name: str
    ic_dir: str
    brief: str = ""
    phases: List[PhaseResult] = field(default_factory=list)
    verdict: str = "UNKNOWN"
    total_elapsed: float = 0.0
    timestamp: str = ""

    def phase_pass_count(self) -> int:
        return sum(1 for p in self.phases if p.status == 'PASS')

    def phase_total(self) -> int:
        return len([p for p in self.phases if p.status != 'SKIP'])


# ============================================================================
# Utility Functions
# ============================================================================

# ── progress supervision, borrowed from the plugin ──────────────────────────
#
# `subprocess.run(..., timeout=N)` ends work because a clock expired, which does
# not make sense: the job may have been one second from finishing, and the same
# input gets a different answer on a fast host than on a loaded one. The plugin
# already owns the honest replacement — `programs/_watchdog.py`, which bounds NO
# PROGRESS (CPU and I/O read from /proc across the whole tree, plus output
# growth) and never runtime. It is LOADED rather than re-implemented, so there
# is one supervisor in this repository and not two that can drift.
def _load_watchdog():
    for cand in (SCRIPT_DIR.parent / "vibe-ic-marketplace" / "plugins" /
                 "vibe-ic" / "programs" / "_watchdog.py",
                 SCRIPT_DIR.parent.parent / "vibe-ic-marketplace" / "plugins" /
                 "vibe-ic" / "programs" / "_watchdog.py"):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("_vibeic_watchdog", cand)
            mod = importlib.util.module_from_spec(spec)
            # REGISTERED BEFORE exec: `_watchdog` defines a @dataclass, and
            # dataclasses resolves `cls.__module__` through `sys.modules` while
            # the class body is being processed. Without this the import dies
            # with `'NoneType' object has no attribute '__dict__'` and the
            # fallback below silently reinstates the runtime bound.
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    return None


_WATCHDOG = _load_watchdog()


class _StalledSynth(RuntimeError):
    """yosys was alive and doing nothing at all across the grace."""


def _supervised(argv, grace_s, stalled_exc, **kw):
    """Run `argv` bounded by NO PROGRESS. Raises `stalled_exc` on a stall.

    Falls back to the old runtime bound ONLY when the plugin's watchdog cannot
    be located — a `tools/` script shipped away from the plugin. That fallback
    is named here rather than left implicit, because it is the one path on which
    a working job can still be killed.
    """
    if _WATCHDOG is None:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=grace_s, **kw)
        return proc
    res = _WATCHDOG.run_host_supervised(argv, stall_grace_s=grace_s, **kw)
    if res.outcome in ("stalled", "ceiling"):
        raise stalled_exc(
            f"no forward progress — no CPU, no I/O, no output from the whole "
            f"process tree — for {grace_s}s; stopped after {res.elapsed_s:.0f}s. "
            f"It was not slow; it was doing nothing.")
    return _WATCHDOG.completed_process(argv, res)


def _run_tool(tool_path: str, args: list, timeout: int = 120) -> Tuple[int, str, str]:
    """Run a Python tool and capture output."""
    cmd = [sys.executable, str(tool_path)] + args
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(SCRIPT_DIR.parent)
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Tool not found: {tool_path}"


def _find_file(directory: str, patterns: List[str]) -> Optional[str]:
    """Find first matching file in directory."""
    for pattern in patterns:
        matches = glob.glob(os.path.join(directory, pattern))
        if matches:
            return matches[0]
        # Also check subdirectories
        matches = glob.glob(os.path.join(directory, '**', pattern), recursive=True)
        if matches:
            return matches[0]
    return None


def _count_lines(filepath: str) -> int:
    """Count non-empty lines in a file."""
    if not os.path.isfile(filepath):
        return 0
    with open(filepath, 'r', errors='replace') as f:
        return sum(1 for line in f if line.strip())


def _count_sva(filepath: str) -> int:
    """Count SVA assertions in a file."""
    if not os.path.isfile(filepath):
        return 0
    with open(filepath, 'r', errors='replace') as f:
        content = f.read()
    return len(re.findall(r'\bassert\s+property\b', content, re.IGNORECASE))


#: Marker shared by `_run_yosys_synth` and its one caller, so the producer and
#: the reader of "yosys was wedged" cannot drift apart.
_SYNTH_NOT_MEASURED = "SYNTH_STALLED"

#: How long yosys may be COMPLETELY IDLE before it is called wedged. NOT a bound
#: on how long a synthesis may legitimately take: a large netlist is exactly the
#: honest long work a runtime cap destroys.
_SYNTH_STALL_GRACE_S = 120


def _run_yosys_synth(rtl_path: str, ic_dir: str) -> Tuple[bool, Optional[int], str]:
    """Run Yosys synthesis and return (success, cell_count, log)."""
    synth_dir = os.path.join(ic_dir, 'phase2_design', 'synth')
    os.makedirs(synth_dir, exist_ok=True)

    module_name = Path(rtl_path).stem
    synth_script = os.path.join(synth_dir, 'synth_check.ys')
    synth_log = os.path.join(synth_dir, 'synth_check.log')

    # Write Yosys script
    with open(synth_script, 'w') as f:
        f.write(f"read_verilog -sv {rtl_path}\n")
        f.write(f"synth -top {module_name}\n")
        f.write(f"stat\n")

    try:
        proc = _supervised(['yosys', '-s', synth_script],
                           _SYNTH_STALL_GRACE_S, _StalledSynth)
        log = proc.stdout + proc.stderr

        # Save log
        with open(synth_log, 'w') as f:
            f.write(log)

        # Parse cell count from stat output
        cells = 0
        cell_match = re.search(r'Number of cells:\s+(\d+)', log)
        if cell_match:
            cells = int(cell_match.group(1))

        success = proc.returncode == 0 and 'ERROR' not in log.upper()
        return success, cells, log

    except FileNotFoundError:
        return False, 0, "Yosys not found in PATH"
    except _StalledSynth as exc:
        # A MEASURED statement about yosys, reached only when its whole process
        # tree was idle across the grace. The first attempt at this fix kept the
        # runtime kill and merely relabelled it, which left a working synthesis
        # just as dead. Still NOT "Synthesis failed" and still no cell count:
        # 0 cells is a MEASUREMENT, and none was taken.
        return False, None, _SYNTH_NOT_MEASURED + f": {exc}"


# ============================================================================
# Phase 1: Specification & Documentation
# ============================================================================

def run_phase1(ic_dir: str, ic_name: str, auto: bool = False) -> PhaseResult:
    """Phase 1: Check datasheet quality and application note quality."""
    start = time.time()
    metrics = {}
    errors = []

    # Check required Phase 1 deliverables
    deliverables = {
        'prompt':    ['01_prompt.md'],
        'dialog':    ['02_dialog.md'],
        'spec':      ['03_spec_confirmed.md', '03_spec.md'],
        'datasheet': ['04_datasheet.md', 'datasheet.md'],
        'appnote':   ['05_appnote.md', 'appnote.md'],
    }

    # Also check in phase1_spec/ subdirectory
    found = {}
    for key, patterns in deliverables.items():
        f = _find_file(ic_dir, patterns)
        if not f:
            f = _find_file(os.path.join(ic_dir, 'phase1_spec'), patterns)
        found[key] = f

    missing = [k for k, v in found.items() if v is None]

    if missing:
        metrics['missing'] = missing
        if 'datasheet' in missing and 'spec' in missing:
            return PhaseResult(
                phase=1, status='FAIL',
                summary=f"Missing: {', '.join(missing)}",
                metrics=metrics,
                errors=[f"Required file not found: {m}" for m in missing],
                elapsed_sec=time.time() - start,
            )

    # Run datasheet quality check
    ds_score = 0
    ds_path = found.get('datasheet')
    if ds_path:
        metrics['datasheet_path'] = ds_path
        ds_tool = TOOLS_DIR / "ds_quality_check.py"
        if ds_tool.exists():
            rc, stdout, stderr = _run_tool(str(ds_tool), [ds_path, '--json'])
            # Try to parse JSON output regardless of exit code (some tools
            # use non-zero exit for below-threshold scores)
            if stdout.strip():
                try:
                    ds_result = json.loads(stdout)
                    ds_score = ds_result.get('total_score', 0)
                    metrics['ds_score'] = ds_score
                    metrics['ds_max'] = ds_result.get('max_score', 100)
                except (json.JSONDecodeError, KeyError):
                    # Try to parse score from text output
                    score_match = re.search(r'Total.*?(\d+)/(\d+)', stdout)
                    if score_match:
                        ds_score = int(score_match.group(1))
                        metrics['ds_score'] = ds_score
                        metrics['ds_max'] = int(score_match.group(2))
        else:
            # Manual line count as fallback
            ds_lines = _count_lines(ds_path)
            metrics['ds_lines'] = ds_lines
            ds_score = min(100, ds_lines // 3)  # rough estimate
            metrics['ds_score'] = ds_score
            metrics['ds_max'] = 100

    # Run application note quality check
    an_score = 0
    an_path = found.get('appnote')
    if an_path:
        metrics['appnote_path'] = an_path
        an_tool = TOOLS_DIR / "an_validator.py"
        if an_tool.exists():
            rc, stdout, stderr = _run_tool(str(an_tool), [an_path, '--json'])
            if stdout.strip():
                try:
                    an_result = json.loads(stdout)
                    an_score = an_result.get('total_score', 0)
                    metrics['an_score'] = an_score
                    metrics['an_max'] = an_result.get('max_score', 80)
                except (json.JSONDecodeError, KeyError):
                    score_match = re.search(r'Total.*?(\d+)/(\d+)', stdout)
                    if score_match:
                        an_score = int(score_match.group(1))
                        metrics['an_score'] = an_score
                        metrics['an_max'] = int(score_match.group(2))
        else:
            an_lines = _count_lines(an_path)
            metrics['an_lines'] = an_lines
            an_score = min(80, an_lines // 3)
            metrics['an_score'] = an_score
            metrics['an_max'] = 80

    # Cross-check: spec vs datasheet consistency
    cross_mismatches = 0
    spec_path = found.get('spec')
    if spec_path and ds_path:
        cross_mismatches = _cross_check_spec_ds(spec_path, ds_path)
        metrics['cross_check_mismatches'] = cross_mismatches

    # Check checkpoint1 signoff
    cp1 = _find_file(ic_dir, ['checkpoint1_signoff.md'])
    metrics['checkpoint1_exists'] = cp1 is not None

    # Determine status
    elapsed = time.time() - start
    ds_max = metrics.get('ds_max', 100)
    an_max = metrics.get('an_max', 80)

    if ds_score >= ds_max * 0.6 and (an_score >= an_max * 0.5 or not an_path):
        status = 'PASS'
    elif ds_score >= ds_max * 0.4:
        status = 'WARN'
    else:
        status = 'FAIL'

    summary_parts = []
    summary_parts.append(f"DS={ds_score}/{ds_max}")
    if an_path:
        summary_parts.append(f"AN={an_score}/{an_max}")
    summary_parts.append(f"CrossCheck={cross_mismatches} mismatches")

    return PhaseResult(
        phase=1, status=status,
        summary=' '.join(summary_parts),
        metrics=metrics,
        errors=errors,
        elapsed_sec=elapsed,
    )


def _cross_check_spec_ds(spec_path: str, ds_path: str) -> int:
    """Simple cross-check between spec and datasheet."""
    mismatches = 0
    try:
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec_text = f.read()
        with open(ds_path, 'r', encoding='utf-8') as f:
            ds_text = f.read()

        # Check if key numbers appear in both
        # Extract voltage values from spec
        spec_voltages = set(re.findall(r'(\d+\.?\d*)\s*V', spec_text))
        ds_voltages = set(re.findall(r'(\d+\.?\d*)\s*V', ds_text))

        # Voltages in spec but not in datasheet (potential mismatch)
        key_voltages = {'3', '3.3', '5', '15', '18'}
        for v in spec_voltages & key_voltages:
            if v not in ds_voltages:
                mismatches += 1

    except Exception:
        pass

    return mismatches


# ============================================================================
# Phase 2: Design & Synthesis
# ============================================================================

def run_phase2(ic_dir: str, ic_name: str, auto: bool = False) -> PhaseResult:
    """Phase 2: Check RTL, SVA, synthesis."""
    start = time.time()
    metrics = {}
    errors = []

    # Find RTL file
    rtl_dir = os.path.join(ic_dir, 'phase2_design', 'rtl')
    rtl_file = None

    if os.path.isdir(rtl_dir):
        sv_files = glob.glob(os.path.join(rtl_dir, '*.sv'))
        # Exclude formal/assertion files
        sv_files = [f for f in sv_files if '_formal' not in f and '_sva' not in f]
        if sv_files:
            rtl_file = sv_files[0]

    if not rtl_file:
        # Look in other common locations
        rtl_file = _find_file(ic_dir, ['*.sv'])
        if rtl_file and ('_formal' in rtl_file or '_sva' in rtl_file):
            rtl_file = None

    if not rtl_file:
        return PhaseResult(
            phase=2, status='FAIL',
            summary="RTL not found",
            metrics=metrics,
            errors=["No .sv RTL file found in phase2_design/rtl/"],
            elapsed_sec=time.time() - start,
        )

    metrics['rtl_path'] = rtl_file

    # Count RTL lines
    rtl_lines = _count_lines(rtl_file)
    metrics['rtl_lines'] = rtl_lines

    # Find and count SVA assertions
    sva_file = _find_file(rtl_dir or ic_dir, ['*_formal.sv', '*_sva.sv', '*_assertions.sv'])
    sva_count = 0
    if sva_file:
        sva_count = _count_sva(sva_file)
        metrics['sva_file'] = sva_file
    metrics['sva_count'] = sva_count

    # Run Yosys synthesis
    synth_success, cell_count, synth_log = _run_yosys_synth(rtl_file, ic_dir)
    metrics['synth_success'] = synth_success
    # `None`, not 0, when nothing was measured. A published `synth_cells: 0` is
    # read as "this design synthesised to nothing".
    metrics['synth_cells'] = cell_count

    if not synth_success:
        # Check if it's a Yosys-not-found issue vs actual synthesis error
        if synth_log.startswith(_SYNTH_NOT_MEASURED):
            metrics['synth_note'] = 'yosys was WEDGED (no forward progress)'
            errors.append(
                'Yosys made no forward progress and was stopped -- a measured '
                'fact about the tool, not a synthesis failure; nothing here is '
                'a finding about the RTL')
        elif 'not found' in synth_log.lower():
            metrics['synth_note'] = 'Yosys not installed'
            errors.append('Yosys not found -- synthesis skipped')
        else:
            # Run synth_doctor for diagnosis
            synth_log_path = os.path.join(ic_dir, 'phase2_design', 'synth', 'synth_check.log')
            if os.path.isfile(synth_log_path):
                doctor_tool = TOOLS_DIR / "synth_doctor.py"
                if doctor_tool.exists():
                    rc, stdout, stderr = _run_tool(str(doctor_tool), [synth_log_path])
                    if rc == 0:
                        metrics['synth_diagnosis'] = stdout[:500]
            errors.append('Synthesis failed')

    # Check checkpoint2 signoff
    cp2 = _find_file(ic_dir, ['checkpoint2_signoff.md'])
    metrics['checkpoint2_exists'] = cp2 is not None

    # Check for other Phase 2 artifacts
    synth_netlist = _find_file(os.path.join(ic_dir, 'phase2_design', 'synth'),
                               ['synth_*.v', '*.v'])
    metrics['synth_netlist_exists'] = synth_netlist is not None

    pnr_def = _find_file(os.path.join(ic_dir, 'phase2_design', 'pnr'),
                          ['*_routed.def', '*.def'])
    metrics['pnr_def_exists'] = pnr_def is not None

    gds_file = _find_file(os.path.join(ic_dir, 'phase2_design', 'gds'),
                           ['*.gds'])
    metrics['gds_exists'] = gds_file is not None

    # Determine status
    elapsed = time.time() - start

    if rtl_lines > 0 and (synth_success or 'not found' in synth_log.lower()):
        status = 'PASS' if synth_success else 'WARN'
    elif rtl_lines > 0:
        status = 'WARN'
    else:
        status = 'FAIL'

    summary_parts = [f"RTL={rtl_lines} lines"]
    if sva_count > 0:
        summary_parts.append(f"SVA={sva_count}")
    if synth_success:
        summary_parts.append(f"Synth={cell_count} cells")
    elif 'not found' in synth_log.lower():
        summary_parts.append("Synth=skipped (no Yosys)")
    else:
        summary_parts.append("Synth=FAIL")

    return PhaseResult(
        phase=2, status=status,
        summary=' '.join(summary_parts),
        metrics=metrics,
        errors=errors,
        elapsed_sec=elapsed,
    )


# ============================================================================
# Phase 3: FPGA Verification
# ============================================================================

def run_phase3(ic_dir: str, ic_name: str, auto: bool = False) -> PhaseResult:
    """Phase 3: Check FPGA harness and generate if missing."""
    start = time.time()
    metrics = {}
    errors = []

    # Check for existing FPGA test artifacts
    fpga_dir = os.path.join(ic_dir, 'phase3_verify')
    if not os.path.isdir(fpga_dir):
        fpga_dir = os.path.join(ic_dir, 'fpga_test')

    # Look for FPGA artifacts in various locations
    sof_file = _find_file(ic_dir, ['*.sof'])
    qsf_file = _find_file(ic_dir, ['*_fpga.qsf', '*.qsf'])
    bist_file = _find_file(ic_dir, ['*_bist*.sv'])
    fpga_top = _find_file(ic_dir, ['*_fpga_top.sv'])
    test_py = _find_file(ic_dir, ['fpga_test*.py'])

    metrics['sof_exists'] = sof_file is not None
    metrics['qsf_exists'] = qsf_file is not None
    metrics['bist_exists'] = bist_file is not None
    metrics['fpga_top_exists'] = fpga_top is not None
    metrics['test_py_exists'] = test_py is not None

    # Try to generate FPGA harness if missing
    harness_generated = False
    if not fpga_top or not bist_file:
        rtl_dir_p3 = os.path.join(ic_dir, 'phase2_design', 'rtl')
        rtl_file = None
        if os.path.isdir(rtl_dir_p3):
            sv_candidates = glob.glob(os.path.join(rtl_dir_p3, '*.sv'))
            sv_candidates = [f for f in sv_candidates
                             if '_formal' not in f and '_sva' not in f]
            if sv_candidates:
                rtl_file = sv_candidates[0]
        if rtl_file:
            harness_tool = TOOLS_DIR / "fpga_harness_gen.py"
            if harness_tool.exists():
                harness_dir = os.path.join(ic_dir, 'phase3_verify', 'fpga_harness')
                os.makedirs(harness_dir, exist_ok=True)

                rc, stdout, stderr = _run_tool(
                    str(harness_tool),
                    ['--rtl', rtl_file, '--output', harness_dir, '--quiet']
                )
                if rc == 0:
                    harness_generated = True
                    metrics['harness_generated'] = True
                    metrics['harness_dir'] = harness_dir
                else:
                    errors.append(f"Harness generation failed: {stderr[:200]}")
            else:
                errors.append("fpga_harness_gen.py not found")
        else:
            errors.append("No RTL file for harness generation")

    # Check for Quartus availability
    quartus_available = False
    try:
        proc = subprocess.run(['quartus_sh', '--version'],
                              capture_output=True, text=True, timeout=10)
        quartus_available = proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    metrics['quartus_available'] = quartus_available

    # Check checkpoint3 signoff
    cp3 = _find_file(ic_dir, ['checkpoint3_signoff.md'])
    metrics['checkpoint3_exists'] = cp3 is not None

    # Determine status
    elapsed = time.time() - start

    if sof_file:
        status = 'PASS'
        summary = f"SOF exists, FPGA tested"
    elif harness_generated:
        status = 'WARN'
        summary = "FPGA harness generated (not compiled)"
    elif fpga_top and bist_file:
        status = 'WARN'
        summary = "FPGA files exist (not compiled)"
        if not quartus_available:
            summary += " (no Quartus)"
    else:
        status = 'WARN'
        summary = "FPGA harness not generated"
        if not quartus_available:
            summary += " (no Quartus)"

    return PhaseResult(
        phase=3, status=status,
        summary=summary,
        metrics=metrics,
        errors=errors,
        elapsed_sec=elapsed,
    )


# ============================================================================
# Project Summary Generator
# ============================================================================

def generate_project_summary(result: PipelineResult) -> str:
    """Generate project_summary.md content."""
    lines = []
    lines.append(f"# {result.ic_name} -- Pipeline Summary")
    lines.append("")
    lines.append(f"**Date**: {result.timestamp}")
    lines.append(f"**IC**: {result.ic_name}")
    if result.brief:
        lines.append(f"**Description**: {result.brief}")
    lines.append(f"**Verdict**: **{result.verdict}**")
    lines.append(f"**Phases**: {result.phase_pass_count()}/{result.phase_total()} passed")
    lines.append(f"**Elapsed**: {result.total_elapsed:.1f}s")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Phase details
    for p in result.phases:
        lines.append(f"## Phase {p.phase}")
        lines.append("")
        lines.append(f"| Item | Value |")
        lines.append(f"|------|-------|")
        lines.append(f"| Status | {p.icon} {p.status} |")
        lines.append(f"| Summary | {p.summary} |")
        lines.append(f"| Elapsed | {p.elapsed_sec:.1f}s |")
        for k, v in p.metrics.items():
            lines.append(f"| {k} | {v} |")
        if p.errors:
            lines.append(f"| Errors | {'; '.join(p.errors)} |")
        lines.append("")

    return '\n'.join(lines)


# ============================================================================
# Pipeline Log (JSONL)
# ============================================================================

def append_pipeline_log(result: PipelineResult, log_path: str):
    """Append pipeline result to JSONL log file."""
    entry = {
        'timestamp': result.timestamp,
        'ic_name': result.ic_name,
        'ic_dir': result.ic_dir,
        'brief': result.brief,
        'verdict': result.verdict,
        'phases': [asdict(p) for p in result.phases],
        'total_elapsed': round(result.total_elapsed, 2),
    }
    with open(log_path, 'a') as f:
        f.write(json.dumps(entry, default=str) + '\n')


# ============================================================================
# Progress Display
# ============================================================================

def print_progress(result: PipelineResult):
    """Print formatted pipeline progress."""
    print(f"\n  Pipeline: {result.ic_name}")
    if result.brief:
        print(f"  Brief:    {result.brief}")
    print()

    for p in result.phases:
        status_icon = {
            'PASS': '\033[92m[OK]\033[0m',    # green
            'FAIL': '\033[91m[FAIL]\033[0m',   # red
            'WARN': '\033[93m[WARN]\033[0m',   # yellow
            'SKIP': '\033[90m[SKIP]\033[0m',   # gray
        }.get(p.status, '[??]')

        # Check if terminal supports ANSI colors
        if not sys.stdout.isatty():
            status_icon = p.icon

        print(f"    Phase {p.phase}: {status_icon} {p.summary}")
        if p.errors:
            for e in p.errors[:3]:
                print(f"             -> {e}")

    # Overall verdict
    verdict_icon = {
        'PASS': '\033[92mPASS\033[0m',
        'FAIL': '\033[91mFAIL\033[0m',
        'PARTIAL': '\033[93mPARTIAL\033[0m',
    }.get(result.verdict, result.verdict)
    if not sys.stdout.isatty():
        verdict_icon = result.verdict

    passed = result.phase_pass_count()
    total = result.phase_total()
    print(f"\n    Result: {verdict_icon} ({passed}/{total} phases complete)")
    print(f"    Elapsed: {result.total_elapsed:.1f}s")
    print()


# ============================================================================
# Resolve IC Directory
# ============================================================================

def resolve_ic_dir(ic_name: Optional[str] = None,
                   ic_dir: Optional[str] = None) -> Tuple[str, str]:
    """
    Resolve IC name and directory.

    Returns:
        (ic_name, ic_dir_path)
    """
    if ic_dir:
        # Existing project directory
        ic_dir = os.path.abspath(ic_dir)
        if not os.path.isdir(ic_dir):
            print(f"ERROR: Directory not found: {ic_dir}")
            sys.exit(1)

        # Extract IC name from directory name
        dir_name = os.path.basename(ic_dir)
        m = re.match(r'ic_\d+_(.+)', dir_name)
        if m:
            name = m.group(1)
        else:
            name = dir_name

        return name, ic_dir

    elif ic_name:
        # Find existing or create new project
        # Search for existing project
        for d in sorted(glob.glob(str(PROJECT_BASE / f'ic_*_{ic_name}'))):
            if os.path.isdir(d):
                return ic_name, d

        # Also try case-insensitive search
        for d in sorted(glob.glob(str(PROJECT_BASE / 'ic_*'))):
            if ic_name.lower() in os.path.basename(d).lower():
                return ic_name, d

        # Create new project directory
        existing = sorted(glob.glob(str(PROJECT_BASE / 'ic_*')))
        if existing:
            last_num = 0
            for e in existing:
                m = re.match(r'ic_(\d+)_', os.path.basename(e))
                if m:
                    last_num = max(last_num, int(m.group(1)))
            next_num = last_num + 1
        else:
            next_num = 1

        new_dir = str(PROJECT_BASE / f'ic_{next_num:03d}_{ic_name}')
        os.makedirs(new_dir, exist_ok=True)
        return ic_name, new_dir

    else:
        print("ERROR: Must specify --ic or --ic-dir")
        sys.exit(1)


# ============================================================================
# Main Pipeline
# ============================================================================

def run_pipeline(
    ic_name: str,
    ic_dir: str,
    brief: str = "",
    phases: Optional[List[int]] = None,
    auto: bool = False,
) -> PipelineResult:
    """Run the full pipeline for an IC."""

    if phases is None:
        phases = [1, 2, 3]

    result = PipelineResult(
        ic_name=ic_name,
        ic_dir=ic_dir,
        brief=brief,
        timestamp=datetime.now().isoformat(),
    )

    total_start = time.time()

    print(f"\n  {'=' * 60}")
    print(f"  Vibe-IC Pipeline Runner")
    print(f"  {'=' * 60}")
    print(f"  IC:    {ic_name}")
    print(f"  Dir:   {ic_dir}")
    print(f"  Brief: {brief or '(not specified)'}")
    print(f"  Phases: {phases}")
    print(f"  Auto:  {auto}")
    print(f"  {'=' * 60}")

    # Phase 1
    if 1 in phases:
        print(f"\n  --- Phase 1: Specification & Documentation ---")
        p1 = run_phase1(ic_dir, ic_name, auto)
        result.phases.append(p1)
        print(f"  {p1.icon} {p1.summary}")
    else:
        result.phases.append(PhaseResult(phase=1, status='SKIP', summary='Skipped'))

    # Phase 2
    if 2 in phases:
        print(f"\n  --- Phase 2: Design & Synthesis ---")
        p2 = run_phase2(ic_dir, ic_name, auto)
        result.phases.append(p2)
        print(f"  {p2.icon} {p2.summary}")
    else:
        result.phases.append(PhaseResult(phase=2, status='SKIP', summary='Skipped'))

    # Phase 3
    if 3 in phases:
        print(f"\n  --- Phase 3: FPGA Verification ---")
        p3 = run_phase3(ic_dir, ic_name, auto)
        result.phases.append(p3)
        print(f"  {p3.icon} {p3.summary}")
    else:
        result.phases.append(PhaseResult(phase=3, status='SKIP', summary='Skipped'))

    # Compute verdict
    result.total_elapsed = time.time() - total_start
    active_phases = [p for p in result.phases if p.status != 'SKIP']
    pass_phases = [p for p in active_phases if p.status == 'PASS']
    fail_phases = [p for p in active_phases if p.status == 'FAIL']

    if len(fail_phases) > 0:
        result.verdict = 'FAIL'
    elif len(pass_phases) == len(active_phases):
        result.verdict = 'PASS'
    else:
        result.verdict = 'PARTIAL'

    # Generate project summary
    summary_path = os.path.join(ic_dir, 'project_summary.md')
    # Only write if no existing summary or if we have new results
    summary_content = generate_project_summary(result)
    pipeline_summary_path = os.path.join(ic_dir, 'pipeline_summary.md')
    with open(pipeline_summary_path, 'w') as f:
        f.write(summary_content)
    print(f"\n  Summary: {pipeline_summary_path}")

    # Append to pipeline log
    log_path = os.path.join(os.path.dirname(ic_dir), 'pipeline.jsonl')
    if not os.path.exists(os.path.dirname(log_path)):
        log_path = os.path.join(ic_dir, 'pipeline.jsonl')
    append_pipeline_log(result, log_path)
    print(f"  Log:     {log_path}")

    # Print progress display
    print_progress(result)

    return result


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Vibe-IC Pipeline Runner -- One Command IC Flow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
    # New IC from scratch
    python3 pipeline_run.py --ic CD4013B --brief "Dual D flip-flop with set/reset"

    # Existing project
    python3 pipeline_run.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --auto

    # Specific phases only
    python3 pipeline_run.py --ic-dir ic_projects_v2/ic_001_CD4013B/ --phase 1,2
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ic', help='IC name (e.g., CD4013B)')
    group.add_argument('--ic-dir', help='Path to existing IC project directory')

    parser.add_argument('--brief', default='', help='IC brief description')
    parser.add_argument('--phase', default='1,2,3',
                        help='Phases to run (comma-separated, default: 1,2,3)')
    parser.add_argument('--auto', action='store_true',
                        help='Non-interactive mode')

    args = parser.parse_args()

    # Parse phases
    try:
        phases = [int(p.strip()) for p in args.phase.split(',')]
    except ValueError:
        print("ERROR: --phase must be comma-separated integers (e.g., 1,2,3)")
        sys.exit(1)

    # Resolve IC directory
    ic_name, ic_dir = resolve_ic_dir(ic_name=args.ic, ic_dir=args.ic_dir)

    # Run pipeline
    result = run_pipeline(
        ic_name=ic_name,
        ic_dir=ic_dir,
        brief=args.brief,
        phases=phases,
        auto=args.auto,
    )

    # Exit code
    if result.verdict == 'PASS':
        sys.exit(0)
    elif result.verdict == 'PARTIAL':
        sys.exit(0)  # partial is OK
    else:
        sys.exit(1)


if __name__ == '__main__':
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
