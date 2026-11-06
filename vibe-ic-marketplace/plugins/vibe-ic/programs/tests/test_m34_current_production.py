"""Canonical M3/M4 controls. Claimed green data below is adversarial only.

No fixture in this module qualifies a simulation or a tapeout as READY.
"""
import json
import shutil
from pathlib import Path

import pytest
import yaml
from _hostpaths import require_repo

PROGRAMS = Path(__file__).resolve().parents[1]
DIR = "reports/analog/mixed_signal"
COSIM = "phase3/mixed_signal/cosim/mixed_signal_results.json"
SI = DIR + "/interface_si.json"


def write(project, rel, value):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def step(name):
    canonical = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
                             "phase1_phase2_phase3.yaml")
    return next(s for s in yaml.safe_load(canonical.read_text())["steps"] if s["id"] == name)


def claims(project):
    write(project, "phase1/analog/analog_block_list.json", {"blocks": ["boundary"]})
    gds = project / "phase3/mixed_signal/top_merged.gds"
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_bytes(b"unverified layout, never signoff evidence")
    write(project, COSIM, {"all_scenarios_passed": True,
                          "scenarios": [{"name": "startup", "status": "PASS"}]})
    write(project, SI, {"all_interfaces_clean": True, "interfaces": [
        {"name": "boundary", "metrics": {"slew_ns": {"measured": 1, "max": 2}}}]})


def blocked(project):
    """Native execution is absent; this is only a refusal/replay subject."""
    import mixed_signal_m3_run as m3
    claims(project)
    assert m3.main([str(project), "--top", "boundary"]) == 2
    return m3


def rebound(project, m3, rel, data):
    write(project, rel, data)


def test_m3_production_is_explicitly_unmeasured_and_canonical_gate_blocks(tmp_path):
    m3 = blocked(tmp_path)
    receipt = json.loads((tmp_path / m3.RECEIPT).read_text())
    assert receipt["execution"] == []
    for rel in (COSIM, SI):
        data = json.loads((tmp_path / rel).read_text())
        assert data["verdict"] == "NOT_MEASURED"
        assert data["execution"] == []
        assert data["blockers"]
    assert json.loads((tmp_path / SI).read_text())["coverage"] == {
        "timing": "NOT_MEASURED", "noise": "NOT_MEASURED", "crosstalk": "NOT_MEASURED"}


@pytest.mark.parametrize("damage,rule", [
    ("missing_execution", "MISSING_EXECUTION"),
    ("empty_scenarios", "EMPTY_SCENARIOS"),
    ("failed_measurement", "FAILED_MEASUREMENT"),
])
def test_cosim_reverse_mutations_never_qualify(tmp_path, damage, rule):
    project = tmp_path / "subject"
    m3 = blocked(project)
    data = json.loads((project / COSIM).read_text())
    # These are adversarial claims, deliberately without a real execution.
    data["scenarios"] = [{"name": "forged", "status": "PASS"}]
    rebound(project, m3, COSIM, data)
    if damage == "empty_scenarios":
        data["scenarios"] = []
        rebound(project, m3, COSIM, data)
    elif damage == "failed_measurement":
        data["scenarios"][0]["status"] = "FAIL"
        rebound(project, m3, COSIM, data)
    report = m3.audit(project, "cosim")
    assert report["verdict"] == "NOT_VERIFIED"
    assert report["findings"][0]["rule"] == rule


@pytest.mark.parametrize("damage,rule", [("empty", "EMPTY_INTERFACES"),
                                        ("unexecuted", "MISSING_EXECUTION"),
                                        ("failed", "FAILED_MEASUREMENT")])
def test_si_reverse_mutations_never_qualify(tmp_path, damage, rule):
    m3 = blocked(tmp_path)
    data = json.loads((tmp_path / SI).read_text())
    if damage != "empty":
        data["interfaces"] = [{"name": "forged", "status": "FAIL" if damage == "failed" else "PASS",
                               "metrics": {"slew_ns": {"measured": 1, "max": 2}}}]
        rebound(tmp_path, m3, SI, data)
    assert m3.audit(tmp_path, "si")["findings"][0]["rule"] == rule
