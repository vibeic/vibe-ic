import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

pytest.importorskip("librelane")

import flow_em_corners as em


def report(violations=0, utilization="93.33", skipped=0, verdict="PASS"):
    return (f"Worst utilization : {utilization} %\nViolations : {violations}\n"
            f"No J-limit (skipped): {skipped}\nNo area (skipped): 0\n"
            f"Segments checked: 12\nVerdict : {verdict}\n")


def test_native_rail_results_keep_original_zero_and_percent_values():
    text = "=== EM_NET VDD ===\n" + report() + "=== EM_NET VSS ===\n" + report(utilization="99.1")
    metrics = em.current_density_metrics(text, ["VDD", "VSS"])
    assert metrics["em_violations"] == 0
    assert metrics["em_worst_utilization_pct"] == 99.1


def test_native_violation_is_kept_even_with_an_incomplete_other_rail():
    text = "=== EM_NET VDD ===\n" + report(2, "101", verdict="FAIL")
    assert em.current_density_metrics(text, ["VDD", "VSS"])["em_violations"] == 2


def test_native_failed_verdict_does_not_become_missing_measurement():
    with pytest.raises(em.StepError, match="verdict is FAIL"):
        em.current_density_metrics("=== EM_NET VDD ===\nVerdict: FAIL\n", ["VDD", "VSS"])


@pytest.mark.parametrize("values, expected", [
    ([{"em_violations": 0, "em_worst_utilization_pct": 98},
      {"em_violations": 0, "em_worst_utilization_pct": 99}], {"em_violations": 0, "em_worst_utilization_pct": 99}),
    ([{"em_violations": 0, "em_worst_utilization_pct": 98}, {}], {}),
    ([{"em_violations": 1, "em_worst_utilization_pct": 101}, {}],
     {"em_violations": 1, "em_worst_utilization_pct": 101}),
])
def test_corner_aggregation_preserves_missing_and_failed_results(monkeypatch, values, expected):
    corners = ["max_slow", "max_fast"]
    metrics = {f"{key}__corner:{corner}": value for corner, row in zip(corners, values)
               for key, value in row.items()}
    monkeypatch.setattr(em.IRDropCorners, "run", lambda *args, **kwargs: ({}, metrics))
    step = object.__new__(em.EMCorners)
    step.config = {"STA_CORNERS": corners}
    result = step.run(object())[1]
    assert {key: result[key] for key in ("em_violations", "em_worst_utilization_pct")
            if key in result} == expected


@pytest.mark.parametrize("text", ["", report(), "=== EM_NET VDD ===\n" + report(),
    "=== EM_NET VDD ===\n" + report(skipped=1),
    "=== EM_NET VDD ===\n" + report(utilization="nan"),
    "=== EM_NET VDD ===\n" + report().replace("Violations : 0\n", "")])
def test_incomplete_native_results_do_not_become_pass(text):
    assert "em_violations" not in em.current_density_metrics(text, ["VDD", "VSS"])


def test_generator_keeps_ic_em_selected_with_original_limits(tmp_path):
    from flow_engine import choose_tool, design_features, predicate
    from flow_steps_generate import ROOT, classify_checks, generate

    native = json.loads((ROOT / "flow/native_limits.json").read_text())
    registry = json.loads((ROOT / "flow/flow109.json").read_text())
    table, _, _ = generate(registry, native)
    classify_checks(table, native)
    features = design_features(tmp_path, {"delivery_target": "shippable_gds"}, table)
    row = next(row for row in table["steps"] if row["name"] == "candidate_electromigration")
    assert features["requires_em"] is True
    assert predicate(row["when"], features)
    assert choose_tool(row["tool"], features)["steps"] == ["VibeIC.EMCorners"]
    assert {(c["metric"], c["operator"], c["limit"]) for c in row["checks"]} == {
        ("em_violations", "==", 0), ("em_worst_utilization_pct", "<=", 100)}
    assert design_features(tmp_path, {"delivery_target": "ip_hardmacro"}, table)["requires_em"] is True


@pytest.mark.parametrize("supplies", [(["PWR"], ["GND"]), (None, None)])
def test_native_tcl_loads_serialized_environment_and_forwards_supply_sources(tmp_path, monkeypatch, supplies):
    lef = tmp_path / "nominal.lef"
    lef.write_text("native technology")
    native_script = tmp_path / "native_ir.tcl"
    native_script.write_text('''set vsrc_files [dict create PWR bonded.vsrc]
proc check_current_density {args} {
    puts "CALL $args"
    puts "Segments checked: 12"
    puts "No J-limit (skipped): 0"
    puts "No area (skipped): 0"
    puts "Worst utilization: 25 %"
    puts "Violations: 0"
    puts "Verdict: PASS"
}
''')
    monkeypatch.setattr(em.IRDropReport, "get_script_path", lambda self: str(native_script))
    limit_calls, outputs = [], []
    monkeypatch.setattr(em, "native_limits", lambda *args: limit_calls.append(args) or "metal 0.001\n")

    def run_native(self, state, env, **kwargs):
        env["STEP_DIR"] = str(tmp_path)
        serialized = tmp_path / "environment.tcl"
        serialized.write_text("\n".join(f"set ::env({key}) {{{value}}}" for key, value in env.items())
                              + '\nset ::env(VDD_NETS) {PWR}\nset ::env(GND_NETS) {GND}\n')
        process = subprocess.run([shutil.which("openroad"), "-no_init", "-no_splash", "-exit", self.get_script_path()],
                                 env={"_TCL_ENV_IN": str(serialized)}, capture_output=True, text=True, check=True)
        outputs.append(process.stdout)
        (tmp_path / "em.rpt").write_text(process.stdout)
        return {}, {"ir__drop__worst": 0.001}

    monkeypatch.setattr(em.IRDropReport, "run", run_native)
    step = object.__new__(em.CurrentDensityReport)
    step.step_dir = str(tmp_path)
    step.config = {"PDK": "fixture", "TECH_LEFS": {}, "VDD_NETS": supplies[0], "GND_NETS": supplies[1],
                   "VDD_PIN": "PWR", "GND_PIN": "GND"}
    step.toolbox = SimpleNamespace(filter_views=lambda *args, **kwargs: [lef])
    metrics = step.run(object(), env={})[1]
    assert metrics["em_violations"] == 0
    assert metrics["em_worst_utilization_pct"] == 25
    assert limit_calls == [("native technology", 0.0, "fixture")]
    assert outputs[0].count("-vsrc bonded.vsrc") == 1
    assert "-net PWR" in outputs[0] and "-net GND" in outputs[0]
