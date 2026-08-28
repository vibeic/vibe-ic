#!/usr/bin/env python3
"""_progress_run.py — a ``subprocess.run``-shaped call that judges PROGRESS.

Owner ruling (2026-08-28), on a test that failed at a 60 s bound in a file
nobody had touched::

    你怎麼知道它 60 秒這次過了，換一臺機器會不會跑得更久或跑得更快？你不知道嘛。

He is right, and the consequence is a standing rule: **a wall-clock bound answers
"how long has it been", which is a different question from "is this working".**
Spending the first as if it were the second kills a hard proof that is genuinely
computing, waits patiently on a corpse, and — the part that matters here —
records the SUBJECT as wrong when the only thing that was different was the host.

``subprocess.run(argv, timeout=N)`` is that mistake in its most common form. When
the bound fires, ``TimeoutExpired`` escapes: a gate aborts with a traceback and a
landing is refused, or a test ERRORs and the program under test is blamed. Same
commit, slower machine, different verdict.

This module is the replacement primitive for that call. It is deliberately
``subprocess.run``-shaped so a call site converts by deleting ``timeout=`` — the
smallest edit that removes the defect, because a *bigger constant is the same
defect restated*.

WHAT REPLACES THE CLOCK
=======================
Forward progress, measured by looking at the child rather than at the clock:

  * **output** — the bytes it has written to stdout/stderr (only ever grows),
  * **CPU** — ``utime+stime`` from ``/proc/<pid>/stat``, summed over the child
    AND its live descendants, so a quiet compute phase still counts as alive,
  * **I/O** — ``read_bytes+write_bytes`` from ``/proc/<pid>/io``, so a phase
    that is neither chatty nor CPU-bound (a large read, a slow fsync) counts.

ANY signal advancing = PROGRESSING, and a progressing child is **never** killed,
however long it legitimately takes. Nothing advancing across ``stall_looks``
CONSECUTIVE looks = STALLED.

**N is how many times we looked, not how long we waited.** A six-hour proof
burning CPU advances the CPU signal at every look and so can never trip the
stall, no matter how many hours pass. That is the property a wall-clock bound
cannot have, and it is the whole point of the module.

THE TWO OUTCOMES, AND WHY NEITHER IS A TIMEOUT
==============================================
``run()`` returns a ``CompletedProcess`` when the child exits — whatever it took.
Otherwise it raises ``Stalled``, which is a **finding about the child**: every
signal we can read sat still while we looked N times. That is evidence of a hang,
not of a slow host, so unlike a timeout it is worth acting on.

Where the caller is a gate and cannot act on it, ``run_or_undetermined()`` maps a
stall to the repo's rc 2 UNDETERMINED convention rather than to a failing verdict
— the landing gate's own rule, that *a review which could not decide must never
reach the stamp as a review that decided nothing was wrong*.

DEGRADE LOUDLY (flow-change-acceptance §6). Which progress signals were actually
readable is recorded on the result (``.signals``) and quoted in ``Stalled``. A
host where ``/proc/<pid>/io`` is not readable still supervises on output+CPU, and
SAYS it did, rather than silently supervising on less than it claims.

chip-AGNOSTIC, tool-AGNOSTIC, PDK-AGNOSTIC: generic process counters only.
"""
from __future__ import annotations

import os
import subprocess  # nosec B404 — this module IS the process-launch primitive
import tempfile
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _watchdog as _wd  # noqa: E402

__all__ = ["Stalled", "run", "run_or_undetermined", "run_best_effort",
           "exit_undetermined_on_stall", "spawn_floor_s",
           "DEFAULT_STALL_LOOKS", "RC_UNDETERMINED", "RC_STALLED"]

#: How many CONSECUTIVE looks may show zero movement on every signal before the
#: child is called hung. Not a duration: at any poll cadence this is a count of
#: observations, and it does NOT grow with how long the child has been running.
#: A child must be motionless on output AND CPU AND I/O every single time we
#: look, twelve times running. At the default cadence that is six minutes of
#: total stillness — deliberately generous, because the cost of being wrong in
#: this direction is killing a child that was merely blocked (a slow network
#: read moves neither CPU nor block-I/O), and the cost of being patient is only
#: that a genuinely wedged child is reported later.
DEFAULT_STALL_LOOKS = 12

#: The rc a BEST-EFFORT call reports for a stall. Inherited from `_watchdog` so
#: the whole repo spells this outcome one way, and chosen to be outside the
#: range any real tool returns, so it can never be read as that tool's verdict.
RC_STALLED = _wd.RC_STALLED

#: The repo's "I could not decide" exit code. A gate that cannot finish looking
#: must reach the stamp as UNDETERMINED, never as a failing verdict.
RC_UNDETERMINED = 2

#: Absolute backstop for a pathological CPU-burning infinite loop, inherited
#: from `_watchdog`. NOT the primary control and never the thing that fires on a
#: slow host: a job must run a full day to reach it.
HARD_CEILING_S = _wd.DEFAULT_HARD_CEILING_S

_CLK_TCK = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0

_spawn_floor_cache: Optional[float] = None


def spawn_floor_s(_probe: Optional[Callable[[], float]] = None) -> float:
    """MEASURE, on this host and in this session, how long a trivial child takes.

    A poll cadence below the cost of starting a process is meaningless: the child
    has not been scheduled yet, so of course nothing has moved. Rather than
    writing down a number that was true on the author's machine, measure the
    floor here — the precedent this repo already set when a stall grace below the
    pytest boot floor was found to be killing children during boot, and the fix
    measured the boot instead of hard-coding it.

    Cached per process: this is a property of the host, not of the call.
    """
    global _spawn_floor_cache
    if _spawn_floor_cache is not None:
        return _spawn_floor_cache
    probe = _probe or _measure_spawn
    samples: List[float] = []
    for _ in range(3):
        try:
            samples.append(probe())
        except Exception:  # nosec — an unmeasurable host falls back below
            pass
    # Median of three: one scheduling hiccup must not set the cadence.
    _spawn_floor_cache = sorted(samples)[len(samples) // 2] if samples else 0.05
    return _spawn_floor_cache


def _measure_spawn() -> float:
    t0 = time.monotonic()
    subprocess.run([sys.executable, "-c", "pass"],  # nosec B603 — fixed argv
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return time.monotonic() - t0


#: Cadence inherited from `_watchdog`. It costs a fast child NOTHING: the poll
#: blocks in ``proc.wait(timeout=poll_s)``, so a child that exits in 5 ms returns
#: in 5 ms. The cadence only governs how often a STILL-RUNNING child is looked at.
DEFAULT_POLL_S = _wd.DEFAULT_POLL_S


def _poll_interval() -> float:
    """The cadence at which we LOOK.

    The measured spawn floor can only make this cadence SLOWER, never faster.
    That direction is the honest one: a host that measures itself as slow becomes
    MORE patient, and no measurement can ever talk this primitive into declaring a
    child hung sooner than the repo's calibrated cadence. Polling faster than the
    host can schedule a process would observe "nothing moved" about a child that
    has not been run yet.
    """
    return max(DEFAULT_POLL_S, spawn_floor_s() * 100.0)


# ── progress signals ────────────────────────────────────────────────────────
def _descendants(pid: int) -> List[int]:
    """`pid` and every live descendant, by walking /proc ppid links.

    Summing the tree matters: `git` hands the work to a pack process, a runner
    hands it to the tool. Reading only the direct child would see a parent that
    is merely waiting and call a busy tree idle.
    """
    try:
        pids = [int(e) for e in os.listdir("/proc") if e.isdigit()]
    except OSError:
        return [pid]
    parent: Dict[int, int] = {}
    for p in pids:
        try:
            with open(f"/proc/{p}/stat", "rb") as fh:
                data = fh.read()
            # comm may contain ')' — the ppid is the 2nd field AFTER the last ')'
            tail = data[data.rfind(b")") + 2:].split()
            parent[p] = int(tail[1])
        except (OSError, ValueError, IndexError):
            continue
    out, frontier = [pid], [pid]
    seen = {pid}
    while frontier:
        nxt = []
        for p in list(parent):
            if parent.get(p) in frontier and p not in seen:
                seen.add(p)
                out.append(p)
                nxt.append(p)
        frontier = nxt
    return out


def _cpu_seconds(pids: Sequence[int]) -> Optional[float]:
    total = 0.0
    seen_any = False
    for p in pids:
        try:
            with open(f"/proc/{p}/stat", "rb") as fh:
                data = fh.read()
            f = data[data.rfind(b")") + 2:].split()
            # after the last ')': state(0) ppid(1) ... utime(11) stime(12)
            total += (int(f[11]) + int(f[12])) / _CLK_TCK
            seen_any = True
        except (OSError, ValueError, IndexError):
            continue
    return total if seen_any else None


def _io_bytes(pids: Sequence[int]) -> Optional[float]:
    total = 0.0
    seen_any = False
    for p in pids:
        try:
            with open(f"/proc/{p}/io", "rb") as fh:
                for line in fh:
                    if line.startswith((b"read_bytes:", b"write_bytes:")):
                        total += float(line.split()[1])
                        seen_any = True
        except (OSError, ValueError, IndexError):
            continue
    return total if seen_any else None


def _host_probe(signals: Dict[str, bool]) -> Callable[[object], Optional[float]]:
    """CPU+I/O of the child's whole tree, recording which signals were readable.

    A signal that is momentarily unavailable returns None for that source only;
    `_watchdog.ProgressMeter` carries the last value forward, so a probe
    flapping to None can never be mistaken for progress.
    """
    def probe(proc) -> Optional[float]:
        pid = getattr(proc, "pid", None)
        if pid is None:
            return None
        pids = _descendants(int(pid))
        cpu = _cpu_seconds(pids)
        io = _io_bytes(pids)
        if cpu is not None:
            signals["cpu"] = True
        if io is not None:
            signals["io"] = True
        if cpu is None and io is None:
            return None
        # Scaled so neither source can swamp the other into invisibility: any
        # advance in either is an advance in the fused score.
        return (cpu or 0.0) + (io or 0.0) / 1e6
    return probe


class Stalled(RuntimeError):
    """The child made NO forward progress across N consecutive looks.

    This is a finding ABOUT THE CHILD — every readable signal sat still while we
    looked N times — and is therefore actionable, which a wall-clock expiry never
    was. `.signals` names which progress sources were actually readable, so a
    stall observed with a degraded probe set can be told from a full one.
    """

    def __init__(self, cmd, looks: int, poll_s: float, elapsed_s: float,
                 signals: Dict[str, bool], out: str = "", err: str = ""):
        self.cmd = cmd
        self.looks = looks
        self.poll_s = poll_s
        self.elapsed_s = elapsed_s
        self.signals = dict(signals)
        self.stdout = out
        self.stderr = err
        live = ",".join(sorted(k for k, v in self.signals.items() if v)) or "none"
        super().__init__(
            f"STALLED: no forward progress across {looks} consecutive looks "
            f"({poll_s:.2f}s apart, {elapsed_s:.1f}s elapsed); "
            f"signals readable: {live}; cmd: {_fmt(cmd)}")


def _fmt(cmd) -> str:
    if isinstance(cmd, (list, tuple)):
        return " ".join(str(c) for c in cmd)[:200]
    return str(cmd)[:200]


#: The ONLY decode policy `_watchdog` applies to a child's streams. A call site
#: that asked for this explicitly (``errors="replace"``) is asking for what it
#: already gets; any OTHER policy would silently not be applied, so it refuses.
_DECODE_ERRORS = "replace"


def _stdin_from(input_payload, stdin):
    """The child's stdin, as a real file object, plus a closer.

    ``subprocess.run(input=...)`` writes the whole payload and closes; for a
    non-interactive child that is indistinguishable from handing it a seekable
    file already containing those bytes. Doing it with a file rather than a
    writer thread keeps this module free of the one thing it must never have —
    a place the parent can block forever on a pipe nobody is draining.
    """
    if input_payload is None:
        return stdin, None
    if stdin is not None:
        raise ValueError("pass input= or stdin=, not both")
    fh = tempfile.TemporaryFile()
    payload = (input_payload.encode("utf-8")
               if isinstance(input_payload, str) else input_payload)
    fh.write(payload)
    fh.flush()
    fh.seek(0)
    return fh, fh


def run(cmd, *, cwd=None, env=None, input=None,  # noqa: A002
        stdin=None, stdout=None, stderr=None, errors=None, shell=False,
        capture_output: bool = True, text: bool = True, check: bool = False,
        stall_looks: int = DEFAULT_STALL_LOOKS,
        poll_s: Optional[float] = None,
        hard_ceiling_s: float = HARD_CEILING_S,
        _supervisor=None) -> subprocess.CompletedProcess:
    """Run `cmd` to completion, however long it legitimately takes.

    Drop-in for ``subprocess.run(cmd, capture_output=True, text=True,
    timeout=N)`` — convert a call site by deleting the ``timeout=`` argument.

    Raises `Stalled` iff every readable progress signal sat still across
    `stall_looks` consecutive looks. Never raises on account of elapsed time.

    THE COMPATIBILITY SURFACE IS DELIBERATELY NARROW, and every shape it does
    accept is one a call site in this repo actually uses. Anything else raises
    `NotImplementedError` rather than accepting the argument and quietly not
    honouring it — a converted call that silently changed meaning would be a
    worse defect than the timeout it replaced:

      * ``errors=`` — only ``"replace"``, which is the decode policy
        `_watchdog` already applies; any other value would not be applied.
      * ``input=`` / ``stdin=`` — the payload is handed over as a seekable
        file (see `_stdin_from`); ``stdin=subprocess.DEVNULL`` passes through.
      * ``stdout=subprocess.PIPE, stderr=subprocess.STDOUT`` — ONE combined
        stream, in the order a human or ``2>&1`` observes it. `.stderr` is then
        empty by construction, because there was no second stream.
      * ``stdout=subprocess.PIPE, stderr=subprocess.PIPE`` — the long spelling
        of ``capture_output=True``, honoured as written.
      * ``shell=True`` — passed to `Popen` unchanged.
      * ``text=False`` — the streams come back as RAW BYTES, supervised
        identically. Decoding and re-encoding would be lossy, and a caller
        splitting `git ls-files -z` on NUL or reading a blob out of
        `git cat-file --batch` must get the bytes the child actually wrote.

    A ``stdout=<file>`` redirect is NOT supported: it would take the output
    away from the progress meter without saying so, leaving the supervision
    resting on CPU and I/O while still claiming an output signal.
    """
    if not text and errors is not None:
        # `errors=` is a DECODE policy; in bytes mode nothing is decoded, so
        # honouring it is not possible and accepting it would be a lie.
        raise NotImplementedError(
            "_progress_run.run(text=False) returns raw bytes; errors= has "
            "nothing to apply to")
    if text and errors is not None and errors != _DECODE_ERRORS:
        raise NotImplementedError(
            f"_progress_run.run decodes with errors={_DECODE_ERRORS!r} "
            f"(the policy `_watchdog` applies); errors={errors!r} would be "
            f"accepted and then not honoured")
    combined = (stdout is subprocess.PIPE and stderr is subprocess.STDOUT)
    # (PIPE, PIPE) is the long spelling of `capture_output=True` — the two
    # streams, separately, which is what this function does anyway. Accepting
    # the spelling lets a call site keep saying what it means.
    both_piped = (stdout is subprocess.PIPE and stderr is subprocess.PIPE)
    if not (combined or both_piped) and (stdout is not None or stderr is not None):
        raise NotImplementedError(
            "_progress_run.run captures both streams itself; the stdout/stderr "
            "shapes it honours are (PIPE, STDOUT) for one combined stream and "
            "(PIPE, PIPE) for the two separately. A FILE redirect would "
            "silently remove the output progress signal — use "
            "_watchdog.run_supervised(log_path=...) so the file it writes is "
            "what gets watched")
    if poll_s is None:
        poll_s = _poll_interval()
    signals: Dict[str, bool] = {"output": capture_output, "cpu": False,
                                "io": False}
    child_stdin, to_close = _stdin_from(input, stdin)

    def popen_factory(c, **kw):
        if combined:
            # ONE pipe for both streams, so interleaving is preserved. The
            # supervisor's err file stays empty and unwatched; `_size` still
            # sees every byte the child writes, because they all land in out.
            kw = dict(kw, stderr=subprocess.STDOUT)
        if child_stdin is not None:
            kw["stdin"] = child_stdin
        return subprocess.Popen(c, cwd=cwd, shell=shell, **kw)  # nosec B603,B602

    supervisor = _supervisor or _wd.run_supervised
    t0 = time.monotonic()
    try:
        res = supervisor(
            cmd,
            output_progress=True,
            stall_grace_s=stall_looks * poll_s,
            poll_s=poll_s,
            hard_ceiling_s=hard_ceiling_s,
            cpu_probe=_host_probe(signals),
            popen_factory=popen_factory,
            env=env,
            as_text=text,
        )
    finally:
        if to_close is not None:
            to_close.close()
    elapsed = time.monotonic() - t0
    outcome = getattr(res, "outcome", "natural")
    if outcome in ("stalled", "ceiling"):
        raise Stalled(cmd, stall_looks, poll_s,
                      getattr(res, "elapsed_s", elapsed) or elapsed,
                      signals, _wd._as_text(res.out), _wd._as_text(res.err))
    cp = subprocess.CompletedProcess(cmd, res.rc, res.out, res.err)
    if check and cp.returncode != 0:
        raise subprocess.CalledProcessError(cp.returncode, cmd,
                                            cp.stdout, cp.stderr)
    return cp


def run_or_undetermined(cmd, **kw):
    """``(CompletedProcess, None)`` on any exit; ``(None, reason)`` on a stall.

    For a GATE. A gate that could not finish looking has not found the subject
    wrong — it has failed to decide, and must say so with rc 2 rather than
    spend a host condition as a verdict about a commit.
    """
    try:
        return run(cmd, **kw), None
    except Stalled as exc:
        return None, str(exc)


def run_best_effort(cmd, **kw) -> subprocess.CompletedProcess:
    """For a call whose failure the caller ALREADY tolerates.

    Returns ``rc=RC_STALLED`` with the reason on ``.stderr`` instead of raising,
    so an existing ``if r.returncode == 0:`` reads a stall as "that did not
    work" and takes the path it already had for a git subcommand that refused.

    USE THIS ONLY where the result does not reach a verdict — a cleanup, a
    reaper, a prune. Everywhere else use `run()`: reporting a stall as an rc at
    a verdict-bearing call site would let every ``if rc != 0: fail`` in the repo
    convert a host condition straight back into a finding about the subject,
    which is the defect this module removes, re-entering through the back door.
    """
    try:
        return run(cmd, **kw)
    except Stalled as exc:
        blank, reason = "", str(exc)
        if kw.get("text") is False:
            blank, reason = b"", reason.encode("utf-8")
        return subprocess.CompletedProcess(cmd, RC_STALLED, blank, reason)


def exit_undetermined_on_stall(main_fn, *args, rc: int = RC_UNDETERMINED,
                               stream=None, **kwargs) -> int:
    """Run a gate's ``main`` so a stall reaches the stamp as UNDETERMINED.

    A gate that could not finish looking has NOT found the subject wrong. Its
    exit code has to say that, because rc 1 is read downstream as a finding
    about the commit — and a commit is not what changed when the host got busy.

    The decline is announced (flow-change-acceptance §6): a silent rc 2 is
    indistinguishable downstream from a gate that examined nothing on purpose.
    """
    out = stream if stream is not None else sys.stderr
    try:
        return main_fn(*args, **kwargs)
    except Stalled as exc:
        print(f"[UNDETERMINED] {exc}", file=out)
        print(f"  This gate could not finish looking, so it has NOT found the "
              f"subject wrong. Reporting rc {rc} (UNDETERMINED) rather than a "
              f"verdict about the commit: the child stopped moving on this "
              f"host, and no property of the commit changed when it did.",
              file=out)
        return rc
