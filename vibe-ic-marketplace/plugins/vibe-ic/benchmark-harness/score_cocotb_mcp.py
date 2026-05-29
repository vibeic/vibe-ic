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


def _container_mounts(container: str):
    """Return list of (host_source, container_destination) tuples from `docker inspect`.

    Empty list means the container doesn't exist or has no bind mounts. Raises
    SystemExit on container-not-found so we fail fast before scoring.
    """
    try:
        out = subprocess.check_output(
            ["docker", "inspect", container], text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"docker inspect {container!r} failed (is the container running?): {e.output.strip()}")
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if not data:
        return []
    mounts = data[0].get("Mounts", []) or []
    return [(Path(m["Source"]).resolve(), m["Destination"]) for m in mounts if m.get("Source")]


def _validate_mount(container: str, mount_host: Path, mount_container: str):
    """Refuse to proceed if --mount-root + --mount-container don't match an actual
    docker bind mount. Captured from v0.1.53 CVDP run: a wrong --mount-root produced
    a silent TESTS=0 PASS=0 FAIL=0 SKIP=0 with the real error ('cd: ... No such file
    or directory') buried in log_tail. Fail loudly instead."""
    actual = _container_mounts(container)
    if not actual:
        # container has no mounts at all — proceeding is futile
        raise SystemExit(
            f"Container {container!r} has no bind mounts; cannot reach project from host.\n"
            f"  Expected mount: {mount_host} → {mount_container}")
    # accept either an EXACT match or a parent-of relationship (mount_host is under an actual source)
    for src, dst in actual:
        if (mount_host == src or src in mount_host.parents) and dst == mount_container:
            return
    listing = "\n".join(f"    {s} → {d}" for s, d in actual)
    raise SystemExit(
        f"--mount-root {mount_host} → {mount_container} is NOT an actual bind mount on container {container!r}.\n"
        f"Actual mounts:\n{listing}\n"
        f"Fix: either pass --mount-root that matches one of the above sources, or rsync the\n"
        f"project under one of them and re-run with the matching --mount-root.")


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
    ap.add_argument("--no-variant-fallback", action="store_true",
                    help="(default OFF = fallback ON) Disable the automatic "
                         "sync→async reset variant fallback. Default behaviour: "
                         "when the primary RTL FAILs, look for a sibling "
                         "<top>_async.sv (next to <top>.sv OR under "
                         "phase2/stage1/rtl_variants/) and re-score with it. "
                         "Captures the v0.1.24 documented Cat-A spec↔harness "
                         "inconsistency (sync NBA races reset_dut) as a "
                         "deterministic gate, not an AI-knowledge requirement.")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    mount_host = Path(a.mount_root).resolve()
    if mount_host not in project.parents and project != mount_host:
        raise SystemExit(
            f"Project must live UNDER --mount-root ({mount_host}) so the container can see it.\n"
            f"  project    = {project}\n"
            f"Symlinks are NOT followed across the docker mount; rsync the project under the mount.")

    # Verify the host-side mount-root is actually bind-mounted into the container.
    # Without this, a wrong --mount-root produces a silent TESTS=0 PASS=0 FAIL=0 SKIP=0
    # with the real error ('cd: ... No such file or directory') buried in log_tail.
    _validate_mount(a.container, mount_host, a.mount_container)

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

    # ── Primary score: run with the requested RTL ─────────────────────────
    primary = _run_one_variant(rtl_host, score_src_host, project,
                                 mount_host, a, test_py.stem)
    tests = primary["tests"]; passed = primary["passed"]
    failed = primary["failed"]; skipped = primary["skipped"]
    primary_verdict = ("PASS" if (tests > 0 and failed == 0 and skipped == 0
                                   and passed == tests) else "FAIL")
    variants_record = [{"rtl": str(rtl_host.relative_to(project)),
                         "variant": "primary",
                         **{k: primary[k] for k in
                            ("tests", "passed", "failed", "skipped",
                             "elapsed_s", "verdict_inferred")}}]

    # ── v0.1.55 capture: sync→async reset variant fallback ───────────────
    # When primary FAILs and --no-variant-fallback wasn't passed, look for
    # a sibling <top>_async.sv (the v0.1.24 documented Cat-A workaround for
    # cocotb harnesses that race synchronous-reset NBA updates). Search both
    # next-to-primary AND phase2/stage1/rtl_variants/.
    fallback_used = False
    fallback_path: Path | None = None
    if primary_verdict == "FAIL" and not a.no_variant_fallback:
        fallback_path = _find_async_variant(rtl_host, project, a.top)
        if fallback_path is not None and fallback_path != rtl_host:
            fb = _run_one_variant(fallback_path, score_src_host, project,
                                    mount_host, a, test_py.stem)
            fb_verdict = ("PASS" if (fb["tests"] > 0 and fb["failed"] == 0
                                       and fb["skipped"] == 0
                                       and fb["passed"] == fb["tests"])
                            else "FAIL")
            variants_record.append({
                "rtl": str(fallback_path.relative_to(project)),
                "variant": "async_fallback",
                **{k: fb[k] for k in
                   ("tests", "passed", "failed", "skipped",
                    "elapsed_s", "verdict_inferred")}})
            if fb_verdict == "PASS":
                fallback_used = True
                tests, passed = fb["tests"], fb["passed"]
                failed, skipped = fb["failed"], fb["skipped"]
                primary = fb  # adopt fallback's log_tail + elapsed

    verdict = ("PASS" if (tests > 0 and failed == 0 and skipped == 0
                            and passed == tests) else "FAIL")
    summary = {
        "project": str(project),
        "top": a.top,
        "shape": "D",
        "tool": f"docker exec {a.container} (iverilog + cocotb)",
        "tool_substitution_note": "Substitutes nvidia/cvdp-sim:v1.0.0 (gated). cocotb 2.0.1; see open-benchmark-methodology skill § 3.",
        "tests": tests, "passed": passed, "failed": failed, "skipped": skipped,
        "verdict": verdict,
        "elapsed_s": primary["elapsed_s"],
        "log_tail": primary["log_tail"],
        "variants_tried": variants_record,
        "variant_fallback_used": fallback_used,
        "variant_fallback_rtl": (str(fallback_path.relative_to(project))
                                  if fallback_used and fallback_path else None),
    }
    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "cocotb_score.json").write_text(json.dumps(summary, indent=2) + "\n")
    suffix = " (via async_fallback)" if fallback_used else ""
    print(f"{a.top} (Shape D)  TESTS={tests} PASS={passed} FAIL={failed} SKIP={skipped}  → verdict {verdict}{suffix}")
    print(f"  cocotb_score.json: {reports / 'cocotb_score.json'}")
    raise SystemExit(0 if verdict == "PASS" else 1)


def _find_async_variant(primary_rtl: Path, project: Path, top: str) -> Path | None:
    """Locate a `<top>_async.sv` (or `.v`) sibling. Looks in 4 places:
       (1) next to the primary RTL itself
       (2) project/phase2/stage1/rtl_variants/
       (3) project/work/rtl/  (a flat copy convention)
       (4) project/phase2/stage1/rtl/  (the runner's emit path)
    Returns None if no async sibling exists.
    """
    candidates = [
        primary_rtl.parent / f"{top}_async.sv",
        primary_rtl.parent / f"{top}_async.v",
        project / "phase2" / "stage1" / "rtl_variants" / f"{top}_async.sv",
        project / "phase2" / "stage1" / "rtl_variants" / f"{top}_async.v",
        project / "work" / "rtl" / f"{top}_async.sv",
        project / "work" / "rtl" / f"{top}_async.v",
        project / "phase2" / "stage1" / "rtl" / f"{top}_async.sv",
        project / "phase2" / "stage1" / "rtl" / f"{top}_async.v",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _run_one_variant(rtl_host: Path, score_src_host: Path, project: Path,
                       mount_host: Path, a, test_module: str) -> dict:
    """Stage cocotb_work, run pytest in the container, return parsed counts.
    Factored out at v0.1.55 so the same code path drives the primary and the
    sync→async fallback variants."""
    work_dir = project / "cocotb_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    shutil.copy2(rtl_host, work_dir / rtl_host.name)
    for py in score_src_host.glob("*.py"):
        shutil.copy2(py, work_dir / py.name)
    rtl_c = _docker_path(work_dir / rtl_host.name, mount_host, a.mount_container)
    work_c = _docker_path(work_dir, mount_host, a.mount_container)
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
    m = re.search(r"TESTS\s*=\s*(\d+)\s+PASS\s*=\s*(\d+)\s+FAIL\s*=\s*(\d+)\s+SKIP\s*=\s*(\d+)", out)
    if m:
        tests, passed, failed, skipped = (int(x) for x in m.groups())
    else:
        tests = passed = failed = skipped = 0
    verdict_inferred = ("PASS" if (tests > 0 and failed == 0 and skipped == 0
                                     and passed == tests) else "FAIL")
    return {"tests": tests, "passed": passed, "failed": failed,
             "skipped": skipped, "elapsed_s": round(elapsed, 2),
             "log_tail": out[-2000:], "verdict_inferred": verdict_inferred}


if __name__ == "__main__":
    main()
