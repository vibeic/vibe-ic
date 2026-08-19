"""One per-step metrics schema, and a diff that does not guess. vibe-ic#1080.

ORFS emits `<stage>__<domain>__<name>` from the tool that computed the number
(`flow.sh:15` passes `-metrics`), and `genMetrics.py` is glob-and-merge, so
"better or worse than last run" is one `diff`. Measured on v1.10.32:
`ls programs/ | grep -iE "metric|qor"` returned no per-step QoR aggregator and
nothing computed a run-to-run delta, so the issue's premise held.

THE TWO PROPERTIES THIS FILE EXISTS TO HOLD, both of which are the difference
between a metrics system and a new place for lies to live:

1. `collect` GLOBS AND MERGES AND DERIVES NOTHING. A collector that could
   compute a number can disagree with the program that computed it, and then
   the metric has two sources and no answer. Asserted by giving `collect` a
   directory containing a log that plainly states a number and checking that
   the number does not appear in the result.

2. `diff` NEVER GUESSES A DIRECTION. #1080 is explicitly oracle-free — it
   records what happened, it does not assert what should have. A differ that
   silently decided which way is good would be an oracle wearing a report's
   clothes. Every key whose tail is not in `DIRECTIONS` must come back
   `undeclared`, and `better`/`worse` must be absent for it.

TWO always-fires mutants are pinned here, because the first version of this
file only had one and the second one SURVIVED:

  * `direction_for` -> always "lower" (label everything better/worse). Passes
    the delta assertions, dies on `test_an_undeclared_key_is_never_called_...`.
  * `key_defect` -> always `None` (accept every key). This one used to leave
    the file 17/17 GREEN: `conformance_defects` carries an independent
    `startswith` check that caught the only key-shape test present, so the
    arity / empty-component / character-class rules inside `key_defect` were a
    ban rather than a check. The three tests marked below kill it.

A mutant that no test kills is the file telling you which of its assertions
are decoration.
"""
import json
import subprocess
import sys
from pathlib import Path

#: vibe-ic#1241. `ci_harness_timeout_ceiling_check` sets the per-call ceiling
#: at harness_bound/3 = 180/3 = 60s, so a call bounded ABOVE it is a promise
#: the harness will not keep: pytest kills the SESSION, not the test, and the
#: invocation ends with no summary line.
#:
#: This file's four calls were 120s and 3x180s. MEASURED, `--durations`: the
#: slowest test in this module is 0.11s and the whole module is 1.56s. 30s is
#: ~270x the measured worst case and half the ceiling -- lowered because the
#: old bounds were over-provisioned, NOT to dodge the rule. A test that
#: genuinely needed longer would belong outside the targeted subset instead.
_SUBPROC_S = 30

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

sys.path.insert(0, str(PROGRAMS))
import step_metrics as sm  # noqa: E402


def _run(*args):
    return subprocess.run([sys.executable, str(PROGRAMS / "step_metrics.py"),
                           *args], capture_output=True, text=True, timeout=_SUBPROC_S)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def test_a_bare_name_is_prefixed_with_step_and_domain(tmp_path):
    sm.emit(tmp_path, "14", {"instance_area": 4795.85}, domain="design")
    doc = json.loads((tmp_path / sm.METRICS_REL / "14.json").read_text())
    assert doc == {"14__design__instance_area": 4795.85}, doc


def test_step_ids_of_every_shape_normalise_stably(tmp_path):
    for raw, want in (("A3", "a3"), ("14", "14"), ("D1", "d1"),
                      ("Step 14", "step_14")):
        assert sm.normalize_step(raw) == want, raw


def test_an_already_qualified_key_is_kept_as_written(tmp_path):
    """ORFS uses four parts (`cts__timing__setup__ws`). A caller that already
    has the full key must not be forced to flatten it into three."""
    sm.emit(tmp_path, "19", {"19__timing__setup__ws": -1.39}, domain="timing")
    doc = json.loads((tmp_path / sm.METRICS_REL / "19.json").read_text())
    assert doc == {"19__timing__setup__ws": -1.39}, doc


def test_a_non_scalar_is_refused(tmp_path):
    try:
        sm.emit(tmp_path, "14", {"nested": {"a": 1}})
    except ValueError as exc:
        assert "flat by design" in str(exc), exc
    else:
        raise AssertionError("a nested value was accepted into a flat schema")


def test_a_key_that_does_not_lead_with_its_step_is_a_defect(tmp_path):
    d = tmp_path / sm.METRICS_REL
    d.mkdir(parents=True)
    (d / "14.json").write_text(json.dumps({"19__design__area": 1}))
    defects = sm.conformance_defects(tmp_path)
    assert any("does not lead with the step" in x for x in defects), defects


# The three tests below exist because of a PAIRED-GUARD result, not a hunch.
# Neutering `key_defect` to `return None` — accept every key — left the whole
# file at 17/17 green. `conformance_defects` carries its OWN `startswith`
# check, so the test above survives the mutant and the SHAPE rules inside
# `key_defect` (arity, empty component, character class) had nothing standing
# on them. Every key below LEADS WITH ITS STEP on purpose, so the independent
# startswith check cannot fire and only `key_defect` can produce the defect.
def test_a_key_with_fewer_than_three_parts_is_a_defect(tmp_path):
    """`<step>__<domain>` alone is not attributable: it names no measurement."""
    d = tmp_path / sm.METRICS_REL
    d.mkdir(parents=True)
    (d / "14.json").write_text(json.dumps({"14__design": 1}))
    defects = sm.conformance_defects(tmp_path)
    assert any("at least" in x for x in defects), defects


def test_a_key_with_an_empty_component_is_a_defect(tmp_path):
    """`14____area` splits to a hole. A hole is not a domain."""
    d = tmp_path / sm.METRICS_REL
    d.mkdir(parents=True)
    (d / "14.json").write_text(json.dumps({"14____area": 1}))
    defects = sm.conformance_defects(tmp_path)
    assert any("empty path component" in x for x in defects), defects


def test_emit_refuses_a_qualified_key_of_the_wrong_character_class(tmp_path):
    """An already-qualified key skips the prefixing path, so it is the only
    way a caller can put an arbitrary string into the schema. `emit` must
    still refuse it — otherwise the one door that bypasses key construction
    is also the one door with no lock."""
    try:
        sm.emit(tmp_path, "14", {"14__Design__area": 1})
    except ValueError as exc:
        assert "lowercase" in str(exc), exc
    else:
        raise AssertionError(
            "emit accepted an upper-case component; a schema whose case is "
            "not enforced is not greppable, which is the whole point")


def test_emit_merges_rather_than_truncating(tmp_path):
    sm.emit(tmp_path, "14", {"a": 1}, domain="design")
    sm.emit(tmp_path, "14", {"b": 2}, domain="design")
    doc = json.loads((tmp_path / sm.METRICS_REL / "14.json").read_text())
    assert doc == {"14__design__a": 1, "14__design__b": 2}, doc


# ---------------------------------------------------------------------------
# property 1 — collect derives NOTHING
# ---------------------------------------------------------------------------
def test_collect_does_not_read_logs(tmp_path):
    """A log sitting in the run, stating a number in the plainest possible
    terms, must not reach the merged metrics. `collect` has no parser and this
    is the assertion that keeps it that way."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "route.log").write_text(
        "wns = -1.39289\ndetailedroute__timing__setup__ws: -1.39289\n")
    sm.emit(tmp_path, "20", {"passed": True}, domain="flow")
    merged, prov = sm.collect(tmp_path)
    assert merged == {"20__flow__passed": True}, merged
    assert not any("1.39289" in str(v) for v in merged.values()), merged
    assert prov["step_count"] == 1


def test_collect_reports_its_own_denominator(tmp_path):
    sm.emit(tmp_path, "14", {"a": 1})
    sm.emit(tmp_path, "a3", {"b": 2})
    _merged, prov = sm.collect(tmp_path)
    assert prov["step_count"] == 2 and prov["metric_count"] == 2, prov
    assert prov["steps_represented"] == ["14", "a3"], prov


def test_an_empty_run_is_not_a_pass(tmp_path):
    """Nothing emitted means the run cannot be compared to another. Exit 2,
    never 0 — the same rule this repo applies to every other sweep."""
    assert _run("collect", str(tmp_path)).returncode == 2
    assert _run("check", str(tmp_path)).returncode == 2


def test_comparing_two_runs_that_measured_nothing_is_not_no_change(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    res = _run("diff", str(a), str(b))
    assert res.returncode == 2, res.stdout + res.stderr
    assert "nothing to compare" in (res.stdout + res.stderr)


# ---------------------------------------------------------------------------
# property 2 — diff never guesses a direction
# ---------------------------------------------------------------------------
def test_a_declared_direction_is_labelled():
    d = sm.diff({"14__drv__violation_count": 7},
                {"14__drv__violation_count": 3})
    rec = d["changed"][0]
    assert rec["direction"] == "lower" and rec["verdict"] == "better", rec
    assert rec["delta"] == -4 and d["better"] == 1 and d["worse"] == 0, d


def test_a_declared_direction_the_other_way_is_labelled_worse():
    d = sm.diff({"19__timing__setup__ws": -1.0},
                {"19__timing__setup__ws": -2.0})
    assert d["changed"][0]["verdict"] == "worse", d
    assert d["worse"] == 1, d


def test_an_undeclared_key_is_never_called_better_or_worse():
    """THE LOAD-BEARING ONE. A differ that guessed here would be asserting what
    should have happened, which #1080 explicitly excludes."""
    d = sm.diff({"14__design__instance_area": 100.0},
                {"14__design__instance_area": 90.0})
    rec = d["changed"][0]
    assert rec["direction"] == "undeclared", rec
    assert rec["verdict"] == "changed", (
        "a key with no declared direction was labelled "
        f"{rec['verdict']!r} — the differ guessed which way is good")
    assert d["better"] == 0 and d["worse"] == 0, d
    assert d["undeclared_changes"] == 1, d


def test_added_and_removed_are_reported_separately():
    d = sm.diff({"14__flow__x": 1}, {"14__flow__y": 2})
    assert d["added"] == ["14__flow__y"] and d["removed"] == ["14__flow__x"], d
    assert d["changed"] == [], d


def test_a_bool_is_not_arithmetic():
    """`True - False == 1` in Python. A bool flip must not report a delta as
    though it were a measurement that moved."""
    d = sm.diff({"11__coverage__passed": True},
                {"11__coverage__passed": False})
    assert "delta" not in d["changed"][0], d["changed"][0]


# ---------------------------------------------------------------------------
# the wired gate — emitted by the program that COMPUTED the number
# ---------------------------------------------------------------------------
def test_the_wired_gate_emits_its_own_metric(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run([sys.executable,
                    str(PROGRAMS / "coverage_metric_check.py"), str(proj)],
                   capture_output=True, text=True, timeout=_SUBPROC_S)
    merged, prov = sm.collect(proj)
    assert prov["step_count"] == 1, (prov, merged)
    assert "11__coverage__passed" in merged, merged
    assert not sm.conformance_defects(proj)


def test_the_metrics_sink_cannot_change_the_gate_s_verdict(tmp_path, monkeypatch):
    """Bookkeeping must not decide a coverage verdict. With the sink guaranteed
    to raise, the gate's rc has to be what it was without it."""
    proj = tmp_path / "proj"
    proj.mkdir()
    a = subprocess.run([sys.executable,
                        str(PROGRAMS / "coverage_metric_check.py"), str(proj)],
                       capture_output=True, text=True, timeout=_SUBPROC_S)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "step_metrics.py").write_text("raise RuntimeError('sink down')\n")
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(broken)
    b = subprocess.run([sys.executable,
                        str(PROGRAMS / "coverage_metric_check.py"), str(proj)],
                       capture_output=True, text=True, timeout=_SUBPROC_S, env=env)
    assert a.returncode == b.returncode, (a.returncode, b.returncode)


# ---------------------------------------------------------------------------
# reconcile — W5. The prose parser is a WITNESS, never a preference.
#
# The rule these pin: there is no code path that returns a value after a
# disagreement. `authoritative` raises, and that is the only exit it has for
# `disagree` — a flag or a "prefer" argument would put the silent tie-break
# straight back, which is the whole defect W5 exists to close.
#
# The METRIC_ONLY / PROSE_ONLY asymmetry is the substance and is pinned in both
# directions: a blind parser beside a live tool is FINE (it is what a wording
# change looks like), and a live parser beside a silent tool is UNCORROBORATED
# (it is where 61 of 62 gate-carrying steps still are). Collapsing either into
# "agree" is how a summary comes to overstate what was checked.
# ---------------------------------------------------------------------------
def test_two_sources_that_match_agree():
    r = sm.reconcile("k", 12, 12)
    assert r["verdict"] == sm.AGREE and r["is_failure"] is False


def test_two_sources_that_differ_are_a_failure():
    r = sm.reconcile("k", 12, 0)
    assert r["verdict"] == sm.DISAGREE and r["is_failure"] is True
    assert "neither may be preferred silently" in r["reason"]


def test_a_disagreement_has_no_value_to_return():
    try:
        sm.authoritative(sm.reconcile("k", 12, 0))
    except ValueError as exc:
        assert "step_metrics.authoritative" in str(exc)
    else:
        raise AssertionError("a disagreement silently produced a number")


def test_a_blind_parser_beside_a_live_tool_is_not_a_failure():
    """What a tool's WORDING change looks like. The measurement is intact."""
    r = sm.reconcile("k", 12, None)
    assert r["verdict"] == sm.METRIC_ONLY and r["is_failure"] is False
    assert sm.authoritative(r) == 12


def test_a_live_parser_beside_a_silent_tool_is_uncorroborated_not_agreed():
    r = sm.reconcile("k", None, 12)
    assert r["verdict"] == sm.PROSE_ONLY and r["is_failure"] is False
    assert "UNCORROBORATED" in r["reason"]
    assert sm.authoritative(r) == 12


def test_neither_side_speaking_is_not_checked_and_not_a_zero():
    r = sm.reconcile("k", None, None)
    assert r["verdict"] == sm.NEITHER
    assert "not a zero" in r["reason"]
    assert sm.authoritative(r) is None


def test_a_boolean_is_not_the_number_one():
    """`True == 1` in Python, so a pass/fail flag would compare equal to a
    violation count of one and a real contradiction would read as agreement."""
    r = sm.reconcile("k", True, 1)
    assert r["verdict"] == sm.DISAGREE, r


def test_tolerance_applies_only_between_two_numbers():
    assert sm.reconcile("k", 1.0, 1.05, tolerance=0.1)["verdict"] == sm.AGREE
    assert sm.reconcile("k", 1.0, 1.5, tolerance=0.1)["verdict"] == sm.DISAGREE
    # strings compare exactly; a tolerance cannot make two names equal
    assert sm.reconcile("k", "a", "b", tolerance=99)["verdict"] == sm.DISAGREE


def test_the_rollup_publishes_uncorroborated_on_its_own():
    """A summary that folded PROSE_ONLY into `agree` would claim a corroboration
    that never happened — the single most misreadable number in the report."""
    rep = sm.reconcile_report([
        sm.reconcile("a", 1, 1),
        sm.reconcile("b", None, 3),
        sm.reconcile("c", 4, None),
        sm.reconcile("d", None, None),
    ])
    assert rep["corroborated"] == 1
    assert rep["uncorroborated"] == 1
    assert rep["metric_only"] == 1
    assert rep["not_checked"] == 1
    assert rep["passed"] is True and rep["failures"] == []


def test_the_rollup_fails_when_any_pair_disagrees():
    rep = sm.reconcile_report([sm.reconcile("a", 1, 1), sm.reconcile("b", 2, 9)])
    assert rep["passed"] is False and len(rep["failures"]) == 1
