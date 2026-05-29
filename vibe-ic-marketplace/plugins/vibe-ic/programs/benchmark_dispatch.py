#!/usr/bin/env python3
"""benchmark_dispatch.py — entry point for /vibe-ic-benchmark.

Reads BENCHMARK_REGISTRY.json, picks the correct run-shape per
open-benchmark-methodology skill § 2, sets up the run dir scaffold, and prints
the canonical next-step commands (clone dataset / drive runner or gates /
invoke scorer / write RESULT.md). Does NOT itself perform the AI authoring
step — the agent does that, guided by the per-shape blind_instructions_*.md.

Usage:
    python3 benchmark_dispatch.py <bench>                       # check status + show plan
    python3 benchmark_dispatch.py <bench> --setup               # create run dir scaffold
    python3 benchmark_dispatch.py <bench> --setup --dataset <ds>  # also pin dataset path
    python3 benchmark_dispatch.py <bench> --score --run <dir> --dataset <ds>  # invoke scorer
    python3 benchmark_dispatch.py --list                         # list all known benchmarks
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "benchmark-harness"
REGISTRY = HARNESS / "BENCHMARK_REGISTRY.json"


def _load_registry() -> dict:
    return json.loads(REGISTRY.read_text())


def _entry(name: str) -> dict:
    reg = _load_registry()
    e = reg.get("benchmarks", {}).get(name)
    if not e:
        raise SystemExit(
            f"Benchmark '{name}' not in registry. Known: "
            + ", ".join(sorted(reg.get('benchmarks', {}).keys())))
    return e


def _env_check():
    """Detect environment requirements (iverilog, iic-eda container, MCP)."""
    have_iverilog = subprocess.run(["which", "iverilog"], capture_output=True).returncode == 0
    try:
        docker_ps = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                                   capture_output=True, text=True, timeout=5).stdout
        have_iiceda = "iic-eda" in docker_ps
    except (FileNotFoundError, subprocess.TimeoutExpired):
        have_iiceda = False
    return {"iverilog": have_iverilog, "iic_eda_running": have_iiceda}


def cmd_list():
    reg = _load_registry()
    print(f"{'BENCHMARK':<22}{'SHAPE':<8}STATUS")
    print("-" * 80)
    for name, e in reg.get("benchmarks", {}).items():
        print(f"{name:<22}{e.get('shape',''):<8}{e.get('status','')}")


def cmd_show(bench: str):
    e = _entry(bench)
    print(f"# {e.get('title', bench)}")
    print(f"  Shape: {e['shape']}     Status: {e.get('status')}")
    # § 4.1 + § 8.1 of open-benchmark-methodology (user directive 2026-05-29):
    # DEFAULT on "run X benchmark" with no qualifier = re-attempt the FAILing
    # set BLIND on the current plugin version. Do NOT skip on prior FLOOR.
    print()
    print("# DEFAULT BEHAVIOUR (per skill § 4.1 + § 8.1, 2026-05-29 user policy):")
    print("# When the user asks 'run <bench>' with no other flag, the default action")
    print("# is to RE-ATTEMPT prior FAIL/FLOOR cases BLIND on the current plugin —")
    print("# NOT to publish the prior canonical and skip. Use --reattempt-floor to")
    print("# print the prior FAILing-problem list for this benchmark from the")
    print("# newest scoring artifact under benchmark_external/<bench>/")
    print("# (Shape-C pass_at_1.json / Shape-D cocotb_score.json / RESULT.md).")
    print()
    if "dataset" in e:
        ds = e["dataset"]
        if "repo" in ds:
            print(f"  Dataset repo: {ds['repo']}")
        if "huggingface" in ds:
            print(f"  Dataset HF:   {ds['huggingface']}")
        if "license" in ds:
            print(f"  License:      {ds['license']}")
    if e.get("blocker"):
        print(f"  BLOCKER: {e['blocker']}")
        print()
        print("This benchmark is Shape E (blocked / out-of-scope). Document it in your RESULT but do NOT publish a number.")
        return
    print()
    print("## Recommended invocation")
    shape = e["shape"]
    if shape == "A":
        print("  /vibe-ic-all <project>     # full doc→GDS (benchmark_clean style)")
        print("  Then run skill `benchmark-verify` for the six-pillar verification.")
    elif shape == "B":
        bi = HARNESS / "blind_instructions_shape_b.md"
        scorer = HARNESS / e.get("scorer", "score_iverilog_tb.py")
        print(f"  1. Clone dataset: git clone {e['dataset']['repo']} <DATASET>")
        print(f"  2. Set up run dir:")
        print(f"     python3 {Path(__file__).name} {bench} --setup --dataset <DATASET> --run <RUNDIR>")
        print(f"  3. Drive batches per blind instructions: {bi}")
        print(f"     For each design: vibe_ic_one_shot_runner.py <project> --skip-phase3 --skip-analog --skip-hardware")
        print(f"  4. Score: python3 {scorer} --bench {bench} --dataset <DATASET> --run <RUNDIR>")
    elif shape == "C":
        bi = HARNESS / "blind_instructions_shape_c.md"
        scorer = HARNESS / e.get("scorer", "score_iverilog_tb.py")
        gates = HARNESS / "gates_atomic.py"
        print(f"  1. Clone dataset: git clone {e['dataset']['repo']} <DATASET>")
        print(f"  2. Set up run dir:")
        print(f"     python3 {Path(__file__).name} {bench} --setup --dataset <DATASET> --run <RUNDIR>")
        print(f"  3. Drive batches per blind instructions: {bi}")
        print(f"     Per-problem gate: python3 {gates} --prob <Prob> --workdir <RUNDIR>/work --dataset <DATASET> --bench {bench}")
        print(f"  4. Score: python3 {scorer} --bench {bench} --dataset <DATASET> --run <RUNDIR>")
    elif shape == "D":
        bi = HARNESS / "blind_instructions_shape_d.md"
        scorer = HARNESS / "score_cocotb_mcp.py"
        print(f"  1. Clone dataset: git clone {e['dataset']['repo']} <DATASET>")
        print(f"  2. Pick a problem; project = <DATASET>/<problem_dir>")
        print(f"  3. Drive: vibe_ic_one_shot_runner.py <project> --pdk sky130A")
        print(f"  4. Score: python3 {scorer} --project <project> --top <dut> --rtl work/rtl/<dut>.sv --mount-root <ROOT>")
        print(f"  Blind instructions: {bi}")


def cmd_setup(bench: str, dataset: str, run: str):
    e = _entry(bench)
    if e["shape"] == "E":
        raise SystemExit(f"Shape E (blocked/out-of-scope). Cannot setup; see blocker:\n  {e.get('blocker')}")
    run_p = Path(run).resolve()
    ds_p = Path(dataset).resolve()
    if not ds_p.is_dir():
        raise SystemExit(f"Dataset path not found: {ds_p}\n"
                         f"Clone first: git clone {e.get('dataset',{}).get('repo','<URL>')} {ds_p}")
    (run_p / "work").mkdir(parents=True, exist_ok=True)
    (run_p / "samples").mkdir(parents=True, exist_ok=True)
    (run_p / "batches").mkdir(parents=True, exist_ok=True)

    # discover problems.list
    shape = e["shape"]
    layout = e.get("layout", {})
    problems = []
    if shape == "C":
        suffix = layout.get("prompt_suffix", "_prompt.txt")
        problems = sorted(p.name.removesuffix(suffix) for p in ds_p.glob(f"*{suffix}"))
    elif shape == "B":
        fn = layout.get("prompt_filename", "design_description.txt")
        problems = sorted(str(p.parent.relative_to(ds_p)) for p in ds_p.rglob(fn) if p.is_file())
    elif shape == "D":
        # v0.1.56 (general; was bench-name-specific in v0.1.55).
        # Shape-D agentic benchmarks ship either as JSONL (CVDP-style:
        # one row per problem with prompt/context/harness) OR as
        # per-problem subdirs already in the Shape-D layout.
        #
        # Auto-detect: if --dataset contains *.jsonl, run the general
        # agentic_jsonl_to_shape_d.py extractor. Otherwise fall through
        # to subdir-discovery (next branch) — no benchmark-name branching.
        if any(ds_p.glob("*.jsonl")):
            import subprocess as _sp
            extractor = Path(__file__).parent / "agentic_jsonl_to_shape_d.py"
            rc = _sp.run(["python3", str(extractor),
                           "--dataset", str(ds_p), "--rundir", str(run_p)],
                          check=False)
            if rc.returncode != 0:
                raise SystemExit(f"agentic_jsonl_to_shape_d failed (rc={rc.returncode})")
            if (run_p / "problems.list").is_file():
                problems = [p for p in (run_p / "problems.list").read_text().splitlines() if p]
        else:
            # Already-laid-out per-problem subdirs: each subdir with work/PROMPT.txt
            # qualifies as a Shape-D problem. Bench-agnostic discovery.
            problems = sorted(str(p.parent.parent.relative_to(ds_p))
                              for p in ds_p.rglob("work/PROMPT.txt") if p.is_file())
    (run_p / "problems.list").write_text("\n".join(problems) + "\n")
    # batches of 10
    for i in range(0, len(problems), 10):
        batch_id = f"batch{i//10:02d}"
        (run_p / "batches" / f"{batch_id}.list").write_text("\n".join(problems[i:i+10]) + "\n")

    # write a .config so subsequent commands know the dataset path
    (run_p / ".bench_config.json").write_text(json.dumps({
        "bench": bench, "dataset": str(ds_p), "shape": shape,
        "problems": len(problems), "batches": (len(problems) + 9) // 10,
    }, indent=2) + "\n")
    print(f"Set up Shape-{shape} run dir for {bench}:")
    print(f"  problems: {len(problems)}")
    print(f"  batches:  {(len(problems) + 9) // 10}")
    print(f"  RUNDIR:   {run_p}")
    bi = HARNESS / f"blind_instructions_shape_{shape.lower()}.md"
    if bi.is_file():
        print(f"  Read the blind instructions next: {bi}")


def cmd_reattempt_floor(bench: str) -> int:
    """v0.1.53 — per § 4.1 / § 8.1 user directive. Surface the prior FAIL
    list so the next run can re-attempt them BLIND. Default policy: do NOT
    inherit FLOOR labels — every fail must be re-justified from a FRESH
    re-run on the current plugin.

    v0.1.55 capture: in addition to Shape-C `pass_at_1.json`, scan Shape-D
    `cocotb_score.json` and, as a final fallback, the newest RESULT*.md, so
    benchmarks like CVDP don't get falsely labelled as "FIRST RUN" when they
    actually have prior runs.
    """
    import glob
    # Find newest scoring artifact under benchmark_external/<bench>/
    name_map = {
        "verilogeval-v2":    "verilogeval_v2",
        "verilogeval-human": "verilogeval_human",
        "rtllm":             "rtllm",
        "cvdp":              "cvdp",
    }
    bench_dir = name_map.get(bench, bench.replace("-", "_"))
    e = _entry(bench)
    shape = e.get("shape", "?")
    base = f"benchmark_external/{bench_dir}"

    # Shape-aware scoring-artifact priority
    if shape == "D":
        artifact_globs = [f"{base}/**/cocotb_score.json",
                          f"{base}/**/pass_at_1.json"]
    else:
        artifact_globs = [f"{base}/**/pass_at_1.json",
                          f"{base}/**/cocotb_score.json"]

    candidates: list[str] = []
    for g in artifact_globs:
        candidates.extend(glob.glob(g, recursive=True))
    candidates = sorted(candidates, key=lambda p: os.path.getmtime(p), reverse=True)

    if not candidates:
        # Fallback: any prior RESULT*.md is still proof of a prior run.
        md = sorted(glob.glob(f"{base}/**/RESULT*.md", recursive=True),
                    key=lambda p: os.path.getmtime(p), reverse=True)
        if not md:
            print(f"No prior scoring artifact under {base}/")
            print("This is a FIRST RUN — there are no prior fails to re-attempt.")
            print("Proceed with the standard --setup workflow.")
            return 0
        newest = md[0]
        head = "\n".join(Path(newest).read_text().splitlines()[:6])
        print(f"# Newest RESULT.md: {newest}")
        print("# (no machine-readable score; cannot enumerate per-problem fails)")
        print("# RESULT headline:")
        for line in head.splitlines():
            print(f"#   {line}")
        print()
        print("# Action: re-run blind (the FLOOR re-attempt policy applies).")
        return 0

    newest = candidates[0]
    print(f"# Newest scoring artifact: {newest}")
    data = json.loads(Path(newest).read_text())

    # Shape-C / aggregate-per-problem schema
    if "results" in data and isinstance(data["results"], list):
        total = data.get("total", "?")
        passed = data.get("passed", "?")
        pct = data.get("pass_at_1_pct", "?")
        print(f"# Prior canonical: {passed}/{total} = {pct}%")
        fails = [r for r in data["results"] if r.get("verdict") != "PASS"]
        print(f"# Prior FAILing problems: {len(fails)}")
        print()
        print("# § 4.1 + § 8.1 policy: re-attempt EACH of these BLIND on the")
        print("# current plugin version. The FLOOR label only sticks if it")
        print("# survives a fresh attempt — re-justify from new run.")
        print()
        for r in fails:
            prob = r["problem"]
            reason = r.get("reason", "")
            print(f"  {prob:<36} {reason[:80]}")
        print()
        print("# Next step (Shape C):")
        print(f"#   gates_atomic.py --prob <Prob> --workdir <RUNDIR>/work --dataset <DS> --bench {bench}")
        return 0

    # Shape-D cocotb_score.json schema (per-cocotb-run aggregate counts)
    if "tests" in data and "failed" in data:
        print(f"# Prior Shape-D cocotb run: TESTS={data.get('tests')} PASS={data.get('passed')} FAIL={data.get('failed')} SKIP={data.get('skipped')}")
        print(f"# Verdict: {data.get('verdict')}")
        if data.get("variant_fallback_used"):
            print(f"# variant_fallback used: {data.get('variant_fallback_rtl')}")
        if int(data.get("failed", 0) or 0) == 0:
            print("# No prior FAILs to re-attempt — but per § 4.1 default policy,")
            print("# re-run BLIND anyway (DON'T inherit prior PASS labels either).")
        else:
            print(f"# Prior FAIL count: {data.get('failed')}")
            print("# Shape-D cocotb_score.json carries aggregate counts only; per-test")
            print("# FAIL names are in log_tail — inspect manually before re-attempting.")
        print()
        print("# Next step (Shape D):")
        print(f"#   1. python3 vibe_ic_one_shot_runner.py <project> --skip-phase3 --skip-analog --skip-hardware")
        print(f"#   2. python3 score_cocotb_mcp.py --project <project> --top <dut> --rtl work/rtl/<dut>.sv --mount-root <ROOT>")
        return 0

    print(f"# Unrecognised scoring schema in {newest}; cannot enumerate fails.")
    print("# Re-run blind per the default policy.")
    return 0


def cmd_score(bench: str, run: str, dataset: str | None):
    e = _entry(bench)
    if e["shape"] not in ("B", "C"):
        raise SystemExit(f"--score only handles Shape B + C here. Shape {e['shape']} → use score_cocotb_mcp.py / benchmark-verify skill.")
    run_p = Path(run).resolve()
    if dataset:
        ds_p = Path(dataset)
    else:
        cfg = run_p / ".bench_config.json"
        if not cfg.is_file():
            raise SystemExit("Pass --dataset, or run --setup first to pin the dataset path.")
        ds_p = Path(json.loads(cfg.read_text())["dataset"])
    scorer = HARNESS / e.get("scorer", "score_iverilog_tb.py")
    cmd = [sys.executable, str(scorer), "--bench", bench, "--dataset", str(ds_p), "--run", str(run_p)]
    print("$ " + " ".join(cmd))
    sys.exit(subprocess.call(cmd))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bench", nargs="?", help="benchmark name (see --list)")
    ap.add_argument("--list", action="store_true", help="list known benchmarks")
    ap.add_argument("--setup", action="store_true", help="create run dir scaffold")
    ap.add_argument("--score", action="store_true", help="invoke the scorer on an existing run dir")
    ap.add_argument("--reattempt-floor", action="store_true",
                    help="print prior FAILing-problem list (per § 4.1 default policy)")
    ap.add_argument("--dataset", help="dataset path on disk")
    ap.add_argument("--run", help="run dir")
    a = ap.parse_args()

    if a.list:
        cmd_list()
        return
    if not a.bench:
        ap.print_help()
        sys.exit(2)
    if a.setup:
        if not (a.dataset and a.run):
            raise SystemExit("--setup requires --dataset and --run")
        cmd_setup(a.bench, a.dataset, a.run)
        return
    if a.score:
        if not a.run:
            raise SystemExit("--score requires --run")
        cmd_score(a.bench, a.run, a.dataset)
        return
    if a.reattempt_floor:
        sys.exit(cmd_reattempt_floor(a.bench))

    # default: show plan + env status
    env = _env_check()
    print(f"# Environment: iverilog={'OK' if env['iverilog'] else 'MISSING'}, "
          f"iic-eda container={'RUNNING' if env['iic_eda_running'] else 'NOT RUNNING'}")
    print()
    cmd_show(a.bench)


if __name__ == "__main__":
    main()
