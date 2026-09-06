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
import argparse, atexit, hashlib, json, os, shutil, subprocess, sys, tempfile
import concurrent.futures
import contextlib
import fcntl
import re
import signal
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


def _own_child_pids() -> list[int]:
    """This process's DIRECT children, from /proc. Never a name pattern.

    Every lane on this fleet runs the same script names, so matching by name
    is how one run kills another's work. Kernel-reported children of THIS pid
    are the only honest population.
    """
    pids: list[int] = []
    try:
        tasks = list(Path(f"/proc/{os.getpid()}/task").iterdir())
    except OSError:
        return pids
    for task in tasks:
        try:
            raw = (task / "children").read_text()
        except OSError:
            continue
        pids.extend(int(tok) for tok in raw.split() if tok.isdigit())
    return sorted(set(pids))


def _kill_live_runner_groups(sig: int = signal.SIGTERM) -> int:
    """Signal each live runner's process GROUP. Returns how many were signalled.

    MEASURED 2026-09-06 (RTLLM run, finding BR-07): killing
    `benchmark_dispatch --solve` left 21 runner processes running for about 15
    minutes against an abandoned run dir, at host load 22+. A pool that
    outlives the run it belongs to burns a shared machine on work nobody will
    read.

    The GROUP, not the child: the runner spawns its own tools, and signalling
    only the direct child leaves exactly the grandchildren BR-07 observed.
    Every runner is started with `start_new_session=True`, so each child is
    its own group leader and `killpg(child_pid)` reaches its whole subtree.
    """
    own = os.getpgrp()
    signalled = 0
    for pid in _own_child_pids():
        try:
            pgid = os.getpgid(pid)
        except OSError:
            continue
        # NEVER our own group. If a child ever failed to get a session of its
        # own, its "group" is the coordinator's, and signalling it would kill
        # the coordinator and everything sharing its terminal -- turning a
        # cleanup into the outage it exists to prevent.
        if pgid == own:
            continue
        try:
            os.killpg(pgid, sig)
            signalled += 1
        except (ProcessLookupError, PermissionError, OSError):
            continue
    return signalled


_ORPHAN_GUARD_INSTALLED = False


def _install_orphan_guard() -> None:
    """Take the worker pool down with the coordinator. Idempotent.

    Covers SIGTERM, SIGINT and SIGHUP, and normal or exceptional exit. It does
    NOT cover SIGKILL, which runs no handler: surviving `kill -9` needs
    PR_SET_PDEATHSIG on each child, and the only way to set it from CPython is
    `preexec_fn`, which the standard library documents as unsafe in the
    presence of threads -- and this pool IS threads. Trading a possible
    fork-time deadlock in every solve for the -9 case is not a trade this
    makes silently; the limit is stated instead.

    Call it from the MAIN THREAD. `signal.signal` refuses anywhere else, and
    the pool's workers are threads -- installing it only from `run()` would
    leave the atexit half alone, which SIGTERM does not reach. MEASURED: with
    the thread-only install, SIGINT took the pool down (CPython turns it into
    KeyboardInterrupt, so atexit runs) and SIGTERM did not.
    """
    global _ORPHAN_GUARD_INSTALLED                       # noqa: PLW0603
    if _ORPHAN_GUARD_INSTALLED:
        return
    _ORPHAN_GUARD_INSTALLED = True
    atexit.register(_kill_live_runner_groups)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            previous = signal.getsignal(sig)
        except (ValueError, OSError):
            continue

        def handler(signum, frame, _previous=previous):
            _kill_live_runner_groups()
            if callable(_previous) and _previous not in (
                    signal.SIG_IGN, signal.SIG_DFL):
                return _previous(signum, frame)
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
            return None

        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            # Not the main thread, or the platform refuses: the atexit half
            # still stands, and nothing is claimed that is not installed.
            continue


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
        """Run ONE runner invocation in its own SESSION.

        `start_new_session` is what lets the coordinator take the whole pool
        with it: each child becomes its own process-group leader, so
        `killpg(child_pid)` reaches the tools the runner started rather than
        just the runner. Without it, killing the coordinator leaves the pool
        running -- the orphaned 21 processes measured in BR-07.

        This stays `subprocess.run`, deliberately. It is the seam the existing
        suite fakes the runner at; moving to `Popen` silently bypassed every
        one of those fakes and invoked the real runner, which is a far worse
        failure than the one being fixed.
        """
        _install_orphan_guard()
        kwargs = {"capture_output": True, "text": True,
                  "start_new_session": True}
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
_REVIEW_TASK_SCHEMA = "vibeic.benchmark.ai_review_task.v3"
_AI_REVIEW_SCHEMA = "vibeic.benchmark.ai_review.v2"
_ACCEPTANCE_SCHEMA = "vibeic.benchmark.program_first_ai_review.v3"
_CANDIDATE_SCHEMA = "vibeic.benchmark.candidate_snapshot.v1"
_CHALLENGE_SCHEMA = "vibeic.benchmark.ai_verification_challenge.v1"
_CHALLENGE_SUPERSESSION_SCHEMA = \
    "vibeic.benchmark.challenge_supersession.v1"
_AI_REPAIR_RECORD_SCHEMA = "vibeic.benchmark.ai_repair_record.v1"
_REVIEW_WORKLIST = "needs_ai_review.jsonl"
_BACKUP_WORKLIST = "needs_ai_backup.jsonl"
_REPAIR_WORKLIST = "needs_ai_repair.jsonl"
_ENHANCEMENT_WORKLIST = "program_enhancement_candidates.jsonl"
_ACCEPTANCE_REPORT = "program_first_ai_review_acceptance.json"
_REVIEW_CORRECTION_SCHEMA = "vibeic.benchmark.ai_review_correction.v1"
_PROGRAM_REGATE_SCHEMA = "vibeic.benchmark.program_regate.v1"
_PRE_GATE_INPUT_SCHEMA = "vibeic.benchmark.pre_gate_input.v1"

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


def _review_obligation_id(item: dict) -> str:
    """Stable identity for one Program-extracted review obligation."""
    material = json.dumps({
        "kind": str(item.get("kind") or ""),
        "requirement": str(item.get("requirement") or ""),
        "evidence": str(item.get("evidence") or ""),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(material)[:16]


def _program_review_obligation_contract(prompt_text: str,
                                        candidate: dict) -> dict:
    """Extract the structural minimum an AI PASS test must cover.

    ``spec_coverage_check`` is the existing benchmark-agnostic Program reader.
    This adapter does not invent a second extractor: it turns that reader's
    exact block-eligible items into a hash-bound handoff for AI Backup.
    """
    import spec_coverage_check as coverage                 # noqa: PLC0415

    rtl_text = _candidate_text(
        [Path(str(p)) for p in candidate.get("rtl_paths") or []])
    report = coverage.run(
        {"user_prompt": prompt_text}, rtl_text, None, None, True)
    obligations = []
    for item in report.get("items") or []:
        if not item.get("block_eligible", True):
            continue
        row = {
            "kind": item.get("kind"),
            "requirement": item.get("requirement"),
            "evidence": item.get("evidence"),
            "coverage_tokens": item.get("coverage_tokens") or [],
        }
        row["id"] = _review_obligation_id(row)
        obligations.append(row)
    core = {
        "schema": "vibeic.benchmark.program_review_obligations.v1",
        "actor": "programs/spec_coverage_check.py",
        "policy": "BLOCKING_STRUCTURAL_MINIMUM",
        "obligation_count": len(obligations),
        "obligations": obligations,
    }
    return {
        **core,
        "sha256": _sha256_text(json.dumps(
            core, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))),
    }


def _program_review_coverage_result(prompt_text: str, candidate: dict,
                                    challenges: list[dict]) -> dict:
    """Measure active AI tests against Program's structural obligations."""
    import spec_coverage_check as coverage                 # noqa: PLC0415

    rtl_text = _candidate_text(
        [Path(str(p)) for p in candidate.get("rtl_paths") or []])
    test_parts = []
    for challenge in challenges:
        path = Path(str(challenge.get("path") or ""))
        text = path.read_text(errors="replace")
        if _sha256_text(text) != challenge.get("sha256"):
            raise ValueError(
                f"active verification challenge hash changed at {path}")
        test_parts.append(text)
    report = coverage.run(
        {"user_prompt": prompt_text}, rtl_text,
        "\n\n".join(test_parts), None, True)
    gaps = []
    for item in report.get("items") or []:
        if item.get("covered") is not False \
                or not item.get("block_eligible", True):
            continue
        row = {
            "kind": item.get("kind"),
            "requirement": item.get("requirement"),
            "evidence": item.get("evidence"),
            "coverage_tokens": item.get("coverage_tokens") or [],
            "coverage_note": item.get("coverage_note"),
        }
        row["id"] = _review_obligation_id(row)
        gaps.append(row)
    return {
        "schema": "vibeic.benchmark.program_review_coverage.v1",
        "actor": "programs/spec_coverage_check.py",
        "status": "PASS" if not gaps else "FAIL",
        "active_challenge_sha256": [c.get("sha256") for c in challenges],
        "checklist_items": report.get("checklist_items"),
        "covered": report.get("covered"),
        "coverage_gaps": report.get("coverage_gaps"),
        "blocking_gaps": report.get("blocking_gaps"),
        "blocking_gap_items": gaps,
    }


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
                       run_p: Path, candidate_origin: str, *,
                       archive_key: str | None = None) -> dict:
    """Freeze the exact gated candidate before an AI can edit the work tree."""
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    source_paths = _rtl_files(project)
    completion = str(got.get("completion") or "")
    rtl_hash = _sha256_text(completion)
    safe = _safe_problem_id(problem_id)
    origin = _safe_problem_id(archive_key or candidate_origin).lower()
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


def _program_version() -> str:
    """The running Program's own version, or "" when the manifest is unreadable.

    An empty string is reported as-is. A retry that cannot name which Program
    produced which bytes is not evidence, and a default would invent one.
    """
    from l_doc_generator_stamp import plugin_version     # noqa: PLC0415
    try:
        return str(plugin_version() or "")
    except Exception:                                    # noqa: BLE001
        return ""


def _pre_gate_input_root(run_p: Path, problem_id: str, signed_hash: str) -> Path:
    return (Path(run_p).resolve() / "pre_gate_inputs"
            / _safe_problem_id(problem_id) / str(signed_hash))


def _archive_pre_gate_input(run_p: Path, problem_id: str,
                            source_paths: list[Path], signed_hash: str) -> dict:
    """Freeze the exact SIGNED bytes the PROGRAM gates are about to consume.

    The gates may normalize this RTL in place, and that overwrite destroys the
    only copy of what the author actually signed. When a later Program fix
    changes the transform there is then nothing to re-enter FROM: the frozen
    output is unwanted, and re-signing it would attribute a Program mutation to
    the author. Preserving the input at this boundary makes the pair
    (signed input sha, gate output sha) a recorded fact rather than something
    reconstructed after the fact.

    Immutable: a second call with the same bytes is a no-op, and different
    bytes under the same hash raise rather than overwrite.
    """
    root = _pre_gate_input_root(run_p, problem_id, signed_hash)
    frozen: list[str] = []
    for index, source in enumerate(source_paths):
        target = root / "rtl" / f"{index:02d}_{source.name}"
        _write_immutable_text(target, source.read_text(errors="replace"))
        frozen.append(str(target.resolve()))
    record = {
        "schema": _PRE_GATE_INPUT_SCHEMA,
        "id": str(problem_id),
        "rtl_sha256": str(signed_hash),
        "rtl_paths": frozen,
        "source_rtl_paths": [str(Path(p).resolve()) for p in source_paths],
        "program_version": _program_version(),
    }
    manifest = root / "manifest.json"
    record["manifest_path"] = str(manifest.resolve())
    _write_immutable_json(manifest, record)
    return record


def _bind_pre_gate_output(preserved: dict, output_hash: str) -> dict:
    """Record the (signed input -> gate output) pair the gates just produced.

    One immutable file per pair, so which Program turned which signed input
    into which frozen output is readable later without re-running anything.
    """
    record = {
        "schema": _PRE_GATE_INPUT_SCHEMA,
        "id": str(preserved.get("id")),
        "signed_input_sha256": str(preserved.get("rtl_sha256")),
        "gate_output_sha256": str(output_hash),
        "input_manifest_path": str(preserved.get("manifest_path")),
        "program_version": _program_version(),
    }
    path = (Path(str(preserved["manifest_path"])).parent
            / f"gate_output_{output_hash}.json")
    _write_immutable_json(path, record)
    return {**record, "binding_path": str(path.resolve())}


def _preserved_input_paths(preserved: dict) -> list[Path]:
    return [Path(str(p)) for p in preserved.get("rtl_paths") or []]


def _pre_gate_input_manifest(regate: dict) -> dict | None:
    """The preserved signed-input manifest a regate names, or None.

    None means "could not read it or it does not verify" -- never an empty
    default. The bytes on disk must still hash to the signed input hash the
    record claims, or the record describes something that is no longer there.
    """
    path = Path(str((regate or {}).get("input_manifest_path") or ""))
    try:
        preserved = json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(preserved, dict) \
            or preserved.get("schema") != _PRE_GATE_INPUT_SCHEMA:
        return None
    signed = str(preserved.get("rtl_sha256") or "")
    if signed != str(regate.get("signed_input_sha256") or ""):
        return None
    paths = _preserved_input_paths(preserved)
    if not paths or not all(q.is_file() for q in paths):
        return None
    try:
        if _sha256_text(_candidate_text(paths)) != signed:
            return None
    except OSError:
        return None
    return preserved


def _verified_program_regate(task: dict) -> dict | None:
    """The regate record ONLY if every one of its bindings still holds.

    Returns None -- leaving every existing refusal exactly as it was -- unless
    the task carries a complete `program_regate` whose preserved input is still
    on disk with the signed bytes, whose recorded new output is this task's own
    frozen candidate, and whose Program version actually moved. A record that
    fails ANY of these is not evidence and is treated as absent.
    """
    regate = task.get("program_regate")
    if not isinstance(regate, dict):
        return None
    if regate.get("schema") != _PROGRAM_REGATE_SCHEMA:
        return None
    signed = str(regate.get("signed_input_sha256") or "")
    produced = str(regate.get("new_output_sha256") or "")
    before = str(regate.get("program_version_before") or "")
    after = str(regate.get("program_version_after") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", signed):
        return None
    if produced != str(task.get("rtl_sha256") or ""):
        return None
    if not before or not after or before == after:
        return None
    preserved = _pre_gate_input_manifest(regate)
    if preserved is None or str(preserved.get("id")) != str(task.get("id")):
        return None
    # The named "before" version is not decoration: it must be the Program
    # that actually produced the preserved input.
    if before != str(preserved.get("program_version") or ""):
        return None
    return regate


def _signed_candidate_hash(task: dict) -> str:
    """The hash an AI repair author's signature is required to cover.

    Normally the frozen candidate itself: the author signs the bytes that were
    reviewed. After a VERIFIED Program re-entry the author's bytes are the
    preserved signed INPUT instead -- the Program, not the author, produced the
    difference, so requiring the author's signature over the Program's output
    would attribute a Program mutation to the author. With no verified regate
    record this is `task["rtl_sha256"]`, exactly as before.
    """
    regate = _verified_program_regate(task)
    if regate is None:
        return str(task.get("rtl_sha256") or "")
    return str(regate.get("signed_input_sha256") or "")


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


def _archive_repair_input(problem_id: str, project: Path, run_p: Path,
                          provenance: dict) -> dict:
    """BLOCKING: preserve and revalidate signed input before Program can edit it."""
    candidate = _archive_candidate(problem_id, project, {
        "id": problem_id, "ok": True,
        "completion": _candidate_text(_rtl_files(project))}, run_p, "AI_REPAIR_INPUT")
    if (candidate["rtl_sha256"] != provenance.get("repaired_rtl_sha256")
            or _validate_candidate_snapshot(candidate, problem_id)):
        raise ValueError("AI_REPAIR_INPUT_REFUSED: signed input changed before Program gates")
    return candidate


def _make_ai_review_task(problem_id: str, project: Path, got: dict,
                         routing: dict, runner_rc: int, run_p: Path,
                         candidate_origin: str, *,
                         program_phases: dict | None = None,
                         verification_challenges: list[dict] | None = None,
                         program_candidate: dict | None = None,
                         repair_parent_candidate: dict | None = None,
                         repair_provenance: dict | None = None,
                         repair_input_candidate: dict | None = None,
                         review_key: str | None = None,
                         archive_key: str | None = None) -> dict:
    """Build the hash-bound, oracle-free handoff for one AI review."""
    project, run_p = Path(project).resolve(), Path(run_p).resolve()
    prompt = project / "input" / "phase1_prompt.md"
    paths = _rtl_files(project)
    completion = str(got.get("completion") or "")
    if not prompt.is_file() or not paths or not got.get("ok") or not completion:
        raise ValueError("cannot request AI review without prompt + gated RTL")
    safe = _safe_problem_id(problem_id)
    candidate = _archive_candidate(
        problem_id, project, got, run_p, candidate_origin, archive_key=archive_key)
    if candidate_origin == "PROGRAM":
        program_candidate = candidate
    import emit_attestation as emit_attestation          # noqa: PLC0415
    phase1_provenance = emit_attestation.phase1_provenance(project)
    challenges = verification_challenges or []
    review_key = review_key or (f"{_safe_problem_id(candidate_origin).lower()}-"
                               f"r{len(challenges)}-{candidate['rtl_sha256']}")
    challenge_dir = (run_p / "ai_verification_challenges" / safe /
                     review_key)
    challenge_file = str((challenge_dir / "challenge_tb.sv").resolve())
    prompt_sha = _sha256_text(prompt.read_text(errors="replace"))
    program_review_obligations = _program_review_obligation_contract(
        prompt.read_text(errors="replace"), candidate)
    evidence_item_shape = {
        "excerpt": ("<exact prompt excerpt; at least 8 characters and a "
                    "whitespace-normalized substring of prompt_path>"),
        "supports": "<the claim it supports; at least 12 characters>",
    }
    phase3 = ((program_phases or {}).get("phase3_verifying") or {})
    ran = phase3.get("ran") if isinstance(phase3.get("ran"), dict) else {}
    not_attempted = (phase3.get("not_attempted")
                     if isinstance(phase3.get("not_attempted"), dict) else {})
    functional_evidence = ran.get("step4_functional_evidence")
    functional_source = "phase3_verifying.ran.step4_functional_evidence"
    if functional_evidence is None:
        functional_evidence = not_attempted.get("step4_functional_evidence")
        functional_source = (
            "phase3_verifying.not_attempted.step4_functional_evidence")
    if functional_evidence is None:
        functional_evidence = "NOT_RECORDED"
        functional_source = "no step4_functional_evidence record"
    confirmation_required = functional_evidence != "PASS"

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
        **({"repair_input_candidate_snapshot": repair_input_candidate}
           if repair_input_candidate is not None else {}),
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
            "functional_evidence": functional_evidence,
            "functional_evidence_source": functional_source,
            "functional_confirmation_required": confirmation_required,
        },
        "program_review_obligations": program_review_obligations,
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
                    "_required_when": (
                        "semantic_review.verdict is FAIL, OR semantic_review."
                        "verdict is PASS while program_verification."
                        "functional_confirmation_required is true; write the "
                        "test file to the task challenge_path"),
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
                "challenge_supersessions": [{
                    "_optional_when": (
                        "a fresh semantic PASS proves that an inherited "
                        "challenge contradicts the prompt; verification_test "
                        "must be a replacement test that PASSES this candidate. "
                        "The named challenge must ALSO validly FAIL, or be "
                        "structurally INVALID on, THIS candidate: a challenge "
                        "that still PASSES is not blocking acceptance, so it "
                        "must not be named here, and naming one rejects the "
                        "whole review. Name each inherited challenge at most "
                        "once, and the replacement must be a DIFFERENT test "
                        "from the one it replaces"),
                    "schema": _CHALLENGE_SUPERSESSION_SCHEMA,
                    "challenge_sha256": "<exact inherited challenge sha256>",
                    "rationale": (
                        "<why the old assertion is defective; at least 80 "
                        "characters>"),
                    "prompt_evidence": [dict(evidence_item_shape)],
                }],
            },
            "blind_inputs_only": [
                "prompt_path",
                "rtl_paths",
                ("verification_challenges only when correcting a defective "
                 "inherited test; never scorer/golden/oracle bytes"),
            ],
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
            "semantic_pass_action": (
                "When PROGRAM has no PASS functional evidence, a semantic PASS "
                "must include a self-contained prompt-derived executable test "
                "at challenge_path. The frozen candidate must PASS that test, "
                "and the current plus inherited active tests must cover every "
                "block-eligible item in program_review_obligations; one passing "
                "example is not whole-spec confirmation. An unrunnable test is "
                "NOT_MEASURED and a failing or coverage-incomplete test cannot "
                "authorize acceptance."),
            "semantic_pass_verification_test": {
                "required": confirmation_required,
                "required_result_on_reviewed_candidate": "PASS",
                "required_program_coverage": "ALL_BLOCKING_OBLIGATIONS",
                "program_review_obligations_sha256": (
                    program_review_obligations["sha256"]),
                "reason": ("PROGRAM step4_functional_evidence is "
                           f"{functional_evidence!r}"),
                "blind_source": "prompt_path only",
            },
            "semantic_fail_verification_test": {
                "schema": _CHALLENGE_SCHEMA,
                "path": challenge_file,
                "top_module": "vibeic_ai_challenge_tb",
                "required_result_on_reviewed_candidate": "FAIL",
                "required_result_on_repair": "PASS",
                "pass_marker": "VIBEIC_AI_CHALLENGE=PASS",
                "fail_marker": "VIBEIC_AI_CHALLENGE=FAIL",
                "marker_form": (
                    "both markers are checked against the challenge SOURCE "
                    "TEXT: each must appear in the file as a LITERAL string. "
                    "A format string such as $display(\"VIBEIC_AI_CHALLENGE"
                    "=%s\", ok ? \"PASS\" : \"FAIL\") prints the marker "
                    "correctly at run time and still contains neither "
                    "literal, so it is rejected; write one $display per "
                    "marker with the marker spelled out"),
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


def _refresh_program_review_obligations(task: dict) -> bool:
    """Refresh only the deterministic contract of an unchanged review task.

    ``program_review_obligations`` is derived by Program from the prompt and
    frozen candidate. A Program upgrade may correct that derivation while a
    long benchmark run is awaiting AI review. The validator intentionally
    compares against the current derivation, so leaving the old value in the
    task creates an impossible state: the task is rejected, but ``--resume``
    previously had no way to replace the stale Program-owned field.

    Refresh is allowed only when every authority-bearing input is still bound
    to its original hash and the candidate snapshot is intact. The prior
    contract is retained in the task for audit. AI verdicts, prompt evidence,
    tests, and RTL are never changed here; newly added obligations therefore
    still require coverage and cannot be silently accepted.
    """
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        return False
    prompt_hash, rtl_hash, stated, current = _current_task_material(task)
    if (stated != current
            or prompt_hash != task.get("prompt_sha256")
            or rtl_hash != task.get("rtl_sha256")
            or _validate_candidate_snapshot(
                task.get("candidate_snapshot") or {},
                str(task.get("id")))):
        return False
    prompt_path = Path(str(task.get("prompt_path") or ""))
    try:
        prompt_text = prompt_path.read_text(errors="replace")
        expected = _program_review_obligation_contract(
            prompt_text, task.get("candidate_snapshot") or {})
    except (ImportError, OSError, ValueError):
        return False
    prior = task.get("program_review_obligations")
    if prior == expected:
        return False
    refreshes = task.setdefault("program_review_obligation_refreshes", [])
    if not isinstance(refreshes, list):
        return False
    refreshes.append({
        "schema": "vibeic.benchmark.program_review_obligations_refresh.v1",
        "basis": "UNCHANGED_HASH_BOUND_PROMPT_AND_CANDIDATE",
        "prior_contract": prior,
        "replacement_sha256": expected.get("sha256"),
    })
    task["program_review_obligations"] = expected
    return True


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
    pre-gate signature must not silently authorize different bytes. Let the AI
    explicitly re-sign the final hash at the same evidence path, even when a
    review already exists. This only refreshes provenance; the unchanged review
    must still pass its normal hash, snapshot, and challenge validation.
    Missing or invalid final provenance remains BLOCKING.
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
        path, parent_task, _signed_candidate_hash(task), challenge)


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
    if provenance.get("repaired_rtl_sha256") != _signed_candidate_hash(task):
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

#: `//` to end of line, and `/* ... */` including newlines. Applied before the
#: forbidden-construct scan so a COMMENT cannot decide the verdict.
_CHALLENGE_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


_TIMESCALE = re.compile(
    r"`timescale\s*(\d+)\s*([munpf]?s)\s*/\s*(\d+)\s*([munpf]?s)")


def _challenge_forbidden_hit(source: str):
    """The forbidden-construct scan, run on CODE rather than on raw text.

    MEASURED 2026-09-06, RTLLM clean-room run. Ten reviews were rejected with
    `verification test is not self-contained` while every one of the ten
    challenge files was clean. The reviewer had written the header comment the
    contract asks for --

        // Self-contained: no `include, no $readmem, no file/system/DPI access.

    -- and that COMMENT contains the literal tokens the pattern looks for, so a
    test was rejected for DECLARING its compliance. Stripping comments made all
    ten clean, and the pattern still catches the real constructs.

    A guard that a comment can flip is not a guard: editing prose must never
    change a verdict about code. Comments are removed first; string literals are
    deliberately NOT removed, because `$readmemh("f.hex", m)` is a real call and
    a path inside a string is exactly what makes it one.
    """
    return _CHALLENGE_FORBIDDEN.search(_CHALLENGE_COMMENT.sub(" ", source or ""))


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
                           prompt_text: str, *,
                           required_for: str = "semantic FAIL"
                           ) -> tuple[dict | None, list[str]]:
    """Validate and freeze an AI-authored prompt-only executable challenge."""
    raw = review.get("verification_test")
    reasons: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"{required_for} requires verification_test"]
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
    if _challenge_forbidden_hit(source):
        reasons.append("verification test is not self-contained")
    if "module vibeic_ai_challenge_tb" not in source:
        reasons.append("verification test must define vibeic_ai_challenge_tb")
    # These are SOURCE-TEXT checks, and the reason has to say so. A challenge
    # written as `$display("VIBEIC_AI_CHALLENGE=%s", bad ? "FAIL" : "PASS")`
    # prints the marker perfectly at run time and is still rejected here,
    # because neither literal appears in the file. Telling its author the test
    # "must print" a marker it demonstrably does print sends them to debug the
    # wrong thing; naming the literal-vs-format-string distinction is the whole
    # remedy.
    _MARKER_FIX = (" as a LITERAL in the source (a $display format string such "
                   "as \"VIBEIC_AI_CHALLENGE=%s\" prints correctly at run time "
                   "but contains neither literal; use one $display per marker)")
    if "VIBEIC_AI_CHALLENGE=PASS" not in source:
        reasons.append("verification test must contain VIBEIC_AI_CHALLENGE=PASS"
                       + _MARKER_FIX)
    if "VIBEIC_AI_CHALLENGE=FAIL" not in source:
        reasons.append("verification test must contain VIBEIC_AI_CHALLENGE=FAIL"
                       + _MARKER_FIX)
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


def _challenge_supersessions_from_review(
        task: dict, review: dict, prompt_text: str,
        replacement: dict | None) -> tuple[list[dict], list[str]]:
    """Validate explicit corrections to defective inherited challenges.

    BLOCKING: an inherited proof remains immutable and active unless a fresh
    blind AI semantic PASS names its exact hash, cites the prompt, and supplies
    a different executable replacement test that passes the current candidate.
    The old proof stays in the audit result as SUPERSEDED; malformed, missing,
    passing, or unrunnable targets never disappear silently.
    """
    raw = review.get("challenge_supersessions")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["challenge_supersessions must be a list"]
    inherited = {
        str(item.get("sha256") or ""): item
        for item in task.get("verification_challenges") or []
        if isinstance(item, dict)
    }
    reasons: list[str] = []
    records: list[dict] = []
    seen: set[str] = set()
    replacement_hash = str((replacement or {}).get("sha256") or "")
    for index, item in enumerate(raw):
        prefix = f"challenge_supersessions[{index}]"
        if not isinstance(item, dict):
            reasons.append(f"{prefix} must be an object")
            continue
        if item.get("schema") != _CHALLENGE_SUPERSESSION_SCHEMA:
            reasons.append(
                f"{prefix}.schema must be {_CHALLENGE_SUPERSESSION_SCHEMA!r}")
        target = str(item.get("challenge_sha256") or "")
        if target not in inherited:
            reasons.append(f"{prefix} must name an inherited challenge sha256")
        if target in seen:
            reasons.append(f"{prefix} repeats a challenge sha256")
        seen.add(target)
        rationale = str(item.get("rationale") or "").strip()
        if len(rationale) < 80:
            reasons.append(f"{prefix}.rationale must be at least 80 characters")
        evidence = _verified_prompt_evidence(
            item.get("prompt_evidence") or [], prompt_text)
        if not evidence:
            reasons.append(f"{prefix} needs prompt-bound evidence")
        if not replacement_hash:
            reasons.append(f"{prefix} needs an executable replacement test")
        elif replacement_hash == target:
            reasons.append(f"{prefix} replacement test must differ from target")
        if (target in inherited and target not in {
                r.get("challenge_sha256") for r in records}
                and len(rationale) >= 80 and evidence and replacement_hash
                and replacement_hash != target):
            records.append({
                "schema": _CHALLENGE_SUPERSESSION_SCHEMA,
                "challenge_sha256": target,
                "replacement_challenge_sha256": replacement_hash,
                "rationale": rationale,
                "prompt_evidence": evidence,
            })
    return records, reasons


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


def _declared_timescale(source: str) -> str | None:
    """The `timescale a source DECLARES, normalized, or None.

    Read from the source text, never guessed. Comments are stripped first, for
    the same reason `_challenge_forbidden_hit` strips them: a directive that is
    commented out is prose, and prose must not decide a verdict about code.
    The FIRST declaration is the one in force at the top of the file, which is
    what "the declared unit" means for the modules that follow it.
    """
    match = _TIMESCALE.search(_CHALLENGE_COMMENT.sub(" ", source or ""))
    if match is None:
        return None
    return f"{match.group(1)}{match.group(2)}/{match.group(3)}{match.group(4)}"


def _timescale_disagreement(rtl_paths: list[str], declared: str | None) -> str | None:
    """A candidate/challenge pair whose declared timescales DISAGREE.

    With one declared unit the prelude makes every module share it. With two
    different ones there is no single answer to impose, and which one wins
    would go back to depending on compile order -- so this is refused by name
    rather than decided silently.
    """
    for path in rtl_paths:
        try:
            found = _declared_timescale(Path(path).read_text(errors="replace"))
        except OSError:
            continue
        if found is not None and declared is not None and found != declared:
            return (f"candidate and challenge declare different timescales: "
                    f"{Path(path).name} declares {found}, the challenge "
                    f"declares {declared}")
    return None


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
    if _challenge_forbidden_hit(source):
        return {"status": "INVALID",
                "reasons": ["challenge is not self-contained"]}
    iverilog, vvp = shutil.which("iverilog"), shutil.which("vvp")
    if not iverilog or not vvp:
        return {"status": "UNAVAILABLE", "reasons": ["iverilog/vvp unavailable"]}
    rtl_paths = [str(Path(p)) for p in candidate.get("rtl_paths") or []]
    # ARGUMENT ORDER IS NOT A VERDICT INPUT. `timescale is a compiler
    # directive that applies from its point of appearance FORWARD, across
    # files, in compile order. A candidate with no `timescale of its own
    # therefore inherits the challenge's unit when the challenge is compiled
    # first, and iverilog's default when it is compiled first -- MEASURED
    # 2026-09-06 on a correct clkgenerator candidate: RTL-first FAIL,
    # TB-first PASS, and the runner reported "the frozen candidate must pass
    # its required test" about a candidate that was right. A verdict that
    # argument order can flip is not a verdict.
    #
    # The fix states the DECLARED unit once, ahead of every source, so all of
    # them share it whatever order they are given in. It is never guessed:
    # with no declaration anywhere there is no prelude and every file keeps
    # the same default, which is already order-independent.
    declared = _declared_timescale(source)
    disagreement = _timescale_disagreement(rtl_paths, declared)
    if disagreement is not None:
        return {"status": "INVALID", "reasons": [disagreement]}
    with tempfile.TemporaryDirectory(prefix="vibeic-ai-challenge-") as td:
        out = Path(td) / "simv"
        prelude = []
        if declared is not None:
            prelude_path = Path(td) / "_vibeic_timescale.v"
            prelude_path.write_text(f"`timescale {declared}\n")
            prelude = [str(prelude_path)]
        try:
            comp = subprocess.run(
                [iverilog, "-g2012", "-s", "vibeic_ai_challenge_tb",
                 "-o", str(out), *prelude, *rtl_paths, str(test_path)],
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
    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        reasons.append("candidate snapshot record is malformed")
        candidate = {}
    reasons.extend(_validate_candidate_snapshot(
        candidate, str(task.get("id"))))
    reasons.extend(_validate_embedded_repair_provenance(task))
    try:
        expected_obligations = _program_review_obligation_contract(
            prompt_text, candidate)
    except (ImportError, OSError, ValueError) as exc:
        expected_obligations = None
        reasons.append(
            "Program review obligations could not be derived: "
            f"{type(exc).__name__}: {exc}")
    if expected_obligations is not None \
            and task.get("program_review_obligations") != expected_obligations:
        reasons.append(
            "program_review_obligations are missing, stale, or differ from "
            "the current prompt and frozen candidate")

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
    # ``or {}`` only launders a FALSY non-dict: a truthy ``"not-an-object"``
    # or ``7`` survived it and reached ``.get()`` as an AttributeError, which
    # is the one outcome a fail-closed guard must never produce -- a BLOCKED
    # exit is legible, a traceback out of the acceptance predicate is not.
    program_verification = task.get("program_verification")
    if not isinstance(program_verification, dict):
        if program_verification is not None:
            reasons.append("Program verification record is malformed")
        program_verification = {}
    functional_evidence = program_verification.get("functional_evidence")
    confirmation_required = program_verification.get(
        "functional_confirmation_required")
    if not isinstance(confirmation_required, bool):
        reasons.append(
            "program_verification.functional_confirmation_required must be boolean")
        confirmation_required = True
    if confirmation_required != (functional_evidence != "PASS"):
        reasons.append(
            "functional confirmation requirement contradicts Program evidence")
    #: Reasons this host could not ADJUDICATE, kept apart from `reasons`, which
    #: are findings against the review or the candidate. The two must never be
    #: mixed: one says "this is wrong", the other says "we did not look".
    unmeasurable: list[str] = []
    raw_supersessions = review.get("challenge_supersessions")
    supersession_requested = (
        isinstance(raw_supersessions, list) and bool(raw_supersessions))
    if semantic_verdict == "FAIL":
        challenge, challenge_reasons = _challenge_from_review(
            task, review, prompt_text)
        reasons.extend(challenge_reasons)
        if challenge is not None:
            challenge_result = _run_verification_challenge(
                candidate, challenge)
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
    elif (semantic_verdict == "PASS"
          and (confirmation_required or supersession_requested)):
        challenge, challenge_reasons = _challenge_from_review(
            task, review, prompt_text,
            required_for=(
                "challenge supersession replacement"
                if supersession_requested
                else "semantic PASS without Program functional evidence"))
        reasons.extend(challenge_reasons)
        if challenge is not None:
            challenge_result = _run_verification_challenge(
                candidate, challenge)
            if challenge_result.get("status") == _CHALLENGE_UNAVAILABLE:
                unmeasurable.append(
                    "the prompt-derived PASS confirmation could not be RUN on "
                    "this host, so the candidate is not functionally measured: "
                    + "; ".join(str(r) for r in
                                challenge_result.get("reasons") or []))
            elif challenge_result.get("status") != "PASS":
                reasons.append(
                    "AI semantic PASS is not confirmed: the frozen candidate "
                    "must pass its required prompt-derived verification test")
    challenge_supersessions, supersession_reasons = \
        _challenge_supersessions_from_review(
            task, review, prompt_text, challenge)
    reasons.extend(supersession_reasons)
    if challenge_supersessions and semantic_verdict != "PASS":
        reasons.append(
            "challenge supersession requires a fresh AI semantic PASS")
    supersession_authorized = (
        semantic_verdict == "PASS"
        and (challenge_result or {}).get("status") == "PASS"
        and not supersession_reasons)
    supersession_by_hash = ({
        item["challenge_sha256"]: item
        for item in challenge_supersessions
    } if supersession_authorized else {})
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
        result = _run_verification_challenge(candidate, inherited)
        supersession = supersession_by_hash.get(
            str(inherited.get("sha256") or ""))
        if supersession is not None:
            if result.get("status") == _CHALLENGE_UNAVAILABLE:
                unmeasurable.append(
                    "a challenge named for supersession could not be RUN on "
                    "this host, so its alleged defect was not measured: "
                    + "; ".join(str(r) for r in
                                result.get("reasons") or []))
            elif result.get("status") in {"FAIL", "INVALID"}:
                result = {
                    **result,
                    "status": "SUPERSEDED",
                    "original_status": result.get("status"),
                    "supersession": supersession,
                }
            else:
                reasons.append(
                    "a challenge named for supersession must validly FAIL or "
                    "be structurally INVALID on the current candidate before "
                    "it can be corrected; this one still PASSES, which means "
                    "it is not blocking acceptance and does not need to be "
                    "named -- drop it from challenge_supersessions")
            inherited_challenge_results.append(result)
            continue
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
        elif (result.get("status") == "INVALID"
              and semantic_verdict == "FAIL"
              and (challenge_result or {}).get("status") == "FAIL"):
            # A broken older test must not deadlock an independently proven
            # repair.  This does NOT waive, supersede, or accept the invalid
            # challenge: it remains visible and is carried to the next fresh
            # review, where semantic PASS is still blocked until the AI
            # supplies a prompt-bound passing replacement.  The only action
            # authorised here is another repair of a candidate that already
            # failed a different, fresh, executable prompt-derived test.
            result["nonblocking_during_proven_repair"] = True
            result["required_on_fresh_review"] = True
        elif result.get("status") != "PASS":
            reasons.append("repair does not pass every immutable verification "
                           "test that proved its parent candidate wrong")
    program_review_coverage = None
    if (semantic_verdict == "PASS" and confirmation_required
            and (challenge_result or {}).get("status") == "PASS"):
        active_challenges = [challenge] if challenge is not None else []
        for inherited, result in zip(
                task.get("verification_challenges") or [],
                inherited_challenge_results):
            if result.get("status") == "PASS":
                active_challenges.append(inherited)
        try:
            program_review_coverage = _program_review_coverage_result(
                prompt_text, candidate, active_challenges)
        except (ImportError, OSError, ValueError) as exc:
            unmeasurable.append(
                "Program could not measure AI verification-test coverage: "
                f"{type(exc).__name__}: {exc}")
        else:
            if program_review_coverage.get("status") != "PASS":
                gap_ids = [str(item.get("id")) for item in
                           program_review_coverage.get(
                               "blocking_gap_items") or []]
                reasons.append(
                    "AI semantic PASS leaves structural prompt obligation(s) "
                    "uncovered by its active executable tests: "
                    + ", ".join(gap_ids))
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
            "challenge_supersessions": challenge_supersessions,
            "program_review_coverage": program_review_coverage,
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
            "program_functional_evidence": (
                task.get("program_verification") or {}).get(
                    "functional_evidence"),
            "functional_confirmation_required": (
                task.get("program_verification") or {}).get(
                    "functional_confirmation_required"),
            "functional_confirmation_result": (
                verdict.get("challenge_result") or {}).get("status"),
            "functional_confirmation_challenge_sha256": (
                verdict.get("verified_challenge") or {}).get("sha256"),
            "program_review_coverage": verdict.get(
                "program_review_coverage"),
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
    """Bind a Shape-C review task back to its runner-owned run evidence.

    This is BLOCKING: any returned reason prevents scorer export.
    """
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
    # A supplied-RTL re-entry does not *run* the upstream owner; attribution
    # correctly records it under not_attempted as SKIPPED-BY-ENTRY. Looking
    # only in ``ran`` made every repaired/backup candidate fail export even
    # though the task and solve report carried the same honest gate status.
    if recorded_rtl_gen is None:
        not_attempted = phase3.get("not_attempted")
        if not isinstance(not_attempted, dict):
            reasons.append("solve_report skipped Program gate record is malformed")
            not_attempted = {}
        recorded_rtl_gen = not_attempted.get("rtl_gen")
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
    import rtl_final_bundle_integrity as bundle_integrity  # noqa: PLC0415

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
        bundle_gate = None
        if not reasons:
            try:
                completion = bio.cvdp_package_response(
                    [Path(str(p)) for p in candidate.get("rtl_paths") or []],
                    [Path(str(p)) for p in
                     candidate.get("source_rtl_paths") or []],
                    response_paths)
            except (OSError, ValueError, TypeError) as exc:
                reasons.append(str(exc))
        if not reasons:
            final_files = bio.cvdp_response_file_map(
                completion, response_paths)
            bundle_gate = bundle_integrity.check_final_bundle(
                [Path(str(p)) for p in candidate.get("rtl_paths") or []],
                final_files)
            bundle_report_path = (run_p / "reports" /
                                  "final_bundle_integrity" /
                                  f"{_safe_problem_id(pid)}.json")
            _atomic_write_json(bundle_report_path, bundle_gate)
            if bundle_gate.get("status") != "PASS":
                detail = "; ".join(
                    str(value) for value in bundle_gate.get("reasons") or [])
                if not detail:
                    detail = str(
                        (bundle_gate.get("compile") or {}).get("reason")
                        or "no compile evidence")
                reasons.append(
                    "general final RTL bundle integrity is "
                    f"{bundle_gate.get('status')}: "
                    f"{detail}")
        if reasons:
            failures.append(f"{pid}: " + "; ".join(reasons))
            continue
        rows.append({"id": pid, "completion": completion})
        evidence.append({
            "id": pid,
            "candidate_rtl_sha256": task.get("rtl_sha256"),
            "scorer_completion_sha256": _sha256_text(completion),
            "response_paths": response_paths,
            "final_bundle_integrity": {
                "status": bundle_gate.get("status"),
                "report": str(bundle_report_path),
                "report_sha256": _sha256_text(
                    bundle_report_path.read_text(errors="replace")),
            },
            "gates": ["vibe_ic_one_shot_runner",
                      "program_first_ai_review",
                      "cvdp_thin_io_package",
                      "rtl_final_bundle_integrity"],
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


def _ensure_phase1_frontdoor(runner: Path, project: Path, runner_budget) -> dict:
    """Materialize canonical Phase-1 provenance before a mid-flow entry.

    This prerequisite is BLOCKING: missing or mutable provenance must stop the
    owning loop instead of silently producing a non-canonical benchmark sample.

    Routing still decides the task's owning loop first. A debug/optimization
    task may therefore *solve* from a later step, but it must not bypass the
    one Phase-1 front door that binds its prompt to L-doc provenance. The
    D1-only pass is accepted by its produced provenance rather than the broad
    runner rc: Phase 1 may honestly return nonzero for an outstanding expert
    handoff after it has emitted all hash-bound L-docs.
    """
    import emit_attestation as emit_attestation          # noqa: PLC0415

    project = Path(project).resolve()
    existing = emit_attestation.phase1_provenance(project)
    if existing.get("ran") is True:
        return {"status": "REUSED", "runner_rc": None,
                "provenance": existing}

    prompt = project / "input" / "phase1_prompt.md"
    try:
        prompt_before = _sha256_text(prompt.read_text(errors="replace"))
        rtl_before = _sha256_text(_candidate_text(_rtl_files(project)))
    except OSError as exc:
        return {"status": "BLOCKED", "runner_rc": None,
                "reason": f"front-door input is unreadable: {exc}"}

    argv = _solver_argv(runner, project, "D1", "D1")
    argv.append("--no-dashboard")
    process = runner_budget.run(argv)
    if process.error is not None:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": process.error}
    try:
        prompt_after = _sha256_text(prompt.read_text(errors="replace"))
        rtl_after = _sha256_text(_candidate_text(_rtl_files(project)))
    except OSError as exc:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": f"front-door output is unreadable: {exc}"}
    if prompt_before != prompt_after or rtl_before != rtl_after:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": "D1-only front door changed the prompt or supplied RTL"}
    provenance = emit_attestation.phase1_provenance(project)
    if provenance.get("ran") is not True:
        return {"status": "BLOCKED", "runner_rc": process.rc,
                "reason": "D1-only front door emitted no hash-bound L-doc provenance"}
    return {"status": "GENERATED", "runner_rc": process.rc,
            "provenance": provenance}


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
        # Two facts a failing row must still report. The route-level
        # AI-backup declaration is a pure function of the routing verdict, so
        # it is known the moment routing returns; the Phase-1 front door's
        # verdict is known the moment it returns. Both live outside the try so
        # that a later failure -- a BLOCKED front door, a runner error --
        # reports the declaration it actually classified (UNDECLARED, INVALID
        # or DECLARED) and the front door that stopped it, instead of stamping
        # NOT_MEASURED over a determinate answer. NOT_MEASURED survives only
        # when the worker died before routing: the one case nobody looked.
        route_backup: dict = {"status": "NOT_MEASURED", "skills": []}
        phase1_frontdoor = None
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
            route_backup = _declared_route_ai_backup(verdict)

            if entry != "D1":
                phase1_frontdoor = _ensure_phase1_frontdoor(
                    runner, proj, runner_budget)
                if phase1_frontdoor.get("status") == "BLOCKED":
                    raise RuntimeError(
                        "canonical Phase-1 front door failed before routed "
                        f"entry {entry}: {phase1_frontdoor.get('reason')}")

            process = runner_budget.run(
                _solver_argv(runner, proj, entry, exit_step))
            if process.error is not None:
                raise RuntimeError(process.error)
            rc = int(process.rc)
            got = bio.collect(fmt, pid, proj)
            waive = _rtl_gen_waive(proj)
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
                "phase1_frontdoor": phase1_frontdoor,
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
                    pid, proj, got, verdict, rc, run_p, "PROGRAM",
                    program_phases=phases)
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
                "phase1_frontdoor": phase1_frontdoor,
                "candidate_origin": "NONE",
                "route_ai_backup": route_backup,
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

    refreshed_obligation_ids = [
        pid for pid, task in task_by_id.items()
        if _refresh_program_review_obligations(task)
    ]
    if refreshed_obligation_ids:
        print("  refreshed deterministic review obligations for "
              f"{len(refreshed_obligation_ids)} unchanged candidate(s): "
              + ", ".join(refreshed_obligation_ids))

    # Old mid-flow runs could route debug/optimization correctly yet skip the
    # canonical Phase-1 provenance pass altogether. Repair that missing
    # program evidence before any candidate is (re-)accepted. A provenance
    # record that once existed and later changed is never regenerated here;
    # that is tampering/staleness and remains blocking.
    #
    # THE REFUSAL IS SCOPED TO ACCEPTANCE, WHICH IS WHAT #2012 SAID.
    # This pass used to `return 2` for the WHOLE run the moment any candidate
    # came up short, before a single repair or backup task had been written.
    # "A candidate must not be ACCEPTED without canonical Phase-1 provenance"
    # and "no candidate in this run may be routed" are different statements,
    # and only the first one is the invariant. Measured consequences of the
    # second, all three on origin/main sources:
    #   * a --resume whose results are all still awaiting AI backup returned 2
    #     with an EMPTY needs_ai_repair.jsonl and needs_ai_backup.jsonl -- the
    #     worklists the AI half of the loop reads;
    #   * one worker crashing took the HEALTHY sibling's routing down with it,
    #     because that sibling's own provenance was equally absent;
    #   * a candidate whose review had already come back REPAIR_REQUIRED was
    #     never routed for repair, so the loop had no way forward at all.
    # The blocked candidates are recorded here and refused AT THE ACCEPT SITE
    # below, which is the single place `accepted` is ever set True.
    import emit_attestation as emit_attestation          # noqa: PLC0415
    phase1_blocked: dict[str, str] = {}
    for result in results:
        pid = str(result.get("id"))
        if (result.get("worker_status") == "ERROR"
                and result.get("worker_retryable") is True):
            # There is no Program outcome to guard yet: this result is owed
            # the retry below, which re-enters at its routed entry and emits
            # the provenance the next --resume binds and checks. Refusing it
            # here made a D1 worker crash unrecoverable except by a fresh
            # --solve that discards every other committed result -- the very
            # loss the retry exists to prevent.
            continue
        proj = run_p / "projects" / re.sub(r"[^\w.-]", "_", pid)
        task = task_by_id.get(pid)
        expected = (task.get("phase1_provenance")
                    if isinstance(task, dict) else None)
        current = emit_attestation.phase1_provenance(proj)
        if isinstance(expected, dict) and expected.get("ran") is True:
            if current != expected:
                phase1_blocked[pid] = (
                    "Phase-1 provenance changed after task creation")
            continue
        if result.get("entry") == "D1" and current.get("ran") is not True:
            # Judged by what the run EMITTED, not by what the task recorded.
            # A task written before provenance was carried, or not written
            # at all yet (awaiting AI backup), says nothing about the L-docs
            # on disk; when they are there the front door below REUSES them
            # without a runner call and binds them into the task. Only a D1
            # run that truly left none is refused, and the message is then
            # a measured fact rather than a missing field.
            phase1_blocked[pid] = (
                "canonical D1-entry run emitted no Phase-1 provenance")
            continue
        frontdoor = _ensure_phase1_frontdoor(runner, proj, runner_budget)
        if frontdoor.get("status") == "BLOCKED":
            phase1_blocked[pid] = str(
                frontdoor.get("reason") or "Phase-1 front door blocked")
            continue
        current = frontdoor["provenance"]
        result["phase1_frontdoor"] = frontdoor
        if isinstance(task, dict):
            task["phase1_provenance"] = current
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
                run_p, "PROGRAM", program_phases=result.get("phases"))
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
                run_p, "AI_BACKUP", program_phases=result.get("phases"))
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
                and (not review_path.is_file()
                     or _validate_embedded_repair_provenance(task))):
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
        # Freeze the signed bytes BEFORE the gates can normalize them in
        # place.  Without this the only copy of what the author signed is
        # destroyed, and a later Program fix has nothing to re-enter from.
        try:
            preserved = _archive_pre_gate_input(
                run_p, pid, working_paths, str(working_hash))
        except (OSError, ValueError) as exc:
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": False,
                           "ai_repair_required": True})
            repair_plans.append({
                "kind": "report", "id": pid, "pre_logs": pre_logs,
                "log": f"  {pid:44s} signed pre-gate input not preserved",
                "repair": {
                    "schema": "vibeic.benchmark.ai_repair_task.v2",
                    "id": pid, "project": str(proj),
                    "status": "PRE_GATE_INPUT_NOT_PRESERVED",
                    "reasons": [f"{type(exc).__name__}: {exc}"],
                    "signed_rtl_sha256": working_hash,
                },
            })
            continue
        repair_plans.append({
            "kind": "run", "id": pid, "pre_logs": pre_logs,
            "task": task, "result": result, "project": proj,
            "challenge": challenge, "repair_provenance": repair_provenance,
            "repair_parent_candidate": task.get("candidate_snapshot"),
            "pre_gate_input": preserved,
            "repair_input_candidate": _archive_repair_input(
                pid, proj, run_p, repair_provenance),
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
            if plan.get("challenge") is not None:
                inherited.append(plan["challenge"])
            new_task = _make_ai_review_task(
                pid, proj, got, result.get("routing_verdict") or {}, rc,
                run_p, "AI_REPAIR",
                program_phases=result.get("phases"),
                verification_challenges=inherited,
                program_candidate=(task.get("program_candidate_snapshot")
                                   or task.get("candidate_snapshot")),
                repair_parent_candidate=plan.get("repair_parent_candidate"),
                repair_provenance=plan["repair_provenance"],
                repair_input_candidate=plan.get("repair_input_candidate"))
            preserved = plan.get("pre_gate_input")
            if isinstance(preserved, dict):
                new_task["pre_gate_input"] = _bind_pre_gate_output(
                    preserved, new_task["rtl_sha256"])
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
        # #2012's invariant, at the only site that can violate it: a
        # candidate whose canonical Phase-1 provenance is missing, or was
        # changed after its review task was written, is NOT accepted and NOT
        # published. Asked before the frozen response payload is written, so
        # nothing reaches responses/ for a refused candidate.
        blocked_reason = phase1_blocked.get(pid)
        if blocked_reason is not None:
            print("ERROR: canonical Phase-1 front door BLOCKED:\n  "
                  f"{pid}: {blocked_reason}", file=sys.stderr)
            repairs.append({
                "schema": "vibeic.benchmark.ai_repair_task.v2",
                "id": pid, "project": task.get("project"),
                "status": "PHASE1_PROVENANCE_BLOCKED",
                "reasons": [blocked_reason],
                "required_next": (
                    "re-enter this project through the canonical Phase-1 "
                    "front door so it emits hash-bound L-doc provenance, then "
                    "run --resume again; a candidate with no canonical "
                    "Phase-1 provenance is never accepted"),
            })
            result.update({"accepted": False, "awaiting_ai": True,
                           "awaiting_ai_review": True,
                           "ai_repair_required": False})
            continue
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


_CORRECTION_REFUSED = "REVIEW_CORRECTION_REFUSED"
_REGATE_REFUSED = "PROGRAM_REGATE_REFUSED"
_PROGRAM_RETRY_DEPRECATION = (
    "DEPRECATED: --program-retry is now an alias of --program-regate and will "
    "be removed one version after v1.17.75 (issue #2047 merged the two "
    "Program re-entry operations into one). Re-run with --program-regate.")


def _correction_path(path: str | Path, run_p: Path | None = None,
                     *, exists: bool = True,
                     token: str = _CORRECTION_REFUSED) -> Path:
    """BLOCKING: correction evidence may not traverse a symlink or escape run.

    `token` names the refusing operation. It changes only the message prefix:
    the two operations enforce one identical path contract, so a divergence
    here could not be a divergence in what is allowed.
    """
    if not isinstance(path, (str, Path)) or not str(path):
        raise ValueError(f"{token}: malformed path")
    path = Path(path).absolute()
    if any(part.is_symlink() for part in [path, *path.parents]):
        raise ValueError(f"{token}: symlink path: {path}")
    path = path.resolve()
    if run_p is not None and not path.is_relative_to(run_p):
        raise ValueError(f"{token}: path outside run: {path}")
    if exists and not path.is_file():
        raise ValueError(f"{token}: missing file: {path}")
    return path


def _correction_object(path: Path,
                       token: str = _CORRECTION_REFUSED) -> tuple[dict, str]:
    raw = path.read_bytes().decode("utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"{token}: not a JSON object: {path}")
    return obj, raw


def _review_task_digest(task: dict) -> str:
    return _sha256_text(json.dumps(task, ensure_ascii=False, sort_keys=True))


def _apply_review_correction(run_p: Path, request_path: Path) -> None:
    """Advance ONE unaccepted review, not its candidate or acceptance verdict.

    BLOCKING: explicit AI attribution, prompt evidence and exact source hashes
    are required. The old current challenge becomes an ordinary inherited
    obligation; ONLY the existing validation/supersession/coverage predicates
    can subsequently retire it. This operation neither proves a defect nor
    authorizes repair, and it never reopens an accepted/published candidate.

    Called only under the solve/resume coordinator lock. Immutable archives are
    prepared first; the sole state-transition commit is the atomic worklist
    replacement. Interruption before that commit leaves the old task active;
    repeating the same request reuses identical archives. Interruption after it
    leaves the new, unreviewed task active. Ordinary resume derives all other
    worklists and the pending acceptance ledger from that authoritative task.
    """
    run_p = run_p.resolve()
    request, request_raw = _correction_object(_correction_path(request_path))
    request_sha = _sha256_text(request_raw)
    task_path = _correction_path(run_p / _REVIEW_WORKLIST, run_p)
    task_raw = task_path.read_text(encoding="utf-8")
    tasks = _read_jsonl(task_path)
    ids = [str(t.get("id")) for t in tasks]
    pid = str(request.get("id") or "")
    if not pid or len(set(ids)) != len(ids) or ids.count(pid) != 1:
        raise ValueError("REVIEW_CORRECTION_REFUSED: missing or duplicate task id")
    current = tasks[ids.index(pid)]
    archive = run_p / "review_corrections" / _safe_problem_id(pid) / request_sha
    transition_path = _correction_path(archive / "transition.json", run_p,
                                       exists=False)
    transition = None
    if transition_path.exists():
        transition, _ = _correction_object(transition_path)
        task = transition.get("prior_task")
        if not isinstance(task, dict):
            raise ValueError("REVIEW_CORRECTION_REFUSED: invalid transition archive")
    else:
        task = current
    if request.get("schema") != _REVIEW_CORRECTION_SCHEMA:
        raise ValueError("REVIEW_CORRECTION_REFUSED: wrong request schema")
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        raise ValueError("REVIEW_CORRECTION_REFUSED: wrong task schema")
    for field, expected in (
            ("task_sha256", _review_task_digest(task)),
            ("prompt_sha256", task.get("prompt_sha256")),
            ("rtl_sha256", task.get("rtl_sha256"))):
        if not re.fullmatch(r"[0-9a-f]{64}", str(request.get(field) or "")) \
                or request[field] != expected:
            raise ValueError(f"REVIEW_CORRECTION_REFUSED: stale {field}")
    author = request.get("author")
    blind = request.get("blind")
    if (not isinstance(author, dict) or author.get("kind") != "AI"
            or not isinstance(author.get("model"), str)
            or author["model"].strip().lower() in {"", "unknown", "unspecified", "n/a"}
            or not isinstance(blind, dict) or blind.get("oracle_accessed") is not False):
        raise ValueError("REVIEW_CORRECTION_REFUSED: attributed blind AI required")
    if not isinstance(request.get("rationale"), str) \
            or len(request["rationale"].strip()) < 80:
        raise ValueError("REVIEW_CORRECTION_REFUSED: rationale needs 80 characters")
    prompt_path = _correction_path(task.get("prompt_path") or "", run_p)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if not _verified_prompt_evidence(request.get("prompt_evidence"), prompt_text):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prompt-bound evidence required")
    candidate = task.get("candidate_snapshot")
    if not isinstance(candidate, dict):
        raise ValueError("REVIEW_CORRECTION_REFUSED: candidate snapshot missing")
    material_paths = [prompt_path]
    project = _correction_path(task.get("project") or "", run_p, exists=False)
    if not project.is_dir():
        raise ValueError("REVIEW_CORRECTION_REFUSED: missing project directory")
    working_paths = [_correction_path(p, run_p) for p in _rtl_files(project)]
    for field in ("rtl_paths", "working_rtl_paths"):
        paths = task.get(field)
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"REVIEW_CORRECTION_REFUSED: missing {field}")
        material_paths.extend(_correction_path(p, run_p) for p in paths)
    for field in ("completion_path", "response_payload_path", "manifest_path"):
        material_paths.append(_correction_path(candidate.get(field) or "", run_p))
    material_paths.extend(_correction_path(p, run_p)
                          for p in candidate.get("rtl_paths") or [])
    if (_validate_candidate_snapshot(candidate, pid)
            or _current_task_material(task)[:2] != (
                task.get("prompt_sha256"), task.get("rtl_sha256"))
            or sorted(task["rtl_paths"]) != sorted(candidate["rtl_paths"])
            or sorted(str(p) for p in working_paths)
                != sorted(task["working_rtl_paths"])
            or _sha256_text(_candidate_text(working_paths))
                != task.get("rtl_sha256")):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prompt/candidate/working RTL drift")
    review_path = _correction_path(task.get("review_path") or "", run_p)
    review, review_raw = _correction_object(review_path)
    for field in ("id", "prompt_sha256", "rtl_sha256"):
        if review.get(field) != task.get(field):
            raise ValueError(f"REVIEW_CORRECTION_REFUSED: prior review {field} drift")
    if (review.get("schema") != _AI_REVIEW_SCHEMA
            or not isinstance(review.get("reviewer"), dict)
            or review["reviewer"].get("kind") != "AI"
            or not isinstance(review.get("blind"), dict)
            or review["blind"].get("oracle_accessed") is not False):
        raise ValueError("REVIEW_CORRECTION_REFUSED: malformed prior AI review")
    if request.get("review_sha256") != _sha256_text(review_raw):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prior review hash drift")
    challenge_path = _correction_path(task.get("challenge_path") or "", run_p)
    raw_test = review.get("verification_test")
    if not isinstance(raw_test, dict):
        raise ValueError("REVIEW_CORRECTION_REFUSED: prior challenge missing")
    _correction_path(raw_test.get("path") or "", run_p)
    challenge, reasons = _challenge_from_review(task, review, prompt_text)
    if reasons or not challenge:
        raise ValueError("REVIEW_CORRECTION_REFUSED: " + "; ".join(reasons))
    if request.get("challenge_sha256") != challenge["sha256"]:
        raise ValueError("REVIEW_CORRECTION_REFUSED: current challenge hash drift")
    material_paths.extend([review_path, challenge_path])
    inherited = task.get("verification_challenges")
    if not isinstance(inherited, list) or not all(isinstance(c, dict) for c in inherited):
        raise ValueError("REVIEW_CORRECTION_REFUSED: malformed inherited challenges")
    for item in inherited:
        path = _correction_path(item.get("path") or "", run_p)
        if _sha256_text(path.read_text(encoding="utf-8")) != item.get("sha256"):
            raise ValueError("REVIEW_CORRECTION_REFUSED: inherited challenge drift")
        material_paths.append(path)
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in material_paths}
    key = f"review-correction-{request_sha}"
    new_review = _correction_path(
        run_p / "ai_reviews" / _safe_problem_id(pid) / f"{key}.json",
        run_p, exists=False)
    new_challenge = _correction_path(
        run_p / "ai_verification_challenges" / _safe_problem_id(pid)
        / key / "challenge_tb.sv", run_p, exists=False)

    def replace_paths(value):
        if isinstance(value, dict):
            return {k: replace_paths(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace_paths(v) for v in value]
        if value == task["challenge_path"]:
            return str(new_challenge)
        if value == task["review_path"]:
            return str(new_review)
        return value

    new_task = replace_paths(task)
    new_task["verification_challenges"] = list(inherited)
    if not any(c.get("sha256") == challenge["sha256"] for c in inherited):
        new_task["verification_challenges"].append(challenge)
    new_task["review_correction"] = {
        "schema": _REVIEW_CORRECTION_SCHEMA,
        "request_sha256": request_sha,
        "archive_path": str(archive),
        "prior_review_path": str(review_path),
        "prior_review_sha256": request["review_sha256"],
        "prior_challenge_sha256": challenge["sha256"],
        "status": "FRESH_REVIEW_REQUIRED",
        "repair_authorized": False,
    }
    expected_transition = {"schema": _REVIEW_CORRECTION_SCHEMA,
                           "prior_task": task, "new_task": new_task,
                           "material_sha256": hashes,
                           "request_sha256": request_sha}
    if transition is not None and transition != expected_transition:
        raise ValueError("REVIEW_CORRECTION_REFUSED: transition evidence drift")
    if current not in (task, new_task):
        raise ValueError("REVIEW_CORRECTION_REFUSED: current task drift")
    already_applied = current == new_task
    if not already_applied:
        solve, _ = _correction_object(_correction_path(run_p / "solve_report.json", run_p))
        results = solve.get("results")
        matches = ([r for r in results if isinstance(r, dict) and r.get("id") == pid]
                   if isinstance(results, list) else [])
        if len(matches) != 1 or matches[0].get("accepted") is not False:
            raise ValueError("REVIEW_CORRECTION_REFUSED: task must be unaccepted")
        acceptance_path = _correction_path(run_p / _ACCEPTANCE_REPORT, run_p,
                                          exists=False)
        if acceptance_path.exists():
            acceptance, _ = _correction_object(acceptance_path)
            if pid in (acceptance.get("accepted_ids") or []):
                raise ValueError("REVIEW_CORRECTION_REFUSED: candidate already accepted")
        response = _correction_path(task.get("response_path") or "", run_p, exists=False)
        if response.exists() or new_review.exists() or new_challenge.exists():
            raise ValueError("REVIEW_CORRECTION_REFUSED: published response or occupied new path")
    archives = {"prior_task.json": json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n",
                "prior_review.json": review_raw,
                "prior_challenge_tb.sv": challenge_path.read_bytes().decode("utf-8"),
                "request.json": request_raw,
                "transition.json": json.dumps(expected_transition, ensure_ascii=False,
                                              sort_keys=True) + "\n"}
    for name, raw in archives.items():
        path = _correction_path(archive / name, run_p, exists=False)
        if path.exists():
            if path.read_bytes().decode("utf-8") != raw:
                raise ValueError("REVIEW_CORRECTION_REFUSED: immutable archive drift")
        else:
            if transition is not None:
                raise ValueError("REVIEW_CORRECTION_REFUSED: immutable archive missing")
            _atomic_write_text(path, raw)
    # Recheck all source material before the one authoritative commit.
    for path, digest in hashes.items():
        source = _correction_path(path, run_p)
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("REVIEW_CORRECTION_REFUSED: source changed during preparation")
    if task_path.read_text(encoding="utf-8") != task_raw:
        raise ValueError("REVIEW_CORRECTION_REFUSED: worklist changed during preparation")
    if not already_applied:
        tasks[ids.index(pid)] = new_task
        _write_jsonl(task_path, tasks)
    print(f"  {pid}: REVIEW_CORRECTION_" +
          ("ALREADY_APPLIED" if already_applied else "APPLIED") +
          "; same candidate; FRESH_REVIEW_REQUIRED; no repair permit")


_PROGRAM_RETRY_SCHEMA = "vibeic.benchmark.program_retry.v1"


def _program_source_identity() -> dict:
    """Fingerprint the installed executable Program sources, including dirty edits.

    The SECOND half of the merged operation's identity. A Program can be fixed
    without a version bump -- the fix is real, the version pair is unchanged --
    and a Program version can move with the executable sources untouched. The
    two identities are neither necessary nor sufficient for each other in
    either direction, so `_apply_program_regate` requires BOTH to have moved.
    """
    root = Path(__file__).resolve().parent.parent
    paths = [root / ".claude-plugin" / "plugin.json"]
    for directory in ("programs", "_shared", "flow", "config", "tools",
                      "schemas", "data", "ip-catalog", "mcp-eda"):
        paths.extend(p for p in (root / directory).rglob("*") if p.is_file()
                     and not {"tests", "__pycache__", ".pytest_cache"}.intersection(p.relative_to(root).parts)
                     and p.suffix not in {".pyc", ".md"})
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(paths)}
    return {"schema": "vibeic.program.source_identity.v1",
            "source_sha256": _review_task_digest(hashes)}


def _regate_path(path, run_p, *, exists=True):
    """`_correction_path` under this operation's own refusal token."""
    return _correction_path(path, run_p, exists=exists, token=_REGATE_REFUSED)


def _regate_project_tree(project: Path) -> dict:
    """Bind all source files and internal relative links without following links."""
    hashes = {}
    for path in sorted(project.rglob("*")):
        key = str(path.relative_to(project))
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve().is_relative_to(project):
                raise ValueError(f"{_REGATE_REFUSED}: escaping project symlink")
            hashes[key] = {"symlink": target}
        elif path.is_file():
            hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise ValueError(f"{_REGATE_REFUSED}: unsupported project file")
    return hashes


def _guard_program_regate_journals(run_p: Path) -> None:
    """BLOCKING: an interrupted promotion needs explicit reconciliation."""
    root = _regate_path(run_p / "program_regates", run_p, exists=False)
    for archive in sorted(root.glob("*/*")):
        _regate_path(archive, run_p, exists=False)
        intent = _regate_path(archive / "intent.json", run_p, exists=False)
        completed = _regate_path(archive / "complete.json", run_p, exists=False)
        failed = _regate_path(archive / "failed.json", run_p, exists=False)
        if not intent.exists():
            continue
        reason = None
        try:
            plan = json.loads(intent.read_text())
            request_path = _regate_path(archive / "request.json", run_p)
            request = json.loads(request_path.read_text())
            if (plan.get("schema") != _PROGRAM_REGATE_SCHEMA or plan.get("request") != request
                    or _sha256_text(request_path.read_text()) != archive.name
                    or plan.get("program_identity") != request.get("program_identity")
                    or _review_task_digest(plan["prior_task"]) != request.get("task_sha256")):
                raise ValueError("intent/request binding differs")
            if completed.exists() and not failed.exists():
                marker = json.loads(completed.read_text())
                transition_path = _regate_path(archive / "transition.json", run_p)
                transition = json.loads(transition_path.read_text())
                if (marker.get("schema") != _PROGRAM_REGATE_SCHEMA
                        or marker.get("request_sha256") != archive.name
                        or marker.get("archive_path") != str(archive)
                        or marker.get("program_identity") != plan["program_identity"]
                        or transition.get("prior_task") != plan["prior_task"]
                        or transition["new_task"].get("program_regate") != marker):
                    raise ValueError("completion/transition binding differs")
            elif failed.exists() and not completed.exists():
                marker = json.loads(failed.read_text())
                if (marker.get("schema") != _PROGRAM_REGATE_SCHEMA
                        or marker.get("request_sha256") != archive.name
                        or marker.get("intent_sha256") != _review_task_digest(plan)
                        or marker.get("promotion_started") is not False
                        or (archive / "prior_project").exists()
                        or (archive / "promotion.json").exists()):
                    raise ValueError("failure marker cannot establish an untouched original")
            else:
                reason = "missing or conflicting terminal markers"
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            reason = str(exc)
        if reason is not None:
            raise ValueError(f"{_REGATE_REFUSED}: interrupted journal requires "
                             f"reconciliation before resume: {archive}: {reason}")


def _regate_request_field(request: dict, primary: str, legacy: str):
    """One request field under BOTH operations' names.

    `--program-regate` (v1.17.63) and `--program-retry` (v1.17.71) named the
    same two hashes differently. The merged operation accepts either spelling
    so a caller written against either front door still binds, and refuses a
    request that supplies both under conflicting values -- an ambiguous
    identity is not an identity.
    """
    have_primary = request.get(primary) is not None
    have_legacy = request.get(legacy) is not None
    if have_primary and have_legacy and request[primary] != request[legacy]:
        raise ValueError(f"{_REGATE_REFUSED}: {primary} and {legacy} disagree")
    if have_primary:
        return request[primary]
    return request.get(legacy)


def _apply_program_regate(bench: str, run_p: Path, request_path: Path,
                          worker_threads: int) -> int:
    """The ONE Program re-entry operation: re-run the FIXED Program on ONE
    preserved, signed pre-gate input, under BOTH Program identities.

    BLOCKING. A deterministic gate can normalize a signed author candidate into
    different bytes before freezing it, which correctly makes the author's
    final signature stale. When that transform is later FIXED, the pending task
    is stuck: its unchanged working output is not re-gated, restoring the signed
    input reads as a new AI edit needing a counterexample against the unwanted
    candidate, and re-signing the unwanted output would attribute a PROGRAM
    mutation to the AI author. This operation is the missing third option.

    IDENTITY -- both halves, always. The Program must have moved in BOTH the
    declared version pair (`program_version_before`/`_after`) and the executable
    SOURCE TREE (`_program_source_identity`). Neither implies the other: a fix
    can land with no version bump, and a version can move with no executable
    change. Requiring one alone lets the other kind of no-op retry loop.

    EXECUTION. The re-run happens in a STAGED copy of the project under the
    resume coordinator lock, with an immutable intent journalled before staging
    and a terminal marker after, so an interrupted promotion blocks the next
    resume instead of resuming over unknown state. Failure leaves the original
    project and task untouched.

    ATTRIBUTION. The regenerated bytes are recorded as PROGRAM-authored with the
    author's signature unchanged (`_verified_program_regate` then binds the
    author's signature to the preserved signed INPUT, not to the Program's
    output). It never accepts, never publishes, never supersedes a challenge and
    never grants a repair permit: the regenerated output carries the SAME
    downstream obligations as a first-time output, including a fresh independent
    review.

    The stale-signature refusal is NOT weakened. Every task without a verified
    `program_regate` record is compared exactly as before; see
    `_signed_candidate_hash`.

    Merged from `--program-regate` (v1.17.63) and `--program-retry` (v1.17.71)
    under issue #2047. `--program-retry` remains as a deprecated alias for one
    version; see `cmd_resume`.
    """
    import benchmark_io_adapter as bio                  # noqa: PLC0415
    import emit_attestation as ea                       # noqa: PLC0415
    import flow_phase_attribution as fpa                # noqa: PLC0415
    import task_nature_route as tnr                     # noqa: PLC0415

    def refuse(reason):
        raise ValueError(f"{_REGATE_REFUSED}: {reason}")

    material = {}

    def bound(path):
        path = _regate_path(path, run_p)
        material[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def obj(path):
        value = json.loads(bound(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            refuse("expected a JSON object")
        return value

    request_path = bound(request_path)
    request_raw = request_path.read_text(encoding="utf-8")
    request = obj(request_path)
    request_sha = _sha256_text(request_raw)
    if request.get("schema") not in (_PROGRAM_REGATE_SCHEMA,
                                     _PROGRAM_RETRY_SCHEMA):
        refuse("unsupported request schema")

    # --- identity half 1: the executable Program sources ------------------
    identity = _program_source_identity()
    if request.get("program_identity") is None:
        refuse("request names no Program source identity; the merged "
               "operation requires the source tree AND the version pair")
    if request.get("program_identity") != identity:
        refuse("stale Program identity")

    rationale = _regate_request_field(request, "rationale", "reason")
    if not isinstance(rationale, str) or len(rationale.strip()) < 80:
        refuse("rationale needs 80 characters")
    author = request.get("author")
    blind = request.get("blind")
    if (not isinstance(author, dict) or author.get("kind") != "AI"
            or not isinstance(author.get("model"), str)
            or author["model"].strip().lower() in {"", "unknown", "unspecified", "n/a"}
            or not isinstance(blind, dict) or blind.get("oracle_accessed") is not False):
        refuse("attributed blind AI required")

    task_path = bound(run_p / _REVIEW_WORKLIST)
    tasks = _read_jsonl(task_path)
    pid = request.get("id")
    ids = [t.get("id") for t in tasks]
    if not isinstance(pid, str) or not pid or len(set(ids)) != len(ids) or ids.count(pid) != 1:
        refuse("missing or duplicate review task")
    task = tasks[ids.index(pid)]
    if task.get("schema") != _REVIEW_TASK_SCHEMA:
        refuse("wrong task schema")
    if task.get("candidate_origin") != "AI_REPAIR":
        refuse("only an AI_REPAIR candidate can be re-gated")

    stale_output = _regate_request_field(request, "stale_output_sha256",
                                         "rtl_sha256")
    signed = _regate_request_field(request, "signed_input_sha256",
                                   "input_rtl_sha256")
    for field, value, expected in (
            ("task_sha256", request.get("task_sha256"), _review_task_digest(task)),
            ("prompt_sha256", request.get("prompt_sha256"), task.get("prompt_sha256")),
            ("stale_output_sha256", stale_output, task.get("rtl_sha256"))):
        if value != expected or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            refuse("stale " + field)
    if not re.fullmatch(r"[0-9a-f]{64}", str(signed or "")):
        refuse("malformed signed_input_sha256")
    if signed == str(task.get("rtl_sha256") or ""):
        refuse("the gates did not change the signed input; nothing to re-gate")

    # --- identity half 2: the declared Program version pair ---------------
    before = str(request.get("program_version_before") or "")
    after = str(request.get("program_version_after") or "")
    running = _program_version()
    if not before or not after:
        refuse("both Program versions must be named")
    if before == after:
        refuse("Program version unchanged; a retry with the same Program "
               "is a loop, not a fix")
    if not running:
        refuse("the running Program version is not readable")
    if after != running:
        refuse(f"program_version_after {after!r} is not the running "
               f"Program {running!r}")
    if (task.get("program_regate") or {}).get("program_identity") == identity:
        refuse("Program identity has not changed since the prior re-entry")

    solve_path = bound(run_p / "solve_report.json")
    solve = obj(solve_path)
    policy = solve.get("acceptance_policy") or {}
    if (policy.get("required") is not True
            or policy.get("review_task_schema") != _REVIEW_TASK_SCHEMA
            or policy.get("review_schema") != _AI_REVIEW_SCHEMA):
        refuse("unsupported solve acceptance policy")
    results = solve.get("results")
    matches = [r for r in results if r.get("id") == pid]
    if len(matches) != 1 or matches[0].get("accepted") is not False:
        refuse("task must be unaccepted")
    result = matches[0]
    if result.get("exit") not in tnr.flow_step_ids():
        refuse("missing or unsupported declared exit")
    fmt = _BENCH_FORMAT.get(bench)
    if fmt is None:
        refuse("no bound IO adapter")
    acceptance_path = _regate_path(run_p / _ACCEPTANCE_REPORT, run_p, exists=False)
    acceptance = obj(acceptance_path) if acceptance_path.exists() else {}
    if pid in (acceptance.get("accepted_ids") or []):
        refuse("candidate already accepted")
    response = _regate_path(task.get("response_path"), run_p, exists=False)
    if response != run_p / "responses" / f"{_safe_problem_id(pid)}.json":
        refuse("response path is not the canonical publication path")
    if response.exists():
        refuse("candidate already published")
    project = _regate_path(task.get("project"), run_p, exists=False)
    if project != run_p / "projects" / _safe_problem_id(pid) or not project.is_dir():
        refuse("project is not the runner-owned project")
    tree = _regate_project_tree(project)
    prompt = bound(task.get("prompt_path"))
    if prompt != project / "input" / "phase1_prompt.md" or _sha256_text(prompt.read_text()) != task["prompt_sha256"]:
        refuse("prompt drift")
    if task.get("phase1_provenance") != ea.phase1_provenance(project):
        refuse("Phase-1 provenance drift")

    def snapshot(candidate):
        if not isinstance(candidate, dict):
            refuse("missing candidate snapshot")
        for field in ("manifest_path", "completion_path", "response_payload_path"):
            bound(candidate.get(field))
        for path in candidate.get("rtl_paths") or []:
            bound(path)
        reasons = _validate_candidate_snapshot(candidate, pid)
        if reasons:
            refuse("; ".join(reasons))

    for field in ("candidate_snapshot", "program_candidate_snapshot", "repair_parent_candidate_snapshot"):
        snapshot(task.get(field))
    working = [bound(p) for p in _rtl_files(project)]
    if ([str(p) for p in working] != task.get("working_rtl_paths")
            or _sha256_text(_candidate_text(working)) != task["rtl_sha256"]
            or task["candidate_snapshot"].get("rtl_sha256") != task["rtl_sha256"]
            or task.get("rtl_paths") != task["candidate_snapshot"]["rtl_paths"]):
        refuse("working or frozen RTL drift")
    provenance = task.get("repair_provenance")
    if not isinstance(provenance, dict):
        refuse("task lacks its AI repair provenance")
    record_path = bound(provenance.get("path"))
    if request.get("repair_record_sha256") != material[str(record_path)]:
        refuse("stale repair record hash")
    if str(provenance.get("repaired_rtl_sha256") or "") != signed:
        refuse("signed_input_sha256 is not the hash the author signed")

    # --- the preserved input, named by BOTH the request and the task ------
    pre_gate = task.get("pre_gate_input")
    if not isinstance(pre_gate, dict):
        refuse("task has no preserved pre-gate input record")
    if str(pre_gate.get("signed_input_sha256") or "") != signed \
            or str(pre_gate.get("gate_output_sha256") or "") \
            != str(task.get("rtl_sha256") or ""):
        refuse("preserved pre-gate binding does not name this task's pair")
    # The signed input is preserved TWICE, by the two merged operations'
    # different records, and the merged operation binds BOTH: the request's
    # immutable CANDIDATE snapshot (--program-retry) and the task's PRE-GATE
    # input manifest (--program-regate). They must describe the same bytes.
    input_manifest = bound(request.get("input_manifest_path"))
    if request.get("input_manifest_sha256") is not None \
            and request["input_manifest_sha256"] != material[str(input_manifest)]:
        refuse("stale input manifest hash")
    input_candidate = obj(input_manifest)
    snapshot(input_candidate)
    if (input_candidate.get("manifest_path") != str(input_manifest)
            or input_candidate.get("rtl_sha256") != signed
            or len(input_candidate.get("rtl_paths") or []) != len(working)
            or input_candidate.get("source_rtl_paths") != task["working_rtl_paths"]):
        refuse("preserved input binding or source paths differ")

    manifest_path = _regate_path(pre_gate.get("input_manifest_path") or "", run_p)
    preserved = obj(manifest_path)
    if preserved.get("schema") != _PRE_GATE_INPUT_SCHEMA \
            or str(preserved.get("id")) != pid \
            or str(preserved.get("rtl_sha256") or "") != signed:
        refuse("preserved input manifest does not match the request")
    if before != str(preserved.get("program_version") or ""):
        refuse(f"program_version_before {before!r} is not the Program that "
               "produced the preserved input")
    preserved_paths = [bound(q) for q in preserved.get("rtl_paths") or []]
    if not preserved_paths:
        refuse("preserved input has no RTL")
    if len(preserved_paths) != len(preserved.get("source_rtl_paths") or []):
        refuse("preserved input manifest is internally inconsistent")
    if len(preserved_paths) != len(working):
        refuse("preserved input does not cover the working RTL file set")
    if _sha256_text(_candidate_text(preserved_paths)) != signed:
        refuse("preserved signed input hash drift")
    automatic_input = task.get("repair_input_candidate_snapshot")
    if automatic_input is not None and automatic_input != input_candidate:
        refuse("request differs from automatically preserved input")
    inherited = task.get("verification_challenges")
    if not isinstance(inherited, list) or not inherited:
        refuse("missing inherited challenges")
    inherited = list(inherited)
    for challenge in inherited:
        path = bound(challenge.get("path"))
        if _sha256_text(path.read_text()) != challenge.get("sha256"):
            refuse("inherited challenge drift")
    signed_challenge = next((c for c in inherited if c.get("sha256") == provenance.get("challenge_sha256")), None)
    if signed_challenge is None:
        refuse("signed challenge is not inherited")
    validated, reasons = _validate_repair_record(
        record_path, {**task, "rtl_sha256": task["repair_parent_candidate_snapshot"]["rtl_sha256"]},
        input_candidate["rtl_sha256"], signed_challenge)
    if reasons or validated != provenance:
        refuse("signed input provenance drift: " + "; ".join(reasons))

    # A bound current proof is preserved and remains an inherited obligation.
    review_path = _regate_path(task.get("review_path"), run_p, exists=False)
    challenge_path = _regate_path(task.get("challenge_path"), run_p, exists=False)
    prior_review = None
    if review_path.exists() or challenge_path.exists():
        prior_review = obj(review_path)
        bound(challenge_path)
        bound((prior_review.get("verification_test") or {}).get("path"))
        if (request.get("review_sha256") != material[str(review_path)]
                or request.get("challenge_sha256") != material[str(challenge_path)]
                or any(prior_review.get(k) != task.get(k) for k in ("id", "prompt_sha256", "rtl_sha256"))
                or prior_review.get("schema") != _AI_REVIEW_SCHEMA
                or (prior_review.get("reviewer") or {}).get("kind") != "AI"
                or (prior_review.get("blind") or {}).get("oracle_accessed") is not False):
            refuse("current review/test is not exactly bound")
        current_challenge, reasons = _challenge_from_review(task, prior_review, prompt.read_text())
        if reasons or not current_challenge:
            refuse("invalid current challenge: " + "; ".join(reasons))
        if not any(c.get("sha256") == current_challenge["sha256"] for c in inherited):
            inherited.append(current_challenge)
    elif request.get("review_sha256") is not None or request.get("challenge_sha256") is not None:
        refuse("bound current review/test is missing")
    key = "program-regate-" + request_sha
    new_review = _regate_path(run_p / "ai_reviews" / _safe_problem_id(pid) / (key + ".json"), run_p, exists=False)
    new_challenge = _regate_path(run_p / "ai_verification_challenges" / _safe_problem_id(pid) / key / "challenge_tb.sv", run_p, exists=False)
    archive = _regate_path(run_p / "program_regates" / _safe_problem_id(pid) / request_sha, run_p, exists=False)
    if archive.exists() or new_review.exists() or new_challenge.exists():
        refuse("occupied re-entry archive or fresh review/test path")
    for name in (_BACKUP_WORKLIST, _REPAIR_WORKLIST):
        path = _regate_path(run_p / name, run_p, exists=False)
        if path.exists():
            bound(path)
    if any(t.get("id") == pid for t in _read_jsonl(run_p / _BACKUP_WORKLIST)):
        refuse("task also has a pending AI backup")

    def recheck():
        for path, digest in material.items():
            if hashlib.sha256(_regate_path(path, run_p).read_bytes()).hexdigest() != digest:
                refuse("source changed during preparation: " + path)
        if _regate_project_tree(project) != tree or _program_source_identity() != identity:
            refuse("project or Program source changed during preparation")
        if response.exists() or new_review.exists() or new_challenge.exists():
            refuse("publication or fresh review/test path occupied during preparation")

    recheck()
    intent = {
        "schema": _PROGRAM_REGATE_SCHEMA, "request": request, "prior_task": task,
        "material_sha256": material, "project_tree": tree,
        "program_identity": identity, "status": "PREPARED"}
    _write_immutable_json(archive / "intent.json", intent)
    _write_immutable_text(archive / "request.json", request_raw)
    for source in (task_path, solve_path, acceptance_path,
                   run_p / _BACKUP_WORKLIST, run_p / _REPAIR_WORKLIST):
        if source.exists():
            _write_immutable_text(archive / "prior_state" / source.name,
                                  source.read_bytes().decode("utf-8"))
    if prior_review is not None:
        _write_immutable_text(archive / "prior_review.json", review_path.read_text())
        _write_immutable_text(archive / "prior_challenge_tb.sv", challenge_path.read_text())
    staged = archive / "staged_project"
    promoted = False
    try:
        shutil.copytree(project, staged, symlinks=True)
        for source, destination in zip(input_candidate["rtl_paths"], working, strict=True):
            _atomic_write_text(staged / destination.relative_to(project), Path(source).read_text())
        if _sha256_text(_candidate_text(_rtl_files(staged))) != signed:
            refuse("staged work tree does not hash to the signed input")
        phase2_report = staged / "reports" / "orchestrator" / "phase2_one_shot.json"
        if phase2_report.exists():
            phase2_report.unlink()  # staged copy only; require fresh gate evidence
        runner = Path(__file__).resolve().parent / "vibe_ic_one_shot_runner.py"
        argv = _resume_solver_argv(runner, staged, True, result.get("entry"), result["exit"])
        process = _RunnerBudget(1, 1, worker_threads).run(argv)
        got = bio.collect(fmt, pid, staged, supplied_rtl=True)
        _write_immutable_json(archive / "runner_result.json", {
            "argv": argv, "rc": process.rc, "error": process.error, "collected": got})
        if process.error or not got.get("ok"):
            refuse("Program runner failed; original task/project retained")
        _regate_project_tree(staged)
        if (ea.phase1_provenance(staged) != task["phase1_provenance"]
                or _sha256_text((staged / "input" / "phase1_prompt.md").read_text()) != task["prompt_sha256"]):
            refuse("Program changed bound prompt or Phase-1 inputs")
        candidate_root = _regate_path(
            run_p / "candidate_snapshots" / _safe_problem_id(pid)
            / f"{key}-{_sha256_text(str(got.get('completion') or ''))}", run_p, exists=False)
        if candidate_root.exists():
            refuse("occupied fresh candidate snapshot")
        for source in _rtl_files(staged):
            _regate_path(source, run_p)
        # Keep absolute gate-report paths valid in the retained staged tree.
        # The promotable copy is separate; no archived report is rewritten.
        promotion_project = archive / "promotion_project"
        shutil.copytree(staged, promotion_project, symlinks=True)
        if _regate_project_tree(promotion_project) != _regate_project_tree(staged):
            refuse("staged output changed while preparing promotion")
        recheck()
        if candidate_root.exists():
            refuse("fresh candidate snapshot occupied during preparation")
        _write_immutable_json(archive / "promotion.json", {"output": got, "staged_tree": _regate_project_tree(staged)})
        # Any interruption after this point is unknown state and blocks resume.
        promoted = True
        project.rename(archive / "prior_project")
        promotion_project.rename(project)
        phases = fpa.attribute(project, routing=result.get("routing_verdict") or {},
                               entry="2", evidence=result.get("evidence"), exit_step=result["exit"],
                               rtl_present=True, artefact_collected=True)
        new_task = _make_ai_review_task(
            pid, project, got, result.get("routing_verdict") or {}, int(process.rc), run_p, "AI_REPAIR",
            program_phases=phases, verification_challenges=inherited,
            program_candidate=task["program_candidate_snapshot"],
            repair_parent_candidate=task["repair_parent_candidate_snapshot"],
            repair_provenance=provenance, repair_input_candidate=input_candidate,
            review_key=key, archive_key=key)
        new_task["pre_gate_input"] = _bind_pre_gate_output(
            preserved, new_task["rtl_sha256"])
        action = {"schema": _PROGRAM_REGATE_SCHEMA, "actor": "PROGRAM",
                  "program_identity": identity, "archive_path": str(archive),
                  "request_sha256": request_sha,
                  "signed_input_sha256": signed,
                  "input_rtl_sha256": signed,
                  "input_manifest_path": str(manifest_path),
                  "stale_output_sha256": task["rtl_sha256"],
                  "prior_output_rtl_sha256": task["rtl_sha256"],
                  "new_output_sha256": new_task["rtl_sha256"],
                  "output_rtl_sha256": new_task["rtl_sha256"],
                  "program_version_before": before,
                  "program_version_after": after,
                  "attributed_to": "PROGRAM",
                  "author_signature_unchanged": True,
                  "repair_authorized": False,
                  "status": "FRESH_REVIEW_REQUIRED",
                  "entry": "2", "exit": result["exit"], "runner_rc": process.rc,
                  "accepted": False}
        new_task["program_regate"] = action
        tasks[ids.index(pid)] = new_task
        _write_immutable_json(archive / "transition.json", {"prior_task": task, "new_task": new_task})
        _write_jsonl(task_path, tasks)
        program_first_phases = result.get("program_first_phases") or result.get("phases") or {}
        if program_first_phases:
            result["program_first_phases"] = program_first_phases
            phases["phase2_solving"] = program_first_phases.get("phase2_solving", {})
            phases["phase4_debugging"] = program_first_phases.get("phase4_debugging", {})
        result.update({"accepted": False, "rc": process.rc, "candidate_ready": True,
                       "candidate_origin": "AI_REPAIR", "awaiting_ai": True,
                       "awaiting_ai_review": True, "ai_repair_required": False,
                       "review_task": new_task["review_path"], "program_regate": action,
                       "phases": phases})
        solve["four_phase_summary"] = _four_phase_rollup(fpa, results)
        _atomic_write_json(solve_path, solve)
        repairs = [t for t in _read_jsonl(run_p / _REPAIR_WORKLIST) if t.get("id") != pid]
        _write_jsonl(run_p / _REPAIR_WORKLIST, repairs)
        outcomes = [t for t in acceptance.get("review_outcomes") or [] if t.get("id") != pid]
        outcomes.append({"id": pid, "status": "PENDING", "reasons": ["fresh independent review required"]})
        acceptance.update({"schema": _ACCEPTANCE_SCHEMA, "status": "PENDING",
                           "review_outcomes": outcomes, "total": len(results),
                           "accepted_ids": [r["id"] for r in results if r.get("accepted")],
                           "accepted": sum(r.get("accepted") is True for r in results),
                           "pending_review": sum(o.get("status") in {"PENDING", "REJECTED"} for o in outcomes),
                           "pending_repair": len(repairs)})
        _atomic_write_json(acceptance_path, acceptance)
        _write_immutable_json(archive / "complete.json", action)
    except Exception as exc:
        if not promoted:
            _write_immutable_json(archive / "failed.json", {
                "schema": _PROGRAM_REGATE_SCHEMA, "request_sha256": request_sha,
                "intent_sha256": _review_task_digest(intent), "promotion_started": False,
                "status": "REFUSED", "reason": str(exc)})
        raise
    print(f"  {pid}: PROGRAM_REGATE_APPLIED; program {before} -> {after}; "
          f"signed input {signed[:12]} re-entered; PROGRAM-attributed; "
          "FRESH_REVIEW_REQUIRED; signature unchanged; no repair permit")
    return 2


def cmd_resume(bench: str, dataset: str, run: str, jobs: int = 1,
               heavy_jobs: int | None = None,
               worker_threads: int = 0,
               review_correction: str | None = None,
               program_regate: str | None = None,
               program_retry: str | None = None) -> int:
    """Run the sole resume coordinator under an exclusive run-root lock.

    TWO explicit operations remain, separate and mutually exclusive: a review
    correction and the ONE Program re-entry. Each keeps its own refusal token
    so the caller is told WHICH operation refused, and no combination is
    silently ordered for them.

    `program_retry` is the DEPRECATED alias of `program_regate` (issue #2047,
    which merged `--program-retry` into `--program-regate`). It maps onto the
    same operation, under the same refusal token, and prints a deprecation
    line, so a caller written against the old front door does not break
    silently. Giving both names at once is refused rather than ordered.
    """
    try:
        if program_regate is not None and program_retry is not None:
            raise ValueError(f"{_REGATE_REFUSED}: --program-retry is the "
                             "deprecated alias of --program-regate; give one")
        if program_retry is not None:
            print(_PROGRAM_RETRY_DEPRECATION, file=sys.stderr)
            program_regate, program_retry = program_retry, None
        if review_correction is not None and program_regate is not None:
            raise ValueError(f"{_REGATE_REFUSED}: cannot combine with review correction")
        if review_correction is not None or program_regate is not None:
            # Check BEFORE resolve/open of the persistent coordinator lock.
            _correction_path(Path(run) / _COORDINATOR_LOCK,
                             Path(run).absolute().resolve(), exists=False,
                             token=(_CORRECTION_REFUSED
                                    if review_correction is not None
                                    else _REGATE_REFUSED))
        with _run_root_coordinator_lock(Path(run), "resume"):
            _guard_program_regate_journals(Path(run).resolve())
            if review_correction is not None:
                try:
                    _apply_review_correction(Path(run).resolve(), Path(review_correction))
                except (KeyError, TypeError, AttributeError) as exc:
                    raise ValueError("REVIEW_CORRECTION_REFUSED: malformed evidence: "
                                     f"{type(exc).__name__}: {exc}") from exc
            if program_regate is not None:
                try:
                    return _apply_program_regate(bench, Path(run).resolve(),
                                                 Path(program_regate), worker_threads)
                except (KeyError, TypeError, AttributeError, IndexError) as exc:
                    raise ValueError(f"{_REGATE_REFUSED}: malformed evidence: "
                                     f"{type(exc).__name__}: {exc}") from exc
            return _cmd_resume_locked(
                bench, dataset, run, jobs=jobs, heavy_jobs=heavy_jobs,
                worker_threads=worker_threads)
    except _CoordinatorBusy as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError) as exc:
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
    ap.add_argument("--review-correction", metavar="REQUEST.json",
                    help="with --resume: explicitly archive and advance one "
                         "unaccepted review on unchanged RTL; requires "
                         "hash-bound blind AI correction evidence; never "
                         "accepts, supersedes a challenge, or permits repair")
    ap.add_argument("--program-regate", metavar="REQUEST.json",
                    help="with --resume: the ONE Program re-entry operation. "
                         "Re-run the FIXED Program on one preserved, signed "
                         "pre-gate input in a staged project under the resume "
                         "coordinator lock. Requires BOTH Program identities "
                         "to have moved -- the declared version pair AND the "
                         "executable source tree -- plus the preserved input "
                         "and an unaccepted task. Binds the new output to the "
                         "SAME author signature, attributes the regenerated "
                         "bytes to the PROGRAM, preserves history, and never "
                         "accepts, publishes or permits repair: a fresh "
                         "independent review is still required.")
    ap.add_argument("--program-retry", metavar="REQUEST.json",
                    help="DEPRECATED alias of --program-regate (issue #2047 "
                         "merged the two Program re-entry operations into "
                         "one). Runs the merged operation and prints a "
                         "deprecation line; removed one version after "
                         "v1.17.75.")
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
    if a.review_correction and (not a.resume or a.solve or a.score or a.show or a.list):
        ap.error("--review-correction requires --resume alone")
    if a.program_regate and (not a.resume or a.solve or a.score or a.show or a.list):
        ap.error("--program-regate requires --resume alone")
    if a.program_regate and a.review_correction:
        ap.error("--program-regate and --review-correction are separate "
                 "operations; run one per resume")
    if a.program_retry and (not a.resume or a.solve or a.score or a.show or a.list or a.review_correction):
        ap.error("--program-retry requires --resume alone, without --review-correction")
    if a.program_retry and a.program_regate:
        ap.error("--program-retry is the DEPRECATED alias of --program-regate "
                 "(issue #2047 merged them into one operation); give one")

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
    if a.resume or a.solve:
        # Main thread, before any worker exists: see `_install_orphan_guard`.
        _install_orphan_guard()
    if a.resume:
        if not (a.dataset and a.run):
            raise SystemExit("--resume requires --dataset and --run")
        sys.exit(cmd_resume(
            a.bench, a.dataset, a.run, jobs=a.jobs,
            heavy_jobs=a.heavy_jobs, worker_threads=a.worker_threads,
            review_correction=a.review_correction,
            program_regate=a.program_regate,
            program_retry=a.program_retry))
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
