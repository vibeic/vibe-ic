import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("librelane")
from librelane.common import Path as NativePath
from librelane.config import Config
from librelane.state import DesignFormat, State
from librelane.steps import StepError, StepException
import flow_density_topup as density
import flow_engine as engine


REPORT = "Stepped area density results (total tiles = 1):\nFOM Density: 0.400\n"


@pytest.fixture
def driver(tmp_path):
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    (helpers / "generate_fill.py").write_text(
        "import gzip, pathlib, sys\n"
        "assert len(sys.argv) == 3 and sys.argv[2] == '-dist'\n"
        "source = pathlib.Path(sys.argv[1])\n"
        "assert source.name == 'unit.gds' and not source.is_absolute()\n"
        "assert source.is_symlink() and source.read_bytes() == b'layout'\n"
        "with gzip.open(source.stem + '_fill_pattern.gds.gz', 'wb') as stream:\n"
        "    stream.write(b'pattern')\n")
    source = tmp_path / "source.gds"
    source.write_bytes(b"layout")
    work = tmp_path / "step"
    work.mkdir()

    class Driver:
        config = {"MAGICRC": str(helpers / "native.magicrc"), "DESIGN_NAME": "unit",
                  "PDK": "native", "PDK_ROOT": str(tmp_path), "KLAYOUT_DENSITY_RUNSET": None}
        step_dir = str(work)
        calls = []

        def run_magic(self, *args, **kwargs):
            return density.DensityTopUp.run_magic(self, *args, **kwargs)

        def extract_env(self, kwargs):
            return kwargs, os.environ.copy()

        def run_subprocess(self, command, log_to, env, **kwargs):
            self.calls.append(command)
            assert env["PDK"] == "native" and env["PDK_ROOT"] == str(tmp_path)
            if command[0] == "klayout":
                assert Path(command[4]).name == "insert_cell.py"
                paths = dict(item.split("=", 1) for item in command if "=" in item)
                assert Path(paths["input"]).name == Path(paths["output"]).name == "unit.gds"
                with gzip.open(paths["insert"], "rb") as stream:
                    Path(paths["output"]).write_bytes(Path(paths["input"]).read_bytes() + stream.read())
                Path(log_to).write_text("merge test double\n")
            else:
                result = subprocess.run(command, env=env, capture_output=True, text=True, **kwargs)
                Path(log_to).write_text(result.stdout + result.stderr)
                result.check_returncode()

    def check_report(report):
        (helpers / "check_density.py").write_text(
            "import pathlib, sys\n"
            "assert len(sys.argv) == 2\n"
            "source = pathlib.Path(sys.argv[1])\n"
            "assert source.name == 'unit.gds' and not source.is_absolute()\n"
            "assert not source.is_symlink() and source.read_bytes() == b'layoutpattern'\n"
            f"print({report!r})\n")

    check_report(REPORT + "Done!\n")
    state = State({DesignFormat.GDS: NativePath(str(source))}, metrics={density.METRIC: 0})
    return Driver(), state, check_report


def test_magic_helpers_merge_current_layout_and_count_every_native_error(driver):
    step, state, report = driver
    report(REPORT + "***Error: native conductor rule\n***Error: native nonmetal rule\nDone!\n")
    views, metrics = density.DensityTopUp.run_magic(step, state)
    assert metrics == {"magic__density_error__count": 2}
    assert Path(str(views[DesignFormat.GDS])).read_bytes() == b"layoutpattern"
    assert len(step.calls) == 3
    assert (Path(str(views[DesignFormat.GDS])).parent.parent / "density.log").is_file()
    assert state[DesignFormat.GDS].endswith("source.gds")


@pytest.mark.parametrize("report", ["", "Done!\n", REPORT, "FOM Density: 0.400\nDone!\n"])
def test_magic_requires_completed_measured_density_report(driver, report):
    step, state, write_report = driver
    write_report(report)
    with pytest.raises(StepException, match="incomplete or unmeasured"):
        density.DensityTopUp.run_magic(step, state)


def test_magic_clean_report_produces_magic_zero(driver):
    step, state, _ = driver
    _, metrics = density.DensityTopUp.run_magic(step, state)
    assert metrics == {"magic__density_error__count": 0}


@pytest.mark.parametrize("missing", ["MAGICRC", "check_density.py"])
def test_no_density_backend_remains_unmeasured(driver, missing):
    step, state, _ = driver
    if missing == "MAGICRC":
        step.config = {**step.config, "MAGICRC": None}
    else:
        (Path(step.config["MAGICRC"]).parent / missing).unlink()
    with pytest.raises(StepException, match="no configured native density"):
        density.DensityTopUp.run_magic(step, state)


def test_native_step_retains_magicrc_and_runs_helper_backend(driver, monkeypatch):
    step, state, _ = driver
    state = State(state, metrics={density.METRIC: 1})
    config = Config({item.name: None for item in density.DensityTopUp.get_all_config_variables()},
                    overrides={**step.config, "UNRELATED": "filtered"})
    constructed = density.DensityTopUp(config, state, _no_revalidate_conf=True)
    assert constructed.config.get("MAGICRC") == step.config["MAGICRC"]
    assert "UNRELATED" not in constructed.config
    constructed.step_dir = step.step_dir
    monkeypatch.setattr(constructed, "run_subprocess", step.run_subprocess)
    views, metrics = constructed.run(state)
    assert metrics == {"magic__density_error__count": 0}
    assert Path(str(views[DesignFormat.GDS])).read_bytes() == b"layoutpattern"


@pytest.mark.parametrize("runset", [None, "native.drc"])
def test_native_zero_does_not_invoke_topup(driver, runset):
    step, state, _ = driver
    step.config = {**step.config, "KLAYOUT_DENSITY_RUNSET": runset, "MAGICRC": None}
    assert density.DensityTopUp.run(step, state) == ({}, {})
    assert step.calls == []
    assert state.metrics[density.METRIC] == 0


def test_native_missing_deck_and_count_skip_without_fabricating_zero(driver):
    step, state, _ = driver
    state = State(state, metrics={})
    step.config = {**step.config, "MAGICRC": None}
    assert density.DensityTopUp.run(step, state) == ({}, {})
    assert step.calls == []
    assert density.METRIC not in state.metrics


def test_configured_deck_missing_native_count_remains_unmeasured(driver):
    step, state, _ = driver
    state = State(state, metrics={})
    step.config = {**step.config, "KLAYOUT_DENSITY_RUNSET": "native.drc"}
    with pytest.raises(StepException, match="has not produced its native count"):
        density.DensityTopUp.run(step, state)


def test_native_positive_without_fill_engine_preserves_original_failure(driver, monkeypatch):
    step, state, _ = driver
    state = State(state, metrics={density.METRIC: 2})
    step.config = {**step.config, "KLAYOUT_DENSITY_RUNSET": "native.drc"}
    monkeypatch.setenv("VIBEIC_KLAYOUT_TOOLS", str(Path(step.step_dir) / "absent"))
    assert density.DensityTopUp.run(step, state) == ({}, {})
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "metal_density_fill")
    measured = engine.measure(row["checks"], state.metrics, step.config, {"ic": True})
    assert measured[0]["status"] == "FAIL" and measured[0]["value"] == 2
    assert measured[0]["limit"] == 0


def test_native_positive_without_deck_or_helpers_still_fails(driver):
    step, state, _ = driver
    state = State(state, metrics={density.METRIC: 2})
    step.config = {**step.config, "MAGICRC": None}
    with pytest.raises(StepError, match="density violations remain") as failure:
        density.DensityTopUp.run(step, state)
    assert not isinstance(failure.value, StepException)
    assert "NOT_MEASURED" not in str(failure.value)
    assert state.metrics[density.METRIC] == 2


def test_positive_magic_result_remains_failure_without_klayout_deck(driver):
    step, state, report = driver
    state = State(state, metrics={density.METRIC: 2})
    report(REPORT + "***Error: native conductor rule\nDone!\n")
    with pytest.raises(StepError, match="Magic density violations"):
        density.DensityTopUp.run(step, state)


def test_incomplete_magic_repair_cannot_erase_original_native_failure(driver):
    step, state, report = driver
    state = State(state, metrics={density.METRIC: 2})
    report("Done!\n")
    with pytest.raises(StepError, match="density violations remain") as failure:
        density.DensityTopUp.run(step, state)
    assert not isinstance(failure.value, StepException)
    assert "NOT_MEASURED" not in str(failure.value)
    assert state.metrics[density.METRIC] == 2


@pytest.mark.parametrize("backend,count,status", [
    ("magic", 0, "PASS"), ("magic", 2, "FAIL"),
    ("klayout", 0, "PASS"), ("klayout", 2, "FAIL"), (None, None, "NOT_MEASURED")])
def test_density_recipe_measures_actual_backend_and_dfm_observes_it(tmp_path, backend, count, status):
    features = {"ic": True, "physical": True, "analog_physical": False,
                "digital_physical": True, "assembly_only": False, "requires_advanced_dfm": False}
    metrics = {f"{backend}__density_error__count": count} if backend else {}
    table = engine.read_json(engine.TABLE)
    row = next(item for item in table["steps"] if item["name"] == "metal_density_fill")
    selected = engine.choose_tool(row["tool"], features)
    assert "Checker.KLayoutDensity" not in selected["steps"]
    config = {"KLAYOUT_DENSITY_RUNSET": "native.drc"}
    measured = engine.measure(row["checks"], metrics, config, features)
    assert len(measured) == 1 and measured[0]["status"] == status
    assert measured[0]["limit"] == 0
    dfm = next(item for item in table["steps"] if item["name"] == "design_for_manufacturability")
    observations, _ = engine.report_observations(
        dfm, tmp_path, SimpleNamespace(metrics=metrics.copy()), {}, features, None)
    assert observations[0]["values"] == metrics


def test_native_density_check_applies_only_to_configured_native_deck():
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "metal_density_fill")
    assert engine.measure(row["checks"], {}, {"KLAYOUT_DENSITY_RUNSET": None}, {"ic": True}) == []
    assert engine.measure(row["checks"], {}, {}, {"ic": True})[0]["status"] == "NOT_MEASURED"
    measured = engine.measure(row["checks"], {}, {"KLAYOUT_DENSITY_RUNSET": "native.drc"}, {"ic": True})
    assert measured[0]["status"] == "NOT_MEASURED"
