"""D66 binding to the existing Step-28 owner; no commercial PERC claim."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "flow/flow109.json"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _put(project, rel, value):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return {"path": rel, "sha256": _sha(path)}


def _summary(*, automated_fail=False, omit_manual=None):
    manual = [
        "ESD protection presence",
        "io_supply_pad_sufficiency",
        "Latch-up / well-tap (spacing + device-physics)",
    ]
    if omit_manual:
        manual.remove(omit_manual)
    categories = [{"category": "Antenna", "status": "AUTOMATED",
                   "result": "FAIL" if automated_fail else "PASS"}]
    for name in manual:
        row = {"category": name, "status": "MANUAL_REVIEW",
               "result": "MANUAL_REVIEW"}
        if name == "ESD protection presence":
            row["library_sources"] = [{"path": "/foss/pdk/io.cdl", "sha256": "a" * 64}]
        categories.append(row)
    return {
        "verdict": "PERC_EQUIV_FAIL" if automated_fail else "PERC_EQUIV_PASS",
        "commercial_calibre_perc_run": False,
        "automated_failed": ["Antenna"] if automated_fail else [],
        "automated_incomplete": [],
        "manual_review_pending": manual,
        "categories": categories,
        "geometry_foundry_data_residual":
            "Foundry-calibrated ESD and substrate device physics are unavailable.",
    }


def _canonical_d65(project, geometry_def, *, damage=None):
    routed = project / "phase3/stage3/pnr/routed.def"
    routed.write_bytes((project / geometry_def["path"]).read_bytes())
    outputs = {
        ref["path"]: ref["sha256"] for ref in (
            _put(project, "reports/phase3/drc_signoff.json", {"status": "PASS"}),
            _put(project, "reports/phase3/lvs.json", {"status": "PASS"}),
        )
    }
    census = {
        "schema": "vibeic/current-step-producer-census/1", "step_id": "31",
        "verdict": "PRODUCED", "consumer_allowed": True, "authority_verdict": "PASS",
        "cross_invocation_reuse": False,
        "input_identity_scope": "row_manifest_and_native_siblings",
        "invalid_results": [], "unexecutable": [], "population": 1,
        "executed": 1, "documents_now_present": 1,
        "input_identity": {"source_sha": "sha256:" + "1" * 64,
                           "source_files": {"/source/producer.py": "2" * 64},
                           "files": {"phase3/stage3/pnr/routed.def": geometry_def["sha256"]}},
        "results": [{"step": "31", "rc": 0, "executed": True,
                     "target_exists_after": True, "target_content_valid": True,
                     "authorship": "producer", "target": "reports/phase3/drc_signoff.json",
                     "target_sha256": outputs["reports/phase3/drc_signoff.json"]}],
    }
    specs = [{"spec": path, "satisfied": True, "mode": "step_attributed",
              "code": "step_attributed"} for path in outputs]
    receipt = {
        "schema": "vibeic/backend-result/2", "step_id": "31", "verdict": "PASS",
        "producer_verdict": "PASS", "source_sha": "default-direct",
        "binding": {"step_id": "31", "source_sha": "default-direct",
                    "required_gates": ["backend_canonical", "backend_native_substance"]},
        "gates": {"backend_canonical": "PASS", "backend_native_substance": "PASS"},
        "gate_ledger": [{"gate": "synthetic_step31", "rc": 0, "verdict": "PASS"}],
        "current_step_declared_producers": census,
        "canonical_receipts": [{"schema": "vibeic/backend-producer-receipt/1",
                                "producer": "execution_backend_producers.produce",
                                "step_id": "31", "verdict": "PASS",
                                "current_step_declared_producers": census}],
        "canonical_step_result": {"id": 31, "status": "PASS", "output_binding": {
            "mode": "step_attributed", "source": "step_folder", "n_project_glob": 0,
            "n_specs": len(outputs), "n_satisfied": len(outputs),
            "n_step_attributed": len(outputs), "codes": ["step_attributed"],
            "notes": [], "specs": specs}},
        "outputs": outputs, "missing_outputs": [],
    }
    if damage == "wrong_step":
        receipt["step_id"] = "30"
    elif damage == "fail":
        receipt["verdict"] = "FAIL"
    elif damage == "missing_input_binding":
        del census["input_identity"]["files"]["phase3/stage3/pnr/routed.def"]
    elif damage == "project_glob":
        receipt["canonical_step_result"]["output_binding"]["n_project_glob"] = 1
    elif damage == "consumer_disallowed":
        census["consumer_allowed"] = False
    elif damage == "bare_pass":
        receipt = {"schema": "vibeic/backend-result/2", "step_id": "31", "verdict": "PASS"}
    return _put(project, "reports/phase3/default_steps/31/backend_result.json", receipt), outputs


def _case(project, monkeypatch, *, producer="PASS", gate="PASS",
          automated_fail=False, omit_manual=None, d65_kind="wrapper", d65_damage=None):
    import flow109_final_perc as perc

    top = "tiny_perc"
    subjects = {
        "geometry_def": _put(project, f"phase3/stage3/pnr/{top}.def",
                             "VERSION 5.8 ;\nDESIGN tiny_perc ;\nEND DESIGN\n"),
        "geometry_gds": _put(project, f"phase3/stage3/pnr/{top}.gds", "gds-bytes"),
        "adopted_netlist": _put(project, f"phase3/stage3/pnr/{top}_pnr.v",
                                "module tiny_perc; endmodule\n"),
        "extracted_netlist": _put(project, "phase3/stage3/extracted/tiny_perc.spice",
                                  ".subckt tiny_perc VDD VSS\n.ends\n"),
    }
    subjects["pad_supply_def"] = dict(subjects["geometry_def"])
    if d65_kind == "canonical":
        d65, d65_outputs = _canonical_d65(
            project, subjects["geometry_def"], damage=d65_damage)
    else:
        d65_native = _put(project, "reports/phase3/default_steps/31/backend_result.json", {
            "schema": "vibeic/backend-result/2", "step_id": "31", "verdict": "PASS"})
        d65 = _put(project, "reports/flow109/D65/component.json", {
            "schema": "vibeic.flow109.window-component.v1", "step_id": "D65",
            "native_step_id": "31", "component_status": "PASS",
            "flow109_acceptance": "NOT_MEASURED", "canonical_receipt": d65_native})
        d65_outputs = {}
    _put(project, perc.INPUT, {
        "schema": perc.SCHEMA, "d65_component": d65, "final_subjects": subjects,
        "backend": {"image_id": perc.EDA_IMAGE, "pdk_root": "/foss/pdks",
                    "pdk_name": "gf180mcuD", "top": top}})
    summary = _summary(automated_fail=automated_fail, omit_manual=omit_manual)
    calls = []

    def fake_produce(_project, params):
        calls.append(params)
        _put(project, perc.OUTPUTS[0], summary)
        _put(project, perc.OUTPUTS[1], "PERC equivalent control\n")
        _put(project, perc.OUTPUTS[2], "# Manual review remains open\n")
        _put(project, perc.OUTPUTS[3], {"status": gate})
        return {"verdict": producer, "canonical_receipts": [{
            "schema": "vibeic/backend-producer-receipt/1", "step_id": "28",
            "verdict": producer}]}

    monkeypatch.setattr(perc, "require_launch_admission", lambda *args, **kwargs: None)
    monkeypatch.setattr(perc, "_d65_geometry_current", lambda *args, **kwargs: None)
    monkeypatch.setattr(perc.backend_producers, "produce", fake_produce)
    monkeypatch.setattr(perc.backend_gates, "evaluate",
                        lambda project, row: {"status": gate, "step": row})
    context = {"requested_step": "D66", "native_step_id": "flow109.D66",
               "context_sha256": "b" * 64}
    return perc, context, subjects, calls, d65_outputs


def test_registry_uses_only_the_D66_existing_owner_adapter():
    import flow109

    registry = json.loads(REGISTRY.read_text())
    row = next(row for row in registry["rows"] if row["id"] == "D66")
    profile = row["profiles"][0]
    dispatch = profile["dispatch"]
    assert dispatch["adapter"] == "flow109_final_perc"
    assert dispatch["native_step_id"] == "flow109.D66"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert dispatch["flow109_metrics_status"] == "UNIMPLEMENTED_MANUAL_REVIEW_PENDING"
    assert dispatch["producer"] == "execution_backend_producers.py:produce"
    assert dispatch["consumer"] == "execution_backend_gates.py:evaluate/perc_signoff_check.py"
    assert profile["execution_status"] == "SOURCE_ADAPTER_IMPLEMENTED_COMPONENT_ONLY"
    features = next(item["features"] for item in registry["reference_profiles"]
                    if item["name"] == "Small digital IC without DFT")
    resolved = flow109.resolve_step(flow109.resolve_plan(features), "D66")
    assert flow109.source_owned_native_dispatch(resolved) == dispatch


def test_automated_pass_binds_final_subjects_but_preserves_manual_and_unsupported(tmp_path,
                                                                                 monkeypatch):
    perc, context, subjects, calls, _d65_outputs = _case(tmp_path, monkeypatch)
    result = perc.execute(tmp_path, context)
    assert result["native_started"] is True
    assert result["automated_component_status"] == "PASS"
    assert result["component_status"] == result["flow109_acceptance"] == "NOT_MEASURED"
    assert result["whole_ic_acceptance"] == "NOT_MEASURED"
    assert result["reason"] == "D66_MANUAL_REVIEW_PENDING"
    assert result["d65_evidence_kind"] == "window_component"
    assert set(result["manual_review_pending"]) == perc.REQUIRED_MANUAL
    assert result["unsupported_capabilities"]
    assert result["commercial_perc_qualification"] == "NOT_CLAIMED"
    declared = calls[0]["resolved_input_manifest"]["files"]
    for ref in subjects.values():
        assert ref["path"] in declared and declared[ref["path"]] == ref["sha256"]
    current = perc.validate_final_perc(tmp_path, result["receipt"])
    assert current["component_status"] == current["whole_ic_acceptance"] == "NOT_MEASURED"


def test_existing_canonical_step31_receipt_binds_current_inputs_without_wrapper(tmp_path,
                                                                                monkeypatch):
    perc, context, subjects, calls, d65_outputs = _case(
        tmp_path, monkeypatch, d65_kind="canonical")
    result = perc.execute(tmp_path, context)
    assert result["native_started"] is True
    assert result["d65_evidence_kind"] == "canonical_step31"
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D66_MANUAL_REVIEW_PENDING"
    declared = calls[0]["resolved_input_manifest"]["files"]
    assert declared["phase3/stage3/pnr/routed.def"] == subjects["geometry_def"]["sha256"]
    assert all(declared[path] == digest for path, digest in d65_outputs.items())
    current = perc.validate_final_perc(tmp_path, result["receipt"])
    assert current["d65_evidence_kind"] == "canonical_step31"
    assert current["flow109_acceptance"] == current["whole_ic_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("damage,reason,status", [
    ("wrong_step", "D66_D65_CANONICAL_WRONG_STEP", "NOT_MEASURED"),
    ("fail", "D66_D65_CANONICAL_FAILED", "FAIL"),
    ("missing_input_binding", "D66_D65_CANONICAL_FINAL_DEF_MISMATCH", "NOT_MEASURED"),
    ("project_glob", "D66_D65_CANONICAL_OUTPUT_BINDING_INVALID", "NOT_MEASURED"),
    ("consumer_disallowed", "D66_D65_CANONICAL_PRODUCER_BINDING_INVALID", "NOT_MEASURED"),
    ("bare_pass", "D66_D65_CANONICAL_NOT_ACCEPTED", "NOT_MEASURED"),
])
def test_canonical_step31_value_negatives_refuse_before_step28(
        tmp_path, monkeypatch, damage, reason, status):
    perc, context, _subjects, calls, _outputs = _case(
        tmp_path, monkeypatch, d65_kind="canonical", d65_damage=damage)
    result = perc.execute(tmp_path, context)
    assert result["component_status"] == status, result
    assert result["reason"] == reason
    assert result["native_started"] is False and calls == []
    assert result["flow109_acceptance"] == result["whole_ic_acceptance"] == "NOT_MEASURED"


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_canonical_step31_live_output_must_match_receipt(tmp_path, monkeypatch, change):
    perc, context, _subjects, calls, outputs = _case(
        tmp_path, monkeypatch, d65_kind="canonical")
    path = tmp_path / next(iter(outputs))
    if change == "missing":
        path.unlink()
    else:
        path.write_text("stale")
    result = perc.execute(tmp_path, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] in {"D66_REQUIRED_INPUT_ABSENT", "D66_REQUIRED_INPUT_CHANGED"}
    assert result["native_started"] is False and calls == []


@pytest.mark.parametrize("producer,gate,automated_fail", [
    ("FAIL", "PASS", False), ("PASS", "FAIL", False), ("PASS", "PASS", True)])
def test_existing_owner_or_value_failure_has_precedence(tmp_path, monkeypatch,
                                                        producer, gate, automated_fail):
    perc, context, _subjects, _calls, _d65_outputs = _case(
        tmp_path, monkeypatch, producer=producer, gate=gate,
        automated_fail=automated_fail)
    result = perc.execute(tmp_path, context)
    assert result["component_status"] == "FAIL", result
    assert result["automated_component_status"] == "FAIL"
    assert result["reason"] == "D66_AUTOMATED_PERC_FAILED"
    assert result["flow109_acceptance"] == result["whole_ic_acceptance"] == "NOT_MEASURED"


def test_missing_final_subject_refuses_before_existing_owner(tmp_path, monkeypatch):
    perc, context, subjects, calls, _d65_outputs = _case(tmp_path, monkeypatch)
    (tmp_path / subjects["geometry_gds"]["path"]).unlink()
    result = perc.execute(tmp_path, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["native_started"] is False and calls == []
    assert result["reason"] == "D66_REQUIRED_INPUT_ABSENT"


@pytest.mark.parametrize("changed", ["geometry_gds", "adopted_netlist"])
def test_current_final_geometry_or_netlist_change_invalidates_reuse(tmp_path, monkeypatch, changed):
    perc, context, subjects, _calls, _d65_outputs = _case(tmp_path, monkeypatch)
    result = perc.execute(tmp_path, context)
    path = tmp_path / subjects[changed]["path"]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(Exception, match="D66_REQUIRED_INPUT_CHANGED"):
        perc.validate_final_perc(tmp_path, result["receipt"])


def test_missing_required_manual_disclosure_cannot_become_pass(tmp_path, monkeypatch):
    perc, context, _subjects, _calls, _d65_outputs = _case(
        tmp_path, monkeypatch, omit_manual="io_supply_pad_sufficiency")
    result = perc.execute(tmp_path, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D66_REQUIRED_REVIEW_CATEGORY_ABSENT"
    assert result["flow109_acceptance"] == result["whole_ic_acceptance"] == "NOT_MEASURED"
