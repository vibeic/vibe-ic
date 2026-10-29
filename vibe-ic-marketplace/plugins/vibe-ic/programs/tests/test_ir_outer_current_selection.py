"""SOFTWARE route controls only; no native solver or platform qualification."""
import json
from types import SimpleNamespace

import pytest

import _opensta_current as current
import librelane_ir_antenna as ir
import phase3_one_shot_runner as runner
from librelane_contract import Refusal
from test_d57_current_native_odb import IMAGE, _current_scene, _write


def _outer(tmp_path, monkeypatch, *, mode="librelane", damage=None, em_only=False):
    project, pdk_root, paths, state = _current_scene(tmp_path, monkeypatch)
    if damage == "missing":
        paths["def"].unlink()
    elif damage == "changed":
        paths["def"].write_text(paths["def"].read_text() + "changed\n")
    elif damage == "invalid":
        state.write_text("invalid State\n")
    elif damage == "foreign_owner":
        def foreign(*_args, **_kwargs):
            raise current.Refusal("CURRENT_DEF_FOREIGN_PATH")
        monkeypatch.setattr(current, "tool_subject", foreign)
    elif damage == "absent_owner":
        (project / ir.CURRENT_STA_RECORD).unlink()
    monkeypatch.setattr(runner, "_librelane_step_ctx", lambda *_: (IMAGE, pdk_root))
    monkeypatch.setattr(runner, "_step24_primary_mode", lambda *_: mode)
    monkeypatch.setattr(runner, "_discover_power_nets", lambda *_: (["P"], ["G"]))
    calls = []

    def marker(_project, _image, _root, _pdk, **kwargs):
        calls.append({"native_boundary": "TEST_ONLY_NOT_NATIVE", **{
            role: str(kwargs[role]) for role in ("routed_def", "netlist", "sdc", "spef")},
            "selected_records": kwargs["expected_current_records"]})
        raise Refusal("SOFTWARE_PRIMARY_CALL_REACHED", "no native execution")

    monkeypatch.setattr(ir, "run_ir", marker)
    # An unqualified EM solve must not consume the current IR scene.
    monkeypatch.setattr(runner, "_docker_exec", lambda *_a, **_k: pytest.fail("unexpected direct/EM tool"))
    legacy = project / "phase3/stage3/pnr/neutral.def"
    assert not legacy.exists()
    report = project / "reports/phase3/ir_drop_librelane.json"
    notes = []
    result = runner._emit_ir_em_reports(project, "neutral", SimpleNamespace(name="neutral"),
        "SOFTWARE_ONLY", project / "reports/phase3/ir_drop.rpt",
        project / "reports/phase3/em.rpt", notes, em_only=em_only)
    observed = {"result": result, "calls": calls, "notes": notes,
                "primary": json.loads(report.read_text()) if report.exists() else None,
                "legacy_created": legacy.exists(), "software_only": True}
    _write(project / "OUTER_OBSERVATION.json", json.dumps(observed, indent=2))
    return project, paths, observed


@pytest.mark.parametrize("mode", ["librelane", "dual"])
def test_outer_current_primary_reaches_normal_consumer_without_legacy_def(tmp_path, monkeypatch, mode):
    project, paths, observed = _outer(tmp_path, monkeypatch, mode=mode)
    assert len(observed["calls"]) == 1, observed
    call = observed["calls"][0]
    assert {role: call[role] for role in ("routed_def", "netlist", "sdc", "spef")} == {
        role: str(paths[key]) for role, key in (
            ("routed_def", "def"), ("netlist", "nl"), ("sdc", "sdc"), ("spef", "spef"))}
    assert set(call["selected_records"]) == {"odb", "def", "netlist", "sdc", "spef",
        "sta_state", "sta_receipt", "sta_config", "step23_record"}
    assert observed["result"] == (False, False)  # marker is a refusal, never PASS
    assert "SOFTWARE_PRIMARY_CALL_REACHED" in str(observed["primary"])
    assert not observed["legacy_created"]
    assert not (project / "reports/phase3/em.json").exists()


@pytest.mark.parametrize("damage,reason", [
    ("invalid", "refused"),
    ("missing", "LL_IR_CURRENT_VIEW_MISSING"),
    ("changed", "LL_IR_CURRENT_VIEW_CHANGED"),
    ("foreign_owner", "LL_IR_CURRENT_STA_INVALID"),
])
def test_outer_invalid_current_owner_never_reaches_primary_or_falls_back(tmp_path, monkeypatch, damage, reason):
    _, _, observed = _outer(tmp_path, monkeypatch, damage=damage)
    assert observed["calls"] == []
    assert observed["result"] == (False, False)
    assert observed["primary"] is not None, observed
    assert observed["primary"]["judgment"]["verdict"] == "NOT_MEASURED"
    assert reason in str(observed["primary"])
    assert not observed["legacy_created"]


@pytest.mark.parametrize("mode,damage,em_only", [
    ("librelane", "absent_owner", False),
    ("direct", None, False),
    ("librelane", None, True),
])
def test_outer_absent_owner_direct_and_em_only_keep_legacy_missing_refusal(tmp_path, monkeypatch, mode, damage, em_only):
    _, _, observed = _outer(tmp_path, monkeypatch, mode=mode, damage=damage, em_only=em_only)
    assert observed["calls"] == []
    assert observed["primary"] is None
    assert observed["result"] == (False, False)
    assert observed["notes"] == ["IR/EM skipped: routed DEF missing"]


@pytest.mark.parametrize("mode", ["librelane", "dual"])
@pytest.mark.parametrize("measurement", ["PASS", "FAIL"])
def test_outer_current_primary_uses_actual_adoption_without_claiming_em(
        tmp_path, monkeypatch, mode, measurement):
    # Only the native transport is instrumented. The normal selector, record
    # builder, adoption and final current-source validator run unchanged.
    import em_current_density_check as emc
    from test_d57_current_native_odb import _sha
    project, root, paths, _ = _current_scene(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_librelane_step_ctx", lambda *_: (IMAGE, root))
    monkeypatch.setattr(runner, "_step24_primary_mode", lambda *_: mode)
    monkeypatch.setattr(runner, "_discover_power_nets", lambda *_: (["VDD"], ["VSS"]))
    monkeypatch.setattr(runner, "_docker_exec", lambda *_a, **_k: pytest.fail("unexpected EM solve"))
    calls = []

    def software_transport(_project, _image, _root, _pdk, **kwargs):
        calls.append(kwargs)
        folder = project / "phase3/librelane/24/01-openroad-irdropreport"
        drop = 0.6 if measurement == "FAIL" else 0.01
        output = _write(folder / "state_out.json", json.dumps({"metrics": {
            "design_powergrid__drop__worst__net:" + net: drop for net in ("VDD", "VSS")}}))
        _write(folder / "state_in.json", json.dumps({"odb": str(paths["odb"]),
            "sdc": str(paths["sdc"]), "spef": {"unit": str(paths["spef"])}}))
        tech = _write(folder / "tech.lef", "SOFTWARE instrument technology bytes\n")
        lib = _write(folder / "timing.lib", "library(neutral) {}\n")
        _write(project / "phase3/librelane/24-config/OpenROAD.IRDropReport.json", json.dumps({
            "DEFAULT_CORNER": "unit", "TECH_LEFS": {"unit": str(tech)}}))
        _write(folder / "openroad-irdropreport.log",
            "Reading timing library for the 'unit' corner at '" + str(lib) + "'\n")
        _write(folder / "irdrop.rpt", "SOFTWARE transport, NOT native qualification\n" +
            "".join(f"neutral grid node {i}: voltage drop {drop} V\n" for i in range(40)))
        selected = ir._current_stapostpnr_ir_inputs(project, IMAGE, root, "neutral", {"DESIGN_NAME": "neutral"})
        return {"tool_state": str(output), "tool_state_sha256": _sha(output),
            "def_sha256": _sha(kwargs["routed_def"]), "spef_sha256": _sha(kwargs["spef"]),
            "vdd_nets": ["VDD"], "gnd_nets": ["VSS"], "lib_voltage_v": 5.0,
            "budget_pct": 10.0, "budget_source": "SOFTWARE instrument budget",
            "rc_model": {"verdict": "AGREE", "disagreeing": []},
            "cross_check": {"verdict": "MEASURED", "per_net_worst_drop_v": {"VDD": drop, "VSS": drop}},
            "transient": {"verdict": "MEASURED", "max_dynamic_drop_mv": 10.0, "vdd": 5.0},
            "input_mode": "current_stapostpnr_odb", "selected_inputs": selected["records"],
            "input_source_chain": {key: selected[key] for key in ("source", "image", "pdk_root", "pdk")}}

    monkeypatch.setattr(ir, "run_ir", software_transport)
    result = runner._emit_ir_em_reports(project, "neutral", SimpleNamespace(name="neutral"),
        "SOFTWARE_ONLY", project / "reports/phase3/ir_drop.rpt",
        project / "reports/phase3/em.rpt", [])
    validation = emc.validate_primary_ir(project)
    _write(project / "ADOPTION_OBSERVATION.json", json.dumps({"software_only": True,
        "result": result, "validation": validation, "native_boundary_calls": len(calls)}, indent=2))
    assert result == (True, False), validation  # valid measured FAIL stays FAIL below
    assert len(calls) == 1
    assert validation["valid"] is True, validation
    assert validation["verdict"] == measurement, validation
    assert not (project / "phase3/stage3/pnr/neutral.def").exists()
    assert not (project / "reports/phase3/em.json").exists()
    assert not (project / "reports/phase3/em_openroad_density.json").exists()
