"""Canonical M3/M4 controls. Claimed green data below is adversarial only.

No fixture in this module qualifies a simulation or a tapeout as READY.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
import flow_compliance_check as flow
from _hostpaths import require_repo
from programs.tests.test_execution_receipt_chain import isolated_transport, real_entry

PROGRAMS = Path(__file__).resolve().parents[1]
FLOW = PROGRAMS.parent / "flow/phase1_phase2_phase3.yaml"
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


def test_unexecuted_m3_report_cannot_pass_canonical_gate(tmp_path):
    claims(tmp_path)
    assert flow.check_step(tmp_path, step("M3"), {}).status == "FAIL"


def test_owner_claim_cannot_pass_m4_gate(tmp_path):
    claims(tmp_path)
    for name, value in (("merge", {"verdict": "PASS"}),
                        ("power_domain", {"all_crossings_protected": True}),
                        ("level_shifter", {"all_required_inserted": True}),
                        ("isolation", {"all_required_inserted": True}),
                        ("signoff", {"ready_for_tapeout": True})):
        write(tmp_path, f"{DIR}/{name}.json", value)
    assert flow.check_step(tmp_path, step("M4"), {}).status == "FAIL"


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
    assert flow.check_step(tmp_path, step("M3"), {}).status == "FAIL"


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


def test_m4_derives_false_without_reading_owner_assertion(tmp_path):
    import mixed_signal_signoff_run as m4
    blocked(tmp_path)
    write(tmp_path, m4.OUTPUT, {"ready_for_tapeout": True})
    assert m4.main([str(tmp_path), "--top", "boundary"]) == 2
    data = json.loads((tmp_path / m4.OUTPUT).read_text())
    assert data == m4.derive(tmp_path, "boundary")
    assert data["ready_for_tapeout"] is False
    assert data["verdict"] == "NOT_READY"
    assert all(c["verdict"] != "PASS" for c in data["checks"])
    assert {c["step"] for c in data["checks"]} == {
        "M1", "M2", "M3_cosim", "M3_si", "PV_drc", "PV_lvs", "PV_antenna", "PV_density"}
    assert flow.check_step(tmp_path, step("M4"), {}).status == "FAIL"


@pytest.mark.parametrize("damage", ["assert_ready", "stale_upstream", "failed_upstream",
                                   "unmeasured_upstream", "missing_upstream", "malformed_upstream",
                                   "wrong_design", "replay"])
def test_m4_reverse_mutations_never_qualify(tmp_path, damage):
    import mixed_signal_signoff_run as m4
    project = tmp_path / "subject"
    blocked(project)
    assert m4.main([str(project), "--top", "boundary"]) == 2
    data = json.loads((project / m4.OUTPUT).read_text())
    if damage == "assert_ready":
        data["ready_for_tapeout"] = True
        data["verdict"] = "PASS"
        write(project, m4.OUTPUT, data)
    elif damage == "stale_upstream":
        (project / COSIM).write_text((project / COSIM).read_text() + "\n")
    elif damage in ("failed_upstream", "unmeasured_upstream"):
        write(project, DIR + "/merge.json", {"verdict": "FAIL" if damage == "failed_upstream" else "NOT_MEASURED"})
    elif damage == "missing_upstream":
        (project / SI).unlink()
    elif damage == "malformed_upstream":
        (project / SI).write_text("{broken")
    elif damage == "wrong_design":
        data["top"] = "foreign"
        write(project, m4.OUTPUT, data)
    elif damage == "replay":
        other = tmp_path / "copy"
        shutil.copytree(project, other)
        project = other
    report = m4.audit(project)
    assert report["ready_for_tapeout"] is False
    assert report["verdict"] == "NOT_VERIFIED"
    expected = ("WRONG_DESIGN" if damage == "wrong_design" else
                "WRONG_PRODUCER_OR_PROJECT" if damage == "replay" else
                "STALE_OR_MISMATCHED_SIGNOFF")
    assert report["findings"][0]["rule"] == expected


@pytest.mark.parametrize("kind", ["cosim", "si", "signoff"])
def test_strict_audit_cannot_create_or_overwrite_evidence(tmp_path, kind):
    import mixed_signal_m3_run as m3
    import mixed_signal_signoff_run as m4
    import mixed_signal_cosim_check as cosim
    import mixed_signal_interface_si_check as si
    import mixed_signal_signoff_check as signoff
    gate = {"cosim": cosim, "si": si, "signoff": signoff}[kind]
    protected = {"cosim": COSIM, "si": SI, "signoff": m4.OUTPUT}[kind]
    assert gate.main([str(tmp_path), "--require-current-production"]) == 1
    assert not (tmp_path / protected).exists()
    blocked(tmp_path)
    if kind == "signoff":
        assert m4.main([str(tmp_path), "--top", "boundary"]) == 2
    before = (tmp_path / protected).read_bytes()
    alias = tmp_path / "audit_alias.json"
    alias.symlink_to(tmp_path / protected)
    assert gate.main([str(tmp_path), "--require-current-production", "--json", str(alias)]) == 1
    assert (tmp_path / protected).read_bytes() == before


@pytest.mark.parametrize("producer", ["m3", "m4"])
def test_production_cannot_overwrite_foreign_output(tmp_path, producer):
    import mixed_signal_m3_run as m3
    import mixed_signal_signoff_run as m4
    project = tmp_path / "subject"
    claims(project)
    foreign = tmp_path / "foreign.json"
    foreign.write_text("foreign evidence\n")
    path = project / (m3.COSIM if producer == "m3" else m4.OUTPUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.symlink_to(foreign)
    program = m3 if producer == "m3" else m4
    assert program.main([str(project), "--top", "boundary"]) == 1
    assert foreign.read_text() == "foreign evidence\n"


def test_fixed_runner_stops_after_genuine_unmeasured_m3(tmp_path, monkeypatch):
    import mixed_signal_m3_run as m3
    import mixed_signal_cosim_check as cosim
    import mixed_signal_interface_si_check as si
    import mixed_signal_power_domain_run as m2
    import vibe_ic_one_shot_runner as runner
    project = tmp_path / "subject"
    shutil.copytree(PROGRAMS / "tests/fixtures/m2_placed", project)
    analog = project / "phase3/analog/analog_block_list.json"
    analog.parent.mkdir(parents=True)
    shutil.copyfile(project / "phase1/analog/analog_block_list.json", analog)
    real_entry('IC', 'default', project)
    rtl = project / "phase2/stage1/rtl/boundary.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module boundary(); endmodule\n")
    calls = []
    real = {"mixed_signal_power_domain_run": m2, "mixed_signal_m3_run": m3,
            "mixed_signal_cosim_check": cosim, "mixed_signal_interface_si_check": si}
    def bounded(label, program, args, env=None):
        name = Path(program).stem
        calls.append(name)
        if name in real:
            # Native M2 runs unchanged; M3 performs honest unmeasured production.
            args = list(args)
            if "--container" in args:
                args[args.index("--container") + 1] = "host"
            return real[name].main(args)
        return 0
    # This fixture exercises the fixed sequence and real downstream consumers.
    # Keep its subprocess seam explicit now that Default also has a Controller.
    monkeypatch.setattr(runner, "_controller_mixed_step", lambda *_args: None)
    monkeypatch.setattr(runner, "_run_phase", bounded)
    monkeypatch.setattr(sys, "argv", ["runner", str(project), "--top", "boundary",
                                     "--route", "ic", "--skip-phase1", "--no-dashboard"])
    runner.main()
    report = json.loads((project / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    phases = {row["name"]: row for row in report["phases"]}
    assert phases["mixed_signal_M2"]["verdict"] == "PASS"
    assert phases["mixed_signal_M3"]["verdict"] == "NOT_READY"
    assert phases["mixed_signal_M4"]["verdict"] == "NOT_READY"
    assert calls.count("mixed_signal_m3_run") == 1
    assert calls.count("mixed_signal_cosim_check") == 1
    assert calls.count("mixed_signal_interface_si_check") == 1
    assert "mixed_signal_signoff_run" not in calls


@pytest.mark.parametrize("fault", ["m2_failed", "missing", "malformed", "stale"])
def test_fixed_runner_cannot_borrow_m3_readiness(tmp_path, monkeypatch, fault):
    import mixed_signal_power_domain_run as m2
    import vibe_ic_one_shot_runner as runner
    project = tmp_path / "subject"
    shutil.copytree(PROGRAMS / "tests/fixtures/m2_placed", project)
    analog = project / "phase3/analog/analog_block_list.json"
    analog.parent.mkdir(parents=True)
    shutil.copyfile(project / "phase1/analog/analog_block_list.json", analog)
    real_entry('IC', 'default', project)
    # M2 is a genuine neutral native prerequisite. Any M3 PASS below remains
    # hostile metadata; the real strict gates must reject its absent evidence.
    stale = project / DIR / "m3_producer_audit.json"
    if fault == "stale":
        write(project, str(stale.relative_to(project)),
              {"program": "mixed_signal_m3_run", "verdict": "PASS"})
    calls = []
    def bounded(label, program, args, env=None):
        name = Path(program).stem
        calls.append(name)
        if name == "mixed_signal_power_domain_run":
            if fault == "m2_failed":
                return 1
            args = list(args)
            args[args.index("--container") + 1] = "host"
            return m2.main(args)
        if name == "mixed_signal_m3_run" and fault == "malformed":
            stale.write_text("{broken")
        if name in ("mixed_signal_cosim_check", "mixed_signal_interface_si_check"):
            module = __import__(name)
            return module.main(args)
        return 0
    # This fixture exercises the fixed sequence and real downstream consumers.
    # Keep its subprocess seam explicit now that Default also has a Controller.
    monkeypatch.setattr(runner, "_controller_mixed_step", lambda *_args: None)
    monkeypatch.setattr(runner, "_run_phase", bounded)
    monkeypatch.setattr(sys, "argv", ["runner", str(project), "--top", "boundary",
                                     "--route", "ic", "--skip-phase1", "--no-dashboard"])
    runner.main()
    report = json.loads((project / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    phases = {row["name"]: row for row in report["phases"]}
    assert phases["mixed_signal_M2"]["verdict"] == ("FAIL" if fault == "m2_failed" else "PASS")
    if fault != "m2_failed":
        assert m2.verify(project)["tool"]["exit_code"] == 0
    assert phases["mixed_signal_M3"]["verdict"] == ("NOT_READY" if fault == "m2_failed" else "FAIL")
    assert phases["mixed_signal_M4"]["verdict"] == "NOT_READY"
    assert "mixed_signal_signoff_run" not in calls
    if fault == "m2_failed":
        assert "mixed_signal_m3_run" not in calls
