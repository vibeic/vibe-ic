"""Public historical L8 regression; this is not an accepted replay checkpoint.

The canonical front door still requires genuine independent review. These
controls exercise its actual clock producer and gate, without signing anything.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import l8_doc_clock_freq_synth as producer
import phase1_doc_one_shot_runner as phase1

FIXTURE = Path(__file__).parent / "fixtures" / "issue3473_retained_replay"
LAYERS = ("L8_RTL_CONSTANTS", "L8_TIMING_WAVEFORM")
REPLAY_DEPENDENCIES = (
    "vibe_ic_one_shot_runner.py", "design_one_shot_runner.py",
    "phase1_doc_one_shot_runner.py", "l8_doc_clock_freq_synth.py",
    "_step_identity.py", "step_output_collector.py", "_phase1_producer_identity.py", "execution_step4.py", "ai_signed_judgement.py",
    "serial_parallel_mul_synth.py", "_cdc_netlist.py",
    "cpu_functional_oracle_waiver_check.py",
)


def load(path):
    return json.loads(path.read_text())


def project(tmp_path):
    shutil.copytree(FIXTURE / "input", tmp_path / "input")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    for layer in LAYERS:
        shutil.copyfile(FIXTURE / "historical" / (layer + ".json"), docs / (layer + ".json"))
    return tmp_path


def gate(p):
    report = p / "gate.json"
    rc = subprocess.run([sys.executable, str(PROGRAMS / "l8_clock_period_actionability_check.py"),
                         str(p), "--json", str(report)], capture_output=True, text=True)
    return rc.returncode, load(report)




def test_exact_public_period_reaches_both_consumed_layers(tmp_path):
    p = project(tmp_path)
    assert producer.main([str(p), "--apply"]) == 0
    phase1._purge_aid_scaffold_residue(p)
    for layer in LAYERS:
        d = load(p / "phase1/generated_docs" / (layer + ".json"))
        clock = next(c for c in d["clock_domains"] if c["name"] == "clk")
        assert clock["period_ns"] == 10.0
        assert clock["freq_evidence"]["file"] == "input/docs/L9_constraints_floorplan.md"
        assert clock["freq_evidence"]["line"] == 4
    assert gate(p)[0] == 0
    assert not list(p.rglob("*.sdc"))
    assert not (p / "reports/audit/ai_judgements").exists()


@pytest.mark.parametrize("statement", [
    "The clock period is 10 ns.",  # no clock named
    "clk: the clock period is not 10 ns.",
    "clk: the clock period is 10 ns but this is no longer used.",
    "clk: the clock period is 10-20 ns.",
    "clk: the clock period is 10 ns or 20 ns.",
    "clk: the clock period is 10 ns to 20 ns.",
    "clk: the clock period is 10 ns; max 20 ns.",
    "clk: setup time is 10 ns.",
    "clk: the clock period is 0 ns.",
    "clk: the clock period is 10 ns. The clock period is 20 ns.",
    "clk: the clock period is 10 ns.\nclk: the clock period is 20 ns.\nclk: the clock period is 10 ns.",
])
def test_missing_denied_or_ambiguous_period_stays_unresolved(tmp_path, statement):
    p = project(tmp_path)
    (p / "input/docs/L9_constraints_floorplan.md").write_text(statement)
    assert producer.main([str(p), "--apply"]) == 0
    assert gate(p)[0] == 1
    for layer in LAYERS:
        assert load(p / "phase1/generated_docs" / (layer + ".json"))["clock_domains"][0]["period_ns"] is None


@pytest.mark.parametrize("value,unit,expected", [(7400, "ps", 7.4), (0.025, "us", 25.0), (12.8, "ns", 12.8)])
def test_period_binding_is_not_a_fixed_ten_ns_default(tmp_path, value, unit, expected):
    p = project(tmp_path)
    (p / "input/docs/L9_constraints_floorplan.md").write_text(f"clk: the clock period is {value} {unit}.")
    producer.main([str(p), "--apply"])
    for layer in LAYERS:
        assert load(p / "phase1/generated_docs" / (layer + ".json"))["clock_domains"][0]["period_ns"] == expected
    assert gate(p)[0] == 0


def test_resolved_clock_is_never_overwritten(tmp_path):
    p = project(tmp_path)
    for layer in LAYERS:
        path = p / "phase1/generated_docs" / (layer + ".json")
        d = load(path)
        for clock in d.get("clock_domains", []) + d.get("clocks", []):
            clock.update(period_ns=25.0, freq_mhz=40.0, freq_hz=40000000)
        path.write_text(json.dumps(d))
    producer.main([str(p), "--apply"])
    for layer in LAYERS:
        assert load(p / "phase1/generated_docs" / (layer + ".json"))["clock_domains"][0]["period_ns"] == 25.0
