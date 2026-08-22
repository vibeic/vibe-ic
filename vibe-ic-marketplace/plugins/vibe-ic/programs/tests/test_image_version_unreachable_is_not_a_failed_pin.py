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

WHICH SUBCOMMAND THESE STATES BELONG TO — CHANGED BY vibe-ic#927.
    Every state above is still pinned, and still means the same thing. What
    moved is WHERE it is asked. These are all answers about a registry another
    org mutates, so they were asked by the wrong subcommand: `--check` is the
    LANDING gate, and a landing gate that returns 1 because `vibeic-eda`
    published while it ran is red for a reason nobody in this repo caused. The
    anchor moved 0.2.75 -> .81 -> .82 -> .83 in about twelve hours for exactly
    that reason.

    So the same three states are now asked by `--report-upstream`, which never
    returns 1 (a disagreement is a dated OBSERVATION, exit 0) and returns 2
    when the registry is silent — the rc-2 vocabulary this file exists to
    defend, intact. `--check` makes no registry call at all and its verdict is
    invariant under all three.

    The distinction this file was written for is UNCHANGED: "I could not look"
    and "I looked and it is clean" are still different results, still printed
    in different words, still never collapsed. See
    test_issue927_blocking_gate_ignores_mutable_registry_pointer.py for the
    property that the blocking verdict cannot move.
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


#: The subcommand that ASKS the registry. `--check` no longer does (#927), so
#: pointing this file at it would make every assertion below vacuous — the
#: unreachable arm would "pass" by never having tried.
_ASK = ["--report-upstream", "--require-remote"]


def _run(env_extra=None, unreachable=False):
    """Run the registry-asking subcommand. `unreachable` severs DNS inside the
    child so the registry genuinely cannot be reached — no mock of the
    program's own logic."""
    env = dict(os.environ)
    env.pop(_ENV_KEY, None)
    env.update(env_extra or {})
    if unreachable:
        code = (
            "import sys, socket, runpy\n"
            f"sys.argv = ['sync_image_version.py'] + {_ASK!r}\n"
            "def _boom(*a, **k):\n"
            "    raise TimeoutError('simulated unreachable registry')\n"
            "socket.getaddrinfo = _boom\n"
            "socket.create_connection = _boom\n"
            f"runpy.run_path({str(_PROG)!r}, run_name='__main__')\n"
        )
        return subprocess.run([sys.executable, "-c", code], cwd=str(_REPO),
                              capture_output=True, text=True, env=env)
    return subprocess.run(
        [sys.executable, str(_PROG), *_ASK],
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


def test_a_registry_that_ANSWERS_and_disagrees_is_STILL_DISTINGUISHED():
    """THE PAIRED HALF, and the one that keeps this from being a loophole.

    A registry that answered and disagreed must never be reported in the same
    words as one that could not be reached. That was the whole complaint, and
    it still holds — what changed (#927) is the EXIT CODE, not the claim.

    Exit 0 here is deliberate and is asserted, not tolerated: the disagreement
    is "the fork published something newer than our anchor", which is true,
    worth printing, and NOT a defect in this commit. Making it non-zero is how
    the landing gate became unobtainable at arbitrary minutes. What must not
    happen is silence, so the output is checked to still name the finding.
    """
    r = _run({_ENV_KEY: "9.9.9"})
    out = r.stdout + r.stderr
    assert "STALE ANCHOR" in out, out
    assert "9.9.9" in out, out
    assert "NOT CHECKED" not in out, (
        "a registry that ANSWERED is being reported as unreachable", out)
    assert r.returncode == 0, out


def test_a_healthy_tree_still_reports_cleanly():
    """Requires real network; skipped rather than guessed at when absent."""
    r = _run()
    if r.returncode == 2:
        pytest.skip("registry unreachable in this environment")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[REPORT]" in r.stdout


def test_the_hygiene_script_tolerates_this_gate_being_uncheckable():
    """The other half of the repair: rc 2 is only non-fatal if the CI script
    routes the registry-asking gate through the tolerating wrapper. Without
    this the program change alone would still red the suite.

    Found BY ITS OWN LABEL rather than by a hardcoded string, so renaming the
    gate cannot silently turn this into a test of nothing — a lookup that
    misses would otherwise assert an empty list is fine.
    """
    script = (_REPO / "tools" / "ci" / "repo_hygiene_gates.sh").read_text()
    line = [ln for ln in script.splitlines()
            if "sync_image_version.py" in ln and "--report-upstream" in ln
            and ln.strip().startswith("run")]
    assert line, "the registry-asking gate is not wired into the CI script"
    assert line[0].strip().startswith("run_tolerating_uncheckable"), line[0]


def test_the_version_anchor_is_readable():
    """Denominator: if VERSION cannot be read, every assertion above is
    vacuous and this test says so instead of passing quietly."""
    assert _version(), "tools/vibeic-eda/VERSION is empty"
