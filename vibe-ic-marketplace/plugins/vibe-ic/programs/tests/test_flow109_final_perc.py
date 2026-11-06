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
