#!/usr/bin/env python3
"""pdk_fpga_gds_reverify_runner.py — v1.6.232 (merged v229+v231).

Single-command orchestrator for FPGA gate-level GDS reverify.

PIPELINE (7 steps)
------------------
  1. pdk_udp_synth_shim_gen           — UDP → synth modules
  2. pdk_yosys_flatten_for_quartus    — flatten + name harmonize
  3. pdk_otp_altsyncram_inject        — OTP → altsyncram M9K + .mif
  4. chip_top_gate_wrapper_gen        — auto-generate FPGA wrapper
                                          (skipped if --wrapper exists)
  5. chip_top_open_drain_polarity_check — wrapper sanity
  6. Quartus compile (cwd=fpga_project)
  7. fpga_gate_level_attestation_check — no RTL fallback
  + optional Step 8: JTAG program (skip with --skip-program)
  + Step 9: emit attestation.json

Each step writes into `<project>/phase3/stage4/reverify/`.

USAGE — pre-compile
-------------------
    python3 pdk_fpga_gds_reverify_runner.py \\
        --project           ./bench-a \\
        --pnr-netlist       phase3/chip_top_asic_pnr.v \\
        --pdk-behavioral    pdk/<pdk>_neg.v \\
        --otp-hex           input/otp.hex \\
        --rtl-chip-top      rtl/chip_top.sv \\
        --rtl-chip-top-asic rtl/chip_top_asic.sv \\
        --fpga-qsf          fpga/de10lite_top.qsf \\
        [--top              chip_top_asic] \\
        [--bus-prefix       id_bus] \\
        [--skip-program]    \\
        [--post-compile-only phase3/quartus/de10lite_top.map.rpt]

EXIT CODES
----------
    0  PASS — every step ran successfully.
    1  FAIL — at least one step failed (stderr names which).
    2  IO / argument error.

chip-AGNOSTIC. Quartus paths can be passed via --quartus-bin /
--quartus-pgm; defaults probe iic-osic-tools and a known mounted
SSD path used by the BENCH-A lab rig.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import _progress_run as _pr  # noqa: E402


PROGRAMS_DIR = Path(__file__).resolve().parent


@dataclass
class StepResult:
    step: str
    cmd: List[str]
    rc: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    extras: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.rc == 0


def _step(label: str, cmd: List[str], cwd: Optional[Path] = None,
           timeout: int = 1800) -> StepResult:
    print(f"\n=== {label} ===\n  $ {' '.join(str(c) for c in cmd)}"
           + (f"  (cwd={cwd})" if cwd else ""),
          file=sys.stderr)
    try:
        cp = _pr.run(cmd, capture_output=True, text=True,
                            cwd=str(cwd) if cwd else None)
    except FileNotFoundError as e:
        return StepResult(step=label, cmd=cmd, rc=2,
                          stderr_tail=str(e))
    rc = cp.returncode
    if rc != 0:
        sys.stderr.write(cp.stdout or "")
        sys.stderr.write(cp.stderr or "")
    return StepResult(
        step=label, cmd=cmd, rc=rc,
        stdout_tail=(cp.stdout or "")[-500:],
        stderr_tail=(cp.stderr or "")[-500:],
    )


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _require_program(name: str) -> Path:
    p = PROGRAMS_DIR / name
    if not p.is_file():
        raise SystemExit(f"error: required helper missing: {p}")
    return p


def run_pre_compile(args) -> List[StepResult]:
    """Steps 1-5 + 6 Quartus compile + 7 attestation + optional program."""
    results: List[StepResult] = []
    project = Path(args.project).resolve()
    out_root = project / "phase3" / "stage4" / "reverify"
    out_root.mkdir(parents=True, exist_ok=True)

    shim_v = out_root / "pdk_synth_shim.v"
    flat_v = out_root / "chip_top_asic_flat.v"
    otpinit_v = out_root / "chip_top_asic_flat_otpinit.v"
    mif_p = out_root / f"{args.mif_name}.mif"
    wrapper_v = out_root / "chip_top.v"

    # Step 1
    p = _require_program("pdk_udp_synth_shim_gen.py")
    results.append(_step("1-udp-shim", [
        sys.executable, str(p),
        str(Path(args.pdk_behavioral).resolve()),
        str(shim_v), "--fpga",
    ]))
    if not results[-1].ok:
        return results

    # Step 2
    p = _require_program("pdk_yosys_flatten_for_quartus.py")
    cmd = [
        sys.executable, str(p),
        "--gate-netlist", str(Path(args.pnr_netlist).resolve()),
        "--pdk-shim", str(shim_v),
        "--top", args.top,
        "--output", str(flat_v),
    ]
    if args.container:
        cmd += ["--container", args.container]
    results.append(_step("2-yosys-flatten", cmd))
    if not results[-1].ok:
        return results

    # Step 3
    p = _require_program("pdk_otp_altsyncram_inject.py")
    results.append(_step("3-otp-altsyncram", [
        sys.executable, str(p),
        "--flat-netlist", str(flat_v),
        "--hex-file", str(Path(args.otp_hex).resolve()),
        "--output", str(otpinit_v),
        "--mif-output", str(mif_p),
        "--rdata-signal", args.otp_rdata_signal,
        "--addr-signal", args.otp_addr_signal,
    ]))
    if not results[-1].ok:
        return results

    # Step 4 — wrapper gen
    p = _require_program("chip_top_gate_wrapper_gen.py")
    results.append(_step("4-wrapper-gen", [
        sys.executable, str(p),
        "--rtl-chip-top", str(Path(args.rtl_chip_top).resolve()),
        "--rtl-chip-top-asic",
        str(Path(args.rtl_chip_top_asic).resolve()),
        "--output", str(wrapper_v),
        "--bus", args.bus_prefix,
        "--gate-top", args.top,
    ]))
    if not results[-1].ok:
        return results

    # Step 5 — polarity check
    p = _require_program("chip_top_open_drain_polarity_check.py")
    results.append(_step("5-polarity-check", [
        sys.executable, str(p),
        "--wrapper", str(wrapper_v),
        "--asic-rtl", str(Path(args.rtl_chip_top_asic).resolve()),
        "--bus-prefix", args.bus_prefix,
    ]))
    if not results[-1].ok:
        return results

    if args.no_quartus:
        return results

    # Step 6 — Quartus compile (rewrite QSF; drop RTL files)
    fpga_dir = out_root / "fpga_project"
    if fpga_dir.exists():
        shutil.rmtree(fpga_dir)
    fpga_dir.mkdir(parents=True)

    qsf_src_p = Path(args.fpga_qsf).resolve()
    qsf_src = qsf_src_p.read_text()
    rtl_drop_patterns = [
        "chip_top.sv", "chip_top_asic.sv",
        "byte_assembler.sv", "main_fsm.sv", "otp_mem.sv",
        "rx_phy.sv", "tx_phy.sv", "wake_gen.sv", "crc8.v",
        "control_logic.sv", "regbank.sv",
    ]
    qsf_lines: List[str] = []
    for ln in qsf_src.splitlines():
        if any(d in ln for d in rtl_drop_patterns):
            continue
        qsf_lines.append(ln)
    qsf_lines.append(f"set_global_assignment -name VERILOG_FILE "
                      f"{otpinit_v.relative_to(fpga_dir.parent) if otpinit_v.is_relative_to(fpga_dir.parent) else otpinit_v}")
    qsf_lines.append(f"set_global_assignment -name VERILOG_FILE "
                      f"{wrapper_v.relative_to(fpga_dir.parent) if wrapper_v.is_relative_to(fpga_dir.parent) else wrapper_v}")
    qsf_lines.append(f"set_global_assignment -name MIF_FILE "
                      f"{args.mif_name}.mif")
    qsf_dst = fpga_dir / qsf_src_p.name
    qsf_dst.write_text("\n".join(qsf_lines) + "\n")
    # Copy qpf + sdc alongside, and the mif file
    for ext in (".qpf", ".sdc"):
        src = qsf_src_p.with_suffix(ext)
        if src.is_file():
            shutil.copy(src, fpga_dir)
    shutil.copy(mif_p, fpga_dir / f"{args.mif_name}.mif")

    qsf_basename = qsf_dst.stem
    results.append(_step("6-quartus-compile",
        [args.quartus_bin, "--flow", "compile", qsf_basename],
        cwd=fpga_dir, timeout=1800))
    sof = fpga_dir / "output_files" / f"{qsf_basename}.sof"
    if not results[-1].ok or not sof.is_file():
        return results

    # Step 7 — attestation
    map_rpt = fpga_dir / "output_files" / f"{qsf_basename}.map.rpt"
    p = _require_program("fpga_gate_level_attestation_check.py")
    cmd7 = [sys.executable, str(p),
            "--map-rpt", str(map_rpt),
            "--gate-top", args.top,
            "--json", "-"]
    results.append(_step("7-attestation", cmd7))

    # Step 8 — optional JTAG program
    if not args.skip_program and results[-1].ok:
        results.append(_step("8-jtag-program",
            [args.quartus_pgm, "-m", "JTAG", "-c", "USB-Blaster",
             "-o", f"p;{sof}@1"]))

    # Step 9 — attestation.json
    if all(r.ok for r in results):
        att = {
            "verdict": "PASS",
            "sof_path": str(sof),
            "sof_sha": _sha(sof),
            "gate_netlist": args.pnr_netlist,
            "pdk_behavioral": args.pdk_behavioral,
            "flat_netlist": str(flat_v),
            "otpinit_netlist": str(otpinit_v),
            "mif_file": str(mif_p),
            "wrapper": str(wrapper_v),
            "map_rpt": str(map_rpt),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                        time.gmtime()),
        }
        (out_root / "attestation.json").write_text(json.dumps(att, indent=2))
        print(f"\n[reverify] DONE — attestation at "
              f"{out_root / 'attestation.json'}\n           "
              f"SOF sha = {att['sof_sha']}")

    return results


def run_post_compile_only(args) -> List[StepResult]:
    """Step 7 only — for re-checking after a manual Quartus run."""
    p = _require_program("fpga_gate_level_attestation_check.py")
    return [_step("7-attestation", [
        sys.executable, str(p),
        "--map-rpt", str(Path(args.post_compile_only).resolve()),
        "--gate-top", args.top,
        "--json", "-",
    ], timeout=120)]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Orchestrate the FPGA gate-level reverify chain "
                     "(GDS → FPGA SOF + attestation)."),
    )
    ap.add_argument("--project", required=True)
    ap.add_argument("--pnr-netlist", required=True)
    ap.add_argument("--pdk-behavioral", required=True)
    ap.add_argument("--otp-hex", required=True)
    ap.add_argument("--rtl-chip-top", required=True)
    ap.add_argument("--rtl-chip-top-asic", required=True)
    ap.add_argument("--fpga-qsf", required=True)
    ap.add_argument("--top", default="chip_top_asic")
    ap.add_argument("--otp-rdata-signal", default="u_otp_rdata_r")
    ap.add_argument("--otp-addr-signal", default="u_fsm_otp_addr")
    ap.add_argument("--bus-prefix", default="id_bus")
    ap.add_argument("--mif-name", default="otp_init",
                    help="MIF filename stem (no extension)")
    ap.add_argument("--container", default=_pin.default_container_name())
    ap.add_argument("--quartus-bin",
                    default="/mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/"
                            "eda/quartus/quartus/bin/quartus_sh")
    ap.add_argument("--quartus-pgm",
                    default="/mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/"
                            "eda/quartus/quartus/bin/quartus_pgm")
    ap.add_argument("--skip-program", action="store_true")
    ap.add_argument("--no-quartus", action="store_true",
                    help="Skip step 6+ (Quartus compile + attest + program)")
    ap.add_argument("--post-compile-only", default=None,
                    help="Quartus *.map.rpt — runs step 7 only")
    ap.add_argument("--json", default=None,
                    help="Write JSON report; '-' for stdout")
    args = ap.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(f"error: project dir not found: {project}",
              file=sys.stderr)
        return 2

    if args.post_compile_only:
        results = run_post_compile_only(args)
        phase = "post_compile_only"
    else:
        results = run_pre_compile(args)
        phase = "pre_compile"

    failed = [r for r in results if not r.ok]
    report = {
        "phase": phase,
        "project": str(project),
        "top": args.top,
        "skip_program": args.skip_program,
        "fpga_qsf": args.fpga_qsf,
        "steps": [asdict(r) for r in results],
        "verdict": "PASS" if not failed else "FAIL",
    }

    if args.json:
        body = json.dumps(report, indent=2)
        if args.json == "-":
            print(body)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body + "\n")

    for r in results:
        print(f"[{r.step}] rc={r.rc}")
        if r.stderr_tail:
            print(f"  stderr: {r.stderr_tail.strip()[-200:]}")
    print(f"\nverdict: {report['verdict']} "
          f"({len(failed)}/{len(results)} failed)")

    return 0 if not failed else 1


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
