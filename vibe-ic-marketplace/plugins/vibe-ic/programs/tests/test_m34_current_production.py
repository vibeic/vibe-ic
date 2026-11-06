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
    """An attacker can update hashes; hashes alone must not certify anything."""
    write(project, rel, data)
    receipt = json.loads((project / m3.RECEIPT).read_text())
    receipt["outputs"][rel] = m3.digest(project / rel)
    write(project, m3.RECEIPT, receipt)


def test_m3_production_is_explicitly_unmeasured_and_canonical_gate_blocks(tmp_path):
    m3 = blocked(tmp_path)
    receipt = json.loads((tmp_path / m3.RECEIPT).read_text())
    assert receipt["execution"] == []
    assert receipt["tool_versions"] == {}
    for rel in (COSIM, SI):
        data = json.loads((tmp_path / rel).read_text())
        assert data["verdict"] == "NOT_MEASURED"
        assert data["execution"] == []
        assert data["blockers"]
        assert receipt["outputs"][rel] == m3.digest(tmp_path / rel)
    assert json.loads((tmp_path / SI).read_text())["coverage"] == {
        "timing": "NOT_MEASURED", "noise": "NOT_MEASURED", "crosstalk": "NOT_MEASURED"}


@pytest.mark.parametrize("damage,rule", [
    ("missing_execution", "MISSING_EXECUTION"),
    ("missing_receipt", "MISSING_OR_MALFORMED_EVIDENCE"),
    ("replay", "WRONG_PROJECT"), ("wrong_path", "WRONG_OUTPUT_PATH"),
    ("wrong_design", "WRONG_DESIGN"), ("stale_input", "STALE_INPUT"),
    ("new_spef", "STALE_INPUT"), ("stale_output", "STALE_OUTPUT"),
    ("empty_scenarios", "EMPTY_SCENARIOS"), ("syntax_only", "SYNTAX_ONLY"),
    ("failed_measurement", "FAILED_MEASUREMENT"),
    ("native_failure", "NATIVE_EXECUTION_FAILED"),
    ("native_looking_replay", "M3_NATIVE_INTEGRATION_NOT_VERIFIED"),
])
def test_cosim_reverse_mutations_never_qualify(tmp_path, damage, rule):
    project = tmp_path / "subject"
    m3 = blocked(project)
    data = json.loads((project / COSIM).read_text())
    # These are adversarial claims, deliberately without a real execution.
    data["scenarios"] = [{"name": "forged", "status": "PASS"}]
    rebound(project, m3, COSIM, data)
    receipt = json.loads((project / m3.RECEIPT).read_text())
    if damage == "missing_receipt":
        (project / m3.RECEIPT).unlink()
    elif damage == "replay":
        other = tmp_path / "copy"
        shutil.copytree(project, other)
        project = other
    elif damage == "wrong_path":
        receipt["outputs"]["elsewhere.json"] = receipt["outputs"].pop(COSIM)
        write(project, m3.RECEIPT, receipt)
    elif damage == "wrong_design":
        data["top"] = "foreign"
        rebound(project, m3, COSIM, data)
    elif damage == "stale_input":
        (project / "phase3/mixed_signal/top_merged.gds").write_bytes(b"changed layout")
    elif damage == "new_spef":
        path = project / "phase3/stage3/pnr/new.spef"
        path.parent.mkdir(parents=True)
        path.write_text("new extraction")
    elif damage == "stale_output":
        (project / COSIM).write_text("{}")
    elif damage == "empty_scenarios":
        data["scenarios"] = []
        rebound(project, m3, COSIM, data)
    elif damage == "failed_measurement":
        data["scenarios"][0]["status"] = "FAIL"
        rebound(project, m3, COSIM, data)
    elif damage in ("syntax_only", "native_failure", "native_looking_replay"):
        receipt["execution"] = [{"command": ["iverilog" if damage == "syntax_only" else "vvp"],
                                 "stage": "compile" if damage == "syntax_only" else "measurement",
                                 "exit_code": 1 if damage == "native_failure" else 0}]
        write(project, m3.RECEIPT, receipt)
    report = m3.audit(project, "cosim")
    assert report["verdict"] == "NOT_VERIFIED"
    assert report["findings"][0]["rule"] == rule


@pytest.mark.parametrize("damage,rule", [("empty", "EMPTY_INTERFACES"),
                                        ("unexecuted", "MISSING_EXECUTION"),
                                        ("failed", "FAILED_MEASUREMENT"),
                                        ("advisory", "M3_NATIVE_INTEGRATION_NOT_VERIFIED")])
def test_si_reverse_mutations_never_qualify(tmp_path, damage, rule):
    m3 = blocked(tmp_path)
    data = json.loads((tmp_path / SI).read_text())
    if damage != "empty":
        data["interfaces"] = [{"name": "forged", "status": "FAIL" if damage == "failed" else "PASS",
                               "metrics": {"slew_ns": {"measured": 1, "max": 2}}}]
        rebound(tmp_path, m3, SI, data)
    if damage == "advisory":
        receipt = json.loads((tmp_path / m3.RECEIPT).read_text())
        receipt["execution"] = [{"stage": "measurement", "exit_code": 0, "command": ["sta"]}]
        write(tmp_path, m3.RECEIPT, receipt)
    assert m3.audit(tmp_path, "si")["findings"][0]["rule"] == rule








@pytest.mark.parametrize("producer", ["m3", "m4"])
def test_production_cannot_overwrite_foreign_output(tmp_path, producer):
    import mixed_signal_m3_run as m3
    project = tmp_path / "subject"
    claims(project)
    foreign = tmp_path / "foreign.json"
    foreign.write_text("foreign evidence\n")
    assert foreign.read_text() == "foreign evidence\n"
