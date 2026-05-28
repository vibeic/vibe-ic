#!/usr/bin/env python3
"""score_cocotb_mcp.py — Shape D scorer wrapping the iic-eda container's icarus + cocotb.

This is a CLI fallback: a host-side runner that does the same thing the MCP
`eda_cocotb` tool does (Icarus + cocotb), but invocable directly via docker exec
so a new plugin user can score Shape-D benchmarks (CVDP-style) without writing
their own subprocess plumbing.

Substitution disclosure: official CVDP harness uses `nvidia/cvdp-sim:v1.0.0`
(gated). We substitute the `iic-eda` (hpretl/iic-osic-tools) container which
ships iverilog 13 + cocotb 2.0.1 + cocotb_tools. Per the methodology skill § 3.

Input layout (Shape D per BENCHMARK_REGISTRY.layout):
    <project>/work/rtl/<dut>.sv                       (candidate RTL — blind authored)
    <project>/work/PROMPT.txt                         (blind input)
    <project>/work/docs/specification.md              (blind input)
    <project>/score/src/test_<dut>.py                 (HIDDEN cocotb test — scoring only)
    <project>/score/src/harness_library.py            (HIDDEN helper)
    <project>/score/src/test_runner.py                (HIDDEN runner)

The candidate RTL + the hidden testbench Python need to be co-located inside
the iic-eda container's mount (typically /foss/designs). This script stages
both into a temp work_dir under the mount, sets PYTHONPATH, and runs
test_runner.py via `docker exec`.

Usage:
    python3 score_cocotb_mcp.py --project /path/to/cvdp_fixed_priority_arbiter \\
        --top fixed_priority_arbiter --rtl work/rtl/fixed_priority_arbiter.sv \\
        --mount-root /home/<user>/AI_IC_design \\
        --container iic-eda

Outputs <project>/reports/cocotb_score.json with the TESTS / PASS / FAIL counts.
"""
from __future__ import annotations
import argparse, json, subprocess, shutil, time, re
from pathlib import Path


def _docker_path(host_path: Path, mount_host: Path, mount_container: str = "/foss/designs") -> str:
    """Translate a host path under <mount_host> to the corresponding container path."""
    rel = host_path.resolve().relative_to(mount_host.resolve())
    return f"{mount_container}/{rel}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True, help="Shape-D project dir (work/ + score/ subdirs)")
    ap.add_argument("--top", required=True, help="DUT top module name")
    ap.add_argument("--rtl", required=True, help="RTL file path (relative to --project) — the candidate to score")
    ap.add_argument("--mount-root", required=True, help="host path mounted into the container as /foss/designs (e.g. /home/<user>/AI_IC_design)")
    ap.add_argument("--mount-container", default="/foss/designs")
    ap.add_argument("--container", default="iic-eda")
    ap.add_argument("--simulator", default="icarus")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    project = Path(a.project).resolve()
    mount_host = Path(a.mount_root).resolve()
    if mount_host not in project.parents and project != mount_host:
        raise SystemExit(
            f"Project must live UNDER --mount-root ({mount_host}) so the container can see it.\n"
            f"  project    = {project}\n"
            f"Symlinks are NOT followed across the docker mount; rsync the project under the mount.")

    rtl_host = project / a.rtl
    if not rtl_host.is_file():
        raise SystemExit(f"RTL not found: {rtl_host}")

    score_src_host = project / "score" / "src"
    test_py = next(score_src_host.glob(f"test_{a.top}.py"), None)
    if not test_py:
        # any test_*.py EXCEPT test_runner.py (which is the pytest entry point,
        # not the cocotb test module). Pick deterministically (sorted).
        cands = sorted(p for p in score_src_host.glob("test_*.py") if p.name != "test_runner.py")
        test_py = cands[0] if cands else None
    if not test_py:
        raise SystemExit(f"No test_*.py under {score_src_host}")
    if not (score_src_host / "test_runner.py").is_file():
        raise SystemExit(f"No test_runner.py under {score_src_host}")

    # Stage a clean work_dir inside the project (same mount) — colocate RTL + score/src/*.py
    work_dir = project / "cocotb_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    # copy RTL
    shutil.copy2(rtl_host, work_dir / rtl_host.name)
    # copy all sibling .py from score/src (mcp eda_cocotb v0.1.13 convention)
    for py in score_src_host.glob("*.py"):
        shutil.copy2(py, work_dir / py.name)

    rtl_c = _docker_path(work_dir / rtl_host.name, mount_host, a.mount_container)
    work_c = _docker_path(work_dir, mount_host, a.mount_container)
    test_module = test_py.stem

    # iic-eda container ships iverilog under /foss/tools/bin and libvvp.so under
    # /foss/tools/iverilog/lib — those paths are only injected by the container's
    # login profile (`bash -lc`), NOT by plain `docker exec`. Use bash -lc so the
    # session inherits the full toolchain PATH + LD_LIBRARY_PATH.
    inner = (
        f"export VERILOG_SOURCES={rtl_c}; "
        f"export SIM={a.simulator}; "
        f"export TOPLEVEL={a.top}; "
        f"export MODULE={test_module}; "
        f"export PYTHONPATH={work_c}:${{PYTHONPATH:-}}; "
        f"cd {work_c} && python3 -m pytest -rA -s test_runner.py"
    )
    cmd = ["docker", "exec", a.container, "bash", "-lc", inner]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
    elapsed = time.time() - t0
    out = p.stdout + p.stderr

    # cocotb / pytest reports "TESTS=N PASS=M FAIL=K SKIP=L"
    m = re.search(r"TESTS\s*=\s*(\d+)\s+PASS\s*=\s*(\d+)\s+FAIL\s*=\s*(\d+)\s+SKIP\s*=\s*(\d+)", out)
    if m:
        tests, passed, failed, skipped = (int(x) for x in m.groups())
    else:
        tests = passed = failed = skipped = 0

    summary = {
        "project": str(project),
        "top": a.top,
        "shape": "D",
        "tool": f"docker exec {a.container} (iverilog + cocotb)",
        "tool_substitution_note": "Substitutes nvidia/cvdp-sim:v1.0.0 (gated). cocotb 2.0.1; see open-benchmark-methodology skill § 3.",
        "tests": tests, "passed": passed, "failed": failed, "skipped": skipped,
        "verdict": "PASS" if (tests > 0 and failed == 0 and skipped == 0 and passed == tests) else "FAIL",
        "elapsed_s": round(elapsed, 2),
        "log_tail": out[-2000:],
    }
    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "cocotb_score.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{a.top} (Shape D)  TESTS={tests} PASS={passed} FAIL={failed} SKIP={skipped}  → verdict {summary['verdict']}")
    print(f"  cocotb_score.json: {reports / 'cocotb_score.json'}")
    raise SystemExit(0 if summary["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
