#!/usr/bin/env python3
"""benchmark_dispatch.py — entry point for /vibe-ic-benchmark.

Reads BENCHMARK_REGISTRY.json, picks the correct run-shape per
open-benchmark-methodology skill § 2, sets up the run dir scaffold, and prints
the canonical next-step commands (clone dataset / drive runner or gates /
invoke scorer / write RESULT.md). Does NOT itself perform the AI authoring
step — the agent does that, guided by the per-shape blind_instructions_*.md.

Usage:
    python3 benchmark_dispatch.py <bench>                       # check status + show plan
    python3 benchmark_dispatch.py <bench> --solve --dataset <ds> --run <dir>
    python3 benchmark_dispatch.py <bench> --resume --dataset <ds> --run <dir>
    python3 benchmark_dispatch.py <bench> --score --dataset <ds> --run <dir>
    python3 benchmark_dispatch.py --list                         # list all known benchmarks
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
import concurrent.futures
import contextlib
import fcntl
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from _atomic_artefact import write_json as _atomic_write_json
from _atomic_artefact import write_text as _atomic_write_text

HARNESS = Path(__file__).resolve().parent.parent / "benchmark"
REGISTRY = HARNESS / "BENCHMARK_REGISTRY.json"
EXPERT_AGENT_MD = Path(__file__).resolve().parent.parent / "agents" / "ic-expert-agent.md"

_COORDINATOR_LOCK = ".benchmark_dispatch.coordinator.lock"


class _CoordinatorBusy(RuntimeError):
    """A second solve/resume coordinator targeted the same run root."""


@contextlib.contextmanager
def _run_root_coordinator_lock(run_p: Path, operation: str):
    """Own all run-root shared writes for one solve/resume invocation.

    The lock file is intentionally persistent so a refused second coordinator
    can name the last recorded owner.  Ownership itself is the kernel ``flock``
    and is released on close, including exception exits; the JSON is only a
    diagnostic, never evidence that a stale process still owns the run.
    """
    run_p = Path(run_p).resolve()
    run_p.mkdir(parents=True, exist_ok=True)
    lock_p = run_p / _COORDINATOR_LOCK
    lock_f = lock_p.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_f.seek(0)
            owner = lock_f.read().strip() or "owner metadata unavailable"
            raise _CoordinatorBusy(
                "another benchmark_dispatch coordinator owns run root "
                f"{run_p}: {owner}") from exc
        lock_f.seek(0)
        lock_f.truncate()
        lock_f.write(json.dumps({
            "schema": "vibeic.benchmark.run_root_lock.v1",
            "operation": str(operation),
            "pid": os.getpid(),
            "run_root": str(run_p),
        }, sort_keys=True) + "\n")
        lock_f.flush()
        yield
    finally:
        try:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        finally:
            lock_f.close()


T = TypeVar("T")
R = TypeVar("R")


def _ordered_parallel_map(items: Iterable[T], worker: Callable[[T], R],
                          jobs: int) -> list[R]:
    """Run unique-project work concurrently and return input-order results."""
    rows = list(items)
    if jobs <= 1 or len(rows) <= 1:
        return [worker(row) for row in rows]
    ordered: list[R | None] = [None] * len(rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(worker, row): i for i, row in enumerate(rows)}
        for future in concurrent.futures.as_completed(futures):
            ordered[futures[future]] = future.result()
    return [row for row in ordered if row is not None]


@dataclass(frozen=True)
class _ProcessOutcome:
    rc: int | None
    error: str | None = None


class _RunnerBudget:
    """Bound runner-heavy concurrency and per-worker tool thread budgets.

    A whole runner invocation is conservatively treated as a heavy slot.  This
    bounds every synth/LEC it may reach without requiring the dispatcher to
    duplicate the runner's internal step map.  ``jobs`` and ``heavy_jobs`` are
    separate so staging/collection fan-out can remain wider than EDA pressure.
    """

    def __init__(self, jobs: int, heavy_jobs: int | None,
                 worker_threads: int):
        if jobs < 1:
            raise ValueError("--jobs must be >= 1")
        self.jobs = int(jobs)
        self.heavy_jobs = int(heavy_jobs if heavy_jobs is not None else jobs)
        if self.heavy_jobs < 1 or self.heavy_jobs > self.jobs:
            raise ValueError("--heavy-jobs must be between 1 and --jobs")
        if worker_threads < 0:
            raise ValueError("--worker-threads must be >= 0")
        self._heavy = threading.BoundedSemaphore(self.heavy_jobs)
        # Per-invocation wall-clock ceiling, env-tunable. Unset (default)
        # keeps the historical unbounded behaviour; set, it stops ONE
        # problem's runner from eating the whole run's budget. A value that
        # does not parse as a positive number REFUSES here rather than
        # degrading to "no ceiling" — a bound that silently turns itself off
        # reports a safety it does not provide.
        self.timeout_s: float | None = None
        raw_timeout = os.environ.get("VIBEIC_SOLVE_RUNNER_TIMEOUT_S")
        if raw_timeout is not None and raw_timeout.strip():
            try:
                self.timeout_s = float(raw_timeout)
            except ValueError:
                raise ValueError(
                    "VIBEIC_SOLVE_RUNNER_TIMEOUT_S must be a number of "
                    f"seconds, got {raw_timeout!r}") from None
            if self.timeout_s <= 0:
                raise ValueError(
                    "VIBEIC_SOLVE_RUNNER_TIMEOUT_S must be > 0, got "
                    f"{raw_timeout!r}")
        self._env: dict[str, str] | None = None
        if worker_threads or self.jobs > 1:
            threads = (int(worker_threads) if worker_threads else
                       max(1, (os.cpu_count() or self.jobs) // self.heavy_jobs))
            self._env = os.environ.copy()
            for name in ("VIBEIC_EDA_THREADS", "VIBEIC_OPENROAD_THREADS",
                         "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                         "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                self._env[name] = str(threads)

    def run(self, argv: list[str]) -> _ProcessOutcome:
        kwargs = {"capture_output": True, "text": True}
        if self._env is not None:
            kwargs["env"] = self._env
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        try:
            with self._heavy:
                proc = subprocess.run(argv, **kwargs)
        except subprocess.TimeoutExpired:
            return _ProcessOutcome(
                rc=None,
                error=(f"TimeoutExpired: runner exceeded "
                       f"VIBEIC_SOLVE_RUNNER_TIMEOUT_S={self.timeout_s:g}s "
                       f"and was killed"))
        except Exception as exc:                         # noqa: BLE001
            return _ProcessOutcome(
                rc=None, error=f"{type(exc).__name__}: {exc}")
        return _ProcessOutcome(rc=int(proc.returncode))


@dataclass(frozen=True)
class _SolveWorkerOutcome:
    index: int
    problem_id: str
    result_json: str
    review_task_json: str | None
    backup_task_json: str | None
    log_line: str


@dataclass(frozen=True)
class _ResumeRunnerOutcome:
    problem_id: str
    rc: int | None
    collected_json: str | None
    error: str | None


def _phase_error_attribution() -> dict:
    """Named no-measurement record for a project worker that could not finish."""
    row = {"status": "NOT_MEASURED", "reason": "PROJECT_WORKER_ERROR"}
    return {
        "phase1_routing": dict(row),
        "phase2_solving": dict(row),
        "phase3_verifying": dict(row),
        "phase4_debugging": dict(row),
    }


# ORGANIC-20260605-shapec-lesson-digest-injection — surface captured lessons to
# blind single-shot authors. The renderer was hoisted to the shared module
# `_lesson_digest` so the PRODUCTION spec-to-rtl path (design_one_shot_runner
# step_rtl_gen WAIVE) surfaces the SAME corpus to runner-driven authors. This
# thin alias preserves the historical `benchmark_dispatch._render_lesson_digest`
# helper name while the only public authoring entry remains `--solve`.
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
    print("# --solve creates a FRESH run dir and stages INPUT only; the")
    print("# benchmark_clean_room_check.py guard FAILs a contaminated run so it")
    print("# cannot be scored as canonical.")
    print("#")
    print("# Partial prior-failure runs are not a benchmark result. Every canonical")
    print("# invocation processes the complete current dataset through this path.")
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
    if bench in _BENCH_FORMAT:
        fmt = _BENCH_FORMAT[bench]
        bi = (HARNESS / "blind_instructions_shape_cvdp.md"
              if fmt == "cvdp" else
              HARNESS / ("blind_instructions_shape_b.md"
                         if shape == "B" else "blind_instructions_shape_c.md"))
        print("  1. Use a fresh run directory; do not use a separate scaffold "
              "or benchmark-specific authoring harness.")
        print("  2. Solve EVERY problem through the general IC-design path:")
        print(f"     python3 {Path(__file__).name} {bench} --solve "
              "--dataset <DATASET> --run <RUNDIR>")
        print(f"  3. Complete blind AI worklists per: {bi}")
        print("     needs_ai_backup.jsonl authors only runner-declared WAIVEs;")
        print("     needs_ai_review.jsonl reviews every exact candidate hash.")
        print(f"  4. Resume until {_ACCEPTANCE_REPORT} is COMPLETE:")
        print(f"     python3 {Path(__file__).name} {bench} --resume "
              "--dataset <DATASET> --run <RUNDIR>")
        score_tail = (" --scorer-root <CVDP_BENCHMARK_ROOT>"
                      if fmt == "cvdp" else "")
        print("  5. Run the official scorer on accepted candidates only:")
        print(f"     python3 {Path(__file__).name} {bench} --score "
              f"--dataset <DATASET> --run <RUNDIR>{score_tail}")
    elif shape == "A":
        print("  /vibe-ic-all <project>     # full doc→GDS (benchmark_clean style)")
        print("  Then run skill `benchmark-verify` for the six-pillar verification.")
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


# A candidate is not accepted merely because Program emitted it. A blind AI
# must review the frozen Program result; rejection requires executable proof.
_REVIEW_TASK_SCHEMA = "vibeic.benchmark.ai_review_task.v2"
_AI_REVIEW_SCHEMA = "vibeic.benchmark.ai_review.v2"
_ACCEPTANCE_SCHEMA = "vibeic.benchmark.program_first_ai_review.v2"
_CANDIDATE_SCHEMA = "vibeic.benchmark.candidate_snapshot.v1"
_CHALLENGE_SCHEMA = "vibeic.benchmark.ai_verification_challenge.v1"
_AI_REPAIR_RECORD_SCHEMA = "vibeic.benchmark.ai_repair_record.v1"
_REVIEW_WORKLIST = "needs_ai_review.jsonl"
_BACKUP_WORKLIST = "needs_ai_backup.jsonl"
_REPAIR_WORKLIST = "needs_ai_repair.jsonl"
_ENHANCEMENT_WORKLIST = "program_enhancement_candidates.jsonl"
_ACCEPTANCE_REPORT = "program_first_ai_review_acceptance.json"

#: A verification challenge has three substantive outcomes -- the candidate
#: PASSed it, the candidate FAILed it, or the challenge itself is INVALID --
#: and one that is not an outcome at all. UNAVAILABLE means the host has no
#: simulator, so nothing about this candidate was established either way.
#: Folding it into "not FAIL" charges the AI reviewer with an unproven finding
#: on the strength of a missing tool; folding it into "not PASS" charges the
#: repair with failing a test nobody ran. Both are a MISSING CAPABILITY
#: rendered as a DEFECT IN THE SUBJECT, so it gets its own status and its own
#: name in the acceptance report.
_CHALLENGE_UNAVAILABLE = "UNAVAILABLE"
#: A joint candidate+challenge compile whose every error cites candidate RTL.
#: This is the strongest available evidence that the candidate itself is
#: broken, but it does not prove the AI's specific semantic claim, so it is
#: neither FAIL nor INVALID: FAIL would endorse an assertion no simulation
#: ran, and INVALID would charge the test with the candidate's own defect.
_CHALLENGE_CANDIDATE_BROKEN = "CANDIDATE_BROKEN"
_NOT_MEASURED = "NOT_MEASURED"


def _safe_problem_id(problem_id: str) -> str:
    return re.sub(r"[^-\w.]", "_", str(problem_id))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _rtl_files(project: Path) -> list[Path]:
    rtl_dir = Path(project) / "phase2" / "stage1" / "rtl"
    return sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v")))


def _candidate_text(paths: list[Path]) -> str:
    return "\n".join(Path(p).read_text(errors="replace") for p in paths)


def _write_immutable_text(path: Path, value: str) -> None:
    """Write evidence once; a hash-addressed artefact may never be replaced."""
    path = Path(path)
    if path.is_file():
        if path.read_text(errors="replace") != value:
            raise ValueError(f"immutable evidence changed at {path}")
        return
    _atomic_write_text(path, value)


def _write_immutable_json(path: Path, value: dict) -> None:
    """JSON form of :func:`_write_immutable_text`."""
    path = Path(path)
    if path.is_file():
        try:
            current = json.loads(path.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"immutable evidence unreadable at {path}: {exc}") from exc
        if current != value:
            raise ValueError(f"immutable evidence changed at {path}")
        return
    _atomic_write_json(path, value)


def _archive_candidate(problem_id: str, project: Path, got: dict,
                       run_p: Path, candidate_origin: str) -> dict:
    """Freeze the exact gated candidate before an AI can edit the work tree."""
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    source_paths = _rtl_files(project)
    completion = str(got.get("completion") or "")
    rtl_hash = _sha256_text(completion)
    safe = _safe_problem_id(problem_id)
    origin = _safe_problem_id(candidate_origin).lower()
    root = run_p / "candidate_snapshots" / safe / f"{origin}-{rtl_hash}"
    frozen_paths: list[str] = []
    for index, source in enumerate(source_paths):
        frozen = root / "rtl" / f"{index:02d}_{source.name}"
        _write_immutable_text(frozen, source.read_text(errors="replace"))
        frozen_paths.append(str(frozen.resolve()))
    completion_path = root / "completion.txt"
    payload_path = root / "response_payload.json"
    _write_immutable_text(completion_path, completion)
    _write_immutable_json(payload_path, got)
    record = {
        "schema": _CANDIDATE_SCHEMA,
        "id": str(problem_id),
        "candidate_origin": candidate_origin,
        "rtl_sha256": rtl_hash,
        "rtl_paths": frozen_paths,
        "completion_path": str(completion_path.resolve()),
        "response_payload_path": str(payload_path.resolve()),
        "source_rtl_paths": [str(p.resolve()) for p in source_paths],
    }
    manifest = root / "manifest.json"
    record["manifest_path"] = str(manifest.resolve())
    _write_immutable_json(manifest, record)
    return record


def _validate_candidate_snapshot(candidate: dict, problem_id: str) -> list[str]:
    """Return tamper/missing reasons for one immutable candidate record."""
    reasons: list[str] = []
    if not isinstance(candidate, dict):
        return ["candidate snapshot is absent"]
    if candidate.get("schema") != _CANDIDATE_SCHEMA:
        reasons.append(f"candidate schema must be {_CANDIDATE_SCHEMA!r}")
    if str(candidate.get("id")) != str(problem_id):
        reasons.append("candidate id does not match the review task")
    paths = [Path(str(p)) for p in candidate.get("rtl_paths") or []]
    if not paths or not all(p.is_file() for p in paths):
        reasons.append("candidate snapshot RTL is absent")
    completion_path = Path(str(candidate.get("completion_path") or ""))
    payload_path = Path(str(candidate.get("response_payload_path") or ""))
    if not completion_path.is_file():
        reasons.append("candidate snapshot completion is absent")
        completion = ""
    else:
        completion = completion_path.read_text(errors="replace")
    expected_hash = candidate.get("rtl_sha256")
    if _sha256_text(completion) != expected_hash:
        reasons.append("candidate snapshot completion hash is stale or wrong")
    if paths:
        try:
            if _sha256_text(_candidate_text(paths)) != expected_hash:
                reasons.append("candidate snapshot RTL bytes do not match completion")
        except OSError as exc:
            reasons.append(f"candidate snapshot RTL is unreadable: {exc}")
    try:
        payload = json.loads(payload_path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        reasons.append(f"candidate snapshot response payload is unreadable: {exc}")
    else:
        if _sha256_text(str(payload.get("completion") or "")) != expected_hash:
            reasons.append("candidate snapshot response payload does not match RTL")
    manifest_path = Path(str(candidate.get("manifest_path") or ""))
    try:
        manifest = json.loads(manifest_path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        reasons.append(f"candidate snapshot manifest is unreadable: {exc}")
    else:
        if manifest != candidate:
            reasons.append("candidate snapshot manifest differs from its task record")
    return reasons


def _make_ai_review_task(problem_id: str, project: Path, got: dict,
                         routing: dict, runner_rc: int, run_p: Path,
                         candidate_origin: str, *,
                         verification_challenges: list[dict] | None = None,
                         program_candidate: dict | None = None,
                         repair_parent_candidate: dict | None = None,
                         repair_provenance: dict | None = None) -> dict:
    """Build the hash-bound, oracle-free handoff for one AI review."""
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    prompt = project / "input" / "phase1_prompt.md"
    paths = _rtl_files(project)
    completion = str(got.get("completion") or "")
    if not prompt.is_file() or not paths or not got.get("ok") or not completion:
        raise ValueError("cannot request AI review without prompt + gated RTL")
    safe = _safe_problem_id(problem_id)
    candidate = _archive_candidate(
        problem_id, project, got, run_p, candidate_origin)
    if candidate_origin == "PROGRAM":
        program_candidate = candidate
    import emit_attestation as emit_attestation          # noqa: PLC0415
    phase1_provenance = emit_attestation.phase1_provenance(project)
    challenges = verification_challenges or []
    review_key = (f"{_safe_problem_id(candidate_origin).lower()}-"
                  f"r{len(challenges)}-{candidate['rtl_sha256']}")
    challenge_dir = (run_p / "ai_verification_challenges" / safe /
                     review_key)
    challenge_file = str((challenge_dir / "challenge_tb.sv").resolve())
    prompt_sha = _sha256_text(prompt.read_text(errors="replace"))
    evidence_item_shape = {
        "excerpt": ("<exact prompt excerpt; at least 8 characters and a "
                    "whitespace-normalized substring of prompt_path>"),
        "supports": "<the claim it supports; at least 12 characters>",
    }
    return {
        "schema": _REVIEW_TASK_SCHEMA,
        "id": str(problem_id),
        "project": str(project),
        "candidate_origin": candidate_origin,
        "candidate_snapshot": candidate,
        "program_candidate_snapshot": program_candidate,
        "repair_parent_candidate_snapshot": repair_parent_candidate,
        "verification_challenges": challenges,
        "repair_provenance": repair_provenance,
        "prompt_path": str(prompt),
        "rtl_paths": candidate["rtl_paths"],
        "working_rtl_paths": [str(p.resolve()) for p in paths],
        "prompt_sha256": prompt_sha,
        "phase1_provenance": phase1_provenance,
        "rtl_sha256": candidate["rtl_sha256"],
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
        "review_path": str((run_p / "ai_reviews" / safe /
                            f"{review_key}.json").resolve()),
        "challenge_path": challenge_file,
        "response_path": str((run_p / "responses" / f"{safe}.json").resolve()),
        "review_requirements": {
            "schema": _AI_REVIEW_SCHEMA,
            "required_envelope": {
                "_contract": (
                    "the review JSON written to review_path is REJECTED "
                    "unless it carries every field below with this exact "
                    "shape; concrete values are the required values (copy "
                    "them verbatim), <angle-bracket> values are authored by "
                    "the reviewer under the stated rule"),
                "schema": _AI_REVIEW_SCHEMA,
                "id": str(problem_id),
                "prompt_sha256": prompt_sha,
                "rtl_sha256": candidate["rtl_sha256"],
                "reviewer": {
                    "kind": "AI",
                    "model": ("<the reviewing AI model name; empty, "
                              "unknown, unspecified and n/a are rejected>"),
                },
                "blind": {"oracle_accessed": False},
                "routing": {
                    "verdict": "<AGREE or OVERRIDE_PROGRAM>",
                    "ai_nature": ("<the AI-judged nature; AGREE requires it "
                                  "to equal program_routing.nature>"),
                },
                "semantic_review": {
                    "verdict": "<PASS or FAIL>",
                    "findings": ["<list; must be non-empty when the verdict "
                                 "is FAIL>"],
                    "rationale": ("<the review basis; at least 16 "
                                  "characters>"),
                    "prompt_evidence": [dict(evidence_item_shape)],
                },
                "override": {
                    "_required_when": "routing.verdict is OVERRIDE_PROGRAM",
                    "prompt_evidence": [dict(evidence_item_shape)],
                    "explanation": ("<at least 160 characters when no "
                                    "prompt_evidence item verifies against "
                                    "the prompt>"),
                    "program_limitation": ("<the deterministic limitation "
                                           "being overridden; at least 16 "
                                           "characters>"),
                },
                "verification_test": {
                    "_required_when": ("semantic_review.verdict is FAIL; "
                                       "write the test file to the task "
                                       "challenge_path"),
                    "schema": _CHALLENGE_SCHEMA,
                    "path": challenge_file,
                    "sha256": "<sha256 of the exact challenge file text>",
                    "top_module": "vibeic_ai_challenge_tb",
                    "rationale": ("<what the test proves and how; at least "
                                  "80 characters>"),
                    "expected_behavior": ("<the checked behavior; at least "
                                          "24 characters>"),
                    "prompt_evidence": [dict(evidence_item_shape)],
                },
            },
            "blind_inputs_only": ["prompt_path", "rtl_paths"],
            "routing_verdicts": ["AGREE", "OVERRIDE_PROGRAM"],
            "override_rule": (
                "OVERRIDE_PROGRAM is allowed when the AI supplies prompt-bound "
                "evidence or a detailed interpretation and names the program "
                "limitation; AI semantic judgment is authoritative"),
            "semantic_verdicts": ["PASS", "FAIL"],
            "semantic_fail_action": (
                "write a self-contained prompt-derived executable test to "
                "challenge_path and describe it in verification_test; the "
                "reviewed PROGRAM candidate must fail that test before repair "
                "is authorized. Corrected RTL must pass the SAME immutable "
                "test, return through PROGRAM gates, then receive a fresh "
                "hash-bound AI review"),
            "semantic_fail_verification_test": {
                "schema": _CHALLENGE_SCHEMA,
                "path": challenge_file,
                "top_module": "vibeic_ai_challenge_tb",
                "required_result_on_reviewed_candidate": "FAIL",
                "required_result_on_repair": "PASS",
                "pass_marker": "VIBEIC_AI_CHALLENGE=PASS",
                "fail_marker": "VIBEIC_AI_CHALLENGE=FAIL",
                "constraints": [
                    "derive assertions only from prompt_path",
                    "self-contained: no include/readmem/file/system/DPI access",
                    "compile with the candidate RTL using iverilog -g2012",
                    "exit zero and print the pass marker only when assertions pass",
                ],
            },
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
    """Current prompt/frozen-RTL hashes plus frozen/stated RTL path sets."""
    prompt = Path(str(task.get("prompt_path") or ""))
    stated = sorted(str(Path(p).resolve()) for p in task.get("rtl_paths") or [])
    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        candidate = {}
    current_paths = sorted(
        str(Path(p).resolve()) for p in candidate.get("rtl_paths") or [])
    prompt_hash = (_sha256_text(prompt.read_text(errors="replace"))
                   if prompt.is_file() else None)
    try:
        rtl_hash = _sha256_text(_candidate_text([Path(p) for p in current_paths])) \
            if current_paths else None
    except OSError:
        rtl_hash = None
    return prompt_hash, rtl_hash, stated, current_paths


def _repair_record_path(run_p: Path, task: dict) -> Path:
    """Stable handoff path for the AI that authors a proven repair."""
    safe = _safe_problem_id(str(task.get("id")))
    parent_hash = str(task.get("rtl_sha256") or "missing")
    return (Path(run_p).resolve() / "ai_repairs" / safe /
            f"repair-of-{parent_hash}.json")


def _validate_repair_record(path: Path, task: dict, repaired_hash: str,
                            challenge: dict) -> tuple[dict | None, list[str]]:
    """Bind an AI repair's author and rationale to parent/new/test hashes."""
    path = Path(path).resolve()
    reasons: list[str] = []
    try:
        raw = path.read_text(errors="replace")
        record = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"AI repair record is absent or unreadable: {exc}"]
    if not isinstance(record, dict):
        return None, ["AI repair record is not a JSON object"]
    expected = {
        "schema": _AI_REPAIR_RECORD_SCHEMA,
        "id": str(task.get("id")),
        "prompt_sha256": task.get("prompt_sha256"),
        "parent_rtl_sha256": task.get("rtl_sha256"),
        "repaired_rtl_sha256": repaired_hash,
        "challenge_sha256": challenge.get("sha256"),
    }
    for key, value in expected.items():
        if record.get(key) != value:
            reasons.append(f"AI repair record {key} is stale or wrong")
    author = record.get("author") or {}
    if author.get("kind") != "AI":
        reasons.append("AI repair record author.kind must be AI")
    model = str(author.get("model") or "").strip()
    if not model or model.lower() in {"unknown", "unspecified", "n/a"}:
        reasons.append("AI repair record author.model must name the AI model")
    if record.get("oracle_accessed") is not False:
        reasons.append("AI repair record oracle_accessed must be false")
    if len(str(record.get("rationale") or "").strip()) < 40:
        reasons.append("AI repair record rationale must explain the repair")
    if reasons:
        return None, reasons
    return {**record, "path": str(path), "sha256": _sha256_text(raw)}, []


def _refresh_final_repair_provenance(task: dict) -> tuple[dict | None,
                                                          list[str]]:
    """Rebind an AI signature to the exact candidate emitted by PROGRAM gates.

    A supplied AI repair re-enters at validation, but deterministic gate logic
    can still normalize that RTL before freezing the candidate.  The original
    pre-gate signature must not silently authorize different bytes.  Before a
    fresh review exists, let the AI explicitly re-sign the final hash at the
    same evidence path; otherwise fail closed and request final provenance.
    """
    if task.get("candidate_origin") != "AI_REPAIR":
        return None, ["candidate is not an AI_REPAIR"]
    provenance = task.get("repair_provenance") or {}
    path_raw = str(provenance.get("path") or "").strip()
    path = Path(path_raw)
    parent = (task.get("repair_parent_candidate_snapshot")
              or task.get("program_candidate_snapshot") or {})
    parent_hash = str(parent.get("rtl_sha256") or "")
    challenges = task.get("verification_challenges") or []
    challenge_hash = str(provenance.get("challenge_sha256") or "")
    challenge = next(
        (item for item in challenges
         if str(item.get("sha256") or "") == challenge_hash), None)
    reasons: list[str] = []
    if not parent_hash:
        reasons.append("final AI repair task lacks its PROGRAM parent hash")
    if challenge is None:
        reasons.append("final AI repair task lacks its inherited challenge")
    if not path_raw:
        reasons.append("final AI repair task lacks its evidence path")
    if reasons:
        return None, reasons
    parent_task = {**task, "rtl_sha256": parent_hash}
    return _validate_repair_record(
        path, parent_task, str(task.get("rtl_sha256") or ""), challenge)


def _validate_embedded_repair_provenance(task: dict) -> list[str]:
    """Ensure a final AI_REPAIR review still names its actual repair author."""
    if task.get("candidate_origin") != "AI_REPAIR":
        return []
    provenance = task.get("repair_provenance")
    if not isinstance(provenance, dict):
        return ["AI_REPAIR candidate lacks repair_provenance"]
    parent = (task.get("repair_parent_candidate_snapshot")
              or task.get("program_candidate_snapshot") or {})
    challenges = task.get("verification_challenges") or []
    expected_challenge_hashes = {str(c.get("sha256")) for c in challenges}
    reasons = []
    reasons.extend(
        "repair parent " + reason
        for reason in _validate_candidate_snapshot(
            parent, str(task.get("id"))))
    if provenance.get("schema") != _AI_REPAIR_RECORD_SCHEMA:
        reasons.append("repair_provenance schema is invalid")
    if str(provenance.get("id")) != str(task.get("id")):
        reasons.append("repair_provenance id does not match task")
    if provenance.get("prompt_sha256") != task.get("prompt_sha256"):
        reasons.append("repair_provenance prompt hash is stale")
    if provenance.get("parent_rtl_sha256") != parent.get("rtl_sha256"):
        reasons.append("repair_provenance parent hash is stale")
    if provenance.get("repaired_rtl_sha256") != task.get("rtl_sha256"):
        reasons.append("repair_provenance repaired hash is stale")
    if str(provenance.get("challenge_sha256")) not in expected_challenge_hashes:
        reasons.append("repair_provenance challenge hash is not inherited")
    author = provenance.get("author") or {}
    if author.get("kind") != "AI" or not str(author.get("model") or "").strip():
        reasons.append("repair_provenance must name the AI author model")
    if provenance.get("oracle_accessed") is not False:
        reasons.append("repair_provenance oracle_accessed must be false")
    path = Path(str(provenance.get("path") or ""))
    try:
        raw = path.read_text(errors="replace")
        disk = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        reasons.append(f"repair_provenance file is absent or unreadable: {exc}")
    else:
        embedded = {k: v for k, v in provenance.items()
                    if k not in {"path", "sha256"}}
        if disk != embedded:
            reasons.append("repair_provenance differs from its evidence file")
        if _sha256_text(raw) != provenance.get("sha256"):
            reasons.append("repair_provenance file hash is stale")
    return reasons


_CHALLENGE_FORBIDDEN = re.compile(
    r"`\s*include|\$(?:readmem[hb]|fopen|fread|fscanf|sscanf|system)|"
    r"\b(?:DPI|VPI|PLI)\b",
    re.I,
)


def _verified_prompt_evidence(items, prompt_text: str) -> list[dict]:
    """Keep only exact normalized excerpts tied to a non-trivial claim."""
    verified = []
    if not isinstance(items, list):
        return verified
    normalized_prompt = re.sub(r"\s+", " ", prompt_text).strip()
    for item in items:
        if not isinstance(item, dict):
            continue
        excerpt = re.sub(r"\s+", " ", str(item.get("excerpt") or "")).strip()
        supports = str(item.get("supports") or "").strip()
        if (len(excerpt) >= 8 and excerpt in normalized_prompt
                and len(supports) >= 12):
            verified.append({"excerpt": excerpt, "supports": supports})
    return verified


def _challenge_from_review(task: dict, review: dict,
                           prompt_text: str) -> tuple[dict | None, list[str]]:
    """Validate and freeze an AI-authored prompt-only executable challenge."""
    raw = review.get("verification_test")
    reasons: list[str] = []
    if not isinstance(raw, dict):
        return None, ["semantic FAIL requires verification_test"]
    if raw.get("schema") != _CHALLENGE_SCHEMA:
        reasons.append(f"verification_test.schema must be {_CHALLENGE_SCHEMA!r}")
    expected_path = Path(str(task.get("challenge_path") or "")).resolve()
    actual_path = Path(str(raw.get("path") or "")).resolve()
    if actual_path != expected_path:
        reasons.append("verification_test.path must equal the task challenge_path")
    if str(raw.get("top_module") or "") != "vibeic_ai_challenge_tb":
        reasons.append("verification_test.top_module must be vibeic_ai_challenge_tb")
    if not actual_path.is_file():
        reasons.append("verification test file is absent")
        source = ""
    else:
        if actual_path.is_symlink():
            reasons.append("verification test must be a real file, not a symlink")
        source = actual_path.read_text(errors="replace")
    source_hash = _sha256_text(source)
    if raw.get("sha256") != source_hash:
        reasons.append("verification_test.sha256 is stale or wrong")
    if _CHALLENGE_FORBIDDEN.search(source):
        reasons.append("verification test is not self-contained")
    if "module vibeic_ai_challenge_tb" not in source:
        reasons.append("verification test must define vibeic_ai_challenge_tb")
    if "VIBEIC_AI_CHALLENGE=PASS" not in source:
        reasons.append("verification test must print VIBEIC_AI_CHALLENGE=PASS")
    if "VIBEIC_AI_CHALLENGE=FAIL" not in source:
        reasons.append("verification test must print VIBEIC_AI_CHALLENGE=FAIL "
                       "before failing")
    rationale = str(raw.get("rationale") or "").strip()
    expected_behavior = str(raw.get("expected_behavior") or "").strip()
    if len(rationale) < 80:
        reasons.append("verification_test.rationale must explain the test in "
                       "at least 80 characters")
    if len(expected_behavior) < 24:
        reasons.append("verification_test.expected_behavior must state the "
                       "checked behavior")
    verified_evidence = _verified_prompt_evidence(
        raw.get("prompt_evidence") or [], prompt_text)
    if not verified_evidence:
        reasons.append("verification_test needs prompt-bound evidence")
    if reasons:
        return None, reasons
    challenge = {
        "schema": _CHALLENGE_SCHEMA,
        "id": str(task.get("id")),
        "path": str(actual_path),
        "sha256": source_hash,
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_sha256": task.get("prompt_sha256"),
        "reviewed_rtl_sha256": task.get("rtl_sha256"),
        "prompt_evidence": verified_evidence,
        "expected_behavior": expected_behavior,
        "rationale": rationale,
    }
    return challenge, []


def _joint_compile_attribution(errors: str, rtl_paths: list[str],
                               test_path: str) -> tuple[bool, bool]:
    """Which side of a joint compile do the error lines cite?

    iverilog reports diagnostics as ``<path>:<line>: ...`` using the paths
    exactly as given on the command line, so ``path + ":"`` is the citation
    token. A line can cite either side; unclassifiable lines cite neither.
    """
    cites_candidate = False
    cites_challenge = False
    for line in errors.splitlines():
        if any(p and (p + ":") in line for p in rtl_paths):
            cites_candidate = True
        if test_path and (test_path + ":") in line:
            cites_challenge = True
    return cites_candidate, cites_challenge


def _run_verification_challenge(candidate: dict, challenge: dict) -> dict:
    """Compile/run one immutable test against one immutable candidate."""
    reasons = _validate_candidate_snapshot(candidate, str(candidate.get("id")))
    if reasons:
        return {"status": "INVALID", "reasons": reasons}
    test_path = Path(str(challenge.get("path") or ""))
    try:
        source = test_path.read_text(errors="replace")
    except OSError as exc:
        return {"status": "INVALID", "reasons": [f"challenge unreadable: {exc}"]}
    if _sha256_text(source) != challenge.get("sha256"):
        return {"status": "INVALID", "reasons": ["challenge hash changed"]}
    if _CHALLENGE_FORBIDDEN.search(source):
        return {"status": "INVALID",
                "reasons": ["challenge is not self-contained"]}
    iverilog, vvp = shutil.which("iverilog"), shutil.which("vvp")
    if not iverilog or not vvp:
        return {"status": "UNAVAILABLE", "reasons": ["iverilog/vvp unavailable"]}
    rtl_paths = [str(Path(p)) for p in candidate.get("rtl_paths") or []]
    with tempfile.TemporaryDirectory(prefix="vibeic-ai-challenge-") as td:
        out = Path(td) / "simv"
        try:
            comp = subprocess.run(
                [iverilog, "-g2012", "-s", "vibeic_ai_challenge_tb",
                 "-o", str(out), *rtl_paths, str(test_path)],
                cwd=td, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            return {"status": "INVALID", "reasons": ["challenge compile timed out"]}
        if comp.returncode != 0:
            errors = comp.stderr or comp.stdout or ""
            cites_candidate, cites_challenge = _joint_compile_attribution(
                errors, rtl_paths, str(test_path))
            if cites_candidate and not cites_challenge:
                return {"status": _CHALLENGE_CANDIDATE_BROKEN, "reasons": [
                    "joint compile failed; every cited file is candidate RTL",
                    errors[-1200:],
                ]}
            if cites_challenge and not cites_candidate:
                cited = "only the challenge file"
            elif cites_candidate:
                cited = "both candidate RTL and the challenge file"
            else:
                cited = "no classifiable file"
            return {"status": "INVALID", "reasons": [
                f"joint compile failed; errors cite {cited}",
                errors[-1200:],
            ]}
        try:
            sim = subprocess.run(
                [vvp, str(out)], cwd=td, capture_output=True, text=True,
                timeout=30)
        except subprocess.TimeoutExpired:
            return {"status": "INVALID", "returncode": None,
                    "reasons": ["challenge simulation timed out"]}
    output = (sim.stdout or "") + (sim.stderr or "")
    # The challenge contract requires printing the FAIL marker, not exiting
    # non-zero: a test that collects its verdict in $finish still fails.
    failed = "VIBEIC_AI_CHALLENGE=FAIL" in output
    passed = (not failed and sim.returncode == 0
              and "VIBEIC_AI_CHALLENGE=PASS" in output)
    return {
        "status": ("FAIL" if failed else ("PASS" if passed else "INVALID")),
        "returncode": sim.returncode,
        "output": output[-2000:],
        "candidate_rtl_sha256": candidate.get("rtl_sha256"),
        "challenge_sha256": challenge.get("sha256"),
    }


def _validate_ai_review(task: dict) -> dict:
    """Validate a hash-bound review, including evidence-backed AI override.

    AI is the semantic authority, but authority is not an unexplained token.
    It may override the program route when it cites prompt text or provides a
    detailed interpretation and identifies the deterministic limitation.  A
    valid semantic FAIL is a real ``REPAIR_REQUIRED`` decision, not a malformed
    review and not a permanent convergence failure.
    """
    task_reasons: list[str] = []
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        task_reasons.append(f"review task schema must be {_REVIEW_TASK_SCHEMA!r}")
    review_path = Path(str(task.get("review_path") or ""))
    if not review_path.is_file():
        return {"status": "PENDING", "review_path": str(review_path),
                "reasons": task_reasons + ["AI review file is absent"]}
    try:
        review = json.loads(review_path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "REJECTED", "review_path": str(review_path),
                "reasons": [f"AI review is unreadable: {type(exc).__name__}: {exc}"]}
    reasons: list[str] = task_reasons
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
    reasons.extend(_validate_candidate_snapshot(
        task.get("candidate_snapshot") or {}, str(task.get("id"))))
    reasons.extend(_validate_embedded_repair_provenance(task))

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
        verified_evidence = _verified_prompt_evidence(evidence, prompt_text)
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
    verified_semantic_evidence = _verified_prompt_evidence(
        semantic_evidence, prompt_text)
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
    challenge = None
    challenge_result = None
    #: Reasons this host could not ADJUDICATE, kept apart from `reasons`, which
    #: are findings against the review or the candidate. The two must never be
    #: mixed: one says "this is wrong", the other says "we did not look".
    unmeasurable: list[str] = []
    if semantic_verdict == "FAIL":
        challenge, challenge_reasons = _challenge_from_review(
            task, review, prompt_text)
        reasons.extend(challenge_reasons)
        if challenge is not None:
            challenge_result = _run_verification_challenge(
                task.get("candidate_snapshot") or {}, challenge)
            if challenge_result.get("status") == _CHALLENGE_UNAVAILABLE:
                unmeasurable.append(
                    "the prompt-derived verification test could not be RUN on "
                    "this host, so the AI finding is neither proven nor "
                    "disproven: "
                    + "; ".join(str(r) for r in
                                challenge_result.get("reasons") or []))
            elif (challenge_result.get("status")
                  == _CHALLENGE_CANDIDATE_BROKEN):
                # A candidate that cannot even compile can never produce the
                # FAIL a proof demands; demanding one here would make worse
                # candidates harder to reject than better ones. The compile
                # errors travel with challenge_result into the repair task.
                pass
            elif challenge_result.get("status") != "FAIL":
                reasons.append("AI finding is not proven: the reviewed candidate "
                               "must fail the prompt-derived verification test")
    inherited_challenge_results = []
    for inherited in task.get("verification_challenges") or []:
        inherited_reasons = []
        if inherited.get("schema") != _CHALLENGE_SCHEMA:
            inherited_reasons.append("inherited challenge schema is invalid")
        if str(inherited.get("id")) != str(task.get("id")):
            inherited_reasons.append("inherited challenge id does not match task")
        if inherited.get("prompt_sha256") != task.get("prompt_sha256"):
            inherited_reasons.append("inherited challenge prompt hash is stale")
        if inherited_reasons:
            reasons.extend(inherited_reasons)
            inherited_challenge_results.append({
                "status": "INVALID", "reasons": inherited_reasons})
            continue
        result = _run_verification_challenge(
            task.get("candidate_snapshot") or {}, inherited)
        inherited_challenge_results.append(result)
        if result.get("status") == _CHALLENGE_UNAVAILABLE:
            unmeasurable.append(
                "an inherited immutable verification test could not be RUN on "
                "this host, so the repair is neither proven nor disproven: "
                + "; ".join(str(r) for r in result.get("reasons") or []))
        elif (result.get("status") == "FAIL"
              and semantic_verdict == "FAIL"):
            # A fresh AI rejection and an inherited prompt-derived failure
            # agree that this intermediate repair is still wrong.  That is
            # additional repair evidence, not a malformed review.  A claimed
            # PASS over the same failure remains rejected below.
            pass
        elif result.get("status") != "PASS":
            reasons.append("repair does not pass every immutable verification "
                           "test that proved its parent candidate wrong")
    if reasons:
        # A finding against the review outranks an unrunnable proof: a
        # malformed review is wrong on every host, simulator or not.
        status = "REJECTED"
        decision_reasons = reasons
    elif unmeasurable:
        status = _NOT_MEASURED
        decision_reasons = unmeasurable + [
            "NOT_MEASURED is not a verdict about this candidate or this "
            "review. This host lacks the capability the proof needs; install "
            "it and re-run --resume. Nothing is accepted on the strength of a "
            "test that did not run."]
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
            "verified_challenge": challenge,
            "challenge_result": challenge_result,
            "inherited_challenge_results": inherited_challenge_results,
            "unmeasurable": unmeasurable,
            "override": ({**override, "verified_prompt_evidence": verified_evidence}
                         if routing_verdict == "OVERRIDE_PROGRAM" else None)}


def _attach_ai_review_attribution(result: dict, verdict: dict,
                                  task: dict) -> None:
    """Put Program First's AI review WHO/HOW into the four-phase record."""
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
    program_candidate = task.get("program_candidate_snapshot") or {}
    initial_origin = (program_candidate.get("candidate_origin")
                      or task.get("candidate_origin") or "NONE")
    result["initial_candidate_origin"] = initial_origin
    phases.setdefault("phase2_solving", {}).update({
        "program_first_candidate": {
            "origin": initial_origin,
            "rtl_sha256": program_candidate.get("rtl_sha256"),
            "how": "Program emitted and gated the immutable first candidate",
        },
        "accepted_candidate": {
            "origin": task.get("candidate_origin"),
            "rtl_sha256": task.get("rtl_sha256"),
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
    repair = task.get("repair_provenance") or {}
    if task.get("candidate_origin") == "AI_REPAIR" and repair:
        phases.setdefault("phase4_debugging", {})[
            "ai_semantic_repair"] = {
                "actor": (repair.get("author") or {}).get("model"),
                "mechanism": "AI",
                "status": "VERIFIED_AND_ACCEPTED" if status == "ACCEPTED"
                          else status,
                "rationale": repair.get("rationale"),
                "parent_rtl_sha256": repair.get("parent_rtl_sha256"),
                "repaired_rtl_sha256": repair.get("repaired_rtl_sha256"),
                "challenge_sha256": repair.get("challenge_sha256"),
                "program_reentry": "step 2 gates",
                "fresh_ai_review_actor": model,
                "physical_eco": False,
            }
    result["program_first_ai_review"] = {
        k: verdict.get(k) for k in (
            "status", "reviewer_model", "routing_verdict", "ai_nature",
            "semantic_verdict", "semantic_findings", "override")
    }
    result["program_first_ai_review"]["repair_provenance"] = repair or None


def _program_enhancement_candidate(task: dict, result: dict,
                                   verdict: dict) -> dict:
    """A durable, non-blocking follow-up when AI exposes program rigidity."""
    override = verdict.get("override") or {}
    if verdict.get("verified_challenge"):
        why_non_blocking = (
            "AI supplied prompt-bound executable evidence; convert the same "
            "test into a reusable Program regression without rewriting this "
            "already-frozen benchmark attempt")
    else:
        why_non_blocking = (
            "AI supplied an auditable route interpretation; improve the "
            "reusable Program router without rewriting this frozen attempt")
    return {
        "schema": "vibeic.benchmark.program_enhancement_candidate.v1",
        "id": str(task.get("id")),
        "project": task.get("project"),
        "prompt_sha256": task.get("prompt_sha256"),
        "rtl_sha256": task.get("rtl_sha256"),
        "review_path": task.get("review_path"),
        "program_candidate_snapshot": task.get("program_candidate_snapshot"),
        "reviewed_candidate_snapshot": task.get("candidate_snapshot"),
        "verified_challenge": verdict.get("verified_challenge"),
        "challenge_result": verdict.get("challenge_result"),
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
        "why_non_blocking": why_non_blocking,
    }


def _verified_program_recovery(task: dict, result: dict,
                               verdict: dict) -> dict:
    """Capture a repair only after it passes the tests that proved Program wrong."""
    return {
        "schema": "vibeic.benchmark.program_enhancement_candidate.v2",
        "id": str(task.get("id")),
        "project": task.get("project"),
        "prompt_sha256": task.get("prompt_sha256"),
        "rtl_sha256": task.get("rtl_sha256"),
        "semantic_verdict": "VERIFIED_RECOVERY",
        "program_candidate_snapshot": task.get("program_candidate_snapshot"),
        "repaired_candidate_snapshot": task.get("candidate_snapshot"),
        "verification_challenges": task.get("verification_challenges") or [],
        "repair_challenge_results":
            verdict.get("inherited_challenge_results") or [],
        "repair_provenance": task.get("repair_provenance"),
        "fresh_ai_review_path": task.get("review_path"),
        "fresh_ai_reviewer_model": verdict.get("reviewer_model"),
        "candidate_origin": result.get("candidate_origin"),
        "status": "VERIFIED_AI_RECOVERY_READY_FOR_PROGRAM_CAPTURE",
        "required_capture": {
            "action": (
                "add the immutable prompt-derived challenge as a Program "
                "regression and enhance the reusable Program implementation"),
            "acceptance": (
                "the enhanced Program candidate passes the captured challenge "
                "on its first attempt without AI repair"),
        },
        "blocking_acceptance": False,
        "why_non_blocking": (
            "the current repair is independently proven and accepted; capture "
            "improves the next Program First attempt without rewriting this run"),
    }


def _four_phase_rollup(fpa, results: list[dict]) -> dict:
    """General attribution plus Program First / AI Review counts and actors."""
    out = fpa.summarize(results)

    def counts(values) -> dict:
        result: dict[str, int] = {}
        for value in values:
            key = str(value)
            result[key] = result.get(key, 0) + 1
        return result

    reviews = [r.get("program_first_ai_review") or {} for r in results]
    out["phase1_ai_review_status"] = counts(
        v.get("status") or "PENDING" for v in reviews)
    out["phase1_ai_review_models"] = counts(
        v.get("reviewer_model") or "PENDING" for v in reviews)
    out["phase2_candidate_origin"] = counts(
        r.get("candidate_origin", "NONE") for r in results)
    out["phase2_initial_candidate_origin"] = counts(
        r.get("initial_candidate_origin", r.get("candidate_origin", "NONE"))
        for r in results)
    out["phase3_ai_semantic_verdict"] = counts(
        v.get("semantic_verdict") or "PENDING" for v in reviews)
    out["phase4_ai_repair_required"] = counts(
        bool(r.get("ai_repair_required")) for r in results)
    out["phase4_ai_repairs_completed"] = counts(
        r.get("candidate_origin") == "AI_REPAIR" for r in results)
    return out


def _require_program_first_ai_acceptance(run_p: Path) -> None:
    """Block scoring until Program gates and blind AI review accept every id."""
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
    if (policy.get("review_task_schema") != _REVIEW_TASK_SCHEMA
            or policy.get("review_schema") != _AI_REVIEW_SCHEMA):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: solve "
                         "uses an obsolete proof schema; start a fresh run")
    acc_p = run_p / _ACCEPTANCE_REPORT
    if not acc_p.is_file():
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "no acceptance report; "
                         "run --resume after completing needs_ai_review.jsonl")
    try:
        acceptance = json.loads(acc_p.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         f"unreadable {acc_p}: {exc}")
    if (acceptance.get("schema") != _ACCEPTANCE_SCHEMA
            or acceptance.get("status") != "COMPLETE"):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "acceptance status is "
                         f"{acceptance.get('status', 'INVALID')}, not COMPLETE")

    tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
    expected = [str(r.get("id")) for r in solve.get("results") or []]
    by_id = {str(t.get("id")): t for t in tasks}
    if len(by_id) != len(tasks) or sorted(by_id) != sorted(expected):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "review worklist ids do "
                         "not exactly match solve_report results")
    accepted_ids = [str(pid) for pid in acceptance.get("accepted_ids") or []]
    if (sorted(accepted_ids) != sorted(expected)
            or acceptance.get("accepted") != len(expected)
            or acceptance.get("total") != len(expected)):
        raise SystemExit("Program First + AI Review acceptance BLOCKED: "
                         "COMPLETE report does "
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
        raise SystemExit("Program First + AI Review acceptance BLOCKED:\n  "
                         + "\n  ".join(failures))


def _shape_c_task_binding_reasons(task: dict, run_p: Path,
                                  solve_result: dict | None) -> list[str]:
    """Bind a Shape-C review task back to its runner-owned run evidence."""
    import emit_attestation as emit_attestation          # noqa: PLC0415

    run_p = Path(run_p).resolve()
    pid = str(task.get("id") or "")
    safe = _safe_problem_id(pid)
    reasons: list[str] = []
    expected_project = (run_p / "projects" / safe).resolve()
    project = Path(str(task.get("project") or "")).resolve()
    if project != expected_project:
        reasons.append("project is not the runner-owned project for this id")
    expected_prompt = expected_project / "input" / "phase1_prompt.md"
    if Path(str(task.get("prompt_path") or "")).resolve() != expected_prompt:
        reasons.append("prompt path is not inside the runner-owned project")
    expected_response = (run_p / "responses" / f"{safe}.json").resolve()
    if Path(str(task.get("response_path") or "")).resolve() != expected_response:
        reasons.append("response path is not the runner-owned response path")
    review_root = (run_p / "ai_reviews" / safe).resolve()
    try:
        Path(str(task.get("review_path") or "")).resolve().relative_to(review_root)
    except ValueError:
        reasons.append("review path escapes the runner-owned review directory")

    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        reasons.append("candidate snapshot record is malformed")
        candidate = {}
    candidate_root = (run_p / "candidate_snapshots" / safe).resolve()
    candidate_paths = [Path(str(p)).resolve() for p in
                       candidate.get("rtl_paths") or []]
    for path in candidate_paths + [
            Path(str(candidate.get("completion_path") or "")).resolve(),
            Path(str(candidate.get("response_payload_path") or "")).resolve(),
            Path(str(candidate.get("manifest_path") or "")).resolve()]:
        try:
            path.relative_to(candidate_root)
        except ValueError:
            reasons.append("candidate evidence escapes its runner-owned snapshot")
            break

    expected_phase1 = task.get("phase1_provenance")
    current_phase1 = emit_attestation.phase1_provenance(expected_project)
    if (not isinstance(expected_phase1, dict)
            or expected_phase1.get("ran") is not True):
        reasons.append("task lacks hash-bound Phase-1 provenance")
    elif current_phase1 != expected_phase1:
        reasons.append("Phase-1 L-doc provenance changed after task creation")

    if not isinstance(solve_result, dict):
        reasons.append("problem is absent from solve_report")
        return reasons
    if (solve_result.get("ok") is not True
            or solve_result.get("candidate_ready") is not True):
        reasons.append("solve_report did not mark a runner-owned candidate ready")
    if solve_result.get("accepted") is not True:
        reasons.append("solve_report did not mark this candidate accepted")
    if str(solve_result.get("candidate_origin")) != str(
            task.get("candidate_origin")):
        reasons.append("candidate origin differs from solve_report")
    if Path(str(solve_result.get("review_task") or "")).resolve() != Path(
            str(task.get("review_path") or "")).resolve():
        reasons.append("review task path differs from solve_report")

    verification = task.get("program_verification")
    if not isinstance(verification, dict):
        reasons.append("Program verification record is malformed")
        verification = {}
    if verification.get("actor") != "vibe_ic_one_shot_runner":
        reasons.append("Program verification actor is not the canonical runner")
    task_rc = verification.get("runner_rc")
    result_rc = solve_result.get("rc")
    if type(task_rc) is not int or type(result_rc) is not int:
        reasons.append(
            "runner rc is absent or not an integer in task or solve_report")
    elif task_rc != result_rc:
        reasons.append("runner rc differs from solve_report")
    phases = solve_result.get("phases")
    if not isinstance(phases, dict):
        reasons.append("solve_report phases record is malformed")
        phases = {}
    phase3 = phases.get("phase3_verifying")
    if not isinstance(phase3, dict):
        reasons.append("solve_report verifying phase is malformed")
        phase3 = {}
    ran = phase3.get("ran")
    if not isinstance(ran, dict):
        reasons.append("solve_report Program gate record is malformed")
        ran = {}
    recorded_rtl_gen = ran.get("rtl_gen")
    if verification.get("rtl_gen") != recorded_rtl_gen:
        reasons.append("RTL-owning Program gate differs from solve_report")
    if recorded_rtl_gen not in {"PASS", "SKIPPED-BY-ENTRY"}:
        reasons.append("RTL-owning Program gate did not pass its allowed status")
    return reasons


def _record_export_guard_notes(run_p: Path, solve: dict,
                               notes_by_id: dict[str, list[str]]) -> None:
    """Persist non-blocking export uncertainty beside each accepted result."""
    results = solve.get("results")
    if (not isinstance(results, list)
            or any(not isinstance(row, dict) for row in results)):
        raise SystemExit("accepted sample export BLOCKED: solve_report results "
                         "are malformed")
    result_ids = [str(row.get("id")) for row in results]
    if (len(set(result_ids)) != len(result_ids)
            or sorted(result_ids) != sorted(notes_by_id)):
        raise SystemExit("accepted sample export BLOCKED: export guard notes "
                         "do not exactly account for solve_report results")
    for row in results:
        row["export_guard_notes"] = list(notes_by_id[str(row.get("id"))])
    _atomic_write_json(Path(run_p) / "solve_report.json", solve)


def _export_accepted_shape_c_task(task: dict, samples: Path,
                                  top_module: str, *, run_p: Path,
                                  solve_result: dict | None) -> dict:
    """BLOCKING Shape-C sole emit for one accepted, frozen runner candidate.

    This is deliberately downstream of ``_require_program_first_ai_acceptance``:
    it never authors RTL.  It re-validates the hash-bound AI review, immutable
    candidate snapshot, Phase-1 provenance, RTL-owning Program gate,
    scorer-facing top, standalone compile, and prompt-derived export guards
    before atomically publishing the exact reviewed bytes.  The broader runner
    rc remains type-checked, cross-record bound, and disclosed in solve_report;
    it is not a functional VerilogEval score gate because unrelated SDC,
    physical, or full-design audit failures do not invalidate reviewed RTL.
    Any unavailable required proof is a named BLOCKED result; it is never an
    advisory and never a silent skip.
    """
    import emit_attestation as emit_attestation          # noqa: PLC0415
    import shape_b_sample_export as guarded_export       # noqa: PLC0415

    pid = str(task.get("id") or "")
    safe = _safe_problem_id(pid)
    reasons: list[str] = _shape_c_task_binding_reasons(
        task, run_p, solve_result)
    if not pid or safe != pid or "/" in pid or "\\" in pid:
        reasons.append("problem id is absent or unsafe for a sample filename")
    verdict = _validate_ai_review(task)
    if verdict.get("status") != "ACCEPTED":
        reasons.append("hash-bound blind AI review is not ACCEPTED")
        reasons.extend(str(v) for v in verdict.get("reasons") or [])

    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        candidate = {}
    reasons.extend(_validate_candidate_snapshot(candidate, pid))
    paths = [Path(str(p)) for p in candidate.get("rtl_paths") or []]
    try:
        rtl_text = _candidate_text(paths) if paths else ""
    except OSError as exc:
        rtl_text = ""
        reasons.append(f"candidate RTL is unreadable: {exc}")
    if _sha256_text(rtl_text) != task.get("rtl_sha256"):
        reasons.append("candidate RTL bytes do not match the reviewed hash")
    if top_module not in guarded_export._module_names(rtl_text):
        reasons.append(f"scorer-facing top module {top_module!r} is absent")

    prompt = Path(str(task.get("prompt_path") or ""))
    try:
        prompt_text = prompt.read_text(errors="replace")
    except OSError as exc:
        prompt_text = ""
        reasons.append(f"staged prompt is unreadable: {exc}")
    if _sha256_text(prompt_text) != task.get("prompt_sha256"):
        reasons.append("staged prompt bytes do not match the reviewed hash")

    project = Path(str(task.get("project") or ""))
    provenance = emit_attestation.phase1_provenance(project)
    if provenance.get("ran") is not True:
        reasons.append("Phase-1 L-doc provenance is absent")
    if shutil.which("iverilog") is None:
        reasons.append("standalone compile capability is unavailable")
    if reasons:
        return {"verdict": "BLOCKED", "id": pid, "reasons": reasons,
                "exported": None}

    samples.mkdir(parents=True, exist_ok=True)
    destination = samples / f"{pid}_sample01.sv"
    temporary = samples / f".{pid}_sample01.sv.pending"
    try:
        temporary.write_text(rtl_text)
        guard_ok, guard_detail = guarded_export.guard_export(
            temporary, prompt_text)
        if not guard_ok:
            return {"verdict": "BLOCKED", "id": pid,
                    "reasons": [str(v) for v in guard_detail],
                    "exported": None}
        temporary.replace(destination)
        try:
            emit_attestation.record(
                samples, destination,
                gates=["vibe_ic_one_shot_runner", "program_first_ai_review",
                       "shape_c_guard_export"],
                shape="C", phase1=provenance)
            records = emit_attestation._load(samples)
            record = records.get(destination.name) or {}
            attestation_matches = (
                record.get("sha256")
                == emit_attestation.sha256_file(destination)
                and record.get("shape") == "C"
                and (record.get("phase1") or {}).get("ran") is True
            )
        except (OSError, ValueError, TypeError) as exc:
            destination.unlink(missing_ok=True)
            return {"verdict": "BLOCKED", "id": pid,
                    "reasons": [f"Shape-C emit attestation failed: {exc}"],
                    "exported": None}
        if not attestation_matches:
            destination.unlink(missing_ok=True)
            return {"verdict": "BLOCKED", "id": pid,
                    "reasons": ["Shape-C emit attestation was not recorded"],
                    "exported": None}
    finally:
        temporary.unlink(missing_ok=True)
    guard_notes = [str(value) for value in guard_detail
                   if str(value).startswith("NOTE:")]
    return {"verdict": "PASS", "id": pid,
            "rtl_sha256": task.get("rtl_sha256"),
            "exported": str(destination),
            "guard_notes": guard_notes,
            "gates": ["vibe_ic_one_shot_runner",
                      "program_first_ai_review", "shape_c_guard_export"]}


def _export_accepted_shape_c_samples(bench: str, run_p: Path) -> None:
    """Export accepted frozen Shape-C candidates through their sole emit.

    Program First deliberately publishes hash-bound response payloads only
    after AI acceptance.  The scorer, however, consumes ``samples/`` carrying
    emit attestations.  Bridge those two contracts here, after blindness and
    acceptance gates but before the scorer. Shape C publishes the exact reviewed
        bytes only after the blocking RTL-gate/review/provenance/top/compile/export
        guard above. Broader runner failures stay visible in solve_report without
        being relabelled PASS. Shape B remains in its byte-identical historical
        function below.
    """
    entry = _entry(bench)
    shape = entry.get("shape")
    if shape != "C":
        return
    if shape == "C":
        import emit_attestation as emit_attestation      # noqa: PLC0415

        run_p = Path(run_p).resolve()
        strategy = (entry.get("layout") or {}).get("module_name_strategy")
        if strategy != "always_TopModule":
            raise SystemExit("accepted Shape-C sample export BLOCKED: module "
                             f"name strategy {strategy!r} is unsupported")
        try:
            tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
            solve = json.loads(
                (run_p / "solve_report.json").read_text(errors="replace"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(
                f"accepted Shape-C sample export setup failed: {exc}") from exc
        if not tasks:
            raise SystemExit("accepted Shape-C sample export BLOCKED: review "
                             "worklist is empty")
        if not isinstance(solve, dict):
            raise SystemExit("accepted Shape-C sample export BLOCKED: "
                             "solve_report root is not an object")
        solve_results = solve.get("results") or []
        if (not isinstance(solve_results, list)
                or any(not isinstance(row, dict) for row in solve_results)):
            raise SystemExit("accepted Shape-C sample export BLOCKED: "
                             "solve_report results are malformed")
        solve_by_id = {str(row.get("id")): row for row in solve_results}
        task_ids = [str(task.get("id")) for task in tasks]
        if (len(solve_by_id) != len(solve_results)
                or len(set(task_ids)) != len(task_ids)
                or sorted(task_ids) != sorted(solve_by_id)):
            raise SystemExit("accepted Shape-C sample export BLOCKED: review "
                             "worklist does not exactly match solve_report")

        failures = []
        guard_notes_by_id: dict[str, list[str]] = {}
        # Validate and emit every task into a private transaction first. A
        # failure in task N must not leave task 1..N-1 visible to the scorer.
        with tempfile.TemporaryDirectory(
                prefix=".shape-c-export-", dir=run_p) as transaction:
            staged_samples = Path(transaction) / "samples"
            for task in tasks:
                pid = str(task.get("id"))
                result = _export_accepted_shape_c_task(
                    task, staged_samples, "TopModule", run_p=run_p,
                    solve_result=solve_by_id.get(pid))
                if result.get("verdict") != "PASS":
                    failures.append(
                        f"{pid}: " + "; ".join(
                            str(v) for v in result.get("reasons") or []))
                else:
                    guard_notes_by_id[pid] = [
                        str(value) for value in result.get("guard_notes") or []]
            if failures:
                raise SystemExit("accepted Shape-C sample export BLOCKED:\n  "
                                 + "\n  ".join(failures))

            samples = run_p / "samples"
            expected_names = {f"{pid}_sample01.sv" for pid in task_ids}
            existing_names = ({p.name for p in samples.iterdir()
                               if p.is_file() and p.suffix in {".sv", ".v"}
                               and not p.name.startswith(".")}
                              if samples.is_dir() else set())
            if existing_names:
                records = emit_attestation._load(samples)
                existing_ok = existing_names == expected_names
                for task in tasks:
                    pid = str(task.get("id"))
                    destination = samples / f"{pid}_sample01.sv"
                    record = records.get(destination.name) or {}
                    if (not destination.is_file()
                            or emit_attestation.sha256_file(destination)
                            != task.get("rtl_sha256")
                            or record.get("sha256") != task.get("rtl_sha256")
                            or record.get("shape") != "C"
                            or record.get("phase1")
                            != task.get("phase1_provenance")):
                        existing_ok = False
                if not existing_ok:
                    raise SystemExit(
                        "accepted Shape-C sample export BLOCKED: samples/ "
                        "contains stale, partial, or foreign scoring artifacts")
                print(f"Program First Shape-C export: {len(tasks)}/{len(tasks)} "
                      "already carries exact accepted, attested samples")
                _record_export_guard_notes(
                    run_p, solve, guard_notes_by_id)
                return

            samples.mkdir(parents=True, exist_ok=True)
            published: list[Path] = []
            try:
                for task in tasks:
                    pid = str(task.get("id"))
                    staged = staged_samples / f"{pid}_sample01.sv"
                    destination = samples / staged.name
                    staged.replace(destination)
                    published.append(destination)
                    emit_attestation.record(
                        samples, destination,
                        gates=["vibe_ic_one_shot_runner",
                               "program_first_ai_review",
                               "shape_c_guard_export"],
                        shape="C", phase1=task.get("phase1_provenance"))
                records = emit_attestation._load(samples)
                for task, destination in zip(tasks, published):
                    record = records.get(destination.name) or {}
                    if (record.get("sha256") != task.get("rtl_sha256")
                            or record.get("shape") != "C"
                            or record.get("phase1")
                            != task.get("phase1_provenance")):
                        raise ValueError(
                            f"attestation read-back mismatch for {task.get('id')}")
            except (OSError, ValueError, TypeError) as exc:
                for destination in published:
                    destination.unlink(missing_ok=True)
                raise SystemExit(
                    "accepted Shape-C sample export BLOCKED: transactional "
                    f"publish failed: {exc}") from exc
        _record_export_guard_notes(run_p, solve, guard_notes_by_id)
        print(f"Program First Shape-C export: {len(tasks)}/{len(tasks)} "
              f"accepted frozen candidate(s) passed blocking sole emit -> "
              f"{run_p / 'samples'}")
        return


def _export_accepted_shape_b_samples(bench: str, dataset: Path,
                                     run_p: Path) -> None:
    """Export accepted frozen candidates through Shape B's sole emit path.

    Program First deliberately publishes hash-bound response payloads only
    after AI acceptance.  The scorer, however, consumes ``samples/`` carrying
    emit attestations.  Bridge those two contracts here, after blindness and
    acceptance gates but before the scorer: export the immutable reviewed RTL,
    never a mutable working copy, through ``shape_b_sample_export``.
    """
    if _entry(bench).get("shape") != "B":
        return
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import shape_b_sample_export as sample_export          # noqa: PLC0415

    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        raise SystemExit(f"no IO adapter bound for {bench!r}")
    dataset = Path(dataset).resolve()
    try:
        problems = {str(row["id"]): row
                    for row in bio.problems(fmt, dataset)}
        tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
        solve_p = run_p / "solve_report.json"
        solve = (json.loads(solve_p.read_text(errors="replace"))
                 if solve_p.is_file() else None)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"accepted sample export setup failed: {exc}") from exc

    if solve is not None and not isinstance(solve, dict):
        raise SystemExit("accepted Shape-B sample export BLOCKED: solve_report "
                         "root is not an object")
    if solve is not None:
        solve_results = solve.get("results")
        if (not isinstance(solve_results, list)
                or any(not isinstance(row, dict) for row in solve_results)):
            raise SystemExit("accepted Shape-B sample export BLOCKED: "
                             "solve_report results are malformed")
        task_ids = [str(task.get("id")) for task in tasks]
        solve_ids = [str(row.get("id")) for row in solve_results]
        if (len(set(task_ids)) != len(task_ids)
                or len(set(solve_ids)) != len(solve_ids)
                or sorted(task_ids) != sorted(solve_ids)):
            raise SystemExit("accepted Shape-B sample export BLOCKED: review "
                             "worklist does not exactly match solve_report")

    failures = []
    guard_notes_by_id: dict[str, list[str]] = {}
    samples = run_p / "samples"
    for task in tasks:
        pid = str(task.get("id"))
        candidate = task.get("candidate_snapshot") or {}
        paths = [Path(str(p)) for p in candidate.get("rtl_paths") or []]
        if not paths or len({p.parent.resolve() for p in paths}) != 1:
            failures.append(f"{pid}: frozen RTL is absent or spans directories")
            continue
        problem = problems.get(pid)
        if problem is None:
            failures.append(f"{pid}: no dataset input record")
            continue
        problem_root = Path(str(problem.get("root") or "")).resolve()
        try:
            design = str(problem_root.relative_to(dataset))
        except ValueError:
            failures.append(f"{pid}: dataset problem root escapes dataset")
            continue
        result = sample_export.export(
            paths[0].parent, pid, samples,
            dataset=dataset, design=design,
            prompt=Path(str(task.get("prompt_path") or "")),
            project=Path(str(task.get("project") or "")))
        if result.get("verdict") != "PASS":
            failures.append(
                f"{pid}: {result.get('reason') or 'emit rejected'}: "
                f"{result.get('note') or result.get('block_reason') or ''}")
        else:
            guard_notes_by_id[pid] = [
                str(value) for value in result.get("guard_notes") or []]
    if failures:
        raise SystemExit("accepted Shape-B sample export BLOCKED:\n  "
                         + "\n  ".join(failures))
    if solve is not None:
        _record_export_guard_notes(run_p, solve, guard_notes_by_id)
    elif any(guard_notes_by_id.values()):
        print("Program First export guard notes (solve_report unavailable): "
              + json.dumps(guard_notes_by_id, sort_keys=True))
    print(f"Program First export: {len(tasks)}/{len(tasks)} accepted frozen "
          f"candidate(s) passed Shape-B emit -> {samples}")


def _export_accepted_cvdp_responses(bench: str, dataset: Path,
                                    run_p: Path) -> Path:
    """Publish exact accepted candidates in CVDP's scorer envelope.

    This is a post-acceptance I/O translation, not an authoring gate. Routing,
    RTL generation, review, repair, and verification have already happened in
    the general flow. The adapter may read scorer-visible output path KEYS at
    this host-only boundary, but never reference values.
    """
    if _BENCH_FORMAT.get(bench) != "cvdp":
        raise SystemExit(f"{bench!r} is not bound to the CVDP I/O adapter")
    import benchmark_io_adapter as bio                    # noqa: PLC0415

    run_p = Path(run_p).resolve()
    dataset = Path(dataset).resolve()
    try:
        tasks = _read_jsonl(run_p / _REVIEW_WORKLIST)
        solve = json.loads(
            (run_p / "solve_report.json").read_text(errors="replace"))
        contracts = bio.cvdp_scorer_contracts(dataset)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"accepted CVDP response export setup failed: {exc}") from exc
    results = solve.get("results") if isinstance(solve, dict) else None
    if (not isinstance(results, list)
            or any(not isinstance(row, dict) for row in results)):
        raise SystemExit(
            "accepted CVDP response export BLOCKED: solve_report is malformed")
    solve_by_id = {str(row.get("id")): row for row in results}
    task_by_id = {str(task.get("id")): task for task in tasks}
    ordered_ids = [str(row.get("id")) for row in results]
    if (len(solve_by_id) != len(results)
            or len(task_by_id) != len(tasks)
            or sorted(task_by_id) != sorted(solve_by_id)):
        raise SystemExit(
            "accepted CVDP response export BLOCKED: review worklist does not "
            "exactly match solve_report")

    rows, evidence, failures = [], [], []
    for pid in ordered_ids:
        task = task_by_id[pid]
        result = solve_by_id[pid]
        reasons = _shape_c_task_binding_reasons(task, run_p, result)
        verdict = _validate_ai_review(task)
        if verdict.get("status") != "ACCEPTED":
            reasons.append("hash-bound blind AI review is not ACCEPTED")
            reasons.extend(str(v) for v in verdict.get("reasons") or [])
        candidate = task.get("candidate_snapshot")
        if not isinstance(candidate, dict):
            candidate = {}
        reasons.extend(_validate_candidate_snapshot(candidate, pid))
        response_paths = contracts.get(pid) or []
        if not response_paths:
            reasons.append("official scorer response-path contract is absent")
        completion = ""
        if not reasons:
            try:
                completion = bio.cvdp_package_response(
                    [Path(str(p)) for p in candidate.get("rtl_paths") or []],
                    [Path(str(p)) for p in
                     candidate.get("source_rtl_paths") or []],
                    response_paths)
            except (OSError, ValueError, TypeError) as exc:
                reasons.append(str(exc))
        if reasons:
            failures.append(f"{pid}: " + "; ".join(reasons))
            continue
        rows.append({"id": pid, "completion": completion})
        evidence.append({
            "id": pid,
            "candidate_rtl_sha256": task.get("rtl_sha256"),
            "scorer_completion_sha256": _sha256_text(completion),
            "response_paths": response_paths,
            "gates": ["vibe_ic_one_shot_runner",
                      "program_first_ai_review",
                      "cvdp_thin_io_package"],
        })
    if failures:
        raise SystemExit("accepted CVDP response export BLOCKED:\n  "
                         + "\n  ".join(failures))

    response_path = run_p / "responses" / "accepted_cvdp.jsonl"
    temp_path = response_path.with_name(
        f".{response_path.name}.{os.getpid()}.pending")
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_jsonl(temp_path, rows)
        temp_path.replace(response_path)
    finally:
        temp_path.unlink(missing_ok=True)
    report = {
        "schema": "vibeic.benchmark.cvdp_response_export.v1",
        "verdict": "PASS",
        "bench": bench,
        "dataset": str(dataset),
        "count": len(rows),
        "response_jsonl": str(response_path),
        "records": evidence,
    }
    _atomic_write_json(run_p / "reports" / "cvdp_response_export.json", report)
    print(f"Program First CVDP export: {len(rows)}/{len(rows)} accepted "
          f"candidate(s) packaged by the thin I/O adapter -> {response_path}")
    return response_path


def cmd_score(bench: str, run: str, dataset: str | None,
              allow_ungated: bool = False, allow_direct_agent: bool = False,
              capture_golden: bool = False, ai_model: str | None = None,
              golden_db: str | None = None,
              scorer_root: str | None = None, threads: int = 4):
    e = _entry(bench)
    if bench not in _BENCH_FORMAT:
        raise SystemExit(
            f"--score has no general I/O binding for {bench!r}. "
            f"Shape {e['shape']} uses benchmark-verify or its documented "
            "external scorer.")
    run_p = Path(run).resolve()
    config_path = run_p / ".bench_config.json"
    try:
        config = json.loads(config_path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            "canonical scoring requires the clean-room metadata written by "
            f"--solve: {config_path}: {exc}") from exc
    if (config.get("schema") != "vibeic.benchmark.general_run.v1"
            or config.get("bench") != bench
            or config.get("full_dataset") is not True):
        raise SystemExit(
            "canonical scoring requires a full-dataset general --solve run; "
            "partial, separate-scaffold, or benchmark-local runs are not eligible")
    _require_program_first_ai_acceptance(run_p)
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
        ds_p = Path(dataset).resolve()
    else:
        ds_p = Path(str(config.get("dataset") or "")).resolve()
    if ds_p != Path(str(config.get("dataset") or "")).resolve():
        raise SystemExit(
            f"dataset mismatch: --solve pinned {config.get('dataset')}, "
            f"but --score received {ds_p}")
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
              "audit skipped. Export is the orchestration DEFAULT (--solve "
              "pre-creates the dir; copy every agent transcript there). A run "
              "scored on this branch MUST disclose 'blindness audit "
              "unavailable' in its RESULT.md (ORGANIC-20260605-transcripts-"
              "export-default).")
    if _BENCH_FORMAT[bench] == "cvdp":
        if capture_golden:
            raise SystemExit(
                "--capture-golden is not implemented for CVDP's official "
                "cocotb result schema; refusing to imply that it was captured")
        responses = _export_accepted_cvdp_responses(
            bench, ds_p, run_p)
        scorer = HARNESS / "score_cvdp_open.py"
        cmd = [sys.executable, str(scorer),
               "--dataset", str(ds_p),
               "--responses", str(responses),
               "--run", str(run_p),
               "--threads", str(max(1, int(threads)))]
        if scorer_root:
            cmd += ["--scorer-root", str(Path(scorer_root).resolve())]
        print("$ " + " ".join(cmd))
        sys.exit(subprocess.call(cmd))
    if e["shape"] == "C":
        _export_accepted_shape_c_samples(bench, run_p)
    else:
        _export_accepted_shape_b_samples(bench, ds_p, run_p)
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
                "by the general runner's accepted emit path "
                "(shape_c_guard_export / shape_b_sample_export), "
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


def _solver_argv(runner: Path, proj: Path, entry, exit_step) -> list:
    """One problem's runner argv, assembled from the routing verdict.

    The exit decides what must NOT run. An RTL-evidence task never needs
    physical design because no RTL consumer reads a netlist or GDS; a run
    whose exit lies before step 15 therefore skips Phase 3 outright.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import task_nature_route as tnr                       # noqa: PLC0415
    argv = [sys.executable, str(runner), str(proj),
            "--skip-analog", "--skip-hardware"]
    if exit_step and exit_step in tnr.flow_step_ids():
        order = {s: i for i, s in enumerate(tnr.flow_step_ids())}
        if order.get(exit_step, 99) < order.get("15", 99):
            argv.append("--skip-phase3")
        # --skip-phase3 was the only bit the exit contract used to reach
        # execution, so a lint-evidence exit still dispatched phase-2 synthesis
        # and DFT/LEC. Forward the exit itself; the phase2 runner prunes every
        # dispatch site wholly past it as SKIPPED-BY-EXIT.
        argv += ["--exit-step", str(exit_step)]
    if entry and entry != "D1":
        argv += ["--entry-step", str(entry)]
    return argv


def _resume_solver_argv(runner: Path, proj: Path, supplied_rtl: bool,
                        entry, exit_step) -> list:
    """Re-enter one routed problem without losing its declared exit.

    AI backup/repair supplies RTL, so it resumes at the first RTL-validation
    step.  The routing exit is unchanged: re-entry must not expand a lint or
    behavioural task into synthesis/DFT/LEC work.
    """
    effective_entry = "2" if supplied_rtl else entry
    return _solver_argv(runner, proj, effective_entry, exit_step)


def _declared_route_ai_backup(routing: dict) -> dict:
    """Validate the route-level AI-backup declaration, without defaulting it.

    An absent declaration is different from a malformed declaration for
    diagnostics, but neither authorises AI work.  In particular, strings are
    not accepted as a convenient one-item list: silently normalising a broken
    route would turn a Program failure into an undeclared AI task.
    """
    plugin_entry = routing.get("plugin_entry")
    if plugin_entry is None:
        return {"status": "UNDECLARED", "skills": []}
    if not isinstance(plugin_entry, dict):
        return {"status": "INVALID", "skills": [],
                "reason": "plugin_entry must be an object"}
    if "ai_backup" not in plugin_entry:
        return {"status": "UNDECLARED", "skills": []}
    declared = plugin_entry.get("ai_backup")
    if not isinstance(declared, list) or not declared:
        return {"status": "INVALID", "skills": [],
                "reason": "plugin_entry.ai_backup must be a non-empty list"}
    if any(not isinstance(skill, str) or not skill.strip()
           for skill in declared):
        return {"status": "INVALID", "skills": [],
                "reason": "every declared AI-backup skill must be non-empty text"}
    skills = [skill.strip() for skill in declared]
    if len(set(skills)) != len(skills):
        return {"status": "INVALID", "skills": [],
                "reason": "declared AI-backup skills must be unique"}
    return {"status": "DECLARED", "skills": skills}


def _make_ai_backup_task(problem_id: str, project: Path, skills: list[str],
                         source: str, detail: str, bench: str,
                         dataset: Path, run_p: Path) -> dict:
    """Build one prompt-bound handoff into the runner-owned RTL directory."""
    project = Path(project).resolve()
    dataset = Path(dataset).resolve()
    run_p = Path(run_p).resolve()
    prompt = project / "input" / "phase1_prompt.md"
    prompt_text = prompt.read_text(errors="replace")
    return {
        "schema": "vibeic.benchmark.ai_backup_task.v1",
        "id": str(problem_id),
        "project": str(project),
        # `skill` keeps the existing single-skill consumer compatible.  The
        # route declaration is ordered, so its first member is the primary;
        # `declared_skills` keeps every authorised alternative visible.
        "skill": skills[0],
        "declared_skills": list(skills),
        "handoff_source": source,
        "prompt_sha256": _sha256_text(prompt_text),
        "write_rtl_to": str(project / "phase2" / "stage1" / "rtl"),
        "read_docs_from": str(project / "phase1" / "generated_docs"),
        "read_prompt_from": str(prompt),
        "runner_said": str(detail or "")[:600],
        "regate_entry_step": "2",
        "review_required_after_regating": True,
        "resume_with": (f"benchmark_dispatch.py {bench} --resume "
                        f"--dataset {dataset} --run {run_p}"),
    }


def _prepare_general_solve_run(bench: str, dataset: Path, run_p: Path,
                               fmt: str, limit: int) -> None:
    """Create the clean-room envelope owned by the one general solve entry.

    The retired scaffold entry used to create this state separately and thereby
    left an authoring gap before score. Keeping creation inside ``--solve``
    makes it impossible to substitute a benchmark-local author between verbs.
    """
    dataset = Path(dataset).resolve()
    run_p = Path(run_p).resolve()
    if not dataset.exists():
        raise SystemExit(f"dataset path not found: {dataset}")
    existing = ([child for child in run_p.iterdir()
                 if child.name != _COORDINATOR_LOCK]
                if run_p.exists() else [])
    if existing:
        raise SystemExit(
            f"clean-room solve requires an empty fresh run directory: {run_p}")
    run_p.mkdir(parents=True, exist_ok=True)
    for child in ("projects", "responses", "reports", "transcripts"):
        (run_p / child).mkdir(parents=True, exist_ok=True)
    _atomic_write_json(run_p / ".bench_config.json", {
        "schema": "vibeic.benchmark.general_run.v1",
        "bench": bench,
        "format": fmt,
        "dataset": str(dataset),
        "clean_room": True,
        "full_dataset": limit == 0,
        "diagnostic_limit": int(limit or 0),
        "inherited_from": None,
        "seed_run": None,
        "reused_samples_from": None,
    })
    _render_lesson_digest(run_p)
    guard = Path(__file__).resolve().parent / "benchmark_clean_room_check.py"
    if guard.is_file() and limit == 0:
        rc = subprocess.call([sys.executable, str(guard), str(run_p)])
        if rc != 0:
            raise SystemExit(
                "clean-room guard failed while creating the general solve run")
    elif limit:
        print("NOTICE: --limit creates a diagnostic partial run; it cannot be "
              "scored or published as a benchmark result")


def _cmd_solve_locked(bench: str, dataset: str, run: str, limit: int = 0,
                      jobs: int = 1, heavy_jobs: int | None = None,
                      worker_threads: int = 0) -> int:
    """Solve every problem through the GENERAL flow.

    This verb did not exist. A separate scaffold prepared the run and
    `--score` scored, leaving a hole an agent filled by hand — how a 302-problem
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
    sys.path.insert(0, str(HARNESS))
    import benchmark_io_adapter as bio                    # noqa: PLC0415
    import benchmark_entry_surface_check as bes           # noqa: PLC0415
    import flow_phase_attribution as fpa                  # noqa: PLC0415
    import task_nature_route as tnr                       # noqa: PLC0415

    entry_audit = bes.audit(Path(__file__).resolve().parents[1])
    if entry_audit.get("verdict") != "PASS":
        detail = "; ".join(
            f"{row.get('rule')}: {row.get('path')}"
            for row in entry_audit.get("findings") or [])
        print("ERROR: benchmark general-entry policy failed: " + detail,
              file=sys.stderr)
        return 2

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

    ds, run_p = Path(dataset).resolve(), Path(run).resolve()
    _prepare_general_solve_run(bench, ds, run_p, fmt, limit)
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"
    runner_budget = _RunnerBudget(jobs, heavy_jobs, worker_threads)
    problem_rows = []
    for index, prob in enumerate(bio.problems(fmt, ds)):
        if limit and index >= limit:
            break
        problem_rows.append((index, prob))
    problem_ids = [str(prob.get("id", f"problem-{index}"))
                   for index, prob in problem_rows]
    project_keys = [re.sub(r"[^\w.-]", "_", pid) for pid in problem_ids]
    if (len(set(problem_ids)) != len(problem_ids)
            or len(set(project_keys)) != len(project_keys)):
        print("ERROR: duplicate problem id or project-path collision in "
              "benchmark dataset", file=sys.stderr)
        return 2

    def _solve_one(row) -> _SolveWorkerOutcome:
        index, prob = row
        pid = str(prob.get("id", f"problem-{index}"))
        proj = run_p / "projects" / re.sub(r"[^\w.-]", "_", pid)
        staged_chars = 0
        nature = "NOT_MEASURED"
        entry = None
        ev = None
        exit_step = None
        verdict: dict = {}
        try:
            proj.mkdir(parents=True, exist_ok=True)
            staged = bio.stage(fmt, prob, proj)
            staged_chars = int(staged.get("prompt_chars") or 0)

            # One detector, not a second inline copy: `input/rtl/` is only ONE
            # of the canonical places a design's input RTL arrives in.
            rtl_present = fpa.rtl_present_at_input(proj)
            prompt_text = (proj / "input" / "phase1_prompt.md").read_text(
                errors="replace")

            # Completeness is disclosure only; it never selects a solver.
            completeness = _assess_why or "NOT_ADAPTED"
            assess = _assessors.get(fmt)
            if assess is not None:
                try:
                    completeness = assess(prompt_text).get("completeness", "?")
                except Exception as exc:                  # noqa: BLE001
                    completeness = (
                        f"UNAVAILABLE: {type(exc).__name__}: {exc}")

            verdict = tnr.classify_task_nature(prompt_text, rtl_present, None)
            nature = verdict["nature"]
            # `entry_nature` is the NATURE_ENTRY key on every branch; `nature`
            # may be the disclosing unpinned-transform label, which is not.
            entry_row = tnr.NATURE_ENTRY[verdict["entry_nature"]]
            entry = entry_row.get("entry_step")
            ev = entry_row.get("default_evidence")
            exit_step = (tnr.EVIDENCE_EXIT.get(ev) or {}).get("exit_step")

            process = runner_budget.run(
                _solver_argv(runner, proj, entry, exit_step))
            if process.error is not None:
                raise RuntimeError(process.error)
            rc = int(process.rc)
            got = bio.collect(fmt, pid, proj)
            waive = _rtl_gen_waive(proj)
            route_backup = _declared_route_ai_backup(verdict)
            backup_source = None
            backup_skills: list[str] = []
            backup_detail = ""
            if not got.get("ok"):
                if waive:
                    backup_source = "rtl_gen_waive"
                    backup_skills = [str(waive.get("fallback_skill"))]
                    backup_detail = str(waive.get("detail") or "")
                elif route_backup["status"] == "DECLARED":
                    backup_source = "route_declaration"
                    backup_skills = list(route_backup["skills"])
                    backup_detail = str(got.get("reason") or "")
            awaiting_backup = bool(backup_source)
            phases = fpa.attribute(
                proj, routing=verdict, entry=entry, evidence=ev,
                exit_step=exit_step, rtl_present=rtl_present,
                artefact_collected=bool(got.get("ok")))
            result = {
                "id": pid, "nature": nature,
                "entry": entry, "evidence": ev, "exit": exit_step,
                "rc": rc,
                "ok": bool(got.get("ok")),
                "candidate_ready": bool(got.get("ok")),
                "accepted": False, "staged": staged_chars,
                "completeness": completeness,
                "routing_verdict": verdict, "phases": phases,
                "candidate_origin": (
                    "PROGRAM" if got.get("ok") else
                    ("AI_BACKUP_PENDING" if awaiting_backup else "NONE")),
                "route_ai_backup": route_backup,
                "program_first_ai_review": {"status": "PENDING"},
                "ai_repair_required": False,
                "awaiting_ai_review": bool(got.get("ok")),
                "awaiting_ai_backup": awaiting_backup,
                "awaiting_ai": bool(got.get("ok") or awaiting_backup),
            }
            review_task = None
            backup_task = None
            if got.get("ok"):
                review_task = _make_ai_review_task(
                    pid, proj, got, verdict, rc, run_p, "PROGRAM")
                result["review_task"] = review_task["review_path"]
                p1 = (phases.get("phase1_routing") or {})
                p1["needs_ai_parse_consumed_by"] = (
                    "blind Program First AI review at "
                    f"{review_task['review_path']}")
            elif awaiting_backup:
                backup_task = _make_ai_backup_task(
                    pid, proj, backup_skills, str(backup_source),
                    backup_detail, bench, ds, run_p)
            state = ("candidate->AI-review" if got.get("ok")
                     else ("WAIVE->AI" if backup_source == "rtl_gen_waive"
                           else ("route-declared->AI" if awaiting_backup
                                 else "no-rtl")))
            log_line = (f"  {pid:44s} {nature:22s} entry={str(entry):3s} "
                        f"exit={str(exit_step):4s} rc={rc} {state}")
            return _SolveWorkerOutcome(
                index=index, problem_id=pid,
                result_json=json.dumps(result),
                review_task_json=(json.dumps(review_task)
                                  if review_task else None),
                backup_task_json=(json.dumps(backup_task)
                                  if backup_task else None),
                log_line=log_line)
        except Exception as exc:                          # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            result = {
                "id": pid,
                "nature": nature, "entry": entry,
                "evidence": ev, "exit": exit_step, "rc": None,
                "worker_status": "ERROR", "worker_error": error,
                "worker_retryable": (
                    proj / "input" / "phase1_prompt.md").is_file(),
                "ok": False, "candidate_ready": False, "accepted": False,
                "staged": staged_chars,
                "completeness": "NOT_MEASURED: WORKER_ERROR",
                "routing_verdict": verdict,
                "phases": _phase_error_attribution(),
                "candidate_origin": "NONE", "route_ai_backup": {
                    "status": "NOT_MEASURED", "skills": []},
                "program_first_ai_review": {"status": "NOT_MEASURED"},
                "ai_repair_required": False,
                "awaiting_ai_review": False,
                "awaiting_ai_backup": False, "awaiting_ai": False,
            }
            return _SolveWorkerOutcome(
                index=index, problem_id=pid,
                result_json=json.dumps(result),
                review_task_json=None, backup_task_json=None,
                log_line=(f"  {pid:44s} NOT_MEASURED worker ERROR: {error}"))

    outcomes = _ordered_parallel_map(problem_rows, _solve_one, jobs)
    results: list[dict] = []
    backlog: list[dict] = []
    review_tasks: list[dict] = []
    for outcome in outcomes:
        result = json.loads(outcome.result_json)
        results.append(result)
        if outcome.review_task_json:
            review_tasks.append(json.loads(outcome.review_task_json))
        if outcome.backup_task_json:
            backlog.append(json.loads(outcome.backup_task_json))
        print(outcome.log_line)

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
        print(f"\n{len(backlog)} problem(s) handed to a declared AI skill -> {bl}")
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
            "rule": ("runner-owned RTL gate PASS (or supplied-RTL re-entry), "
                     "exact overall runner rc preserved, blocking sole-emit "
                     "compile/guards PASS, AND blind AI semantic PASS; AI route "
                     "may AGREE or evidence-backed OVERRIDE_PROGRAM"),
            "semantic_authority": "AI",
            "program_disagreement": (
                "AI must prove the issue with a prompt-derived executable test "
                "that the frozen Program candidate fails; repair must pass the "
                "same immutable test, runner-owned RTL gate, blocking sole-emit "
                "compile/guards, and a fresh AI review"),
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
          + (f", {waiting} awaiting AI review/backup" if waiting else "")
          + f" -> {run_p}/solve_report.json")
    # 2 = handed off, not failed. Even when every PROGRAM candidate exists, no
    # response is accepted until the blind AI review agrees.
    return 2 if results and waiting == len(results) else 1


def cmd_solve(bench: str, dataset: str, run: str, limit: int = 0,
              jobs: int = 1, heavy_jobs: int | None = None,
              worker_threads: int = 0) -> int:
    """Run the sole solve coordinator under an exclusive run-root lock."""
    try:
        with _run_root_coordinator_lock(Path(run), "solve"):
            return _cmd_solve_locked(
                bench, dataset, run, limit=limit, jobs=jobs,
                heavy_jobs=heavy_jobs, worker_threads=worker_threads)
    except _CoordinatorBusy as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _cmd_resume_locked(bench: str, dataset: str, run: str,
                       jobs: int = 1, heavy_jobs: int | None = None,
                       worker_threads: int = 0) -> int:
    """Advance Program First / AI Review work and publish only acceptances.

    PROGRAM emits first. A runner WAIVE or a valid route-level declaration may
    authorise AI backup for a missing initial candidate. Every gated candidate
    then receives a blind AI route + semantic review. AI may reject only with a
    prompt-derived test that the frozen candidate actually fails; a repair must
    pass that same immutable test plus PROGRAM gates and a fresh review. A
    changed prompt is never legitimised by refresh.
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
    policy = solve.get("acceptance_policy") or {}
    if (policy.get("required") is not True
            or policy.get("review_task_schema") != _REVIEW_TASK_SCHEMA
            or policy.get("review_schema") != _AI_REVIEW_SCHEMA):
        print("ERROR: this solve predates the current Program First + AI Review "
              "proof schemas; start a fresh --solve run", file=sys.stderr)
        return 2
    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        print(f"ERROR: no IO adapter bound for {bench!r}", file=sys.stderr)
        return 2
    runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"
    runner_budget = _RunnerBudget(jobs, heavy_jobs, worker_threads)

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

    def _run_and_collect(job) -> _ResumeRunnerOutcome:
        pid, proj, supplied_rtl, entry, exit_step = job
        # AI backup/repair has already authored the candidate. Re-enter at the
        # first RTL-validation step so program-first does not author again and
        # overwrite the hash whose semantics the AI just repaired. The routed
        # exit still applies; otherwise resume expands a step-2/4 task into LEC.
        argv = _resume_solver_argv(
            runner, proj, supplied_rtl, entry, exit_step)
        process = runner_budget.run(argv)
        if process.error is not None:
            return _ResumeRunnerOutcome(
                problem_id=pid, rc=None, collected_json=None,
                error=process.error)
        try:
            got = bio.collect(fmt, pid, proj, supplied_rtl=supplied_rtl)
            payload = json.dumps(got)
        except Exception as exc:                          # noqa: BLE001
            return _ResumeRunnerOutcome(
                problem_id=pid, rc=process.rc, collected_json=None,
                error=f"{type(exc).__name__}: {exc}")
        return _ResumeRunnerOutcome(
            problem_id=pid, rc=process.rc, collected_json=payload, error=None)

    def _refresh_result(result: dict, proj: Path, rc: int, got: dict) -> None:
        routing = result.get("routing_verdict") or {}
        phases = fpa.attribute(
            proj, routing=routing, entry=result.get("entry"),
            evidence=result.get("evidence"), exit_step=result.get("exit"),
            rtl_present=fpa.rtl_present_at_input(proj),
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
        result.pop("worker_status", None)
        result.pop("worker_error", None)
        result.pop("worker_retryable", None)

    repairs: list[dict] = []
    remaining_backup: list[dict] = []
    refreshed: set[str] = set()
    enhancement_by_key = {
        (str(row.get("id")), str(row.get("prompt_sha256")),
         str(row.get("rtl_sha256")), str(row.get("semantic_verdict"))): row
        for row in prior_enhancements
    }

    # A process-level worker error is not converted into a design verdict.
    # The staged project stays in the run root and --resume retries exactly
    # that Program invocation; successful projects already committed in the
    # solve report are never discarded or re-authored.
    retry_plans = []
    for result in results:
        if (result.get("worker_status") == "ERROR"
                and result.get("worker_retryable") is True):
            pid = str(result.get("id"))
            retry_plans.append({
                "id": pid, "result": result,
                "project": (run_p / "projects" /
                            re.sub(r"[^\w.-]", "_", pid)),
            })
    retry_outcomes = _ordered_parallel_map(
        [(p["id"], p["project"], False, p["result"].get("entry"),
          p["result"].get("exit"))
         for p in retry_plans], _run_and_collect, jobs)
    existing_backup_ids = {str(item.get("id")) for item in backup}
    for plan, outcome in zip(retry_plans, retry_outcomes):
        pid = plan["id"]
        result = plan["result"]
        proj = plan["project"]
        if outcome.error is not None:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROJECT_WORKER_ERROR",
                "reasons": [outcome.error],
                "required_next": (
                    "fix the named worker failure and run --resume again; "
                    "other coordinator-committed project results are retained"),
            })
            result.update({"rc": None, "worker_status": "ERROR",
                           "worker_error": outcome.error})
            print(f"  {pid:44s} Program worker retry ERROR: {outcome.error}")
            continue
        rc = int(outcome.rc)
        got = json.loads(str(outcome.collected_json))
        _refresh_result(result, proj, rc, got)
        if got.get("ok"):
            task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, "PROGRAM")
            task_by_id[pid] = task
            result.update({
                "review_task": task["review_path"],
                "candidate_origin": "PROGRAM",
                "awaiting_ai_review": True, "awaiting_ai": True,
            })
            refreshed.add(pid)
            print(f"  {pid:44s} Program worker retry completed; "
                  "fresh AI review required")
            continue
        waive = _rtl_gen_waive(proj)
        route_backup = _declared_route_ai_backup(
            result.get("routing_verdict") or {})
        backup_source = None
        backup_skills: list[str] = []
        backup_detail = ""
        if waive:
            backup_source = "rtl_gen_waive"
            backup_skills = [str(waive.get("fallback_skill"))]
            backup_detail = str(waive.get("detail") or "")
        elif route_backup["status"] == "DECLARED":
            backup_source = "route_declaration"
            backup_skills = list(route_backup["skills"])
            backup_detail = str(got.get("reason") or "")
        result.update({
            "route_ai_backup": route_backup,
            "candidate_origin": (
                "AI_BACKUP_PENDING" if backup_source else "NONE"),
            "awaiting_ai_backup": bool(backup_source),
            "awaiting_ai_review": False,
            "awaiting_ai": bool(backup_source),
        })
        if backup_source and pid not in existing_backup_ids:
            backup.append(_make_ai_backup_task(
                pid, proj, backup_skills, str(backup_source), backup_detail,
                bench, Path(dataset).resolve(), run_p))
            existing_backup_ids.add(pid)
        print(f"  {pid:44s} Program worker retry completed (rc={rc})")

    # AI backup is authorised only by its recorded WAIVE/route declaration.
    # The coordinator validates every handoff first, workers run only unique
    # projects, and the coordinator applies their immutable outcomes in the
    # original worklist order.
    backup_plans: list[dict] = []
    for item in backup:
        pid = str(item.get("id"))
        result = result_by_id.get(pid)
        proj = Path(str(item.get("project") or ""))
        if result is None:
            backup_plans.append({
                "kind": "invalid", "item": item, "id": pid,
                "repair": {"id": pid, "status": "INVALID_HANDOFF",
                           "reasons": [
                               "backup id is absent from solve_report"]},
            })
            continue
        prompt = proj / "input" / "phase1_prompt.md"
        expected_prompt_hash = item.get("prompt_sha256")
        try:
            current_prompt_hash = _sha256_text(
                prompt.read_text(errors="replace"))
        except OSError as exc:
            current_prompt_hash = None
            prompt_reason = f"staged prompt is unreadable: {exc}"
        else:
            prompt_reason = "staged prompt differs from the handoff-bound hash"
        if (not isinstance(expected_prompt_hash, str)
                or len(expected_prompt_hash) != 64
                or current_prompt_hash != expected_prompt_hash):
            status = ("PROMPT_CHANGED" if expected_prompt_hash
                      and current_prompt_hash is not None
                      else "INVALID_BACKUP_HANDOFF")
            backup_plans.append({
                "kind": "prompt_error", "item": item, "id": pid,
                "result": result, "status": status,
                "repair": {
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj), "status": status,
                "reasons": [prompt_reason],
                "required_next": (
                    "restore the exact staged prompt and start a fresh "
                    "--solve handoff; do not re-gate this backup"),
                },
            })
            continue
        rtl_dir = proj / "phase2" / "stage1" / "rtl"
        authored = rtl_dir.is_dir() and (list(rtl_dir.glob("*.sv"))
                                         + list(rtl_dir.glob("*.v")))
        if not authored:
            backup_plans.append({
                "kind": "no_rtl", "item": item, "id": pid,
                "result": result,
            })
            continue
        backup_plans.append({
            "kind": "run", "item": item, "id": pid, "result": result,
            "project": proj, "rtl_dir": rtl_dir,
        })

    backup_run_plans = [p for p in backup_plans if p["kind"] == "run"]
    backup_outcomes = iter(_ordered_parallel_map(
        [(p["id"], p["project"], True, None, p["result"].get("exit"))
         for p in backup_run_plans],
        _run_and_collect, jobs))
    for plan in backup_plans:
        kind = plan["kind"]
        pid = plan["id"]
        item = plan["item"]
        if kind == "invalid":
            repairs.append(plan["repair"])
            continue
        result = plan["result"]
        if kind == "prompt_error":
            repairs.append(plan["repair"])
            result.update({"accepted": False, "candidate_origin": "NONE",
                           "awaiting_ai_backup": False,
                           "awaiting_ai_review": False,
                           "awaiting_ai": False})
            print(f"  {pid:44s} AI backup blocked: {plan['status']}")
            continue
        if kind == "no_rtl":
            remaining_backup.append(item)
            result.update({"accepted": False, "awaiting_ai_backup": True,
                           "awaiting_ai_review": False, "awaiting_ai": True})
            print(f"  {pid:44s} AI backup still has no authored RTL")
            continue
        outcome = next(backup_outcomes)
        if outcome.error is not None:
            remaining_backup.append(item)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(plan["project"]),
                "status": "PROJECT_WORKER_ERROR",
                "reasons": [outcome.error],
                "required_next": (
                    "fix the named worker failure and run --resume again; "
                    "other coordinator-committed project results are retained"),
            })
            result.update({
                "rc": None, "worker_status": "ERROR",
                "worker_error": outcome.error, "accepted": False,
                "candidate_ready": False, "awaiting_ai_backup": True,
                "awaiting_ai_review": False, "awaiting_ai": True,
                "ai_repair_required": False,
            })
            print(f"  {pid:44s} AI backup worker ERROR: {outcome.error}")
            continue
        rc = int(outcome.rc)
        got = json.loads(str(outcome.collected_json))
        proj = plan["project"]
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
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROGRAM_GATES_REJECTED_AI_BACKUP",
                "reasons": [str(got.get("reason") or "runner rejected RTL")],
                "write_rtl_to": str(plan["rtl_dir"]),
                "resume_with": (f"benchmark_dispatch.py {bench} --resume "
                                f"--dataset {dataset} --run {run_p}"),
            })
            result.update({"awaiting_ai_backup": True,
                           "awaiting_ai_review": False,
                           "awaiting_ai": True,
                           "ai_repair_required": True})
            print(f"  {pid:44s} AI backup rejected by PROGRAM gates (rc={rc})")

    # AI repair is authorised only after the frozen candidate demonstrably
    # failed a prompt-derived test.  Validation remains coordinator-owned;
    # only the independent project runner calls fan out.
    repair_plans: list[dict] = []
    for pid, task in list(task_by_id.items()):
        if pid in refreshed:
            repair_plans.append({"kind": "noop", "id": pid})
            continue
        result = result_by_id.get(pid)
        if result is None:
            repair_plans.append({
                "kind": "report", "id": pid,
                "repair": {"id": pid, "status": "INVALID_REVIEW_TASK",
                           "reasons": [
                               "review id is absent from solve_report"]},
            })
            continue
        pre_logs: list[str] = []
        review_path = Path(str(task.get("review_path") or ""))
        if (task.get("candidate_origin") == "AI_REPAIR"
                and not review_path.is_file()):
            final_provenance, final_provenance_reasons = \
                _refresh_final_repair_provenance(task)
            if final_provenance_reasons:
                result.update({"accepted": False, "awaiting_ai": True,
                               "awaiting_ai_review": False,
                               "ai_repair_required": True})
                repair_plans.append({
                    "kind": "report", "id": pid,
                    "log": f"  {pid:44s} final gated RTL needs AI provenance",
                    "repair": {
                        "schema": "vibeic.benchmark.ai_repair_task.v2",
                        "id": pid, "project": task.get("project"),
                        "status": "AI_REPAIR_FINAL_PROVENANCE_REQUIRED",
                        "reasons": final_provenance_reasons,
                        "repair_record_path": (task.get("repair_provenance")
                                               or {}).get("path"),
                        "program_parent_rtl_sha256":
                            (task.get("program_candidate_snapshot")
                             or {}).get("rtl_sha256"),
                        "final_repaired_rtl_sha256": task.get("rtl_sha256"),
                    },
                })
                continue
            task["repair_provenance"] = final_provenance
            result.update({"awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": False})
            pre_logs.append(f"  {pid:44s} final AI repair provenance rebound")
        prompt_hash, _, _, _ = _current_task_material(task)
        if prompt_hash != task.get("prompt_sha256"):
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": task.get("project"),
                    "status": "PROMPT_CHANGED",
                    "reasons": [
                        "restore the original prompt; it cannot be refreshed"],
                },
            })
            continue
        proj = Path(str(task.get("project") or ""))
        working_paths = _rtl_files(proj)
        try:
            working_hash = (_sha256_text(_candidate_text(working_paths))
                            if working_paths else None)
        except OSError:
            working_hash = None
        if working_hash == task.get("rtl_sha256"):
            repair_plans.append({
                "kind": "noop", "id": pid, "pre_logs": pre_logs})
            continue
        prior_verdict = _validate_ai_review(task)
        challenge = prior_verdict.get("verified_challenge")
        if prior_verdict.get("status") != "REPAIR_REQUIRED" or not challenge:
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": False})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "log": (f"  {pid:44s} changed RTL rejected: "
                        "AI issue is unproven"),
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": str(proj),
                    "status": "UNPROVEN_AI_EDIT_REJECTED",
                    "reasons": [
                        "working RTL changed before an AI finding was proven "
                        "by a prompt-derived executable verification test",
                        *[str(v) for v in prior_verdict.get("reasons") or []],
                    ],
                    "restore_from": (task.get("candidate_snapshot") or {}).get(
                        "manifest_path"),
                },
            })
            continue
        repair_record_path = _repair_record_path(run_p, task)
        repair_provenance, provenance_reasons = _validate_repair_record(
            repair_record_path, task, str(working_hash), challenge)
        if provenance_reasons:
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": True})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "log": f"  {pid:44s} changed RTL needs AI repair provenance",
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": str(proj),
                    "status": "AI_REPAIR_PROVENANCE_REQUIRED",
                    "reasons": provenance_reasons,
                    "repair_record_path": str(repair_record_path),
                    "reviewed_rtl_sha256": task.get("rtl_sha256"),
                    "repaired_rtl_sha256": working_hash,
                    "challenge_sha256": challenge.get("sha256"),
                },
            })
            continue
        repair_plans.append({
            "kind": "run", "id": pid, "pre_logs": pre_logs,
            "task": task, "result": result, "project": proj,
            "challenge": challenge, "repair_provenance": repair_provenance,
            "program_first_phases": (
                result.get("program_first_phases")
                or result.get("phases") or {}),
        })

    repair_run_plans = [p for p in repair_plans if p["kind"] == "run"]
    repair_outcomes = iter(_ordered_parallel_map(
        [(p["id"], p["project"], True, None, p["result"].get("exit"))
         for p in repair_run_plans],
        _run_and_collect, jobs))
    for plan in repair_plans:
        for line in plan.get("pre_logs") or []:
            print(line)
        if plan["kind"] == "noop":
            continue
        if plan["kind"] == "report":
            repairs.append(plan["repair"])
            if plan.get("log"):
                print(plan["log"])
            continue
        pid = plan["id"]
        task = plan["task"]
        result = plan["result"]
        proj = plan["project"]
        outcome = next(repair_outcomes)
        if outcome.error is not None:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROJECT_WORKER_ERROR",
                "reasons": [outcome.error],
                "required_next": (
                    "fix the named worker failure and run --resume again; "
                    "other coordinator-committed project results are retained"),
            })
            result.update({
                "rc": None, "worker_status": "ERROR",
                "worker_error": outcome.error, "accepted": False,
                "awaiting_ai": True, "awaiting_ai_review": False,
                "ai_repair_required": True,
            })
            print(f"  {pid:44s} AI repair worker ERROR: {outcome.error}")
            continue
        rc = int(outcome.rc)
        got = json.loads(str(outcome.collected_json))
        _refresh_result(result, proj, rc, got)
        program_first_phases = plan["program_first_phases"]
        if program_first_phases:
            result["program_first_phases"] = program_first_phases
            result.setdefault("phases", {})["phase2_solving"] = \
                program_first_phases.get("phase2_solving", {})
            result["phases"]["phase4_debugging"] = \
                program_first_phases.get("phase4_debugging", {})
        if got.get("ok"):
            inherited = list(task.get("verification_challenges") or [])
            inherited.append(plan["challenge"])
            new_task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, "AI_REPAIR",
                verification_challenges=inherited,
                program_candidate=(task.get("program_candidate_snapshot")
                                   or task.get("candidate_snapshot")),
                repair_parent_candidate=task.get("candidate_snapshot"),
                repair_provenance=plan["repair_provenance"])
            task_by_id[pid] = new_task
            result["review_task"] = new_task["review_path"]
            result["candidate_origin"] = "AI_REPAIR"
            result["ai_repair_required"] = False
            print(f"  {pid:44s} changed RTL re-gated; fresh AI review required")
        else:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": str(proj),
                "status": "PROGRAM_GATES_REJECTED_AI_REPAIR",
                "reasons": [str(got.get("reason") or "runner rejected RTL")],
                "write_rtl_to": str(proj / "phase2" / "stage1" / "rtl"),
            })
            result["ai_repair_required"] = True
            print(f"  {pid:44s} changed RTL rejected by PROGRAM gates (rc={rc})")

    accepted_ids: list[str] = []
    review_outcomes: list[dict] = []
    not_measured: list[dict] = []
    for pid, result in result_by_id.items():
        task = task_by_id.get(pid)
        if task is None:
            result["accepted"] = False
            continue
        verdict = _validate_ai_review(task)
        _attach_ai_review_attribution(result, verdict, task)
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
        if verdict["status"] == _NOT_MEASURED:
            # Not accepted -- nothing was established, so nothing is scored --
            # but this is NOT a repair task and NOT an AI failure. It waits on
            # the HOST, and it says so in its own row rather than borrowing
            # the vocabulary of a defect.
            not_measured.append({
                "schema": "vibeic.benchmark.ai_review_not_measured.v1",
                "id": pid, "project": task.get("project"),
                "status": _NOT_MEASURED,
                "reasons": verdict.get("unmeasurable") or [],
                "decision_reasons": verdict.get("decision_reasons") or [],
                "review_path": task.get("review_path"),
                "reviewed_rtl_sha256": task.get("rtl_sha256"),
                "required_next": (
                    "install the missing capability on this host and re-run "
                    "--resume; do not re-author RTL on the strength of a test "
                    "that did not run"),
            })
            result.update({"accepted": False, "awaiting_ai": False,
                           "awaiting_ai_review": False,
                           "ai_repair_required": False,
                           "not_measured": True})
            print(f"  {pid:44s} NOT_MEASURED -- this host cannot run the "
                  f"verification challenge")
            continue
        if verdict["status"] != "ACCEPTED":
            needs_repair = verdict["status"] == "REPAIR_REQUIRED"
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": not needs_repair,
                           "ai_repair_required": needs_repair})
            if needs_repair:
                result["ai_repair_required"] = True
                repairs.append({
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": task.get("project"),
                    "status": "AI_SEMANTIC_REPAIR_REQUIRED",
                    "reasons": (verdict.get("decision_reasons") or [])
                               + [str(v) for v in
                                  verdict.get("semantic_findings_detail") or []],
                    "review_path": task.get("review_path"),
                    "reviewed_rtl_sha256": task.get("rtl_sha256"),
                    "verified_challenge": verdict.get("verified_challenge"),
                    "challenge_result": verdict.get("challenge_result"),
                    "repair_record_path": str(
                        _repair_record_path(run_p, task)),
                    "repair_record_requirements": {
                        "schema": _AI_REPAIR_RECORD_SCHEMA,
                        "id": pid,
                        "prompt_sha256": task.get("prompt_sha256"),
                        "parent_rtl_sha256": task.get("rtl_sha256"),
                        "repaired_rtl_sha256":
                            "sha256 of the corrected working RTL",
                        "challenge_sha256":
                            (verdict.get("verified_challenge") or {}).get(
                                "sha256"),
                        "author": {"kind": "AI", "model": "required"},
                        "oracle_accessed": False,
                        "rationale": "required",
                    },
                    "verified_prompt_evidence":
                        (verdict.get("override") or {}).get(
                            "verified_prompt_evidence") or [],
                    "verified_semantic_prompt_evidence":
                        verdict.get("verified_semantic_prompt_evidence") or [],
                    "write_rtl_to": str(
                        Path(str(task.get("project"))) /
                        "phase2" / "stage1" / "rtl"),
                    "required_next": (
                        "author corrected RTL that passes verified_challenge, "
                        "write the hash-bound AI repair record, run --resume "
                        "for PROGRAM gates and the SAME challenge, then submit "
                        "a fresh AI review for the new hash"),
                })
            continue
        supplied_rtl = result.get("candidate_origin") in {
            "AI_BACKUP", "AI_REPAIR"}
        got = bio.collect(
            fmt, pid, Path(str(task.get("project") or "")),
            supplied_rtl=supplied_rtl)
        if (not got.get("ok")
                or _sha256_text(str(got.get("completion") or ""))
                != task.get("rtl_sha256")):
            reasons = ["current PROGRAM-gated completion does not match the "
                       "AI-reviewed RTL hash"]
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "ACCEPTED_REVIEW_MATERIAL_MISMATCH",
                "reasons": reasons,
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": True})
            continue
        if task.get("candidate_origin") == "AI_REPAIR":
            recovery = _verified_program_recovery(task, result, verdict)
            enhancement_by_key[(
                pid, str(task.get("prompt_sha256")),
                str(task.get("rtl_sha256")), "VERIFIED_RECOVERY",
            )] = recovery
        payload_path = Path(str((task.get("candidate_snapshot") or {}).get(
            "response_payload_path") or ""))
        try:
            frozen_payload = json.loads(payload_path.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError) as exc:
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "FROZEN_RESPONSE_PAYLOAD_INVALID",
                "reasons": [str(exc)],
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": False})
            continue
        _atomic_write_json(Path(task["response_path"]), frozen_payload)
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
        "not_measured": len(not_measured),
        "not_measured_detail": not_measured,
        "pending_review": sum(1 for o in review_outcomes
                              if o.get("status") in {"PENDING", "REJECTED"}),
        "program_enhancement_candidates": len(enhancements),
    }
    _atomic_write_json(run_p / _ACCEPTANCE_REPORT, acceptance)
    if not_measured:
        print(f"\n{len(not_measured)}/{total} NOT_MEASURED: this host could not "
              f"run the verification challenge, so those reviews were neither "
              f"proven nor disproven. This is a host capability gap, not a "
              f"finding about the candidates.")
    print(f"\n{len(accepted_ids)}/{total} Program First + AI Review accepted; status "
          f"{acceptance['status']} -> {run_p / _ACCEPTANCE_REPORT}")
    if complete:
        return 0
    return 2 if (remaining_backup or repairs or ordered_tasks) else 1


def cmd_resume(bench: str, dataset: str, run: str, jobs: int = 1,
               heavy_jobs: int | None = None,
               worker_threads: int = 0) -> int:
    """Run the sole resume coordinator under an exclusive run-root lock."""
    try:
        with _run_root_coordinator_lock(Path(run), "resume"):
            return _cmd_resume_locked(
                bench, dataset, run, jobs=jobs, heavy_jobs=heavy_jobs,
                worker_threads=worker_threads)
    except _CoordinatorBusy as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bench", nargs="?", help="benchmark name (see --list)")
    ap.add_argument("--list", action="store_true", help="list known benchmarks")
    ap.add_argument("--show", action="store_true",
                    help="print the full registry entry for <bench> (#532)")
    ap.add_argument("--score", action="store_true", help="invoke the scorer on an existing run dir")
    ap.add_argument("--solve", action="store_true",
                    help="SOLVE the benchmark through the general flow. This is "
                         "the verb that closes the old scaffold-to-score gap: "
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
                         "allowed only after a prompt-derived executable test "
                         "proves the frozen candidate wrong, then is re-gated "
                         "and must pass the same test plus fresh AI review; "
                         f"repeat until {_ACCEPTANCE_REPORT} is COMPLETE.")
    ap.add_argument("--limit", type=int, default=0,
                    help="with --solve: stop after N problems (0 = all)")
    ap.add_argument("--dataset", help="dataset path on disk")
    ap.add_argument("--run", help="run dir")
    ap.add_argument("--jobs", type=int, default=1,
                    help="with --solve/--resume: bounded project workers "
                         "(default 1 preserves serial behaviour)")
    ap.add_argument("--heavy-jobs", type=int, default=None,
                    help="with --solve/--resume: maximum concurrent runner "
                         "heavy slots (default: --jobs)")
    ap.add_argument("--worker-threads", type=int, default=0,
                    help="with --solve/--resume: EDA threads per worker; 0 "
                         "auto-budgets host CPUs (serial default is unchanged)")
    ap.add_argument("--scorer-root",
                    help="with CVDP --score: directory containing the official "
                         "run_benchmark.py (or set CVDP_BENCHMARK_ROOT)")
    ap.add_argument("--threads", type=int, default=4,
                    help="with CVDP --score: official scorer worker count "
                         "(default 4)")
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
    if a.score:
        if not a.run:
            raise SystemExit("--score requires --run")
        cmd_score(a.bench, a.run, a.dataset,
                  allow_ungated=a.allow_ungated,
                  allow_direct_agent=a.allow_direct_agent,
                  capture_golden=a.capture_golden,
                  ai_model=a.ai_model,
                  golden_db=a.golden_db,
                  scorer_root=a.scorer_root,
                  threads=a.threads)
        return
    if a.resume:
        if not (a.dataset and a.run):
            raise SystemExit("--resume requires --dataset and --run")
        sys.exit(cmd_resume(
            a.bench, a.dataset, a.run, jobs=a.jobs,
            heavy_jobs=a.heavy_jobs, worker_threads=a.worker_threads))
    if a.solve:
        if not (a.dataset and a.run):
            raise SystemExit("--solve requires --dataset and --run")
        sys.exit(cmd_solve(
            a.bench, a.dataset, a.run, limit=a.limit, jobs=a.jobs,
            heavy_jobs=a.heavy_jobs, worker_threads=a.worker_threads))
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
