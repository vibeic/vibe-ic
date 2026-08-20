"""PPA phase 0 — the flow DECLARES a metric per axis, and a run RECORDS it.

WHAT WAS WRONG
--------------
Measured on `flow/phase1_phase2_phase3.yaml` at v1.11.7: the union of step keys
over every step entry was

    blocks_on closed_loop condition condition_kind gate id known_gap mcp_tools
    name notes programs required_inputs required_outputs skills stage

There is no metric key, so no step declared a metric for ANY axis, and the
count of steps declaring an AREA metric was zero for the same reason the timing
count was. Meanwhile the numbers existed: synthesis area and cell count in
`stats.json`, the OpenSTA power table's four components, DIEAREA in the DEF.
Nothing named them, so nothing could ask for one and no absence was detectable.

THE TWO PROPERTIES THIS FILE HOLDS
----------------------------------
1. THE CHECKER HAS SEEN ITS RED. `flow_metric_coverage_check` must FAIL on a
   flow that declares no metric for a gated axis. A coverage checker that only
   ever ran against the flow it was written for is a certificate. Asserted
   against a synthetic flow with the declarations stripped — which is exactly
   the pre-change shape of the shipped one.

2. A FIELD A RUN DID NOT PRODUCE IS THE LITERAL `NOT_MEASURED`. Not 0, not
   null, not absent, not the previous run's number. `flow_metric_record` must
   WRITE the literal into the per-step metrics file, so a consumer iterating
   the recorded metrics sees the hole without knowing the flow.

MUTANTS PINNED HERE (each one killed by a named test below):

  * `declarations` -> accept a malformed entry (drop the REQUIRED_FIELDS
     check). Then `metrics: [{}]` closes an axis and the checker certifies a
     flow that declares nothing readable.
     killed by: test_a_malformed_declaration_does_not_close_an_axis
  * `read_metric` -> return 0 instead of NOT_MEASURED on a missing source.
     Every empty run then reports a full sweep of zeroes.
     killed by: test_an_absent_source_records_the_literal_not_measured
  * `read_metric` -> OMIT the key instead of recording NOT_MEASURED. The
     per-step file then looks like a run that was never asked for the number.
     killed by: test_not_measured_is_written_not_omitted
  * the log readers -> take the FIRST match instead of the LAST. The router
     reprints its total as it iterates; on a real run the first is 13033 and
     the last 12704.
     killed by: test_the_log_readers_take_the_last_occurrence_not_the_first
  * `main` -> return 0 when the project directory does not exist. "I could not
     look" then reads the same as "I looked and found nothing".
     killed by: test_a_project_that_cannot_be_read_is_not_a_run_with_no_metrics
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROGRAMS = Path(__file__).resolve().parent.parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
COVERAGE = PROGRAMS / "flow_metric_coverage_check.py"
RECORD = PROGRAMS / "flow_metric_record.py"

#: Bounded well under the harness ceiling: these calls parse one YAML file and
#: read a handful of small text files, so a call that needs longer is hung, not
#: slow, and a bound the harness will not keep kills the SESSION rather than
#: the test.
TIMEOUT = 60


def run(args):
    return subprocess.run([sys.executable] + [str(a) for a in args],
                          capture_output=True, text=True, timeout=TIMEOUT)


def load_flow():
    return yaml.safe_load(FLOW.read_text(encoding="utf-8"))


def write_flow(path: Path, doc) -> Path:
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


# ── property 1: the checker has seen its red ────────────────────────────────
def test_the_shipped_flow_declares_every_axis():
    r = run([COVERAGE, "--flow-def", FLOW])
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_flow_with_no_declarations_fails_and_that_is_the_red(tmp_path):
    """The pre-change shape of the shipped flow. This is the checker's red."""
    doc = load_flow()
    for s in doc["steps"]:
        s.pop("metrics", None)
    f = write_flow(tmp_path / "flow.yaml", doc)
    r = run([COVERAGE, "--flow-def", f, "--axis", "area", "--axis", "power"])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "area" in r.stderr and "power" in r.stderr


def test_every_axis_is_reported_even_when_only_one_is_gated(tmp_path):
    """An axis this invocation does not gate on is still visible."""
    r = run([COVERAGE, "--flow-def", FLOW, "--axis", "area"])
    assert r.returncode == 0, r.stdout + r.stderr
    for axis in ("performance", "power", "area"):
        assert axis in r.stdout
    assert "reported only" in r.stdout  # the two ungated axes say so


def test_one_uncovered_gated_axis_is_enough_to_fail(tmp_path):
    doc = load_flow()
    for s in doc["steps"]:
        if "metrics" in s:
            s["metrics"] = [m for m in s["metrics"] if m["axis"] != "power"]
            if not s["metrics"]:
                s.pop("metrics")
    f = write_flow(tmp_path / "flow.yaml", doc)
    assert run([COVERAGE, "--flow-def", f, "--axis", "area"]).returncode == 0
    assert run([COVERAGE, "--flow-def", f, "--axis", "power"]).returncode == 1


def test_a_malformed_declaration_does_not_close_an_axis(tmp_path):
    """MUTANT: drop REQUIRED_FIELDS and `metrics: [{}]` certifies the flow."""
    doc = load_flow()
    for s in doc["steps"]:
        s.pop("metrics", None)
    doc["steps"][0]["metrics"] = [{"name": "design__instance__area",
                                   "axis": "area"}]  # no source, no reader
    f = write_flow(tmp_path / "flow.yaml", doc)
    r = run([COVERAGE, "--flow-def", f, "--axis", "area"])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "missing/empty" in r.stderr


def test_an_axis_outside_the_vocabulary_is_a_defect_not_a_new_axis(tmp_path):
    doc = load_flow()
    for s in doc["steps"]:
        s.pop("metrics", None)
    doc["steps"][0]["metrics"] = [{"name": "x__y__z", "axis": "powers",
                                   "source": "a.json", "reader": "json:v"}]
    f = write_flow(tmp_path / "flow.yaml", doc)
    r = run([COVERAGE, "--flow-def", f, "--axis", "power"])
    assert r.returncode == 1
    assert "not one of" in r.stderr


def test_two_steps_cannot_own_one_key(tmp_path):
    doc = load_flow()
    for s in doc["steps"]:
        s.pop("metrics", None)
    d = {"name": "design__instance__area", "axis": "area",
         "source": "a.json", "reader": "json:v"}
    doc["steps"][0]["metrics"] = [dict(d), dict(d)]
    f = write_flow(tmp_path / "flow.yaml", doc)
    r = run([COVERAGE, "--flow-def", f])
    assert r.returncode == 1
    assert "already declared" in r.stderr


def test_an_unreadable_flow_is_not_checked_never_clean(tmp_path):
    bad = tmp_path / "flow.yaml"
    bad.write_text("steps: [ this: is: not: yaml\n", encoding="utf-8")
    r = run([COVERAGE, "--flow-def", bad])
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT CHECKED" in r.stderr
    empty = tmp_path / "empty.yaml"
    empty.write_text("steps: []\n", encoding="utf-8")
    r2 = run([COVERAGE, "--flow-def", empty])
    assert r2.returncode == 2, r2.stdout + r2.stderr


# ── property 2: NOT_MEASURED, never a default ───────────────────────────────
def test_an_absent_source_records_the_literal_not_measured(tmp_path):
    """MUTANT: return 0 on a missing source -> an empty run sweeps clean."""
    r = run([RECORD, tmp_path, "--flow-def", FLOW])
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    assert rep["measured"] == 0
    assert rep["not_measured"] == rep["declared"] > 0
    for m in rep["metrics"]:
        assert m["value"] == "NOT_MEASURED"
        assert m["detail"], "a refusal must say WHY it refused"


def test_not_measured_is_written_not_omitted(tmp_path):
    """MUTANT: omit the key -> the file reads as never having been asked."""
    run([RECORD, tmp_path, "--flow-def", FLOW])
    step_files = sorted((tmp_path / "reports" / "metrics").glob("*.json"))
    assert len(step_files) > 1, "a per-step file per declaring step"
    for f in step_files:
        if f.name == "ppa.json":
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc, f"{f.name} is empty; the hole was omitted, not recorded"
        assert all(v == "NOT_MEASURED" for v in doc.values()), doc


def test_require_measured_turns_a_hole_into_a_non_zero_exit(tmp_path):
    assert run([RECORD, tmp_path, "--flow-def", FLOW]).returncode == 0
    r = run([RECORD, tmp_path, "--flow-def", FLOW, "--require-measured"])
    assert r.returncode == 1
    assert "NOT_MEASURED" in r.stderr


def test_a_project_that_cannot_be_read_is_not_a_run_with_no_metrics(tmp_path):
    """MUTANT: exit 0 on a missing project -> could-not-look == looked-clean."""
    r = run([RECORD, tmp_path / "no_such_dir", "--flow-def", FLOW])
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT RECORDED" in r.stderr


def test_a_flow_that_declares_nothing_is_not_a_run_that_measured_nothing(
        tmp_path):
    doc = load_flow()
    for s in doc["steps"]:
        s.pop("metrics", None)
    f = write_flow(tmp_path / "flow.yaml", doc)
    proj = tmp_path / "proj"
    proj.mkdir()
    r = run([RECORD, proj, "--flow-def", f])
    assert r.returncode == 2, r.stdout + r.stderr
    assert "declares no metrics" in r.stderr


# ── the readers ─────────────────────────────────────────────────────────────
def _synth_stats(proj: Path, **kw):
    d = proj / "phase2" / "stage2" / "synth"
    d.mkdir(parents=True, exist_ok=True)
    (d / "stats.json").write_text(json.dumps(kw), encoding="utf-8")


def test_the_json_reader_reads_the_declared_field(tmp_path):
    _synth_stats(tmp_path, chip_area=1234.5, cell_count=42)
    run([RECORD, tmp_path, "--flow-def", FLOW])
    rep = json.loads((tmp_path / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    by = {m["key"]: m for m in rep["metrics"]}
    assert by["9__design__instance__area"]["value"] == 1234.5
    assert by["9__design__instance__count"]["value"] == 42
    assert by["9__design__instance__area"]["provenance"] == "artefact"


def test_a_present_but_null_field_is_not_a_measurement(tmp_path):
    _synth_stats(tmp_path, chip_area=None, cell_count=42)
    run([RECORD, tmp_path, "--flow-def", FLOW])
    rep = json.loads((tmp_path / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    by = {m["key"]: m for m in rep["metrics"]}
    assert by["9__design__instance__area"]["value"] == "NOT_MEASURED"
    assert by["9__design__instance__count"]["value"] == 42


def test_the_log_readers_take_the_last_occurrence_not_the_first(tmp_path):
    """MUTANT: take the first match.

    Both figures are reprinted by the tool as it iterates. On a real run
    (spm, 2026-08-03) the router printed 13033 first and 12704 last, and
    detailed placement 45.6% first and 59.2% last.
    """
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "openroad.log").write_text(
        "Total wire length = 13033 um.\n"
        "[INFO DPL-0009] Utilization: 45.6%\n"
        "noise\n"
        "[INFO DPL-0009] Utilization: 59.2%\n"
        "Total wire length = 12704 um.\n", encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    rep = json.loads((tmp_path / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    by = {m["key"]: m for m in rep["metrics"]}
    assert by["21__route__wirelength"]["value"] == 12704.0
    assert by["17__design__instance__utilization"]["value"] == 59.2


def test_a_log_derived_reading_is_labelled_log_not_metric(tmp_path):
    """A proxy must not be laundered into a measurement."""
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "openroad.log").write_text("Total wire length = 99 um.\n",
                                    encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    rep = json.loads((tmp_path / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    by = {m["key"]: m for m in rep["metrics"]}
    assert by["21__route__wirelength"]["provenance"] == "log"
    r = run([RECORD, tmp_path, "--flow-def", FLOW,
             "--require-provenance", "artefact"])
    assert r.returncode == 1
    assert "weaker than" in r.stderr


def test_die_area_is_scaled_by_the_def_s_own_units(tmp_path):
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "filled.def").write_text(
        "UNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 142000 142000 ) ;\n", encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    rep = json.loads((tmp_path / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    by = {m["key"]: m for m in rep["metrics"]}
    assert by["37__design__die__area"]["value"] == pytest.approx(142.0 * 142.0)


def test_a_def_with_no_units_yields_no_area(tmp_path):
    """Coordinates with no declared scale are not an area."""
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "filled.def").write_text("DIEAREA ( 0 0 ) ( 142000 142000 ) ;\n",
                                  encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    rep = json.loads((tmp_path / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    by = {m["key"]: m for m in rep["metrics"]}
    assert by["37__design__die__area"]["value"] == "NOT_MEASURED"
    assert "UNITS" in by["37__design__die__area"]["detail"]


def test_core_area_refuses_a_single_row_rather_than_inventing_a_height(
        tmp_path):
    """Row height is the y-pitch between rows; one row has no pitch."""
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    one = ("UNITS DISTANCE MICRONS 1000 ;\n"
           "ROW ROW_0 unit 10560 10080 N DO 168 BY 1 STEP 660 0 ;\n")
    (d / "placed.def").write_text(one, encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    by = {m["key"]: m for m in json.loads(
        (tmp_path / "reports" / "metrics" / "ppa.json")
        .read_text(encoding="utf-8"))["metrics"]}
    assert by["17__design__core__area"]["value"] == "NOT_MEASURED"
    assert "single y" in by["17__design__core__area"]["detail"]

    (d / "placed.def").write_text(
        one + "ROW ROW_1 unit 10560 15120 FS DO 168 BY 1 STEP 660 0 ;\n",
        encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    by = {m["key"]: m for m in json.loads(
        (tmp_path / "reports" / "metrics" / "ppa.json")
        .read_text(encoding="utf-8"))["metrics"]}
    # 168 sites x 0.66 um wide; two rows 5.04 um apart -> 10.08 um tall
    assert by["17__design__core__area"]["value"] == pytest.approx(
        110.88 * 10.08)


def test_the_power_split_is_four_figures_not_one(tmp_path):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "power.rpt").write_text(
        "Group                  Internal  Switching    Leakage      Total\n"
        "Sequential             1.59e-03   2.62e-05   4.98e-09   1.62e-03\n"
        "Total                  1.80e-03   1.62e-04   1.32e-08   1.96e-03 "
        "100.0%\n", encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    by = {m["key"]: m for m in json.loads(
        (tmp_path / "reports" / "metrics" / "ppa.json")
        .read_text(encoding="utf-8"))["metrics"]}
    assert by["33__power__internal__total"]["value"] == pytest.approx(1.80e-03)
    assert by["33__power__switching__total"]["value"] == pytest.approx(1.62e-04)
    assert by["33__power__leakage__total"]["value"] == pytest.approx(1.32e-08)
    assert by["33__power__total"]["value"] == pytest.approx(1.96e-03)


def test_a_power_report_with_no_total_row_is_not_zero_power(tmp_path):
    """The file exists and tabulated nothing. That is not a reading of zero."""
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "power.rpt").write_text("REPORT_POWER_FAIL: no liberty\n",
                                 encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    by = {m["key"]: m for m in json.loads(
        (tmp_path / "reports" / "metrics" / "ppa.json")
        .read_text(encoding="utf-8"))["metrics"]}
    for k in ("internal__total", "switching__total", "leakage__total",
              "total"):
        assert by[f"33__power__{k}"]["value"] == "NOT_MEASURED"


def test_a_step_emitted_metric_is_read_back_and_labelled_metric(tmp_path):
    """The strongest provenance: the step that computed it emitted it."""
    d = tmp_path / "reports" / "metrics"
    d.mkdir(parents=True)
    (d / "20.json").write_text(json.dumps({"20__timing__hold__ws": 0.0412}),
                               encoding="utf-8")
    run([RECORD, tmp_path, "--flow-def", FLOW])
    by = {m["key"]: m for m in json.loads(
        (d / "ppa.json").read_text(encoding="utf-8"))["metrics"]}
    assert by["20__timing__hold__ws"]["value"] == 0.0412
    assert by["20__timing__hold__ws"]["provenance"] == "metric"


# ── the declarations themselves ─────────────────────────────────────────────
def test_every_declared_reader_is_one_the_recorder_implements(tmp_path):
    """A declaration naming a reader nobody implements is a permanent hole."""
    proj = tmp_path / "proj"
    proj.mkdir()
    run([RECORD, proj, "--flow-def", FLOW])
    rep = json.loads((proj / "reports" / "metrics" / "ppa.json")
                     .read_text(encoding="utf-8"))
    for m in rep["metrics"]:
        assert "no reader named" not in (m["detail"] or ""), m


def test_every_declared_source_is_relative_to_the_run_root():
    doc = load_flow()
    for s in doc["steps"]:
        for m in (s.get("metrics") or []):
            src = m["source"]
            assert not src.startswith("/"), (s["id"], src)
            assert ".." not in src.split("/"), (s["id"], src)
