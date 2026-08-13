"""One per-step metrics schema, and "better or worse than last time". vibe-ic#1080.

OpenROAD-flow-scripts answers "is this run better or worse than the last one"
with one `diff`, because every stage emits into one flat namespace through the
same wrapper (`flow/scripts/flow.sh:15`, `utl::set_metrics_stage` at the head of
each stage script). We had 129 gate invocations already writing
`--json reports/.../x.json`, and no schema, no aggregator and no differ over any
of them.

WHAT THESE TESTS HOLD, beyond "it runs"
=======================================
  * the harvest reads the artefact THE TOOL WROTE and REFUSES anything that
    would need a log regex — #1080's own constraint, and lie-shape #12: a regex
    over a log is a proxy for the measurement, not the measurement;
  * "no metrics" and "no regressions" are different answers, and the second is
    never printed for the first;
  * direction is DECLARED, never guessed. An unrecognised metric is reported as
    changed-with-no-declared-direction and never scored as neutral, because a
    silent neutral is how a regression hides;
  * it is ORACLE-FREE: `diff` exits 0 over a regression unless the caller opts
    in. It records what happened; it does not assert what should have happened.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "run_metrics.py"

sys.path.insert(0, str(PROGRAMS))
import run_metrics as RM  # noqa: E402


def _flow(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "flow.yaml"
    f.write_text(body)
    return f


def _run(*argv: str):
    p = subprocess.run([sys.executable, str(PROG), *argv],
                       capture_output=True, text=True, timeout=55)
    return p.returncode, p.stdout + p.stderr


_FLOW = """\
steps:
  - id: 4
    gate:
      all_of:
        - program_exit_zero: "some_check . --json reports/a.json"
  - id: 23
    gate:
      all_of:
        - advisory_program_exit_zero: "other_check . --json reports/b.json"
"""


# --------------------------------------------------------------------------
# the schema
# --------------------------------------------------------------------------
def test_the_prefix_is_the_flow_step_id_not_a_typed_name(tmp_path):
    """`<step>__<key>__…` — the prefix is fixed by the FLOW, so no gate author
    can name its own namespace and no two steps can collide."""
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "a.json").write_text(json.dumps(
        {"passed": True, "compared_points": 29,
         "summary": {"unproven_points": 2}, "findings": []}))
    res = RM.harvest(tmp_path, _flow(tmp_path, _FLOW))
    m = res["metrics"]
    assert m["4__passed"] == 1, m
    assert m["4__compared_points"] == 29, m
    assert m["4__summary__unproven_points"] == 2, m
    assert m["4__findings__count"] == 0, ("a list must contribute its LENGTH; "
                                          "its elements are evidence, not metrics")


def test_a_null_field_is_dropped_not_recorded_as_zero(tmp_path):
    """"this field was not computed" is not a measurement, and recording it as
    0 would make an absent number look like a good one."""
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "a.json").write_text(
        json.dumps({"unproven_points": None, "compared_points": 1}))
    m = RM.harvest(tmp_path, _flow(tmp_path, _FLOW))["metrics"]
    assert "4__unproven_points" not in m, m
    assert m["4__compared_points"] == 1


# --------------------------------------------------------------------------
# #1080's own constraint: emit from the tool, never re-parse a log
# --------------------------------------------------------------------------
def test_a_non_json_declared_output_is_REFUSED_not_regexed(tmp_path):
    """A regex over a log is a PROXY for the measurement rather than the
    measurement (lie-shape #12). A metric this program cannot get honestly is
    one it does not report — and it says which."""
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "a.log").write_text("wns = -1.39\n")
    flow = _flow(tmp_path, _FLOW.replace("reports/a.json", "reports/a.log"))
    res = RM.harvest(tmp_path, flow)
    assert not any(k.startswith("4__") for k in res["metrics"]), res["metrics"]
    assert any("not .json" in r for r in res["refused"]), res["refused"]


def test_an_empty_harvest_REFUSES_rather_than_reporting_a_clean_run(tmp_path):
    """"nothing was harvested" must never render as "harvested, all fine"."""
    rc, out = _run("harvest", "--project", str(tmp_path),
                   "--flow", str(_flow(tmp_path, _FLOW)))
    assert rc == 2, out
    assert "NOT CHECKED" in out, out


# --------------------------------------------------------------------------
# direction is declared, never guessed
# --------------------------------------------------------------------------
def test_direction_is_read_from_the_word_not_only_the_last_one():
    """The last word is often the UNIT. Both of these end in `points`, and on
    the first real harvest both came back direction-not-declared."""
    assert RM._polarity("13__compared_points") == 1
    assert RM._polarity("13__non_equivalent_points") == -1
    assert RM._polarity("cts__timing__setup__violation_count") == -1
    assert RM._polarity("cts__timing__setup__ws") == 1


def test_an_unrecognised_metric_is_CHANGED_never_scored_as_neutral():
    """A silent neutral is how a regression hides. This is the paired guard for
    the polarity table: if it ever returned a default direction instead of 0,
    this test dies."""
    assert RM._polarity("4__some__opaque_widget") == 0
    res = RM.diff({"4__some__opaque_widget": 1}, {"4__some__opaque_widget": 9})
    row = res["rows"][0]
    assert row["verdict"] == RM.UNDECLARED, row
    assert res["worse"] == 0 and res["better"] == 0, res
    assert res["changed_undeclared"] == 1, res
    assert "direction not declared" in RM.format_diff(res)


def test_it_reports_better_worse_new_and_gone(tmp_path):
    res = RM.diff(
        {"4__compared_points": 29, "4__violation_count": 5, "4__gone_one": 1},
        {"4__compared_points": 34, "4__violation_count": 9, "4__new_one": 2})
    by = {r["metric"]: r["verdict"] for r in res["rows"]}
    assert by["4__compared_points"] == RM.UP, by
    assert by["4__violation_count"] == RM.DOWN, by
    assert by["4__gone_one"] == RM.GONE, by
    assert by["4__new_one"] == RM.NEW, by


def test_a_verdict_that_flips_is_a_QoR_change(tmp_path):
    """A bool is a number here on purpose: `passed: true -> false` is the most
    important regression a run can have, and a schema that dropped it would
    diff everything except the thing that matters."""
    res = RM.diff({"4__passed": 1}, {"4__passed": 0})
    assert res["worse"] == 1, res


# --------------------------------------------------------------------------
# it is a report, not an oracle
# --------------------------------------------------------------------------
def test_diff_exits_0_over_a_regression_unless_the_caller_opts_in(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"metrics": {"4__violation_count": 1}}))
    b.write_text(json.dumps({"metrics": {"4__violation_count": 9}}))
    rc, out = _run("diff", str(a), str(b))
    assert rc == 0, ("this tool records what happened; asserting what should "
                     f"have happened is every other gate's job:\n{out}")
    assert "WORSE" in out, out
    rc2, _ = _run("diff", str(a), str(b), "--fail-on-regression")
    assert rc2 == 1, "the opt-in did not fire"


def test_two_runs_sharing_no_metric_REFUSE_rather_than_report_no_regressions(
        tmp_path):
    """"0 worse" over 0 compared metrics is not a result."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"metrics": {"4__x": 1}}))
    b.write_text(json.dumps({"metrics": {"23__y": 1}}))
    rc, out = _run("diff", str(a), str(b), "--fail-on-regression")
    assert rc == 2, out
    assert "NOT CHECKED" in out, out
    assert "NOT 'no regressions'" in out, out


def test_the_summary_always_states_its_denominator(tmp_path):
    res = RM.diff({"4__x": 1}, {"4__x": 1})
    assert "compared 1 metric(s)" in RM.format_diff(res)


# --------------------------------------------------------------------------
# it works on the real flow, not only on a fixture
# --------------------------------------------------------------------------
def test_the_real_flow_declares_per_step_json_outputs_to_harvest():
    """If this returns nothing the harvester is pointed at the wrong structure
    and every other test here is passing over a fixture."""
    pairs = RM.declared_outputs(RM.FLOW_YAML)
    assert len(pairs) > 50, len(pairs)
    assert all(p.endswith(".json") for _, p in pairs), \
        [p for _, p in pairs if not p.endswith(".json")][:5]
    assert len({s for s, _ in pairs}) > 10, "every output came from one step"
