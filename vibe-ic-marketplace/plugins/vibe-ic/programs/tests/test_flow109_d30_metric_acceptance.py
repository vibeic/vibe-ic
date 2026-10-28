"""D30 owner/consumer controls using explicitly synthetic LEC/STA fixtures.

The real delivery owner, readset reader, native receipt validator, normalizer,
metric consumer and selected-row consumer run. Fixture STA/LEC are test doubles,
not electrical, scan timing, native-row or whole-flow qualification.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import design_one_shot_runner as design
import flow109
import flow109_metric_acceptance as metrics
import librelane_contract as native
import step_output_collector as versions
from test_flow109_selection import _d30_scan_case


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(project, path):
    return {"path": path.relative_to(project).as_posix(), "sha256": _sha(path)}


def _case(project, monkeypatch):
    validator = native.validate_step_receipt
    context = _d30_scan_case(project, monkeypatch)
    # Restore the genuine receipt validator after the shared upstream fixture.
    monkeypatch.setattr(native, "validate_step_receipt", validator)
    timing_path = project / "reports/flow109/d26_scan_mode.json"
    timing = json.loads(timing_path.read_text())
    library = project / "input/libraries/neutral.lib"
    library.parent.mkdir(parents=True)
    library.write_text("/* TEST DOUBLE: not native timing qualification */\nlibrary(neutral) {}\n")
    for arm in timing["post_scan_arms"].values():
        folder = project / arm["native"]["folder"]
        config = {"meta": {"step": "OpenROAD.STAPrePNR"},
                  "PNR_SDC_FILE": str((project / arm["constraint"]["path"]).resolve()),
                  "CELL_LIBS": {"*": [str(library)]}}
        _write(folder / "config.json", config)
        _write(folder / "pdk_root.json", {"mounts_under_it": [], "test_double": True})
        state = json.loads((folder / "state_in.json").read_text())
        fingerprint = {"step": "OpenROAD.STAPrePNR", "image": "TEST_DOUBLE_NOT_NATIVE",
            "state": _sha(folder / "state_in.json"), "config": _sha(folder / "config.json"),
            "state_files": {state["nl"]: _sha(Path(state["nl"]))},
            "config_files": {str(library): _sha(library),
                             config["PNR_SDC_FILE"]: _sha(Path(config["PNR_SDC_FILE"]))}}
        _write(folder / "input_fingerprint.json", fingerprint)
        (folder / "invocation.log").write_text("TEST DOUBLE: no native STA dispatch\n")
        log = folder / "tt/sta.log"
        log.parent.mkdir(parents=True)
        log.write_text("TEST DOUBLE: producer read journal\n"
            f"Reading cell library for the 'tt' corner at '{library}'…\n"
            f"Reading top-level netlist at '{state['nl']}'…\n"
            f"Reading design constraints file at '{config['PNR_SDC_FILE']}'…\n")
        _write(folder / "vibeic_receipt.json", {"input": fingerprint,
            "sha256": {p.relative_to(folder).as_posix(): _sha(p)
                       for p in folder.rglob("*") if p.is_file() and p.name != "vibeic_receipt.json"}})
        arm["native"]["receipt"] = _ref(project, folder / "vibeic_receipt.json")
    _write(timing_path, timing)
    row_path = project / "reports/flow109/default_rows/D26.json"
    row = json.loads(row_path.read_text())
    row["timing_modes_receipt"] = _ref(project, timing_path)
    _write(row_path, row)
    _write(project / "context.json", context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(project / "context.json"))
    folder_name = "test-d30-handoff"
    handoff = versions._versions_root(project) / folder_name / "outputs.json"
    _write(handoff, {"canonical_pass": True, "status": "PASS", "test_double": True})
    monkeypatch.setattr(design, "_current_phase2_consumer", lambda *_: {"folder": folder_name})

    # Independent owner source is fixed BEFORE invoking the delivery/readset
    # producer. Do not copy a measured value or its identity into approval.
    functional = timing["post_scan_arms"]["functional"]
    reference = {"netlist_sha256": functional["adopted_netlist"]["sha256"], "timing": [{
        "mode": "functional", "corner": "tt",
        "sdc": {"path": str(project / functional["constraint"]["path"]),
                "sha256": functional["constraint"]["sha256"]},
        "libraries": [{"path": str(library), "sha256": _sha(library)}]}]}
    reference_identity = {key: {"fixture": "independent approved reference; NOT native qualification"}
                          for key in ("producer", "checker", "tool_execution", "consumed_inputs",
                                      "requirements", "configuration")}
    payload = {"reference": reference, "reference_identity": reference_identity}
    source = project / "input/approved-handoff.json"
    _write(source, {"adopted_netlist_sdc_library": payload})
    authority = project / "adopted/base_19/adopted_netlist_sdc_library.json"
    _write(authority, {"schema": "vibeic.flow109.adopted-reference.v1", **payload,
        "approval": {"status": "APPROVED", "authority": "requirements_owner",
                     "source_reference": _ref(project, source)}})
    return context, library, timing_path, authority


def _deliver(project, context):
    attempt = flow109._new_attempt(project, context)
    ref = design._d30_publish_delivery(project, context, attempt, "test-d30-handoff")
    return {"step_id": "D30", "context_sha256": context["context_sha256"],
            "component_status": "PASS", "default_row_status": "PASS", "completed": True,
            "d30_delivery_receipt": ref}


def _adopted(result):
    return next(item for item in result["obligations"]
                if item["id"] == "base_19.adopted_netlist_sdc_library")


def _reseal_native(project, timing_path):
    """Simulate a FRESH fixture producer, never used on a real carrier."""
    timing = json.loads(timing_path.read_text())
    arm = timing["post_scan_arms"]["functional"]
    folder = project / arm["native"]["folder"]
    receipt = json.loads((folder / "vibeic_receipt.json").read_text())
    for name in receipt["input"]["config_files"]:
        receipt["input"]["config_files"][name] = _sha(Path(name))
    _write(folder / "input_fingerprint.json", receipt["input"])
    receipt["sha256"] = {name: _sha(folder / name) for name in receipt["sha256"]}
    _write(folder / "vibeic_receipt.json", receipt)
    arm["native"]["receipt"] = _ref(project, folder / "vibeic_receipt.json")
    if arm["constraint"]["sha256"] != _sha(project / arm["constraint"]["path"]):
        arm["constraint"]["sha256"] = _sha(project / arm["constraint"]["path"])
        for gate_name in ("sdc_gate", "slack_gate"):
            gate_path = project / arm[gate_name]["path"]
            gate = json.loads(gate_path.read_text())
            if gate_name == "sdc_gate":
                gate["sdc_sha256"] = arm["constraint"]["sha256"]
            _write(gate_path, gate)
            arm[gate_name].update(_ref(project, gate_path))
    _write(timing_path, timing)
    row_path = project / "reports/flow109/default_rows/D26.json"
    row = json.loads(row_path.read_text())
    row["timing_modes_receipt"] = _ref(project, timing_path)
    _write(row_path, row)


def test_d30_correct_independent_bundle_passes_only_adopted_metric(tmp_path, monkeypatch):
    context, _, _, _ = _case(tmp_path, monkeypatch)
    component = _deliver(tmp_path, context)
    result = metrics.accept_d30(tmp_path, context, component)
    assert _adopted(result)["status"] == "PASS", result
    assert result["status"] == "NOT_MEASURED" and result["delivery_blocked"] is True
    assert result["obligations"][1]["status"] == "UNIMPLEMENTED_METRIC_BINDING"
    selected = flow109._selected_step_result(tmp_path, context, component)
    assert selected["metric_acceptance"] == result
    assert selected["default_row_status"] == "NOT_MEASURED" and selected["completed"] is False


def test_d30_reader_refuses_unqualified_native_receipt(tmp_path, monkeypatch):
    context, _, timing, _ = _case(tmp_path, monkeypatch)
    admission = flow109.dft_preroute_admission(tmp_path, context)
    folder = tmp_path / json.loads(timing.read_text())["post_scan_arms"]["functional"]["native"]["folder"]
    (folder / "invocation.log").write_text("changed producer execution\n")
    observed = metrics.d30_consumed_timing(tmp_path, admission)
    assert observed["status"] == "NOT_MEASURED", observed
    assert observed["reason"] == "LL_STEP_OUTPUT_UNBOUND", observed


@pytest.mark.parametrize("changed", ["library", "sdc"])
def test_d30_fresh_changed_bundle_fails_independent_reference(tmp_path, monkeypatch, changed):
    context, library, timing, authority = _case(tmp_path, monkeypatch)
    approved_bytes = authority.read_bytes()
    target = library if changed == "library" else tmp_path / json.loads(timing.read_text())[
        "post_scan_arms"]["functional"]["constraint"]["path"]
    target.write_text(target.read_text() + ("/* changed model */\n" if changed == "library"
                                         else "set_clock_uncertainty 0.25 [get_clocks clk]\n"))
    _reseal_native(tmp_path, timing)
    component = _deliver(tmp_path, context)
    result = metrics.accept_d30(tmp_path, context, component)
    assert _adopted(result)["status"] == "FAIL", result
    assert result["status"] == "FAIL"
    assert result["reason"] == "D30_ADOPTED_BUNDLE_MISMATCH"
    assert authority.read_bytes() == approved_bytes
    selected = flow109._selected_step_result(tmp_path, context, component)
    assert selected["default_row_status"] == "FAIL" and selected["completed"] is False


@pytest.mark.parametrize("damage", ["stale_library", "missing_library", "unsealed_log", "stale_log",
                                    "missing_log", "foreign_native", "reader_source", "delivery_source"])
def test_d30_unproven_current_source_refused(tmp_path, monkeypatch, damage):
    context, library, timing, _ = _case(tmp_path, monkeypatch)
    component = _deliver(tmp_path, context)
    arm = json.loads(timing.read_text())["post_scan_arms"]["functional"]
    folder = tmp_path / arm["native"]["folder"]
    if damage == "stale_library":
        library.write_text("/* stale fixture library */\n")
    elif damage == "missing_library":
        library.unlink()
    elif damage in ("stale_log", "missing_log"):
        log = folder / "tt/sta.log"
        log.write_text("changed") if damage == "stale_log" else log.unlink()
    elif damage == "unsealed_log":
        receipt = json.loads((folder / "vibeic_receipt.json").read_text())
        del receipt["sha256"]["tt/sta.log"]
        _write(folder / "vibeic_receipt.json", receipt)
        _reseal_native(tmp_path, timing)
    elif damage == "foreign_native":
        manifest = json.loads(timing.read_text())
        manifest["post_scan_arms"]["functional"]["native"]["folder"] = str(tmp_path.parent)
        _write(timing, manifest)
    else:
        path = tmp_path / component["d30_delivery_receipt"]["path"]
        receipt = json.loads(path.read_text())
        field = "metric_reader_source_sha256" if damage == "reader_source" else "producer_source_sha256"
        receipt[field] = "0" * 64
        _write(path, receipt)
        component["d30_delivery_receipt"] = _ref(tmp_path, path)
    result = metrics.accept_d30(tmp_path, context, component)
    assert _adopted(result)["status"] == "NOT_MEASURED", result
    assert _adopted(result).get("reason"), result
    if damage in ("stale_library", "missing_library"):
        assert _adopted(result)["reason"] == "D30_NATIVE_INPUT_STALE_OR_MISSING", result
    elif damage == "unsealed_log":
        assert _adopted(result)["reason"] == "D30_NATIVE_READ_LOG_UNBOUND", result
    elif damage == "reader_source":
        assert _adopted(result)["reason"] == "D30_DELIVERY_READSET_STALE", result
    assert result["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("damage", ["missing", "unapproved", "stale_source", "semantic_mismatch"])
def test_d30_approval_is_bound_to_independent_source(tmp_path, monkeypatch, damage):
    context, _, _, authority = _case(tmp_path, monkeypatch)
    component = _deliver(tmp_path, context)
    body = json.loads(authority.read_text())
    if damage == "missing":
        authority.unlink()
    elif damage == "stale_source":
        (tmp_path / body["approval"]["source_reference"]["path"]).write_text("{}\n")
    else:
        if damage == "unapproved":
            body["approval"]["status"] = "DRAFT"
        else:
            body["reference"]["netlist_sha256"] = "0" * 64
        _write(authority, body)
    result = metrics.accept_d30(tmp_path, context, component)
    assert _adopted(result)["status"] == "NOT_MEASURED", result
    assert _adopted(result).get("reason"), result


@pytest.mark.parametrize("census", [None, {"required_items": []}, {"required_items": ["unexplained"]}])
def test_d30_missing_or_unexplained_census_cannot_promote_row(tmp_path, monkeypatch, census):
    context, _, _, _ = _case(tmp_path, monkeypatch)
    if census is not None:
        _write(tmp_path / "requirements/base_19/post_synth_crossing_power_changes.json", census)
    result = metrics.accept_d30(tmp_path, context, _deliver(tmp_path, context))
    assert _adopted(result)["status"] == "PASS", result
    assert result["obligations"][1]["status"] == "UNIMPLEMENTED_METRIC_BINDING"
    assert result["status"] == "NOT_MEASURED" and result["delivery_blocked"] is True
