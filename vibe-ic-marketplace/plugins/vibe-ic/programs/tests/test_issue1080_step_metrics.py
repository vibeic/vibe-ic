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
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

sys.path.insert(0, str(PROGRAMS))
import step_metrics as sm  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _run(*args):
    return _pr.run([sys.executable, str(PROGRAMS / "step_metrics.py"),
                           *args], capture_output=True, text=True)


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
    _pr.run([sys.executable,
                    str(PROGRAMS / "coverage_metric_check.py"), str(proj)],
                   capture_output=True, text=True)
    merged, prov = sm.collect(proj)
    assert prov["step_count"] == 1, (prov, merged)
    assert "11__coverage__passed" in merged, merged
    assert not sm.conformance_defects(proj)


def test_the_metrics_sink_cannot_change_the_gate_s_verdict(tmp_path, monkeypatch):
    """Bookkeeping must not decide a coverage verdict. With the sink guaranteed
    to raise, the gate's rc has to be what it was without it."""
    proj = tmp_path / "proj"
    proj.mkdir()
    a = _pr.run([sys.executable,
                        str(PROGRAMS / "coverage_metric_check.py"), str(proj)],
                       capture_output=True, text=True)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "step_metrics.py").write_text("raise RuntimeError('sink down')\n")
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(broken)
    b = _pr.run([sys.executable,
                        str(PROGRAMS / "coverage_metric_check.py"), str(proj)],
                       capture_output=True, text=True, env=env)
    assert a.returncode == b.returncode, (a.returncode, b.returncode)
