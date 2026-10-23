"""Neutral caller/producer/receipt/consumer controls; no native IC execution."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution_backend_producers as backend
import librelane_postroute_repair as repair
import phase3_one_shot_runner as runner
from test_backend_input_contract_sdc import _project


def _write(project, relative, content):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _native_measurement(root, case):
    """Synthetic instrument output, shaped like the native Step32 producer.

    These are neutral test bytes, not measured STA or IC qualification. Keep
    the producer's baseline/final census, state identities and full DRV
    judgement so the real policy can reach the input-manifest checks.
    """
    state = _write(root, "phase3/librelane/32-source-control/04-openroad-stapostpnr/state_out.json",
                   '{"metrics":{"source_control_only":1}}\n')
    final = {"setup_ws_min": 0.5, "hold_ws_min": 0.2, "drv_count": 0,
             "antenna_nets": 0, "antenna_pins": 0,
             "sta_state": str(state),
             "sta_state_sha256": hashlib.sha256(state.read_bytes()).hexdigest()}
    baseline = dict(final)
    adopted = "source-control-candidate" if case == "updated_route" else None
    report = {"step": "32", "verdict": "FAIL" if case == "measured_fail" else "PASS",
              "baseline": baseline, "final": final, "adopted": adopted,
              "corners": ["neutral_scene"], "candidates": [],
              "floors": {"setup": [0.0, "source control"], "hold": [0.0, "source control"]},
              "drv_signoff_verdict": "PASS", "drv_signoff": {
                  "verdict": "PASS", "counts": {"max_slew": 0, "max_capacitance": 0, "max_fanout": 0},
                  "failures": [], "not_measured": [], "waived": []}}
    if adopted:
        baseline["drv_count"] = 1
        report["candidates"] = [{"candidate": adopted, "closure_decision": "PROMOTED",
            "repair_metrics": {"vibeic__prr__changed": 1},
            "measurement": {"sta_state_sha256": final["sta_state_sha256"]}}]
    source = _write(root, repair.REPORT_REL, json.dumps(report))
    # Use the real native publisher for the raw decision and branch output.
    # Canonical publication, current receipt, gates and consumer remain real.
    repair._publish_declared_repair(root, report, source)
    return source, state


@pytest.mark.parametrize("case", [
    "current", "updated_route", "directory", "missing", "changed", "measured_fail",
])
def test_default_current_native_manifest_reaches_the_consumer(tmp_path, monkeypatch, case):
    project = _project(tmp_path)
    _write(project, "input/step_0_5ic_answers.json", '{"route":"DIE"}\n')
    _write(project, "input/submission_template/tapeout_declaration.json", '{"route":"DIE"}\n')
    route = _write(project, "phase3/stage3/pnr/routed.def", "original routed layout\n")
    source = project / "phase3/librelane/prelayout/gates/step8_sdc_opensta.json"
    original_source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    child = "phase2/stage1/sim/tb/source_control.v"
    if case == "directory":
        _write(project, child, "module source_control; endmodule\n")
    missing = ["phase2/stage2/constraints/spm.asic.sdc",
               "phase3/librelane/prelayout/gates/step8_sdc_opensta.json"]
    if case == "missing":
        for raw in missing:
            (project / raw).unlink()
    cfg = SimpleNamespace(name="synthetic")
    monkeypatch.setattr(runner, "_backend_parameter_values", lambda *_: {
        "pdk_root": str(project / "neutral_pdk"), "image_id": "SOURCE_CONTROL_ONLY"})
    monkeypatch.setattr(backend, "_parameters", lambda *_: (
        runner, None, cfg, "SOURCE_CONTROL_ONLY"))
    # This control owns native input-manifest/current-state behaviour, not the
    # independent Step-7 ASIC-SDC producer. Preserve the fixture's existing
    # SDC bytes (including the explicit missing-input case) while exercising
    # the real Step-32 admission, producer and consumers.
    monkeypatch.setattr(runner, "_refresh_default_step32_sdc", lambda *_: None)
    seen, calls = {}, []
    actual_produce = backend.produce

    def observed(root, params):
        seen["manifest"] = params["resolved_input_manifest"]
        result = actual_produce(root, params)
        seen["producer_result"] = result
        return result

    monkeypatch.setattr(backend, "produce", observed)

    def controlled_native(root, *_args):
        # Replace the native instrument, retaining the real caller, producer,
        # current receipt authority, output collector and canonical consumers.
        calls.append("native_instrument")
        if case == "changed":
            source.write_text("changed stable source\n")
        if case == "updated_route":
            route.write_text("producer-promoted routed layout\n")
        native_source, state = _native_measurement(root, case)
        if case == "absent_report":
            native_source.unlink()
        elif case == "stale_state":
            state.write_text('{"metrics":{"changed_after_measurement":1}}\n')
        elif case == "changed_report":
            native_source.write_text(native_source.read_text() + "\n")
        elif case in ("missing_baseline", "missing_drv"):
            report = json.loads(native_source.read_text())
            if case == "missing_baseline":
                report.pop("baseline")
            else:
                report["drv_signoff"]["counts"].pop("max_fanout")
            native_source.write_text(json.dumps(report))
            # Rebind the raw receipt: these controls exercise census checks,
            # independently of the source-report hash rejection above.
            raw = root / repair.DECLARED_REPAIR_REL / "postroute_timing_repair_decision.json"
            decision = json.loads(raw.read_text())
            decision["source_report_sha256"] = hashlib.sha256(native_source.read_bytes()).hexdigest()
            raw.write_text(json.dumps(decision))
        return runner.StepResult("postroute_repair_librelane",
            "FAIL" if case == "measured_fail" else "PASS", 0,
            "controlled native failure" if case == "measured_fail" else "neutral instrument complete")

    monkeypatch.setattr(runner, "step_postroute_repair_librelane", controlled_native)
    row = runner._default_pnr_rows(project, "neutral", cfg, "SOURCE_CONTROL_ONLY", ["32"])
    receipt_path = project / "reports/phase3/default_steps/32/backend_result.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else None
    _write(project, "API_OBSERVATION.json", json.dumps({
        "case": case, "caller_status": row.status, "caller_detail": row.detail,
        "instrument_calls": calls, "seen": seen, "receipt": receipt,
        "route": route.read_text(), "original_source_sha256": original_source_sha,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None,
        "scope": "SOURCE_CONTROL_ONLY; no native EDA or IC qualification"}, indent=2))
    if case in {"absent_report", "stale_state", "changed_report", "missing_baseline", "missing_drv"}:
        assert calls == ["native_instrument"]
        assert row.status == receipt["verdict"] == "NOT_MEASURED", row.detail
        expected_reason = {
            "absent_report": "current Step-32 bound producer decision absent",
            "changed_report": "current Step-32 bound producer decision absent",
            "stale_state": "Step-32 baseline STA state is absent or changed",
            "missing_baseline": "Step-32 baseline timing/DRV/antenna census is incomplete",
            "missing_drv": "Step-32 full DRV judgement is incomplete",
        }[case]
        assert expected_reason in row.detail, row.detail
    elif case == "missing":
        assert row.status == "NOT_MEASURED", row.detail
        assert calls == [], "missing current producer inputs must stop before the tool"
        assert all(raw in row.detail for raw in missing), row.detail
    else:
        assert calls == ["native_instrument"]
        expected = "NOT_MEASURED" if case == "changed" else "FAIL" if case == "measured_fail" else "PASS"
        assert row.status == expected, row.detail
        assert receipt["verdict"] == expected, receipt
        if case != "measured_fail":
            current = receipt["current_step_declared_producers"]
            assert seen["manifest"]["files"]["phase3/librelane/prelayout/gates/step8_sdc_opensta.json"] == original_source_sha
            if case == "changed":
                assert current["reason"] == "NATIVE_CURRENT_INPUT_CHANGED: phase3/librelane/prelayout/gates/step8_sdc_opensta.json"
            else:
                assert current["inputs"]["phase3/librelane/prelayout/gates/step8_sdc_opensta.json"]["sha256"] == original_source_sha
                assert current["verdict"] == "PRODUCED"
                assert receipt["canonical_step_result"]["status"] == "PASS", receipt
                assert {r["gate"] for r in receipt["gate_ledger"]} >= {
                    "flow_step_output_content_check", "postroute_timing_repair_audit"}
        if case == "directory":
            assert child in seen["manifest"]["files"], seen
        if case == "updated_route":
            assert route.read_text() == "producer-promoted routed layout\n"
            assert "phase3/stage3/pnr/routed.def" not in current["inputs"]


@pytest.mark.parametrize("case", ["absent_report", "stale_state", "changed_report",
                                  "missing_baseline", "missing_drv"])
def test_default_step32_rejects_incomplete_or_changed_native_evidence(tmp_path, monkeypatch, case):
    test_default_current_native_manifest_reaches_the_consumer(tmp_path, monkeypatch, case)
