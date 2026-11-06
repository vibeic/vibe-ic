#!/usr/bin/env python3
"""Is the EDA container USABLE — not "is something wearing that name running".

WHY THIS EXISTS (#2230)
=======================
Six test modules carried their own copy of this predicate, and every copy asked
the same question::

    docker inspect -f {{.State.Running}} vibeic-eda   ->  "true"

Running is not usable. `vibeic-eda` is a bare, guessable, SHARED name on a
multi-lane host, and the answer is `True` for whatever process got to the name
first — including a container running an image this repo does not pin. The
attach check one layer down then refuses, CORRECTLY (`_eda_pin`, #2076), but by
then the test is committed to a red instead of a skip.

MEASURED 2026-09-10 on 8HD-8, clean main `9c653d47f`, against a container
literally named `vibeic-eda` started 2026-09-05 on
`sha256:06537f7e…` while the pin is `sha256:89a8fd72…`:

    7 test files RED, 10 test ids, one cause.

Not one of those reds is about the tree. They are about which container held a
name on one host, and they are INVISIBLE anywhere else — the most expensive
shape of red there is, because the next lander differences against it and
attributes it to whatever landed most recently.

WHAT THIS IS NOT
================
It does not skip a failing assertion and it does not relax one. A container
running the wrong bytes is the SAME state as an absent container — the pinned
runtime is not here — and an absent container already skipped. This makes the
guard measure the fact it was always claiming to measure; the assertions behind
it are untouched, and on a host that does hold the pinned runtime every one of
them still runs.

`_eda_pin.container_matches_pin` is the repo's ONE definition of "provably the
pinned bytes", already exported for exactly this and already consulted by the
#2120 preflight. This is that predicate, in the boolean shape a `skipif` wants.

chip-AGNOSTIC: container identity only. No design, PDK, vendor or tool literal.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _eda_pin as _pin  # noqa: E402

__all__ = ["container_usable"]


def container_usable(container: str | None = None, env=None) -> bool:
    """True only when `container` PROVABLY runs the pinned image.

    Every answer short of proof is False, and they are false for different
    reasons that the caller does not need to distinguish — no docker client, no
    such container, a digest docker would not report, a digest that is not the
    pin. What a `skipif` needs to know is whether the pinned runtime is
    reachable here, and only `MATCH` says it is.

    `container=None` asks about the name the runtime itself would derive
    (`_eda_pin.default_container_name`), which is per-pin and therefore cannot
    be squatted by an older image the way the bare shared name can.
    """
    if shutil.which("docker") is None:
        return False
    name = container or _pin.default_container_name(env)
    try:
        return _running(name)
    except Exception:                                   # noqa: BLE001
        # An auditor that cannot read the machine has not proved the pin is
        # here; it says "not usable", never "usable".
        return False


_RUNNING_TIMEOUT_S = 15


def _running(name: str) -> bool:
    """Is `name` a container that is RUNNING right now?

    THE CONVERSE OF THIS MODULE'S OWN THESIS. The header above says running is
    not usable; usable is not running either, and only the first half was
    implemented. `container_matches_pin` reads the IMAGE a container was
    created from, and docker answers that for a STOPPED container just as
    readily as for a live one — so a container holding the pinned bytes and not
    running returned True, while `container_usable` promises in its first line
    that it is True only when the container "PROVABLY runs the pinned image".

    MEASURED 2026-09-10 on 8HD-8: with the pinned container stopped and its
    bytes still on the machine, the guard admitted the two live-path tests in
    test_lec_include_hub_aggregator; `docker exec` then produced empty output
    and both FAILED on an empty string — a red about a stopped container, which
    is precisely the absent-runtime state this module exists to turn into a
    skip.

    Absent, wrong bytes, and stopped are one state to a caller: the pinned
    runtime is not reachable here. They are one answer here too. Anything this
    cannot read is False, for the same reason every other answer here is.
    """
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True, text=True, timeout=_RUNNING_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip().lower() == "true"
