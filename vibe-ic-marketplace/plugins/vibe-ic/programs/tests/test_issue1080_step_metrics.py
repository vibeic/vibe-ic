"""vibe-ic#1080 — "is this run better or worse than the last one" as a command.

ORFS answers it with one `diff` because every stage emits the same flat schema
and the aggregator is glob-and-merge (`flow/util/genMetrics.py:251-301`). We
could not: measured on `a38902d1`, no per-step QoR aggregator and no run-to-run
diff existed.

WHAT THESE PIN
==============
The schema is ENFORCED, not suggested — `emit` refuses a key that breaks
`<stage>__<domain>__<name>` or that is not prefixed by its own stage. A schema
nobody enforces is a suggestion, and a suggestion is what produced 63 steps each
choosing their own shape.

The diff stays ORACLE-FREE. "Better or worse" needs to know whether lower is
better, which is a FACT ABOUT THE METRIC (violation counts go down, coverage
goes up), not a judgement about the run. The producer declares it; where it does
not, the diff reports the change and says the direction is unknown rather than
guessing. `test_an_undeclared_direction_is_not_guessed` is the one that keeps
this honest.

The fixtures use REAL ORFS keys (`cts__timing__setup__ws`,
`cts__timing__drv__setup_violation_count`, `cts__flow__warnings__count:ORD-0012`)
so a schema that drifted from the convention we adopted would fail here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

import step_metrics as M  # noqa: E402

GATE = _PROGRAMS / "step_metrics.py"

WS = "cts__timing__setup__ws"
VIOL = "cts__timing__drv__setup_violation_count"
WARN = "cts__flow__warnings__count:ORD-0012"


def _run(*a):
    p = subprocess.run([sys.executable, str(GATE), *map(str, a)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# ── the schema is enforced ──────────────────────────────────────────────────

def test_a_conforming_key_is_recorded(tmp_path):
    rc, out = _run("emit", tmp_path, "--stage", "cts", "--key", WS,
                   "--value", "-1.39", "--direction", "higher_is_better")
    assert rc == M.RC_PASS, out
    doc = json.loads(M.stage_file(tmp_path, "cts").read_text())
    assert doc["metrics"][WS]["value"] == -1.39
    assert doc["metrics"][WS]["direction"] == "higher_is_better"


def test_a_key_that_breaks_the_convention_is_refused(tmp_path):
    rc, out = _run("emit", tmp_path, "--stage", "cts", "--key", "badkey",
                   "--value", "1")
    assert rc == M.RC_FAIL, out
    assert "does not match" in out, out


def test_a_key_not_prefixed_by_its_stage_is_refused(tmp_path):
    """The fixed prefix is what makes the merged file greppable per stage."""
    rc, out = _run("emit", tmp_path, "--stage", "cts", "--key",
                   "drt__timing__setup__ws", "--value", "1")
    assert rc == M.RC_FAIL, out
    assert "not prefixed by its stage" in out, out


def test_there_is_no_log_regex_mode(tmp_path):
    """#1080: 'a log regex is a proxy for the measurement, not the measurement'.

    `emit` takes a value from its caller and there is deliberately no
    `--from-log`. If one is ever added this test should be deleted in the same
    commit, deliberately, rather than quietly passing.
    """
    rc, out = _run("emit", "--help")
    assert "--from-log" not in out, (
        "a log-scraping mode appeared; lie-shape #12 is back:\n" + out)


# ── glob-and-merge, and it stays dumb ───────────────────────────────────────

def test_collect_merges_every_stage_file(tmp_path):
    _run("emit", tmp_path, "--stage", "cts", "--key", WS, "--value", "-1.0")
    _run("emit", tmp_path, "--stage", "drt", "--key", "drt__route__drc__count",
         "--value", "3", "--direction", "lower_is_better")
    rc, out = _run("collect", tmp_path)
    assert rc == M.RC_PASS, out
    merged, sources = M.collect(tmp_path)
    assert set(merged) == {WS, "drt__route__drc__count"}, merged
    assert sorted(sources) == ["cts.json", "drt.json"], sources


def test_collect_over_nothing_is_vacuous(tmp_path):
    rc, out = _run("collect", tmp_path)
    assert rc == M.RC_VACUOUS, out
    assert "NOT a run with good numbers" in out, out


# ── the diff answers the question the issue asks ────────────────────────────

@pytest.fixture
def pair(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    for run, ws, viol in ((a, -1.39, 67), (b, -0.5, 90)):
        _run("emit", run, "--stage", "cts", "--key", WS, "--value", str(ws),
             "--direction", "higher_is_better")
        _run("emit", run, "--stage", "cts", "--key", VIOL, "--value", str(viol),
             "--direction", "lower_is_better")
    return a, b


def test_worse_is_reported_as_regressed(pair):
    a, b = pair
    rc, out = _run("diff", a, b)
    assert rc == M.RC_PASS, out
    rep = M.diff(M.collect(a)[0], M.collect(b)[0])
    assert [r["key"] for r in rep["regressed"]] == [VIOL], rep
    assert [r["key"] for r in rep["improved"]] == [WS], rep


def test_direction_decides_the_verdict_not_the_sign(pair):
    """67 -> 90 is a RISE and a regression; -1.39 -> -0.5 is also a rise and an
    improvement. Only the declared direction tells them apart."""
    a, b = pair
    rep = M.diff(M.collect(a)[0], M.collect(b)[0])
    assert all(r["after"] > r["before"] for r in rep["regressed"] + rep["improved"]), rep
    assert rep["regressed"] and rep["improved"], rep


def test_an_undeclared_direction_is_not_guessed(tmp_path):
    """The oracle-free line. A metric whose polarity nobody stated is reported
    as CHANGED, never as better or worse."""
    a, b = tmp_path / "A", tmp_path / "B"
    _run("emit", a, "--stage", "cts", "--key", WARN, "--value", "1")
    _run("emit", b, "--stage", "cts", "--key", WARN, "--value", "5")
    rep = M.diff(M.collect(a)[0], M.collect(b)[0])
    assert not rep["improved"] and not rep["regressed"], rep
    assert [r["key"] for r in rep["changed_unknown"]] == [WARN], rep


def test_new_and_gone_metrics_are_named(pair):
    a, b = pair
    _run("emit", b, "--stage", "cts", "--key", WARN, "--value", "1")
    rep = M.diff(M.collect(a)[0], M.collect(b)[0])
    assert rep["new"] == [WARN], rep
    assert rep["gone"] == [], rep


def test_a_diff_against_a_run_with_no_metrics_is_vacuous(tmp_path, pair):
    a, _b = pair
    rc, out = _run("diff", a, tmp_path / "empty")
    assert rc == M.RC_VACUOUS, out
    assert "NOT a report of no change" in out, out


# ── paired guard ────────────────────────────────────────────────────────────

def test_a_diff_that_always_says_nothing_changed_is_killed(pair):
    """If `diff` were replaced by one that reports no movement, every tier
    above must die rather than read as a stable run."""
    a, b = pair
    real = M.diff(M.collect(a)[0], M.collect(b)[0])
    assert real["regressed"], real

    blind = {"improved": [], "regressed": [], "changed_unknown": [],
             "new": [], "gone": []}
    assert blind != real, (
        "a diff that reports nothing is indistinguishable from a run that did "
        "not move, so these tests would not notice the comparison being lost")
