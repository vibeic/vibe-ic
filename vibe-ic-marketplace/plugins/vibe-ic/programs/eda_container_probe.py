#!/usr/bin/env python3
"""A container/image probe that cannot report "absent" when it never answered.

FOUND BY BEING BITTEN BY IT (vibe-ic#1283). Two probes in the test suite were
written as:

    try:
        r = subprocess.run([...], capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False

`docker image inspect` reads LOCAL metadata and normally returns in
milliseconds. Under fleet load — several agents each running docker-touching
suites on one host — it exceeds 30s. `TimeoutExpired` is an `Exception`, the
handler returns `False`, and the test then skips with the reason

    "vibeic-eda container not available"

which is a claim about the image that the probe never established. Measured on
an UNCHANGED tree, same 39-file selection, same command:

    run 1 (machine contended) : 446 passed, 6 skipped
    run 2 (machine idle)      : 451 passed, 1 skipped

Five assertions moved from RAN to NOT-RUN and both runs reported green.

    A CHECK THAT COULD NOT RUN AND A CHECK THAT FOUND A DEFECT ARE NOT THE
    SAME RESULT.

That sentence is this repository's own, from
`test_image_version_unreachable_is_not_a_failed_pin.py`, which fixed the
identical conflation in the image-version gate (#354/#566). This module carries
the same distinction into the test-side probes, using the vocabulary already in
use in four other places: `run_tolerating_uncheckable` (rc 2, NOT CHECKED,
non-fatal), `gate_host_independence_check`'s DIRTY_CHECKOUT, and
`NOTHING_SCANNED` in the NDA and portability scanners.

THREE OUTCOMES, NOT TWO:

    PRESENT     the probe answered and the thing is there    -> run the test
    ABSENT      the probe answered and it is not there       -> skip (legitimate)
    UNCHECKABLE the probe never answered                     -> NOT CHECKED

ABSENT still skips, exactly as before — that is the whole point of these guards
and this module does not weaken it. UNCHECKABLE is the new tier: by default it
also skips (so no run that is green today turns red), but it says so in
different words, and under VIBEIC_REQUIRE_EDA_VERIFICATION it FAILS, so a run
that means to prove real EDA behaviour cannot be silently satisfied by a
daemon that was too busy to reply.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import NamedTuple

# A local `docker image inspect` is metadata-only and answers in milliseconds.
# The old 30s budget was not generous, it was a race the probe loses whenever
# the daemon is serialising other agents' work. This bound exists to outlast
# contention, NOT to wait on a network pull -- nothing here reaches a registry.
PROBE_TIMEOUT_S = 120

# Set by an operator who wants "the EDA container really was exercised" to be a
# property of a green run. With it set, UNCHECKABLE stops being tolerable.
REQUIRE_ENV = "VIBEIC_REQUIRE_EDA_VERIFICATION"

PRESENT = "present"
ABSENT = "absent"
UNCHECKABLE = "uncheckable"


class Probe(NamedTuple):
    """The verdict, the words to explain it, and what the probe printed."""

    state: str
    detail: str
    out: str = ""

    @property
    def ok(self) -> bool:
        return self.state == PRESENT


def _run(argv, timeout: int) -> Probe:
    """Run a probe command ONCE, mapping HOW it ended onto the three outcomes."""
    if not shutil.which("docker"):
        # A genuinely absent tool. The probe answered: there is no docker here.
        return Probe(ABSENT, "docker is not installed on this host")
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return Probe(
            UNCHECKABLE,
            f"docker did not answer within {timeout}s "
            f"({' '.join(argv)}) — the probe was not able to determine "
            f"whether the image/container exists",
        )
    except OSError as exc:
        return Probe(UNCHECKABLE, f"could not execute the probe: {exc}")
    out = (r.stdout or "").strip()
    if r.returncode == 0:
        return Probe(PRESENT, "", out)
    # A clean non-zero exit IS an answer: docker looked and did not find it.
    err = (r.stderr or "").strip()
    return Probe(ABSENT, err.splitlines()[-1] if err else f"rc={r.returncode}", out)


def image_available(ref: str, timeout: int = PROBE_TIMEOUT_S) -> Probe:
    """Is this image present in the LOCAL store? No registry access."""
    return _run(["docker", "image", "inspect", ref], timeout)


def container_running(name: str, timeout: int = PROBE_TIMEOUT_S) -> Probe:
    """Is a CONTAINER of this name up?

    `--type=container` matters: a bare `docker inspect <name>` also resolves an
    IMAGE of that name, so on any host with the image pulled the guard passes
    and the test then fails inside `docker exec` instead of skipping.
    """
    probe = _run(
        ["docker", "inspect", "--type=container", "-f", "{{.State.Running}}", name],
        timeout,
    )
    if probe.state != PRESENT:
        return probe
    # It resolved, so `.State.Running` decides: a STOPPED container inspects
    # fine and cannot be exec'd.
    if probe.out != "true":
        return Probe(ABSENT, f"container {name} exists but is not running", probe.out)
    return probe


def container_execable(name: str, timeout: int = PROBE_TIMEOUT_S) -> Probe:
    """Can we actually `docker exec` in this container?

    Stronger than `container_running`: a container can be up and still refuse
    exec. Callers that are about to exec should ask this, so the guard proves
    the same thing the test needs rather than something adjacent to it.
    """
    return _run(["docker", "exec", name, "true"], timeout)


def require(probe: Probe, what: str) -> None:
    """Skip or fail, in the caller's own words, based on WHY the thing is missing.

    Call from a test body (or a fixture). Returns normally only when the probe
    says PRESENT, so the caller can carry on unguarded.
    """
    import pytest

    if probe.ok:
        return
    if probe.state == UNCHECKABLE:
        message = (
            f"NOT CHECKED — {what}: {probe.detail}. This is NOT a pass and it "
            f"is NOT evidence that {what} is unavailable; the probe itself "
            f"could not run (vibe-ic#1283). Set {REQUIRE_ENV}=1 to make this "
            f"a failure instead."
        )
        if os.environ.get(REQUIRE_ENV):
            pytest.fail(message)
        pytest.skip(message)
    pytest.skip(f"{what} not available: {probe.detail}")
