"""D66 binding to the existing Step-28 owner; no commercial PERC claim."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "flow/flow109.json"
TEST_IMAGE = "registry.example/vibeic-eda@sha256:" + "1" * 64
OTHER_IMAGE = "registry.example/vibeic-eda@sha256:" + "2" * 64


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
          automated_fail=False, omit_manual=None, d65_kind="wrapper", d65_damage=None,
          native_cvc=True, native_cvc_fail=False, cvc_damage=None,
          real_consumer=False, declared_image=None, runtime_authority="valid"):
    import flow109_final_perc as perc
    import _eda_pin
    import librelane_contract

    def resolve_image(_project, *, record=False):
        assert record is False
        if runtime_authority == "missing":
            raise librelane_contract.Refusal("LL_IMAGE_NOT_RESOLVABLE", "fixture authority absent")
        return TEST_IMAGE

    def inspected(_reference):
        if runtime_authority == "uninspectable":
            return (), "fixture image inspect unavailable"
        if runtime_authority == "changed":
            return (OTHER_IMAGE,), ""
        return (TEST_IMAGE,), ""

    monkeypatch.setattr(librelane_contract, "resolve_image", resolve_image)
    monkeypatch.setattr(_eda_pin, "local_repo_digests", inspected)

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
        "backend": {"image_id": declared_image or TEST_IMAGE, "pdk_root": "/foss/pdks",
                    "pdk_name": "gf180mcuD", "top": top}})
    summary = _summary(automated_fail=automated_fail, omit_manual=omit_manual)
    if native_cvc:
        count = 2 if native_cvc_fail else 0
        report_text = ("CVC: 2(2) instances, 4(4) nets, 2(2) devices.\n"
                       f"CVC: HI-Z Inputs: {count}\nCVC: Total: {count}\n"
                       "CVC: End: now\n")
        report = _put(project, "reports/phase3/cvc_native/report.rpt", report_text)
        pdk_sources = _put(project, "reports/phase3/cvc_native/pdk-sources.sha256",
                           "a" * 64 + "  /pdk/cvc/cvcrc\n")
        parsed = perc.phase3_runner._parse_native_cvc_report(report_text)
        receipt_payload = {
            "schema": "vibeic/native-cvc-result/1",
            "producer": "phase3_one_shot_runner._native_cvc_category",
            "tool": "cvc_rv", "image": TEST_IMAGE, "top": top,
            "native_rc": 0,
            "inputs": {"extracted_netlist": subjects["extracted_netlist"],
                       "adopted_netlist": subjects["adopted_netlist"]},
            "pdk_sources": pdk_sources, "report": report, "parsed": parsed,
        }
        if cvc_damage == "forged":
            receipt_payload["producer"] = "tests.synthetic_producer"
        elif cvc_damage == "forged_input":
            receipt_payload["inputs"]["adopted_netlist"] = {
                **subjects["adopted_netlist"], "sha256": "f" * 64}
        elif cvc_damage == "failed_launch":
            receipt_payload["native_rc"] = 17
        elif cvc_damage == "wrong_image":
            receipt_payload["image"] = OTHER_IMAGE
        receipt = _put(project, "reports/phase3/cvc_native/result.json", receipt_payload)
        summary["categories"].append({
            "category": "Native CVC electrical rules", "status": "AUTOMATED",
            "tool": "cvc_rv + PDK-declared libs.tech/librelane/cvc",
            **parsed, "native_rc": 17 if cvc_damage == "failed_launch" else 0,
            "evidence": report,
            "producer_receipt": receipt,
        })
        if native_cvc_fail:
            summary["verdict"] = "PERC_EQUIV_FAIL"
            summary["automated_failed"].append("Native CVC electrical rules")
    calls = []

    def fake_produce(_project, params):
        calls.append(params)
        _put(project, perc.OUTPUTS[0], summary)
        _put(project, perc.OUTPUTS[1],
             f"OVERALL VERDICT: {summary['verdict']}\n" +
             "\n".join(row["category"] for row in summary["categories"]))
        _put(project, perc.OUTPUTS[2],
             f"**Overall verdict:** `{summary['verdict']}`\n" +
             "\n".join(row["category"] for row in summary["categories"]))
        _put(project, perc.OUTPUTS[3], {"status": gate})
        if cvc_damage == "mismatched":
            (project / "reports/phase3/cvc_native/report.rpt").write_text(
                report_text.replace(f"Total: {count}", "Total: 9"))
        return {"verdict": producer, "canonical_receipts": [{
            "schema": "vibeic/backend-producer-receipt/1", "step_id": "28",
            "verdict": producer}]}

    monkeypatch.setattr(perc, "require_launch_admission", lambda *args, **kwargs: None)
    monkeypatch.setattr(perc, "_d65_geometry_current", lambda *args, **kwargs: None)
    monkeypatch.setattr(perc.backend_producers, "produce", fake_produce)
    if real_consumer:
        import perc_signoff_check

        def consume(project, row):
            audit = perc_signoff_check.audit(project)
            return {"status": "PASS" if audit["rc"] == 0 else "FAIL",
                    "step": row, "audit": audit}
        monkeypatch.setattr(perc.backend_gates, "evaluate", consume)
    else:
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


def test_d66_binds_job_image_to_resolved_and_inspected_runtime(tmp_path, monkeypatch):
    perc, context, _subjects, calls, _outputs = _case(tmp_path, monkeypatch)
    result = perc.execute(tmp_path, context)
    assert calls and calls[0]["image_id"] == TEST_IMAGE
    assert result["runtime_image"] == {
        "declared_reference": TEST_IMAGE,
        "resolved_reference": TEST_IMAGE,
        "digest": "sha256:" + "1" * 64,
        "inspected_digests": ["sha256:" + "1" * 64],
    }


@pytest.mark.parametrize("mode,declared,reason", [
    ("valid", OTHER_IMAGE, "D66_RUNTIME_IMAGE_MISMATCH"),
    ("missing", TEST_IMAGE, "D66_RUNTIME_IMAGE_AUTHORITY_ABSENT"),
    ("uninspectable", TEST_IMAGE, "D66_RUNTIME_IMAGE_UNINSPECTABLE"),
    ("changed", TEST_IMAGE, "D66_RUNTIME_IMAGE_MISMATCH"),
])
def test_d66_runtime_identity_refuses_before_native(
        tmp_path, monkeypatch, mode, declared, reason):
    perc, context, _subjects, calls, _outputs = _case(
        tmp_path, monkeypatch, declared_image=declared, runtime_authority=mode)
    result = perc.execute(tmp_path, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == reason
    assert result["native_started"] is False and calls == []


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


def test_native_cvc_report_is_graded_from_contents_not_process_rc():
    import phase3_one_shot_runner as runner

    population = "CVC: 2(2) instances, 4(4) nets, 2(2) devices.\n"
    positive = population + "CVC: HI-Z Inputs: 0\nCVC: Total: 0\nCVC: End: now\n"
    negative = population + "CVC: HI-Z Inputs: 2\nCVC: Total: 2\nCVC: End: now\n"
    assert runner._parse_native_cvc_report(positive)["result"] == "PASS"
    parsed = runner._parse_native_cvc_report(negative)
    assert parsed["result"] == "FAIL"
    assert parsed["counts"]["HI-Z Inputs"] == parsed["counts"]["Total"] == 2
    assert runner._parse_native_cvc_report(positive.removesuffix("CVC: End: now\n"))[
        "result"] == "INCOMPLETE"
    assert runner._parse_native_cvc_report(
        "CVC: Total: 0\nCVC: End: now\n")["result"] == "INCOMPLETE"


@pytest.mark.parametrize("mode", [
    "success", "no_report", "failed", "failed_with_report",
])
def test_native_cvc_producer_publishes_bound_report_and_receipt(
        tmp_path, monkeypatch, mode):
    import librelane_contract
    import phase3_one_shot_runner as runner

    top = "neutral_top"
    extracted = tmp_path / "phase3/stage3/extracted/neutral_top.sp"
    adopted = tmp_path / f"phase3/stage3/pnr/{top}_pnr.v"
    extracted.parent.mkdir(parents=True)
    adopted.parent.mkdir(parents=True)
    extracted.write_text(".subckt neutral_top VDD VSS\n.ends\n")
    adopted.write_text("module neutral_top; endmodule\n")
    monkeypatch.setattr(runner, "_pdk_dir_of", lambda _pdk: "/pdk/current")
    monkeypatch.setattr(runner, "_pdk_std_cell_library", lambda _pdk: "cells")
    monkeypatch.setattr(runner, "_design_supply_nets",
                        lambda _pdk: ({"VDD"}, {"VSS"}))
    monkeypatch.setattr(librelane_contract, "native_tool_command",
                        lambda _image, command: ("none", command))

    out = tmp_path / "reports/phase3/cvc_native"
    out.mkdir(parents=True)
    (out / "report.rpt").write_text(
        "CVC: 9(9) instances, 9(9) nets, 9(9) devices.\n"
        "CVC: HI-Z Inputs: 0\nCVC: Total: 0\nCVC: End: stale\n")
    (out / "result.json").write_text('{"stale": true}\n')

    def fake_run(argv, **_kwargs):
        assert "--cpus" in argv and argv[argv.index("--cpus") + 1] == "4"
        if mode in {"success", "failed_with_report"}:
            (out / "report.rpt").write_text(
                "CVC: 2(2) instances, 4(4) nets, 2(2) devices.\n"
                "CVC: HI-Z Inputs: 0\nCVC: Total: 0\nCVC: End: current\n")
        (out / "pdk-sources.sha256").write_text("a" * 64 + "  /pdk/cvcrc\n")
        return SimpleNamespace(returncode=0 if mode in {"success", "no_report"} else 17)

    monkeypatch.setattr(librelane_contract, "run_container", fake_run)
    category = runner._native_cvc_category(
        tmp_path, top, SimpleNamespace(), "registry/image@sha256:" + "1" * 64)
    receipt_path = out / "result.json"
    if mode != "success":
        assert category["result"] == "INCOMPLETE"
        assert "producer_receipt" not in category
        assert not receipt_path.exists()
        return
    assert category["result"] == "PASS" and category["counts"]["Total"] == 0
    receipt = json.loads(receipt_path.read_text())
    assert receipt["producer"] == "phase3_one_shot_runner._native_cvc_category"
    assert receipt["report"] == category["evidence"]
    assert receipt["inputs"]["extracted_netlist"]["sha256"] == _sha(extracted)
    assert receipt["inputs"]["adopted_netlist"]["sha256"] == _sha(adopted)


def test_d66_refuses_when_existing_owner_did_not_publish_native_cvc(tmp_path, monkeypatch):
    perc, context, _subjects, calls, _d65_outputs = _case(
        tmp_path, monkeypatch, native_cvc=False)
    result = perc.execute(tmp_path, context)
    assert calls
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D66_NATIVE_CVC_EVIDENCE_ABSENT"


@pytest.mark.parametrize("damage,reason", [
    ("forged", "D66_NATIVE_CVC_PRODUCER_INVALID"),
    ("failed_launch", "D66_NATIVE_CVC_PRODUCER_INVALID"),
    ("forged_input", "D66_NATIVE_CVC_EVIDENCE_MISMATCH"),
    ("mismatched", "D66_NATIVE_CVC_EVIDENCE_MISMATCH"),
    ("wrong_image", "D66_NATIVE_CVC_PRODUCER_INVALID"),
])
def test_d66_refuses_forged_or_mismatched_native_cvc(
        tmp_path, monkeypatch, damage, reason):
    perc, context, _subjects, _calls, _outputs = _case(
        tmp_path, monkeypatch, cvc_damage=damage)
    result = perc.execute(tmp_path, context)
    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == reason


@pytest.mark.parametrize("native_fail,expected_rc,expected_status", [
    (False, 0, "NOT_MEASURED"),
    (True, 1, "FAIL"),
])
def test_native_cvc_reaches_actual_perc_consumer(
        tmp_path, monkeypatch, native_fail, expected_rc, expected_status):
    perc, context, _subjects, _calls, _outputs = _case(
        tmp_path, monkeypatch, native_cvc_fail=native_fail, real_consumer=True)
    result = perc.execute(tmp_path, context)
    assert result["consumer_result"]["audit"]["rc"] == expected_rc
    assert result["component_status"] == expected_status
    if native_fail:
        assert result["reason"] == "D66_AUTOMATED_PERC_FAILED"
        assert result["consumer_result"]["audit"]["automated_failed"] == [
            "Native CVC electrical rules"]


@pytest.mark.parametrize(('native_status', 'count', 'expected'),
                         [('PASS', 0, 'PASS'), ('FAIL', 2, 'FAIL'), ('INCOMPLETE', None, 'NOT_MEASURED')])
def test_cvc_selects_this_runs_lvs_state(tmp_path, monkeypatch, native_status, count, expected):
    import phase3_one_shot_runner as runner
    folder = tmp_path / 'phase3/librelane/native-lvs'
    root = tmp_path / 'pdk-store'
    kit = root / 'test-kit'
    assets = {}
    for role, rel in {'tech': 'libs.ref/test-cells/techlef/nom.tlef',
                      'cell': 'libs.ref/test-cells/lef/cells.lef',
                      'liberty': 'libs.ref/test-cells/lib/cells.lib'}.items():
        path = kit / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('neutral software fixture')
        assets[role] = str(path)
    state = {'spice': str(tmp_path / 'native-final.spice'),
             'nl': str(tmp_path / 'native-final.v'), 'gds': str(tmp_path / 'delivered.gds')}
    _put(tmp_path, 'phase3/librelane/native-lvs/state_out.json', state)
    _put(tmp_path, 'phase3/librelane/native-lvs/config.json',
         {'DESIGN_NAME': 'selected_chip', 'PDK': 'test-kit',
          'LIB': {'*': [assets['liberty']]}, 'TECH_LEFS': {'*': assets['tech']},
          'CELL_LEFS': [assets['cell']]})
    _put(tmp_path, 'reports/phase3/librelane_pv_lvs.json',
         {'metrics': {'design__lvs_error__count': {'folder': str(folder)}}})
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(root))
    observed = []
    def native(project, top, pdk, image, **kwargs):
        observed.append((top, kwargs))
        return {'result': native_status, 'counts': {'Total': count}}
    monkeypatch.setattr(runner, '_native_cvc_category', native)
    result = runner._cvc_from_native_state(tmp_path)
    assert result['verdict'] == expected
    assert result['gds'] == state['gds']
    assert result['unmeasured_obligations'] == ['latch-up spacing', 'ESD characterization']
    assert observed == [('selected_chip', {'extracted_netlist': Path(state['spice']),
                                          'adopted_netlist': Path(state['nl'])})]
