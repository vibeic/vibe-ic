#!/usr/bin/env python3
"""
fault_atpg_run.py — Open-source ATPG via Fault (cloudv-io/fault).

Runs Fault's `cut` + `atpg` subcommands on a synthesized netlist to produce
stuck-at test vectors and a coverage metric, then emits the artefacts
required by flow Step 11 (DFT insertion):

  <project>/dft/scan_netlist.v        (copy of cut netlist; Fault's cut DFF
                                       replacement is the moral equivalent
                                       of scan insertion for open flow)
  <project>/dft/atpg_coverage.rpt     (human-readable coverage ratio + count)
  <project>/reports/dft/coverage.json (machine-readable with
                                       stuck_at_ge_target: bool)

Eliminates the "no commercial ATPG" waiver (feedback_plugin_usage_discipline.md,
2026-04-22).

Usage:
    python3 fault_atpg_run.py <project_dir> \\
        --netlist synth/netlist.v \\
        --top aon_timer \\
        --clock clk_i \\
        [--pdk gf180] [--min-coverage 80] [--tv-count 100]

Requires Docker image hpretl/iic-osic-tools:latest (Fault + GF180 cell model).
Fault ≈ 10-60 s for typical <5k-cell designs.

Exit 0 = coverage >= threshold AND all artefacts produced.
Exit 1 = coverage below threshold OR Fault failed.
Exit 2 = usage / IO / Docker error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
import _path_layout as _pl


DOCKER_IMAGE = "hpretl/iic-osic-tools:latest"

# Per-PDK defaults: verilog cell-model path (inside Docker) + DFF cell names.
# pdk=custom reads paths from --cell-model-path and --dff-cells flags.
PDK_CONFIG = {
    "gf180": {
        "cell_model": (
            "/foss/pdks/ciel/gf180mcu/versions/"
            "8f2d1529c86235d726979eb9ecb7e9628108590b"
            "/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0"
            "/verilog/gf180mcu_fd_sc_mcu7t5v0.v"
        ),
        "dff_cells": "gf180mcu_fd_sc_mcu7t5v0__dffq_1,gf180mcu_fd_sc_mcu7t5v0__dffrq_1",
    },
    # m18e80pm180su custom PDK — used in the v046 aon_timer pilot
    "m18e80pm180su": {
        # Inside the container this path is /pdk/verilog/... if the host
        # mounts shared_pdk at /pdk; fault_atpg_run mounts it that way below.
        "cell_model": "/pdk/verilog/m18e80pm180su_verilog_210524/m18e80pm180su_neg.v",
        "dff_cells": "DFFRQD1,DFFSQD1",
    },
    # sky130A high-density stdcell library (default OpenLane PDK).
    # Added 2026-05-24 for v2 e2e benchmark spm_e2e — covers the broad
    # sky130_fd_sc_hd DFF family (dfxtp / dfrtp / dfstp / dfbbn / sdfxtp).
    "sky130": {
        "cell_model": (
            "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/"
            "sky130_fd_sc_hd.v"
        ),
        "dff_cells": (
            "sky130_fd_sc_hd__dfxtp_1,sky130_fd_sc_hd__dfxtp_2,"
            "sky130_fd_sc_hd__dfxtp_4,"
            "sky130_fd_sc_hd__dfrtp_1,sky130_fd_sc_hd__dfrtp_2,"
            "sky130_fd_sc_hd__dfrtp_4,"
            "sky130_fd_sc_hd__dfstp_1,sky130_fd_sc_hd__dfstp_2,"
            "sky130_fd_sc_hd__dfstp_4,"
            "sky130_fd_sc_hd__sdfxtp_1,sky130_fd_sc_hd__sdfxtp_2,"
            "sky130_fd_sc_hd__sdfrtp_1,sky130_fd_sc_hd__sdfrtp_2"
        ),
    },
}

# Iverilog lives in iic-osic-tools but isn't in default PATH; set the env var
# Fault expects, and also prepend to PATH and LD_LIBRARY_PATH so sub-tools
# find the iverilog `vvp` simulator and its shared library (libvvp.so).
IVERILOG_ROOT = "/foss/tools/iverilog"
YOSYS_BIN = "/foss/tools/bin"
ENV_PREAMBLE = (
    f"export FAULT_IVERILOG={IVERILOG_ROOT}/bin/iverilog && "
    f"export FAULT_YOSYS={YOSYS_BIN}/yosys && "
    f"export PATH={IVERILOG_ROOT}/bin:{YOSYS_BIN}:$PATH && "
    f"export LD_LIBRARY_PATH={IVERILOG_ROOT}/lib:${{LD_LIBRARY_PATH:-}} && "
)


def _run_docker(
    project: Path,
    cmd: list[str],
    timeout: int = 600,
    pdk_dir: Path | None = None,
) -> tuple[int, str, str]:
    """Run a command inside iic-osic-tools.
    - project mounted at /work
    - pdk_dir (shared_pdk) mounted at /pdk (optional, for custom PDKs)
    """
    docker_cmd = [
        "docker", "run", "--rm",
        "--entrypoint", "bash",
        "-v", f"{project}:/work",
    ]
    if pdk_dir is not None and pdk_dir.exists():
        docker_cmd += ["-v", f"{pdk_dir}:/pdk"]
    docker_cmd += [
        DOCKER_IMAGE,
        "-c", ENV_PREAMBLE + " ".join(cmd),
    ]
    try:
        r = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "docker command timed out"
    except FileNotFoundError:
        return 127, "", "docker binary not found in PATH"


def run_fault(
    project: Path,
    netlist_rel: str,
    clock: str,
    pdk: str,
    min_coverage: float,
    tv_count: int,
    pdk_dir: Path | None = None,
    reset: str | None = None,
    reset_active_low: bool = False,
) -> tuple[int, dict]:
    """Run Fault cut+atpg in the Docker container. Returns (exit, report_dict)."""
    pdk_cfg = PDK_CONFIG.get(pdk)
    if pdk_cfg is None:
        return 2, {"error": f"unsupported pdk: {pdk}. "
                            f"Supported: {list(PDK_CONFIG.keys())}"}
    cell_model = pdk_cfg["cell_model"]
    dff_cells = pdk_cfg["dff_cells"]

    # Prepare output paths (relative to project / /work)
    dft_dir = _pl.dft_dir(project)
    reports_dft = (_pl.reports_phase2_dir(project) / "dft")
    dft_dir.mkdir(parents=True, exist_ok=True)
    reports_dft.mkdir(parents=True, exist_ok=True)

    cut_out = "phase2/stage2/dft/cut_netlist.v"
    tv_out = "phase2/stage2/dft/tv.json"
    cov_out = "phase2/stage2/dft/coverage.yml"
    rpt_out = "phase2/stage2/dft/atpg_coverage.rpt"

    netlist_abs = f"/work/{netlist_rel}"
    cut_abs = f"/work/{cut_out}"

    # Step A: fault cut (DFF-flattening). Note: fault cut does NOT take --top.
    cut_cmd = [
        "fault", "cut",
        "--output", cut_abs,
        "--dff", dff_cells,
        "--clock", clock,
    ]
    if reset:
        cut_cmd += ["--reset", reset]
        if reset_active_low:
            cut_cmd += ["--reset-active-low"]
    cut_cmd.append(netlist_abs)

    ec, out, err = _run_docker(project, cut_cmd, timeout=120, pdk_dir=pdk_dir)
    cut_log = (out + "\n" + err)[-1000:]
    if ec != 0 or not (project / cut_out).exists():
        return 1, {
            "stage": "cut",
            "exit": ec,
            "log_tail": cut_log,
        }

    # Step B: fault atpg
    atpg_cmd = [
        "fault", "atpg",
        "--cell-model", cell_model,
        "--clock", clock,
        "-o", f"/work/{tv_out}",
        "--output-coverage-metadata", f"/work/{cov_out}",
        "-m", str(min_coverage),
        "-v", str(tv_count),
        cut_abs,
    ]
    ec, out, err = _run_docker(project, atpg_cmd, timeout=1800, pdk_dir=pdk_dir)
    atpg_log = (out + "\n" + err)[-2000:]

    # Parse coverage. Fault 0.9 emits `ratio: <fractional>` in the YAML
    # metadata + "Found X fault sites" / "Final coverage: Y%" in stdout.
    coverage_ratio = 0.0
    faults_total = 0
    cov_file = project / cov_out
    if cov_file.exists():
        text = cov_file.read_text()
        m_ratio = re.search(
            r"^ratio\s*:\s*([0-9.eE+\-]+)", text, re.MULTILINE,
        )
        if m_ratio:
            val = float(m_ratio.group(1))
            coverage_ratio = val * 100.0 if val <= 1.0 else val

    # Fallbacks from stdout log
    if coverage_ratio == 0.0:
        m = re.search(r"Final coverage:\s*([0-9.]+)\s*%", atpg_log)
        if m:
            coverage_ratio = float(m.group(1))
    m_total = re.search(r"Found\s+(\d+)\s+fault\s+sites", atpg_log)
    if m_total:
        faults_total = int(m_total.group(1))

    # Derive covered count rather than counting YAML "-" lines (which also
    # match testVectors etc. and over-counts).
    faults_covered = int(round(faults_total * coverage_ratio / 100.0))

    # Also grep the atpg stdout for a coverage number — Fault prints it at end
    if coverage_ratio == 0.0:
        m = re.search(r"[Cc]overage[^0-9]*([0-9.]+)\s*%", atpg_log)
        if m:
            coverage_ratio = float(m.group(1))

    # Write human-readable report
    (project / rpt_out).write_text(
        "Fault ATPG Coverage Report\n"
        "==========================\n"
        f"Clock         : {clock}\n"
        f"Netlist       : {netlist_rel}\n"
        f"PDK           : {pdk}\n"
        f"Stuck-at %    : {coverage_ratio:.2f}\n"
        f"Covered / Total: {faults_covered} / {faults_total}\n"
        f"Target (min)  : {min_coverage:.2f}\n"
        f"Result        : {'PASS' if coverage_ratio >= min_coverage else 'FAIL'}\n"
        "\n"
        f"(coverage metadata: {cov_out})\n"
        f"(test vectors    : {tv_out})\n"
    )

    # Also drop a copy as scan_netlist.v (Fault's cut output is the scan-ready
    # netlist in the open flow)
    scan_netlist = _pl.dft_dir(project) / "scan_netlist.v"
    if not scan_netlist.exists() and (project / cut_out).exists():
        scan_netlist.write_bytes((project / cut_out).read_bytes())

    report = {
        "tool": "fault",
        "clock": clock,
        "pdk": pdk,
        "netlist": netlist_rel,
        "coverage_pct": coverage_ratio,
        "faults_covered": faults_covered,
        "faults_total": faults_total,
        "target_pct": min_coverage,
        "stuck_at_ge_target": coverage_ratio >= min_coverage,
        "atpg_exit": ec,
        "log_tail": atpg_log[-500:],
    }

    return (0 if report["stuck_at_ge_target"] else 1), report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--netlist", default="phase2/stage2/synth/netlist.v",
                   help="Path (relative to project_dir) to synth netlist (default: synth/netlist.v)")
    p.add_argument("--clock", required=True, help="Clock signal name (e.g. clk_i)")
    p.add_argument("--reset", help="Reset signal name (optional)")
    p.add_argument("--reset-active-low", action="store_true", help="Reset is active low")
    p.add_argument("--pdk", default="m18e80pm180su",
                   help=f"PDK name. Supported: {', '.join(PDK_CONFIG.keys())}")
    p.add_argument("--pdk-dir", help="Path to PDK dir (mounted at /pdk for custom PDKs)")
    p.add_argument("--min-coverage", type=float, default=80.0,
                   help="Minimum stuck-at coverage %% required (default 80.0)")
    p.add_argument("--tv-count", type=int, default=100,
                   help="Initial test-vector batch size (default 100)")
    p.add_argument("--json", help="Write report JSON to this path "
                                  "(default: reports/dft/coverage.json under project)")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"fault_atpg_run: not a directory: {project}", file=sys.stderr)
        return 2

    netlist = project / args.netlist
    if not netlist.exists():
        print(f"fault_atpg_run: netlist not found: {netlist}", file=sys.stderr)
        return 2

    # For m18e80pm180su default PDK dir is ../../shared_pdk relative to project,
    # matching benchmark/phase2+3_v046 convention
    pdk_dir = None
    if args.pdk_dir:
        pdk_dir = Path(args.pdk_dir).resolve()
    elif args.pdk == "m18e80pm180su":
        candidate = project.parent / "shared_pdk"
        if candidate.exists():
            pdk_dir = candidate

    exit_code, report = run_fault(
        project,
        netlist_rel=args.netlist,
        clock=args.clock,
        pdk=args.pdk,
        min_coverage=args.min_coverage,
        tv_count=args.tv_count,
        pdk_dir=pdk_dir,
        reset=args.reset,
        reset_active_low=args.reset_active_low,
    )

    json_path = Path(args.json) if args.json else (_pl.report_path(project, "dft/coverage.json"))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2))

    cov = report.get("coverage_pct", 0.0)
    target = report.get("target_pct", 0.0)
    print(f"fault_atpg_run: coverage={cov:.2f}%  target={target:.2f}%  "
          f"stuck_at_ge_target={report.get('stuck_at_ge_target', False)}")
    if exit_code != 0:
        print(f"  (see: {json_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
