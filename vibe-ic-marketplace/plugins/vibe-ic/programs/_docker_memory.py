#!/usr/bin/env python3
"""_docker_memory.py — the memory ceiling every `docker run` in this plugin
carries, in one place.

MEASURED 2026-08-19 across a seven-machine fleet: 45 EDA containers were
running with `HostConfig.Memory == 0`. A container with no cgroup limit does
not share the host's memory — it IS the host's memory, and `ulimit -v` inside
our image is `unlimited`, so a tool never gets an allocation failure it could
report. On two of those machines a yosys took the whole box: 54 GB apiece for
two siblings, then 109 GB for the survivor once the kernel had killed its twin
and freed the room. The kernel picks its victim by oom_score_adj, so what
actually died was chrome and Xorg — the desktop session, not the tool that
caused it.

A ceiling makes that failure local: the kernel kills the runaway INSIDE the
container, the tool's log ends in "Killed", and the host keeps its cushion.
`--memory-swap` is pinned to the same value so the container cannot reach the
host's swap either; the minutes of "frozen" that preceded the crash were swap
thrash, not the kill.

This is deliberately NOT a budget by default. Each container gets the same
ceiling, so N concurrent containers can still exceed the host between them.
What it removes is the failure that actually happened: ONE tool, unattended,
taking everything.

MEASURED 2026-09-14 on 8HD-8, that deferred case arrived. Three containers,
one ngspice apiece at 25.3 / 24.8 / 23.8 GB, each correctly under its own
88 GB ceiling on a 126 GB host -- promised 264 GB between them:

    host memory  127,626 MB used of 128,721  ->  38 MB available
    host swap    2,047 of 2,047 MB           ->   0 B free
    host load    220 -> 24 (the CPU recovered; the memory never did)

It does not present as a memory failure. Every TCP port still completed its
handshake, so every liveness probe read the host as healthy while no userspace
process could answer: sshd took the connection and never sent its banner, and
the six production sites that host also serves returned nothing for forty
minutes. journalctl never broke and uptime never reset; the machine was never
down, it was starved.

VIBEIC_DOCKER_MEMORY_SHARED=1 turns the ceiling into a budget: what the
RUNNING containers have already been promised comes off the share first. It is
OPT-IN and stays that way, because subtracting a SIBLING'S CEILING is not the
same as subtracting what the sibling uses -- an idle container holding an 88 GB
promise would leave the next job the floor, and a ceiling that starves honest
work is the failure this module exists to avoid. Enable it where a dispatcher
is known to place several jobs per host; the durable fix is admission control
at the placement layer, which cannot live in this file.

Chip-AGNOSTIC and PDK-AGNOSTIC: nothing here reads a design, a tool name or a
technology.

Environment:
    VIBEIC_DOCKER_MEMORY            explicit ceiling; any docker size string
                                    ("48g", "64G", a plain byte count), or
                                    0 / unlimited / none to opt out entirely
    VIBEIC_DOCKER_MEMORY_FRACTION   percent of physical RAM when the above is
                                    unset (default 70)
    VIBEIC_DOCKER_MEMORY_SHARED     1/on/yes/true to subtract what the running
                                    containers already hold (default: off)
"""
from __future__ import annotations

import os
import subprocess
from typing import List, Optional

DEFAULT_FRACTION = 70
#: Below this a ceiling only breaks tools without protecting anything.
FLOOR_BYTES = 2 * 1024 ** 3
_OPT_OUT = {"0", "unlimited", "none", "off"}
_SHARING_ON = {"1", "on", "yes", "true"}


def physical_memory_bytes() -> Optional[int]:
    """Total RAM, or None where the platform will not say.

    `os.sysconf` answers on Linux and macOS alike and hands back an integer, so
    there is no text to parse and nothing to reformat. That last part is not
    hypothetical: the shell version of this ceiling first asked awk for
    `MemTotal * 1024`, which printed `134973464576` on one host and
    `1.34974e+11` on five others, and the five silently ran unbounded.
    """
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, AttributeError, OSError):
        return None
    if not isinstance(pages, int) or not isinstance(size, int):
        return None
    total = pages * size
    return total if total > 0 else None


def reserved_by_running_containers(runner=None) -> int:
    """Bytes already promised to RUNNING containers that carry a ceiling.

    A ZERO IS "I COULD NOT ASK", NEVER "THERE ARE NONE". When docker cannot be
    reached the caller is left with exactly the share it had without this
    function, because a guard that refuses a container on a host where docker
    is not installed is worse than the gap it closes.

    Reads `HostConfig.Memory`, which is the PROMISE, not the usage -- see the
    module docstring for why that distinction keeps this opt-in.
    """
    run = subprocess.run if runner is None else runner
    try:
        ps = run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=10)
    except Exception:
        return 0
    if getattr(ps, "returncode", 1) != 0:
        return 0
    ids = [i for i in (ps.stdout or "").split() if i]
    if not ids:
        return 0
    try:
        insp = run(["docker", "inspect", "-f", "{{.HostConfig.Memory}}", *ids],
                   capture_output=True, text=True, timeout=15)
    except Exception:
        return 0
    if getattr(insp, "returncode", 1) != 0:
        return 0
    total = 0
    for tok in (insp.stdout or "").split():
        try:
            v = int(tok)
        except ValueError:
            continue
        if v > 0:
            total += v
    return total


def sharing_enabled(env=None) -> bool:
    """True when the operator asked for a budget rather than a per-container cap."""
    env = os.environ if env is None else env
    return (env.get("VIBEIC_DOCKER_MEMORY_SHARED") or "").strip().lower() in _SHARING_ON


def memory_limit(env=None) -> Optional[str]:
    """The ceiling to pass to `docker run`, or None when opted out.

    Returns the value verbatim when the operator named one, so a docker size
    string stays readable in the argv the caller logs.
    """
    env = os.environ if env is None else env
    explicit = (env.get("VIBEIC_DOCKER_MEMORY") or "").strip()
    if explicit:
        return None if explicit.lower() in _OPT_OUT else explicit

    raw = (env.get("VIBEIC_DOCKER_MEMORY_FRACTION") or "").strip()
    fraction = DEFAULT_FRACTION
    if raw:
        try:
            fraction = int(raw)
        except ValueError:
            fraction = DEFAULT_FRACTION
        if not 1 <= fraction <= 100:
            fraction = DEFAULT_FRACTION

    total = physical_memory_bytes()
    if total is None:
        # Windows / an unusual libc. Docker there runs inside a VM that already
        # has its own hard ceiling, so an unbounded flag list is not the
        # host-killing configuration it would be on Linux. Say nothing and let
        # the operator set VIBEIC_DOCKER_MEMORY if they want one anyway.
        return None
    budget = total * fraction // 100
    if sharing_enabled(env):
        reserved = reserved_by_running_containers()
        if reserved > 0:
            budget -= reserved
    limit = max(budget, FLOOR_BYTES)
    limit = min(limit, total)
    return str(limit)


def docker_memory_flags(env=None) -> List[str]:
    """`--memory`/`--memory-swap` for a `docker run` argv, or [] when opted out.

    Splice this directly after the `run` verb. Both flags or neither: passing
    `--memory` alone leaves the container free to use the host's swap on top,
    which is the half of the incident that froze the machine.
    """
    limit = memory_limit(env)
    return [] if limit is None else ["--memory", limit, "--memory-swap", limit]


def _main(argv: List[str]) -> int:
    """`_docker_memory.py --flags` prints the flags, one per line, for shell
    callers (tools/vibeic-eda/restart-eda.sh). Exit 0 with NO output means the
    operator opted out; exit 2 means the ceiling could not be determined, which
    a caller must treat as a refusal rather than as "run unbounded" — a safety
    guard whose failure mode is "no guard" is worse than none, because it
    reports success.
    """
    if "--flags" not in argv:
        print("usage: _docker_memory.py --flags", flush=True)
        return 64
    env_opt = (os.environ.get("VIBEIC_DOCKER_MEMORY") or "").strip().lower()
    if env_opt in _OPT_OUT:
        return 0
    if physical_memory_bytes() is None:
        print("cannot determine physical memory; set VIBEIC_DOCKER_MEMORY "
              "explicitly, or VIBEIC_DOCKER_MEMORY=0 to opt out on purpose",
              flush=True)
        return 2
    for flag in docker_memory_flags():
        print(flag)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    import sys as _sys
    raise SystemExit(_main(_sys.argv[1:]))
