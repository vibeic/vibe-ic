import json
from decimal import Decimal
import random
import shutil
import subprocess

import pytest

import flow_explore as explorer
from _hostpaths import require_repo


def test_level_policy_document_cli_and_default(tmp_path):
    from flow_ppa_variants import selected_level

    assert selected_level(tmp_path) == (2, "default")
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    policy = docs / "policy.md"
    policy.write_text("# PPA\nPPA_LEVEL = 1\n")
    assert selected_level(tmp_path)[0] == 1
    assert selected_level(tmp_path, 0) == (0, "CLI")
    policy.write_text("# PPA\nPPA_LEVEL = 9\n")
    with pytest.raises(ValueError, match="Invalid document"):
        selected_level(tmp_path)
    assert selected_level(tmp_path, 0) == (0, "CLI")
    policy.write_text("# PPA\nDo not use PPA_LEVEL = 1.\n")
    assert selected_level(tmp_path) == (2, "default")


def test_native_candidate_population_and_fixed_document_settings(tmp_path):
    from flow_ppa_variants import native_candidates

    resolved = {"EXTRA_EXCLUDED_CELLS": ["custom*", "*_1"]}
    a = native_candidates(tmp_path, {}, resolved, level=2)
    prior_state = random.getstate()
    random.seed(999)
    b = native_candidates(tmp_path, {}, resolved, level=2)
    random.setstate(prior_state)
    assert a == b and len(a) == 16
    assert a[0] == ("reference", {})
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "constraints.md").write_text("# Physical constraints\n"
        "VIBEIC_PRR_RECOVER_POWER_PCT = 25\nPL_RESIZER_SETUP_MAX_UTIL_PCT = 75\n")
    constrained = native_candidates(tmp_path, {}, resolved, level=1)
    assert all("VIBEIC_PRR_RECOVER_POWER_PCT" not in value
               and "PL_RESIZER_SETUP_MAX_UTIL_PCT" not in value for _, value in constrained)
    assert len(constrained) < 7
    assert native_candidates(tmp_path, {}, resolved, level=0) == [("reference", {})]


def test_zero_level_runs_once_without_a_ppa_measurement(tmp_path, monkeypatch):
    calls = []

    def run(project, output, variant, *args):
        calls.append(variant)
        return {"name": variant[0], "project": str(output / variant[0]), "overrides": variant[1],
                "rows": [{"name": "authoring", "status": "PASS"}], "metrics": {},
                "resolved_settings": {}, "all_pass": True, "exit_code": 0}

    monkeypatch.setattr(explorer, "run_variant", run)
    report = explorer.explore(tmp_path / "project", tmp_path / "output", ppa_level=0)
    assert report["selected"] == "reference"
    assert len(calls) == 1 and report["ppa_level"] == 0
    assert report["variants"][0]["objective"]["score"] is None


def test_weighted_native_comparison_preserves_power_area_tradeoff(tmp_path, monkeypatch):
    # Existing explorer API, no new symbol required: this observes the winning
    # value rather than merely noticing that the new option/function exists.
    monkeypatch.setattr(explorer, "variants", lambda project, **kwargs:
                        [("reference", {}), ("lower_power", {"VIBEIC_PRR_RECOVER_POWER_PCT": 50})])

    def run(project, output, variant, *args):
        name, overrides = variant
        return {"name": name, "project": str(output / name), "overrides": overrides,
                "rows": [{"name": "native_analysis", "status": "PASS"}], "exit_code": 0,
                "all_pass": True, "resolved_settings": {"CLOCK_PERIOD": 10,
                    "PDK": "process", "STD_CELL_LIBRARY": "cells", "STA_CORNERS": ["nominal"]},
                "metrics": {"design__instance__area": 110 if name == "lower_power" else 100,
                            "power__total": 1 if name == "lower_power" else 10,
                            "timing__setup__ws": 2}}

    monkeypatch.setattr(explorer, "run_variant", run)
    report = explorer.explore(tmp_path / "project", tmp_path / "output", cpus=2, jobs=2)
    assert report["selected"] == "lower_power"
    assert report["variants"][1]["objective"]["improvement_pct"]["area"] == -10
    assert report["weights"]["source"]["power"] == "inherited, not chosen"


def test_postroute_recovery_keeps_separate_setup_and_hold(tmp_path):
    if not shutil.which("tclsh"):
        pytest.skip("Tcl is required to execute the real post-route command construction")
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                          "librelane_plugins", "librelane_plugin_vibeic", "postroute_repair.tcl").read_text()
    # Run the actual repository actuator construction against command-recording
    # native stubs, without starting a second EDA job during runtime measurement.
    start = source.index("# ---- 4. repair")
    end = source.index("# What repair_design left:", start)
    script = '''
proc append_if_exists_argument {variable key flag} {
    upvar 1 $variable args
    if {[info exists ::env($key)]} {lappend args $flag $::env($key)}
}
proc log_cmd {name args} {puts [list $name {*}$args]}
proc vic_say {args} {}
set ::env(VIBEIC_PRR_SETUP_SEQUENCE) default
set ::env(VIBEIC_PRR_SETUP_MARGIN) 0
set ::env(VIBEIC_PRR_HOLD_MARGIN) 0
set ::env(VIBEIC_PRR_SETUP_MAX_BUFFER_PCT) 5
set ::env(VIBEIC_PRR_HOLD_MAX_BUFFER_PCT) 5
'''
    actuator = source[start:end]
    baseline = subprocess.run(["tclsh"], input=script + actuator, text=True, capture_output=True, check=True)
    baseline_lines = baseline.stdout.splitlines()
    assert len([line for line in baseline_lines if line.startswith("repair_timing")]) == 2
    assert not any("recover_power" in line or "set_opt_config" in line for line in baseline_lines)
    optimized = subprocess.run(["tclsh"], input=script + '''
set ::env(VIBEIC_PRR_RECOVER_POWER_PCT) 50
set ::env(VIBEIC_PRR_MAX_UTIL_PCT) 80
set ::env(VIBEIC_PRR_LIMIT_SIZING_AREA) 1
set ::env(VIBEIC_PRR_LIMIT_SIZING_LEAKAGE) 1
''' + actuator, text=True, capture_output=True, check=True)
    lines = optimized.stdout.splitlines()
    assert lines[0] == "set_opt_config -limit_sizing_area 1 -limit_sizing_leakage 1"
    timing = [line for line in lines if line.startswith("repair_timing")]
    assert len(timing) == 3
    assert "-recover_power 50" in timing[0]
    assert "-setup" in timing[1] and "-recover_power" not in timing[1]
    assert "-hold" in timing[2] and "-recover_power" not in timing[2]
    assert all("-max_utilization 80" in line for line in timing)


def test_native_optional_recovery_variables_compile_without_eda(tmp_path):
    pytest.importorskip("librelane")
    from librelane.common import GenericDict
    from librelane.config import Config
    from librelane_plugins.librelane_plugin_vibeic.postroute_repair import PostRouteRepair
    from flow_config import native_defaults

    variables = {var.name: var for var in PostRouteRepair.config_vars}
    overrides = {"VIBEIC_PRR_RECOVER_POWER_PCT": "50", "VIBEIC_PRR_MAX_UTIL_PCT": "80",
                 "VIBEIC_PRR_LIMIT_SIZING_AREA": "1", "VIBEIC_PRR_LIMIT_SIZING_LEAKAGE": "1"}
    (tmp_path / "work/flow").mkdir(parents=True)
    (tmp_path / "work/flow/native_overrides.json").write_text(json.dumps(overrides))
    config = native_defaults(Config({"DESIGN_DIR": str(tmp_path)}))
    for key, raw in overrides.items():
        variable = variables[key]
        assert variable.compile(GenericDict({}), [])[1] is None
        assert variable.compile(GenericDict({key: raw}), [], permissive_typing=True)[1] == Decimal(raw)
        assert variable.compile(config, [], permissive_typing=True)[1] == Decimal(raw)


def test_document_weights_and_unmeasured_reference_are_explicit(tmp_path):
    from flow_ppa_objective import compare_native, objective_weights

    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "policy.md").write_text("# PPA\nPPA_AREA_WEIGHT = 700\nPPA_POWER_WEIGHT = 200\n")
    weights = objective_weights(tmp_path)
    assert weights["values"] == {"performance": 10000, "power": 200, "area": 700}
    assert weights["source"] == {"performance": "inherited, not chosen", "power": "document", "area": "document"}
    reference = {"name": "reference", "metrics": {}, "all_pass": True, "rows": []}
    result = compare_native(reference, reference, weights)
    assert result["score"] is None and not result["eligible"]
    assert "NOT_MEASURED" in result["detail"]


def test_router_history_is_not_a_final_violation_penalty():
    from flow_ppa_objective import final_violation_metrics

    metrics = {"route__drc_errors__iter:0": 87, "route__drc_errors": 3,
               "route__drc_errors_final": 0, "magic__drc_error__count": 0}
    final = final_violation_metrics(metrics)
    assert final == {"route__drc_errors": 0, "magic__drc_error__count": 0}


def test_observed_native_violation_cannot_win_despite_a_passing_summary(tmp_path):
    from flow_ppa_objective import compare_native, objective_weights

    reference = {"name": "reference", "all_pass": True, "rows": [],
                 "resolved_settings": {"CLOCK_PERIOD": 10, "PDK": "process",
                    "STD_CELL_LIBRARY": "cells", "STA_CORNERS": ["nominal"]},
                 "metrics": {"design__instance__area": 100, "power__total": 10,
                             "timing__setup__ws": 2}}
    candidate = {**reference, "violation_metrics": {"magic__drc_error__count": 1}}
    result = compare_native(reference, candidate, objective_weights(tmp_path))
    assert not result["eligible"]
    assert result["score"] > compare_native(reference, reference, objective_weights(tmp_path))["score"]
    candidate["violation_metrics"]["magic__drc_error__count"] = None
    result = compare_native(reference, candidate, objective_weights(tmp_path))
    assert result["score"] is None and not result["eligible"]
