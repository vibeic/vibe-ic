"""The migration off log-parsing, counted rather than remembered. W5.

`step_metrics`'s docstring carried its own coverage as a hand-typed sentence
("the other 61 gate-carrying steps DO NOT emit yet"). That number was true when
it was typed and had no way of staying true. This file pins the program that
derives it instead — and, more importantly, pins the two properties that stop
the derived number from being a comfortable fiction:

* IT PUBLISHES TWO BOUNDS AND NEVER ONE. Following a gate's named program
  through its imports is necessary (`drc_report_check` is a wrapper) and it
  overcounts (`eda_report_audit` serves seven modes and one is migrated). The
  naive single number said 8 consuming steps where 2 gate paths reconcile.
  DIRECT cannot overstate, REACHABLE cannot miss, and the truth is between.
* IT REFUSES TO PASS ON NOTHING. No flow file, no steps, or no baseline is
  rc 2 NOT CHECKED. A census that reported clean because it could not see is
  the exact failure this whole work item is about.

And the ratchet is shown to FAIL, not just to pass: a floor above the measured
count reddens.
"""
import json
import subprocess
import sys
from pathlib import Path

_SUBPROC_S = 60

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
REPO = PLUGIN.parent.parent.parent

sys.path.insert(0, str(PROGRAMS))
import step_metrics_coverage_check as cc  # noqa: E402


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "step_metrics_coverage_check.py"),
         *args], capture_output=True, text=True, timeout=_SUBPROC_S, cwd=cwd)


# ---------------------------------------------------------------------------
# the census on the real flow file
# ---------------------------------------------------------------------------
def test_the_canonical_flow_is_read_and_its_gate_carrying_steps_counted():
    rep = cc.census(PLUGIN)
    assert rep["status"] == "measured", rep
    # 63 declared entries, 62 carrying a gate — the numbers `step_metrics`'s
    # docstring states in prose, here derived from the file itself.
    assert rep["declared_step_entries"] == 63, rep["declared_step_entries"]
    assert rep["gate_carrying_steps"] == 62, rep["gate_carrying_steps"]


def test_direct_never_exceeds_reachable():
    """The bounds must actually bound. If DIRECT ever exceeded REACHABLE the
    labels would be backwards and every reading of the census would be wrong."""
    rep = cc.census(PLUGIN)
    assert rep["emit_count_direct"] <= rep["emit_count_reachable"]
    assert rep["consume_count_direct"] <= rep["consume_count_reachable"]
    assert set(rep["steps_emitting_direct"]) <= set(rep["steps_emitting_reachable"])
    assert set(rep["steps_consuming_direct"]) <= set(rep["steps_consuming_reachable"])


def test_the_drc_gate_steps_are_the_ones_that_reach_the_channel():
    """Step 21 and step 31 are the two gate paths W5 migrated; both must show
    up as reaching the metrics channel, or the migration is not wired."""
    rep = cc.census(PLUGIN)
    assert "21" in rep["steps_consuming_reachable"], rep["steps_consuming_reachable"]
    assert "31" in rep["steps_consuming_reachable"], rep["steps_consuming_reachable"]


# ---------------------------------------------------------------------------
# it cannot pass on nothing
# ---------------------------------------------------------------------------
def test_no_flow_file_is_not_checked_rather_than_clean(tmp_path):
    rep = cc.census(tmp_path)
    assert rep["status"] == "not_checked", rep
    assert "could not be read" in rep["reason"], rep


def test_a_flow_file_with_no_steps_is_not_a_measurement_of_zero(tmp_path):
    (tmp_path / "flow").mkdir()
    (tmp_path / cc.FLOW_REL).write_text("version: 2\nsteps: []\n", encoding="utf-8")
    rep = cc.census(tmp_path)
    assert rep["status"] == "not_checked", rep
    assert "not a measurement of zero" in rep["reason"], rep


def test_an_absent_baseline_exits_two_not_zero(tmp_path):
    (tmp_path / "flow").mkdir(parents=True)
    (tmp_path / cc.FLOW_REL).write_text(
        "steps:\n- id: 1\n  gate:\n    program_exit_zero: nothing_here .\n",
        encoding="utf-8")
    (tmp_path / "programs").mkdir(exist_ok=True)
    r = _run(str(tmp_path))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "not a passed floor" in r.stderr, r.stderr


# ---------------------------------------------------------------------------
# the ratchet is shown to fail
# ---------------------------------------------------------------------------
def _mini_tree(tmp_path, baseline):
    plugin = tmp_path / "vibe-ic-marketplace/plugins/vibe-ic"
    (plugin / "flow").mkdir(parents=True)
    (plugin / cc.FLOW_REL).write_text(
        "steps:\n"
        "- id: 1\n  gate:\n    program_exit_zero: reader .\n",
        encoding="utf-8")
    progs = plugin / "programs"
    progs.mkdir(parents=True)
    (progs / "reader.py").write_text(
        "import step_metrics as _sm\n"
        "def go(p):\n    return _sm.collect(p)\n", encoding="utf-8")
    (progs / cc.BASELINE_NAME).write_text(json.dumps(baseline), encoding="utf-8")
    return tmp_path


def test_a_floor_above_the_measured_count_reddens(tmp_path):
    root = _mini_tree(tmp_path, {"emit_count_direct": 0,
                                 "emit_count_reachable": 0,
                                 "consume_count_direct": 9,
                                 "consume_count_reachable": 9})
    r = _run(str(root))
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "fell from 9 to 1" in r.stderr, r.stderr


def test_a_floor_at_the_measured_count_passes(tmp_path):
    root = _mini_tree(tmp_path, {"emit_count_direct": 0,
                                 "emit_count_reachable": 0,
                                 "consume_count_direct": 1,
                                 "consume_count_reachable": 1})
    r = _run(str(root))
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "held or improved" in r.stdout, r.stdout


# ---------------------------------------------------------------------------
# the shipped baseline
# ---------------------------------------------------------------------------
def test_the_shipped_tree_holds_its_own_floor():
    r = _run(str(REPO))
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)


def test_the_shipped_baseline_records_both_bounds():
    bl = json.loads((PROGRAMS / cc.BASELINE_NAME).read_text())
    for key in ("emit_count_direct", "emit_count_reachable",
                "consume_count_direct", "consume_count_reachable"):
        assert key in bl, (key, bl)
    assert "FLOOR, not a target" in bl["note"]
