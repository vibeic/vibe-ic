"""Regression for vibe-ic#1446 — 46 red tests that were the scratch root, not
the tree, and a suite that neither stated nor pinned which it ran under.

現象
====
#1446 set out to count main's red tests outside the 63x9 matrix. Five counts
were published on it — ~93, 46, 39, 145, 218 — and four were retracted or
corrected by their own author. One correction names this file's subject:

    scratch INSIDE a repo   218 reds
    scratch OUTSIDE         145 reds
    only in the inside run   74      <- environment, not main

MEASURED on 3d13e2c59, same tree, same commit, same host, only the pytest
scratch root moved:

    --basetemp outside any repository     57 passed
    --basetemp inside a git repository    35 failed, 22 passed
                    (test_published_record_staleness_check.py)

plus 11 across test_issue905_ic_level_layout_contract.py and
test_issue967_empty_ic_unit_examined_nothing.py — 46 in all.

WHY THE FIX IS IN THE HARNESS AND NOT IN THE GATES
==================================================
`git -C D ls-files` cannot FAIL while any ancestor of D is a work tree: it
succeeds and answers about that checkout scoped to D, which is zero paths for a
directory nobody committed. It is tempting to read that as the gates' bug and
have them walk the disk whenever the tracked set comes back empty. That was
tried here and MEASURED: it makes the 46 green and turns
`test_issue967_empty_ic_unit_examined_nothing.py::
test_bug_an_ic_holding_only_untracked_scratch_published_nothing` RED, because
#967 pins the opposite as a deliberate property — an IC whose only entry is a
developer's local scratch "published NOTHING, so it is a skip, not a pass".

So the gates are right, the tests they fail are right, and what was wrong is
that the RUN's verdict depended on an environment variable the harness neither
set nor recorded. This file guards the declaration and the refusal.

BOTH DIRECTIONS
===============
A guard that refuses is trivially "fixed" by refusing more, and a suite that
cannot run is not a suite that passes. So every refusal case here is paired
with a case that must still RUN:

    refuses a scratch root inside a work tree
    but runs, unchanged, on a root outside one
    and runs when the operator has explicitly allowed it
    and says so in the header in BOTH states, since a declaration that only
      appears in the bad case cannot be checked from a good run

chip-AGNOSTIC: harness/environment structure only.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parent.parent.parent
_PROGRAMS = _PLUGIN / "programs"
sys.path.insert(0, str(_PROGRAMS))
import scratch_root_guard as G  # noqa: E402

#: Well under the 180s session bound the landing harness runs at: an inner
#: bound longer than the session's kills the SESSION rather than one test.
_TIMEOUT = 60


# ── fixtures ───────────────────────────────────────────────────────────────

def _repo(d: Path) -> Path:
    """A repository at `d`. Its own `.git` terminates git's upward walk, so
    these cases hold whether or not the host's tmp is inside one."""
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True, timeout=_TIMEOUT)
    return d


def _inner_suite(d: Path) -> Path:
    """A one-test pytest tree that loads the guard exactly as the plugin does.

    Driven as a SUBPROCESS: the guard acts in `pytest_configure`, so the only
    honest way to assert what a session does is to run one.
    """
    d.mkdir(parents=True, exist_ok=True)
    (d / "conftest.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(_PROGRAMS)!r})\n"
        'pytest_plugins = ("scratch_root_guard",)\n', encoding="utf-8")
    (d / "test_one.py").write_text(
        "def test_one():\n    assert True\n", encoding="utf-8")
    return d


def _run_inner(suite: Path, basetemp: Path, *extra: str):
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:randomly",
         "-p", "no:cacheprovider", "--basetemp", str(basetemp),
         *extra, str(suite)],
        capture_output=True, text=True, timeout=_TIMEOUT,
        cwd=str(suite), env={**_clean_env(), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    return r.returncode, r.stdout + r.stderr


def _clean_env() -> dict:
    import os
    env = dict(os.environ)
    env.pop(G._ENV_ALLOW, None)
    return env


# ── A. the refusal ─────────────────────────────────────────────────────────

def test_a_scratch_root_inside_a_work_tree_is_refused(tmp_path):
    """The 46-red arm. One named error, not dozens of failures whose cause is
    nowhere in their output."""
    amb = _repo(tmp_path / "ambient")
    suite = _inner_suite(tmp_path / "suite")

    rc, out = _run_inner(suite, amb / "bt")
    assert rc != 0, out
    assert "scratch_root_guard" in out, out
    assert "INSIDE a git work tree" in out, out


def test_the_refusal_names_the_root_and_the_work_tree(tmp_path):
    """A refusal a reader cannot act on is a wall. It must say WHICH directory
    and WHICH checkout, because the operator's next move is to move one."""
    amb = _repo(tmp_path / "ambient2")
    suite = _inner_suite(tmp_path / "suite2")
    bt = amb / "bt"

    _rc, out = _run_inner(suite, bt)
    assert str(bt) in out, out
    assert str(amb.resolve()) in out, out
    assert "TMPDIR" in out, out


def test_the_refusal_happens_before_any_test_reports_a_verdict(tmp_path):
    """The whole point: a run that cannot be trusted must not LOOK like a
    measurement of the tree. No passed/failed tally may be printed."""
    amb = _repo(tmp_path / "ambient3")
    suite = _inner_suite(tmp_path / "suite3")

    _rc, out = _run_inner(suite, amb / "bt")
    assert " passed" not in out, out
    assert " failed" not in out, out


# ── B. the paired guard: it must still let an honest run happen ────────────

def test_a_scratch_root_outside_any_work_tree_runs_normally(tmp_path):
    """Refusing more is not a fix. The ordinary case must be untouched."""
    suite = _inner_suite(tmp_path / "suite4")
    bt = tmp_path / "plain_bt"

    rc, out = _run_inner(suite, bt)
    assert rc == 0, out
    assert "1 passed" in out, out


def test_an_explicit_allowance_runs_and_discloses_itself(tmp_path):
    """For a container whose only writable tmp is inside the checkout. The
    escape hatch exists so the guard cannot become a blocker — and it prints
    that it was used, so a count taken from that run carries its own caveat."""
    amb = _repo(tmp_path / "ambient5")
    suite = _inner_suite(tmp_path / "suite5")

    rc, out = _run_inner(suite, amb / "bt", "--allow-scratch-root-in-repo")
    assert rc == 0, out
    assert "1 passed" in out, out
    assert "not trustworthy" in out, out


# ── C. the declaration, which must be checkable from a GOOD run ────────────

def test_every_run_states_the_scratch_root_it_used(tmp_path):
    """A declaration that only appears when something is wrong cannot be
    verified by the runs that matter. #1446's five irreconcilable counts are
    what a suite that does not state its own conditions looks like."""
    suite = _inner_suite(tmp_path / "suite6")
    bt = tmp_path / "plain_bt6"

    _rc, out = _run_inner(suite, bt)
    assert "scratch_root_guard" in out, out
    assert str(bt) in out, out


def test_the_declaration_survives_dash_q(tmp_path):
    """`-q` SUPPRESSES `pytest_report_header`, and `-q` is the shape the
    landing harness runs. Measured before this test existed:

        pytest -q ... | grep -c scratch_root_guard   ->  0

    A guard about runs that do not state their own conditions, shipped so that
    it stated nothing in the only invocation shape that matters, would be this
    issue's defect wearing this issue's fix.
    """
    suite = _inner_suite(tmp_path / "suite7")
    bt = tmp_path / "plain_bt7"

    rc, out = _run_inner(suite, bt, "-q")
    assert rc == 0, out
    assert "scratch_root_guard" in out, out
    assert str(bt) in out, out


def test_the_declaration_distinguishes_could_not_look_from_looked(tmp_path):
    """"git could not be asked" must not be reported as a clean "outside" —
    the distinction the rest of this repo keeps, kept here too."""
    src = (_PROGRAMS / "scratch_root_guard.py").read_text(encoding="utf-8")
    assert "or git could not be asked" in src, \
        "the outside-branch wording no longer discloses the unaskable case"


# ── D. the mechanism itself, pinned so nobody re-derives it ────────────────

def test_git_ls_files_succeeds_with_zero_inside_an_enclosing_repository(
        tmp_path):
    """The fact underneath all 46: rc==0 does NOT mean "this root is a
    published tree"."""
    amb = _repo(tmp_path / "ambient7")
    d = amb / "nobody" / "committed" / "this"
    d.mkdir(parents=True)
    (d / "a.json").write_text("{}", encoding="utf-8")

    r = subprocess.run(["git", "-C", str(d), "ls-files", "-z"],
                       capture_output=True, timeout=_TIMEOUT)
    assert r.returncode == 0, r.returncode
    assert [p for p in r.stdout.split(b"\0") if p] == [], r.stdout


def test_the_guard_classifies_a_root_it_was_pointed_at(tmp_path):
    """`enclosing_work_tree` is the whole decision; assert it directly so a
    refactor of the hook wiring cannot quietly invert it."""
    amb = _repo(tmp_path / "ambient8")
    inside = amb / "deep" / "down"
    inside.mkdir(parents=True)

    assert G.enclosing_work_tree(inside) == str(amb.resolve())
    assert G.enclosing_work_tree(tmp_path / "does_not_exist_yet") in (
        None, G.enclosing_work_tree(tmp_path))
