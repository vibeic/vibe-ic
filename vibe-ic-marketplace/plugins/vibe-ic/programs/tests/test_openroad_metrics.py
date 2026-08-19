"""`-metrics` on every OpenROAD invocation, and what may not be guessed. W5.

THE PROPERTIES THIS FILE HOLDS
------------------------------
1. `openroad` THE COMMAND IS NOT `openroad` THE DIRECTORY. Every call site in
   this tree opens `export PATH=/foss/tools/openroad/bin:...`, and the first
   version of `with_metrics` matched that PATH COMPONENT, producing
   `export PATH=/foss/tools/openroad -metrics /w/openroad.metrics.json/bin:...`
   — a mangled PATH and a metrics path that is not a path. It was caught by
   running the wrapper on a real call-site string, not by reading it. That
   string is now a test.

2. AN UNDERIVABLE PATH IS REFUSED, NOT INVENTED. A metrics file written where
   the caller cannot predict is a metrics file nothing will ever read, which is
   indistinguishable downstream from the tool never having been asked.

3. INGEST NEVER TURNS AN ABSENT MEASUREMENT INTO A ZERO. `status: absent` and a
   file of zeros are different facts about a run, and only one of them is a
   measurement.

4. THE TOOL'S NAMESPACE SURVIVES. `detailedroute__route__drc_errors` says which
   stage computed the number; flattening it would throw away the one property
   that makes an ORFS-shaped key worth having.
"""
import json
import subprocess
import sys
from pathlib import Path

#: See test_issue1080_step_metrics for the ceiling this respects; the slowest
#: test here is a single in-process call and a 3-file glob.
_SUBPROC_S = 30

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

sys.path.insert(0, str(PROGRAMS))
import openroad_metrics as om  # noqa: E402
import step_metrics as sm  # noqa: E402

#: A verbatim call-site string from `phase3_one_shot_runner`, PATH prologue and
#: all. The prologue is the whole point — see property 1.
REAL_CALL = ("export PATH=/foss/tools/openroad/bin:/foss/tools/bin:$PATH && "
             "openroad -no_init -exit /w/pnr.tcl 2>&1 | tee /w/out/openroad.log")


def _run(*args):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "openroad_metrics.py"), *args],
        capture_output=True, text=True, timeout=_SUBPROC_S)


# ---------------------------------------------------------------------------
# with_metrics
# ---------------------------------------------------------------------------
def test_the_path_prologue_is_not_mistaken_for_the_command():
    """The regression that shipped for the length of one test run."""
    out = om.with_metrics(REAL_CALL)
    assert "/foss/tools/openroad/bin:/foss/tools/bin:$PATH" in out, out
    assert "openroad -metrics /w/out/openroad.metrics.json -no_init" in out, out
    # and exactly one flag, on the command, not two
    assert out.count("-metrics") == 1, out


def test_the_metrics_path_is_derived_from_the_tee_target():
    out = om.with_metrics(REAL_CALL)
    assert "-metrics /w/out/openroad.metrics.json" in out, out


def test_wrapping_twice_changes_nothing():
    once = om.with_metrics(REAL_CALL)
    assert om.with_metrics(once) == once


def test_a_command_with_no_log_target_is_refused_not_guessed():
    try:
        om.with_metrics("openroad -no_init -exit /w/x.tcl")
    except om.WiringDefect as exc:
        assert "refusing to invent" in str(exc), str(exc)
    else:
        raise AssertionError("an underivable metrics path was invented")


def test_an_explicit_path_is_accepted_when_there_is_no_tee():
    out = om.with_metrics("openroad -no_init -exit /w/x.tcl",
                          om.metrics_path_for_log("/w/p/repair.log"))
    assert out.startswith("openroad -metrics /w/p/repair.metrics.json "), out


def test_a_string_that_only_names_the_tool_is_not_an_invocation():
    try:
        om.with_metrics("openroad is on PATH")
    except om.WiringDefect:
        pass
    else:
        raise AssertionError("a prose mention was wrapped as a command")


def test_metrics_path_derivation_is_total():
    assert om.metrics_path_for_log("/a/b.log") == "/a/b.metrics.json"
    assert om.metrics_path_for_log("/a/b") == "/a/b.metrics.json"
    assert om.metrics_path_for_log("/a/b.txt") == "/a/b.metrics.json"


# ---------------------------------------------------------------------------
# invocations — what the wiring check reads
# ---------------------------------------------------------------------------
def test_a_path_component_is_not_reported_as_an_invocation():
    found = om.invocations(REAL_CALL)
    assert len(found) == 1, found
    assert found[0]["has_metrics"] is False


def test_a_wrapped_command_reads_as_wired():
    found = om.invocations(om.with_metrics(REAL_CALL))
    assert len(found) == 1 and found[0]["has_metrics"] is True, found


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------
def test_an_absent_metrics_file_is_absent_and_not_a_zero(tmp_path):
    out, prov = om.ingest(tmp_path, "21", tmp_path / "nope.json")
    assert out is None
    assert prov["status"] == "absent", prov
    assert prov["emitted"] == 0
    # and nothing was written that a later collect could read as a measurement
    merged, p = sm.collect(tmp_path)
    assert merged == {} and p["step_count"] == 0, (merged, p)


def test_the_tools_namespace_is_kept_whole_and_only_prefixed(tmp_path):
    src = tmp_path / "drc_router.metrics.json"
    src.write_text(json.dumps({"detailedroute__route__drc_errors": 12,
                               "detailedroute__route__wirelength": 1284310}))
    out, prov = om.ingest(tmp_path, "21", src)
    assert prov["status"] == "emitted" and prov["emitted"] == 2, prov
    doc = json.loads(out.read_text())
    assert doc == {"21__detailedroute__route__drc_errors": 12,
                   "21__detailedroute__route__wirelength": 1284310}, doc


def test_an_ingested_key_is_schema_conformant(tmp_path):
    src = tmp_path / "m.json"
    src.write_text(json.dumps({"detailedroute__route__drc_errors": 12}))
    om.ingest(tmp_path, "21", src)
    assert sm.conformance_defects(tmp_path) == []


def test_a_non_scalar_is_skipped_with_its_reason_not_dropped(tmp_path):
    src = tmp_path / "m.json"
    src.write_text(json.dumps({"a__b": {"nested": 1}, "c__d": 3}))
    _out, prov = om.ingest(tmp_path, "21", src)
    assert prov["read"] == 2 and prov["emitted"] == 1, prov
    assert len(prov["skipped"]) == 1 and prov["skipped"][0]["key"] == "a__b", prov


def test_a_malformed_metrics_file_is_not_an_empty_measurement(tmp_path):
    src = tmp_path / "m.json"
    src.write_text("[1, 2, 3]")
    out, prov = om.ingest(tmp_path, "21", src)
    assert out is None and prov["status"] == "malformed", prov


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_wrap_prints_the_wired_command():
    r = _run("wrap", REAL_CALL)
    assert r.returncode == 0, r.stderr
    assert "-metrics /w/out/openroad.metrics.json" in r.stdout, r.stdout


def test_cli_ingest_of_an_absent_file_does_not_exit_zero(tmp_path):
    r = _run("ingest", str(tmp_path), "21", str(tmp_path / "nope.json"))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
