"""Power intent is emitted before RTL without inventing state-analysis results."""
import json
from pathlib import Path
import subprocess

import pytest

import flow_engine as engine
import flow_native_adapters as adapters
import l21_to_upf_emit as emitter


@pytest.mark.parametrize("code,expected", [(0, "NOT_MEASURED"), (1, "FAIL"), (2, "NOT_MEASURED")])
def test_power_intent_runs_before_rtl(tmp_path, monkeypatch, code, expected):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_IMPLEMENTATION.json").write_text(json.dumps({"top_module": "core"}))
    calls = []

    def run(self, argv, **kwargs):
        argv = list(map(str, argv))
        calls.append(argv)
        assert argv[argv.index("--top") + 1] == "core"
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps({"verdict": "PASS"}))
        self.records.append({"exit_code": code, "log": str(self.directory / "emit.log")})
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(adapters.Commands, "run", run)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "power_intent_and_domain_rules")
    native = engine.ToolResult(**adapters.execute(tmp_path, tmp_path / "step", row["tool"], {}))
    assert len(calls) == 1
    assert not (tmp_path / "phase2/stage1/rtl").exists()
    assert "illegal_power_states" not in native.metrics
    measured = engine.measure(row["checks"], native.metrics, {}, {"has_power_intent": True})
    assert engine.evaluate(native, measured) == expected


def test_emitter_preserves_domain_elements(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L21_DOMAIN_PLAN.json").write_text(json.dumps({"fields": {"power_domains": [
        {"name": "AON", "power_net": "VDD_AON", "elements": ["u_aon"]},
        {"name": "SW", "power_net": "VDD_SW", "elements": ["u_counter"]}]}}))
    assert emitter.main([str(tmp_path), "--top", "core"]) == 0
    text = (tmp_path / "phase2/stage2/constraints/core.upf").read_text()
    assert "create_power_domain PD_AON -elements {u_aon}" in text
    assert "create_power_domain PD_SW -elements {u_counter}" in text
    assert "-include_scope" not in text


def test_missing_supply_is_not_a_design_failure(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L21_POWER_INTENT.json").write_text(json.dumps({"power_domains": [{"name": "SW"}]}))
    report = tmp_path / "emit.json"
    assert emitter.main([str(tmp_path), "--json", str(report)]) == 2
    assert json.loads(report.read_text())["verdict"] == "NOT_MEASURED"
