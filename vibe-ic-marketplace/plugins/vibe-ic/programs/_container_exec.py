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
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated

__all__ = [
    "run_in_container",
    "container_deadline_argv",
    "docker_exec_argv",
    "ContainerImageMismatch",
    "TIMEOUT_EXPIRED_RC",
    "TIMEOUT_UNAVAILABLE_RC",
    "IMAGE_MISMATCH_RC",
    "DEFAULT_KILL_GRACE_S",
    "CLIENT_GRACE_S",
]

#: coreutils `timeout` exit status when the deadline expired. Documented by
#: POSIX/GNU, not observed here, so keying on it is reading a protocol.
TIMEOUT_EXPIRED_RC = 124

#: `timeout` itself could not be run (127 = command not found, from the shell).
#: Surfaced rather than swallowed: see "degrade loudly" above.
TIMEOUT_UNAVAILABLE_RC = 127

#: The container does not hold the pinned image, so NOTHING was run in it.
#:
#: 125 is docker's own "the run itself could not be started" code, chosen so the
#: refusal cannot be mistaken for a verdict the TOOL produced. It is a non-zero
#: return like any other, which the `returncode != 0` handling every caller
#: already has will route -- the same reasoning that made an expired deadline
#: rc 124 rather than an exception thrown past callers that never expected one.
IMAGE_MISMATCH_RC = 125

#: Seconds between SIGTERM and the SIGKILL escalation.
DEFAULT_KILL_GRACE_S = 5

#: How much longer the client-side backstop waits than the container-side
#: deadline. Must be > 0 so the container-side deadline always fires first.
CLIENT_GRACE_S = 15


class ContainerImageMismatch(RuntimeError):
    """`docker exec` was about to address a container running the wrong bytes.

    Carries the refusal `_eda_pin` composed, which names BOTH digests.
    """


def docker_exec_argv(container: str, *rest: str,
                     opts: Sequence[str] = ()) -> list:
    """``["docker", "exec", *opts, container, *rest]`` — with the attach check.

    THE ONE PLACE A `docker exec` ARGV IS BUILT, and that is the whole point.
    `run_in_container` already refused to attach to a container running bytes
    other than the pinned ones, but it is not the only way into a container:
    MEASURED 2026-09-07, sixty-five argv constructions in thirty shipped files
    spelled ``["docker", "exec", …]`` by hand, and every one of them was a path
    on which the guarantee did not hold. A guard each caller must remember to
    invoke is a guard that decays; a guard in the constructor cannot be
    forgotten, because there is nothing else to call.

    ``opts`` are the flags that must precede the container name — ``-w``, ``-e``
    and friends. They are a separate parameter rather than leading positionals
    precisely so the CONTAINER is always an identified argument and can always
    be checked; a builder that took one flat argv would have to guess which
    element was the container, and guessing is what this module exists to stop.

    RAISES on a MEASURED MISMATCH, and only then. A digest that could not be
    read is NOT_MEASURED, never a mismatch (see `_eda_pin.container_pin_state`):
    the command is built and docker reports its own failure, as it always did.
    Raising rather than returning a marker argv is deliberate — an argv that
    looks runnable and is not would be discovered inside the tool's own output,
    which is the class of confusion this change removes.
    """
    why = _pin.container_attach_refusal(container)
    if why:
        raise ContainerImageMismatch(why)
    return _unguarded_exec_argv(container, *rest, opts=opts)


def _unguarded_exec_argv(container: str, *rest: str,
                         opts: Sequence[str] = ()) -> list:
    """The argv shape alone, with NO attach check.

    Exactly one caller is entitled to this: the refusal path below, which has
    the refusal in hand already and needs the argv only to RECORD what it
    declined to run. Asking the guard a second time there would raise out of the
    very branch whose contract is to RETURN `IMAGE_MISMATCH_RC` — measured while
    writing this: routing `container_deadline_argv` through the guard turned the
    landed rc-125 refusal into an exception.
    """
    return ["docker", "exec", *opts, container, *rest]


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
    """Run ``cmd`` inside ``container`` so the deadline kills the TOOL.

    Returns the ``CompletedProcess``. ``returncode == TIMEOUT_EXPIRED_RC``
    means the deadline expired and the tool was signalled; no orphan remains.

    Raises ``subprocess.TimeoutExpired`` only if the CONTAINER ITSELF is wedged
    past ``deadline_s + client_grace_s`` — the case a container-side deadline
    cannot cover, and the only case in which an orphan is still possible.

    THE ATTACH CHECK RUNS FIRST, and it is not optional. ``docker exec`` takes a
    NAME, and a name is a label whichever process got there first is holding.
    MEASURED 2026-09-07 on 8hd-3: the container named ``vibeic-eda`` was running
    ``sha256:06537f7e…`` (0.3.46) while the pin demanded ``sha256:8da785a8…``,
    and a run that attached to it recorded image provenance PASS about the wrong
    image -- a report that named a digest, and so read as reproducible, and was
    reproducibly about a toolchain nobody had pinned.

    When the bytes do not match, ``IMAGE_MISMATCH_RC`` comes back with the
    refusal on stderr and THE COMMAND IS NOT RUN. Naming both digests is the
    load-bearing part of the message: a reader told only that something
    mismatched cannot tell a stale container from a mis-set
    ``VIBEIC_EDA_IMAGE_REPO``, and will simply re-run it.
    """
    # ONLY A MEASURED DISAGREEMENT STOPS THIS. A container whose image cannot
    # be read is NOT_MEASURED, not a mismatch: docker reports that itself, as it
    # always did, and refusing on it would make every locally-built container
    # unusable while claiming to have judged its image.
    why = _pin.container_attach_refusal(container)
    if why:
        return subprocess.CompletedProcess(
            args=_unguarded_exec_argv(
                container, "timeout", "-k", str(int(kill_grace_s)),
                str(int(deadline_s)), *shell, cmd),
            returncode=IMAGE_MISMATCH_RC, stdout="",
            stderr=f"_container_exec: refused, nothing was run: {why}\n")
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
    if cp.returncode == IMAGE_MISMATCH_RC:
        # The refusal already names both digests; it is relayed verbatim rather
        # than summarised, because "the container is the wrong image" is only
        # actionable when the reader is told WHICH wrong image.
        return (cp.stderr or "").strip() or (
            f"the container does not hold the pinned image "
            f"({_pin.CONTAINER_IMAGE_MISMATCH}); nothing was run")
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
