"""D75 binds the existing bare-die package/test consumers without approving tapeout."""
from __future__ import annotations

import json
import copy
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import _tapeout_declaration as TD  # noqa: E402
import _submission_template as ST  # noqa: E402
import flow109  # noqa: E402
import flow109_package_electrical as D67  # noqa: E402
import flow109_package_ready as D75  # noqa: E402
import submission_template_ingest as ING  # noqa: E402
import test_flow109_package_electrical as D67T  # noqa: E402
from programs.tests._hostpaths import require_repo  # noqa: E402


def test_d75_adapter_loads_by_path_with_existing_consumers(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "flow109_package_ready_path_control", PROGRAMS / "flow109_package_ready.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.STEP == "D75"
    project = _project(tmp_path)
    result = module.execute(project, def_path=project / module.PAD_DEF,
        tech_lef=project / "input/pdk/tech.tlef", io_lefs=[project / "input/pdk/io.lef"])
    assert result["component_status"] == "PASS"


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value,
                    encoding="utf-8")


def _context(project: Path, **features):
    registry = flow109.load_registry()
    selected = dict(next(profile["features"] for profile in
        registry["reference_profiles"] if profile["name"] == "Small digital IC without DFT"))
    selected.update({"package_model_required": False, "requires_dft": False,
                     "requires_perc": True})
    selected.update(features)
    context = flow109.execution_context(flow109.resolve_plan(selected), "D75", "D75")
    _write(project / "reports/flow109/requests" /
           f"{context['context_sha256']}.json", context)
    return context


def _declaration():
    doc = TD.blank_declaration()
    doc["answers"]["deliverable"] = TD.DELIVERABLE_DIE
    doc[TD.PROVENANCE_KEY] = {"deliverable": {
        "answered_by": TD.ANSWERED_BY_OWNER_VALUE,
        "citation": "D75 neutral fixture authority: deliver a bare die.",
    }}
    return doc


def _gds(path: Path) -> None:
    import klayout.db as k
    layout = k.Layout()
    layout.dbu = 0.001
    pad = layout.create_cell("PADX")
    pad.shapes(layout.layer(167, 5)).insert(k.Box(7500, 290000, 67500, 350000))
    top = layout.create_cell("chip_top")
    top.insert(k.CellInstArray(pad.cell_index(), k.Trans(850000, 0)))
    path.parent.mkdir(parents=True, exist_ok=True)
    layout.write(str(path))


def _project(root: Path) -> Path:
    project = root / "project"
    decl = _declaration()
    _write(project / TD.DECLARATION_REL, decl)
    own = _declaration()
    own["operator_template"] = {
        "path": None, "slot": None,
        "absent_reason": "Owner selected independent bare-die tapeout.",
    }
    _write(project / "input/submission_template/operator_answers.json", own)
    _write(project / ST.DESIGN_ANSWERS_REL, own)
    _write(project / TD.SELF_TAPEOUT_REL,
           TD.SELF_TAPEOUT_MARKER + "\nowner-selected independent tapeout\n")
    _write(project / "input/docs/L3_interfaces.md", """\
## Physical Pad Placement

| side | signals |
|------|---------|
| East (E) | `clk` |
""")
    _write(project / "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json", {
        "layer": "L20", "applicability": "NOT_APPLICABLE", "fields": {},
    })
    _write(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {
        "layer": "L19", "fields": {"die_area_budget_um": "1000x1000"},
    })
    _write(project / "reports/phase3/io_pad_chip_top.json", {
        "program": "io_pad_chip_top_gen", "verdict": "WROTE",
        "chip_top_module": "chip_top",
        "io_library_lefs": ["input/pdk/io.lef"],
    })
    _write(project / "input/pdk/tech.tlef", """\
UNITS
  DATABASE MICRONS 2000 ;
END UNITS
LAYER Metal5
  TYPE ROUTING ;
  WIDTH 0.44 ;
END Metal5
""")
    _write(project / "input/pdk/io.lef", """\
VERSION 5.8 ;
MACRO PADX
  CLASS PAD ;
  ORIGIN 0 0 ;
  SIZE 75 BY 350 ;
  PIN PAD
    DIRECTION INOUT ;
    USE SIGNAL ;
    PORT
      LAYER Metal5 ;
      RECT 7.5 290 67.5 350 ;
    END
  END PAD
END PADX
END LIBRARY
""")
    _write(project / "input/pdk/layers.lyp", """\
<layer-properties><properties><name>OPEN</name><source>OPEN 167/5@1</source></properties></layer-properties>
""")
    _write(project / "input/submission_template/provider_target.json", {
        "provider": "neutral",
        "technical_target": {"dimensions_um": [1000, 1000],
                             "origin_um": [0, 0], "packaging": "bare_die"},
        "bond_pad_edge_distance": {
            "max_distance_um": 900,
            "opening_layer": {"name": "OPEN",
                              "layer_properties": "input/pdk/layers.lyp"},
            "io_lefs": ["input/pdk/io.lef"],
        },
    })
    _write(project / "phase3/stage3/pnr/padring.def", """\
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 2000 ;
DIEAREA ( 0 0 ) ( 2000000 2000000 ) ;
COMPONENTS 1 ;
- u_pad_clk PADX + PLACED ( 1700000 0 ) N ;
END COMPONENTS
PINS 1 ;
- clk + NET clk + DIRECTION INPUT + USE SIGNAL
  + PORT
    + LAYER Metal5 ( -60000 -60000 ) ( 60000 60000 )
    + PLACED ( 1820000 640000 ) N ;
END PINS
NETS 1 ;
- clk ( PIN clk ) ( u_pad_clk PAD ) ;
END NETS
END DESIGN
""")
    _gds(project / "phase3/stage4/gds/chip_top.gds")
    phase3 = project / "reports/phase3"
    _write(phase3 / "perc_equivalent.json", {
        "verdict": "PASS", "categories": [
            {"category": "ESD", "status": "AUTOMATED", "result": "PASS"}],
    })
    _write(phase3 / "perc_equivalent.rpt", "OVERALL VERDICT: PASS\nESD\n")
    _write(phase3 / "PERC_SIGNOFF_MEMO.md", "**Overall verdict:** `PASS`\nESD\n")
    return project


def _current_native_authority(project: Path, monkeypatch):
    """Neutral retained STAPostPNR authority; it runs no EDA producer."""
    import execution_adapters_backend as backend

    folder = project / "phase3/librelane/neutral/01-openroad-stapostpnr"
    old_def = project / D75.PAD_DEF
    current_def = folder / "chip_top.def"
    current_odb = folder / "chip_top.odb"
    _write(current_def, old_def.read_text())
    _write(current_odb, "neutral adopted ODB bytes\n")
    netlist = folder / "chip_top.v"
    sdc = folder / "chip_top.sdc"
    spef = folder / "chip_top.nom.spef"
    _write(netlist, "module chip_top(input a, output y); assign y = a; endmodule\n")
    _write(sdc, "set_propagated_clock [all_clocks]\n")
    _write(spef, "*SPEF neutral\n")
    tech = project / "input/pdk/tech.tlef"
    io_lef = project / "input/pdk/io.lef"
    config = {
        "DESIGN_NAME": "chip_top", "DEFAULT_CORNER": "nom_tt",
        "TECH_LEFS": {"nom_*": str(tech)}, "PAD_LEFS": [str(io_lef)],
    }
    _write(folder / "config.json", config)
    state = {"odb": str(current_odb), "def": str(current_def),
             "nl": str(netlist), "sdc": str(sdc),
             "spef": {"nom_*": str(spef)}, "metrics": {}}
    _write(folder / "state_out.json", state)
    _write(folder / "pdk_root.json", {
        "stated_by": "run_chain(pdk_root=...)", "execution_route": "docker",
        "cli_pdk_root": "/pdk", "mounts_under_it": [
            [str(project / "input/pdk"), str(project / "input/pdk")]],
    })
    _write(folder / "invocation.log", "neutral retained producer invocation\n")

    def rebind():
        fp = {
            "step": "OpenROAD.STAPostPNR",
            "image": "ghcr.io/vibeic/vibeic-eda@sha256:" + "0" * 64,
            "state_files": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (current_odb, current_def, netlist, sdc, spef)},
            "config_files": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (tech, io_lef)},
        }
        _write(folder / "input_fingerprint.json", fp)
        names = ["state_out.json", "config.json", "input_fingerprint.json",
                 "pdk_root.json", "invocation.log", "chip_top.odb", "chip_top.def",
                 "chip_top.v", "chip_top.sdc", "chip_top.nom.spef"]
        receipt = {"input": fp, "sha256": {
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in names}}
        _write(folder / "vibeic_receipt.json", receipt)
        _write(project / "reports/phase3/sta_postpnr_signoff.json", {
            "sta_state": str(folder / "state_out.json"),
            "sta_state_sha256": hashlib.sha256(
                (folder / "state_out.json").read_bytes()).hexdigest(),
        })

    rebind()
    selected = {
        "top": "chip_top", "views": {"odb": current_odb.resolve(),
            "def": current_def.resolve(), "netlist": netlist.resolve(),
            "sdc": sdc.resolve(), "spef": spef.resolve()},
        "inputs": (), "transport": None,
    }
    monkeypatch.setattr(backend, "_default_step24_current_subject",
                        lambda *_a, **_k: selected)
    return {"folder": folder, "def": current_def, "odb": current_odb,
            "netlist": netlist,
            "tech": tech, "old_def": old_def, "selected": selected,
            "rebind": rebind}


def _by_name(result, name):
    return next(check for check in result["checks"] if check["check"] == name)


def _produced_d67(project: Path):
    """Run the supplied D67 producer on its neutral checked-in RLC model."""
    context, requirements, reference = D67T._case(project)
    fixture = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                           "programs", "tests", "fixtures", "flow109_d67",
                           "package.sp")
    assert Path(requirements["cases"][0]["model"]["path"]).resolve() == fixture.resolve()
    report = D67T._native(project, context)
    assert report["component_status"] == "PASS", report
    return context, requirements, reference, report


def test_registry_routes_only_the_existing_default_d75_component():
    registry = json.loads((PLUGIN / "flow/flow109.json").read_text())
    row = next(row for row in registry["rows"] if row["id"] == "D75")
    dispatch = row["profiles"][0]["dispatch"]
    assert dispatch["adapter"] == "flow109_package_ready"
    assert dispatch["native_step_id"] == "flow109.D75"
    assert dispatch["admission_policy"] == "source_owned_existing_native"
    assert dispatch["acceptance_scope"] == "existing_native_component_only"
    assert dispatch["component_scope"] == "existing_Default_bare_die_interface_component_only"
    plan = flow109.resolve_plan(next(profile["features"] for profile in
        registry["reference_profiles"] if profile["name"] == "Small digital IC without DFT"))
    row = flow109.resolve_step(plan, "D75")
    assert flow109.source_owned_native_dispatch(row)["adapter"] == "flow109_package_ready"
    assert row["metric_acceptance_status"] == "UNIMPLEMENTED"


def test_bare_die_positive_runs_actual_consumers_but_not_whole_flow(tmp_path):
    project = _project(tmp_path)
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "PASS", result
    for name in ("tapeout_declaration_check", "pad_side_constraint_check",
                 "pad_bterm_coincidence_check", "provider_bond_pad_edge",
                 "perc_signoff_check"):
        assert _by_name(result, name)["status"] == "PASS", result
    assert _by_name(result, "test_access_applicability")["status"] == "NOT_APPLICABLE"
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert result["delivery_accepted"] is False
    assert result["inputs"] and all(item["sha256"] for item in result["inputs"])
    D75.validate(project, result)


def test_current_native_geometry_and_tech_are_consumed_not_legacy_padring(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    authority = _current_native_authority(project, monkeypatch)
    authority["old_def"].unlink()
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "PASS", result
    current = _by_name(result, "current_native_geometry_authority")
    assert current["status"] == "PASS"
    assert current["detail"]["def"]["sha256"] == hashlib.sha256(
        authority["def"].read_bytes()).hexdigest()
    assert current["detail"]["odb"]["sha256"] == hashlib.sha256(
        authority["odb"].read_bytes()).hexdigest()
    assert current["detail"]["selected_tech_pattern"] == "nom_*"
    assert current["detail"]["database_microns"] == 2000
    assert current["detail"]["routing_layers"] == ["Metal5"]


def test_current_native_missing_stale_and_wrong_source_refuse(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    authority = _current_native_authority(project, monkeypatch)
    original = authority["tech"].read_bytes()
    authority["tech"].write_bytes(original + b"\nchanged after native receipt\n")
    stale = D75.execute(project, _context(project))
    assert stale["component_status"] == "NOT_MEASURED", stale
    assert stale["reason"] == "D75_CURRENT_NATIVE_GEOMETRY_UNBOUND"
    authority["tech"].write_bytes(original)
    restored = D75.execute(project, _context(project))
    assert restored["component_status"] == "PASS", restored

    authority["tech"].unlink()
    missing = D75.execute(project, _context(project))
    assert missing["component_status"] == "NOT_MEASURED", missing
    assert missing["reason"] == "D75_CURRENT_NATIVE_GEOMETRY_UNBOUND"
    authority["tech"].write_bytes(original)

    authority["selected"]["views"]["def"] = authority["old_def"].resolve()
    wrong = D75.execute(project, _context(project))
    assert wrong["component_status"] == "NOT_MEASURED", wrong
    assert wrong["reason"] == "D75_CURRENT_NATIVE_GEOMETRY_UNBOUND"


def test_current_native_wrong_geometry_remains_a_real_failure(tmp_path, monkeypatch):
    project = _project(tmp_path)
    authority = _current_native_authority(project, monkeypatch)
    authority["def"].write_text(authority["def"].read_text().replace(
        "+ PLACED ( 1820000 640000 ) N ;",
        "+ PLACED ( 1000000 640000 ) N ;"))
    authority["rebind"]()
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "FAIL", result
    assert _by_name(result, "current_native_geometry_authority")["status"] == "PASS"
    assert _by_name(result, "pad_bterm_coincidence_check")["status"] == "FAIL"


def test_validated_self_tapeout_does_not_require_a_provider(tmp_path):
    project = _project(tmp_path)
    (project / D75.PROVIDER_TARGET).unlink()
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "PASS", result
    provider = _by_name(result, "provider_bond_pad_edge")
    assert provider["status"] == "NOT_APPLICABLE", result
    assert provider["detail"]["route"] == TD.ROUTE_SELF_TAPEOUT
    assert provider["detail"]["owner_self_tapeout"] is True
    assert result["provider_identity"] is None
    for name in ("pad_side_constraint_check", "pad_bterm_coincidence_check"):
        assert _by_name(result, name)["status"] == "PASS", result
    D75.validate(project, result)
    owner = project / ST.DESIGN_ANSWERS_REL
    owner.write_text(owner.read_text() + "\n")
    with pytest.raises(D75.D75Refusal, match="D75_INPUT_STALE"):
        D75.validate(project, result)


def _retained_catalogue(project: Path, tmp_path: Path) -> Path:
    catalogue = project / ST.STAGED_TEMPLATE_REL
    catalogue.mkdir(parents=True, exist_ok=True)
    source = catalogue / "neutral.json"
    source.write_text(json.dumps({
        "DIE_AREA": [0, 0, 1000, 1000], "SEAL_RING_WIDTH": 10}))
    reason = json.loads((project / ST.DESIGN_ANSWERS_REL).read_text())[
        "operator_template"]["absent_reason"]
    assert ING.main([str(project), "--template", str(catalogue),
                     "--no-template-reason", reason]) == 0
    return source


def test_self_tapeout_catalogue_hash_and_selection_still_require_provider(tmp_path):
    project = _project(tmp_path / "stale")
    source = _retained_catalogue(project, tmp_path)
    (project / D75.PROVIDER_TARGET).unlink()
    source.write_text("{}")
    stale = D75.execute(project, _context(project))
    assert stale["component_status"] == "FAIL", stale
    assert stale["reason"] == "D75_DECLARATION_CONSUMER_FAILED"
    assert [r["rule"] for r in _by_name(
        stale, "tapeout_declaration_check")["detail"]["refusals"]] == [
            "ROUTER_CONTRADICTION"]

    project = _project(tmp_path / "missing")
    source = _retained_catalogue(project, tmp_path)
    (project / D75.PROVIDER_TARGET).unlink()
    source.unlink()
    missing = D75.execute(project, _context(project))
    assert missing["component_status"] == "FAIL", missing
    assert missing["reason"] == "D75_DECLARATION_CONSUMER_FAILED"

    project = _project(tmp_path / "selected")
    _retained_catalogue(project, tmp_path)
    (project / D75.PROVIDER_TARGET).unlink()
    own = json.loads((project / ST.DESIGN_ANSWERS_REL).read_text())
    own["operator_template"]["slot"] = "neutral"
    _write(project / ST.DESIGN_ANSWERS_REL, own)
    selected = D75.execute(project, _context(project))
    assert selected["component_status"] == "FAIL", selected
    assert selected["reason"] == "D75_DECLARATION_CONSUMER_FAILED"


def test_missing_owner_scope_does_not_make_missing_provider_not_applicable(tmp_path):
    project = _project(tmp_path)
    (project / D75.PROVIDER_TARGET).unlink()
    (project / ST.DESIGN_ANSWERS_REL).unlink()
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "NOT_MEASURED", result
    assert result["reason"] == "D75_REQUIRED_INPUT_ABSENT_OR_INVALID"


def test_provider_manual_review_is_not_upgraded_to_pass(tmp_path):
    project = _project(tmp_path)
    profile = project / D75.PROVIDER_TARGET
    doc = json.loads(profile.read_text())
    doc["bond_pad_edge_distance"].pop("max_distance_um")
    _write(profile, doc)
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "NOT_MEASURED", result
    provider = _by_name(result, "provider_bond_pad_edge")
    assert provider["detail"]["verdict"] == "MANUAL_REVIEW"
    assert provider["status"] == "NOT_MEASURED"


def test_wrong_domain_pad_pin_geometry_fails(tmp_path):
    project = _project(tmp_path)
    path = project / D75.PAD_DEF
    path.write_text(path.read_text().replace(
        "+ PLACED ( 1820000 640000 ) N ;",
        "+ PLACED ( 1000000 640000 ) N ;"))
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "FAIL", result
    assert _by_name(result, "pad_bterm_coincidence_check")["status"] == "FAIL"


@pytest.mark.parametrize("clock_x, disconnected, expected_status", [
    (1000000, ["clk"], "FAIL"),
    (1820000, [], "NOT_MEASURED"),
])
def test_disconnected_pad_fails_even_when_another_pad_is_undecided(
        tmp_path, clock_x, disconnected, expected_status):
    project = _project(tmp_path)
    path = project / D75.PAD_DEF
    path.write_text(path.read_text().replace(
        "COMPONENTS 1 ;", "COMPONENTS 2 ;").replace(
        "END COMPONENTS", "- u_pad_aux PADX + PLACED ( 1700000 0 ) N ;\nEND COMPONENTS").replace(
        "PINS 1 ;", "PINS 2 ;").replace(
        "+ PLACED ( 1820000 640000 ) N ;",
        f"+ PLACED ( {clock_x} 640000 ) N ;").replace(
        "END PINS", "- aux + NET aux + DIRECTION INPUT + USE SIGNAL ;\nEND PINS").replace(
        "NETS 1 ;", "NETS 2 ;").replace(
        "END NETS", "- aux ( PIN aux ) ( u_pad_aux PAD ) ;\nEND NETS"))
    result = D75.execute(project, _context(project))
    pads = _by_name(result, "pad_bterm_coincidence_check")
    assert pads["detail"]["not_connected_nets"] == disconnected
    assert pads["detail"]["undecided_nets"] == ["aux"]
    assert pads["status"] == expected_status
    assert result["component_status"] == expected_status


def test_missing_geometry_and_missing_required_package_models_do_not_pass(tmp_path):
    project = _project(tmp_path)
    (project / "phase3/stage4/gds/chip_top.gds").unlink()
    missing = D75.execute(project, _context(project))
    assert missing["component_status"] == "NOT_MEASURED"
    assert missing["reason"] == "D75_FINAL_GEOMETRY_UNBOUND"

    project = _project(tmp_path / "packaged")
    packaged = D75.execute(project, _context(project, package_model_required=True))
    assert packaged["component_status"] == "NOT_MEASURED"
    assert packaged["reason"] == "D75_D67_REPORT_ABSENT_OR_INVALID"


def test_foreign_subject_d67_is_refused_then_same_subject_is_accepted(
        tmp_path, monkeypatch):
    project = _project(tmp_path)
    authority = _current_native_authority(project, monkeypatch)
    d67_context, requirements, reference, d67_report = _produced_d67(project)
    result = D75.execute(project, _context(project, package_model_required=True))
    assert result["component_status"] == "FAIL", result
    assert result["reason"] == "D75_D67_SUBJECT_MISMATCH"
    electrical = _by_name(result, "package_electrical_feedback")
    assert electrical["status"] == "FAIL"
    assert electrical["detail"]["subject_join"]["d67_top"] == "proof_alpha"
    assert electrical["detail"]["subject_join"]["d75_io_top"] == "chip_top"
    assert electrical["detail"]["subject_join"]["d75_native_top"] == "chip_top"

    # Restore one exact subject: D67 remeasures the same adopted netlist that
    # the current D75 native checkpoint selects. The model and bounds do not
    # change; only their source-owned applicability identity is corrected.
    native_netlist = D67._record(project, authority["netlist"])
    requirements["top"] = "chip_top"
    requirements["netlist"] = native_netlist
    reference["reference"]["top"] = "chip_top"
    reference["reference"]["netlist"] = native_netlist
    D67T._bind(project, requirements, reference)
    d67_report = D67T._native(project, d67_context)
    assert d67_report["component_status"] == "PASS", d67_report
    result = D75.execute(project, _context(project, package_model_required=True))
    assert result["component_status"] == "PASS", result
    electrical = _by_name(result, "package_electrical_feedback")
    assert electrical["status"] == "PASS"
    assert electrical["detail"]["d67_context_sha256"] == d67_context["context_sha256"]
    assert electrical["detail"]["metrics"]["status"] == "PASS"
    assert (electrical["detail"]["metrics"]["physical_package_qualification"]
            == "NOT_MEASURED")
    assert electrical["detail"]["subject_join"]["status"] == "PASS"
    assert electrical["detail"]["subject_join"]["netlist"] == native_netlist
    assert any(item["path"] == str(D75.D67_REPORT) for item in result["inputs"])
    D75.validate(project, result)
    report_path = project / D75.D67_REPORT
    report_bytes = report_path.read_bytes()
    report_path.write_bytes(report_bytes + b"\n")
    with pytest.raises(D75.D75Refusal, match="D75_INPUT_STALE"):
        D75.validate(project, result)
    report_path.write_bytes(report_bytes)
    D75.validate(project, result)

    # A changed model invalidates both D67's declared consumer and D75.  Restore
    # the same source bytes and the current producer receipt is consumable again.
    model = Path(requirements["cases"][0]["model"]["path"])
    original = model.read_text()
    local = D67T._put(project, "input/package-current.sp", original)
    requirements["cases"][0]["model"] = local
    reference["reference"]["models"][0]["model"] = local
    D67T._bind(project, requirements, reference)
    current = D67T._native(project, d67_context)
    assert current["component_status"] == "PASS", current
    model = project / local["path"]
    model.write_text(original + "\n* changed after native receipt\n")
    stale = D75.execute(project, _context(project, package_model_required=True))
    assert stale["component_status"] == "NOT_MEASURED", stale
    assert stale["reason"] == "D75_D67_CONSUMER_REFUSED"
    assert "D67_INPUT_STALE_OR_MISSING" in _by_name(
        stale, "adapter_refusal")["detail"]
    model.write_text(original)
    restored = D75.execute(project, _context(project, package_model_required=True))
    assert restored["component_status"] == "PASS", restored


def test_package_required_legacy_subject_does_not_invent_native_prerequisite(tmp_path):
    project = _project(tmp_path)
    d67_context, requirements, reference = D67T._case(project)
    netlist_path = project / "input/legacy-chip-top.v"
    _write(netlist_path,
           "module chip_top(input a, output y); assign y = a; endmodule\n")
    netlist = D67._record(project, netlist_path)
    requirements["top"] = "chip_top"
    requirements["netlist"] = netlist
    reference["reference"]["top"] = "chip_top"
    reference["reference"]["netlist"] = netlist
    D67T._bind(project, requirements, reference)
    report = D67T._native(project, d67_context)
    assert report["component_status"] == "PASS", report

    result = D75.execute(project, _context(project, package_model_required=True))
    assert result["component_status"] == "PASS", result
    subject = _by_name(
        result, "package_electrical_feedback")["detail"]["subject_join"]
    assert subject["status"] == "PASS"
    assert subject["basis"] == "existing legacy applicability: IO top"
    assert subject["d75_native_top"] is None


def test_d67_wrong_netlist_port_and_unsupported_model_do_not_pass_d75(tmp_path):
    project = _project(tmp_path / "port")
    context, requirements, reference = D67T._case(project)
    netlist = Path(requirements["netlist"]["path"]).read_text().replace(
        "output y", "output q")
    local_netlist = D67T._put(project, "input/wrong-port.v", netlist)
    requirements["netlist"] = local_netlist
    reference["reference"]["netlist"] = local_netlist
    D67T._bind(project, requirements, reference)
    d67_report = D67T._native(project, context)
    assert d67_report["component_status"] == "FAIL", d67_report
    assert d67_report["reason"] == "D67_PORT_IDENTITY_MISMATCH"
    wrong_port = D75.execute(project, _context(project, package_model_required=True))
    assert wrong_port["component_status"] == "FAIL", wrong_port
    assert wrong_port["reason"] == "D75_D67_CONSUMER_REFUSED"
    assert "D67_PORT_IDENTITY_MISMATCH" in _by_name(
        wrong_port, "adapter_refusal")["detail"]

    project = _project(tmp_path / "unsupported")
    context, requirements, reference = D67T._case(project)
    source = Path(requirements["cases"][0]["model"]["path"]).read_text()
    unsupported = D67T._put(project, "input/unsupported-package.sp",
                            source.replace("Rseries die neck 10", ".include absent.sp"))
    requirements["cases"][0]["model"] = unsupported
    reference["reference"]["models"][0]["model"] = unsupported
    D67T._bind(project, requirements, reference)
    d67_report = D67T._native(project, context)
    assert d67_report["component_status"] == "NOT_MEASURED", d67_report
    unsupported_result = D75.execute(
        project, _context(project, package_model_required=True))
    assert unsupported_result["component_status"] == "NOT_MEASURED"
    assert unsupported_result["reason"] == "D75_D67_CONSUMER_REFUSED"
    assert "D67_MODEL_SCOPE_UNSUPPORTED" in _by_name(
        unsupported_result, "adapter_refusal")["detail"]


def test_d67_native_failure_and_open_item_label_cannot_pass_d75(tmp_path):
    project = _project(tmp_path / "native-fail")
    context, requirements, reference = D67T._case(project)
    requirements["cases"][0]["limits"]["voltage_at_sample"] = {"max": 0.5}
    D67T._bind(project, requirements, reference)
    d67_report = D67T._native(project, context)
    assert d67_report["native_started"] is True
    assert d67_report["component_status"] == "FAIL", d67_report
    failed = D75.execute(project, _context(project, package_model_required=True))
    assert failed["component_status"] == "FAIL", failed
    assert _by_name(failed, "package_electrical_feedback")["status"] == "FAIL"

    project = _project(tmp_path / "open-items")
    _context67, _requirements, _reference, report = _produced_d67(project)
    report["component_status"] = "PASS_WITH_OPEN_ITEMS"
    _write(project / D75.D67_REPORT, report)
    open_items = D75.execute(project, _context(project, package_model_required=True))
    assert open_items["component_status"] == "NOT_MEASURED", open_items
    assert open_items["reason"] == "D75_D67_RECEIPT_STATUS_MISMATCH"


def test_failing_and_missing_perc_evidence_remain_fail_or_unmeasured(tmp_path):
    project = _project(tmp_path)
    summary = project / "reports/phase3/perc_equivalent.json"
    doc = json.loads(summary.read_text())
    doc["verdict"] = "FAIL"
    doc["categories"][0]["result"] = "FAIL"
    summary.write_text(json.dumps(doc))
    for projection in (project / "reports/phase3/perc_equivalent.rpt",
                       project / "reports/phase3/PERC_SIGNOFF_MEMO.md"):
        projection.write_text(projection.read_text().replace("PASS", "FAIL"))
    failed = D75.execute(project, _context(project))
    assert failed["component_status"] == "FAIL"
    assert _by_name(failed, "perc_signoff_check")["status"] == "FAIL"

    project = _project(tmp_path / "missing")
    (project / "reports/phase3/perc_equivalent.json").unlink()
    missing = D75.execute(project, _context(project))
    assert missing["component_status"] == "NOT_MEASURED"
    assert _by_name(missing, "perc_signoff_check")["status"] == "NOT_MEASURED"


def test_current_receipt_revalidates_and_changed_source_is_stale(tmp_path):
    project = _project(tmp_path)
    result = D75.execute(project, _context(project))
    D75.validate(project, result)
    lef = project / "input/pdk/io.lef"
    lef.write_text(lef.read_text() + "\n# changed after receipt\n")
    with pytest.raises(D75.D75Refusal, match="D75_INPUT_STALE"):
        D75.validate(project, result)


def test_wrong_provider_and_consumer_load_identity_refuse_then_restore(tmp_path,
                                                                      monkeypatch):
    project = _project(tmp_path)
    result = D75.execute(project, _context(project))
    assert result["component_status"] == "PASS", result

    wrong_provider = copy.deepcopy(result)
    wrong_provider["provider_identity"]["provider"] = "different-provider"
    with pytest.raises(D75.D75Refusal, match="D75_PROVIDER_IDENTITY_MISMATCH"):
        D75.validate(project, wrong_provider)

    actual_sources = D75.operation_sources()
    monkeypatch.setattr(D75, "operation_sources",
                        lambda: {**actual_sources,
                                 "programs/provider_bond_pad_edge.py": "0" * 64})
    with pytest.raises(D75.D75Refusal, match="D75_LOAD_IDENTITY_MISMATCH"):
        D75.validate(project, result)
    monkeypatch.setattr(D75, "operation_sources", lambda: actual_sources)
    D75.validate(project, result)


def test_context_feature_source_is_bound_and_missing_stale_or_unknown_refuses(tmp_path):
    project = _project(tmp_path)
    context = _context(project)
    result = D75.execute(project, context)
    request = (project / "reports/flow109/requests" /
               f"{context['context_sha256']}.json")
    assert result["context_sha256"] == context["context_sha256"]
    assert any(item["path"] == str(request.relative_to(project))
               and item["sha256"] for item in result["inputs"])

    request.unlink()
    missing = D75.execute(project, context)
    assert missing["reason"] == "D75_CONTEXT_SOURCE_UNBOUND"

    _write(request, context)
    changed = json.loads(request.read_text())
    changed["features"]["requires_dft"] = True
    _write(request, changed)
    stale = D75.execute(project, context)
    assert stale["reason"] == "D75_CONTEXT_SOURCE_STALE"

    unknown = dict(context)
    unknown["features"] = dict(context["features"])
    unknown["features"].pop("requires_dft")
    invalid = D75.execute(project, unknown)
    assert invalid["reason"] == "D75_CONTEXT_INVALID"


def test_normal_flow109_default_entry_runs_d75_without_generic_qualification(
        tmp_path, monkeypatch):
    import _delivery_route
    import flow109_admission

    project = _project(tmp_path)
    assert _delivery_route.admit(project, "ic") is None
    registry = flow109.load_registry()
    features = dict(next(profile["features"] for profile in
        registry["reference_profiles"] if profile["name"] == "Small digital IC without DFT"))
    features["package_model_required"] = False
    manifest = project / "flow109-manifest.json"
    manifest.write_text(json.dumps({"features": features}))
    # Register teardown even when absent: the in-process front door sets these.
    monkeypatch.setenv(flow109.CONTEXT_ENV, "")
    monkeypatch.setenv(flow109.ATTEMPT_ENV, "")
    generic_admission_calls = []
    monkeypatch.setattr(flow109_admission, "require_admission",
                        lambda *a, **k: generic_admission_calls.append("called") or
                        {"status": "PASS"})
    args = SimpleNamespace(flow="109", flow109_manifest=manifest,
                           flow109_plan_only=False, execution_mode="default",
                           entry_step="D75", exit_step="D75")
    rc = flow109.prepare_front_door(args, project)
    assert generic_admission_calls == [], generic_admission_calls
    assert rc == 2
    result = json.loads((project / "reports/flow109/components/D75.json").read_text())
    assert result["component_status"] == "PASS"
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["completed"] is False
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    admission = json.loads((project / "reports/flow109/admission.json").read_text())
    assert admission["qualification_status"] == "NOT_CLAIMED"
    assert admission["acceptance_scope"] == "existing_native_component_only"
