#!/usr/bin/env python3
"""pdk_yosys_flatten_for_quartus.py — v1.6.222 (ORGANIC-20260512-followup-2).

Workaround for Quartus Lite SGN crash on flat post-PnR netlists.

Background: Quartus 23.1 Lite's quartus_map crashes with
  Internal Error: SGN_NAME_MAKER::process_group_name dimension == 0
when elaborating a flat gate netlist (~3k cells from OpenROAD PnR)
plus a per-cell synth-shim library (~338 modules). The crash is in
Quartus's hierarchical name-mangler, NOT in the netlist itself.

Workaround: use Yosys 0.62 to:
  1. read PDK synth-shim (e.g. <pdk>_synth_shim.v from
     pdk_udp_synth_shim_gen.py)
  2. read post-PnR gate netlist (chip_top_asic_pnr.v)
  3. hierarchy -top <top> -check; proc; flatten; clean
     → collapses all std-cell sub-modules into the top scope,
       leaves a single $-prim-based combinational + DFF netlist
  4. write_verilog
  5. run the existing atpg-name-harmonize tool (fix_fault_cut_names.py)
     to convert remaining `<NAME>.<sub>.<X>` escape identifiers to
     plain `_NAME__sub_X` form — Quartus accepts these.

After this pass, Quartus elaborates the design as a single flat
module with no hierarchical name-mangling, dodging the SGN crash.

chip-AGNOSTIC; works for any (gate netlist, synth shim, top module
name) tuple.

Usage:
    python3 pdk_yosys_flatten_for_quartus.py \\
        --gate-netlist <chip_top_asic_pnr.v> \\
        --pdk-shim <pdk_synth_shim.v> \\
        --top chip_top_asic \\
        --output <chip_top_asic_flat.v> \\
        [--container vibeic-eda]
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile, shutil
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
ATPG_HARMONIZE = PLUGIN / "programs" / "fix_fault_cut_names.py"

YS_TEMPLATE = """\
read_verilog {pdk_shim}
read_verilog {gate_netlist}
hierarchy -top {top} -check
proc
flatten
clean
write_verilog -noattr {out_path}
stat
"""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gate-netlist", type=Path, required=True)
    p.add_argument("--pdk-shim",      type=Path, required=True)
    p.add_argument("--top",           required=True)
    p.add_argument("--output",        type=Path, required=True)
    p.add_argument("--container",     default="vibeic-eda",
                    help="docker container that has yosys 0.62+")
    p.add_argument("--keep-tmp",      action="store_true")
    args = p.parse_args()

    # Map host paths to docker paths (<host> convention)
    def _docker_path(host: Path) -> str:
        h = host.resolve()
        if "AI_IC_design" in str(h):
            # host.resolve() yields an absolute path (e.g.
            # /home/<user>/AI_IC_design/...), so the host→container mount root
            # must be matched as an absolute path — the literal "~/AI_IC_design"
            # never appears post-resolve, which made the old replace a no-op.
            aid_root = str((Path.home() / "AI_IC_design").resolve())
            return str(h).replace(aid_root, "/foss/designs")
        return str(h)

    # Place tmp dir alongside the output so it lives inside the docker
    # mount (/foss/designs ↔ AI_IC_design). If output is under /tmp,
    # the .ys script and yosys output need to be reachable from
    # inside the container — fall back to /tmp inside container by
    # using the project root as anchor.
    tmp = args.output.resolve().parent / ".tmp_flatten"
    tmp.mkdir(parents=True, exist_ok=True)

    flat_v = tmp / "flat_raw.v"
    ys_path = tmp / "flatten.ys"
    ys_text = YS_TEMPLATE.format(
        pdk_shim=_docker_path(args.pdk_shim),
        gate_netlist=_docker_path(args.gate_netlist),
        top=args.top,
        out_path=_docker_path(flat_v),
    )
    ys_path.write_text(ys_text)

    # Run Yosys in container
    cmd = ["docker", "exec", args.container, "bash", "-lc",
           f"yosys -s {_docker_path(ys_path)} 2>&1 | tail -30"]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if cp.returncode != 0 or "ERROR" in cp.stdout:
        print(f"[flatten] yosys FAILED:\n{cp.stdout}{cp.stderr}",
              file=sys.stderr)
        return 2
    if not flat_v.is_file() or flat_v.stat().st_size < 100:
        print(f"[flatten] yosys output missing: {flat_v}", file=sys.stderr)
        return 2

    # Run name harmoniser to clean escape IDs
    if not ATPG_HARMONIZE.is_file():
        print(f"[flatten] missing harmoniser: {ATPG_HARMONIZE}", file=sys.stderr)
        return 2
    name_map = tmp / "harmonize.json"
    cp2 = subprocess.run([sys.executable, str(ATPG_HARMONIZE),
                          "--scan-cut", str(flat_v),
                          "--out", str(args.output),
                          "--name-map", str(name_map)],
                         capture_output=True, text=True, timeout=120)
    if cp2.returncode != 0:
        print(f"[flatten] name harmonise FAILED:\n{cp2.stdout}{cp2.stderr}",
              file=sys.stderr)
        return 2

    print(f"[flatten] OK: {args.output} "
          f"({args.output.stat().st_size} bytes)")
    print(cp.stdout.strip().splitlines()[-1] if cp.stdout else "")

    if not args.keep_tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
