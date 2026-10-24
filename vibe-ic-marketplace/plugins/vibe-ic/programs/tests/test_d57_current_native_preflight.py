"""D57 Default preflight selects the current STAPostPNR physical subject."""
import json
from pathlib import Path

import pytest

import _default_backend_fixtures as fixtures
import _opensta_current as current
import execution_adapters_backend as adapters
import execution_backend_producers as producers
import execution_modes as modes
import execution_policy as policy
import librelane_contract as contract
import librelane_ir_antenna as ir
from test_backend_input_contract_sdc import _project
from test_default_current_power import (
    NETLIST, SPEF, bind_original_transport, original_transport,
    project as current_power_project,
)
from test_default_step24_self_tapeout_inputs import _project as self_tapeout_project


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _install_current(project):
    _write(project / "input/step_0_5ic_answers.json", "{}\n")
    _write(project / "input/submission_template/neutral.json", "{}\n")
    native = project / "phase3/librelane/final-sta-inputs"
    views = {
        "odb": str(_write(native / "neutral.odb", "current selected ODB\n").resolve()),
        "def": str(_write(native / "neutral.def",
                          "VERSION 5.8 ;\nDESIGN neutral ;\nEND DESIGN\n").resolve()),
        "nl": str(_write(native / "neutral.v", NETLIST).resolve()),
        "sdc": str(_write(native / "neutral.sdc", "create_clock -period 10 [get_ports x]\n").resolve()),
        "spef": {"nom_typ": str(_write(native / "neutral.spef", SPEF).resolve())},
        "metrics": {},
    }
    folder, _ = fixtures.producer(
        project, "OpenROAD.STAPostPNR", views, views,
        lane="final-sta/01-openroad-stapostpnr", config_folder="22-config",
        name="neutral")
    corner = "nom_typ"
    liberty = _write(project / "fixture_pdk/neutral/neutral.lib",
                     "library(neutral_typ) { default_operating_conditions : typ; }\n")
    _write(folder / corner / "sta.log",
           f"Reading cell library for the '{corner}' corner at '/pdk/neutral/neutral.lib'\n")
    config_path = project / "phase3/librelane/22-config/OpenROAD.STAPostPNR.json"
    config = json.loads(config_path.read_text())
    config["CELL_LIBS"] = {"*": ["/pdk/neutral/neutral.lib"]}
    config_path.write_text(json.dumps(config))
    (folder / "config.json").write_text(json.dumps(config))
    fingerprint = json.loads((folder / "input_fingerprint.json").read_text())
    fingerprint.update(
        config=contract.digest(config_path),
        config_files={"/pdk/neutral/neutral.lib": contract.digest(liberty)},
        liberty_files={"/pdk/neutral/neutral.lib": contract.digest(liberty)},
    )
    (folder / "input_fingerprint.json").write_text(json.dumps(fingerprint))
    hashes = {str(path.relative_to(folder)): contract.digest(path)
              for path in folder.rglob("*")
              if path.is_file() and path.name != "vibeic_receipt.json"}
    (folder / "vibeic_receipt.json").write_text(json.dumps({
        "input": fingerprint, "sha256": hashes}))
    state = folder / "state_out.json"
    record = project / ir.CURRENT_STA_RECORD
    _write(record, json.dumps({
        "sta_state": str(state), "sta_state_sha256": contract.digest(state),
        "judgment": {"worst_setup": {"corner": corner}},
    }))
    return project, folder, {key: Path(value) for key, value in views.items()
                             if key not in {"spef", "metrics"}} | {
                                 "spef": Path(views["spef"][corner])}


def _scene(tmp_path):
    return _install_current(_project(tmp_path))


def _issued(project, mode="default"):
    parameters = {}
    policy._fixed_inputs({"project": project, "policy": {"mode": mode}},
                         "24", parameters=parameters)
    return parameters["resolved_input_manifest"]


def test_default_fixed_inputs_admit_current_native_subject_without_legacy_aliases(tmp_path):
    project, folder, views = _scene(tmp_path)
    assert not (project / "phase3/stage3/pnr/routed.def").exists()
    assert not (project / "phase3/stage3/pnr/pdn.done").exists()
    assert not (project / "phase3/stage3/pnr/pdn.tcl").exists()

    issued = _issued(project)

    assert issued["missing"] == []
    assert all("phase3/stage3/pnr/routed.def" not in str(row)
               and "phase3/stage3/pnr/pdn." not in str(row)
               for row in issued["declarations"])
    for path in (*views.values(), folder / "state_out.json",
                 folder / "config.json", folder / "vibeic_receipt.json",
                 project / ir.CURRENT_STA_RECORD):
        assert str(path.relative_to(project)) in issued["files"]


def test_default_fixed_inputs_reopen_external_original_through_owner_readset(
        tmp_path, monkeypatch):
    project, folder, _ = current_power_project(tmp_path)
    original = original_transport(tmp_path, monkeypatch, project, folder)
    fingerprint = bind_original_transport(project, folder, original)
    _write(project / "input/step_0_5ic_answers.json", "{}\n")
    _write(project / "input/submission_template/neutral.json", "{}\n")

    issued = _issued(project)

    assert issued["missing"] == []
    receipt_rel = str((folder / "vibeic_receipt.json").relative_to(project))
    state_rel = str((folder / "state_out.json").relative_to(project))
    assert {receipt_rel, state_rel}.issubset(issued["files"])
    for role in ("odb", "def", "netlist", "sdc"):
        path = original[role]
        assert fingerprint["state_files"][str(path)] == contract.digest(path)
        assert str(path) not in issued["files"]
        assert all(str(path) not in str(row) for row in issued["declarations"])
    assert not (project / "phase3/stage3/pnr/routed.def").exists()
    assert not (project / "phase3/stage3/pnr/pdn.done").exists()


@pytest.mark.parametrize("damage", ["missing_record", "changed_odb", "foreign_odb", "role_swap"])
def test_default_fixed_inputs_refuse_invalid_current_owner_without_native_start(
        tmp_path, monkeypatch, damage):
    project, folder, views = _scene(tmp_path)
    started = []
    if damage == "missing_record":
        (project / ir.CURRENT_STA_RECORD).unlink()
        issued = _issued(project)
        assert "phase3/stage3/pnr/routed.def" in issued["missing"]
        assert any("pdn.tcl OR phase3/stage3/pnr/pdn.done" in row
                   for row in issued["missing"])
    elif damage == "changed_odb":
        views["odb"].write_text("changed after current owner publication\n")
        with pytest.raises(ValueError, match="current STAPostPNR owner is invalid|odb view changed"):
            _issued(project)
    elif damage == "foreign_odb":
        foreign = _write(tmp_path / "foreign/neutral.odb", "unowned ODB\n").resolve()
        state = json.loads((folder / "state_out.json").read_text())
        state["odb"] = str(foreign)
        (folder / "state_out.json").write_text(json.dumps(state))
        marker = project / ir.CURRENT_STA_RECORD
        doc = json.loads(marker.read_text())
        doc["sta_state_sha256"] = contract.digest(folder / "state_out.json")
        marker.write_text(json.dumps(doc))
        receipt = json.loads((folder / "vibeic_receipt.json").read_text())
        receipt["input"]["state_files"][str(foreign)] = contract.digest(foreign)
        receipt["sha256"]["state_out.json"] = contract.digest(folder / "state_out.json")
        (folder / "vibeic_receipt.json").write_text(json.dumps(receipt))
        with pytest.raises(ValueError, match="current STAPostPNR owner is invalid"):
            _issued(project)
    else:
        real = current.tool_subject

        def swapped(*args, **kwargs):
            subject, tool = real(*args, **kwargs)
            rows = {row["role"]: row for row in subject["inputs"]}
            rows["netlist"]["path"] = rows["sdc"]["path"]
            rows["netlist"]["resolved"] = rows["sdc"]["resolved"]
            rows["netlist"]["sha256"] = rows["sdc"]["sha256"]
            return subject, tool

        monkeypatch.setattr(current, "tool_subject", swapped)
        with pytest.raises(ValueError, match="netlist role is mismatched"):
            _issued(project)
    assert started == []


def test_operator_and_legacy_step24_requirements_are_unchanged(tmp_path):
    project, _, _ = _scene(tmp_path)
    operator = adapters.backend_canonical_input_contract(
        project, "24", ({"from": 21, "path": "phase3/stage3/pnr/routed.def"},
                        {"from": 15, "path": "phase3/stage3/pnr/pdn.tcl OR phase3/stage3/pnr/pdn.done"}),
        execution_mode="ultra")
    assert operator == ({"from": 21, "path": "phase3/stage3/pnr/routed.def"},
                        {"from": 15, "path": "phase3/stage3/pnr/pdn.tcl OR phase3/stage3/pnr/pdn.done"})

    (project / ir.CURRENT_STA_RECORD).unlink()
    legacy = adapters.backend_canonical_input_contract(
        project, "24", operator, execution_mode="default")
    assert legacy == operator


@pytest.mark.parametrize("legacy_aliases", ["absent", "present"])
def test_default_producer_prefers_current_views_over_self_tapeout_aliases(
        tmp_path, monkeypatch, legacy_aliases):
    project, _, views = _install_current(self_tapeout_project(tmp_path))
    # This is the actual uncovered case: the old physical subject is declared,
    # but its historical files may be unavailable in the current-owner carrier.
    # Keeping them in the paired arm proves the reverse on compared path values,
    # not merely because an old alias is absent.
    if legacy_aliases == "absent":
        for path in (
            project / "phase3/stage3/pnr/chip_top.def",
            project / "phase3/stage3/pnr/core_pnr.v",
            project / "phase3/stage3/pnr/constraint.sdc",
            project / "phase3/librelane/32-unit/03-openroad-rcx/nom/chip_top.nom.spef",
        ):
            path.unlink()
    seen = {}

    class NativeEntryReached(RuntimeError):
        pass

    class Runner:
        @staticmethod
        def _librelane_step24_record(project, top, pdk, mode, spef, written,
                                     *, routed_def=None, netlist=None, sdc=None):
            seen.update(spef=Path(spef), routed_def=routed_def,
                        netlist=netlist, sdc=sdc)
            raise NativeEntryReached("controlled current D57 native entry")

    monkeypatch.setattr(producers, "_parameters", lambda *_: (
        Runner, None, type("Pdk", (), {"name": "neutral"})(), ""))
    with pytest.raises(NativeEntryReached, match="controlled current D57 native entry"):
        producers.produce_signoff(project, {
            "step_id": "24", "top": "neutral", "pdk_name": "neutral",
            "pdk_root": str(tmp_path), "image_id": "SOURCE_CONTROL_ONLY",
            "execution_mode": "default",
        })
    assert seen["spef"] == views["spef"]
    assert seen["routed_def"] is None
    assert seen["netlist"] is None
    assert seen["sdc"] is None


def test_default_producer_refuses_stale_current_before_self_tapeout_fallback(
        tmp_path, monkeypatch):
    project, _, views = _install_current(self_tapeout_project(tmp_path))
    views["spef"].write_text(views["spef"].read_text() + "stale\n")
    entered = []

    class Runner:
        @staticmethod
        def _librelane_step24_record(*args, **kwargs):
            entered.append((args, kwargs))

    monkeypatch.setattr(producers, "_parameters", lambda *_: (
        Runner, None, type("Pdk", (), {"name": "neutral"})(), ""))
    with pytest.raises(modes.Refusal, match="BACKEND_CURRENT_SPEF_INVALID: LL_INPUT_CHANGED"):
        producers.produce_signoff(project, {
            "step_id": "24", "top": "neutral", "pdk_name": "neutral",
            "pdk_root": str(tmp_path), "image_id": "SOURCE_CONTROL_ONLY",
            "execution_mode": "default",
        })
    assert entered == []
