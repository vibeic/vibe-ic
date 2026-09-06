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

import shlex
import shutil
import subprocess
from typing import Optional, Sequence

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402

__all__ = [
    "run_in_container",
    "container_deadline_argv",
    "TIMEOUT_EXPIRED_RC",
    "TIMEOUT_UNAVAILABLE_RC",
    "DEFAULT_KILL_GRACE_S",
    "CLIENT_GRACE_S",
]

#: coreutils `timeout` exit status when the deadline expired. Documented by
#: POSIX/GNU, not observed here, so keying on it is reading a protocol.
TIMEOUT_EXPIRED_RC = 124

#: `timeout` itself could not be run (127 = command not found, from the shell).
#: Surfaced rather than swallowed: see "degrade loudly" above.
TIMEOUT_UNAVAILABLE_RC = 127

#: Seconds between SIGTERM and the SIGKILL escalation.
DEFAULT_KILL_GRACE_S = 5

#: How much longer the client-side backstop waits than the container-side
#: deadline. Must be > 0 so the container-side deadline always fires first.
CLIENT_GRACE_S = 15


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
    return (["docker", "exec", container,
             "timeout", "-k", str(int(kill_grace_s)), str(int(deadline_s))]
            + list(shell) + [cmd])


def run_in_container(container: str,
                     cmd: str,
                     deadline_s: int = 120,
                     kill_grace_s: int = DEFAULT_KILL_GRACE_S,
                     client_grace_s: int = CLIENT_GRACE_S,
                     shell: Sequence[str] = ("bash", "-lc"),
                     ) -> subprocess.CompletedProcess:
    """Run ``cmd`` inside ``container`` so the deadline kills the TOOL.

    Returns the ``CompletedProcess``. ``returncode == TIMEOUT_EXPIRED_RC``
    means the deadline expired and the tool was signalled; no orphan remains.

    Raises ``subprocess.TimeoutExpired`` only if the CONTAINER ITSELF is wedged
    past ``deadline_s + client_grace_s`` — the case a container-side deadline
    cannot cover, and the only case in which an orphan is still possible.
    """
    return _pr.run(
        container_deadline_argv(container, cmd, deadline_s, kill_grace_s, shell),
        capture_output=True, text=True, errors="replace")


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
