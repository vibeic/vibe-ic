"""Focused D42 source controls; native GF180 evidence is retained separately."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import flow109_route_check as route


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()




def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return path


def _receipt(folder, step, state, *, reports=(), invocation="actual native fixture output\n"):
    folder.mkdir(parents=True, exist_ok=True)
    state_path = _json(folder / "state_out.json", state)
    fingerprint = {"step": step}
    _json(folder / "input_fingerprint.json", fingerprint)
    _json(folder / "pdk_root.json", {"cli_pdk_root": "/pdk"})
    (folder / "invocation.log").write_text(invocation)
    hashes = {name: _sha(folder / name) for name in
              ("state_out.json", "input_fingerprint.json", "pdk_root.json", "invocation.log")}
    for name, content in reports:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        hashes[name] = _sha(path)
    _json(folder / "vibeic_receipt.json", {"input": fingerprint, "sha256": hashes})
    return state_path




def _context():
    return {}


def _d41(project, monkeypatch, *, pdk_name="gf180mcuD",
         image="ghcr.io/vibeic/vibeic-eda@sha256:" + "6" * 64,
         adopted="32-cand09"):
    monkeypatch.setenv("VIBEIC_EDA_IMAGE", image)
    monkeypatch.setenv("VIBEIC_LIBRELANE_IMAGE", image)
    pdk = project / "pdk"
    (pdk / pdk_name).mkdir(parents=True)
    monkeypatch.setenv("VIBEIC_LIBRELANE_PDK_ROOT", str(pdk))
    _json(project / "reports/phase3/default_steps/32/backend_result.json", {
        "producer_verdict": "PASS",
        "gates": {"backend_canonical": "PASS", "backend_native_substance": "PASS"}})
    lane = adopted or "32-base"
    folder = project / "phase3/librelane" / lane / "01-vibeic-postrouterepair"
    views = {}
    for name, content in (("def", "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n"),
                          ("odb", "ODB\n"), ("nl", "module chip_top; endmodule\n"),
                          ("pnl", "module chip_top; endmodule\n"),
                          ("sdc", "create_clock -period 10 clk\n")):
        views[name] = folder / ("chip_top." + ("nl.v" if name == "nl" else
                                               "pnl.v" if name == "pnl" else name))
        views[name].parent.mkdir(parents=True, exist_ok=True)
        views[name].write_text(content)
    state = {name: str(path) for name, path in views.items()}
    state["metrics"] = {"route__drc_errors": 0}
    _json(project / "state_out.json", state)
    _json(project / "config.json", {"PDK": pdk_name, "STD_CELL_LIBRARY": "sc"})
    _receipt(folder, "Vibeic.PostRouteRepair", state)
    _json(folder / "config.json", {"PDK": pdk_name, "STD_CELL_LIBRARY": "sc"})
    # config.json is an output in a real receipt; bind it after the helper made
    # the minimal receipt.
    receipt = json.loads((folder / "vibeic_receipt.json").read_text())
    receipt["sha256"].update({path.name: _sha(path) for path in views.values()})
    receipt["sha256"]["config.json"] = _sha(folder / "config.json")
    _json(folder / "vibeic_receipt.json", receipt)
    live_def = project / "phase3/stage3/pnr/routed.def"
    live_nl = project / "phase3/stage3/pnr/subservient_pnr.v"
    live_def.parent.mkdir(parents=True, exist_ok=True)
    live_def.write_bytes(views["def"].read_bytes())
    live_nl.write_bytes(views["nl"].read_bytes())
    _json(project / "reports/phase3/librelane_postroute_repair.json", {
        "adopted": adopted, "adopted_state": str(folder / "state_out.json")})
    _json(project / "reports/phase3/librelane_postroute_repair_handoff.json", {
        "state": str(folder / "state_out.json"), "state_sha256": _sha(folder / "state_out.json"),
        "views": {
            "def": {"source": str(views["def"]), "source_sha256": _sha(views["def"]),
                    "dest": str(live_def), "dest_sha256": _sha(live_def)},
            "nl": {"source": str(views["nl"]), "source_sha256": _sha(views["nl"]),
                   "dest": str(live_nl), "dest_sha256": _sha(live_nl)}}})
    return views


def _native_folders(project, lane, *, route_errors=0, disconnected=0, critical=None,
                    wire_max=25, wire_threshold="100", omit_report=None,
                    disconnected_table="Pin,Reason\n"):
    critical = disconnected if critical is None else critical
    values = {
        "Checker.TrDRC": {"route__drc_errors": route_errors},
        "Odb.ReportDisconnectedPins": {
            "design__disconnected_pin__count": disconnected,
            "design__critical_disconnected_pin__count": critical},
        "Checker.DisconnectedPins": {"design__critical_disconnected_pin__count": critical},
        "Odb.ReportWireLength": {"route__wirelength__max": wire_max},
        "Checker.WireLength": {"route__wirelength__max": wire_max},
    }
    folders = []
    for index, step in enumerate(route.STEPS, 1):
        folder = project / "phase3/librelane" / lane / f"{index:02d}-{step.lower().replace('.', '-')}"
        reports = []
        if step == "Odb.ReportDisconnectedPins" and omit_report != "disconnected":
            reports.append(("full_disconnected_pins_table.txt", disconnected_table))
        if step == "Odb.ReportWireLength" and omit_report != "wire":
            reports.append(("wire_lengths.csv", "net,length_um\n"))
        invocation = ("Threshold for Threshold-surpassing long wires is not set. "
                      "The checker will be skipped.\n"
                      if step == "Checker.WireLength" and wire_threshold is None
                      else "actual native fixture output\n")
        _receipt(folder, step, {"metrics": values[step]}, reports=reports,
                 invocation=invocation)
        _json(folder / "config.json", {"meta": {"step": step},
                                       "WIRE_LENGTH_THRESHOLD": wire_threshold})
        folders.append(folder)
    return folders




def test_whole_d42_adapter_positive_uses_native_consumer(tmp_path, monkeypatch):
    _d41(tmp_path, monkeypatch)
    configs = {}
    for step in route.STEPS:
        configs[step] = _json(tmp_path / "configs" / f"{step}.json", {
            "meta": {"step": step}, "WIRE_LENGTH_THRESHOLD": "100"})
    monkeypatch.setattr(route.contract, "resolve_step_configs", lambda *a, **k: configs)
    monkeypatch.setattr(route.contract, "run_chain", lambda project, image, steps, **kw:
                        _native_folders(project, kw["lane"]))
    result = route.execute(tmp_path, _context())
    assert result["measurements"]["route_short_overlap_errors"] == 0
    assert result["measurements"]["disconnected_required_pins"] == 0


def test_prepare_accepts_supported_non_gf180_route_and_runtime_image(
        tmp_path, monkeypatch):
    image = "ghcr.io/vibeic/vibeic-eda@sha256:" + "a" * 64
    _d41(tmp_path, monkeypatch, pdk_name="sky130A", image=image)
    prepared = route.prepare(tmp_path, _context())
    assert prepared["image"] == image
    assert prepared["pdk"] == "sky130A"




def test_native_checker_errors_remain_enabled(tmp_path, monkeypatch):
    _d41(tmp_path, monkeypatch)
    configs = {step: _json(tmp_path / "configs" / f"{step}.json", {
        "meta": {"step": step}, "WIRE_LENGTH_THRESHOLD": "100"})
        for step in route.STEPS}
    seen = {}

    def resolve(*args, **kwargs):
        seen.update(kwargs["overlay"])
        return configs

    monkeypatch.setattr(route.contract, "resolve_step_configs", resolve)
    monkeypatch.setattr(route.contract, "run_chain", lambda project, image, steps, **kw:
                        _native_folders(project, kw["lane"]))
    assert route.execute(tmp_path, _context())["component_status"] == "PASS"
    assert {key: value for key, (value, _) in seen.items()} == {
        "ERROR_ON_TR_DRC": True,
        "ERROR_ON_DISCONNECTED_PINS": True,
        "ERROR_ON_LONG_WIRE": True,
        "ERROR_ON_MISSING_METRIC": True,
    }


def test_common_step_result_reader_accepts_custom_shape_and_keeps_not_run(tmp_path):
    custom = {"step": "Checker.TrDRC", "case": "custom", "config": {},
              "status": "PASS", "metrics": {"route__drc_errors": 0},
              "scope": "custom_step", "log": {}}
    assert route._step_result(custom, "Checker.TrDRC", tmp_path) == custom
    absent = route._step_result(tmp_path / "never-ran", "Checker.TrDRC", tmp_path)
    assert absent["status"] == "NOT_RUN"


def test_native_checker_fail_stays_fail_and_later_steps_stay_not_run(
        tmp_path, monkeypatch):
    _d41(tmp_path, monkeypatch)
    configs = {step: _json(tmp_path / "configs" / f"{step}.json", {
        "meta": {"step": step}, "WIRE_LENGTH_THRESHOLD": "100"})
        for step in route.STEPS}
    monkeypatch.setattr(route.contract, "resolve_step_configs", lambda *a, **k: configs)

    def native_fail(project, image, steps, **kwargs):
        folder = project / "phase3/librelane" / kwargs["lane"] / "01-checker-trdrc"
        _json(folder / "config.json", {"meta": {"step": "Checker.TrDRC"},
                                       "ERROR_ON_TR_DRC": True})
        _json(folder / "state_in.json", {"metrics": {"route__drc_errors": 1}})
        (folder / "invocation.log").write_text("1 Routing DRC errors found. - deferred\n")
        raise route.contract.Refusal("LL_STEP_FAILED", "Checker.TrDRC: rc=255")

    monkeypatch.setattr(route.contract, "run_chain", native_fail)
    result = route.execute(tmp_path, _context())
    rows = result["native_steps"]
    assert rows[0]["status"] == "FAIL"
    assert [row["status"] for row in rows[1:]] == ["NOT_RUN"] * 4


def test_native_inactive_pin_classification_is_not_rewritten(tmp_path, monkeypatch):
    _d41(tmp_path, monkeypatch)
    configs = {step: _json(tmp_path / "configs" / f"{step}.json", {
        "meta": {"step": step}, "WIRE_LENGTH_THRESHOLD": "100"})
        for step in route.STEPS}
    monkeypatch.setattr(route.contract, "resolve_step_configs", lambda *a, **k: configs)
    monkeypatch.setattr(route.contract, "run_chain", lambda project, image, steps, **kw:
        _native_folders(project, kw["lane"], disconnected=1, critical=0))
    result = route.execute(tmp_path, _context())
    assert result["component_status"] == "PASS"
    assert result["measurements"]["native_disconnected_pins"] == 1
    assert result["measurements"]["native_critical_disconnected_pins"] == 0
    assert result["measurements"]["disconnected_required_pins"] == 0


def test_unset_pdk_wire_threshold_is_disclosed_not_an_invented_requirement(
        tmp_path, monkeypatch):
    _d41(tmp_path, monkeypatch)
    configs = {step: _json(tmp_path / "configs" / f"{step}.json", {
        "meta": {"step": step}, "WIRE_LENGTH_THRESHOLD": None}) for step in route.STEPS}
    monkeypatch.setattr(route.contract, "resolve_step_configs", lambda *a, **k: configs)
    monkeypatch.setattr(route.contract, "run_chain", lambda project, image, steps, **kw:
        _native_folders(project, kw["lane"], wire_threshold=None))
    result = route.execute(tmp_path, _context())
    assert result["component_status"] == "PASS"
    assert result["wire_length_check"]["status"] == "NOT_APPLICABLE"
    assert result["measurements"]["wire_length_threshold_um"] is None










@pytest.mark.parametrize(
    "route_errors,disconnected,omit,expected,reason",
    [(1, 0, None, "FAIL", "D42_NATIVE_CHECK_FAILED"),
     (0, 2, None, "FAIL", "D42_NATIVE_CHECK_FAILED"),
     (0, 0, "disconnected", "NOT_MEASURED", "D42_DISCONNECTED_REPORT_EMPTY"),
     (0, 0, "wire", "NOT_MEASURED", "D42_WIRE_REPORT_EMPTY")])
def test_native_fail_and_missing_reports_never_pass(
        tmp_path, monkeypatch, route_errors, disconnected, omit, expected, reason):
    _d41(tmp_path, monkeypatch)
    configs = {step: _json(tmp_path / "configs" / f"{step}.json", {
        "meta": {"step": step}, "WIRE_LENGTH_THRESHOLD": "100"}) for step in route.STEPS}
    monkeypatch.setattr(route.contract, "resolve_step_configs", lambda *a, **k: configs)
    monkeypatch.setattr(route.contract, "run_chain", lambda project, image, steps, **kw:
        _native_folders(project, kw["lane"], route_errors=route_errors,
                        disconnected=disconnected, omit_report=omit))
    result = route.execute(tmp_path, _context())
    assert result["component_status"] == expected
    assert result["reason"] == reason
    assert result["component_status"] != "PASS"
