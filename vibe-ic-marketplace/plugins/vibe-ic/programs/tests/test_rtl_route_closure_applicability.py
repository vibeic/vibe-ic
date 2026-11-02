"""Neutral fixture controls for joined RTL applicability, not native acceptance."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess

import pytest

import benchmark_dispatch as dispatch
import flow109
import route_decision as rd
import task_nature_route as tnr


PROMPT = "Debug the supplied two input AND gate whose output is inverted. Return RTL.\n"
PROGRAMS = Path(__file__).resolve().parents[1]


def _receipt(nature="debug", evidence="existence", target="rtl"):
    return tnr.route_decision_receipt(
        PROMPT, nature=nature, requested_evidence=evidence, delivery_target=target)


def _rehash(receipt):
    receipt["receipt_sha256"] = rd.sha256_json(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"})
    return receipt


@pytest.mark.parametrize("nature", list(tnr.NATURE_ENTRY))
@pytest.mark.parametrize("evidence", ["existence", "lint_validated", "behaviour", "proof"])
def test_validated_join_preserves_requested_evidence_and_rtl_delivery(nature, evidence):
    receipt = _receipt(nature, evidence)
    before = copy.deepcopy(receipt)
    assert rd.validate_route_receipt(receipt) == []
    expected = None if nature == "debug" and evidence == "proof" else "rtl"
    assert dispatch._rtl_delivery_target(receipt) == expected
    assert receipt == before


@pytest.mark.parametrize("evidence", ["area", "equivalence", "timing", "manufacturability", "power", "silicon"])
def test_nonrtl_requested_evidence_retains_physical_admission(evidence):
    assert dispatch._rtl_delivery_target(_receipt(nature="spec_generation", evidence=evidence)) is None


@pytest.mark.parametrize("target", ["gds", "shippable_gds", "ip_hardmacro", "foundry_handoff"])
def test_physical_delivery_retains_physical_admission(target):
    assert dispatch._rtl_delivery_target(_receipt(nature="spec_generation", target=target)) is None


@pytest.mark.parametrize("change", [
    {"verify_closed_steps": ["1", "2", "4", "9"]},
    {"verify_closed_steps": ["1", "2", "4"]},
    {"verify_through": "5"},
    {"verify_through": "3"},
    {"minimum_steps": ["1", "1", "1"]},
    {"task_nature": "unsupported"},
    {"requested_evidence": "unsupported"},
    {"input_contract": "original"},
    {"schema": "unsupported"},
    {"derivation_rules_version": "stale"},
    {"dag_sha256": "0" * 64},
])
def test_rehashed_malformed_receipt_cannot_acquire_rtl_scope(change):
    receipt = _receipt(evidence="behaviour")
    receipt.update(change)
    _rehash(receipt)
    assert rd.validate_route_receipt(receipt)
    assert dispatch._rtl_delivery_target(receipt) is None


def test_changed_receipt_digest_cannot_acquire_rtl_scope():
    receipt = _receipt(evidence="behaviour")
    receipt["source_sha256"] = "0" * 64
    assert dispatch._rtl_delivery_target(receipt) is None


def test_exact_evidence_exit_identity_stays_strict():
    assert not tnr.is_rtl_only_evidence("existence", exit_step="4")
    assert tnr.is_rtl_only_evidence("behaviour", exit_step="4")
    assert not tnr.is_rtl_only_evidence(exit_step="3")
    assert not tnr.is_rtl_only_evidence(exit_step="6")


def _project(project):
    source = project / "input"
    (source / "rtl").mkdir(parents=True)
    (source / "phase1_prompt.md").write_text(PROMPT)
    (source / "rtl/unit.v").write_text(
        "module unit(input a, input b, output y); assign y=~(a&b); endmodule\n")
    (source / "step_0_5ic_answers.json").write_text(json.dumps({
        "schema": "vibe-ic/step_0_5ic_answers/1",
        "answers": {"deliverable": "HARDMACRO"},
        "answer_provenance": {"deliverable": {
            "answered_by": "owner", "citation": "Earlier retained fixture delivery declaration."}},
    }))
    profile = next(row for row in flow109.load_registry()["reference_profiles"]
                   if row["name"] == "RTL-only")
    (source / "flow109-manifest.json").write_text(json.dumps({"features": profile["features"]}))


def test_public_d1_argv_accepts_joined_rtl_scope_without_acceptance_credit(tmp_path):
    _project(tmp_path)
    inputs = {path.relative_to(tmp_path): path.read_bytes()
              for path in (tmp_path / "input").rglob("*") if path.is_file()}
    receipt = _receipt()
    argv = dispatch._solver_argv(
        PROGRAMS / "vibe_ic_one_shot_runner.py", tmp_path, "D1", "D1",
        delivery_target=dispatch._rtl_delivery_target(receipt))
    assert "--delivery-target" in argv
    assert argv[argv.index("--entry-step") + 1] == "D01"
    assert argv[argv.index("--exit-step") + 1] == "D01"
    observed = subprocess.run(argv + ["--flow109-plan-only"],
                              capture_output=True, text=True, timeout=60)
    assert observed.returncode == 0, observed.stdout + observed.stderr
    assert "runtime NOT_MEASURED" in observed.stdout
    plan = json.loads((tmp_path / "reports/flow109/plan.json").read_bytes())
    assert plan["features"]["physical"] is False
    assert not (tmp_path / "reports/flow109/requests").exists()
    assert all((tmp_path / path).read_bytes() == raw for path, raw in inputs.items())
    assert not (tmp_path / "reports/phase1/submission_scope.json").exists()
    assert not (tmp_path / "reports/orchestrator/phase1_one_shot.json").exists()


@pytest.mark.parametrize("conflict", ["hard_ip", "has_analog", "technology_specific",
                                      "runtime_tool_uses", "qualification_registry", "ic"])
def test_public_scope_retains_native_exclusions(tmp_path, conflict):
    _project(tmp_path)
    argv = dispatch._solver_argv(
        PROGRAMS / "vibe_ic_one_shot_runner.py", tmp_path, "D1", "D1",
        delivery_target=dispatch._rtl_delivery_target(_receipt(evidence="behaviour")))
    manifest_path = tmp_path / "input/flow109-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    definitions = flow109.load_registry()["predicate_definitions"]
    manifest["features"] = {key: value for key, value in manifest["features"].items()
                            if key not in definitions}
    if conflict == "hard_ip":
        manifest["features"].update(rtl_only=False, hard_ip=True,
                                    digital_netlist=True, technology_specific=True)
    elif conflict == "has_analog":
        manifest["features"].update(has_analog=True, technology_specific=True)
    elif conflict == "technology_specific":
        manifest["features"]["technology_specific"] = True
    elif conflict == "runtime_tool_uses":
        manifest[conflict] = []
    elif conflict == "qualification_registry":
        manifest[conflict] = "qualification.json"
    elif conflict == "ic":
        argv[argv.index("--route") + 1] = "ic"
    manifest_path.write_text(json.dumps(manifest))
    before = {path: path.read_bytes() for path in (tmp_path / "input").rglob("*")
              if path.is_file()}
    observed = subprocess.run(argv + ["--flow109-plan-only"],
                              capture_output=True, text=True, timeout=60)
    assert observed.returncode == 2, observed.stdout + observed.stderr
    assert "FLOW109_RTL_SCOPE_CONFLICT" in observed.stderr
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert not (tmp_path / "reports/phase1/submission_scope.json").exists()
