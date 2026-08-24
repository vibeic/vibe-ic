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
import re
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "benchmark"
REGISTRY = HARNESS / "BENCHMARK_REGISTRY.json"
EXPERT_AGENT_MD = Path(__file__).resolve().parent.parent / "agents" / "ic-expert-agent.md"


# ORGANIC-20260605-shapec-lesson-digest-injection — surface captured lessons to
# blind single-shot authors. The renderer was hoisted to the shared module
# `_lesson_digest` so the PRODUCTION spec-to-rtl path (design_one_shot_runner
# step_rtl_gen WAIVE) surfaces the SAME corpus to runner-driven authors. This
# thin alias preserves the historical `benchmark_dispatch._render_lesson_digest`
# entry point (Shape-C `--setup`) and its name for existing tests.
#
# CONSUME CONTRACT (#733 — staged != consumed): the rendered digest header makes
# it MANDATORY that BEFORE authoring each design the author keyword-match the
# design genre against each section's "When to apply" and apply every matched
# section (Section 4-E: apply unless the spec states otherwise). The digest is
# blindness-clean — `_lesson_digest` scrubs benchmark design identifiers so no
# design-name->solution association is surfaced.
from _lesson_digest import render_lesson_digest as _render_lesson_digest  # noqa: E402


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
    """Detect environment requirements (iverilog, vibeic-eda container, MCP)."""
    have_iverilog = subprocess.run(["which", "iverilog"], capture_output=True).returncode == 0
    try:
        docker_ps = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                                   capture_output=True, text=True, timeout=5).stdout
        have_iiceda = "vibeic-eda" in docker_ps
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
    # § 4.1 + § 8.1 of open-benchmark-methodology (user directive 2026-06-04,
    # BINDING, supersedes the 2026-05-29 re-attempt-FAILing-set default):
    # DEFAULT on "run X benchmark" with no qualifier = CLEAN-ROOM FULL re-run.
    print()
    print("# DEFAULT BEHAVIOUR (per skill § 4.1 + § 8.1, 2026-06-04 user policy):")
    print("# 'run <bench>' with no flag = CLEAN-ROOM FULL re-run. A fresh agent")
    print("# authors EVERY problem from the spec alone, blind to any prior run.")
    print("# The authoring context starts EMPTY. A clean-room run MUST NOT read:")
    print("#   (1) prior run samples / artifacts,")
    print("#   (2) agent memory,")
    print("#   (3) any cached result in storage (prior pass_at_1.json / scores).")
    print("# --setup scaffolds a FRESH run dir with an EMPTY samples/; the")
    print("# benchmark_clean_room_check.py guard FAILs a contaminated run so it")
    print("# cannot be scored as canonical.")
    print("#")
    print("# Re-attempting ONLY the prior FAILing set is an EXPLICIT OPTION, never")
    print("# the default: pass --floor-only (it still re-authors each selected")
    print("# problem BLIND — no inherited RTL/samples). Use --reattempt-floor to")
    print("# print the prior FAILing-problem list to drive a --floor-only run.")
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
        exp = Path(__file__).resolve().parent / "shape_b_sample_export.py"
        print(f"  3b. Export each sample (DETERMINISTIC sole emit path, #678 — "
              f"never hand-copy a single module):")
        print(f"      python3 {exp} --project <project> --leaf <leaf> --samples <RUNDIR>/samples [--module <name>]")
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
    elif isinstance(e.get("flow"), dict):
        # #532 round-2 (adversarial review): composite shapes ("C/D") carry
        # their own documented flow — surface it instead of an empty section.
        for k, v in e["flow"].items():
            print(f"  {k}: {v}")
        if e.get("scorer"):
            print(f"  scorer: {e['scorer']}")
        if e.get("triage"):
            print(f"  triage: {e['triage']}")
    else:
        raise SystemExit(
            f"unhandled shape {shape!r} for {bench!r} and no flow dict in "
            f"the registry entry — refusing to print an empty plan")


def cmd_setup(bench: str, dataset: str, run: str, floor_only: bool = False):
    e = _entry(bench)
    if e["shape"] == "E":
        raise SystemExit(f"Shape E (blocked/out-of-scope). Cannot setup; see blocker:\n  {e.get('blocker')}")
    if e["shape"] not in ("B", "C", "D"):
        # #532 round-2 (adversarial review): a composite shape ("C/D") fell
        # through every problem-discovery branch and produced a SILENT
        # 0-problem scaffold that exits 0. Refuse loudly and point at the
        # entry's documented flow instead.
        flow = e.get("flow")
        hint = ("\n  documented flow: " + json.dumps(flow, ensure_ascii=False)
                ) if flow else ""
        raise SystemExit(
            f"shape {e['shape']!r} has no generic --setup scaffold — drive "
            f"this benchmark via its documented flow (see --show {bench})."
            + hint)
    run_p = Path(run).resolve()
    ds_p = Path(dataset).resolve()
    if not ds_p.is_dir():
        raise SystemExit(f"Dataset path not found: {ds_p}\n"
                         f"Clone first: git clone {e.get('dataset',{}).get('repo','<URL>')} {ds_p}")
    # ── Clean-room enforcement (ORGANIC-20260604, user directive 2026-06-04) ──
    # A clean-room run authors EVERY problem fresh; the run dir's samples/ MUST
    # be EMPTY at --setup. Refuse to set up on top of a prior run's samples
    # (default AND --floor-only) — a fresh run dir is required so no prior
    # authoring is inherited. This is the deterministic half of "一定是重跑".
    samples_dir = run_p / "samples"
    if samples_dir.is_dir() and any(samples_dir.rglob("*")):
        raise SystemExit(
            f"clean-room violation: {samples_dir} is NOT empty — it carries a "
            "prior run's samples. A clean-room run must start EMPTY (user "
            "directive 2026-06-04: '一定是重跑', no inherited samples). Use a "
            "FRESH --run dir. Re-attempting only the prior FAILing set is an "
            "explicit option (--floor-only) but it still re-authors blind into "
            "a fresh dir.")
    (run_p / "work").mkdir(parents=True, exist_ok=True)
    (run_p / "samples").mkdir(parents=True, exist_ok=True)
    (run_p / "batches").mkdir(parents=True, exist_ok=True)
    # ORGANIC-20260605-transcripts-export-default: transcript export is the
    # orchestration DEFAULT, not an optional extra — pre-create the audit
    # input dir so the blindness guard has something to audit at --score.
    (run_p / "transcripts").mkdir(parents=True, exist_ok=True)

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

    # write a .config so subsequent commands know the dataset path.
    # clean_room=true is the default; floor_only records the explicit opt-in.
    # inherited_from/seed_run are intentionally NULL — a clean-room run inherits
    # nothing (the clean-room guard FAILs any run that sets them, except a
    # floor_only run may NAME its seed run in inherited_from with fresh samples).
    (run_p / ".bench_config.json").write_text(json.dumps({
        "bench": bench, "dataset": str(ds_p), "shape": shape,
        "problems": len(problems), "batches": (len(problems) + 9) // 10,
        "clean_room": True,
        "floor_only": bool(floor_only),
        "inherited_from": None,
        "seed_run": None,
    }, indent=2) + "\n")
    mode = "FLOOR-ONLY (blind re-author of the prior FAIL set)" if floor_only \
        else "CLEAN-ROOM FULL re-run (every problem authored fresh)"
    print(f"Set up Shape-{shape} run dir for {bench}  [{mode}]:")
    print(f"  problems: {len(problems)}")
    print(f"  batches:  {(len(problems) + 9) // 10}")
    print(f"  RUNDIR:   {run_p}")
    # ORGANIC-20260605-shapec-lesson-digest-injection: render the captured
    # general-pattern lessons so blind authors actually receive them.
    n_lessons = _render_lesson_digest(run_p)
    if n_lessons:
        print(f"  lessons:  {n_lessons} captured general-pattern lessons → "
              f"{run_p / 'lessons.md'}  (authors MUST read before authoring)")
    print(f"  transcripts: EXPORT REQUIRED — copy every authoring/close-loop "
          f"agent's transcript (or tool-call log) to {run_p / 'transcripts'}/ "
          f"named per agent; the blindness audit at --score reads them "
          f"(ORGANIC-20260605-transcripts-export-default).")
    # Verify the fresh run dir is clean-room (empty samples, no seed config).
    guard = Path(__file__).resolve().parent / "benchmark_clean_room_check.py"
    if guard.is_file():
        rc = subprocess.call([sys.executable, str(guard), str(run_p)])
        if rc != 0:
            raise SystemExit("clean-room guard FAILed on the fresh run dir — "
                             "see violations above; do not author into it.")
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
    # Find newest scoring artifact under benchmark-data/evaluation/<bench>/
    name_map = {
        "verilogeval-v2":    "verilogeval_v2",
        "verilogeval-human": "verilogeval_human",
        "rtllm":             "rtllm",
        "cvdp":              "cvdp",
    }
    bench_dir = name_map.get(bench, bench.replace("-", "_"))
    e = _entry(bench)
    shape = e.get("shape", "?")
    base = f"benchmark-data/evaluation/{bench_dir}"

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


def cmd_score(bench: str, run: str, dataset: str | None,
              allow_ungated: bool = False, allow_direct_agent: bool = False):
    e = _entry(bench)
    if e["shape"] not in ("B", "C"):
        raise SystemExit(f"--score only handles Shape B + C here. Shape {e['shape']} → use score_cocotb_mcp.py / benchmark-verify skill.")
    run_p = Path(run).resolve()
    # Front-door Vibe-IC entry gate (owner directive 2026-06-28): refuse to
    # score a run that did not enter through the Vibe-IC plugin.  Direct-agent
    # authoring / patching followed by a host-scorer invocation measures
    # "Opus + MCP-EDA", not Vibe-IC.
    entry_guard = Path(__file__).resolve().parent / "vibe_ic_entry_guard.py"
    if entry_guard.is_file() and not allow_direct_agent:
        rc = subprocess.call([sys.executable, str(entry_guard), str(run_p),
                              "--strict"])
        if rc != 0:
            raise SystemExit(
                "Vibe-IC entry guard FAILed — this run lacks evidence of "
                "passing through vibe_ic_one_shot_runner.py / phase1. "
                "Run the benchmark through the Vibe-IC plugin; direct-agent "
                "authoring/patching cannot be scored as canonical. "
                "Pass --allow-direct-agent only for a disclosed NON-CANONICAL "
                "exploratory run.")
    # Front-door clean-room gate (ORGANIC-20260604): refuse to score a run that
    # inherited prior samples / scores / memory. The published pass@1 must come
    # from a clean-room run ('一定是重跑', user directive 2026-06-04).
    guard = Path(__file__).resolve().parent / "benchmark_clean_room_check.py"
    if guard.is_file():
        rc = subprocess.call([sys.executable, str(guard), str(run_p)])
        if rc != 0:
            raise SystemExit("clean-room guard FAILed — this run inherited prior "
                             "samples/scores and CANNOT be scored as canonical. "
                             "Re-run clean-room into a fresh dir.")
    if dataset:
        ds_p = Path(dataset)
    else:
        cfg = run_p / ".bench_config.json"
        if not cfg.is_file():
            raise SystemExit("Pass --dataset, or run --setup first to pin the dataset path.")
        ds_p = Path(json.loads(cfg.read_text())["dataset"])
    # Front-door blindness audit (ORGANIC-20260605-blindness-deterministic-
    # audit-guard): when the orchestrator exported batch-agent transcripts to
    # <RUNDIR>/transcripts/, audit them deterministically — any non-prompt
    # dataset access (sibling refs/tests, build files) or agent-side scorer
    # self-run REFUSES scoring. No transcripts exported -> explicit NOTICE
    # (the audit cannot vouch for a run it never saw).
    audit = Path(__file__).resolve().parent / "blindness_audit.py"
    tdir = run_p / "transcripts"
    has_transcripts = tdir.is_dir() and any(tdir.iterdir())
    if audit.is_file() and has_transcripts:
        rc = subprocess.call([sys.executable, str(audit), "--dataset",
                              str(ds_p), "--bench", bench, str(tdir)])
        if rc == 1:
            raise SystemExit(
                "blindness audit FAILed — an agent accessed non-prompt "
                "dataset files or self-ran the host scorer (offending "
                "transcript + path named above). The run is not blind and "
                "CANNOT be scored as canonical; fix the orchestration and "
                "re-run clean-room.")
        # rc == 3 is AUDIT_ERROR (blindness_audit.EXIT_AUDIT_ERROR): the
        # auditor itself crashed (e.g. a malformed transcript line). This is a
        # TOOL failure, NOT a blindness violation — it must NEVER be folded
        # into the FAIL message above (ORGANIC-20260607, #480). Refuse to
        # score (the audit could not vouch for the run) but say so honestly so
        # the host fixes the transcript/auditor rather than the orchestration.
        if rc == 3:
            raise SystemExit(
                "blindness audit could NOT complete (AUDIT_ERROR) — the "
                "auditor hit an internal error while scanning the transcripts "
                "(see message above); this is a tool failure, NOT a blindness "
                "violation. The run is NOT blindness-verified, so it cannot be "
                "scored as canonical yet; fix the transcript/auditor and re-run "
                "the audit. (Do not treat this as 'agent accessed dataset "
                "files'.)")
    elif audit.is_file():
        print("NOTICE: <RUNDIR>/transcripts/ not present or empty — blindness "
              "audit skipped. Export is the orchestration DEFAULT (--setup "
              "pre-creates the dir; copy every agent transcript there). A run "
              "scored on this branch MUST disclose 'blindness audit "
              "unavailable' in its RESULT.md (ORGANIC-20260605-transcripts-"
              "export-default).")
    # Front-door GATE-AS-SOLE-EMIT-PATH guard: every scoreable sample MUST carry a
    # valid emit-path attestation (gates_atomic / shape_b_sample_export wrote it on a
    # clean emit). A sample authored directly into samples/ — bypassing the emit gates
    # + port-reorder — has none, so the number would measure the raw author, not the
    # runner (and silently undercount emit-gate-recoverable designs). HARD-BLOCK by
    # default, exactly like the clean-room + blindness guards; --allow-ungated opts an
    # exploratory direct-author run out (its RESULT.md MUST then disclose NON-CANONICAL).
    emit_chk = Path(__file__).resolve().parent / "emit_attestation_check.py"
    if emit_chk.is_file():
        rc = subprocess.call([sys.executable, str(emit_chk), "--samples",
                              str(run_p / "samples")] + ([] if allow_ungated else ["--strict"]))
        if rc != 0 and not allow_ungated:
            raise SystemExit(
                "emit-attestation guard FAILed — one or more samples were NOT produced "
                "by the deterministic emit path (gates_atomic.py / shape_b_sample_export.py), "
                "so the emit gates + port-reorder never fired and this run is NON-CANONICAL. "
                "Author into a work dir and emit through the gate (the runner does this "
                "automatically), or pass --allow-ungated for a disclosed exploratory run.")
    if allow_direct_agent:
        print("NOTICE: --allow-direct-agent passed — this run is NON-CANONICAL and "
              "its RESULT.md MUST disclose that it did not enter through the "
              "Vibe-IC runner.")
    scorer = HARNESS / e.get("scorer", "score_iverilog_tb.py")
    cmd = [sys.executable, str(scorer), "--bench", bench, "--dataset", str(ds_p), "--run", str(run_p)]
    print("$ " + " ".join(cmd))
    sys.exit(subprocess.call(cmd))


# ── FORMAT BINDING ───────────────────────────────────────────────────────────
# Which IO adapter reads which benchmark's files. This is the ONLY benchmark
# knowledge the dispatcher holds, and it is a mapping, not a code path.
_BENCH_FORMAT = {
    "verilogeval-v2": "verilogeval",
    "verilogeval-human": "verilogeval",
    "rtllm": "rtllm",
    "cvdp-open": "cvdp",
}


def _rtl_gen_waive(project: Path) -> dict | None:
    """The runner's rtl_gen WAIVE record, or None.

    Detected from the report the runner writes, not from stdout text: the
    deterministic dispatch declares `extras.fallback_skill` when it hands over,
    and that field is the handover contract.
    """
    rep = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    if not rep.is_file():
        return None
    try:
        d = json.loads(rep.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    for st in d.get("steps") or []:
        if st.get("name") == "rtl_gen" and st.get("status") == "WAIVED":
            ex = st.get("extras") or {}
            if ex.get("fallback_skill"):
                return {"fallback_skill": ex["fallback_skill"],
                        "detail": st.get("detail", "")}
    return None


def cmd_solve(bench: str, dataset: str, run: str, limit: int = 0) -> int:
    """Solve every problem through the GENERAL flow.

    This verb did not exist. `--setup` scaffolded and `--score` scored, and
    between them was a hole an agent filled by hand — which is how a 302-problem
    CVDP run came to be authored by a prompt->drafts->gate loop that RULE 0
    forbids, and scored 192/302 with no deterministic emit and no
    program-extracted spec.

    What happens per problem, and note that none of it is benchmark-specific:

        benchmark_io_adapter.stage   record/files -> a project (INPUT only;
                                     reading an oracle path RAISES)
        task_nature_route            prompt + supplied RTL -> nature ->
                                     entry_step + evidence class -> exit step
        vibe_ic_one_shot_runner      --entry-step <entry>, the one real runner
        benchmark_io_adapter.collect the artefact -> the scorer's shape

    The adapter is the thin IO shell § 0 permits; everything between IN and OUT
    is the flow a normal design task takes.
    """
    import subprocess                                    # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import task_nature_route as tnr                       # noqa: PLC0415

    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        print(f"ERROR: no IO adapter bound for {bench!r}. Known: "
              f"{sorted(_BENCH_FORMAT)}", file=sys.stderr)
        return 2

    ds, run_p = Path(dataset), Path(run)
    (run_p / "projects").mkdir(parents=True, exist_ok=True)
    (run_p / "responses").mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"

    results, backlog, n = [], [], 0
    for prob in bio.problems(fmt, ds):
        if limit and n >= limit:
            break
        n += 1
        pid = str(prob["id"])
        proj = run_p / "projects" / re.sub(r"[^\w.-]", "_", pid)
        proj.mkdir(parents=True, exist_ok=True)
        staged = bio.stage(fmt, prob, proj)

        rtl_present = any((proj / "input" / "rtl").glob("*")) \
            if (proj / "input" / "rtl").is_dir() else False
        verdict = tnr.classify_task_nature(
            (proj / "input" / "phase1_prompt.md").read_text(errors="replace"),
            rtl_present, None)
        nature = verdict["nature"]
        entry = tnr.NATURE_ENTRY.get(nature, {}).get("entry_step")
        ev = tnr.NATURE_ENTRY.get(nature, {}).get("default_evidence")
        exit_step = (tnr.EVIDENCE_EXIT.get(ev) or {}).get("exit_step")

        argv = [sys.executable, str(runner), str(proj),
                "--skip-analog", "--skip-hardware"]
        # The exit decides what must NOT run. An RTL-evidence benchmark never
        # needs physical design: measured, no open RTL scorer reads a netlist
        # or a GDS, so running phase 3 for one would be work nothing consumes.
        if exit_step and exit_step in tnr.flow_step_ids():
            order = {s: i for i, s in enumerate(tnr.flow_step_ids())}
            if order.get(exit_step, 99) < order.get("15", 99):
                argv.append("--skip-phase3")
        if entry and entry != "D1":
            argv += ["--entry-step", str(entry)]

        rc = subprocess.run(argv, capture_output=True, text=True).returncode
        got = bio.collect(fmt, pid, proj)
        waive = _rtl_gen_waive(proj)
        results.append({"id": pid, "nature": nature, "entry": entry,
                        "evidence": ev, "exit": exit_step, "rc": rc,
                        "ok": got.get("ok"), "staged": staged["prompt_chars"],
                        "awaiting_ai": bool(waive and not got.get("ok"))})
        state = ("rtl" if got.get("ok")
                 else ("WAIVE->AI" if waive else "no-rtl"))
        print(f"  {pid:44s} {nature:22s} entry={str(entry):3s} "
              f"exit={str(exit_step):4s} rc={rc} {state}")
        if got.get("ok"):
            (run_p / "responses" / f"{re.sub(r'[^-\w.]', '_', pid)}.json"
             ).write_text(json.dumps(got, indent=1))
        elif waive:
            backlog.append({
                "id": pid, "project": str(proj),
                "skill": waive.get("fallback_skill"),
                "write_rtl_to": str(proj / "phase2" / "stage1" / "rtl"),
                "read_docs_from": str(proj / "phase1" / "generated_docs"),
                "runner_said": waive.get("detail", "")[:600],
                "resume_with": (f"benchmark_dispatch.py {bench} --resume "
                                f"--dataset {ds} --run {run_p}"),
            })

    if backlog:
        # THE HAND-OFF. A program cannot call a language model, so the honest
        # shape is not "the solver silently did nothing" but a WORK-LIST plus a
        # resume command. The runner has already emitted L1-L27 for each of
        # these and named the skill it waived to; the AI authors into the
        # runner's OWN tree (phase2/stage1/rtl/) and `--resume` re-invokes the
        # runner so ITS gates fire on that RTL. That is the runner's designed
        # AI-backup, not a bypass of it: nothing here writes a scoring artefact.
        bl = run_p / "needs_ai_backup.jsonl"
        bl.write_text("\n".join(json.dumps(b) for b in backlog) + "\n")
        print(f"\n{len(backlog)} problem(s) WAIVED to an AI skill -> {bl}")
        print(f"  author RTL into each project's phase2/stage1/rtl/, then:")
        print(f"    python3 {Path(__file__).name} {bench} --resume "
              f"--dataset {ds} --run {run_p}")
    (run_p / "solve_report.json").write_text(json.dumps(
        {"bench": bench, "format": fmt, "dataset": str(ds),
         "solved": sum(1 for r in results if r["ok"]), "total": len(results),
         "results": results}, indent=2))
    ok = sum(1 for r in results if r["ok"])
    waiting = sum(1 for r in results if r.get("awaiting_ai"))
    print(f"\n{ok}/{len(results)} produced an artefact"
          + (f", {waiting} awaiting AI-backup" if waiting else "")
          + f" -> {run_p}/solve_report.json")
    if results and ok == len(results):
        return 0
    # 2 = handed off, not failed. A run that correctly reached the WAIVE and
    # emitted its work-list did its half; reporting that as a failure would
    # make the dual track look broken every time it works as designed.
    return 2 if waiting and waiting + ok == len(results) else 1


def cmd_resume(bench: str, dataset: str, run: str) -> int:
    """Re-invoke the runner on every project the AI has since authored into.

    The dual track is program-first THEN AI-backup THEN the runner's gates. A
    run that stopped after the AI wrote a file has completed two of those three:
    the RTL exists but nothing has linted it, elaborated it, or checked it
    against the spec. `--resume` is what makes the third happen, and a project
    whose rtl/ is still empty is reported as still-waiting rather than quietly
    skipped.
    """
    import subprocess                                    # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import benchmark_io_adapter as bio                    # noqa: PLC0415

    run_p = Path(run)
    bl = run_p / "needs_ai_backup.jsonl"
    if not bl.is_file():
        print(f"ERROR: no work-list at {bl} — run --solve first", file=sys.stderr)
        return 2
    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        print(f"ERROR: no IO adapter bound for {bench!r}", file=sys.stderr)
        return 2
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"

    done = still = 0
    for line in bl.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        proj = Path(item["project"])
        rtl_dir = proj / "phase2" / "stage1" / "rtl"
        authored = rtl_dir.is_dir() and (list(rtl_dir.glob("*.sv"))
                                         + list(rtl_dir.glob("*.v")))
        if not authored:
            still += 1
            print(f"  {item['id']:44s} still empty — the AI has not authored yet")
            continue
        rc = subprocess.run(
            [sys.executable, str(runner), str(proj), "--skip-analog",
             "--skip-hardware", "--skip-phase3"],
            capture_output=True, text=True).returncode
        got = bio.collect(fmt, item["id"], proj)
        if got.get("ok"):
            (run_p / "responses" / f"{re.sub(r'[^-\w.]', '_', str(item['id']))}.json"
             ).write_text(json.dumps(got, indent=1))
            done += 1
        print(f"  {item['id']:44s} re-gated rc={rc} "
              f"{'kept' if got.get('ok') else 'no rtl after gates'}")
    print(f"\n{done} re-gated, {still} still awaiting the AI")
    return 0 if still == 0 else 2


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bench", nargs="?", help="benchmark name (see --list)")
    ap.add_argument("--list", action="store_true", help="list known benchmarks")
    ap.add_argument("--show", action="store_true",
                    help="print the full registry entry for <bench> (#532)")
    ap.add_argument("--setup", action="store_true", help="create run dir scaffold")
    ap.add_argument("--score", action="store_true", help="invoke the scorer on an existing run dir")
    ap.add_argument("--reattempt-floor", action="store_true",
                    help="OPT-IN: print the prior FAILing-problem list to drive "
                         "a --floor-only run (not the default; default is "
                         "clean-room full re-run per § 4.1/§ 8.1, 2026-06-04)")
    ap.add_argument("--floor-only", action="store_true",
                    help="OPT-IN: scope --setup to the prior FAILing set only. "
                         "Still re-authors each selected problem BLIND into a "
                         "FRESH run dir (no inherited samples). Default is a "
                         "clean-room FULL re-run.")
    ap.add_argument("--solve", action="store_true",
                    help="SOLVE the benchmark through the general flow. This is "
                         "the verb that was missing: between --setup and --score "
                         "there was no program that solved, and that hole is "
                         "where an agent hand-rolls a benchmark-only harness — "
                         "the thing RULE 0 forbids. Each problem is staged by "
                         "the thin IO adapter, routed by task_nature_route to an "
                         "entry step and an evidence class, and run through "
                         "vibe_ic_one_shot_runner. No benchmark-specific solver "
                         "is involved.")
    ap.add_argument("--resume", action="store_true",
                    help="After the AI has authored RTL into the projects named "
                         "by needs_ai_backup.jsonl, RE-INVOKE the runner on each "
                         "so ITS gates fire on that RTL. This is the second half "
                         "of the dual track — RTL that never went back through "
                         "the runner has been authored, not gated.")
    ap.add_argument("--limit", type=int, default=0,
                    help="with --solve: stop after N problems (0 = all)")
    ap.add_argument("--dataset", help="dataset path on disk")
    ap.add_argument("--run", help="run dir")
    ap.add_argument("--allow-ungated", action="store_true",
                    help="OPT-IN: score even if some samples lack an emit-path attestation "
                         "(a disclosed exploratory direct-author run, NON-CANONICAL). Default "
                         "HARD-BLOCKs ungated samples so the published number reflects the runner.")
    ap.add_argument("--allow-direct-agent", action="store_true",
                    help="OPT-IN: score even if the run lacks Vibe-IC runner entry evidence "
                         "(NON-CANONICAL). Default HARD-BLOCKs direct-agent authoring/patching.")
    a = ap.parse_args()

    if a.list:
        cmd_list()
        return
    if not a.bench:
        ap.print_help()
        sys.exit(2)
    # A front door that answers "unknown benchmark: verilogeval-v1" to someone
    # who typed a name from our own README is a front door with a lock on it.
    _reg_keys = json.loads(REGISTRY.read_text())["benchmarks"]
    if a.bench and a.bench not in _reg_keys:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import benchmark_io_adapter as _bio          # noqa: PLC0415
            _resolved = _bio.resolve_name(a.bench)
        except ImportError:
            _resolved = None
        if _resolved and _resolved in _reg_keys:
            print(f"[name] {a.bench!r} -> {_resolved!r}")
            a.bench = _resolved

    if a.show:
        reg = json.loads(REGISTRY.read_text())["benchmarks"]
        if a.bench not in reg:
            raise SystemExit(f"unknown benchmark: {a.bench} (see --list)")
        print(json.dumps({a.bench: reg[a.bench]}, ensure_ascii=False,
                         indent=2))
        return
    if a.setup:
        if not (a.dataset and a.run):
            raise SystemExit("--setup requires --dataset and --run")
        cmd_setup(a.bench, a.dataset, a.run, floor_only=a.floor_only)
        return
    if a.score:
        if not a.run:
            raise SystemExit("--score requires --run")
        cmd_score(a.bench, a.run, a.dataset,
                  allow_ungated=a.allow_ungated,
                  allow_direct_agent=a.allow_direct_agent)
        return
    if a.resume:
        if not (a.dataset and a.run):
            raise SystemExit("--resume requires --dataset and --run")
        sys.exit(cmd_resume(a.bench, a.dataset, a.run))
    if a.solve:
        if not (a.dataset and a.run):
            raise SystemExit("--solve requires --dataset and --run")
        sys.exit(cmd_solve(a.bench, a.dataset, a.run, limit=a.limit))
    if a.reattempt_floor:
        sys.exit(cmd_reattempt_floor(a.bench))

    # default: show plan + env status
    env = _env_check()
    print(f"# Environment: iverilog={'OK' if env['iverilog'] else 'MISSING'}, "
          f"vibeic-eda container={'RUNNING' if env['iic_eda_running'] else 'NOT RUNNING'}")
    print()
    cmd_show(a.bench)


if __name__ == "__main__":
    main()
