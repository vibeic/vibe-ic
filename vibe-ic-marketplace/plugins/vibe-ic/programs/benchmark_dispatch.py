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
import argparse, hashlib, json, os, subprocess, sys
import re
from pathlib import Path

from _atomic_artefact import write_json as _atomic_write_json
from _atomic_artefact import write_text as _atomic_write_text

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


# THE HOST-REQUIREMENT MODEL LIVES IN ONE PLACE (`benchmark_setup`), AND THIS
# IS THE EDGE THAT REACHES IT. `_env_check` used to probe two tools of its own
# — iverilog and the container — while `benchmark_setup` already carried the
# seven-probe summary AND the per-SHAPE requirement table (`needs`), and
# nothing invoked it. Two answers to "is this host ready" is the drift shape
# this repo keeps removing: the weaker one is the one every caller saw, so a
# Shape-D run missing `docker`, or a Shape-A/B run missing `yosys`, printed a
# clean environment line and then failed inside the runner.
import benchmark_setup as _setup                       # noqa: E402


def _env_check():
    """The host probe, delegated to the module that owns it.

    Returns `benchmark_setup.env_summary()` — a SUPERSET of the two keys this
    function used to return (`iverilog`, `iic_eda_running` are both still
    present and mean the same thing), so every existing reader keeps working
    and the requirement table below can be asked about the other five.
    """
    return _setup.env_summary()


def _requirement_report(entry: dict, env: dict) -> tuple[list, list]:
    """`(needed, missing)` for one registry entry, per `benchmark_setup.needs`.

    The shape->requirement mapping is NOT restated here. `needs()` is the one
    table, and a shape added to it is answered by this dispatcher for free.
    """
    needed = sorted(_setup.needs(entry))
    return needed, [k for k in needed if not env.get(k)]


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
        print(f"  1. Clone dataset: git clone {e['dataset']['repo']} <DATASET>")
        print("  2. Solve through the general PROGRAM rail:")
        print(f"     python3 {Path(__file__).name} {bench} --solve "
              "--dataset <DATASET> --run <RUNDIR>")
        print(f"  3. Complete blind AI worklists per: {bi}")
        print("     needs_ai_backup.jsonl authors WAIVED candidates; "
              "needs_ai_review.jsonl independently reviews every candidate.")
        print(f"  4. Converge both rails: python3 {Path(__file__).name} {bench} "
              "--resume --dataset <DATASET> --run <RUNDIR>")
        print(f"  5. Score only after dual_track_acceptance.json is COMPLETE: "
              f"python3 {Path(__file__).name} {bench} --score "
              "--dataset <DATASET> --run <RUNDIR>")
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


# ── OUR OWN GOLDEN CORPUS, CAPTURED AT THE MOMENT THE HOST SAYS PASS ─────────
# `benchmark_golden_capture` records a HOST-VERIFIED, vibe-ic-AUTHORED solution
# tagged with the plugin version + AI model that produced it, in a corpus kept
# SEPARATE from the downloaded `reference_solution` (user directive
# 2026-06-22). The only place that verdict exists is the scorer's
# `pass_at_1.json`, and nothing read it back — so the corpus stayed empty and
# the "how do our solutions evolve across plugin versions / models" question it
# was built to answer had no data at all.
#
# WHY THE MODEL IS REQUIRED AND NOT DEFAULTED. Nothing on this host knows which
# model authored the samples; a default would stamp every row with a guess and
# the cross-version diff would compare two rows that are not comparable. The
# capture is therefore requested explicitly, and refuses without `--ai-model`
# rather than inventing one.
_GOLDEN_DEFAULT_DB = os.path.expanduser("~/vibe_golden/vibe_golden.sqlite")


def _sample_for(run_p: Path, shape: str, ident_value: str) -> Path | None:
    """The on-disk sample the scorer graded, by the harness's own naming.

    Shape B writes `<design>.v` (or `.sv`); Shape C writes `<Prob>_sample01.sv`.
    Returns None when nothing is there — a PASS with no readable sample is not
    capturable and is reported, never captured as an empty solution.
    """
    leaf = ident_value.split("/")[-1]
    cands = ([run_p / "samples" / f"{leaf}_sample01.sv"] if shape == "C"
             else [run_p / "samples" / f"{leaf}.v", run_p / "samples" / f"{leaf}.sv"])
    for c in cands:
        if c.is_file():
            return c
    return None


def capture_goldens(run_p: Path, bench: str, ai_model: str,
                    db: str | None = None, backup: str | None = None) -> dict:
    """Capture every HOST-VERIFIED PASS in `pass_at_1.json` as our own golden.

    Returns a report dict. Counts are stated with their denominator: "captured
    N of M PASSing problems" — a capture count alone would not say how many it
    could not reach.
    """
    import benchmark_golden_capture as _gold             # noqa: PLC0415
    from l_doc_generator_stamp import plugin_version     # noqa: PLC0415

    summary_p = run_p / "pass_at_1.json"
    if not summary_p.is_file():
        return {"captured": 0, "passing": 0,
                "why": f"no {summary_p} — the scorer wrote no verdict to capture"}
    doc = json.loads(summary_p.read_text())
    shape = doc.get("shape", "")
    results = doc.get("results") or []
    ident = "design" if shape == "B" else "problem"
    version = plugin_version() or "UNSTAMPED"
    scorer = doc.get("tool", "")
    db_path = db or _GOLDEN_DEFAULT_DB
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    passing = [r for r in results if r.get("verdict") == "PASS"]
    captured, unreachable = 0, []
    for r in passing:
        pid = str(r.get(ident, "")).split("/")[-1]
        sample = _sample_for(run_p, shape, str(r.get(ident, "")))
        if sample is None:
            unreachable.append(pid)
            continue
        _gold.capture(db_path, bench, pid, str(sample), None, version, ai_model,
                      host_verdict="PASS", scorer=scorer, run_id=str(run_p),
                      **({"backup": backup} if backup else {}))
        captured += 1
    return {"captured": captured, "passing": len(passing),
            "total_scored": len(results), "db": db_path,
            "plugin_version": version, "ai_model": ai_model,
            "sample_not_found": unreachable}


# A candidate is not accepted merely because the program emitted it. The
# program rail and a blind AI semantic-review rail must independently agree.
_REVIEW_TASK_SCHEMA = "vibeic.benchmark.ai_review_task.v1"
_AI_REVIEW_SCHEMA = "vibeic.benchmark.ai_review.v1"
_ACCEPTANCE_SCHEMA = "vibeic.benchmark.dual_track_acceptance.v1"
_REVIEW_WORKLIST = "needs_ai_review.jsonl"
_BACKUP_WORKLIST = "needs_ai_backup.jsonl"
_REPAIR_WORKLIST = "needs_ai_repair.jsonl"
_ENHANCEMENT_WORKLIST = "program_enhancement_candidates.jsonl"
_ACCEPTANCE_REPORT = "dual_track_acceptance.json"


def _safe_problem_id(problem_id: str) -> str:
    return re.sub(r"[^-\w.]", "_", str(problem_id))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _rtl_files(project: Path) -> list[Path]:
    rtl_dir = Path(project) / "phase2" / "stage1" / "rtl"
    return sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))


def _candidate_text(paths: list[Path]) -> str:
    return "\n".join(Path(p).read_text(errors="replace") for p in paths)


def _make_ai_review_task(problem_id: str, project: Path, got: dict,
                         routing: dict, runner_rc: int, run_p: Path,
                         candidate_origin: str) -> dict:
    """Build the hash-bound, oracle-free handoff for one AI review."""
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    prompt = project / "input" / "phase1_prompt.md"
    paths = _rtl_files(project)
    completion = str(got.get("completion") or "")
    if not prompt.is_file() or not paths or not got.get("ok") or not completion:
        raise ValueError("cannot request AI review without prompt + gated RTL")
    safe = _safe_problem_id(problem_id)
    return {
        "schema": _REVIEW_TASK_SCHEMA,
        "id": str(problem_id),
        "project": str(project),
        "candidate_origin": candidate_origin,
        "prompt_path": str(prompt),
        "rtl_paths": [str(p.resolve()) for p in paths],
        "prompt_sha256": _sha256_text(prompt.read_text(errors="replace")),
        "rtl_sha256": _sha256_text(completion),
        "program_routing": {
            "nature": routing.get("nature"),
            "route": routing.get("route"),
            "source": routing.get("source"),
            "needs_ai_parse": routing.get("needs_ai_parse"),
        },
        "program_verification": {
            "actor": "vibe_ic_one_shot_runner",
            "rtl_gen": got.get("rtl_gen"),
            "runner_rc": int(runner_rc),
        },
        "review_path": str((run_p / "ai_reviews" / f"{safe}.json").resolve()),
        "response_path": str((run_p / "responses" / f"{safe}.json").resolve()),
        "review_requirements": {
            "schema": _AI_REVIEW_SCHEMA,
            "blind_inputs_only": ["prompt_path", "rtl_paths"],
            "routing_verdicts": ["AGREE", "OVERRIDE_PROGRAM"],
            "override_rule": (
                "OVERRIDE_PROGRAM is allowed when the AI supplies prompt-bound "
                "evidence or a detailed interpretation and names the program "
                "limitation; AI semantic judgment is authoritative"),
            "semantic_verdicts": ["PASS", "FAIL"],
            "semantic_fail_action": (
                "author corrected RTL, return it through PROGRAM gates, then "
                "perform a fresh hash-bound AI review"),
            "reviewer_kind": "AI",
            "reviewer_model_required": True,
            "oracle_accessed": False,
        },
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not Path(path).is_file():
        return []
    rows = []
    for lineno, raw in enumerate(Path(path).read_text(errors="replace").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{lineno}: row is not an object")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                   for r in rows)
    _atomic_write_text(path, text)


def _current_task_material(task: dict) -> tuple[str | None, str | None,
                                                 list[str], list[str]]:
    """Current prompt/RTL hashes plus exact current/stated RTL path sets."""
    prompt = Path(str(task.get("prompt_path") or ""))
    project = Path(str(task.get("project") or ""))
    stated = sorted(str(Path(p).resolve()) for p in task.get("rtl_paths") or [])
    current_paths = [str(p.resolve()) for p in _rtl_files(project)]
    prompt_hash = (_sha256_text(prompt.read_text(errors="replace"))
                   if prompt.is_file() else None)
    try:
        rtl_hash = _sha256_text(_candidate_text([Path(p) for p in current_paths])) \
            if current_paths else None
    except OSError:
        rtl_hash = None
    return prompt_hash, rtl_hash, stated, current_paths


def _validate_ai_review(task: dict) -> dict:
    """Validate a hash-bound review, including evidence-backed AI override.

    AI is the semantic authority, but authority is not an unexplained token.
    It may override the program route when it cites prompt text or provides a
    detailed interpretation and identifies the deterministic limitation.  A
    valid semantic FAIL is a real ``REPAIR_REQUIRED`` decision, not a malformed
    review and not a permanent convergence failure.
    """
    review_path = Path(str(task.get("review_path") or ""))
    if not review_path.is_file():
        return {"status": "PENDING", "review_path": str(review_path),
                "reasons": ["AI review file is absent"]}
    try:
        review = json.loads(review_path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "REJECTED", "review_path": str(review_path),
                "reasons": [f"AI review is unreadable: {type(exc).__name__}: {exc}"]}
    reasons: list[str] = []
    if not isinstance(review, dict):
        reasons.append("AI review is not a JSON object")
        review = {}
    if review.get("schema") != _AI_REVIEW_SCHEMA:
        reasons.append(f"schema must be {_AI_REVIEW_SCHEMA!r}")
    if str(review.get("id")) != str(task.get("id")):
        reasons.append("review id does not match the task")

    prompt_hash, rtl_hash, stated, current = _current_task_material(task)
    if stated != current:
        reasons.append("current RTL file set differs from the reviewed task")
    if prompt_hash != task.get("prompt_sha256"):
        reasons.append("prompt changed after the review task was issued")
    if rtl_hash != task.get("rtl_sha256"):
        reasons.append("RTL changed after the review task was issued")
    if review.get("prompt_sha256") != task.get("prompt_sha256"):
        reasons.append("review prompt_sha256 is stale or wrong")
    if review.get("rtl_sha256") != task.get("rtl_sha256"):
        reasons.append("review rtl_sha256 is stale or wrong")

    reviewer = review.get("reviewer") or {}
    if reviewer.get("kind") != "AI":
        reasons.append("reviewer.kind must be AI")
    model = str(reviewer.get("model") or "").strip()
    if not model or model.lower() in {"unknown", "unspecified", "n/a"}:
        reasons.append("reviewer.model must name the AI model")

    blind = review.get("blind") or {}
    if blind.get("oracle_accessed") is not False:
        reasons.append("blind.oracle_accessed must be false")

    prompt_path = Path(str(task.get("prompt_path") or ""))
    prompt_text = (prompt_path.read_text(errors="replace")
                   if prompt_path.is_file() else "")
    normalized_prompt = re.sub(r"\s+", " ", prompt_text).strip()

    def _verified_prompt_evidence(items) -> list[dict]:
        verified = []
        if not isinstance(items, list):
            return verified
        for item in items:
            if not isinstance(item, dict):
                continue
            excerpt = re.sub(
                r"\s+", " ", str(item.get("excerpt") or "")).strip()
            supports = str(item.get("supports") or "").strip()
            if (len(excerpt) >= 8 and excerpt in normalized_prompt
                    and len(supports) >= 12):
                verified.append({"excerpt": excerpt, "supports": supports})
        return verified

    routing = review.get("routing") or {}
    expected_nature = (task.get("program_routing") or {}).get("nature")
    routing_verdict = routing.get("verdict")
    override = review.get("override") or {}
    evidence = override.get("prompt_evidence") or []
    verified_evidence = []
    if routing_verdict == "AGREE":
        if routing.get("ai_nature") != expected_nature:
            reasons.append("AI route marked AGREE but does not match program route")
    elif routing_verdict == "OVERRIDE_PROGRAM":
        if not isinstance(evidence, list):
            reasons.append("override.prompt_evidence must be a list")
            evidence = []
        verified_evidence = _verified_prompt_evidence(evidence)
        explanation = str(override.get("explanation") or "").strip()
        if not verified_evidence and len(explanation) < 160:
            reasons.append("OVERRIDE_PROGRAM needs prompt-bound evidence or a "
                           "detailed explanation of at least 160 characters")
        if len(str(override.get("program_limitation") or "").strip()) < 16:
            reasons.append("OVERRIDE_PROGRAM must identify the program limitation")
        proposed = override.get("proposed_program_enhancement")
        if proposed is not None:
            if not isinstance(proposed, dict):
                reasons.append("proposed_program_enhancement must be an object")
            elif (len(str(proposed.get("component") or "").strip()) < 3
                  or len(str(proposed.get("proposal") or "").strip()) < 16
                  or len(str(proposed.get("regression_fixture") or "").strip()) < 8):
                reasons.append("proposed_program_enhancement must name a component, "
                               "concrete proposal, and regression fixture")
    else:
        reasons.append("AI routing verdict must be AGREE or OVERRIDE_PROGRAM")

    semantic = review.get("semantic_review") or {}
    semantic_verdict = semantic.get("verdict")
    findings = semantic.get("findings")
    semantic_evidence = semantic.get("prompt_evidence") or []
    verified_semantic_evidence = _verified_prompt_evidence(semantic_evidence)
    if semantic_verdict not in {"PASS", "FAIL"}:
        reasons.append("AI semantic_review verdict must be PASS or FAIL")
    if not isinstance(findings, list):
        reasons.append("semantic_review.findings must be a list")
        findings = []
    if semantic_verdict == "FAIL" and not findings:
        reasons.append("semantic FAIL must name at least one actionable finding")
    rationale = str(semantic.get("rationale") or "").strip()
    if len(rationale) < 16:
        reasons.append("semantic_review.rationale must state the review basis")
    if (semantic_verdict == "FAIL" and not verified_semantic_evidence
            and not verified_evidence and len(rationale) < 160):
        reasons.append("semantic FAIL needs prompt-bound evidence or a detailed "
                       "rationale of at least 160 characters")
    if reasons:
        status = "REJECTED"
        decision_reasons = reasons
    elif semantic_verdict == "FAIL":
        status = "REPAIR_REQUIRED"
        decision_reasons = ["AI semantic authority rejected the current RTL; "
                            "repair, re-run PROGRAM gates, and review the new hash"]
    else:
        status = "ACCEPTED"
        decision_reasons = []
    return {"status": status,
            "review_path": str(review_path), "reasons": reasons,
            "decision_reasons": decision_reasons,
            "reviewer_model": model or None,
            "routing_verdict": routing_verdict,
            "ai_nature": routing.get("ai_nature"),
            "semantic_verdict": semantic_verdict,
            "semantic_findings": len(findings),
            "semantic_findings_detail": findings,
            "semantic_rationale": rationale,
            "verified_semantic_prompt_evidence": verified_semantic_evidence,
            "override": ({**override, "verified_prompt_evidence": verified_evidence}
                         if routing_verdict == "OVERRIDE_PROGRAM" else None)}


def _attach_ai_review_attribution(result: dict, verdict: dict) -> None:
    """Put the second rail's WHO/HOW into this problem's four-phase record."""
    phases = result.get("phases") or {}
    result["phases"] = phases
    status = verdict.get("status")
    model = verdict.get("reviewer_model")
    phases.setdefault("phase1_routing", {}).update({
        "ai_decided_routing_review": {
            "actor": model or "AI_PENDING",
            "mechanism": "AI",
            "authority": "FINAL_SEMANTIC_AUTHORITY",
            "status": status,
            "verdict": verdict.get("routing_verdict"),
            "nature": verdict.get("ai_nature"),
            "how": "blind prompt parse, hash-bound to prompt_sha256",
            "override_basis": verdict.get("override"),
        },
    })
    phases.setdefault("phase3_verifying", {}).update({
        "ai_semantic_review": {
            "actor": model or "AI_PENDING",
            "mechanism": "AI",
            "status": status,
            "verdict": verdict.get("semantic_verdict"),
            "findings": verdict.get("semantic_findings"),
            "how": "blind prompt-versus-RTL review, hash-bound to rtl_sha256",
        },
    })
    if status == "REPAIR_REQUIRED":
        phases.setdefault("phase4_debugging", {})[
            "ai_semantic_repair_handoff"] = {
                "actor": model, "mechanism": "AI",
                "status": status,
                "findings": verdict.get("semantic_findings_detail"),
                "how": ("AI explains the spec mismatch; corrected RTL must "
                        "return through PROGRAM gates and a fresh AI review"),
                "physical_eco": False,
            }
    result["dual_track_review"] = {
        k: verdict.get(k) for k in (
            "status", "reviewer_model", "routing_verdict", "ai_nature",
            "semantic_verdict", "semantic_findings", "override")
    }


def _program_enhancement_candidate(task: dict, result: dict,
                                   verdict: dict) -> dict:
    """A durable, non-blocking follow-up when AI exposes program rigidity."""
    override = verdict.get("override") or {}
    return {
        "schema": "vibeic.benchmark.program_enhancement_candidate.v1",
        "id": str(task.get("id")),
        "project": task.get("project"),
        "prompt_sha256": task.get("prompt_sha256"),
        "rtl_sha256": task.get("rtl_sha256"),
        "review_path": task.get("review_path"),
        "program_routing": task.get("program_routing"),
        "ai_routing": {
            "verdict": verdict.get("routing_verdict"),
            "nature": verdict.get("ai_nature"),
        },
        "semantic_verdict": verdict.get("semantic_verdict"),
        "semantic_findings": verdict.get("semantic_findings_detail"),
        "semantic_rationale": verdict.get("semantic_rationale"),
        "verified_semantic_prompt_evidence":
            verdict.get("verified_semantic_prompt_evidence") or [],
        "verified_prompt_evidence": override.get("verified_prompt_evidence") or [],
        "ai_explanation": override.get("explanation"),
        "program_limitation": override.get("program_limitation"),
        "proposed_program_enhancement":
            override.get("proposed_program_enhancement"),
        "candidate_origin": result.get("candidate_origin"),
        "status": "OPEN_PROGRAM_ENHANCEMENT",
        "blocking_acceptance": False,
        "why_non_blocking": (
            "AI supplied an auditable semantic decision; improve the reusable "
            "program without trapping this benchmark item in permanent disagreement"),
    }


def _four_phase_rollup(fpa, results: list[dict]) -> dict:
    """General attribution plus benchmark dual-track counts and actors."""
    out = fpa.summarize(results)

    def counts(values) -> dict:
        result: dict[str, int] = {}
        for value in values:
            key = str(value)
            result[key] = result.get(key, 0) + 1
        return result

    reviews = [r.get("dual_track_review") or {} for r in results]
    out["phase1_ai_review_status"] = counts(
        v.get("status") or "PENDING" for v in reviews)
    out["phase1_ai_review_models"] = counts(
        v.get("reviewer_model") or "PENDING" for v in reviews)
    out["phase2_candidate_origin"] = counts(
        r.get("candidate_origin", "NONE") for r in results)
    out["phase3_ai_semantic_verdict"] = counts(
        v.get("semantic_verdict") or "PENDING" for v in reviews)
    out["phase4_ai_repair_required"] = counts(
        bool(r.get("ai_repair_required")) for r in results)
    return out


def _require_dual_track_acceptance(run_p: Path) -> None:
    """Hard-block scoring of a solve-run until both rails accepted every id."""
    run_p = Path(run_p).resolve()
    solve_p = run_p / "solve_report.json"
    if not solve_p.is_file():
        return                         # historical/manual runs keep old policy
    try:
        solve = json.loads(solve_p.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return                         # the clean-room gate reports this later
    policy = solve.get("acceptance_policy") or {}
    if policy.get("required") is not True:
        return
    acc_p = run_p / _ACCEPTANCE_REPORT
    if not acc_p.is_file():
        raise SystemExit("dual-track acceptance BLOCKED: no acceptance report; "
                         "run --resume after completing needs_ai_review.jsonl")
    try:
        acceptance = json.loads(acc_p.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"dual-track acceptance BLOCKED: unreadable {acc_p}: {exc}")
    if (acceptance.get("schema") != _ACCEPTANCE_SCHEMA
            or acceptance.get("status") != "COMPLETE"):
        raise SystemExit("dual-track acceptance BLOCKED: acceptance status is "
                         f"{acceptance.get('status', 'INVALID')}, not COMPLETE")

    tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
    expected = [str(r.get("id")) for r in solve.get("results") or []]
    by_id = {str(t.get("id")): t for t in tasks}
    if len(by_id) != len(tasks) or sorted(by_id) != sorted(expected):
        raise SystemExit("dual-track acceptance BLOCKED: review worklist ids do "
                         "not exactly match solve_report results")
    accepted_ids = [str(pid) for pid in acceptance.get("accepted_ids") or []]
    if (sorted(accepted_ids) != sorted(expected)
            or acceptance.get("accepted") != len(expected)
            or acceptance.get("total") != len(expected)):
        raise SystemExit("dual-track acceptance BLOCKED: COMPLETE report does "
                         "not account for every solve_report result")
    failures = []
    for pid in expected:
        task = by_id[pid]
        verdict = _validate_ai_review(task)
        if verdict["status"] != "ACCEPTED":
            failures.append(f"{pid}: " + "; ".join(verdict["reasons"]))
            continue
        response = Path(str(task.get("response_path") or ""))
        try:
            payload = json.loads(response.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{pid}: accepted response unreadable: {exc}")
            continue
        if _sha256_text(str(payload.get("completion") or "")) != task.get("rtl_sha256"):
            failures.append(f"{pid}: response bytes do not match reviewed RTL")
    if failures:
        raise SystemExit("dual-track acceptance BLOCKED:\n  "
                         + "\n  ".join(failures))


def cmd_score(bench: str, run: str, dataset: str | None,
              allow_ungated: bool = False, allow_direct_agent: bool = False,
              capture_golden: bool = False, ai_model: str | None = None,
              golden_db: str | None = None):
    e = _entry(bench)
    if e["shape"] not in ("B", "C"):
        raise SystemExit(f"--score only handles Shape B + C here. Shape {e['shape']} → use score_cocotb_mcp.py / benchmark-verify skill.")
    run_p = Path(run).resolve()
    _require_dual_track_acceptance(run_p)
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
    rc = subprocess.call(cmd)
    if capture_golden:
        if not ai_model:
            raise SystemExit(
                "--capture-golden needs --ai-model: nothing on this host knows "
                "which model authored the samples, and a defaulted tag would "
                "make two incomparable rows look comparable.")
        rep = capture_goldens(run_p, bench, ai_model, db=golden_db)
        if rep.get("why"):
            print(f"golden capture: NOT DONE — {rep['why']}")
        else:
            print(f"golden capture: {rep['captured']} of {rep['passing']} "
                  f"PASSing problem(s) recorded (of {rep['total_scored']} scored) "
                  f"as plugin v{rep['plugin_version']} / {rep['ai_model']} -> "
                  f"{rep['db']}")
            if rep["sample_not_found"]:
                print(f"  NOT captured (no sample on disk): {rep['sample_not_found']}")
    sys.exit(rc)


# ── FORMAT BINDING ───────────────────────────────────────────────────────────
# Which IO adapter reads which benchmark's files. This is the ONLY benchmark
# knowledge the dispatcher holds, and it is a mapping, not a code path.
_BENCH_FORMAT = {
    "verilogeval-v2": "verilogeval",
    "verilogeval-human": "verilogeval",
    "rtllm": "rtllm",
    "cvdp-open": "cvdp",
}

# ── THE SAME COMPLETENESS ENGINE, PER FORMAT ─────────────────────────────────
# `benchmark_completeness` is the THIN-ADAPTER layer over the ONE general
# engine (`spec_complete_extract.assess_spec`): each benchmark differs only in
# how it states its interface, and the COMPLETE / EXTRACTION_GAP / SPEC_ABSENT
# verdict comes from the same place for all of them and for a plain Phase-1
# doc. It had no caller, so `--solve` recorded rc/ok per problem and NOTHING
# about whether the prompt it was handed could be solved at all — which is the
# FLOOR half of the triage rubric (benchmark-defect / under-spec) that
# open-benchmark-methodology § 4 requires a run to separate out.
#
# A MAPPING, not a code path: a format added to `_BENCH_FORMAT` above and to
# this table is assessed with no further change here. `cvdp` is deliberately
# absent — its interface arrives as a cocotb harness + `.env` TOPLEVEL, which
# `cvdp_complete_extract.extract(record)` reads from the RECORD, not from the
# staged prompt text this loop has in hand.
def _completeness_adapters() -> dict:
    """`{format: assess(prompt) -> spec}`. Imported lazily and never fatally.

    A completeness verdict is DISCLOSURE on the solve report; an import error
    here must not stop a run from solving. It is recorded by name instead of
    swallowed, so `completeness: "UNAVAILABLE: ..."` is distinguishable from a
    real SPEC_ABSENT.
    """
    import benchmark_completeness as _bc                # noqa: PLC0415
    return {"rtllm": _bc.assess_rtllm,
            "verilogeval": _bc.assess_verilogeval}


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
    import flow_phase_attribution as fpa                  # noqa: PLC0415
    import task_nature_route as tnr                       # noqa: PLC0415

    try:
        _assessors = _completeness_adapters()
        _assess_why = ""
    except Exception as exc:                              # noqa: BLE001
        _assessors, _assess_why = {}, f"UNAVAILABLE: {type(exc).__name__}: {exc}"

    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        print(f"ERROR: no IO adapter bound for {bench!r}. Known: "
              f"{sorted(_BENCH_FORMAT)}", file=sys.stderr)
        return 2

    ds, run_p = Path(dataset), Path(run)
    (run_p / "projects").mkdir(parents=True, exist_ok=True)
    (run_p / "responses").mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"

    results, backlog, review_tasks, n = [], [], [], 0
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
        prompt_text = (proj / "input" / "phase1_prompt.md").read_text(errors="replace")

        # SPEC COMPLETENESS, from the one general engine via this format's thin
        # adapter. Recorded, never acted on: a prompt the engine calls
        # INCOMPLETE_SPEC_ABSENT is still solved and still scored — the verdict
        # is what lets a FAIL be triaged as FLOOR rather than as an agent miss.
        completeness = _assess_why or "NOT_ADAPTED"
        assess = _assessors.get(fmt)
        if assess is not None:
            try:
                completeness = assess(prompt_text).get("completeness", "?")
            except Exception as exc:                      # noqa: BLE001
                completeness = f"UNAVAILABLE: {type(exc).__name__}: {exc}"

        verdict = tnr.classify_task_nature(
            prompt_text, rtl_present, None)
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
        phases = fpa.attribute(
            proj, routing=verdict, entry=entry, evidence=ev,
            exit_step=exit_step, rtl_present=rtl_present,
            artefact_collected=bool(got.get("ok")))
        result = {"id": pid, "nature": nature, "entry": entry,
                  "evidence": ev, "exit": exit_step, "rc": rc,
                  "ok": bool(got.get("ok")),
                  "candidate_ready": bool(got.get("ok")),
                  "accepted": False,
                  "staged": staged["prompt_chars"],
                  "completeness": completeness,
                  "routing_verdict": verdict,
                  "phases": phases,
                  "candidate_origin": ("PROGRAM" if got.get("ok") else
                                       ("AI_BACKUP_PENDING" if waive else
                                        "NONE")),
                  "dual_track_review": {"status": "PENDING"},
                  "ai_repair_required": False,
                  "awaiting_ai_review": bool(got.get("ok")),
                  "awaiting_ai_backup": bool(waive and not got.get("ok")),
                  "awaiting_ai": bool(got.get("ok")
                                      or (waive and not got.get("ok")))}
        state = ("candidate->AI-review" if got.get("ok")
                 else ("WAIVE->AI" if waive else "no-rtl"))
        print(f"  {pid:44s} {nature:22s} entry={str(entry):3s} "
              f"exit={str(exit_step):4s} rc={rc} {state}")
        if got.get("ok"):
            task = _make_ai_review_task(
                pid, proj, got, verdict, rc, run_p, "PROGRAM")
            review_tasks.append(task)
            result["review_task"] = task["review_path"]
            # This is the consumer the route attribution previously said did
            # not exist. The review must independently classify the same prompt.
            p1 = (phases.get("phase1_routing") or {})
            p1["needs_ai_parse_consumed_by"] = (
                f"blind AI dual-track review at {task['review_path']}")
        elif waive:
            backlog.append({
                "schema": "vibeic.benchmark.ai_backup_task.v1",
                "id": pid, "project": str(proj),
                "skill": waive.get("fallback_skill"),
                "write_rtl_to": str(proj / "phase2" / "stage1" / "rtl"),
                "read_docs_from": str(proj / "phase1" / "generated_docs"),
                "read_prompt_from": str(proj / "input" / "phase1_prompt.md"),
                "runner_said": waive.get("detail", "")[:600],
                "review_required_after_regating": True,
                "resume_with": (f"benchmark_dispatch.py {bench} --resume "
                                f"--dataset {ds} --run {run_p}"),
            })
        results.append(result)

    if backlog:
        # THE HAND-OFF. A program cannot call a language model, so the honest
        # shape is not "the solver silently did nothing" but a WORK-LIST plus a
        # resume command. The runner has already emitted L1-L27 for each of
        # these and named the skill it waived to; the AI authors into the
        # runner's OWN tree (phase2/stage1/rtl/) and `--resume` re-invokes the
        # runner so ITS gates fire on that RTL. That is the runner's designed
        # AI-backup, not a bypass of it: nothing here writes a scoring artefact.
        bl = run_p / _BACKUP_WORKLIST
        _write_jsonl(bl, backlog)
        print(f"\n{len(backlog)} problem(s) WAIVED to an AI skill -> {bl}")
        print(f"  author RTL into each project's phase2/stage1/rtl/, then:")
        print(f"    python3 {Path(__file__).name} {bench} --resume "
              f"--dataset {ds} --run {run_p}")
    else:
        _write_jsonl(run_p / _BACKUP_WORKLIST, [])

    _write_jsonl(run_p / _REVIEW_WORKLIST, review_tasks)
    if review_tasks:
        print(f"\n{len(review_tasks)} program candidate(s) require blind AI "
              f"semantic review -> {run_p / _REVIEW_WORKLIST}")
        print("  write each schema-bound review to its review_path, then run --resume")
    # The completeness roll-up carries its own denominator: "3 SPEC_ABSENT" out
    # of an unstated population is the shape this repo refuses everywhere else.
    comp_counts: dict = {}
    for r in results:
        comp_counts[r.get("completeness", "?")] = comp_counts.get(r.get("completeness", "?"), 0) + 1
    solve_report = {
        "bench": bench, "format": fmt, "dataset": str(ds),
        "solved": sum(1 for r in results if r["ok"]),
        "accepted": 0, "total": len(results),
        "acceptance_policy": {
            "required": True,
            "rule": ("PROGRAM gates PASS AND blind AI semantic PASS; AI route "
                     "may AGREE or evidence-backed OVERRIDE_PROGRAM"),
            "semantic_authority": "AI",
            "program_disagreement": (
                "repair and re-gate candidate; preserve a non-blocking reusable "
                "program-enhancement candidate rather than deadlock"),
            "review_task_schema": _REVIEW_TASK_SCHEMA,
            "review_schema": _AI_REVIEW_SCHEMA,
            "score_gate": _ACCEPTANCE_REPORT,
        },
        "completeness_counts": comp_counts,
        "completeness_assessed_of":
            f"{sum(comp_counts.get(k, 0) for k in comp_counts if not k.startswith(('UNAVAILABLE', 'NOT_ADAPTED')))} of {len(results)}",
        "four_phase_summary": _four_phase_rollup(fpa, results),
        "results": results,
    }
    _atomic_write_json(run_p / "solve_report.json", solve_report)
    _atomic_write_json(run_p / _ACCEPTANCE_REPORT, {
        "schema": _ACCEPTANCE_SCHEMA, "status": "PENDING",
        "accepted": 0, "total": len(results), "accepted_ids": [],
    })
    ok = sum(1 for r in results if r["ok"])
    waiting = sum(1 for r in results if r.get("awaiting_ai"))
    print(f"\n{ok}/{len(results)} produced a gated candidate; 0 accepted"
          + (f", {waiting} awaiting an AI rail" if waiting else "")
          + f" -> {run_p}/solve_report.json")
    # 2 = handed off, not failed. Even when every PROGRAM candidate exists, no
    # response is accepted until the independent AI rail agrees.
    return 2 if results and waiting == len(results) else 1


def cmd_resume(bench: str, dataset: str, run: str) -> int:
    """Advance AI backup/review work and publish only dual-track acceptances.

    There are two distinct AI jobs.  A runner WAIVE asks AI backup to author a
    candidate, which is then returned through the PROGRAM gates.  Every gated
    candidate, including a program-authored one, separately requires a blind
    AI route + semantic review.  Only a hash-bound PASS on both rails writes a
    scorer response.  A changed candidate is re-gated and receives a fresh
    review task; a changed prompt is never legitimised by refresh.
    """
    import subprocess                                    # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import flow_phase_attribution as fpa                  # noqa: PLC0415

    run_p = Path(run).resolve()
    solve_p = run_p / "solve_report.json"
    if not solve_p.is_file():
        print(f"ERROR: no solve report at {solve_p} — run --solve first",
              file=sys.stderr)
        return 2
    try:
        solve = json.loads(solve_p.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: unreadable solve report {solve_p}: {exc}",
              file=sys.stderr)
        return 2
    if (solve.get("acceptance_policy") or {}).get("required") is not True:
        print("ERROR: this solve predates the dual-track acceptance policy; "
              "start a fresh --solve run", file=sys.stderr)
        return 2
    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        print(f"ERROR: no IO adapter bound for {bench!r}", file=sys.stderr)
        return 2
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"

    try:
        backup = _read_jsonl(run_p / _BACKUP_WORKLIST)
        review_tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
        prior_enhancements = _read_jsonl(run_p / _ENHANCEMENT_WORKLIST)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    results = solve.get("results") or []
    result_by_id = {str(r.get("id")): r for r in results}
    task_by_id = {str(t.get("id")): t for t in review_tasks}
    if len(result_by_id) != len(results) or len(task_by_id) != len(review_tasks):
        print("ERROR: duplicate problem id in solve report or review worklist",
              file=sys.stderr)
        return 2

    def _run_and_collect(pid: str, proj: Path) -> tuple[int, dict]:
        rc = subprocess.run(
            [sys.executable, str(runner), str(proj), "--skip-analog",
             "--skip-hardware", "--skip-phase3"],
            capture_output=True, text=True).returncode
        return rc, bio.collect(fmt, pid, proj)

    def _refresh_result(result: dict, proj: Path, rc: int, got: dict) -> None:
        routing = result.get("routing_verdict") or {}
        rtl_input = proj / "input" / "rtl"
        phases = fpa.attribute(
            proj, routing=routing, entry=result.get("entry"),
            evidence=result.get("evidence"), exit_step=result.get("exit"),
            rtl_present=rtl_input.is_dir() and any(rtl_input.glob("*")),
            artefact_collected=bool(got.get("ok")))
        result.update({
            "rc": rc,
            "ok": bool(got.get("ok")),
            "candidate_ready": bool(got.get("ok")),
            "accepted": False,
            "phases": phases,
            "awaiting_ai_backup": False,
            "awaiting_ai_review": bool(got.get("ok")),
            "awaiting_ai": bool(got.get("ok")),
        })

    repairs: list[dict] = []
    remaining_backup: list[dict] = []
    refreshed: set[str] = set()
    enhancement_by_key = {
        (str(row.get("id")), str(row.get("prompt_sha256")),
         str(row.get("rtl_sha256")), str(row.get("semantic_verdict"))): row
        for row in prior_enhancements
    }

    # Rail 2a: AI authored after a deterministic WAIVE.  It still has to pass
    # the exact same runner and then enters the independent review rail.
    for item in backup:
        pid = str(item.get("id"))
        result = result_by_id.get(pid)
        proj = Path(str(item.get("project") or ""))
        if result is None:
            repairs.append({"id": pid, "status": "INVALID_HANDOFF",
                            "reasons": ["backup id is absent from solve_report"]})
            continue
        rtl_dir = proj / "phase2" / "stage1" / "rtl"
        authored = rtl_dir.is_dir() and (list(rtl_dir.glob("*.sv"))
                                         + list(rtl_dir.glob("*.v")))
        if not authored:
            remaining_backup.append(item)
            result.update({"accepted": False, "awaiting_ai_backup": True,
                           "awaiting_ai_review": False, "awaiting_ai": True})
            print(f"  {pid:44s} AI backup still has no authored RTL")
            continue
        rc, got = _run_and_collect(pid, proj)
        _refresh_result(result, proj, rc, got)
        if got.get("ok"):
            task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, "AI_BACKUP")
            task_by_id[pid] = task
            result["review_task"] = task["review_path"]
            result["candidate_origin"] = "AI_BACKUP"
            result["ai_repair_required"] = False
            refreshed.add(pid)
            print(f"  {pid:44s} AI backup re-gated; fresh AI review required")
        else:
            # Keep the original backup handoff live: after the AI repairs the
            # rejected files, the next --resume must know to re-run the gates.
            remaining_backup.append(item)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v1",
                "id": pid, "project": str(proj),
                "status": "PROGRAM_GATES_REJECTED_AI_BACKUP",
                "reasons": [str(got.get("reason") or "runner rejected RTL")],
                "write_rtl_to": str(rtl_dir),
                "resume_with": (f"benchmark_dispatch.py {bench} --resume "
                                f"--dataset {dataset} --run {run_p}"),
            })
            result.update({"awaiting_ai_backup": True,
                           "awaiting_ai_review": False,
                           "awaiting_ai": True,
                           "ai_repair_required": True})
            print(f"  {pid:44s} AI backup rejected by PROGRAM gates (rc={rc})")

    # Rail 2b: an AI repair changes candidate bytes.  Re-run program gates and
    # replace the old hash-bound task.  The prompt itself is immutable input;
    # refreshing its hash would turn prompt tampering into accepted evidence.
    for pid, task in list(task_by_id.items()):
        if pid in refreshed:
            continue
        result = result_by_id.get(pid)
        if result is None:
            repairs.append({"id": pid, "status": "INVALID_REVIEW_TASK",
                            "reasons": ["review id is absent from solve_report"]})
            continue
        prompt_hash, rtl_hash, stated, current = _current_task_material(task)
        if prompt_hash != task.get("prompt_sha256"):
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v1",
                "id": pid, "project": task.get("project"),
                "status": "PROMPT_CHANGED",
                "reasons": ["restore the original prompt; it cannot be refreshed"],
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False})
            continue
        if stated == current and rtl_hash == task.get("rtl_sha256"):
            continue
        proj = Path(str(task.get("project") or ""))
        rc, got = _run_and_collect(pid, proj)
        _refresh_result(result, proj, rc, got)
        if got.get("ok"):
            new_task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, "AI_REPAIR")
            task_by_id[pid] = new_task
            result["review_task"] = new_task["review_path"]
            result["candidate_origin"] = "AI_REPAIR"
            result["ai_repair_required"] = False
            print(f"  {pid:44s} changed RTL re-gated; fresh AI review required")
        else:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v1",
                "id": pid, "project": str(proj),
                "status": "PROGRAM_GATES_REJECTED_AI_REPAIR",
                "reasons": [str(got.get("reason") or "runner rejected RTL")],
                "write_rtl_to": str(proj / "phase2" / "stage1" / "rtl"),
            })
            result["ai_repair_required"] = True
            print(f"  {pid:44s} changed RTL rejected by PROGRAM gates (rc={rc})")

    accepted_ids: list[str] = []
    review_outcomes: list[dict] = []
    for pid, result in result_by_id.items():
        task = task_by_id.get(pid)
        if task is None:
            result["accepted"] = False
            continue
        verdict = _validate_ai_review(task)
        _attach_ai_review_attribution(result, verdict)
        review_outcomes.append({"id": pid, **verdict})
        if (verdict["status"] == "REPAIR_REQUIRED"
                or (verdict["status"] == "ACCEPTED"
                    and verdict.get("routing_verdict") == "OVERRIDE_PROGRAM")):
            enhancement = _program_enhancement_candidate(task, result, verdict)
            enhancement_by_key[(
                pid, str(task.get("prompt_sha256")),
                str(task.get("rtl_sha256")),
                str(verdict.get("semantic_verdict")),
            )] = enhancement
        if verdict["status"] != "ACCEPTED":
            needs_repair = verdict["status"] == "REPAIR_REQUIRED"
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": not needs_repair,
                           "ai_repair_required": needs_repair})
            if needs_repair:
                result["ai_repair_required"] = True
                repairs.append({
                    "schema": "vibeic.benchmark.ai_repair_task.v1",
                    "id": pid, "project": task.get("project"),
                    "status": "AI_SEMANTIC_REPAIR_REQUIRED",
                    "reasons": (verdict.get("decision_reasons") or [])
                               + [str(v) for v in
                                  verdict.get("semantic_findings_detail") or []],
                    "review_path": task.get("review_path"),
                    "reviewed_rtl_sha256": task.get("rtl_sha256"),
                    "verified_prompt_evidence":
                        (verdict.get("override") or {}).get(
                            "verified_prompt_evidence") or [],
                    "verified_semantic_prompt_evidence":
                        verdict.get("verified_semantic_prompt_evidence") or [],
                    "write_rtl_to": str(
                        Path(str(task.get("project"))) /
                        "phase2" / "stage1" / "rtl"),
                    "required_next": (
                        "author corrected RTL, run --resume for PROGRAM gates, "
                        "then submit a fresh AI review for the new hash"),
                })
            continue
        got = bio.collect(fmt, pid, Path(str(task.get("project") or "")))
        if (not got.get("ok")
                or _sha256_text(str(got.get("completion") or ""))
                != task.get("rtl_sha256")):
            reasons = ["current PROGRAM-gated completion does not match the "
                       "AI-reviewed RTL hash"]
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v1",
                "id": pid, "project": task.get("project"),
                "status": "ACCEPTED_REVIEW_MATERIAL_MISMATCH",
                "reasons": reasons,
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": True})
            continue
        _atomic_write_json(Path(task["response_path"]), got)
        accepted_ids.append(pid)
        result.update({"accepted": True, "awaiting_ai": False,
                       "awaiting_ai_backup": False,
                       "awaiting_ai_review": False,
                       "ai_repair_required": False,
                       "reviewer_model": verdict.get("reviewer_model")})
        route_note = ("AI OVERRIDE_PROGRAM" if
                      verdict.get("routing_verdict") == "OVERRIDE_PROGRAM"
                      else "AI AGREE")
        print(f"  {pid:44s} ACCEPTED by PROGRAM gates + {route_note}")

    ordered_tasks = [task_by_id[pid] for pid in result_by_id
                     if pid in task_by_id]
    _write_jsonl(run_p / _BACKUP_WORKLIST, remaining_backup)
    _write_jsonl(run_p / _REVIEW_WORKLIST, ordered_tasks)
    _write_jsonl(run_p / _REPAIR_WORKLIST, repairs)
    enhancements = sorted(enhancement_by_key.values(),
                          key=lambda row: (str(row.get("id")),
                                           str(row.get("rtl_sha256"))))
    _write_jsonl(run_p / _ENHANCEMENT_WORKLIST, enhancements)

    total = len(results)
    complete = (total > 0 and len(accepted_ids) == total
                and len(ordered_tasks) == total and not remaining_backup
                and not repairs)
    solve.update({
        "solved": sum(1 for r in results if r.get("candidate_ready")),
        "accepted": len(accepted_ids),
        "four_phase_summary": _four_phase_rollup(fpa, results),
        "results": results,
    })
    _atomic_write_json(solve_p, solve)
    acceptance = {
        "schema": _ACCEPTANCE_SCHEMA,
        "status": "COMPLETE" if complete else "PENDING",
        "accepted": len(accepted_ids), "total": total,
        "accepted_ids": accepted_ids,
        "review_outcomes": review_outcomes,
        "pending_backup": len(remaining_backup),
        "pending_repair": len(repairs),
        "pending_review": sum(1 for o in review_outcomes
                              if o.get("status") in {"PENDING", "REJECTED"}),
        "program_enhancement_candidates": len(enhancements),
    }
    _atomic_write_json(run_p / _ACCEPTANCE_REPORT, acceptance)
    print(f"\n{len(accepted_ids)}/{total} dual-track accepted; status "
          f"{acceptance['status']} -> {run_p / _ACCEPTANCE_REPORT}")
    if complete:
        return 0
    return 2 if (remaining_backup or repairs or ordered_tasks) else 1


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
                         "vibe_ic_one_shot_runner. Every PROGRAM candidate is "
                         "hash-bound to a mandatory blind AI route + semantic "
                         "review before it can be scored. AI may issue an "
                         "evidence-backed OVERRIDE_PROGRAM and is the final "
                         "semantic authority. No benchmark-specific solver is "
                         "involved.")
    ap.add_argument("--resume", action="store_true",
                    help="Advance needs_ai_backup.jsonl, needs_ai_review.jsonl, "
                         "and needs_ai_repair.jsonl. AI-authored/modified RTL is "
                         "re-gated; only a current hash-bound blind AI route + "
                         "semantic PASS writes a scoreable response. Semantic "
                         "FAIL becomes a finite repair/re-gate/review loop; "
                         "repeat until dual_track_acceptance.json is COMPLETE.")
    ap.add_argument("--limit", type=int, default=0,
                    help="with --solve: stop after N problems (0 = all)")
    ap.add_argument("--dataset", help="dataset path on disk")
    ap.add_argument("--run", help="run dir")
    ap.add_argument("--allow-ungated", action="store_true",
                    help="OPT-IN: score even if some samples lack an emit-path attestation "
                         "(a disclosed exploratory direct-author run, NON-CANONICAL). Default "
                         "HARD-BLOCKs ungated samples so the published number reflects the runner.")
    ap.add_argument("--capture-golden", action="store_true",
                    help="after --score, record every HOST-VERIFIED PASS into "
                         "OUR OWN golden corpus (benchmark_golden_capture), "
                         "tagged with the plugin version + --ai-model")
    ap.add_argument("--ai-model", default=None,
                    help="the model that authored the samples; REQUIRED by "
                         "--capture-golden (never defaulted)")
    ap.add_argument("--golden-db", default=None,
                    help=f"sqlite for --capture-golden (default {_GOLDEN_DEFAULT_DB})")
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
                  allow_direct_agent=a.allow_direct_agent,
                  capture_golden=a.capture_golden,
                  ai_model=a.ai_model,
                  golden_db=a.golden_db)
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
    # The per-SHAPE requirement check, from `benchmark_setup.needs()`. Printed
    # before the plan because a plan whose step 3 cannot run is worse than no
    # plan: the reader follows it and finds out inside the runner.
    try:
        _entry_for_env = _entry(a.bench)
    except SystemExit:
        _entry_for_env = None
    if _entry_for_env is not None:
        needed, missing = _requirement_report(_entry_for_env, env)
        print(f"# Requirements for shape {_entry_for_env.get('shape','?')}: "
              + ", ".join(f"{k}={'OK' if env.get(k) else 'MISSING'}" for k in needed))
        if missing:
            print(f"# MISSING: {', '.join(missing)} — this host cannot run "
                  f"{a.bench} as scoped. Detail + install pointers:")
            print(f"#   python3 {Path(__file__).resolve().parent / 'benchmark_setup.py'} {a.bench}")
    print()
    cmd_show(a.bench)


if __name__ == "__main__":
    main()
