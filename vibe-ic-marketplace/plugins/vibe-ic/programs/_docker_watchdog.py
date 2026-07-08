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


def container_cpu_seconds(container: str, marker: Optional[str],
                          docker_exec_raw: RawExec,
                          timeout: int = 15) -> Optional[float]:
    """Sum CPU-seconds (utime+stime) of in-container processes whose argv
    contains `marker`, using the injected raw exec for the short `ps` probe.
    Returns float seconds, or None when unavailable (no marker / ps missing /
    nothing matched). tool/chip-AGNOSTIC — `marker` is a caller token."""
    if not marker:
        return None
    rc, out, _ = docker_exec_raw(
        container, "ps -eo cputimes=,args= 2>/dev/null", timeout=timeout)
    if rc == 0 and (out or "").strip():
        total, found = 0.0, False
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) < 2 or marker not in parts[1]:
                continue
            try:
                total += float(parts[0])
                found = True
            except ValueError:
                continue
        if found:
            return total
    # Portable fallback: cputime = [[DD-]HH:]MM:SS
    rc, out, _ = docker_exec_raw(
        container, "ps -eo cputime=,args= 2>/dev/null", timeout=timeout)
    if rc != 0 or not (out or "").strip():
        return None
    total, found = 0.0, False
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or marker not in parts[1]:
            continue
        secs = parse_cputime_hms(parts[0])
        if secs is not None:
            total += secs
            found = True
    return total if found else None


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
    ceil_inner = max(1, int(hard_ceiling_s) - 5)
    wrapped = (
        f"if command -v timeout >/dev/null 2>&1; then "
        f"exec timeout --kill-after=5 {ceil_inner} bash -lc {shlex.quote(cmd)}; "
        f"else exec bash -lc {shlex.quote(cmd)}; fi"
    )
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
