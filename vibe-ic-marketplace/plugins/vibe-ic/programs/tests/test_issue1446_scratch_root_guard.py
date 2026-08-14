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

from _hostpaths import require_repo  # noqa: E402

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


def test_an_unaskable_git_does_not_crash_and_does_not_refuse(
        tmp_path, monkeypatch):
    """Degrade loudly, never silently (flow-change-acceptance §6), and never
    into a refusal.

    With git unavailable the guard cannot classify the root — and a run it
    could not classify is not one it should stop. It must also not raise: a
    harness guard that dies on a host without git takes down every suite on
    that host, which is a far larger failure than the one it prevents.

    The wording keeps "I could not look" apart from "I looked and there is
    nothing", which is the distinction the rest of this repo maintains.
    """
    amb = _repo(tmp_path / "ambient9")
    empty = tmp_path / "no_tools"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    assert G.enclosing_work_tree(amb) is None
    assert "or git could not be asked" in G.declaration(
        _FakeConfig(basetemp=amb))


# ── E. driven by the REAL repository, not by fixtures this change authored ──
#
# flow-change-acceptance §4: "A change whose tests are all fixtures authored
# alongside it CANNOT DISTINGUISH ITSELF FROM ITS OWN ABSENCE." Everything
# above builds its own `git init` tree, which proves the logic and nothing
# about the tree this guard actually runs in. These two read the checked-in
# artefacts through `_hostpaths.require_repo`.

def test_the_real_repository_is_detected_as_a_work_tree():
    """If this returns None on the real checkout the guard is inert here, and
    every claim above is about fixtures only."""
    root = require_repo(".")

    top = G.enclosing_work_tree(root)
    assert top is not None, (
        "the guard cannot see the repository it ships in — it would never "
        "fire for the operator whose TMPDIR points into their own checkout")
    assert Path(top).exists(), top


def test_the_landing_harness_does_not_point_its_scratch_into_the_tree():
    """The property this guard exists to keep, asserted against the real
    `gatekeeper-land.sh` rather than a copy of it.

    The landing sets neither `--basetemp` nor `TMPDIR`, so it inherits
    pytest's default under the platform temp root and the guard stays inert
    there. That is measured here rather than assumed, because the day someone
    adds an in-tree `--basetemp` to speed a run up is the day every landing
    starts refusing — and this test names the reason instead of leaving a
    maintainer to rediscover #1446.
    """
    land = require_repo("tools", "gatekeeper-land.sh")
    text = land.read_text(encoding="utf-8", errors="replace")

    offenders = [ln.strip() for ln in text.splitlines()
                 if ("--basetemp" in ln or "TMPDIR=" in ln)
                 and not ln.lstrip().startswith("#")]
    assert offenders == [], (
        "gatekeeper-land.sh now pins a scratch root; if it points inside the "
        "checkout every landing refuses (vibe-ic#1446): " + repr(offenders))


def test_the_landing_preflights_the_scratch_root():
    """The CLI's machine runner, asserted against the real landing script.

    `checker_execution_wiring_audit` calls a checker that only its own unit
    test executes an orphan — "a fixture the author wrote proves the logic,
    never the artefacts". The wiring is what makes this guard reach a real
    landing, so deleting it must break a test rather than pass quietly.
    """
    land = require_repo("tools", "gatekeeper-land.sh")
    text = land.read_text(encoding="utf-8", errors="replace")

    live = [ln for ln in text.splitlines()
            if "scratch_root_guard.py" in ln and not ln.lstrip().startswith("#")]
    assert live, ("gatekeeper-land.sh no longer runs scratch_root_guard as a "
                  "preflight; the landing can again spend an hour on a run its "
                  "own environment falsifies (vibe-ic#1446)")


# ── F. the CLI, both directions ────────────────────────────────────────────

def _cli(*args):
    r = subprocess.run([sys.executable, str(_PROGRAMS / "scratch_root_guard.py"),
                        *args], capture_output=True, text=True,
                       timeout=_TIMEOUT, env=_clean_env())
    return r.returncode, r.stdout + r.stderr


def test_cli_refuses_a_root_inside_a_work_tree(tmp_path):
    amb = _repo(tmp_path / "cli_amb")

    rc, out = _cli("--scratch-root", str(amb))
    assert rc == 2, out          # the repo's disclosed-refusal convention
    assert "[FAIL]" in out, out
    assert str(amb.resolve()) in out, out


def test_cli_passes_a_root_outside_any_work_tree(tmp_path):
    """The paired guard: a CLI that only ever refuses is a ban, not a check."""
    plain = tmp_path / "cli_plain"
    plain.mkdir()

    rc, out = _cli("--scratch-root", str(plain))
    assert rc == 0, out
    assert "[PASS]" in out, out


def test_cli_allowance_reports_the_refusal_and_still_exits_zero(tmp_path):
    amb = _repo(tmp_path / "cli_amb2")

    rc, out = _cli("--scratch-root", str(amb), "--allow")
    assert rc == 0, out
    assert "[FAIL]" in out, out          # still SAYS it
    assert "not\ntrustworthy" in out or "not trustworthy" in out, out


class _FakeConfig:
    """pytest passes a Config; the guard reads exactly two attributes off it."""

    def __init__(self, basetemp):
        self.option = type("O", (), {
            "basetemp": str(basetemp),
            "allow_scratch_root_in_repo": False})()


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
