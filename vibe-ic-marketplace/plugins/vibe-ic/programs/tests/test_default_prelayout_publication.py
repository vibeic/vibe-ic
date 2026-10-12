from __future__ import annotations

import json
import sys
import tarfile
import types
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
import design_one_shot_runner as design
import execution_policy as policy
import phase3_one_shot_runner as phase3
import test_step8_post_prelayout as postcheck_fixtures


RETAINED_ARCHIVE = Path(__file__).resolve().parent / "fixtures/default_prelayout_native.tar.gz"


def _fixture(tmp_path):
    project = tmp_path / "project"
    netlist = project / "phase2/stage2/synth/spm_synth.v"
    declared = project / "phase2/stage2/constraints/spm.asic.sdc"
    pnr = project / "phase3/stage3/pnr/constraint.sdc"
    rec = project / "phase2/stage2/constraints/asic_sdc.json"
    pvt = project / "phase2/stage2/constraints/pvt_matrix.json"
    l8 = project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
    for path in (netlist, declared, pnr, rec, pvt, l8):
        path.parent.mkdir(parents=True, exist_ok=True)
    netlist.write_text("module spm; endmodule\n")
    declared.write_text("create_clock -period 10 [get_ports clk]\n")
    pnr.write_text("create_clock -period 9 [get_ports clk]\n")
    rec.write_text(json.dumps({"path": str(declared.relative_to(project))}))
    pvt.write_text(json.dumps({"corners": [{"name": "TT"}], "primary_corner": "TT"}))
    l8.write_text(json.dumps({"clocks": {"clk": {"period_ns": 10}}}))
    return project, netlist, pnr


def _retained_native(project, netlist, pnr):
    folder = project / "phase3/librelane/prelayout/design_sdc/native"
    folder.mkdir(parents=True, exist_ok=True)
    with tarfile.open(RETAINED_ARCHIVE, "r:gz") as archive:
        for member in archive.getmembers():
            name = Path(member.name)
            if (name.is_absolute() or ".." in name.parts or
                    not member.isfile()):
                raise AssertionError(f"unsafe native fixture member: {member.name}")
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = archive.extractfile(member)
            if payload is None:
                raise AssertionError(f"unreadable native fixture member: {member.name}")
            target.write_bytes(payload.read())
    state = folder / "state_out.json"
    gate = project / "phase3/librelane/prelayout/gates/step8_sdc_opensta.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    import librelane_contract as ll
    gate.write_text(json.dumps({
        "step": "8",
        "program": "librelane_prelayout.judge_sdc",
        "verdict": "PASS",
        "netlist": str(netlist.relative_to(project)),
        "netlist_sha256": ll.digest(netlist),
        "sdc": str(pnr.relative_to(project)),
        "sdc_sha256": ll.digest(pnr),
        "source": str(state.relative_to(project)),
        "state_out_sha256": ll.digest(state),
    }))
    return folder, gate


def _native_result(folder):
    import librelane_contract as ll
    return {"folder": folder, "receipt_sha256": ll.digest(folder / "vibeic_receipt.json")}


def _runtime(project):
    return {
        "project": project,
        "policy": {"mode": "default"},
        "parameters": {"top": "spm", "pdk": object(), "container": "vibeic-eda"},
    }


def _stub_step8_and_step10(monkeypatch, order):
    def post(*args, **kwargs):
        order.append("step8")
        return types.SimpleNamespace(status="PASS", detail="focused")

    def publish(*args, **kwargs):
        order.append("step10")
        project = Path(args[0])
        gate = project / "phase3/librelane/prelayout/gates/step8_sdc_opensta.json"
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text(json.dumps({"verdict": "PASS"}))
        return {"pre_pnr_timing": "retained"}

    monkeypatch.setattr(design, "step_sdc_validation_post_prelayout", post)
    monkeypatch.setattr(phase3, "publish_prelayout_reports", publish)


def test_default_step15_runs_native_then_step8_step10_before_census(tmp_path, monkeypatch):
    project, netlist, pnr = _fixture(tmp_path)
    order = []

    def produce(project_, top, pdk, runner_sdc, staged, modes, notes):
        order.append("native")
        folder = project_ / "phase3/librelane/prelayout/design_sdc/native"
        folder.mkdir(parents=True)
        (folder / "vibeic_receipt.json").write_text("{}")
        return {"folder": folder, "sdc": {"verdict": "PASS"}}

    _stub_step8_and_step10(monkeypatch, order)
    monkeypatch.setattr(phase3, "_prelayout_librelane", produce)
    policy._ensure_default_prelayout(_runtime(project), "15")
    assert order == ["native", "step8", "step10"]


def test_default_dispatch_leaves_prelayout_to_canonical_producer(
        tmp_path, monkeypatch):
    project, netlist, pnr = _fixture(tmp_path)
    order = []
    runtime = {
        "project": project,
        "policy": {"mode": "default", "request_receipt": {"invocation_id": "x"}},
        "parameters": {"top": "spm", "pdk": object(), "container": "vibeic-eda"},
        "contexts": {}, "runs": {},
        "route": {"source_sha": "s", "project_digest": "p", "ic_ip_path": "i"},
    }
    monkeypatch.setattr(policy, "_ordinary_runtime", runtime)

    def produce(project_, top, pdk, runner_sdc, staged, modes, notes):
        order.append("native")
        folder = project_ / "phase3/librelane/prelayout/design_sdc/native"
        folder.mkdir(parents=True)
        (folder / "vibeic_receipt.json").write_text("{}")
        return {"folder": folder, "sdc": {"verdict": "PASS"}}

    def trap(*args, **kwargs):
        raise AssertionError("Default policy dispatched the pre-layout producer")

    monkeypatch.setattr(policy, "_ensure_default_prelayout", trap)
    result = policy.dispatch_fixed_step(project, "15")
    # The phase-3 caller owns the canonical pre-layout producer.  The policy
    # seam must not publish it or construct a Controller input census.
    assert result is None
    assert order == []


def test_default_step15_refuses_failed_native_producer(tmp_path, monkeypatch):
    project, _, _ = _fixture(tmp_path)
    gate = project / "phase3/librelane/prelayout/gates/step8_sdc_opensta.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({"verdict": "PASS"}))

    def fail(*args):
        return {"sdc": {"verdict": "FAIL"}}

    monkeypatch.setattr(phase3, "_prelayout_librelane", fail)
    with pytest.raises(policy.Refusal, match="PRELAYOUT_PUBLICATION_FAILED"):
        policy._ensure_default_prelayout(_runtime(project), "15")
    assert json.loads(gate.read_text())["verdict"] == "PASS"


def test_postcheck_publishes_retained_three_corner_reports(tmp_path):
    _, pnr, netlist = postcheck_fixtures.project(tmp_path)
    project = tmp_path
    folder, gate = _retained_native(project, netlist, pnr)
    row = design.step_sdc_validation_post_prelayout(
        project, "top", native_result=_native_result(folder))
    assert row.status == "PASS", row.detail
    receipt = json.loads(Path(row.output_files[0]).read_text())
    assert receipt["binding"]["native_proof"] is True
    published = phase3.publish_prelayout_reports(
        project, folder, receipt_sha256=_native_result(folder)["receipt_sha256"])
    assert Path(published["pre_pnr_timing"]).is_file()
    assert Path(published["pre_pnr_summary"]).is_file()
    summary = json.loads(Path(published["pre_pnr_summary"]).read_text())
    assert summary["record_role"] == "prelayout_audit"
    import l24_signoff_evidence_backed_check as signoff
    assert signoff._is_input_or_audit_record(Path(published["pre_pnr_summary"]))
    names = sorted(p.name for p in (project / "phase3/stage3/sta/prelayout_per_corner").glob("*.rpt"))
    assert names == ["sta_FF.rpt", "sta_SS.rpt", "sta_TT.rpt"]


def test_changed_native_report_refuses_canonical_publication(tmp_path):
    _, pnr, netlist = postcheck_fixtures.project(tmp_path)
    project = tmp_path
    folder, _ = _retained_native(project, netlist, pnr)
    report = folder / "nom_tt_025C_5v00/max.rpt"
    report.write_text(report.read_text() + "\nchanged\n")
    with pytest.raises(Exception, match="PRELAYOUT_NATIVE_RECEIPT_INVALID"):
        phase3.publish_prelayout_reports(project, folder)


def test_changed_native_state_refuses_canonical_publication(tmp_path):
    _, pnr, netlist = postcheck_fixtures.project(tmp_path)
    folder, _ = _retained_native(tmp_path, netlist, pnr)
    state = folder / "state_out.json"
    state.write_text(state.read_text() + "\n")
    with pytest.raises(Exception, match="PRELAYOUT_NATIVE_RECEIPT_INVALID"):
        phase3.publish_prelayout_reports(tmp_path, folder)


@pytest.mark.parametrize("field", ["source", "sdc", "netlist"])
def test_project_relative_gate_escape_refuses_before_tools(tmp_path, monkeypatch, field):
    _, pnr, netlist = postcheck_fixtures.project(tmp_path)
    project = tmp_path
    folder, gate = _retained_native(project, netlist, pnr)
    doc = json.loads(gate.read_text())
    doc[field] = "../outside"
    gate.write_text(json.dumps(doc))
    monkeypatch.setattr(design.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("path escape must refuse before tools"))
    row = design.step_sdc_validation_post_prelayout(
        project, "top", native_result={"folder": folder})
    assert row.status == "NOT_MEASURED"
    assert "PATH_ESCAPE" in row.detail or "GATE_STALE" in row.detail


def test_project_relative_symlink_refuses_before_tools(tmp_path, monkeypatch):
    _, pnr, netlist = postcheck_fixtures.project(tmp_path)
    folder, gate = _retained_native(tmp_path, netlist, pnr)
    link = tmp_path / "phase3/stage3/pnr/link.sdc"
    link.symlink_to(pnr)
    doc = json.loads(gate.read_text())
    doc["sdc"] = str(link.relative_to(tmp_path))
    gate.write_text(json.dumps(doc))
    monkeypatch.setattr(design.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("symlink must refuse before tools"))
    row = design.step_sdc_validation_post_prelayout(
        tmp_path, "top", native_result={"folder": folder})
    assert row.status == "NOT_MEASURED"
    assert "SYMLINK" in row.detail


def test_changed_native_receipt_refuses_current_native_proof(tmp_path):
    _, pnr, netlist = postcheck_fixtures.project(tmp_path)
    project = tmp_path
    folder, _ = _retained_native(project, netlist, pnr)
    receipt = folder / "vibeic_receipt.json"
    expected = _native_result(folder)["receipt_sha256"]
    receipt.write_text(receipt.read_text() + "\n")
    row = design.step_sdc_validation_post_prelayout(
        project, "top", native_result={"folder": folder,
                                       "receipt_sha256": expected})
    assert row.status == "NOT_MEASURED"
    assert "SDC_POSTCHECK_NATIVE_PROOF_STALE" in row.detail


def test_corrupt_native_receipt_hash_refuses_publication(tmp_path):
    _, pnr, netlist = postcheck_fixtures.project(tmp_path)
    folder, _ = _retained_native(tmp_path, netlist, pnr)
    receipt = folder / "vibeic_receipt.json"
    doc = json.loads(receipt.read_text())
    doc["sha256"]["summary.rpt"] = "0" * 64
    receipt.write_text(json.dumps(doc))
    with pytest.raises(Exception, match="PRELAYOUT_NATIVE_RECEIPT_INVALID"):
        phase3.publish_prelayout_reports(tmp_path, folder)
