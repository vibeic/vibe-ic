#!/usr/bin/env python3
"""vibe-ic#1412 — LOCK 2 scored a pytest EXIT STATUS and called it the cell.

THE DEFECT
==========
`matrix_mutation_ledger._run_cell` ran one pytest cell in a subprocess and
returned `proc.returncode`. A pytest process exits non-zero for the CELL, or for
anything the SESSION decided, and the two are not the same claim.

The measured instance: the plugin's own `conftest.py` loads `suite_write_guard`,
which discovers its subject with `git rev-parse --show-toplevel` from its own
file. LOCK 2's PLUGIN_TREE replays run the cell inside a `cp -al` mirror built
under `tempfile.mkdtemp()`, so that resolves to whatever repository happens to
enclose `TMPDIR`. The mirror's own `__pycache__` is UNTRACKED in that repository
whenever its ignore rules are not this one's, so the guard sets
`session.exitstatus = 1` — while the cell itself reports `1 passed`.

Measured on clean main `3d13e2c59`, same worktree, ONLY `TMPDIR` varying:

    TMPDIR=/tmp                       96 passed
    TMPDIR=<a dir inside a git repo>   3 failed, 93 passed

      test_lock2_the_mutation_really_reddens_its_witness[D1-ORPHAN-UMBRELLA-GATE]
      test_lock2_the_mutation_really_reddens_its_witness[D6-UMBRELLA-ALWAYS-SKIPS]
      test_the_replay_actually_ran_and_is_not_starved

Both of those entries carry `witness="P0"`, and both replays reported

    ALREADY_RED ... baseline rc=1, mutant rc=1

with `1 passed` in the baseline arm's own output. The cell was GREEN. The ledger
said the recorded proof no longer held.

BOTH DIRECTIONS WERE BROKEN, AND THE OTHER ONE IS WORSE
=======================================================
The direction #1412 measured turns a proof into a false alarm. The direction
nobody measured turns a mutation that moved NOTHING into a recorded REDDENED:
`proved` needs `mutant_rc != 0` and the declared `red_signal` somewhere in the
output, and a session reddened by a plugin supplies the first for free. A ledger
that can be satisfied that way is a ledger of teeth nobody has checked.

WHAT THIS FILE PINS
===================
`_run_cell` returns the colour pytest itself recorded FOR THE CELL, read from
its `--junit-xml` report, plus a REASON when the report cannot be read.

  * :func:`test_a_session_reddened_by_a_plugin_leaves_the_green_cell_green` —
    the #1412 direction, with the raw process rc asserted in the same test so
    the arms are visibly different rather than asserted to be.
  * :func:`test_a_session_reddened_by_a_plugin_cannot_manufacture_a_red` — the
    teeth. A green cell under a red session must not be readable as red.
  * :func:`test_a_genuinely_failing_cell_is_still_read_as_red` — the control
    this whole change must not buy its green with: when the cell really fails,
    the colour is still red.
  * :func:`test_an_unreadable_report_is_a_REASON_not_a_colour` — a run that
    selected nothing has not told us the cell is green OR red, and must say so.
  * :func:`test_a_genuinely_red_baseline_is_still_ALREADY_RED` — the verdict
    #1412 was WRONGLY receiving must still be reachable when it is right.

Every session below is a REAL pytest process running the REAL `_run_cell`, in a
throwaway tree outside this repository. chip-AGNOSTIC: no design, PDK, vendor or
IC input anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import matrix_mutation_ledger as L

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: Bound for one synthetic pytest session. These trees hold ONE trivial test and
#: measure at well under a second; 30 s is slack for a loaded host and is under
#: the 60 s ceiling `ci_harness_timeout_ceiling_check` enforces (vibe-ic#1022).
_T = 30

#: A `pytest_sessionfinish` that reddens the SESSION while every test passes —
#: the exact mechanism `suite_write_guard` uses when it decides a run wrote into
#: the tree. Reproduced rather than imported so this file pins the SHAPE, and
#: keeps pinning it if that particular guard is ever rewritten.
_REDDENING_PLUGIN = (
    "def pytest_sessionfinish(session, exitstatus):\n"
    "    session.exitstatus = 1\n")


def _tree(tmp_path: Path, body: str, *, reddening_plugin: bool) -> Path:
    """A throwaway pytest rootdir holding exactly one test file."""
    root = tmp_path / "tree"
    root.mkdir(parents=True)
    (root / "test_probe.py").write_text(body, encoding="utf-8")
    (root / "conftest.py").write_text(
        _REDDENING_PLUGIN if reddening_plugin else "", encoding="utf-8")
    return root


def _raw_pytest_rc(root: Path, nodeid: str) -> int:
    """What the OLD `_run_cell` would have scored: the process exit status."""
    p = _pr.run(
        [sys.executable, "-m", "pytest", nodeid, "-q", "-p", "no:randomly",
         "--no-header", "-rN"],
        cwd=str(root), capture_output=True, text=True, env={**_child_env()})
    return p.returncode


def _child_env() -> dict:
    """Pin what the child loads from the HOST, the way `_run_cell` does.

    Without this a broken third-party `pytest11` entry point on the landing host
    reddens a session that has nothing to do with the claim under test — the
    failure mode `test_suite_write_guard._child_env` records by name.
    """
    import os
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTEST_ADDOPTS"] = ""
    env["PYTEST_PLUGINS"] = ""
    return env


@pytest.fixture()
def cell(monkeypatch):
    """Point `cell_nodeid` at the synthetic probe instead of a matrix cell."""
    nodeid = "test_probe.py::test_probe"
    monkeypatch.setattr(L, "cell_nodeid", lambda dim, sid: nodeid)
    return nodeid


_PASSING = "def test_probe():\n    assert True\n"
_FAILING = "def test_probe():\n    assert False, 'the cell really fails'\n"


# --------------------------------------------------------------------------
# The #1412 direction — a red session must not redden a green cell.
# --------------------------------------------------------------------------

def test_a_session_reddened_by_a_plugin_leaves_the_green_cell_green(
        tmp_path, cell):
    """The reproduction, with the pre-fix answer measured in the same test.

    The `assert raw == 1` half is what makes this falsifiable: it shows the
    process DID exit non-zero, so a green here is the report being read and not
    the session happening to be quiet. Against the pre-fix `_run_cell` — which
    returned `proc.returncode` — this test cannot pass.
    """
    root = _tree(tmp_path, _PASSING, reddening_plugin=True)

    raw = _raw_pytest_rc(root, cell)
    assert raw == 1, (
        "fixture is not faithful: the session was supposed to be reddened by "
        f"the plugin, but pytest exited {raw}")

    rc, out, why = L._run_cell(1, "P0", root, None, _T)
    assert why == "", f"the report was readable, so there is no reason: {why!r}"
    assert rc == 0, (
        "a GREEN cell under a RED session was scored red — this is #1412:\n"
        f"{out}")
    assert "1 passed" in out, out


def test_a_session_reddened_by_a_plugin_cannot_manufacture_a_red(
        tmp_path, cell):
    """The worse direction: LOCK 2's `proved` must not be satisfiable by it.

    A mutant arm that moved nothing, run under a session-reddening plugin,
    supplies `mutant_rc != 0` for free — and `red_signal` matching is a substring
    search over output the plugin also writes. Scored on the CELL, the arm is
    green and `proved` is False whatever the text says.
    """
    root = _tree(tmp_path, _PASSING, reddening_plugin=True)
    rc, out, why = L._run_cell(1, "P0", root, None, _T)

    r = L.ReplayResult("PROBE", 1, "P0", True, 0, rc, True,
                       "synthetic", 0.0, "REDDENED", why, L.PLUGIN_TREE)
    assert not r.proved, (
        "a mutation that moved nothing was scored REDDENED because the SESSION "
        f"went red:\n{out}")
    assert r.verdict == "STAYED_GREEN", r.verdict


# --------------------------------------------------------------------------
# THE CONTROL. A green bought by no longer being able to see red is the
# defect this repository spent a campaign removing.
# --------------------------------------------------------------------------

def test_a_genuinely_failing_cell_is_still_read_as_red(tmp_path, cell):
    """The cell fails on its own merits — with and without a red session."""
    for reddening in (False, True):
        root = _tree(tmp_path / f"r{int(reddening)}", _FAILING,
                     reddening_plugin=reddening)
        rc, out, why = L._run_cell(1, "P0", root, None, _T)
        assert why == "", why
        assert rc == 1, (
            f"a genuinely failing cell read as GREEN (reddening={reddening}) — "
            f"the fix would have removed the gate's teeth:\n{out}")
        assert "1 failed" in out, out


def test_a_green_cell_under_a_quiet_session_is_still_green(tmp_path, cell):
    """The unremarkable case, asserted so the two above are a contrast."""
    root = _tree(tmp_path, _PASSING, reddening_plugin=False)
    rc, out, why = L._run_cell(1, "P0", root, None, _T)
    assert (rc, why) == (0, ""), (rc, why, out)


# --------------------------------------------------------------------------
# Degrading loudly — "could not look" is not a colour.
# --------------------------------------------------------------------------

def test_an_unreadable_report_is_a_REASON_not_a_colour(tmp_path, monkeypatch):
    """A nodeid that selects nothing must not be scored at all.

    Pre-fix this arrived as `rc=4`, i.e. as ALREADY_RED — an empty result
    recorded as a measurement. It is now `None` plus a named reason, and
    `ReplayResult.verdict` turns that into NOT_REPLAYABLE.
    """
    monkeypatch.setattr(L, "cell_nodeid",
                        lambda dim, sid: "test_probe.py::test_does_not_exist")
    root = _tree(tmp_path, _PASSING, reddening_plugin=False)

    rc, _out, why = L._run_cell(1, "P0", root, None, _T)
    assert rc is None, f"an unmeasured cell was given a colour: rc={rc}"
    assert why, "NOT_REPLAYABLE with no reason is the silence this forbids"

    r = L.ReplayResult("PROBE", 1, "P0", True, rc, None, False,
                       "synthetic", 0.0, "REDDENED", why, L.PLUGIN_TREE)
    assert r.verdict == "NOT_REPLAYABLE", r.verdict
    assert not r.as_recorded


@pytest.mark.parametrize("xml,expect_rc", [
    ('<testsuites><testsuite><testcase name="a"/></testsuite></testsuites>', 0),
    ('<testsuites><testsuite><testcase name="a"><failure/></testcase>'
     '</testsuite></testsuites>', 1),
    ('<testsuites><testsuite><testcase name="a"><error/></testcase>'
     '</testsuite></testsuites>', 1),
])
def test_the_report_reader_maps_each_outcome_to_the_cell_colour(
        tmp_path, xml, expect_rc):
    """Passed, failed and errored are the three outcomes that ARE a colour.

    `skipped` used to be a fourth row here, pinned at 0 on the argument quoted
    below. It is no longer a colour at all and has moved to
    `test_issue1421_a_skipped_cell_has_no_colour.py`, which pins the reason
    string too. THE ROW WAS NOT DELETED TO MAKE ANYTHING GREEN — the argument
    that justified it only ever covered one of the two ways to be wrong:

        "the exit status said the same, and `proved` still requires the MUTANT
        arm to go non-zero, so a skip cannot buy a red."

    True, and beside the point. The skip conditions in a cell test are
    properties of the CHECKOUT, not of the mutation, so they hold on BOTH arms:
    the mutant arm skips too, `replay` reads 0 and 0, and the pair is scored
    STAYED_GREEN — "the recorded proof no longer holds". A skip cannot buy a
    red; it buys the FALSE NEGATIVE, which is the direction this ledger is for
    (vibe-ic#1421).
    """
    p = tmp_path / "cell.xml"
    p.write_text(xml, encoding="utf-8")
    # The process rc is passed only so an unreadable report can quote it; a
    # readable report never consults it. 1 here proves that.
    assert L._cell_rc_from_report(p, 1) == (expect_rc, "")


@pytest.mark.parametrize("case", ["missing", "two_cases", "unparseable"])
def test_every_unreadable_shape_returns_None_and_names_itself(tmp_path, case):
    p = tmp_path / "cell.xml"
    if case == "two_cases":
        p.write_text('<testsuites><testsuite><testcase name="a"/>'
                     '<testcase name="b"/></testsuite></testsuites>',
                     encoding="utf-8")
    elif case == "unparseable":
        p.write_text("<testsuites><not closed", encoding="utf-8")
    rc, why = L._cell_rc_from_report(p, 7)
    assert rc is None, case
    assert why and "7" in why, (case, why)


# --------------------------------------------------------------------------
# ALREADY_RED must remain REACHABLE. #1412 is that it was reached wrongly,
# not that the verdict should go away.
# --------------------------------------------------------------------------

def test_a_genuinely_red_baseline_is_still_ALREADY_RED(tmp_path, cell):
    """The witness really is failing before the mutation — the experiment
    cannot run, and the ledger must still say exactly that."""
    root = _tree(tmp_path, _FAILING, reddening_plugin=False)
    base_rc, _out, why = L._run_cell(1, "P0", root, None, _T)
    assert (base_rc, why) == (1, "")

    r = L.ReplayResult("PROBE", 1, "P0", True, base_rc, 1, True,
                       "synthetic", 0.0, "REDDENED", why, L.PLUGIN_TREE)
    assert r.verdict == "ALREADY_RED"
    assert not r.proved
