#!/usr/bin/env python3
"""Give a container command a deadline the CONTAINER enforces.

WHY THIS MODULE EXISTS
======================
Every EDA tool this flow drives runs inside a container, invoked as

    subprocess.run(["docker", "exec", <container>, "bash", "-lc", cmd],
                   capture_output=True, text=True, timeout=N)

That ``timeout=N`` reads like a deadline on the tool. It is not. It is a
deadline on the LOCAL ``docker exec`` CLIENT. When it expires, Python kills the
client and raises ``subprocess.TimeoutExpired``; the process inside the
container is never signalled, because it is not a child of the client and no
signal ever crosses the container boundary. The tool keeps running, holding its
cores, and never finishes writing the output the caller was waiting for.

MEASURED, on this repo's own ``vibeic/vibeic-eda`` container. A command
``echo <mark>; sleep 600`` invoked exactly the way ``analog_real_corner_sweep.
_docker`` invokes ngspice, with ``timeout=5``:

    client-side TimeoutExpired after 5.0s
    container-side `sleep 600` still running, count = 2

and with the deadline moved inside the container by this module:

    returned cleanly rc=124 after 5.1s
    container-side `sleep 600` survivors = 0

That is the whole defect and the whole fix. The abandoned process is why a
sizing-loop point can burn CPU-hours and never create its ``.measure.json``:
the run is not slow, it is orphaned, and the caller has already given up on it.
An orphan is invisible in exactly the way that matters — ``ps`` shows it busy,
so the host looks like it is working on the design.

THE CONTRACT
============
``run_in_container`` wraps the command in coreutils ``timeout``, which runs
INSIDE the container as the tool's own parent and can therefore signal it:

    docker exec <container> timeout -k <kill_grace> <deadline> bash -lc <cmd>

* the tool is signalled where it lives, so no orphan survives the deadline;
* ``timeout`` returns **124** on expiry, so expiry becomes an ORDINARY non-zero
  return code that existing ``returncode != 0`` handling already routes, rather
  than an exception thrown past callers that never expected one;
* ``-k`` escalates to SIGKILL for a tool that ignores SIGTERM, which several
  SPICE and layout engines do while writing;
* the client-side ``timeout=`` is RETAINED, deliberately, at
  ``deadline + _CLIENT_GRACE``. It is a backstop for the container itself being
  wedged (daemon hang, container paused), which no container-side deadline can
  cover. Because it is strictly larger, the container-side deadline always
  fires first in the normal case, so the backstop stops being the thing that
  orphans and becomes the thing that catches what orphaning would have hidden.

DEGRADE LOUDLY, NEVER SILENTLY. If ``timeout`` is absent from the image,
``TIMEOUT_UNAVAILABLE_RC`` comes back from the shell and the caller is told the
deadline could NOT be enforced, instead of the command running unbounded behind
a deadline that exists only in the caller's belief. A deadline you think you
have is worse than one you know you lack.

chip-AGNOSTIC: process lifetime and signal delivery only. No design, PDK,
vendor or tool literal appears here, and the module never inspects the command
it is given.
"""
from __future__ import annotations

import vibeic_temp as _vtmp

import os
import shlex
import shutil
import subprocess
import json
from typing import Optional, Sequence

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402
import _docker_memory as _dmem  # noqa: E402

__all__ = [
    "run_in_container",
    "container_deadline_argv",
    "container_tree_probe",
    "container_id",
    "run_in_container_supervised",
    "default_ceiling_notice",
    "CEILING_CROSSED_MARK",
    "STALLED_RC",
    "docker_exec_argv",
    "TIMEOUT_EXPIRED_RC",
    "TIMEOUT_UNAVAILABLE_RC",
    "EX_ENV_REFUSED",
    "DEFAULT_KILL_GRACE_S",
    "CLIENT_GRACE_S",
]

#: coreutils `timeout` exit status when the deadline expired. Documented by
#: POSIX/GNU, not observed here, so keying on it is reading a protocol.
TIMEOUT_EXPIRED_RC = 124

#: `timeout` itself could not be run (127 = command not found, from the shell).
#: Surfaced rather than swallowed: see "degrade loudly" above.
TIMEOUT_UNAVAILABLE_RC = 127

EX_ENV_REFUSED = 69

#: Seconds between SIGTERM and the SIGKILL escalation.
DEFAULT_KILL_GRACE_S = 5

#: How much longer the client-side backstop waits than the container-side
#: deadline. Must be > 0 so the container-side deadline always fires first.
CLIENT_GRACE_S = 15


def docker_exec_argv(container: str, *rest: str,
                         opts: Sequence[str] = ()) -> list:
    """Build an exec command, or a fresh run with the selected image and mounts."""
    if os.environ.get("VIBEIC_A4_FRESH_PROBES") != "1":
        return ["docker", "exec", *_vtmp.container_env(), "-w", str(_vtmp.scratch()), *opts, container, *rest]
    # Fleet policy: keep the selected image and bind mounts, and run each
    # probe in a fresh container. The canonical A4 corner launcher is unchanged.
    inspected = subprocess.run(
        ["docker", "inspect", container], capture_output=True, text=True,
        check=True)
    selected = json.loads(inspected.stdout)[0]
    config = selected["Config"]
    limits = selected["HostConfig"]
    image = selected["Image"]
    memory = limits.get("Memory")
    if not isinstance(memory, int) or memory <= 0:
        raise ValueError("fresh probe requires a declared memory ceiling")
    allowed = {"-w", "--workdir", "-e", "--env", "-u", "--user"}
    index = 0
    while index < len(opts):
        if opts[index] not in allowed or index + 1 >= len(opts):
            raise ValueError("unsupported fresh-probe option")
        index += 2
    argv = ["docker", "run", "--rm", "--init",
            *_dmem.docker_memory_flags({"VIBEIC_DOCKER_MEMORY": str(memory)}),
            "--label", "vibeic.a4.probe=1"]
    for mount in selected.get("Mounts", []):
        if mount.get("Type") != "bind":
            raise ValueError("fresh probe requires explicit bind mounts")
        spec = mount["Source"] + ":" + mount["Destination"]
        argv += ["-v", spec + ("" if mount.get("RW") else ":ro")]
    for value in config.get("Env", []):
        argv += ["-e", value]
    argv += ["-e", "IIC_OSIC_TOOLS_QUIET=1"]
    if config.get("WorkingDir"):
        argv += ["-w", config["WorkingDir"]]
    if config.get("User"):
        argv += ["-u", config["User"]]
    return [*argv, *_vtmp.docker_mounts(), *opts, image, "--skip", *rest]


# ---------------------------------------------------------------------------
# THE PROGRESS SIGNAL HAS TO POINT AT THE TOOL, NOT AT THE CLIENT
# ---------------------------------------------------------------------------
#
# The deadline defect this module opens with has a twin, and it was measured on
# the same shape. `docker exec` supervision watches the LOCAL CLIENT: its CPU,
# its I/O, and the bytes it relays. The tool is not its child -- it is parented
# by the container runtime's shim -- so none of those three counters describe
# the work at all.
#
# MEASURED 2026-09-07 on 8HD-8 (vibe-ic#2083), a magic LEF extraction of a
# 35 MB GDS through this exact call, sampled every 5 s from the host:
#
#     t+29s  magic cpu= 28.8s rss=1.15GB | client cpu=0.01 io=0/0 out=0 new bytes
#     t+99s  magic cpu= 99.2s rss=2.35GB | client cpu=0.01 io=0/0 out=0 new bytes
#     t+124s magic cpu=124.3s rss=2.31GB | client cpu=0.01 io=0/0 out=0 new bytes
#
# magic was pinned at a full 1.00 CPU-second per second and growing its heap by
# tens of megabytes a second. Every signal the supervisor could see sat exactly
# still -- the longest window with client CPU, client I/O and relayed output ALL
# flat was 351.9 s, against a 180 s grace -- and the run was declared
# `STALLED: no forward progress ...` and the hard macro was never produced.
#
# LEFT ALONE, that same extraction finished: 5187.5 s (86 min 27 s), exit 0,
# `DIGITAL_LEF_WRITE_DONE`, a 21494-byte abstract with 84 pins. The stall
# verdict had fired at 13.6% of the real job. The tool was never the subject of
# that verdict; the client was.
#
# So a `docker exec` launch supervises the CONTAINER as well. The probe below
# sums CPU and I/O over the host processes that belong to this container and
# that started after the launch -- the exec's own work, not the container's
# idle main process and not a sibling that was already running. It is fused
# with the client probe rather than replacing it, so this can only ever add a
# reason to keep waiting.
#
# DEGRADE LOUDLY. `container_id` failing is recorded as the `container` signal
# staying False, and `Stalled` already prints which signals were readable, so a
# stall observed with no container channel reads differently from one observed
# with it.

_CLK_TCK = float(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else 100.0


def container_id(container: str) -> Optional[str]:
    """The container's full id, or None when it cannot be read.

    None is NOT "no such container" -- it is "I could not tell", which is why
    the caller degrades to the client-only signals and says so rather than
    treating the container as empty.
    """
    if not container or container == "host":
        return None
    try:
        cp = subprocess.run(  # nosec B603,B607 — fixed argv, no shell
            ["docker", "inspect", "-f", "{{.Id}}", container],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    cid = (cp.stdout or "").strip()
    return cid if cp.returncode == 0 and len(cid) >= 12 else None


def _uptime_ticks() -> Optional[float]:
    try:
        with open("/proc/uptime", "rb") as fh:
            return float(fh.read().split()[0]) * _CLK_TCK
    except (OSError, ValueError, IndexError):
        return None


def _in_container(pid: int, cid: str) -> bool:
    try:
        with open(f"/proc/{pid}/cgroup", "rb") as fh:
            return cid.encode("ascii") in fh.read()
    except OSError:
        return False


def _stat_fields(pid: int):
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            data = fh.read()
        return data[data.rfind(b")") + 2:].split()
    except (OSError, IndexError):
        return None


def container_tree_probe(container: str):
    """A `_progress_run` probe factory watching the WORK inside `container`.

    Returns ``factory(signals) -> probe(proc)``; the ``container`` key of
    ``signals`` records whether the channel was actually readable, so a stall
    reported with it missing can be told from one reported with it present.
    """
    def factory(signals):
        cid = container_id(container)
        # The launch instant, in the same units /proc/<pid>/stat field 22 uses.
        # Processes older than this belong to somebody else's work in the same
        # container and must not vouch for ours.
        since = _uptime_ticks()

        def probe(_proc) -> Optional[float]:
            if cid is None or since is None:
                return None
            total, seen = 0.0, False
            try:
                pids = [int(e) for e in os.listdir("/proc") if e.isdigit()]
            except OSError:
                return None
            for pid in pids:
                f = _stat_fields(pid)
                if not f or len(f) < 22:
                    continue
                try:
                    if float(f[19]) < since:      # field 22: starttime
                        continue
                except ValueError:
                    continue
                if not _in_container(pid, cid):
                    continue
                try:
                    # utime + stime, AND cutime + cstime: the CPU of children
                    # this process has already REAPED. Without the second pair
                    # a finished child's CPU vanishes from the sum, the total
                    # DROPS, and a monotonic-max meter reads its still-working
                    # siblings as still until they re-earn it. MEASURED (lane
                    # mig114, 2026-09-26): six parallel ngspice decks, one
                    # finished after 2 h 45 min, and the other five — all
                    # computing — were reaped as STALLED (rc 199) 3 min later.
                    total += (int(f[11]) + int(f[12])) / _CLK_TCK
                    seen = True
                except (ValueError, IndexError):
                    continue
                try:
                    total += (int(f[13]) + int(f[14])) / _CLK_TCK
                except (ValueError, IndexError):
                    pass
                try:
                    with open(f"/proc/{pid}/io", "rb") as fh:
                        for line in fh:
                            if line.startswith((b"read_bytes:", b"write_bytes:")):
                                total += float(line.split()[1]) / 1e6
                except (OSError, ValueError, IndexError):
                    # Another uid's process: /proc/<pid>/io is 0400. CPU from
                    # `stat` is world-readable and still counts, which is the
                    # measured case -- the tool runs as the image's own user.
                    pass
            if seen:
                signals["container"] = True
                return total
            return None
        return probe
    return factory


def container_deadline_argv(container: str,
                            cmd: str,
                            deadline_s: int,
                            kill_grace_s: int = DEFAULT_KILL_GRACE_S,
                            shell: Sequence[str] = ("bash", "-lc")) -> list:
    """The argv that runs ``cmd`` in ``container`` under a container-side deadline.

    Split out from :func:`run_in_container` so a test drives the SAME argv the
    caller runs rather than re-typing it — a re-typed argv agrees with the
    implementation by coincidence, which is how this class of defect returns.
    """
    return docker_exec_argv(
        container, "timeout", "-k", str(int(kill_grace_s)),
        str(int(deadline_s)), *shell, cmd)


def run_in_container(container: str,
                     cmd: str,
                     deadline_s: int = 120,
                     kill_grace_s: int = DEFAULT_KILL_GRACE_S,
                     client_grace_s: int = CLIENT_GRACE_S,
                     shell: Sequence[str] = ("bash", "-lc"),
                     ) -> subprocess.CompletedProcess:
    """Run a command with its deadline enforced inside the selected container."""
    return _pr.run(
        container_deadline_argv(container, cmd, deadline_s, kill_grace_s, shell),
        capture_output=True, text=True, errors="replace",
        progress_probe=container_tree_probe(container))


#: The rc a supervised container run reports when the TOOL stopped moving.
#: Inherited from `_progress_run` so the whole repo spells this outcome one way,
#: and distinct from `TIMEOUT_EXPIRED_RC` on purpose: "it stopped moving" and
#: "the clock ran out" are different findings and only one of them is about the
#: tool.
STALLED_RC = _pr.RC_STALLED


def _raw_exec(container: str, cmd: str, timeout: int = 15):
    """Run a short probe into the container for process cleanup."""
    try:
        cp = subprocess.run(  # nosec B603 — fixed argv, no shell
            docker_exec_argv(container, "bash", "-lc", cmd),
            capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return cp.returncode, cp.stdout or "", cp.stderr or ""


#: The line a supervised container run prints ONCE when its recorded budget is
#: crossed. A stable, greppable prefix so a log reader can find the crossing
#: without parsing prose, and so a test can assert the announcement happened.
CEILING_CROSSED_MARK = "VIBEIC_CEILING_CROSSED"


def default_ceiling_notice(container: str, ceiling_s: float, out=None):
    """The notice `run_in_container_supervised` installs when given none.

    ANNOUNCE AND CONTINUE. The budget stops nothing (vibe-ic#2051); its whole
    value is that a reader watching a long run learns, at the moment it
    happens, that this job has passed the time the flow used to allow it — and
    that it is still working. Written to stderr because that is where a
    supervisor's remarks about a run belong; the tool's own stdout stays
    exactly what the tool wrote.
    """
    stream = out if out is not None else sys.stderr

    def notice(elapsed_s: float) -> None:
        print(f"{CEILING_CROSSED_MARK} container={container} "
              f"ceiling_s={float(ceiling_s):.0f} elapsed_s={float(elapsed_s):.0f}"
              f" — the budget is a RECORD, not a kill: this job was NOT "
              f"signalled and is still running.", file=stream, flush=True)
    return notice


def run_in_container_supervised(container: str,
                                cmd: str,
                                ceiling_s: float = 86_400.0,
                                shell: Sequence[str] = ("bash", "-lc"),
                                stall_looks: int = _pr.DEFAULT_STALL_LOOKS,
                                ceiling_notice=None,
                                poll_s: Optional[float] = None,
                                ) -> subprocess.CompletedProcess:
    """Run ``cmd`` in ``container`` with NO CLOCK: reaped only on STILLNESS.

    THE DIFFERENCE FROM :func:`run_in_container`, and why it exists (owner
    ruling 2026-09-07, vibe-ic#2083). That function gives the tool a container-
    side `timeout -k 5 <deadline>`, which is a raw clock kill of a job that may
    be working perfectly — the class vibe-ic#2051 removed everywhere else. It
    is right for a call whose deadline really is a deadline; it is wrong for a
    long EDA run. MEASURED on 8HD-8 in the pinned image: the magic LEF
    extraction of a 35 MB GDS needs **5187 s** and finishes cleanly, so the
    shipped 900 s deadline would SIGTERM it at 17.4% of the job and the step
    would report "did not complete" about a tool that was never in trouble.

    The shape here is the one the supervised path already uses elsewhere:

      * `_docker_watchdog.supervised_container_command` — the shell records its
        own (pid, starttime) IDENTITY STAMP and then `exec`s the tool, so the
        stamped pid IS the tool's pid and is the leader of its process group.
        No `timeout`, no outer clock of any kind.
      * `_progress_run.run` with `container_tree_probe` — the stillness signal,
        which reads the CONTAINER's work rather than the `docker exec` client
        that cannot see it.
      * on a stall, `_docker_watchdog.kill_supervised_job` — TERM then KILL, by
        IDENTITY, so the reap can never select a stranger that happens to match
        a command line. THE ORPHAN CONTRACT IS KEPT AND SHARPENED: a still tool
        is reaped where it lives, a computing one is never cut.

    ``ceiling_s`` is a RECORDED BUDGET and stops nothing (vibe-ic#2051):
    the crossing is announced ONCE, on stderr, and the job runs on. The
    announcement is this function's to install (vibe-ic#2117): `_watchdog`
    calls an INJECTED `ceiling_notice`, `_progress_run.run` forwards one, and
    until both halves were wired every `ceiling_s` handed to this function was
    a budget whose crossing nothing outside the supervisor could observe --
    recorded in `observations`, carried back on nothing, printed nowhere.
    Pass `ceiling_notice=` to route it somewhere other than stderr.

    `poll_s` is the OBSERVATION CADENCE, not a bound on anything. `None` keeps
    the host-measured default (30 s here), which is right for a job measured in
    minutes and is also why the crossing of a small budget by a short job is
    not seen: the supervisor only looks between polls, so a job that finishes
    inside the first look after the budget is never observed to have crossed
    it. Exposed so a test can drive the announcement path against a REAL
    container command instead of asserting that it exists. The stall grace is
    `stall_looks * poll_s`, so a test that tightens the cadence must widen the
    look count or it has quietly built a clock.

    Returns the tool's own `CompletedProcess`, or one carrying `STALLED_RC`
    with the stall reason AND the reap evidence on `.stderr` — never the tool's
    rc for an outcome the tool did not reach.
    """
    # Imported HERE, not at module scope: `_docker_watchdog` imports this
    # module for `docker_exec_argv`, so a top-level import would be a cycle.
    import _docker_watchdog as _dw  # noqa: PLC0415

    pidfile = _dw.new_job_pidfile()
    wrapped = _dw.supervised_container_command(cmd, pidfile)
    argv = docker_exec_argv(container, *shell, wrapped)
    try:
        return _pr.run(argv, capture_output=True, text=True, errors="replace",
                       stall_looks=stall_looks, hard_ceiling_s=ceiling_s,
                       ceiling_notice=(ceiling_notice or
                                       default_ceiling_notice(container,
                                                              ceiling_s)),
                       **({} if poll_s is None else {"poll_s": float(poll_s)}),
                       progress_probe=container_tree_probe(container))
    except _pr.Stalled as exc:
        # REAP WHERE THE TOOL LIVES. The host-side supervisor has stopped
        # watching; without this the tool would be exactly the orphan the
        # container-side deadline used to prevent.
        reap = _dw.kill_supervised_job(container, pidfile,
                                       docker_exec_raw=_raw_exec)
        return subprocess.CompletedProcess(
            argv, STALLED_RC, exc.stdout or "",
            (exc.stderr or "") + "\n" + str(exc) + "\n" + (reap or "").strip())
    finally:
        _dw.cleanup_job_pidfile(container, pidfile, _raw_exec)


def describe_result(cp: subprocess.CompletedProcess,
                    deadline_s: int) -> Optional[str]:
    """A one-line operator-facing reason when the run did not complete normally.

    ``None`` when the command ran to completion (whatever its own verdict was).
    Callers use this so a deadline expiry is REPORTED as a deadline expiry and
    never as the tool's own answer — a killed run has no verdict, and recording
    one for it is the failure mode this whole module exists to prevent.
    """
    if cp.returncode == TIMEOUT_EXPIRED_RC:
        return (f"container-side deadline of {deadline_s}s expired; the tool "
                f"was signalled inside the container and produced no result")
    if cp.returncode == STALLED_RC:
        return ("the tool made no forward progress in the container — every "
                "readable signal (its own CPU and I/O inside the container, "
                "and the bytes it wrote) sat still while the supervisor "
                "looked; it was reaped by identity and no orphan remains")
    if cp.returncode == TIMEOUT_UNAVAILABLE_RC:
        return ("`timeout` is not available in this image, so NO deadline "
                "could be enforced; the command may have run unbounded")
    return None


# ---------------------------------------------------------------------------
# IS THERE A ROUTE TO A CONTAINER AT ALL?
# ---------------------------------------------------------------------------

def no_container_route() -> bool:
    """True when this process CANNOT reach any container, because there is no
    `docker` client on PATH.

    ONE definition, shared, because there are two independent ways this repo
    enters a container and each learned the same lesson separately:
    `phase3_one_shot_runner._docker_exec*` (`docker exec` into a named,
    already-running container) and `fault_atpg_run._run_docker` (`docker run`
    of a fresh sibling container). Both are unreachable when the runner is
    ALREADY RUNNING INSIDE that image — there is no docker binary in there —
    and both were returning 127 for every tool call while the tool itself sat
    on the process's own PATH. A second copy of this predicate is how the two
    would come to disagree about which route a run took.

    MEASURED 2026-09-06, subservient through the canonical front door inside
    ghcr.io/vibeic/vibeic-eda 0.3.46: with only the `docker exec` side taught
    to run locally, Phase 3 reached PnR but Step 11 still recorded
    `"exit": 127, "log_tail": "docker binary not found in PATH"` in
    `reports/phase2/dft/scan_chain.json` — so the run routed the PRE-SCAN
    netlist while the same tree run host-side routed the SCAN netlist, and the
    two disagreed about which steps even opened.

    DELIBERATELY NOT "and nobody named a container". A runner's own
    `--container` DEFAULT is published into `$EDA_CONTAINER`, so that question
    reads a value the runner wrote to itself and can never be false. What the
    naming buys is a NAME IN THE DIAGNOSTIC, not a route.

    UNCACHED ON PURPOSE: `shutil.which` is microseconds, callers that want a
    cache already have one, and a module-level cache here would have to stay
    coherent with theirs. Tool/PDK/chip-AGNOSTIC."""
    return shutil.which("docker") is None

# -------------------------------------------------------------------------
# THE SHARED IN-IMAGE ROUTE
#
# `no_container_route()` above answers the ONE question ("is there a route to
# any container from here"). Everything below is the small amount of argv and
# file-staging shaping that follows from that answer, kept HERE so that every
# runner which enters a container gets the same answer AND the same behaviour
# from it. `phase3_one_shot_runner` learned this first and carries its own
# copies of the shaping (landed as v1.18.20); `design_one_shot_runner` is the
# THIRD exec surface and uses these. The predicate is not duplicated — both
# call `no_container_route()` — so the two can disagree about wording but
# never about which route a run took.
# -------------------------------------------------------------------------

_ANNOUNCED: set = set()


def local_exec_mode(tag: str = "runner") -> bool:
    """True when this process must run its tools ON ITS OWN FILESYSTEM.

    Delegates to `no_container_route()` — there is exactly one definition of
    the question. `tag` names the announcing runner in the one-line stderr
    notice so a transcript records WHICH surface decided, and the notice is
    printed once per tag per process (a route silently taken is a route nobody
    can audit afterwards).

    Tool/PDK/chip-AGNOSTIC: nothing here names a tool, a PDK or a design."""
    local = no_container_route()
    if local and tag not in _ANNOUNCED:
        _ANNOUNCED.add(tag)
        import os
        named = os.environ.get("EDA_CONTAINER") or "<none named>"
        print("[%s] EXEC ROUTE = LOCAL: no docker client on PATH, so every "
              "tool command runs on THIS filesystem. The container named for "
              "this run (%s) was not entered and nothing was executed in it."
              % (tag, named), file=sys.stderr)
    return bool(local)


def exec_argv(container: str, wrapped: str, *,
              workdir: Optional[str] = None,
              shell: str = "bash",
              quiet: bool = True,
              login: bool = True,
              tag: str = "runner") -> list:
    """The argv that runs `wrapped` in a shell where the tools live.

    ONE seam for every `docker exec ... <shell> -c` site, so no two of them
    can drift into disagreeing about where a tool runs.

    CONTAINER ROUTE (the default, and byte-identical to what these sites have
    always emitted): `docker exec [-w <dir>] [-e IIC_OSIC_TOOLS_QUIET=1]
    <container> <shell> -lc <wrapped>`.

    LOCAL ROUTE: the same command in the same kind of LOGIN shell on this
    filesystem. `-w` has no docker to interpret it, so the workdir becomes an
    explicit `cd` — quoted, and `&&` so a missing directory FAILS the command
    instead of silently running it somewhere else. `-e` likewise cannot be a
    docker flag, so the knob goes into the environment before the login shell
    sources the image's profile; `setdefault` reproduces what `docker exec -e`
    does for the child and leaves an operator's own value alone.

    `login=False` keeps a plain `-c` for the sites that use one (a bare
    capability probe does not want a profile), so the container argv this
    returns is byte-identical to what each site emitted before."""
    if local_exec_mode(tag):
        if quiet:
            import os
            os.environ.setdefault("IIC_OSIC_TOOLS_QUIET", "1")
        if workdir:
            wrapped = "cd %s && %s" % (shlex.quote(str(workdir)), wrapped)
        return [shell, "-lc" if login else "-c", wrapped]
    # DELEGATED to `docker_exec_argv`, which is the ONE place a `docker exec`
    # argv is built AND the place the attach guard lives: it refuses to attach
    # to a container running bytes other than the pinned ones. Building the
    # argv here instead would have produced the same list and BYPASSED that
    # guard, which is the whole reason the builder exists. This function keeps
    # only what is its own — WHICH ROUTE the command takes — and the container
    # route it returns is byte-identical to what each site emitted before.
    opts: list = []
    if workdir:
        opts += ["-w", str(workdir)]
    if quiet:
        opts += ["-e", "IIC_OSIC_TOOLS_QUIET=1"]
    return docker_exec_argv(container, shell, "-lc" if login else "-c",
                            wrapped, opts=tuple(opts))


def annotate_local_exec(rc: int, err: str, tag: str = "runner") -> str:
    """Name the route when a LOCAL run reports 127.

    `yosys: command not found` inside the image and `No such file or
    directory: 'docker'` on a host without a client are two different
    diagnoses that the rc alone cannot tell apart. Bounded: one line,
    appended, never replacing what the shell said. A no-op outside local mode
    and for every rc but 127."""
    if rc != 127 or not local_exec_mode(tag):
        return err
    import os
    note = ("LOCAL_EXEC: no docker client on PATH, so this ran on THIS "
            "filesystem (container named for the run: %s, not entered); 127 "
            "means the tool is not on PATH here either — it does NOT mean a "
            "container was unreachable."
            % (os.environ.get("EDA_CONTAINER") or "<none named>"))
    return (err + "\n" + note) if err else note


def strip_container_prefix(spec: str, container: str) -> str:
    """`container:/some/path` -> `/some/path`; anything else unchanged.

    `docker cp` addresses one side of the copy with a `<container>:` prefix.
    In the local route that prefix names the filesystem this process is
    ALREADY ON, so removing it yields the real path. Only the declared
    container's own prefix is stripped, so a host path that merely contains a
    colon is left alone."""
    pre = "%s:" % container
    return spec[len(pre):] if container and spec.startswith(pre) else spec


def local_copy(src: str, dst: str, container: str = "") -> tuple:
    """The LOCAL equivalent of `docker cp src dst`: a real copy, both ways.

    `docker cp` is used here to STAGE a file where the tool will read it, and
    to RETRIEVE a produced file afterwards. In the image both endpoints are
    paths on this one filesystem, so the equivalent is a copy — NOT a no-op
    and NOT a removal. A no-op would leave the tool reading a file that is not
    there; a removal would destroy the input.

    Copies INTO the destination directory, creating it if needed, and
    preserves mtime/mode (`copy2`) because downstream freshness checks compare
    timestamps. When both sides resolve to the SAME file the copy is already
    satisfied and this is a success, not a `SameFileError`.

    Returns the `(rc, out, err)` triple the callers' `_run` returns."""
    s = strip_container_prefix(str(src), container)
    d = strip_container_prefix(str(dst), container)
    try:
        sp, dp = Path(s), Path(d)
        if dp.is_dir():
            dp = dp / sp.name
        if sp.resolve() == dp.resolve():
            return 0, "", ""
        dp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, dp)
        return 0, "", ""
    except Exception as e:                                   # noqa: BLE001
        return 1, "", "LOCAL_COPY failed %s -> %s: %s" % (s, d, e)


def local_engine_cwd():
    """A throwaway working directory for an engine launched on the LOCAL route.

    The container route never gives the engine the caller's cwd: `docker run`
    starts it in the image's WORKDIR, inside a filesystem `--rm` discards. The
    local route launched the same argv with NO `cwd=`, so the engine inherited
    whatever directory the CALLER was in -- and an engine that writes relative
    to its cwd wrote there. Measured in the vibeic-eda image under pytest: the
    ATPG engine's PLY parser (`parser.out`, `parsetab.py`, written to `.`) and
    its per-thread simulation directory (`thr0x.../tb.sv`) landed in the plugin
    root the suite was invoked from (F35).

    Returned as a `TemporaryDirectory`, so the caller runs the engine inside a
    `with` and the scratch disappears on exit, as the container's would. Every
    path the command names is absolute (`localise_mounted_paths`), so the cwd
    carries no input and loses no output.

    Tool/PDK/chip-AGNOSTIC: names no tool, PDK or design."""
    import vibeic_temp as _tempfile
    return _tempfile.TemporaryDirectory(prefix="vibeic_local_engine_")


def localise_mounted_paths(shell: str,
                           mounts: Sequence[tuple]) -> str:
    """Rewrite the container-absolute paths in `shell` to THIS filesystem.

    A `docker run` site writes its command against the mount points it is
    about to create (`/work`, `/pdk`, a private `/libmnt`). On the LOCAL route
    no mount is created, so the same command must name the same files under
    their REAL paths.  `mounts` is the site's own mount table as
    `(container_mount, host_path)` pairs — the site already has it, because it
    is what it hands to `-v`.

    ONE definition, here, for the same reason `no_container_route` is one:
    `fault_atpg_run` learned this rewrite first for `/work` + `/pdk`, and the
    at-speed producer needs it for those TWO PLUS the private liberty mount it
    adds when a `.lib` resolves outside the project.  A second copy is how the
    two would come to disagree about which files a local run read.

    Anchored on the mount point followed by `/` or by a word boundary, so a
    token that merely CONTAINS the mount name (a design called `network`, a
    path like `/opt/workspace`) is not rewritten.  Longest prefix first, so a
    `/work` substitution can never eat the head of a longer `/workdir` mount.

    Tool/PDK/chip-AGNOSTIC: nothing here names a tool, a PDK or a design."""
    import re as _re
    subs = [(str(m), str(h)) for m, h in mounts if m and h]
    subs.sort(key=lambda t: len(t[0]), reverse=True)
    for mount, real in subs:
        shell = _re.sub(_re.escape(mount) + r"(?=/|\b)",
                        real.rstrip("/"), shell)
    return shell
