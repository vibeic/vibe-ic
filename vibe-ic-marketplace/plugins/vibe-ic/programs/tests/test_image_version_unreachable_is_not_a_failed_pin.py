#!/usr/bin/env python3
"""An unreachable registry is UNVERIFIABLE, not a wrong version pin.

FOUND BY BEING BITTEN BY IT. On 2026-07-27 the `image-version pins resolve`
gate turned the hygiene suite red with

    [FAIL] latest-vs-anchor: registry unverifiable (TimeoutError)
           and --require-remote is set.

The next two runs, on an unchanged tree, passed. Nothing was wrong with any
pin — `anchor-vs-reality` had already reported OK in the same run — the
network blipped. But the gate said FAIL, in the same words it uses for a pin
that genuinely does not resolve, which is the failure #354 added
`--require-remote` to catch.

    A CHECK THAT COULD NOT RUN AND A CHECK THAT FOUND A DEFECT ARE NOT THE
    SAME RESULT.

This repo already has the vocabulary and uses it in four places:
`run_tolerating_uncheckable` (rc 2, NOT CHECKED, non-fatal),
`gate_host_independence_check`'s DIRTY_CHECKOUT, and `NOTHING_SCANNED` in the
NDA and portability scanners. This gate was the one place still collapsing the
two into rc 1.

#354's INTENT IS PRESERVED, and that is the load-bearing constraint here.
`--require-remote` exists so an unreachable registry cannot be a silent PASS.
rc 2 is not a pass: the program prints "This is NOT a pass", and the hygiene
script prints `^^ NOT CHECKED (rc 2, non-fatal)` on stderr. What it stops doing
is reporting a transient timeout as a version-pin defect.

THREE STATES, all pinned below:

    registry answered, everything agrees      -> 0
    registry answered, something disagrees    -> 1   (must NOT be downgraded)
    registry unreachable                      -> 2
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# parents: [0]=tests [1]=programs [2]=vibe-ic [3]=plugins
# [4]=vibe-ic-marketplace [5]=repo root. Off-by-one here makes every
# assertion below vacuous, so test_the_version_anchor_is_readable pins it.
_REPO = Path(__file__).resolve().parents[5]
_PROG = _REPO / "tools" / "vibeic-eda" / "sync_image_version.py"
_ENV_KEY = "VIBEIC_EDA_PUBLISHED_TAG"


def _version() -> str:
    return (_REPO / "tools" / "vibeic-eda" / "VERSION").read_text().strip()


def _run(env_extra=None, unreachable=False):
    """Run the gate. `unreachable` severs DNS inside the child so the registry
    genuinely cannot be reached — no mock of the program's own logic."""
    env = dict(os.environ)
    env.pop(_ENV_KEY, None)
    env.update(env_extra or {})
    if unreachable:
        code = (
            "import sys, socket, runpy\n"
            "sys.argv = ['sync_image_version.py', '--check', '--require-remote']\n"
            "def _boom(*a, **k):\n"
            "    raise TimeoutError('simulated unreachable registry')\n"
            "socket.getaddrinfo = _boom\n"
            "socket.create_connection = _boom\n"
            f"runpy.run_path({str(_PROG)!r}, run_name='__main__')\n"
        )
        return subprocess.run([sys.executable, "-c", code], cwd=str(_REPO),
                              capture_output=True, text=True, env=env)
    return subprocess.run(
        [sys.executable, str(_PROG), "--check", "--require-remote"],
        cwd=str(_REPO), capture_output=True, text=True, env=env)


def test_an_unreachable_registry_is_rc2_NOT_CHECKED():
    """THE LOAD-BEARING CASE — the run that turned the suite red for nothing."""
    r = _run(unreachable=True)
    out = r.stdout + r.stderr
    assert r.returncode == 2, out
    assert "NOT CHECKED" in out, out


def test_rc2_says_plainly_that_it_is_not_a_pass():
    """#354's intent, defended. Downgrading the exit code must not downgrade
    the CLAIM — a reader has to see that nothing was compared."""
    out = _run(unreachable=True).stdout + _run(unreachable=True).stderr
    assert "NOT a pass" in out, out
    assert "[PASS]" not in out, out


def test_a_registry_that_ANSWERS_and_disagrees_is_still_a_hard_fail():
    """THE PAIRED HALF, and the one that keeps this from being a loophole. A
    stale anchor is the defect #354 exists for — it must NOT be downgraded to
    NOT CHECKED just because the other axis is also non-zero."""
    r = _run({_ENV_KEY: "9.9.9"})
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "STALE ANCHOR" in out, out


def test_a_healthy_tree_still_passes():
    """Requires real network; skipped rather than guessed at when absent."""
    r = _run()
    if r.returncode == 2:
        pytest.skip("registry unreachable in this environment")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_the_hygiene_script_tolerates_this_gate_being_uncheckable():
    """The other half of the repair: rc 2 is only non-fatal if the CI script
    routes this gate through the tolerating wrapper. Without this the program
    change alone would still red the suite."""
    script = (_REPO / "tools" / "ci" / "repo_hygiene_gates.sh").read_text()
    line = [ln for ln in script.splitlines()
            if "image-version pins resolve" in ln and ln.strip().startswith("run")]
    assert line, "gate not found in the CI script"
    assert line[0].strip().startswith("run_tolerating_uncheckable"), line[0]


def test_the_version_anchor_is_readable():
    """Denominator: if VERSION cannot be read, every assertion above is
    vacuous and this test says so instead of passing quietly."""
    assert _version(), "tools/vibeic-eda/VERSION is empty"
