"""Neutral instrument writes; real Default producer, adoption and consumers."""
import hashlib
import json
from pathlib import Path

import pytest

import _opensta_current as sta_current
import em_current_density_check as emc
import execution_adapters_backend as adapters
import execution_backend_producers as backend
import execution_policy as policy
import librelane_ir_antenna as la
import phase3_one_shot_runner as runner
import step_output_collector as versions
from test_backend_input_contract_sdc import _project
from test_pad_connected_pdn_ring import _pdk
from test_d57_current_native_odb import _current_scene as _sta_scene, _record as _sta_record


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs(tmp_path):
    root = _project(tmp_path)
    for rel in ("input/step_0_5ic_answers.json", "input/submission_template/neutral.json"):
        _write(root, rel, "{}\n")
    for rel in ("phase3/stage3/pnr/routed.def", "phase3/stage3/pnr/neutral.def"):
        _write(root, rel, "DESIGN neutral ;\nEND DESIGN\n")
    _write(root, "phase3/stage3/pnr/neutral_pnr.v", "module neutral; endmodule\n")
    _write(root, "phase3/stage3/pnr/pdn.done", "native PDN completed\n")
    _write(root, "phase3/stage3/extracted/neutral.spef", "*SPEF neutral\n")
    _write(root, "phase2/stage2/constraints/pvt_matrix.json", "{}\n")
    return root


def _contract(project, mode):
    # Exercise the shared issuer, including its actual mode handoff, rather
    # than depending on a new helper keyword unavailable on the red product.
    issued = {}
    policy._fixed_inputs({"project": project, "policy": {"mode": mode}}, "23", parameters=issued)
    return issued["resolved_input_manifest"]["files"]


@pytest.mark.parametrize("case", ["current", "native_fail", "missing_native",
    "changed_input", "changed_artifact", "changed_liberty", "changed_tool_state", "missing_liberties"])
def test_default_step24_adopts_its_current_native_primary(tmp_path, monkeypatch, case):
    project = _inputs(tmp_path)
    pdk = _pdk(tmp_path, ring=None)
    monkeypatch.setattr(runner, "_backend_parameter_values", lambda *_: {
        "pdk_root": str(tmp_path), "image_id": "SOURCE_CONTROL_ONLY"})
    seen = {}
    def parameters(_root, params):
        seen["manifest"] = params["resolved_input_manifest"]
        return runner, None, pdk, "SOURCE_CONTROL_ONLY"
    monkeypatch.setattr(backend, "_parameters", parameters)
    monkeypatch.setattr(runner, "_librelane_step_ctx", lambda *_: ("SOURCE_CONTROL_ONLY", tmp_path))
    calls = []
    assets = {}

    def instrument(root, *_args, **kw):
        calls.append("native_ir_transport")
        if case == "missing_native":
            raise ValueError("neutral instrument did not produce a native result")
        folder = "phase3/librelane/24/01-openroad-irdropreport"
        drop = 0.6 if case == "native_fail" else 0.01
        metrics = {"design_powergrid__drop__worst__net:" + net: drop for net in ("VDD", "VSS")}
        state = _write(root, folder + "/state_out.json", json.dumps({"metrics": metrics}))
        odb = _write(root, folder + "/input.odb", "neutral ODB instrument bytes\n")
        tech = _write(root, folder + "/tech.lef", "neutral technology instrument bytes\n")
        lib = _write(root, folder + "/timing.lib", "library(neutral) {}\n")
        _write(root, folder + "/state_in.json", json.dumps({"odb": str(odb),
            "sdc": str(kw["sdc"]), "spef": {"unit": str(kw["spef"])}}))
        _write(root, "phase3/librelane/24-config/OpenROAD.IRDropReport.json", json.dumps({
            "DEFAULT_CORNER": "unit", "TECH_LEFS": {"unit": str(tech)}}))
        _write(root, folder + "/openroad-irdropreport.log",
            "Reading timing library for the 'unit' corner at '" + str(lib) + "'\n")
        _write(root, folder + "/irdrop.rpt", "OpenROAD PSM static IR source-control report\n" +
            "".join(f"neutral grid node {i}: voltage drop {drop} V\n" for i in range(40)))
        # The real runner appends its tool invocation to this audit-only log.
        with (root / "provenance.jsonl").open("a") as stream:
            stream.write('{"record":"neutral invocation"}\n')
        assets.update(state=state, liberty=lib, report=root / folder / "irdrop.rpt")
        return {"tool_state": str(state), "tool_state_sha256": _sha(state),
            "def_sha256": _sha(kw["routed_def"]), "spef_sha256": _sha(kw["spef"]),
            "vdd_nets": ["VDD"], "gnd_nets": ["VSS"], "lib_voltage_v": 5.0,
            "budget_pct": 10.0, "budget_source": "neutral instrument budget",
            "rc_model": {"verdict": "AGREE", "disagreeing": []},
            "cross_check": {"verdict": "MEASURED", "per_net_worst_drop_v": {"VDD": drop, "VSS": drop}},
            "transient": {"verdict": "MEASURED", "max_dynamic_drop_mv": 10.0, "vdd": 5.0}}

    monkeypatch.setattr(la, "run_ir", instrument)
    original = runner._librelane_step24_publish
    publishes = []

    def publish(root, doc):
        original(root, doc)
        publishes.append(True)
        if len(publishes) == 1:
            if case == "missing_liberties":
                doc["native_basis"]["liberties"] = []
                _write(root, "reports/phase3/ir_drop_librelane.json", json.dumps(doc))
            target = {"changed_input": root / "phase3/stage3/pnr/constraint.sdc",
                      "changed_artifact": assets.get("report"),
                      "changed_liberty": assets.get("liberty"),
                      "changed_tool_state": assets.get("state")}.get(case)
            if target:
                target.write_text(target.read_text() + "\nchanged\n")

    monkeypatch.setattr(runner, "_librelane_step24_publish", publish)
    row = runner._default_pnr_rows(project, "neutral", pdk, "SOURCE_CONTROL_ONLY", ["24"])
    doc = json.loads((project / "reports/phase3/ir_drop_librelane.json").read_text())
    receipt = json.loads((project / "reports/phase3/default_steps/24/backend_result.json").read_text())
    validation = emc.validate_primary_ir(project)
    valid, verdict = validation["valid"], validation.get("verdict")
    _write(project, "API_OBSERVATION.json", json.dumps({"case": case, "status": row.status,
        "detail": row.detail, "primary": doc, "receipt": receipt,
        "validation": [valid, verdict], "calls": calls, "seen": seen,
        "source_control_only": True}, indent=2))
    # The whole Default row retains its existing failed-producer FAIL;
    # the unavailable primary remains explicitly NOT_MEASURED underneath.
    expected = "PASS" if case == "current" else "FAIL"
    assert calls == ["native_ir_transport"]
    assert row.status == expected, row.detail
    assert not (project / "reports/phase3/ir_drop_psm_cross_check.json").exists()
    assert "power_basis" not in doc
    if case in ("current", "native_fail"):
        assert doc["adopted"] is True
        assert valid is True
        assert verdict == expected
        assert doc["judgment"]["verdict"] == expected
    else:
        assert valid is False
        assert verdict == "NOT_MEASURED"
    if case == "current":
        assert "provenance.jsonl" not in seen["manifest"]["files"]
        assert receipt["canonical_step_result"]["status"] == "PASS"
        assert versions.latest_pass(project, "24")["current_inputs"] is True
        with (project / "provenance.jsonl").open("a") as stream:
            stream.write('{"record":"next producer"}\n')
        assert versions.latest_pass(project, "24")["current_inputs"] is True
        (project / "phase3/stage3/pnr/routed.def").write_text("changed real layout\n")
        assert versions.latest_pass(project, "24")["current_inputs"] is False


@pytest.mark.parametrize("changed", ["journal", "step8", "sdc"])
def test_default_step23_checkpoint_keeps_scientific_inputs_current(tmp_path, changed):
    project = _inputs(tmp_path)
    issued = {}
    policy._fixed_inputs({"project": project, "policy": {"mode": "default"}}, "23", parameters=issued)
    files = issued["resolved_input_manifest"]["files"]
    assert "provenance.jsonl" not in files
    assert "phase3/librelane/prelayout/gates/step8_sdc_opensta.json" in files
    assert "phase2/stage2/constraints/spm.asic.sdc" in files
    # Exercise the existing version API with neutral output bytes. This is
    # a source-level currentness control, not a Step23 native qualification.
    from execution_adapters_backend import ROWS
    row = ROWS["23"]["canonical_row"]
    for spec in row.get("required_outputs", []):
        for alternative in spec.split(" OR "):
            _write(project, alternative.strip().replace("*", "neutral"), "neutral output\n")
    attempt = versions.begin_step(project, "23", files)
    versions.finish_step(project, attempt, verdict="PASS", canonical_pass=True)
    assert versions.latest_pass(project, "23")["current_inputs"] is True
    rel = {"journal": "provenance.jsonl", "step8": "phase3/librelane/prelayout/gates/step8_sdc_opensta.json",
           "sdc": "phase2/stage2/constraints/spm.asic.sdc"}[changed]
    with (project / rel).open("a") as stream:
        stream.write("next producer\n")
    assert versions.latest_pass(project, "23")["current_inputs"] is (changed == "journal")


def test_ultra_transport_and_explicit_step7_journal_binding_are_retained(tmp_path):
    project = _inputs(tmp_path)
    assert "provenance.jsonl" in _contract(project, "ultra")
    step7 = project / "phase2/stage2/constraints/asic_sdc.json"
    doc = json.loads(step7.read_text())
    doc["inputs"] = {"provenance.jsonl": _sha(project / "provenance.jsonl")}
    step7.write_text(json.dumps(doc))
    assert "provenance.jsonl" in _contract(project, "default")


def test_default_reads_semantic_image_live_but_keeps_explicit_file_bindings(tmp_path):
    project = _inputs(tmp_path)
    report = _write(project, "reports/container_image.json", json.dumps({
        "image_id": "sha256:neutral", "container": "first", "verdict": "PASS"}))
    step7 = project / "phase2/stage2/constraints/asic_sdc.json"
    doc = json.loads(step7.read_text())
    doc["inputs"] = {"@container_image": "semantic image binding"}
    step7.write_text(json.dumps(doc))
    default = _contract(project, "default")
    ultra = _contract(project, "ultra")
    assert "reports/container_image.json" not in default
    assert "phase2/stage2/constraints/asic_sdc.json" in default
    assert "reports/container_image.json" in ultra
    report.write_text(report.read_text().replace("first", "next"))
    assert default == _contract(project, "default")
    doc["inputs"]["reports/container_image.json"] = _sha(report)
    step7.write_text(json.dumps(doc))
    assert "reports/container_image.json" in _contract(project, "default")


@pytest.mark.parametrize("changed", ["em_current_density_check.py",
                                    "em_peak_current_authority_check.py",
                                    "_emit_em_current_authority"])
def test_current_ir_keeps_its_measured_failure_after_em_only_source_changes(
        tmp_path, monkeypatch, changed):
    # The existing real adoption/consumer fixture establishes a current FAIL.
    # Reading it under a later EM-only source must preserve that measured FAIL,
    # without upgrading or rewriting the retained native receipt.
    test_default_step24_adopts_its_current_native_primary(tmp_path, monkeypatch, "native_fail")
    project = tmp_path / "project"
    receipt = project / "reports/phase3/ir_drop_librelane.json"
    original_bytes = receipt.read_bytes()
    current = emc.native_source_identity()
    assert changed in current
    current[changed] = "0" * 64
    monkeypatch.setattr(emc, "native_source_identity", lambda: dict(current))
    result = emc.validate_primary_ir(project)
    assert result["valid"] is True, result
    assert result["verdict"] == "FAIL", result
    assert receipt.read_bytes() == original_bytes


def test_current_ir_rebinds_intact_project_relative_native_paths(tmp_path, monkeypatch):
    """A relocated project consumes identical retained bytes without receipt edits."""
    test_default_step24_adopts_its_current_native_primary(tmp_path, monkeypatch, "current")
    original = tmp_path / "project"
    receipt_rel = Path("reports/phase3/ir_drop_librelane.json")
    receipt_bytes = (original / receipt_rel).read_bytes()
    relocated = tmp_path / "relocated"
    original.rename(relocated)
    result = emc.validate_primary_ir(relocated)
    assert result["valid"] is True, result
    assert result["verdict"] == "PASS", result
    assert (relocated / receipt_rel).read_bytes() == receipt_bytes


def _external_current_primary(tmp_path, monkeypatch, case="current"):
    """Turn the existing neutral IR result into a real current-owner receipt."""
    test_default_step24_adopts_its_current_native_primary(tmp_path, monkeypatch, case)
    project, pdk_root, paths, state = _sta_scene(tmp_path, monkeypatch)
    original = tmp_path / "adopted-original"
    external = {
        "odb": _write(original, "neutral.odb", paths["odb"].read_text()),
        "def": _write(original, "neutral.def", paths["def"].read_text()),
    }
    paths.update(external)
    state.write_text(json.dumps({
        "odb": str(paths["odb"]), "def": str(paths["def"]),
        "nl": str(paths["nl"]), "sdc": str(paths["sdc"]),
        "spef": {"max_*": str(paths["spef"])}, "metrics": {},
    }))
    receipt = state.parent / "vibeic_receipt.json"
    receipt.write_text(json.dumps({"input": {"state_files": {
        str(path): _sha(path) for path in paths.values()
    }}}))
    subject, tool = sta_current.tool_subject(project, "neutral")
    roles = {row["role"]: row for row in subject["inputs"]}
    roles["tool_state"].update(_sta_record(state, "tool_state"))
    roles["tool_receipt"].update(_sta_record(receipt, "tool_receipt"))
    monkeypatch.setattr(sta_current, "tool_subject",
                        lambda *_args, **_kwargs: (subject, tool))
    selected = la._current_stapostpnr_ir_inputs(
        project, tool["image"], pdk_root, "neutral", {"DESIGN_NAME": "neutral"})

    report = project / "reports/phase3/ir_drop_librelane.json"
    doc = json.loads(report.read_text())
    doc["inputs"] = {role: dict(selected["records"][role])
                     for role in ("def", "netlist", "sdc", "spef")}
    doc["record"].update({
        "input_mode": "current_stapostpnr_odb",
        "selected_inputs": selected["records"],
        "input_source_chain": {key: selected[key] for key in
                               ("source", "image", "pdk_root", "pdk")},
    })
    for role in ("odb", "sdc", "spef"):
        row = selected["records"][role]
        path = Path(row["path"])
        path = path if path.is_absolute() else project / path
        doc["native_basis"][role] = {"path": str(path.resolve()),
                                     "sha256": row["sha256"]}
    report.write_text(json.dumps(doc))
    return project, report, selected, paths, state


def test_current_ir_accepts_owned_external_views_through_current_validator(
        tmp_path, monkeypatch):
    project, report, selected, paths, _ = _external_current_primary(
        tmp_path, monkeypatch)
    before = report.read_bytes()
    result = emc.validate_primary_ir(project)
    assert result["valid"] is True, result
    assert result["verdict"] == "PASS", result
    assert Path(selected["records"]["def"]["path"]) == paths["def"]
    assert paths["def"].is_relative_to(tmp_path / "adopted-original")
    assert report.read_bytes() == before


@pytest.mark.parametrize("damage", [
    "malformed", "unbound", "changed", "owner_stale", "wrong_role",
    "selected_self_asserted", "missing_owner", "symlink",
])
def test_current_ir_refuses_unowned_or_stale_external_inputs(
        tmp_path, monkeypatch, damage):
    project, report, selected, paths, state = _external_current_primary(
        tmp_path, monkeypatch)
    doc = json.loads(report.read_text())
    if damage == "malformed":
        doc["inputs"]["def"] = {"path": str(paths["def"])}
    elif damage == "unbound":
        foreign = _write(tmp_path / "foreign", "foreign.def", paths["def"].read_text())
        doc["inputs"]["def"] = {"path": str(foreign), "sha256": _sha(foreign)}
    elif damage == "changed":
        paths["def"].write_text(paths["def"].read_text() + "changed\n")
    elif damage == "owner_stale":
        state.write_text(state.read_text() + "\n")
    elif damage == "wrong_role":
        doc["inputs"]["def"] = dict(selected["records"]["netlist"])
    elif damage == "selected_self_asserted":
        forged = _write(project, "forged.def", paths["def"].read_text())
        forged_row = {"path": str(forged.relative_to(project)),
                      "sha256": _sha(forged)}
        doc["inputs"]["def"] = dict(forged_row)
        doc["record"]["selected_inputs"]["def"] = dict(forged_row)
    elif damage == "missing_owner":
        (project / la.CURRENT_STA_RECORD).unlink()
    else:
        contents = paths["def"].read_text()
        paths["def"].unlink()
        target = _write(tmp_path / "foreign", "symlink-target.def", contents)
        paths["def"].symlink_to(target)
    report.write_text(json.dumps(doc))
    result = emc.validate_primary_ir(project)
    assert result["valid"] is False, (damage, result)
    assert result["verdict"] == "NOT_MEASURED", (damage, result)
    assert result["rule"] == "LL_IR_CURRENT_BINDING_INVALID"


def test_current_ir_owned_external_measured_fail_stays_fail(tmp_path, monkeypatch):
    project, _, _, _, _ = _external_current_primary(
        tmp_path, monkeypatch, "native_fail")
    result = emc.validate_primary_ir(project)
    assert result["valid"] is True, result
    assert result["verdict"] == "FAIL", result

@pytest.mark.parametrize("damage", ["missing", "changed", "symlink"])
def test_current_ir_rebinding_refuses_nonidentical_or_nonregular_state(
        tmp_path, monkeypatch, damage):
    test_default_step24_adopts_its_current_native_primary(tmp_path, monkeypatch, "current")
    original = tmp_path / "project"
    relocated = tmp_path / "relocated"
    original.rename(relocated)
    state = relocated / "phase3/librelane/24/01-openroad-irdropreport/state_out.json"
    if damage == "missing":
        state.unlink()
    elif damage == "changed":
        state.write_text(state.read_text() + "\nchanged\n")
    else:
        outside = tmp_path / "foreign-state.json"
        outside.write_text(state.read_text())
        state.unlink()
        state.symlink_to(outside)
    result = emc.validate_primary_ir(relocated)
    assert result["valid"] is False, result
    assert result["verdict"] == "NOT_MEASURED", result
    assert result["rule"] == "LL_IR_CURRENT_BINDING_INVALID"


@pytest.mark.parametrize("damage", ["missing", "changed", "both_missing", "empty_both"])
def test_current_ir_requires_each_actual_ir_source_owner(tmp_path, monkeypatch, damage):
    test_default_step24_adopts_its_current_native_primary(tmp_path, monkeypatch, "native_fail")
    project = tmp_path / "project"
    receipt = project / "reports/phase3/ir_drop_librelane.json"
    original = json.loads(receipt.read_text())
    current = emc.native_source_identity()
    # These are existing identity keys, not a new receipt schema. Listing them
    # independently makes the refusal controls cover every real IR owner.
    required = ("_librelane_step24_record", "_librelane_step24_refusal_publish",
                "_librelane_step24_publish", "_step24_primary_mode", "_step24_adopt_primary",
                "_step24_basis_inputs", "_step24_transient_argv", "_emit_ir_em_reports",
                "librelane_ir_antenna.py", "dynamic_ir_vectored_emit.py", "ir_drop_report_check.py")
    assert all(name in current and name in original["source_identity"] for name in required)
    for name in required if damage != "empty_both" else (None,):
        doc = json.loads(json.dumps(original))
        observed_current = dict(current)
        if damage == "empty_both":
            doc["source_identity"] = {}
            observed_current = {}
        elif damage == "changed":
            doc["source_identity"][name] = "0" * 64
        else:
            doc["source_identity"].pop(name)
            if damage == "both_missing":
                observed_current.pop(name)
        receipt.write_text(json.dumps(doc))
        monkeypatch.setattr(emc, "native_source_identity", lambda: dict(observed_current))
        result = emc.validate_primary_ir(project)
        assert result["valid"] is False, (name, result)
        assert result["verdict"] == "NOT_MEASURED", (name, result)


@pytest.mark.parametrize("changed", ["em_current_density_check.py",
                                    "em_peak_current_authority_check.py"])
def test_step25_keeps_its_complete_native_source_binding(tmp_path, monkeypatch, changed):
    from test_default_power_density import build
    project, _, _ = build(tmp_path, monkeypatch, direct=True)
    assert emc.validate_native_density(project)["valid"] is True
    current = emc.native_source_identity()
    current[changed] = "0" * 64
    monkeypatch.setattr(emc, "native_source_identity", lambda: dict(current))
    result = emc.validate_native_density(project)
    assert result["valid"] is False, result
    assert result["verdict"] == "NOT_MEASURED", result
    assert result["reason"] == "native producer/consumer source changed"
