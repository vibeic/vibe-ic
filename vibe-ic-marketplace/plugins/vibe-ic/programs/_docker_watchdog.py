#!/usr/bin/env python3
"""_docker_watchdog.py — the SHARED docker glue that routes a long in-container
EDA tool run through the general progress-stall primitive (`_watchdog.py`).

Owner directive (v1.3.48): "let watchdog be the common process for loop in the
vibe-ic plugin." Rather than every runner re-implementing progress-stall
supervision, each runner's ``_docker_exec(..., marker=...)`` dispatch delegates
HERE. `_watchdog.py` stays strictly docker/EDA-AGNOSTIC (it knows only generic
output/CPU counters); the docker specifics — the in-container CPU probe (via
``ps``), the marker ``pkill`` kill, and the ceiling ``timeout`` wrap — live here
and are INJECTED with the caller's OWN raw docker-exec, so this module never
assumes a particular exec implementation or bind-mount layout.

A long tool is killed ONLY when it makes NO forward progress (captured output
grew OR its in-container CPU advanced) for `stall_grace_s`; a still-progressing
tool runs to completion however long that legitimately takes. `marker` is a
token already present in the tool's argv (its script/deck path): it both sums
the tool's in-container CPU and targets the ``pkill``. chip/tool-AGNOSTIC.

(phase3_one_shot_runner keeps its own equivalent, proven glue for backward
compatibility; NEW callers — mixed_signal / design_one_shot / ppa — route here.)
"""
from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

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


def _sum_marked_tree_cpu(out: str, marker: str,
                         parse_cpu) -> Optional[float]:
    """Sum CPU over the PROCESS TREE rooted at marker-matched processes.

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
                          timeout: int = 15) -> Optional[float]:
    """Sum CPU-seconds (utime+stime) of the in-container process TREES whose
    root argv contains `marker` (descendants included — see
    `_sum_marked_tree_cpu`), using the injected raw exec for the short `ps`
    probe. Returns float seconds, or None when unavailable (no marker / ps
    missing / nothing matched). tool/chip-AGNOSTIC — `marker` is a caller
    token."""
    if not marker:
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
        total = _sum_marked_tree_cpu(out, marker, _parse_float)
        if total is not None:
            return total
    # Portable fallback: cputime = [[DD-]HH:]MM:SS
    rc, out, _ = docker_exec_raw(
        container, "ps -eo pid=,ppid=,cputime=,args= 2>/dev/null",
        timeout=timeout)
    if rc != 0 or not (out or "").strip():
        return None
    return _sum_marked_tree_cpu(out, marker, parse_cputime_hms)


def wrap_with_container_timeout(cmd: str, timeout_s: float,
                                margin_s: int = 5) -> str:
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
    """
    inner = max(1, int(timeout_s) - margin_s)
    return (
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
    probes only (never routed back through the supervisor)."""
    # OUTER backstop: wrap with a container-side `timeout` at the CEILING so the
    # tool self-terminates even if the host supervisor dies.
    wrapped = wrap_with_container_timeout(cmd, hard_ceiling_s)
    if container in ("", "host"):
        full = ["bash", "-lc", wrapped]
    else:
        full = ["docker", "exec", container, "bash", "-lc", wrapped]

    def _cpu_probe(_proc):
        return container_cpu_seconds(container, marker, docker_exec_raw)

    def _kill(_proc, reason):
        q = shlex.quote(marker)
        try:
            docker_exec_raw(container, f"pkill -TERM -f {q}", timeout=15)
            time.sleep(min(term_grace_s, 30))
            docker_exec_raw(container, f"pkill -KILL -f {q}", timeout=15)
        except Exception:  # nosec — best-effort in-container kill
            pass
        try:
            _proc.kill()
        except Exception:  # nosec — release the host docker-exec client
            pass

    res = _wd.run_supervised(
        full, log_path=log_path, cpu_probe=_cpu_probe, kill=_kill,
        stall_grace_s=stall_grace_s, poll_s=poll_s,
        hard_ceiling_s=hard_ceiling_s)
    return res.rc, res.out, res.err
