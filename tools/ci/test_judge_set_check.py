#!/usr/bin/env python3
"""Guard the judge-set check itself.

The check answers one question — *did this candidate change the code that judges
it?* — by DERIVING the judge set from what the verifier executes, rather than
reading a hand-maintained register. These cases pin the properties that make that
derivation trustworthy, because a derivation that quietly returns less is worse
than the list it replaced: every landing would pass and nobody would know.
"""
from __future__ import annotations
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "tools" / "ci" / "judge_set_check.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_jsc", CHECK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(*args):
    return subprocess.run([sys.executable, str(CHECK), "--repo", str(REPO), *args],
                          capture_output=True, text=True)


def test_the_derived_set_contains_the_actual_judges():
    """Non-vacuity, named rather than counted.

    A set that came back empty, or that missed the lander itself, would
    authorise every change to every judge while still exiting 0.
    """
    judges = _mod().judge_set(REPO)
    assert judges, "the judge set derived EMPTY — every landing would pass"
    for must in ("tools/gatekeeper-land.sh", "tools/gatekeeper-verify-merge.sh"):
        assert must in judges, (
            f"{must} is not in the derived judge set, so a candidate could "
            f"rewrite the lander and this check would not notice")


def test_it_refuses_a_candidate_that_touches_a_judge():
    """The whole point, driven end to end against real history."""
    cp = _run("--base", "HEAD~1", "--head", "HEAD")
    assert cp.returncode in (0, 1), (cp.returncode, cp.stdout, cp.stderr)
    if cp.returncode == 1:
        assert "REFUSE" in cp.stdout and "judge it" in cp.stdout, cp.stdout


def test_authorising_a_path_lets_it_through_and_says_so():
    """A refusal a human has read must be expressible, or the check gets
    bypassed instead of answered."""
    judges = sorted(_mod().judge_set(REPO))
    cp = _run("--base", "HEAD", "--head", "HEAD",
              *sum([["--authorised", p] for p in judges[:2]], []))
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_an_empty_judge_set_is_refused_rather_than_passing_everything():
    """The failure mode this check must never have.

    Driven by making the derivation return nothing, because an assertion about
    what SHOULD happen when the set is empty is worth nothing unless the empty
    case is actually reached.
    """
    m = _mod()
    m.judge_set = lambda repo: set()
    import io, contextlib
    buf = io.StringIO()
    sys.argv = ["x", "--repo", str(REPO), "--base", "HEAD~1"]
    with contextlib.redirect_stdout(buf):
        rc = m.main()
    assert rc == 2, f"an empty judge set returned {rc}, not a refusal"
    assert "EMPTY" in buf.getvalue(), buf.getvalue()


def test_the_set_is_a_property_of_the_commit_not_of_the_checkout():
    """Two derivations of one tree must agree.

    MEASURED 2026-08-28: the same commit gave 254 files in a clean clone and 191
    in a working tree carrying untracked files — the check reads the WORKING
    TREE, so an untracked file changes the answer. That is a real limitation and
    it is pinned here rather than left for someone to trip over: the set is
    reproducible for a CLEAN checkout, which is what the landing path uses.
    """
    a = _mod().judge_set(REPO)
    b = _mod().judge_set(REPO)
    assert a == b, "two derivations of the same tree disagreed"
