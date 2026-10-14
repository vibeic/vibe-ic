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


def _issue3141_native(tmp_path, name):
    """Read independently retained, self-authored neutral native outputs.

    These opt-in cases never substitute a successful tool or receipt writer.
    The exact source-bound native inputs and raw worker receipts accompany
    the issue3141 source packet; unrelated field captures are not consumed.
    """
    import os
    import shutil
    root = os.environ.get("VIBEIC_ISSUE3141_NEUTRAL_INPUTS")
    if not root:
        pytest.skip("issue3141 neutral native inputs were not supplied")
    original = Path(root) / name
    source = original / "phase3/librelane/issue3141/01-openroad-staprepnr"
    assert source.is_dir(), source
    folder = tmp_path / "phase3/librelane/issue3141/01-openroad-staprepnr"
    shutil.copytree(source, folder)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/container_image.json").write_bytes(
        (original / "reports/container_image.json").read_bytes())
    return folder


@pytest.mark.parametrize("name,unit", [("ns", "ns"), ("ps", "ps"),
                                      ("ps-lib-ns-command", "ns")])
def test_issue3141_native_command_unit_reaches_composed_report(tmp_path, name, unit):
    import librelane_prelayout as prelayout
    folder = _issue3141_native(tmp_path, name)
    reports = prelayout.compose_corner_reports(
        folder, tmp_path / "composed", phase3._classify_corner_from_name)
    assert len(reports) == 3
    for path in reports.values():
        assert f"STA_TIME_UNIT: {unit}\n" in path.read_text()


@pytest.mark.parametrize("name,scale", [("ns", 1), ("ps", .001)])
def test_issue3141_normal_publication_scales_native_readings(tmp_path, name, scale):
    folder = _issue3141_native(tmp_path, name)
    published = phase3.publish_prelayout_reports(tmp_path, folder)
    record = json.loads(Path(published["pre_pnr_summary"]).read_text())
    summary = record["summary"]
    assert record["passed"] is True
    assert summary["slack_measurement"] == "MEASURED"
    metrics = json.loads((folder / "state_out.json").read_text())["metrics"]
    expected = round(metrics["timing__setup__wns__corner:max_ss_025C_1v00"], 2) * scale
    assert summary["slack_ns"]
    assert all(row["setup_wns_ns"] == pytest.approx(expected)
               for row in summary["slack_ns"])


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_issue3141_changed_unit_output_retains_receipt_refusal(tmp_path, change):
    folder = _issue3141_native(tmp_path, "ns")
    unit = folder / "max_ss_025C_1v00/vibeic_time_unit.rpt"
    if change == "missing":
        unit.unlink()
    else:
        unit.write_text(unit.read_text() + "changed\n")
    with pytest.raises(Exception, match="PRELAYOUT_NATIVE_RECEIPT_INVALID"):
        phase3.publish_prelayout_reports(tmp_path, folder)


@pytest.mark.parametrize("text", ["STA_TIME_UNIT_NOT_STATED: unavailable\n",
                                  "STA_TIME_UNIT: ns\nSTA_TIME_UNIT: ps\n"])
def test_issue3141_missing_or_conflicting_unit_is_not_a_measurement(tmp_path, text):
    """Authored invalid source records; no native success credit is asserted."""
    import librelane_contract as ll
    folder = _issue3141_native(tmp_path, "ns")
    unit = folder / "max_ss_025C_1v00/vibeic_time_unit.rpt"
    unit.write_text(text)
    receipt = folder / "vibeic_receipt.json"
    record = json.loads(receipt.read_text())
    record["sha256"][str(unit.relative_to(folder))] = ll.digest(unit)
    receipt.write_text(json.dumps(record))
    with pytest.raises(ll.Refusal, match="TIME_UNIT"):
        phase3.publish_prelayout_reports(tmp_path, folder)


def test_issue3141_real_image_internal_liberty_remains_measured(tmp_path):
    folder = _issue3141_native(tmp_path, "image-internal")
    assert json.loads((folder / "pdk_root.json").read_text())["mounts_under_it"] == []
    result = phase3.publish_prelayout_reports(tmp_path, folder)
    record = json.loads(Path(result["pre_pnr_summary"]).read_text())
    assert record["passed"] is True
    assert record["summary"]["slack_measurement"] == "MEASURED"
    assert record["summary"]["slack_time_unit"] == "ns"


def test_issue3141_genuine_negative_native_slack_still_blocks(tmp_path):
    import librelane_contract as ll
    folder = _issue3141_native(tmp_path, "negative-ps")
    metrics = json.loads((folder / "state_out.json").read_text())["metrics"]
    assert metrics["timing__setup__ws__corner:max_ss_025C_1v00"] < 0
    with pytest.raises(ll.Refusal, match="PRELAYOUT_STA_SUMMARY_FAILED"):
        phase3.publish_prelayout_reports(tmp_path, folder)
    record = json.loads((tmp_path / "reports/phase3/sta/pre_pnr_summary.json").read_text())
    assert record["passed"] is False
    assert record["summary"]["real_violation_found"] is True
    expected = round(metrics["timing__setup__wns__corner:max_ss_025C_1v00"], 2) * .001
    assert expected < 0
    assert all(row["setup_wns_ns"] == pytest.approx(expected)
               for row in record["summary"]["slack_ns"])


@pytest.mark.parametrize("change", ["missing", "changed", "unbound"])
def test_issue3141_invalid_mounted_liberty_context_cannot_publish_units(tmp_path, change):
    """Invalid authored context controls do not claim a successful native run."""
    import shutil
    import librelane_contract as ll
    folder = _issue3141_native(tmp_path, "ns")
    pdk_path = folder / "pdk_root.json"
    pdk = json.loads(pdk_path.read_text())
    original = Path(pdk["mounts_under_it"][0][0])
    assets = tmp_path / "assets"
    shutil.copytree(original, assets)
    pdk["mounts_under_it"][0][0] = str(assets)
    if change == "missing":
        (assets / "ss.lib").unlink()
    elif change == "changed":
        (assets / "ss.lib").write_text((assets / "ss.lib").read_text() + "\nchanged\n")
    pdk_path.write_text(json.dumps(pdk))
    receipt_path = folder / "vibeic_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    if change == "unbound":
        receipt["input"]["config_files"].pop("/foss/pdks/issue3141-neutral/ss.lib")
        fp = folder / "input_fingerprint.json"
        fp.write_text(json.dumps(receipt["input"]))
        receipt["sha256"]["input_fingerprint.json"] = ll.digest(fp)
    receipt["sha256"]["pdk_root.json"] = ll.digest(pdk_path)
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ll.Refusal, match="LIBERTY"):
        phase3.publish_prelayout_reports(tmp_path, folder)
