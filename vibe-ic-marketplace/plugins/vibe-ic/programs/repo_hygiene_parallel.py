from __future__ import annotations


import os as _os                                                    # noqa: E402


import sys as _sys                                                  # noqa: E402


if _sys.flags.isolated:
    _sys.dont_write_bytecode = True


if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))


import json


import os


import select


import shutil


import signal


import stat


import subprocess


import sys


import tempfile


import threading


from pathlib import Path


from typing import Any, Callable, Dict, List, Sequence, Tuple


import _gate_inflight_progress as _inflight


import _owned_process_supervisor as _owned


import _semantic_child_progress as _semantic_progress


from _atomic_artefact import write_json, write_text


DEFAULT_JOBS = 8


DEFAULT_STALL_GRACE_S = 300


JOBS_ENV = "GATEKEEPER_HYGIENE_JOBS"


SHARD_DISPATCH_JOBS = "1"


DEFAULT_POLL_S = 5


_OWNED_REAPER_PREFIX = "hygiene-owned-reaper-"


_PENDING_REAPERS: Dict[
    Tuple[int, int], Tuple[subprocess.Popen, int | None, Path]
] = {}


_PENDING_REAPERS_LOCK = threading.Lock()


_ACTIVE_REAPER_SCRATCH: set[Path] = set()


class BudgetRefused(ValueError):
    """The stage was given a job count it will not guess at."""


def stage_process_budget(explicit: int | None = None,
                         env: Dict[str, str] | None = None) -> int:
    """The ONE number that bounds this whole stage's concurrent gate slots.

    WHAT WAS WRONG (vibe-ic#2072)
    -----------------------------
    Three layers each chose a width and nobody multiplied them out.

      * `tools/gatekeeper-land.sh:1988` reads `GATEKEEPER_HYGIENE_JOBS` (else
        8), subtracts the other live lanes, and hands the remainder to ONE
        `repo_hygiene_gates.sh`. Peak on the landing path is therefore the
        budget, whole, and that shape is why its own comment can say "peak
        concurrent process count in the tier is 8 in every shape".
      * This module took `--jobs` from a CLI default of 8, never looked at the
        env, and launched `jobs * 2` shards at once (both A/B arms).
      * Each shard is a FRESH `repo_hygiene_gates.sh`, so each one re-defaulted
        at `tools/ci/_gate_dispatch.sh:476` to 8 of its own.

    `_gate_dispatch.sh` states the invariant it believed it had — "Exactly one
    level of this script is parallel: the outermost" — and it is true of the
    script and false of the stage, because every shard IS an outermost
    invocation. 8 buckets x 2 arms x 8 = 128.

    MEASURED, 8HD-4 (32 cores), 2026-09-07, at v1.18.35 on a host that started
    at load1 5.05: a direct `repo_hygiene_parallel.py` reached 108 concurrent
    dispatch-side processes, 207 descendants, and load1 96.3. The landing path
    at the same tree holds 8. czharness measured the same shape on 8HD-9
    (load ~19 -> 114).

    A QUEUE, NOT A CAP THAT DROPS WORK
    ----------------------------------
    Nothing is skipped and no budget is shortened to compensate. Every shard
    the plan produced is still submitted; the pool runs at most `budget` of
    them at a time and the rest WAIT. So the fan-out is:

        peak concurrent gate slots = (shards running) x (each shard's width)
                                   = budget x 1

    ONE UNIT PER SHARD, AND WHY THE SECOND FACTOR IS 1 RATHER THAN A SHARE.
    `hygiene_shard_plan` is an LPT makespan split over IDENTICAL MACHINES: it
    balances the buckets on the assumption that a shard works through its own
    bucket one gate at a time. Width 1 is the execution the partition was
    computed for, and `_gate_dispatch.sh:474` records that 1 "restores the
    exact pre-#P4 execution path, gate for gate and byte for byte" — so it is
    the one width whose per-gate behaviour is already known not to differ.
    Giving each shard `budget // shards` instead would have to round, and a
    rounded share either overshoots the cap or idles the machine.

    THE SOURCE, IN ORDER, AND NEVER A GUESS.
    An explicit `--jobs` (a caller who said a number) beats the environment,
    which beats `DEFAULT_JOBS` — the same 8 that both `gatekeeper-land.sh` and
    `_gate_dispatch.sh` already default to, so an unset env puts this stage at
    the landing path's width rather than at a width of its own. A malformed
    env is REFUSED, not rounded: `_gate_dispatch.sh:483` refuses "to guess how
    much of this run to parallelise" and a stage that guessed where the
    dispatcher refuses would reintroduce the divergence by the back door.
    """
    if explicit is not None:
        if explicit < 1:
            raise BudgetRefused("--jobs must be a positive integer")
        return explicit
    raw = (os.environ if env is None else env).get(JOBS_ENV)
    if raw is None or raw == "":
        return DEFAULT_JOBS
    if not raw.strip().isdigit() or int(raw.strip()) < 1:
        raise BudgetRefused(
            f"{JOBS_ENV}={raw!r} is not a positive integer; refusing to guess "
            f"how many concurrent gate slots this stage may hold")
    return int(raw.strip())


def shard_env(base: Dict[str, str]) -> Dict[str, str]:
    """Give one shard its OWN width, which is one unit of the stage's budget.

    The forward is what makes the budget above arithmetic rather than a wish.
    Without it a shard inherits whatever the caller set — or, with the caller
    setting nothing, re-defaults to 8 at `_gate_dispatch.sh:476` — and the
    stage's peak becomes the PRODUCT of two widths that were each chosen as if
    they were the only one.
    """
    base[JOBS_ENV] = SHARD_DISPATCH_JOBS
    return base


def _reap_completed_reaper_records() -> None:
    """Remove only attributed records whose exact reaper identity is gone."""
    tmp_root = Path(tempfile.gettempdir())
    for scratch in tmp_root.glob(_OWNED_REAPER_PREFIX + "*"):
        with _PENDING_REAPERS_LOCK:
            if scratch in _ACTIVE_REAPER_SCRATCH:
                continue
        status = scratch / "reaper-status.json"
        try:
            doc = _load_json(status)
            if doc.get("state") == "reaper_complete":
                events = doc.get("events") or []
                last = events[-1]
                pid = int(last["reaper_pid"])
                starttime = int(last["reaper_starttime"])
            elif doc.get("state") == "complete":
                pid = int(doc["reaper_pid"])
                starttime = int(doc["reaper_starttime"])
            else:
                continue
        except (OSError, ValueError, TypeError, KeyError, IndexError,
                json.JSONDecodeError):
            continue
        try:
            live = _owned._read_proc_identity(pid)
        except (OSError, ValueError, IndexError):
            continue
        if live is None or live[1] != starttime:
            shutil.rmtree(scratch, ignore_errors=True)


def _retain_pending_reaper(helper: subprocess.Popen, helper_pidfd: int | None,
                           scratch: Path, starttime: int) -> None:
    """Keep a strong, inspectable owner until its SIGKILL-pending tree exits."""
    key = (helper.pid, starttime)
    with _PENDING_REAPERS_LOCK:
        _PENDING_REAPERS[key] = (helper, helper_pidfd, scratch)

    def finish() -> None:
        try:
            helper.wait()
        finally:
            if helper_pidfd is not None:
                try:
                    os.close(helper_pidfd)
                except OSError:
                    pass
            with _PENDING_REAPERS_LOCK:
                _PENDING_REAPERS.pop(key, None)
                _ACTIVE_REAPER_SCRATCH.discard(scratch)
            # Keep the tiny status/result directory as termination evidence.
            # A later invocation may reap completed records; deleting it here
            # would race the caller that is reporting the rc=2 sidecar path.

    threading.Thread(
        target=finish, name=f"owned-reaper-{helper.pid}", daemon=True).start()


def _strict_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _strict_loads(payload: str) -> Any:
    return json.loads(payload, object_pairs_hook=_strict_object,
                      parse_constant=_reject_json_constant)


def _load_json(path: Path) -> Dict[str, Any]:
    doc = _strict_loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("top-level JSON is not an object")
    return doc


def _exact_identity_rows(value: object) -> bool:
    if not isinstance(value, list):
        return False
    identities = []
    for row in value:
        if (not isinstance(row, dict)
                or set(row) != {"pid", "starttime"}
                or type(row.get("pid")) is not int or row["pid"] <= 0
                or type(row.get("starttime")) is not int
                or row["starttime"] < 0):
            return False
        identities.append((row["pid"], row["starttime"]))
    return len(identities) == len(set(identities))


def _owned_final_zero(doc: object) -> bool:
    """Strict trusted-helper terminal record usable as an atomic proof."""
    fields = {
        "protocol", "rc", "body", "problem", "outcome", "launched",
        "census_ok", "final_descendants", "observed", "capability_error",
    }
    return (isinstance(doc, dict) and set(doc) == fields
            and type(doc.get("protocol")) is int and doc["protocol"] == 1
            and type(doc.get("rc")) is int
            and isinstance(doc.get("body"), str)
            and (doc.get("problem") is None
                 or isinstance(doc.get("problem"), str))
            and doc.get("outcome") in {
                "natural", "stalled", "ceiling", "aborted"}
            and doc.get("launched") is True
            and doc.get("census_ok") is True
            and doc.get("final_descendants") == []
            and _exact_identity_rows(doc.get("observed"))
            and isinstance(doc.get("capability_error"), str))


def _shutdown_final_zero(doc: object, *, helper_pid: int,
                         helper_starttime: int | None,
                         helper_rc: int | None) -> bool:
    fields = {
        "protocol", "state", "reaper_pid", "reaper_starttime", "exit_code",
        "census_ok", "final_descendants", "observed",
    }
    return (isinstance(doc, dict) and set(doc) == fields
            and type(doc.get("protocol")) is int and doc["protocol"] == 1
            and doc.get("state") == "shutdown_complete"
            and type(doc.get("reaper_pid")) is int
            and doc["reaper_pid"] == helper_pid
            and type(doc.get("reaper_starttime")) is int
            and doc["reaper_starttime"] >= 0
            and (helper_starttime is None
                 or doc["reaper_starttime"] == helper_starttime)
            and type(doc.get("exit_code")) is int
            and doc["exit_code"] == 128 + signal.SIGTERM
            and helper_rc == doc["exit_code"]
            and doc.get("census_ok") is True
            and doc.get("final_descendants") == []
            and _exact_identity_rows(doc.get("observed")))


_OUTER_RELAY_POLL_S = 5.0


class OuterProgressRelay:
    """Renew the REVIEW-side lease from measured sub-unit progress."""

    def __init__(self, rows, *, stream=None, poll_s: float = _OUTER_RELAY_POLL_S):
        self._readers = [
            (arm, shard, _inflight.InflightReader(str(path), tuple(labels)))
            for arm, shard, path, labels in rows]
        self._scores: Dict[Tuple[str, int], int] = {}
        self._said_error: set = set()
        self._stream = stream
        self._poll_s = float(poll_s)
        self._stop = threading.Event()
        self._thread = None
        self.emitted = 0

    def _say(self, line: str) -> None:
        print(line, file=self._stream if self._stream is not None else sys.stdout,
              flush=True)

    def sample_once(self) -> int:
        """One pass. Returns how many lines it emitted."""
        emitted = 0
        for arm, shard, reader in self._readers:
            key = (arm, shard)
            try:
                score = reader.sample()
            except Exception:
                # A relay that raised would take the whole tier down over a
                # channel that is only ever an ADDITION to the record.
                continue
            if score > self._scores.get(key, 0):
                self._scores[key] = score
                self._say(f"[PROGRESS] hygiene arm {arm} shard {shard}: "
                          f"{reader.describe()}")
                emitted += 1
            if reader.error and key not in self._said_error:
                self._said_error.add(key)
                self._say(f"[PROGRESS] hygiene arm {arm} shard {shard}: "
                          "in-flight channel stopped renewing: "
                          f"{reader.error}")
                emitted += 1
        self.emitted += emitted
        return emitted

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_s):
            self.sample_once()
        self.sample_once()

    def __enter__(self):
        if self._readers:
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="hygiene-outer-progress")
            self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._poll_s * 2.0, 1.0))
        return False


def _run(argv: List[str], cwd: Path, env: Dict[str, str], *,
         progress_path: Path | None = None,
         expected_progress_labels: Sequence[str] | None = None,
         inflight_path: Path | None = None,
         stall_grace_s: float = DEFAULT_STALL_GRACE_S,
         atomic: bool = False,
         owned_result_sink: Dict[str, Any] | None = None,
         semantic_progress_scope: str | None = None,
         semantic_progress_units: Sequence[str] | None = None,
         domain_progress_callback: Callable[[str, int, int], None] | None = None):
    """Run until natural completion while supervising FORWARD PROGRESS.

    There is deliberately no whole-run timeout. Existing callers retain their
    explicit output/attestation/atomic policy. Supplying ``semantic_progress_*``
    selects the stricter issue-1710 mode: only exact parent-manifest checkpoints
    renew the lease; stdout, CPU and generic log activity cannot. Validated
    checkpoints are relayed while the direct child is still running.
    """
    # Subreaper state and waitpid(-1) are process-global.  `_run` is called by
    # several dispatcher threads, so each job gets a dedicated one-job helper.
    # The private pipe is the semantic state channel: the outer thread waits on
    # either a helper-exit pidfd event or an explicit termination-pending event,
    # never on an estimated whole-job deadline.
    semantic_requested = (semantic_progress_scope is not None
                          or semantic_progress_units is not None)
    if (semantic_progress_scope is None) != (semantic_progress_units is None):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: semantic progress scope "
                "and finite unit manifest must be supplied together")
    if domain_progress_callback is not None and not semantic_requested:
        return (2, "", "OWNED_SUPERVISOR_NORECORD: domain progress callback "
                "has no semantic child channel")
    if semantic_requested and (progress_path is not None or atomic):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: semantic progress is "
                "exclusive with attestation/log or atomic renewal")
    if not hasattr(os, "pidfd_open") or not hasattr(select, "poll"):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: dispatcher pidfd "
                "exit events are unavailable")
    if atomic and progress_path is not None:
        return (2, "", "OWNED_SUPERVISOR_NORECORD: atomic completion-only "
                "mode cannot accept a progress channel")
    if (progress_path is None) != (expected_progress_labels is None):
        return (2, "", "OWNED_SUPERVISOR_NORECORD: semantic progress path "
                "and assigned-label manifest must be supplied together")
    try:
        probe_pidfd = os.pidfd_open(os.getpid())
    except OSError as exc:
        return (2, "", "OWNED_SUPERVISOR_NORECORD: dispatcher cannot open "
                f"pidfd exit events: {exc}")
    else:
        os.close(probe_pidfd)

    _reap_completed_reaper_records()
    scratch = Path(tempfile.mkdtemp(prefix=_OWNED_REAPER_PREFIX))
    with _PENDING_REAPERS_LOCK:
        _ACTIVE_REAPER_SCRATCH.add(scratch)
    result_path = scratch / "owned-result.json"
    status_path = scratch / "reaper-status.json"
    expected_progress_path = scratch / "expected-progress-labels.json"
    diagnostic_path = scratch / "helper.log"
    event_read = -1
    event_write = -1
    helper: subprocess.Popen | None = None
    helper_pidfd: int | None = None
    diagnostic_fh = None
    retained = False
    try:
        semantic_plan = None
        relay = None
        helper_env = env
        if semantic_requested:
            try:
                semantic_plan = _semantic_progress.prepare_parent(
                    scratch, str(semantic_progress_scope),
                    list(semantic_progress_units or ()), env)
                relay = _semantic_progress.RelayValidator(
                    semantic_plan.scope, len(semantic_plan.units),
                    domain_progress_callback)
                helper_env = semantic_plan.env
            except (OSError, ValueError,
                    _semantic_progress.ProgressProtocolError) as exc:
                return (2, "", "OWNED_SUPERVISOR_NORECORD: cannot prepare "
                        f"semantic child progress: {exc}")
        event_read, event_write = os.pipe()
        os.set_blocking(event_read, False)
        diagnostic_fh = diagnostic_path.open("wb")
        helper_argv = [
            sys.executable, str(Path(_owned.__file__).resolve()),
            "--result", str(result_path),
            "--status", str(status_path),
            "--event-fd", str(event_write),
            "--cwd", str(cwd.resolve()),
            "--stall-grace", str(stall_grace_s),
            "--poll", str(DEFAULT_POLL_S),
        ]
        if progress_path is not None:
            write_json(expected_progress_path, {
                "schema": 1,
                "labels": list(expected_progress_labels or ()),
            }, ensure_ascii=False)
            expected_progress_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            helper_argv.extend([
                "--progress", str(progress_path.resolve()),
                "--expected-progress-labels",
                str(expected_progress_path.resolve()),
            ])
            # vibe-ic#2177 — the second, finer renewal source. Only meaningful
            # beside `--progress`, and `run_owned` refuses it on its own.
            if inflight_path is not None:
                helper_argv.extend(
                    ["--inflight-progress", str(inflight_path.resolve())])
        elif atomic:
            helper_argv.append("--atomic")
        if semantic_plan is not None:
            helper_argv.extend([
                "--semantic-progress-manifest",
                str(semantic_plan.manifest_path),
            ])
        helper_argv.extend(["--", *argv])
        helper = subprocess.Popen(
            helper_argv, env=helper_env, stdout=diagnostic_fh,
            stderr=subprocess.STDOUT, pass_fds=(event_write,),
            start_new_session=True)
        diagnostic_fh.close()
        os.close(event_write)
        event_write = -1
        try:
            helper_pidfd = os.pidfd_open(helper.pid)
        except OSError as exc:
            helper.send_signal(signal.SIGTERM)
            helper_diagnostic = diagnostic_path.read_text(
                encoding="utf-8", errors="replace")
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            starttime = observed[1] if observed is not None else -1
            _retain_pending_reaper(helper, None, scratch, starttime)
            retained = True
            helper = None
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_NORECORD: cannot own helper pidfd: "
                    f"{exc}")

        poller = select.poll()
        poller.register(event_read,
                        select.POLLIN | select.POLLHUP | select.POLLERR)
        poller.register(helper_pidfd,
                        select.POLLIN | select.POLLHUP | select.POLLERR)
        event_buffer = b""
        pending: Dict[str, Any] | None = None
        helper_exited = False
        channel_failed = False
        channel_failure = ""

        def drain_pending_events() -> None:
            nonlocal event_buffer, pending, channel_failed, channel_failure
            while True:
                try:
                    chunk = os.read(event_read, 65536)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                event_buffer += chunk
                while b"\n" in event_buffer:
                    raw, event_buffer = event_buffer.split(b"\n", 1)
                    if not raw:
                        channel_failed = True
                        channel_failure = "empty private supervisor event"
                        continue
                    try:
                        candidate = _semantic_progress.strict_loads(
                            raw.decode("ascii"))
                    except (UnicodeDecodeError, ValueError,
                            json.JSONDecodeError):
                        candidate = {"state": "invalid"}
                    if (isinstance(candidate, dict)
                            and candidate.get("state")
                            == "termination_pending"):
                        pending = candidate
                    elif (isinstance(candidate, dict)
                          and candidate.get("state") == "domain_progress"):
                        if relay is None:
                            channel_failed = True
                            channel_failure = "unexpected domain-progress relay"
                        else:
                            relay.accept(candidate)
                            if relay.error:
                                channel_failed = True
                                channel_failure = relay.error
                    else:
                        channel_failed = True
                        channel_failure = "invalid private supervisor event"

        while not pending and not helper_exited:
            # Both watched objects are kernel events.  There is deliberately no
            # wall-clock estimate for how long a healthy helper may run.
            events = poller.poll()
            pipe_events = [event for fd, event in events
                           if fd == event_read]
            if pipe_events:
                drain_pending_events()
                if event_buffer and any(
                        event & (select.POLLHUP | select.POLLERR)
                        for event in pipe_events):
                    channel_failed = True
                    channel_failure = "truncated private supervisor event"
                if pending is None and any(
                        event & (select.POLLHUP | select.POLLERR)
                        for event in pipe_events):
                    # The sidecar is written before the pipe event.  Recover a
                    # transition if the helper closed between those operations.
                    try:
                        durable = _load_json(status_path)
                    except (OSError, ValueError, json.JSONDecodeError):
                        durable = {}
                    events_doc = durable.get("events")
                    if isinstance(events_doc, list):
                        for candidate in reversed(events_doc):
                            if (isinstance(candidate, dict)
                                    and candidate.get("state")
                                    == "termination_pending"):
                                pending = candidate
                                break
                    if pending is None:
                        if (result_path.is_file()
                                or durable.get("state") == "complete"):
                            # Normal helper shutdown writes its result/status
                            # before closing the channel.  Stop watching the
                            # now-permanent HUP and await its pidfd exit event.
                            poller.unregister(event_read)
                        else:
                            channel_failed = True
            if pending is not None:
                break
            if channel_failed:
                break
            if any(fd == helper_pidfd for fd, _event in events):
                # The helper can publish a pending transition immediately before
                # exit.  Drain the private channel before classifying the pidfd
                # event so a fast reaper completion cannot hide that rc=2 state.
                drain_pending_events()
                helper_exited = pending is None

        if helper_exited and event_buffer and not channel_failed:
            channel_failed = True
            channel_failure = "truncated private supervisor event"

        if channel_failed:
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            expected_starttime = observed[1] if observed is not None else None
            if helper.poll() is None:
                try:
                    helper.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass

            # A semantic callback is part of an enclosing atomic test lease.
            # On relay failure retain ownership here, drain the helper-only
            # pipe, and wait only on pidfd exit until the helper has published
            # a trusted final-zero cleanup record. There is no elapsed bound.
            pipe_registered = True
            while helper.poll() is None:
                for fd, event in poller.poll():
                    if fd == event_read and pipe_registered:
                        while True:
                            try:
                                chunk = os.read(event_read, 65536)
                            except BlockingIOError:
                                break
                            if not chunk:
                                break
                        if event & (select.POLLHUP | select.POLLERR):
                            poller.unregister(event_read)
                            pipe_registered = False
                    if fd == helper_pidfd:
                        helper.wait()
                        break
            helper.wait()
            helper_diagnostic = diagnostic_path.read_text(
                encoding="utf-8", errors="replace")

            cleanup_proof = ""
            cleanup_verified = False
            try:
                status_doc = _semantic_progress.strict_loads(
                    status_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError,
                    json.JSONDecodeError) as exc:
                status_doc = None
                cleanup_proof = f"unreadable final-zero status: {exc}"
            if isinstance(status_doc, dict):
                if _shutdown_final_zero(
                        status_doc, helper_pid=helper.pid,
                        helper_starttime=expected_starttime,
                        helper_rc=helper.returncode):
                    cleanup_proof = "shutdown_complete/final_descendants=[]"
                    cleanup_verified = True
                else:
                    cleanup_proof = "final-zero status differs"
            if not cleanup_verified and result_path.is_file():
                try:
                    result_doc = _semantic_progress.strict_loads(
                        result_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError,
                        json.JSONDecodeError) as exc:
                    cleanup_proof = (
                        f"unreadable natural final-zero result: {exc}")
                else:
                    if helper.returncode == 0 and _owned_final_zero(result_doc):
                        cleanup_proof = "natural/final_descendants=[]"
                        cleanup_verified = True
            if not cleanup_verified:
                cleanup_proof = "UNPROVED: " + (cleanup_proof or "missing")
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_NORECORD: private supervisor channel "
                    "failed before a terminal record"
                    + (f": {channel_failure}" if channel_failure else "")
                    + f"; atomic cleanup={cleanup_proof}")
        helper_diagnostic = diagnostic_path.read_text(
            encoding="utf-8", errors="replace")
        if pending is not None:
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            expected_start = pending.get("reaper_starttime")
            violations: List[str] = []
            try:
                status_doc = _load_json(status_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                status_doc = {}
                violations.append(f"unreadable durable pending status: {exc}")
            if status_doc.get("state") not in (
                    "termination_pending", "reaper_complete"):
                violations.append("durable sidecar has no pending state")
            if pending.get("protocol") != 1:
                violations.append("unknown pending protocol")
            if pending.get("reaper_pid") != helper.pid:
                violations.append("pending record names a different reaper PID")
            if not isinstance(expected_start, int) or expected_start < 0:
                violations.append("pending record has no reaper starttime")
            if (observed is not None and isinstance(expected_start, int)
                    and observed[1] != expected_start):
                violations.append("reaper PID/starttime identity changed")
            if not isinstance(pending.get("reason"), str):
                violations.append("pending record has no reason")
            if not isinstance(pending.get("pending_descendants"), list):
                violations.append("pending record has no descendant census")
            if pending.get("status_error"):
                violations.append(
                    "durable pending sidecar failed: "
                    f"{pending['status_error']}")
            if violations:
                if helper.poll() is None:
                    # A pending transition proves cleanup is already active.
                    # Retain that unique subreaper; do not interrupt it with a
                    # nested signal-handler cleanup merely because one of its
                    # observability records was malformed.
                    retain_start = (
                        observed[1] if observed is not None else
                        expected_start if isinstance(expected_start, int)
                        else -1)
                    _retain_pending_reaper(
                        helper, helper_pidfd, scratch, int(retain_start))
                    retained = True
                    helper = None
                    helper_pidfd = None
                return (2, helper_diagnostic,
                        "OWNED_SUPERVISOR_NORECORD: invalid pending state: "
                        + "; ".join(violations))

            # Transfer the live Popen/pidfd objects to a background waiter.  The
            # helper is a session-isolated subreaper and continues to own the
            # SIGKILL-pending tree; the dispatcher can now fail closed with rc2.
            _retain_pending_reaper(
                helper, helper_pidfd, scratch, int(expected_start))
            retained = True
            helper = None
            helper_pidfd = None
            reason = str(pending["reason"])
            descendants = pending.get("pending_descendants")
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_TERMINATION_PENDING: "
                    f"reason={reason}; reaper={pending['reaper_pid']}/"
                    f"{expected_start}; descendants={descendants!r}; "
                    f"status={status_path}")

        helper.wait()
        if helper.returncode != 0 or not result_path.is_file():
            return (2, helper_diagnostic,
                    "OWNED_SUPERVISOR_NORECORD: helper did not publish its "
                    f"terminal census (helper rc={helper.returncode})")
        try:
            record = _load_json(result_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return (2, helper_diagnostic,
                    f"OWNED_SUPERVISOR_NORECORD: invalid result: {exc}")
    except BaseException:
        if helper is not None and helper.poll() is None:
            # The helper is session-isolated, so explicitly request its cleanup
            # when this dispatcher thread is cancelled.
            helper.send_signal(signal.SIGTERM)
            try:
                observed = _owned._read_proc_identity(helper.pid)
            except (OSError, ValueError, IndexError):
                observed = None
            starttime = observed[1] if observed is not None else -1
            _retain_pending_reaper(
                helper, helper_pidfd, scratch, starttime)
            retained = True
            helper = None
            helper_pidfd = None
        raise
    finally:
        if event_read >= 0:
            try:
                os.close(event_read)
            except OSError:
                pass
        if event_write >= 0:
            try:
                os.close(event_write)
            except OSError:
                pass
        if diagnostic_fh is not None and not diagnostic_fh.closed:
            diagnostic_fh.close()
        if helper_pidfd is not None:
            try:
                os.close(helper_pidfd)
            except OSError:
                pass
        if not retained:
            shutil.rmtree(scratch, ignore_errors=True)
            with _PENDING_REAPERS_LOCK:
                _ACTIVE_REAPER_SCRATCH.discard(scratch)

    body = str(record.get("body") or "")
    if helper_diagnostic:
        body += helper_diagnostic
    violations: List[str] = []
    if record.get("protocol") != 1:
        violations.append("unknown ownership protocol")
    if not isinstance(record.get("rc"), int):
        violations.append("missing integer child rc")
    if not isinstance(record.get("launched"), bool):
        violations.append("missing launch state")
    if not isinstance(record.get("census_ok"), bool):
        violations.append("missing census integrity state")
    if not isinstance(record.get("outcome"), str):
        violations.append("missing supervisor outcome")
    if not isinstance(record.get("observed"), list):
        violations.append("missing observed-identity census")
    final = record.get("final_descendants")
    if final != []:
        violations.append(f"final descendant census is not zero: {final!r}")
    if record.get("launched") and record.get("census_ok") is not True:
        violations.append("PID/starttime census was not continuously provable")
    recorded_problem = record.get("problem")
    if recorded_problem is not None and not isinstance(recorded_problem, str):
        violations.append("malformed problem record")
        recorded_problem = None
    if (isinstance(recorded_problem, str)
            and "SEMANTIC_PROGRESS_NORECORD:" in recorded_problem):
        violations.append(
            "semantic child progress did not reach its exact terminal FSM")
    if relay is not None and (
            relay.error or relay.completed != relay.total):
        violations.append(
            "incomplete domain-progress relay "
            f"({relay.completed}/{relay.total})"
            + (f": {relay.error}" if relay.error else ""))
    if (record.get("launched") is False
            and (record.get("rc") == 0 or not recorded_problem)):
        violations.append("helper reported success without launching the job")
    if violations:
        violations.insert(0, "OWNED_SUPERVISOR_REFUSED")
    problem = "; ".join(
        [item for item in [recorded_problem, *violations] if item]) or None
    rc = (2 if violations else
          record.get("rc") if isinstance(record.get("rc"), int) else 2)
    if owned_result_sink is not None:
        owned_result_sink.clear()
        owned_result_sink.update(record)
    return rc, body, problem
