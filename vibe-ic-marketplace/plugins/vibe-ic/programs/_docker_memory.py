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

This is deliberately NOT a budget. Each container gets the same ceiling, so N
concurrent containers can still exceed the host between them. What it removes
is the failure that actually happened: ONE tool, unattended, taking everything.

Chip-AGNOSTIC and PDK-AGNOSTIC: nothing here reads a design, a tool name or a
technology.

Environment:
    VIBEIC_DOCKER_MEMORY            explicit ceiling; any docker size string
                                    ("48g", "64G", a plain byte count), or
                                    0 / unlimited / none to opt out entirely
    VIBEIC_DOCKER_MEMORY_FRACTION   percent of physical RAM when the above is
                                    unset (default 70)
"""
from __future__ import annotations

import os
from typing import List, Optional

DEFAULT_FRACTION = 70
#: Below this a ceiling only breaks tools without protecting anything.
FLOOR_BYTES = 2 * 1024 ** 3
_OPT_OUT = {"0", "unlimited", "none", "off"}


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
    limit = total * fraction // 100
    limit = max(limit, FLOOR_BYTES)
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
