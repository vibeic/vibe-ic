#!/usr/bin/env python3
"""_watchdog.py — the plugin-wide PROGRESS-STALL supervision primitive.

Owner directive (v1.3.47): "timeout estimation is not professional; have a
general way to let a sub-process ALWAYS finish its job." A fixed wall-clock /
size-ESTIMATE kill is fundamentally wrong — it murders a healthy, still-
progressing process because the guess was too small (proven on ibex: a ~60 min
detailed_route was killed at a 4395s estimate while actively routing). This
module supervises a sub-process by FORWARD PROGRESS, not by a runtime guess:

    Kill ONLY a process that has made NO forward progress for a grace window;
    NEVER kill one that is still progressing → any progressing sub-process
    runs to completion, however long that legitimately takes.

Forward progress = OR of generic, transport-AGNOSTIC signals:
  • captured stdout/stderr grew (bytes advanced) — universal, every tool emits,
  • an optional external log file grew (size or mtime advanced),
  • an optional CPU probe advanced (utime+stime of the job's processes).
ANY signal advancing resets the grace clock. So a CPU-bound-but-quiet phase is
kept alive by the CPU signal, and a chatty phase by the output signal; a genuine
deadlock (flat everything) trips the grace and dies. `stall_grace_s` is the ONE
tunable — "how long may the job be SILENT *and* idle before we call it hung" —
NOT a runtime estimate. `hard_ceiling_s` (default 24h) is a pathological-
infinite-loop backstop ONLY (a CPU-burning loop that never goes idle), NOT the
primary control.

DESIGN — this module knows NOTHING about docker or EDA. The caller INJECTS:
  • `cpu_probe(proc) -> Optional[float]` — HOW to read the job's CPU (docker
    exec ps in-container, host /proc, …). Return None when unavailable.
  • `kill(proc, reason)` — HOW to terminate the job tree. It must select its
    victims by IDENTITY, never by matching a command line: see
    `_docker_watchdog.kill_supervised_job` (stamped pid + /proc starttime,
    plus the ppid-walked descendants) for the in-container case and
    `_owned_process_supervisor` for the host case. This line used to read
    "pkill -f marker in a container" — it described the defect as the design,
    and both callers implemented exactly that (2026-08-27: one run's watchdog
    SIGTERMed another run's healthy tool inside the shared container).
  • `log_path` — an external tee'd log to also watch for growth.
  • `popen_factory(cmd, **kw) -> proc` — HOW to launch (default: host
    subprocess.Popen). `proc` must expose `.wait(timeout)` and `.kill()`.
The SUPERVISION LOGIC (the meter + the grace/ceiling loop) is fully general
here, so a docker-exec'd in-container tool, a host subprocess, or any future
caller reuse it unchanged. The sibling `loop_guard(...)` (while/poll/retry/
convergence-loop face) lives here too and REUSES `ProgressMeter`: it is the
SECOND face of the primitive — for IN-PROCESS loops (NOT sub-processes) it
gives the same guarantee (a loop can NEVER spin forever) via a bounded
`max_iter` hard cap plus a no-progress break.

THE THIRD KILL — `abort_probe` (a PROGRESSING job that is going NOWHERE).
Progress-stall supervision answers "is it alive?", never "is it getting
anywhere?". A tool can burn CPU and emit output for a full day while its own
convergence metric sits flat — e.g. a detailed router re-iterating at a
constant violation count. That job is NOT hung (every signal advances, so the
stall grace never trips) and NOT pathological-infinite (it exits eventually),
so BOTH existing kills correctly decline to touch it, and the CPU is spent for
nothing. `abort_probe() -> Optional[str]` lets the CALLER supply the domain
convergence read: return None to keep running, or a REASON string to stop now.
The primitive stays domain-blind — it only polls the predicate and kills.
§4.05: opt-in (None ⇒ byte-identical behaviour), and an abort is a DISTINCT
outcome/rc, never dressed up as a natural exit or as a hang.

Public API (stable — an enforcement gate builds against it):
  RC_STALLED, RC_CEILING, RC_ABORTED  — distinct return codes for the 3 kills
  SupervisedResult(rc,out,err,outcome,elapsed_s,abort_reason)
  ProgressMeter(size_fn, log_fn, cpu_fn)      — signal fusion → monotonic score
  supervise(proc, progress_probe, kill_fn, *, poll_s, stall_grace_s,
            hard_ceiling_s, wait_fn=None, clock=time.monotonic,
            abort_probe=None) -> (outcome, rc)
  run_supervised(cmd, *, log_path=None, output_progress=True,
                 domain_progress_probe=None,
                 stall_grace_s=1800, poll_s=30,
                 hard_ceiling_s=86400, cpu_probe=None, kill=None,
                 popen_factory=None, env=None, abort_probe=None)
                 -> SupervisedResult
  loop_guard(name, *, max_iter, stall_iters=None, progress_fn=None,
             clock=time.monotonic) -> LoopGuard   # in-process convergence loops
  LoopGuard(...).reason ∈ {'converged','max_iter','stalled'}; .iterations

chip-AGNOSTIC + tool-AGNOSTIC + pure: generic file/CPU counters only.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

# Distinct return codes: STALLED (no forward progress) is NOT the natural rc and
# NOT the old rc=124 estimate-timeout; the CEILING backstop keeps the historical
# rc=124 "wall-clock" code so existing downstream diagnostics still read it.
RC_STALLED = 199
RC_CEILING = 124
# ABORTED — the caller's own convergence predicate said "this is going
# nowhere". Distinct from STALLED (the job WAS progressing) and from CEILING
# (it would have finished): the run is stopped on PURPOSE, so a downstream
# reader can tell a deliberate no-progress abort from a hang.
RC_ABORTED = 198

DEFAULT_POLL_S = 30              # cheap probe cadence (negligible overhead)
DEFAULT_STALL_GRACE_S = 1800     # 30 min of ZERO forward progress ⇒ hung
DEFAULT_HARD_CEILING_S = 86_400  # 24 h absolute backstop (pathological loop)


@dataclass
class SupervisedResult:
    """Outcome of a supervised sub-process. `.rc` is the return code
    (RC_STALLED on a stall kill, RC_CEILING on the backstop kill, else the
    process's natural rc). `.out`/`.err` are decoded str (never bytes)."""
    rc: int
    out: str
    err: str
    # 'natural' | 'stalled' | 'ceiling' | 'aborted' | 'launch_error'
    outcome: str
    elapsed_s: float = 0.0
    # The `abort_probe` reason, present ONLY on outcome == 'aborted'.
    abort_reason: str = ""
    # §4.05 input-scope record (vibe-ic#1079): what was imposed on the child,
    # or why nothing was. Always present, so "was it enforced?" is answerable
    # from the result rather than from the absence of a complaint.
    scope: dict = field(default_factory=dict)

    @property
    def stalled(self) -> bool:
        return self.outcome in ("stalled", "ceiling")

    @property
    def aborted(self) -> bool:
        """True iff the caller's convergence predicate stopped the job. NOT
        folded into `.stalled`: a deliberate no-progress abort and a hang are
        different findings and must stay tellable apart."""
        return self.outcome == "aborted"


class ProgressMeter:
    """Fuse forward-progress signals into a MONOTONIC non-decreasing score so
    the supervisor sees "progress" iff a signal genuinely ADVANCED.

    Sources, all individually non-decreasing:
      • captured-output bytes  (a temp file the child appends to — only grows),
      • external tee'd-log advances  (size or mtime change → +1 event),
      • CPU seconds  (carried forward; counted only on a strict increase).
    A signal that is momentarily UNAVAILABLE (probe returned None) CARRIES
    FORWARD its last value — a signal *disappearing* is never mistaken for
    progress. This closes the None-flap where an intermittently-failing CPU
    probe (None ↔ frozen value) would otherwise reset the grace clock every
    poll and let a genuinely hung job squat until the ceiling. pure + generic."""

    def __init__(self,
                 size_fn: Optional[Callable[[], float]] = None,
                 log_fn: Optional[Callable[[], object]] = None,
                 cpu_fn: Optional[Callable[[], Optional[float]]] = None):
        self._size_fn = size_fn
        self._log_fn = log_fn
        self._cpu_fn = cpu_fn
        self._log_events = 0.0
        self._last_log = None
        self._last_cpu = 0.0

    def sample(self) -> float:
        score = 0.0
        if self._size_fn is not None:
            try:
                score += float(self._size_fn() or 0)
            except Exception:  # nosec — a probe error is just "no reading"
                pass
        if self._log_fn is not None:
            try:
                sig = self._log_fn()
            except Exception:  # nosec
                sig = None
            if sig is not None:
                if self._last_log is not None and sig != self._last_log:
                    self._log_events += 1.0
                self._last_log = sig
        score += self._log_events
        if self._cpu_fn is not None:
            try:
                cpu = self._cpu_fn()
            except Exception:  # nosec
                cpu = None
            if cpu is not None and cpu > self._last_cpu:
                self._last_cpu = cpu
        score += self._last_cpu
        return score


def _default_wait(proc, timeout: float) -> Optional[int]:
    """Block up to `timeout`s for the process to exit. Returns its rc if it
    exited, else None. Uses proc.wait so a FAST process returns IMMEDIATELY on
    exit (never idles a full poll window) — this is what makes short calls
    prompt while long calls poll cheaply."""
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    except Exception:  # nosec — fall back to a non-blocking poll
        try:
            return proc.poll()
        except Exception:  # nosec
            return None


def _default_kill(proc, reason: str) -> None:
    try:
        proc.kill()
    except Exception:  # nosec
        pass


def supervise(proc, progress_probe: Callable[[], object],
              kill_fn: Callable[[object, str], None], *,
              poll_s: float, stall_grace_s: float, hard_ceiling_s: float,
              wait_fn: Optional[Callable[[object, float], Optional[int]]] = None,
              clock: Callable[[], float] = time.monotonic,
              abort_probe: Optional[Callable[[], Optional[str]]] = None
              ) -> Tuple[str, Optional[int]]:
    """Generic progress-stall control loop over an already-launched process.

    `progress_probe()` returns a comparable token; forward progress is signalled
    by the token CHANGING between polls (use a ProgressMeter for the robust
    monotonic score). `kill_fn(proc, reason)` terminates the job tree. Returns
    ``(outcome, exit_code)`` with outcome ∈
    {'natural','stalled','ceiling','aborted'}.
    Kills ONLY after NO progress for `stall_grace_s`; `hard_ceiling_s` is a
    pathological backstop only. `wait_fn`/`clock` are injectable for tests.

    `abort_probe()` (optional) is the caller's DOMAIN convergence read, polled
    on the same cadence: returning a non-empty reason kills the job as
    'aborted'. It is checked LAST, so a job that exits on its own in this poll
    window is always reported 'natural' — an abort never steals a completed
    run's result. A probe that raises is treated as "no opinion" (never aborts
    on a probe bug)."""
    wait_fn = wait_fn or _default_wait
    start = clock()
    last_progress = start
    try:
        last_token = progress_probe()
    except Exception:  # nosec — probe error ⇒ no signal this poll
        last_token = None
    while True:
        rc = wait_fn(proc, poll_s)
        if rc is not None:
            return "natural", rc
        now = clock()
        try:
            token = progress_probe()
        except Exception:  # nosec
            token = None
        if token is not None and token != last_token:
            last_progress = now
        if token is not None:
            last_token = token
        if now - last_progress > stall_grace_s:
            kill_fn(proc, "stalled")
            return "stalled", None
        if now - start > hard_ceiling_s:
            kill_fn(proc, "ceiling")
            return "ceiling", None
        if abort_probe is not None:
            try:
                reason = abort_probe()
            except Exception:  # nosec — a probe bug must never kill a job
                reason = None
            if reason:
                kill_fn(proc, "aborted")
                return "aborted", None


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", errors="replace")
    return v


def run_supervised(cmd, *, log_path=None, output_progress: bool = True,
                   domain_progress_probe: Optional[Callable[[], object]] = None,
                   stall_grace_s: float = DEFAULT_STALL_GRACE_S,
                   poll_s: float = DEFAULT_POLL_S,
                   hard_ceiling_s: float = DEFAULT_HARD_CEILING_S,
                   cpu_probe: Optional[Callable[[object], Optional[float]]] = None,
                   kill: Optional[Callable[[object, str], None]] = None,
                   popen_factory: Optional[Callable[..., object]] = None,
                   env=None,
                   merge_stderr: bool = False,
                   scope_project=None,
                   scope_step=None,
                   scope_guard_dir=None,
                   cwd=None,
                   wait_fn=None,
                   clock: Callable[[], float] = time.monotonic,
                   abort_probe: Optional[Callable[[], Optional[str]]] = None
                   ) -> SupervisedResult:
    """Launch `cmd` and supervise it by FORWARD PROGRESS (see module docstring).

    Captures stdout/stderr to OS temp files (no pipe-buffer deadlock, decoded to
    str on return). Progress = output grew (unless ``output_progress=False``)
    OR `log_path` grew OR `domain_progress_probe()` changed OR
    `cpu_probe(proc)` advanced. A caller with a structured domain event channel
    can disable output progress so a chatty subject cannot impersonate domain
    progress. A still-progressing job is
    NEVER killed; a job idle+silent for `stall_grace_s` is killed via
    `kill(proc, 'stalled')` → rc=RC_STALLED; the `hard_ceiling_s` backstop kills
    → rc=RC_CEILING. `cpu_probe`/`kill`/`popen_factory` inject the transport
    (docker/host/…); the default launches a host subprocess and kills it with
    proc.kill(). `abort_probe` (optional) is the caller's convergence read — a
    non-empty reason stops the job → rc=RC_ABORTED, `outcome='aborted'`, and the
    reason is echoed on `.abort_reason` and appended to `.err`.
    Returns a SupervisedResult."""
    popen_factory = popen_factory or (
        lambda c, **kw: subprocess.Popen(c, **kw))
    kill = kill or _default_kill

    # §4.05 AS A MECHANISM (vibe-ic#1079). This is the one place a supervised
    # step becomes a process, so it is the one place its input scope can be
    # imposed rather than reviewed. OFF unless `VIBEIC_STEP_SCOPE` is set: with
    # the switch unset `child_env` returns `env` unchanged — including `None`,
    # so a caller that passed nothing still INHERITS, byte-for-byte as before
    # this existed. `scope_step` is the flow step id; the permitted paths are
    # read from that step's `required_inputs` in the flow YAML, never from a
    # second declaration.
    scope_meta = {"enforced": False}
    if scope_step is not None:
        try:
            import step_input_scope as _sis  # noqa: PLC0415
            env, scope_meta = _sis.child_env(
                env, project=scope_project, step_id=scope_step,
                guard_dir=scope_guard_dir)
        except Exception as _exc:  # noqa: BLE001
            # A guard that cannot be built must SAY so. Silently continuing
            # unenforced is the vacuous pass this repo removes from gates one
            # at a time; the run continues (this is not a gate) but the record
            # says the scope was not imposed.
            scope_meta = {"enforced": False, "error": repr(_exc)}

    out_f = tempfile.TemporaryFile()
    # `merge_stderr` sends stderr down the SAME descriptor as stdout, which is
    # what `2>&1 | tee` and a human at a terminal see. Separately captured
    # streams re-order under Python's own buffering -- stderr can arrive first
    # while the final stdout verdict flushes at exit -- so for a caller whose
    # comparison is over the combined text, the split is not cosmetic.
    err_f = None if merge_stderr else tempfile.TemporaryFile()

    def _size():
        try:
            n = os.fstat(out_f.fileno()).st_size
            if err_f is not None:
                n += os.fstat(err_f.fileno()).st_size
            return n
        except OSError:
            return 0

    def _log():
        if log_path is None:
            return None
        try:
            st = os.stat(os.fspath(log_path))
            return (st.st_size, st.st_mtime)
        except OSError:
            return None

    t0 = time.monotonic()
    try:
        _kw = {"stdout": out_f,
               "stderr": (subprocess.STDOUT if merge_stderr else err_f),
               "env": env}
        if cwd is not None:
            # Passed only when set: an injected popen_factory that predates
            # this parameter keeps working untouched.
            _kw["cwd"] = cwd
        proc = popen_factory(cmd, **_kw)
    except FileNotFoundError as e:
        out_f.close()
        if err_f is not None:
            err_f.close()
        return SupervisedResult(127, "", f"COMMAND_NOT_FOUND: {e}",
                                "launch_error", 0.0, scope=scope_meta)

    def _domain_or_log():
        domain = (domain_progress_probe()
                  if domain_progress_probe is not None else None)
        log = _log() if log_path is not None else None
        if domain_progress_probe is not None and log_path is not None:
            return (domain, log)
        return domain if domain_progress_probe is not None else log

    meter = ProgressMeter(
        size_fn=(_size if output_progress else None),
        log_fn=(_domain_or_log if (domain_progress_probe is not None
                                   or log_path is not None) else None),
        cpu_fn=((lambda: cpu_probe(proc)) if cpu_probe is not None else None))

    # The abort REASON belongs to the caller's predicate, so capture it as the
    # predicate fires rather than re-invoking it after the kill (a second call
    # could read a different state and report a reason that never triggered).
    _abort_reason = ""

    def _abort_capture() -> Optional[str]:
        nonlocal _abort_reason
        reason = abort_probe()
        if reason:
            _abort_reason = str(reason)
        return reason

    outcome, rc = supervise(
        proc, meter.sample, kill,
        poll_s=poll_s, stall_grace_s=stall_grace_s,
        hard_ceiling_s=hard_ceiling_s, wait_fn=wait_fn, clock=clock,
        abort_probe=(_abort_capture if abort_probe is not None else None))

    # Reap and collect whatever partial output exists.
    try:
        proc.wait(timeout=60)
    except Exception:  # nosec — already killed; don't hang the caller
        pass

    def _read(f):
        try:
            f.seek(0)
            return _as_text(f.read())
        except OSError:
            return ""

    out = _read(out_f)
    err = _read(err_f) if err_f is not None else ""
    out_f.close()
    if err_f is not None:
        err_f.close()
    elapsed = time.monotonic() - t0

    # §4.05 LIVENESS (vibe-ic#1079). The child has exited, so this is the only
    # moment the parent can learn whether the in-child guard actually LOADED.
    # A `sitecustomize` can silently fail to install for reasons invisible from
    # here (`-S`, `-E`, a child that rewrote PYTHONPATH, a non-CPython
    # interpreter), and `enforced: True` must not stand on having merely SET
    # the variables. `liveness()` downgrades the record when the marker is
    # absent, so a reader cannot mistake "we asked for it" for "it happened".
    if scope_meta.get("enforced"):
        try:
            import step_input_scope as _sis  # noqa: PLC0415
            scope_meta = _sis.liveness(scope_meta)
        except Exception as _exc:  # noqa: BLE001
            scope_meta = dict(scope_meta)
            scope_meta["enforced"] = False
            scope_meta["liveness"] = f"could not confirm: {_exc!r}"

    if outcome == "stalled":
        return SupervisedResult(
            RC_STALLED, out,
            err + (f"\nWATCHDOG_STALLED: configured forward-progress signals "
                   f"did not advance for > {stall_grace_s:g}s — killed as "
                   "hung, not slow."),
            "stalled", elapsed, scope=scope_meta)
    if outcome == "ceiling":
        return SupervisedResult(
            RC_CEILING, out,
            err + (f"\nWATCHDOG_CEILING: hard backstop {hard_ceiling_s:g}s "
                   f"exceeded (pathological non-idle loop) — killed."),
            "ceiling", elapsed, scope=scope_meta)
    if outcome == "aborted":
        return SupervisedResult(
            RC_ABORTED, out,
            err + (f"\nWATCHDOG_ABORTED: {_abort_reason}"),
            "aborted", elapsed, _abort_reason, scope=scope_meta)
    return SupervisedResult(rc if rc is not None else 0, out, err,
                            "natural", elapsed, scope=scope_meta)


# ===========================================================================
# loop_guard — the SECOND face of the primitive: for IN-PROCESS convergence /
# poll / retry loops (NOT sub-processes). Same guarantee as `supervise`: the
# loop can NEVER spin forever. Two independent stop conditions:
#   • `max_iter`   — a HARD cap on iteration count (always present).
#   • no-progress  — if the caller-supplied `progress_fn` value fails to IMPROVE
#     for `stall_iters` consecutive iterations, stop (analogous to the stall
#     grace of `supervise`, counted in ITERATIONS instead of seconds).
# The caller `break`ing out early is recorded as 'converged'. `ProgressMeter`
# (cpu_fn face → running MAX, strict-increase = improvement, None carried
# forward) is REUSED as the monotonic progress tracker, so the same robust
# fusion semantics apply. Pure + injectable-clock (only for `.elapsed_s`
# observability) so tests run in milliseconds. chip/tool-AGNOSTIC.
# ===========================================================================

class LoopGuard:
    """Bounded, no-progress-aware driver for an in-process loop.

    Use as the loop's iterable:

        g = loop_guard("postroute_timing_repair", max_iter=20, stall_iters=3,
                       progress_fn=lambda: resolved_count)
        for i in g:
            ... one iteration of work ...
            if all_done:
                break                     # → g.reason == 'converged'
        # else g.reason is 'max_iter' (hit the cap) or 'stalled' (no progress)

    Guarantees the loop terminates: it yields at most `max_iter` times, and if
    `progress_fn`/`stall_iters` are given it stops early once progress plateaus.
    `progress_fn()` returns a number that should INCREASE as the loop makes
    headway (e.g. #resolved, -error, iteration score); return None when a
    reading is momentarily unavailable (carried forward, never mistaken for
    progress). `reason` and `iterations` are readable after the loop."""

    def __init__(self, name: str, *, max_iter: int,
                 stall_iters: Optional[int] = None,
                 progress_fn: Optional[Callable[[], Optional[float]]] = None,
                 clock: Callable[[], float] = time.monotonic):
        if max_iter is None or int(max_iter) < 1:
            raise ValueError("loop_guard requires max_iter >= 1 (a hard cap)")
        if stall_iters is not None and int(stall_iters) < 1:
            raise ValueError("stall_iters must be >= 1 when given")
        self.name = name
        self.max_iter = int(max_iter)
        self.stall_iters = None if stall_iters is None else int(stall_iters)
        self._progress_fn = progress_fn
        self._clock = clock
        self.reason: Optional[str] = None      # 'converged'|'max_iter'|'stalled'
        self.iterations = 0
        self.elapsed_s = 0.0

    def __iter__(self):
        start = self._clock()
        meter = (ProgressMeter(cpu_fn=self._progress_fn)
                 if (self._progress_fn is not None and self.stall_iters)
                 else None)
        # Prime the baseline BEFORE the first iteration so improvement is
        # measured against the loop's initial state.
        last = meter.sample() if meter is not None else None
        no_improve = 0
        i = 0
        try:
            while i < self.max_iter:
                self.iterations = i + 1
                yield i
                i += 1
                if meter is not None:
                    cur = meter.sample()
                    if cur > last:               # strict increase = progress
                        last = cur
                        no_improve = 0
                    else:
                        no_improve += 1
                        if no_improve >= self.stall_iters:
                            self.reason = "stalled"
                            return
            self.reason = "max_iter"
        except GeneratorExit:
            # The caller broke out (or was GC'd) before hitting a stop
            # condition → it decided the loop was satisfied.
            if self.reason is None:
                self.reason = "converged"
            raise
        finally:
            self.elapsed_s = self._clock() - start

    @property
    def stopped_early(self) -> bool:
        """True when the guard itself stopped the loop (cap or stall) rather
        than the caller converging out."""
        return self.reason in ("max_iter", "stalled")


def loop_guard(name: str, *, max_iter: int,
               stall_iters: Optional[int] = None,
               progress_fn: Optional[Callable[[], Optional[float]]] = None,
               clock: Callable[[], float] = time.monotonic) -> "LoopGuard":
    """Factory for a :class:`LoopGuard` — see its docstring. Iterate it to drive
    a bounded, no-progress-aware in-process loop; read ``.reason`` afterward."""
    return LoopGuard(name, max_iter=max_iter, stall_iters=stall_iters,
                     progress_fn=progress_fn, clock=clock)


# ===========================================================================
# HOST progress probe — the third face of the primitive.
#
# `run_supervised` is transport-AGNOSTIC: it asks the CALLER to inject a
# `cpu_probe`. Two injections shipped (both docker-exec: `_docker_watchdog`
# and `phase3_one_shot_runner`), so every HOST caller that wanted progress
# supervision had no probe to reach for and fell back to the one thing that
# needs no probe — `subprocess.run(..., timeout=N)`. That is why a wall-clock
# budget kept being re-invented: the honest alternative was missing, not
# rejected. This section supplies it.
#
# A host job's forward progress is read from /proc, tree-wide:
#   • CPU  — utime+stime of every process in the tree (a silent but computing
#     job is PROGRESSING, and must never be killed),
#   • I/O  — read_bytes+write_bytes (a job blocked on a slow disk is
#     PROGRESSING; interpreter boot alone moves this),
# summed over the TREE, not the direct child: a helper that shells out and
# then blocks in `wait()` has all of its progress in a grandchild, and probing
# only the child would read that healthy job as frozen.
#
# Tree-wide is also what makes the reading HONEST in the other direction: a
# process whose whole tree shows zero CPU and zero I/O across the grace window
# is not slow, it is stuck. That is a verdict about the JOB, not about the
# clock — which is the entire point.
# ===========================================================================

_CLK_TCK = None


def _clk_tck() -> float:
    """SC_CLK_TCK — the unit of /proc/<pid>/stat's utime/stime fields."""
    global _CLK_TCK
    if _CLK_TCK is None:
        try:
            _CLK_TCK = float(os.sysconf("SC_CLK_TCK")) or 100.0
        except (ValueError, OSError, AttributeError):  # nosec
            _CLK_TCK = 100.0
    return _CLK_TCK


def _proc_children_map() -> dict:
    """ppid -> [pid, ...] for every live process readable in /proc.

    One pass over /proc, so walking a tree of any depth costs one scan. A pid
    that vanishes mid-scan is simply absent — a dead process contributes no
    progress, and its CPU is already carried forward by the meter."""
    kids: dict = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return kids
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % name, "rb") as fh:
                data = fh.read()
        except OSError:  # nosec — raced with exit, or not ours to read
            continue
        # comm is parenthesised and may itself contain spaces/parens: fields
        # after the LAST ')' are the ones with fixed positions.
        cut = data.rfind(b")")
        if cut < 0:
            continue
        rest = data[cut + 2:].split()
        if len(rest) < 2:
            continue
        try:
            kids.setdefault(int(rest[1]), []).append(int(name))
        except ValueError:  # nosec
            continue
    return kids


def _pid_cpu_s(pid: int):
    """utime+stime of ONE pid, in seconds; None when unreadable."""
    try:
        with open("/proc/%d/stat" % pid, "rb") as fh:
            data = fh.read()
    except OSError:  # nosec
        return None
    cut = data.rfind(b")")
    if cut < 0:
        return None
    rest = data[cut + 2:].split()
    # after the last ')': state, ppid, pgrp, session, tty, tpgid, flags,
    # minflt, cminflt, majflt, cmajflt, utime, stime, ...
    if len(rest) < 13:
        return None
    try:
        return (float(rest[11]) + float(rest[12])) / _clk_tck()
    except ValueError:  # nosec
        return None


def _pid_io_bytes(pid: int):
    """read_bytes+write_bytes of ONE pid; None when unreadable.

    /proc/<pid>/io is readable only for our own processes — which is exactly
    the case here (we launched the job) — and absent on kernels built without
    CONFIG_TASK_IO_ACCOUNTING. Absent ⇒ None ⇒ the CPU signal carries the
    reading alone; never an error, and never mistaken for 'no progress'."""
    try:
        with open("/proc/%d/io" % pid, "rb") as fh:
            total = 0.0
            for line in fh:
                if line.startswith(b"read_bytes:") or \
                        line.startswith(b"write_bytes:"):
                    try:
                        total += float(line.split(b":", 1)[1])
                    except ValueError:  # nosec
                        pass
            return total
    except OSError:  # nosec
        return None


def host_tree_progress(pid: int):
    """Forward-progress reading for the host process TREE rooted at `pid`.

    Returns CPU-seconds + I/O-megabytes summed tree-wide (one comparable float
    that only grows while the job works), or None when nothing in the tree is
    readable — i.e. the job is gone. Returning None rather than 0.0 on a dead
    tree matters: `ProgressMeter` CARRIES FORWARD an unavailable signal, so a
    process exiting can never look like a progress RESET, and an unreadable
    /proc can never look like a stall.

    I/O is scaled to megabytes so neither signal swamps the other; the meter
    only asks whether the number ADVANCED, so the scale is presentational."""
    seen = False
    total = 0.0
    kids = _proc_children_map()
    stack = [int(pid)]
    walked = set()
    while stack:
        cur = stack.pop()
        if cur in walked:
            continue
        walked.add(cur)
        cpu = _pid_cpu_s(cur)
        if cpu is not None:
            seen = True
            total += cpu
        io = _pid_io_bytes(cur)
        if io is not None:
            seen = True
            total += io / 1e6
        stack.extend(kids.get(cur, ()))
    return total if seen else None


def host_cpu_probe(proc):
    """`cpu_probe` injection for `run_supervised` over a HOST subprocess.

    Signature matches what `run_supervised` calls: it is handed the live proc
    object and returns a monotonic progress reading (or None)."""
    pid = getattr(proc, "pid", None)
    if pid is None:
        return None
    return host_tree_progress(pid)


def run_host_supervised(cmd, **kw) -> "SupervisedResult":
    """`run_supervised` with the HOST /proc progress probe already injected.

    This is the honest replacement for `subprocess.run(cmd, timeout=N)`: it
    bounds NO-PROGRESS, never RUNTIME, so a slow-but-working job on a loaded
    host runs to completion however long that legitimately takes, while a job
    whose entire tree is idle across the grace window is still killed as hung.
    An explicit `cpu_probe=` in `kw` wins, so a caller with a better reading of
    its own transport keeps it.

    `poll_s` is DERIVED from the grace rather than left at the module default:
    the loop cannot notice a stall sooner than it looks, so a caller that
    declares a 3 s grace and inherits a 30 s cadence gets a 30 s detection —
    the declared grace silently means nothing. Sampling four times per grace
    window keeps the two consistent at any grace, and the default grace still
    yields the module's default cadence. This is an observation CADENCE, not a
    runtime bound: sampling more often never kills a working job sooner."""
    kw.setdefault("cpu_probe", host_cpu_probe)
    if "poll_s" not in kw:
        grace = kw.get("stall_grace_s", DEFAULT_STALL_GRACE_S)
        kw["poll_s"] = max(0.25, min(DEFAULT_POLL_S, float(grace) / 4.0))
    return run_supervised(cmd, **kw)


def completed_process(cmd, res: "SupervisedResult"
                      ) -> subprocess.CompletedProcess:
    """Adapt a `SupervisedResult` to `subprocess.CompletedProcess`.

    Lets a call site swap a `subprocess.run(..., timeout=N)` for supervision
    WITHOUT touching its callers: `.returncode` / `.stdout` / `.stderr` keep
    their meanings, and a stall arrives as rc RC_STALLED with WATCHDOG_STALLED
    on stderr — a distinct, self-describing code, never silently folded into
    the ordinary failure rc the subject would have produced itself."""
    return subprocess.CompletedProcess(cmd, res.rc, res.out, res.err)
