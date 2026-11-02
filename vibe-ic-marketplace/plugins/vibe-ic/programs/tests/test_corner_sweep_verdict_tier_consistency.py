"""A real failing sweep must publish one consistent verdict through every seam.

The minimal native fixture retains the original counts, failed corner IDs,
values and statuses. Other fixtures are neutral inputs, not native evidence.
"""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import pytest
import analog_corner_sweep_check as checker


FIXTURE = Path(__file__).parent / "fixtures/corner_sweep_verdict/native_spec_failure.json"


def stage(project, data, block="block_a"):
    path = project / "phase3/analog" / block / "corner_results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if data is not None else "{")


def passing():
    return {"total_corners": 9, "results_found": 9,
            "design_content": "structure_and_geometry",
            "corners": [{"name": f"point_{i}", "simulator_run": True} for i in range(9)],
            "spec_results": [{"spec": "quantity", "status": "PASS"}]}


def verdict(report):
    return report["passed"], report["summary"]["pass"], report["summary"]["verdict_tier"]


def test_native_failed_input_json_never_claims_a_pass_tier(tmp_path):
    data = json.loads(FIXTURE.read_text())
    stage(tmp_path, data)
    report = tmp_path / "report.json"
    run = subprocess.run([sys.executable, checker.__file__, str(tmp_path), "--json", str(report)], capture_output=True, text=True)
    body = json.loads(report.read_text())
    assert run.returncode == 1
    assert verdict(body) == (False, False, "FAIL")
    assert body["summary"]["details"][0]["total_corners"] == 243
    assert len(body["findings"]) == len(data["spec_results"]) == 2
    assert all(f["rule"] == "SPEC_FAIL_AT_CORNER" for f in body["findings"])
    assert all(any(row["corner"] in f["message"] for f in body["findings"]) for row in data["spec_results"])


@pytest.mark.parametrize("failure", ["parse", "coverage", "missing", "all_derived", "spec", "yield", "subject"])
def test_every_evaluated_failure_uses_the_same_failed_outcome(tmp_path, failure):
    data = passing()
    if failure == "parse":
        data = None
    elif failure == "coverage":
        data.update(total_corners=8, results_found=8)
    elif failure == "missing":
        data["results_found"] = 8
    elif failure == "all_derived":
        for row in data["corners"]:
            row["simulator_run"] = False
    elif failure == "spec":
        data = json.loads(FIXTURE.read_text())
    elif failure == "yield":
        data["mc_yield_pct"] = 94.9
    elif failure == "subject":
        del data["design_content"]
    stage(tmp_path, data)
    body = asdict(checker.run_audit(tmp_path))
    assert verdict(body) == (False, False, "FAIL")
    assert any(f["severity"] == "ERROR" for f in body["findings"])


@pytest.mark.parametrize("tier", ["PASS", "PASS_WITH_STUB", "PASS_WITH_STUB_PARTIAL", "PASS_STRUCTURE_ONLY", "PASS_WITH_DERIVED_CORNERS"])
def test_existing_success_tiers_keep_their_meaning(tmp_path, tier):
    data = passing()
    stub = {"extraction_strategy": "deterministic_stub"}
    if tier == "PASS_WITH_STUB":
        data = stub
    elif tier == "PASS_WITH_STUB_PARTIAL":
        stage(tmp_path, stub, "stub_block")
    elif tier == "PASS_STRUCTURE_ONLY":
        data["design_content"] = "structure_only"
    elif tier == "PASS_WITH_DERIVED_CORNERS":
        for row in data["corners"][1:]:
            row["simulator_run"] = False
    stage(tmp_path, data)
    assert verdict(asdict(checker.run_audit(tmp_path))) == (True, True, tier)


@pytest.mark.parametrize("success_kind", ["stub", "structure_only", "derived"])
def test_a_successful_block_cannot_mask_another_blocks_failure(tmp_path, success_kind):
    data = passing()
    if success_kind == "stub":
        data = {"extraction_strategy": "deterministic_stub"}
    elif success_kind == "structure_only":
        data["design_content"] = "structure_only"
    else:
        for row in data["corners"][1:]:
            row["simulator_run"] = False
    stage(tmp_path, data, "successful_block")
    stage(tmp_path, json.loads(FIXTURE.read_text()), "failed_block")
    assert verdict(asdict(checker.run_audit(tmp_path))) == (False, False, "FAIL")


@pytest.mark.parametrize("outcome", ["failed", "passing", "absent_input"])
def test_canonical_json_consumer_preserves_the_outcome(tmp_path, monkeypatch, outcome):
    import flow_compliance_check as flow
    monkeypatch.setattr(flow, "_GATE_LEDGER", [])
    if outcome == "failed":
        stage(tmp_path, json.loads(FIXTURE.read_text()))
    elif outcome == "passing":
        stage(tmp_path, passing())
    command = "analog_corner_sweep_check . --json reports/gates/corners.json"
    ok, _ = flow._check_program_exit_zero(tmp_path, command)
    row = flow._GATE_LEDGER[-1]
    report = json.loads((tmp_path / "reports/gates/corners.json").read_text())
    if outcome == "absent_input":
        assert row["verdict"] == "BLOCKED"
        assert row["rc"] == 2
        assert report["summary"]["skipped"] is True
        assert "verdict_tier" not in report["summary"]
    else:
        passed = outcome == "passing"
        assert ok is passed
        assert row["verdict"] == ("PASS" if passed else "FAIL")
        assert row["rc"] == (0 if passed else 1)
        assert verdict(report) == (passed, passed, row["verdict"])


@pytest.mark.parametrize("tier", ["NOT_MEASURED", "NOT_APPLICABLE", "ENV_UNAVAILABLE", "INCOMPLETE", "FAIL"])
def test_frontdoor_nonpass_status_mapping_is_unchanged(tier):
    import analog_one_shot_runner as runner
    assert runner.verdict_tier(tier) == tier
