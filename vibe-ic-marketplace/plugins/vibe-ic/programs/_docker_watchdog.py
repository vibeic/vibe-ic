#!/usr/bin/env python3
"""_docker_watchdog.py — the SHARED docker glue that routes a long in-container
EDA tool run through the general progress-stall primitive (`_watchdog.py`).

Owner directive (v1.3.48): "let watchdog be the common process for loop in the
vibe-ic plugin." Rather than every runner re-implementing progress-stall
supervision, each runner's ``_docker_exec(..., marker=...)`` dispatch delegates
HERE. `_watchdog.py` stays strictly docker/EDA-AGNOSTIC (it knows only generic
output/CPU counters); the docker specifics — the in-container CPU probe (via
``ps``), the IDENTITY-ANCHORED reap, and the ceiling ``timeout`` wrap — live
here and are INJECTED with the caller's OWN raw docker-exec, so this module
never assumes a particular exec implementation or bind-mount layout.

A long tool is killed ONLY when it makes NO forward progress (captured output
grew OR its in-container CPU advanced) for `stall_grace_s`; a still-progressing
tool runs to completion however long that legitimately takes.

WHICH process gets killed is decided by IDENTITY, never by a name: the job
stamps ``(pid, /proc starttime)`` into a per-invocation pidfile at spawn and
the reap signals only that verified root plus its ppid-walked descendants.
`marker` remains a caller token used ONLY to sum CPU before the stamp lands.
chip/tool-AGNOSTIC.

phase3_one_shot_runner keeps its own `_docker_exec` wrapper (it has its own
env/log/outputs concerns) but DELEGATES the reap and the ceiling wrap here, so
there is exactly ONE implementation of each — the same delegation already used
for `container_cpu_seconds`.
"""
from __future__ import annotations

import secrets
import shlex
import time
from pathlib import Path
from typing import Callable, Optional, Set, Tuple

import _watchdog as _wd

DEFAULT_POLL_S = _wd.DEFAULT_POLL_S
DEFAULT_STALL_GRACE_S = _wd.DEFAULT_STALL_GRACE_S
DEFAULT_HARD_CEILING_S = _wd.DEFAULT_HARD_CEILING_S
RC_STALLED = _wd.RC_STALLED
RC_CEILING = _wd.RC_CEILING

_TERM_GRACE_S = 10        # SIGTERM → SIGKILL escalation window

# type of the injected raw exec: (container, cmd, timeout) -> (rc, out, err)
RawExec = Callable[..., Tuple[int, str, str]]


def parse_cputime_hms(tok: str) -> Optional[float]:
    """Parse a ps `cputime` token ``[[DD-]HH:]MM:SS`` → total seconds."""
    try:
        days = 0
        if "-" in tok:
            d, tok = tok.split("-", 1)
            days = int(d)
        bits = [int(x) for x in tok.split(":")]
        while len(bits) < 3:
            bits.insert(0, 0)
        h, m, s = bits[-3], bits[-2], bits[-1]
        return days * 86400 + h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return None


def _sum_marked_tree_cpu(out: str, marker: Optional[str],
                         parse_cpu,
                         root: Optional[int] = None) -> Optional[float]:
    """Sum CPU over the PROCESS TREE rooted at `root` (the identity-verified
    pid) when one is known, else at marker-matched processes.

    Rows are `pid ppid cpu args`. The match set is every process whose argv
    contains `marker` PLUS all transitive descendants. The descendants are
    load-bearing: yosys runs its whole ABC technology-mapping pass in a child
    `yosys-abc` whose argv does NOT carry the caller's marker (the output
    netlist path lives only in the parent's `-p` script). During ABC's long
    quiet phase the parent idles, the log stops growing, and the child burns
    100% CPU invisibly — argv-only accounting reported zero progress and the
    stall watchdog killed a HEALTHY 1.8M-cell synth at the 30-min grace
    (first hit: Kimi-scale phase-3 synth; the identical run passed earlier
    purely because a lighter machine kept ABC's quiet phase under the grace).
    """
    rows = []
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, cpu_tok, args = parts
        cpu = parse_cpu(cpu_tok)
        if cpu is None:
            continue
        rows.append((pid, ppid, cpu, args))
    if root is not None:
        # IDENTITY root: the pid we stamped at spawn. A command line cannot
        # identify a process, so once the stamp exists we stop asking argv.
        matched = {pid for pid, _pp, _c, _a in rows if pid == str(root)}
    else:
        matched = {pid for pid, _pp, _c, args in rows if marker in args}
    if not matched:
        return None
    grew = True
    while grew:
        grew = False
        for pid, ppid, _c, _a in rows:
            if pid not in matched and ppid in matched:
                matched.add(pid)
                grew = True
    return sum(c for pid, _pp, c, _a in rows if pid in matched)


def container_cpu_seconds(container: str, marker: Optional[str],
                          docker_exec_raw: RawExec,
                          timeout: int = 15,
                          pidfile: Optional[str] = None) -> Optional[float]:
    """Sum CPU-seconds (utime+stime) of the supervised job's process TREE
    (descendants included — see `_sum_marked_tree_cpu`), using the injected raw
    exec for the short `ps` probe.

    The tree ROOT is the identity-verified pid read back from `pidfile` when
    one is supplied and already stamped; only until then (a startup race of at
    most one poll) does it fall back to matching `marker` in argv. That matters
    beyond tidiness: an argv match can attribute a STRANGER's CPU to this job,
    and a stranger burning CPU would read as forward progress and keep a
    genuine runaway alive — the reaper failing to fire is as much a defect as
    the reaper firing on the wrong process.

    Returns float seconds, or None when unavailable (no marker and no stamp /
    ps missing / nothing matched). A None is SAFE: `_watchdog.ProgressMeter`
    carries the last CPU reading forward, so a vanishing signal is never
    mistaken for progress. tool/chip-AGNOSTIC — `marker` is a caller token."""
    root = None
    if pidfile:
        root = read_job_pid(container, pidfile, docker_exec_raw,
                            timeout=timeout)
    if root is None and not marker:
        return None

    def _parse_float(tok):
        try:
            return float(tok)
        except ValueError:
            return None

    rc, out, _ = docker_exec_raw(
        container, "ps -eo pid=,ppid=,cputimes=,args= 2>/dev/null",
        timeout=timeout)
    if rc == 0 and (out or "").strip():
        total = _sum_marked_tree_cpu(out, marker, _parse_float, root=root)
        if total is not None:
            return total
    # Portable fallback: cputime = [[DD-]HH:]MM:SS
    rc, out, _ = docker_exec_raw(
        container, "ps -eo pid=,ppid=,cputime=,args= 2>/dev/null",
        timeout=timeout)
    if rc != 0 or not (out or "").strip():
        return None
    return _sum_marked_tree_cpu(out, marker, parse_cputime_hms, root=root)


# ===========================================================================
# IDENTITY-ANCHORED REAP — kill the job we started, never a stranger's.
# ===========================================================================
# MEASURED 2026-08-27. The reap used to be `pkill -TERM/-KILL -f <marker>`,
# with no `-x`, no uid filter, no pid and no pgid. `marker` is a PATH already
# present in the tool's argv, so the pattern matched ANY process whose command
# line contained that path — and the blast radius is the PID namespace of the
# SINGLE long-lived `vibeic-eda` container that every run on the host shares.
# One run's stall watchdog therefore SIGTERMed a DIFFERENT run's healthy tool.
#
# The signature is `rc=143 with ZERO test failures`, seen three times in one
# night at 85 s, 17 min and 46 min — no consistent duration, and no cgroup OOM
# in dmesg for the third, which is what ruled out a resource ceiling. It was
# not merely rude: `lec_run` did not carry 143 in its container-timeout set at
# all, so a stray SIGTERM fell through to a hard FAIL and a HEALTHY design was
# booked as a PROVEN NON-EQUIVALENCE. (The consumer side is repaired
# separately by `lec_run.classify_container_kill`, which separates an external
# kill from a real deadline; this is the PRODUCER side — stop emitting it.)
#
# Why `-x` is NOT the fix: `-x` matches the full command line exactly, and the
# stranger on this fleet is running the IDENTICAL command line on the same
# shared namespace. Exactness makes the pattern stricter, not the selection
# correct. No pattern over argv can distinguish two processes that share argv.
#
# The victim is therefore selected the way `_owned_process_supervisor` already
# selects one — IDENTITY = ``(pid, /proc starttime)`` (its `Identity` type and
# `_read_proc_identity`), extended over the descendants reached by walking
# ppid from that verified root (its `_descendants`). The job stamps its own
# identity at spawn (`identity_stamp_prelude`); the reap reads it back,
# RE-VALIDATES starttime so a recycled PID is never signalled, and signals
# only that set.
#
# When the stamp is missing, unreadable, or no longer matches, the reap does
# NOTHING and says why. It never falls back to a pattern — a fallback to the
# broken selector would reinstate the defect on exactly the paths where the
# stamp failed. The recovery the reaper exists for survives untouched: a real
# runaway IS its own stamped root, so it is still killed, together with every
# child it spawned (GNU `timeout` puts the job in its own process group, and
# the ppid walk catches anything that left the group).

_PIDFILE_DIR = "/tmp"
_PIDFILE_PREFIX = ".vibeic-job-"

# `starttime` is field 22 of /proc/<pid>/stat. `comm` (field 2) may itself
# contain spaces and parentheses, so the fields are counted from AFTER the
# LAST ')' — byte-for-byte the same rule as
# `_owned_process_supervisor._read_proc_identity`, which does
# `raw[raw.rfind(")") + 2:].split()[19]`.
_ST_FN = (
    "__vic_st(){ sed 's/^.*) //' \"/proc/$1/stat\" 2>/dev/null"
    " | awk '{print $20}'; }; "
)

# Reads the stamp and REFUSES to proceed unless the live starttime still
# equals the stamped one. Leaves the verified pid in $VPID.
_IDENTITY_GATE = (
    "PF=__PIDFILE__; "
    "[ -r \"$PF\" ] || { echo VIBEIC_REAP_SKIP no_stamp; exit 0; }; "
    "read -r VPID VST _r < \"$PF\" 2>/dev/null"
    " || { echo VIBEIC_REAP_SKIP unreadable; exit 0; }; "
    "case \"$VPID\" in ''|*[!0-9]*) echo VIBEIC_REAP_SKIP bad_pid; exit 0;; "
    "esac; "
    "case \"$VST\" in ''|*[!0-9]*) echo VIBEIC_REAP_SKIP bad_starttime; "
    "exit 0;; esac; "
    "VCUR=$(__vic_st \"$VPID\"); "
    "[ -n \"$VCUR\" ] || { echo VIBEIC_REAP_SKIP already_gone; exit 0; }; "
    "[ \"$VCUR\" = \"$VST\" ]"
    " || { echo VIBEIC_REAP_SKIP pid_reused; exit 0; }; "
)

# Descendant closure by ppid from the verified root, then signal. Both the
# process GROUP (when the root leads one, which `timeout` arranges) and the
# explicit pid set are signalled: the group is atomic, the walk catches a
# child that called setpgid and left it.
_REAP_TAIL = (
    "VKIDS=$(ps -eo pid=,ppid= 2>/dev/null | awk -v r=\"$VPID\" '"
    "{p[NR]=$1; q[NR]=$2; n=NR} "
    "END{s[r]=1; c=1; "
    "while(c){c=0; for(i=1;i<=n;i++) "
    "if(!(p[i] in s) && (q[i] in s)){s[p[i]]=1; c=1}} "
    "for(k in s) if(k!=r) printf \"%s \", k}'); "
    "VPG=$(ps -o pgid= -p \"$VPID\" 2>/dev/null | tr -d ' '); "
    "if [ \"$VPG\" = \"$VPID\" ]; then "
    "kill -__SIG__ -- \"-$VPID\" 2>/dev/null || :; fi; "
    "kill -__SIG__ \"$VPID\" $VKIDS 2>/dev/null || :; "
    "echo VIBEIC_REAP __SIG__ \"$VPID\" $VKIDS; "
)


def new_job_pidfile() -> str:
    """A fresh, unguessable stamp path for ONE supervised job.

    The nonce keeps two concurrent jobs in the same namespace from sharing a
    stamp. It is a FILE PATH, never a search pattern: identity comes from the
    (pid, starttime) pair INSIDE the file, so a stranger who happened to carry
    this path in its argv still could not be selected."""
    return "%s/%s%s.pid" % (_PIDFILE_DIR, _PIDFILE_PREFIX,
                            secrets.token_hex(8))


def identity_stamp_prelude(pidfile: str) -> str:
    """Shell that records ``<pid> <starttime>`` of the about-to-exec job.

    Runs in the same shell that then `exec`s the tool, so the recorded pid IS
    the pid the tool inherits (exec replaces the image, keeping the pid), and
    with GNU `timeout` in front that pid is also the process-GROUP leader."""
    return (_ST_FN + "printf '%s %s\\n' \"$$\" \"$(__vic_st $$)\" > "
            + shlex.quote(pidfile) + " 2>/dev/null || :; ")


def reap_command(pidfile: str, sig: str) -> str:
    """Shell that signals ONLY the stamped, still-identical job tree."""
    if sig not in ("TERM", "KILL"):
        raise ValueError("sig must be TERM or KILL, got %r" % (sig,))
    return (_ST_FN
            + _IDENTITY_GATE.replace("__PIDFILE__", shlex.quote(pidfile))
            + _REAP_TAIL.replace("__SIG__", sig))


def job_pid_command(pidfile: str) -> str:
    """Shell that echoes ``VIBEIC_JOBPID <pid>`` for the verified job."""
    return (_ST_FN
            + _IDENTITY_GATE.replace("__PIDFILE__", shlex.quote(pidfile))
            + "echo VIBEIC_JOBPID \"$VPID\"; ")


def read_job_pid(container: str, pidfile: str, docker_exec_raw: RawExec,
                 timeout: int = 15) -> Optional[int]:
    """The job's identity-verified pid, or None when it is not (yet) known."""
    try:
        rc, out, _ = docker_exec_raw(container, job_pid_command(pidfile),
                                     timeout=timeout)
    except Exception:  # nosec — a probe failure is just "no reading"
        return None
    if rc != 0:
        return None
    for line in (out or "").splitlines():
        if line.startswith("VIBEIC_JOBPID "):
            tok = line.split()[1] if len(line.split()) > 1 else ""
            if tok.isdigit():
                return int(tok)
    return None


def reaped_pids(reap_output: str) -> Set[int]:
    """The pids a `reap_command` reported signalling. Evidence, not control."""
    out: Set[int] = set()
    for line in (reap_output or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "VIBEIC_REAP":
            for tok in parts[2:]:
                if tok.isdigit():
                    out.add(int(tok))
    return out


def kill_supervised_job(container: str, pidfile: str, *,
                        docker_exec_raw: RawExec,
                        term_grace_s: float = _TERM_GRACE_S,
                        timeout: int = 15) -> str:
    """TERM the stamped job tree, wait out the grace, then KILL what is left.

    Returns the concatenated reap output (``VIBEIC_REAP``/``VIBEIC_REAP_SKIP``
    lines) so a caller — or a test — can see exactly which pids were signalled
    and, when none were, why not."""
    seen = []
    try:
        _rc, out, _err = docker_exec_raw(
            container, reap_command(pidfile, "TERM"), timeout=timeout)
        seen.append(out or "")
        time.sleep(min(term_grace_s, 30))
        _rc, out, _err = docker_exec_raw(
            container, reap_command(pidfile, "KILL"), timeout=timeout)
        seen.append(out or "")
    except Exception:  # nosec — best-effort reap; never mask the tool's rc
        pass
    return "".join(seen)


def cleanup_job_pidfile(container: str, pidfile: str,
                        docker_exec_raw: RawExec, timeout: int = 15) -> None:
    """Drop the stamp once the job is done. Best-effort; a leftover stamp is
    inert anyway (its starttime can no longer match a live process)."""
    try:
        docker_exec_raw(container, "rm -f -- " + shlex.quote(pidfile),
                        timeout=timeout)
    except Exception:  # nosec
        pass


def wrap_with_container_timeout(cmd: str, timeout_s: float,
                                margin_s: int = 5, *,
                                pidfile: Optional[str] = None) -> str:
    """Give an in-container command its OWN deadline, `margin_s` before the
    host's.

    WHY (measured 2026-07-22): a host-side `subprocess.run(..., timeout=N)`
    kills the *`docker exec` client*, NOT the process inside the container.
    Docker does not propagate that to the exec'd process, so the tool is
    ORPHANED and keeps running — forever, unsupervised, holding its memory and
    a core inside a cpu/memory-capped container that the rest of the run is
    still sharing. Observed in one `ps` listing, 18 minutes after a 300 s
    timeout was recorded, the leaked call and a correctly-wrapped one side by
    side:

        116   18:17  yosys -p read_verilog ...        <- leaked, no wrapper
        2616  13:16  timeout --kill-after=5 86395 bash -lc ...   <- bounded
        2647  13:16  yosys -p read_slang ...

    Worse than the resource leak: both invocations wrote the SAME output
    netlist path, so the orphan was free to overwrite the good artifact
    produced by the step that replaced it — a silent wrong-result hazard, not
    just waste.

    The wrap is what makes the host deadline real: GNU `timeout` puts the
    command in its own process group and signals the GROUP, so a tool that
    spawns children (yosys -> abc, magic -> ext2spice) is torn down whole.
    `--kill-after=5` escalates TERM to KILL. Firing `margin_s` early means the
    container side is already dead when the host raises TimeoutExpired, so the
    caller still gets its rc/partial output.

    Degrades gracefully: a container with no `timeout` binary runs exactly as
    before. chip/tool-AGNOSTIC.

    `pidfile` (optional) prepends the IDENTITY STAMP: the shell records its own
    (pid, /proc starttime) before `exec`ing the tool, which is what lets the
    reap select this exact job instead of pattern-matching a command line. The
    stamp is best-effort and never fails the command. Omitting `pidfile`
    reproduces the previous string BYTE-FOR-BYTE, so every existing caller and
    its tests are untouched.
    """
    inner = max(1, int(timeout_s) - margin_s)
    prelude = identity_stamp_prelude(pidfile) if pidfile else ""
    return (
        prelude +
        f"if command -v timeout >/dev/null 2>&1; then "
        f"exec timeout --kill-after=5 {inner} bash -lc {shlex.quote(cmd)}; "
        f"else exec bash -lc {shlex.quote(cmd)}; fi"
    )


def run_docker_supervised(container: str, cmd: str, marker: str, *,
                          docker_exec_raw: RawExec,
                          log_path: Optional[Path] = None,
                          stall_grace_s: float = DEFAULT_STALL_GRACE_S,
                          poll_s: float = DEFAULT_POLL_S,
                          hard_ceiling_s: float = DEFAULT_HARD_CEILING_S,
                          term_grace_s: float = _TERM_GRACE_S
                          ) -> Tuple[int, str, str]:
    """Launch `cmd` inside `container` (or on the host when container is ''/
    'host') under the progress-stall watchdog. Returns (rc, out, err) where rc
    is the tool's natural rc, RC_STALLED on a no-progress kill, or RC_CEILING on
    the 24h+ pathological backstop. `docker_exec_raw` runs the short CPU/kill
    probes only (never routed back through the supervisor).

    `container in ("", "host")` is the NATIVE mode: the tools are installed on
    the host and there is no container to exec into, so both the job and the
    probes run in the host's own process table. That mode is legitimate and
    stays — what was never legitimate is the reap it used to perform there. A
    `pkill -f` dispatched through a host-mode raw exec searched the WHOLE HOST
    process table, which is strictly worse than the container-scoped version of
    the same bug. Identity selection removes the distinction: the stamp names
    one process in whichever namespace the job was started in, so native mode
    and container mode reap exactly the job they launched and nothing else."""
    # Per-invocation identity stamp: written by the job itself at spawn, read
    # back by the reap. This is what replaces `pkill -f <marker>`.
    pidfile = new_job_pidfile()

    # OUTER backstop: wrap with a container-side `timeout` at the CEILING so the
    # tool self-terminates even if the host supervisor dies.
    wrapped = wrap_with_container_timeout(cmd, hard_ceiling_s,
                                          pidfile=pidfile)
    if container in ("", "host"):
        full = ["bash", "-lc", wrapped]
    else:
        full = ["docker", "exec", container, "bash", "-lc", wrapped]

    def _cpu_probe(_proc):
        return container_cpu_seconds(container, marker, docker_exec_raw,
                                     pidfile=pidfile)

    def _kill(_proc, reason):
        kill_supervised_job(container, pidfile,
                            docker_exec_raw=docker_exec_raw,
                            term_grace_s=term_grace_s)
        try:
            _proc.kill()
        except Exception:  # nosec — release the host docker-exec client
            pass

    try:
        res = _wd.run_supervised(
            full, log_path=log_path, cpu_probe=_cpu_probe, kill=_kill,
            stall_grace_s=stall_grace_s, poll_s=poll_s,
            hard_ceiling_s=hard_ceiling_s)
    finally:
        cleanup_job_pidfile(container, pidfile, docker_exec_raw)
    return res.rc, res.out, res.err
