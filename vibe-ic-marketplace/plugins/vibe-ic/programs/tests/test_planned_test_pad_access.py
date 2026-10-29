"""Actual plan/physical consumers over explicit SOFTWARE upstream fixtures.

The synthetic D01/D24 preconditions and IO library confer no product authority,
native qualification, scan realization or physical-placement acceptance.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest
import _l_doc_pad_placement as LPP
import _cdc_netlist as frontend_inputs
import _path_layout as layout
import _specrtl_common as sources
import _tapeout_declaration as TD
import fault_scan_chain_insert as scan
import flow109
import io_pad_chip_top_gen as physical
import phase3_one_shot_runner as backend
import slot_pad_budget_check as budget
import test_io_pad_chip_top_gen as io_fixture
import test_r0915101_a_die_budgets_against_its_own_pad_ring as die_fixture
from _hostpaths import require_repo

NORMAL_D01 = scan.load_d09_dft_contract


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def subject(tmp_path, monkeypatch):
    # Existing repository registry actually selects the physical Default route.
    require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow", "flow109.json")
    role_names = {"scan_enable": "enable_i", "scan_in": "serial_i",
                  "scan_out": "serial_o", "test": "test_i", "tck": "test_clock_i"}
    doc = io_fixture.DOC.replace("2 |", "32 |").replace("`q` |", "`q`, `y` |")
    rtl = ("module core(input clk, input rst, input [31:0] d, input y, output q, "
           "input enable_i, input serial_i, output serial_o, input test_i, "
           "input test_clock_i); assign q=d[0]; assign serial_o=q; endmodule\n")
    project = die_fixture._project(l3=doc, rtl=rtl, top="core")
    spec = copy.deepcopy(io_fixture.SPEC)
    spec["top_ports"][2].update(width=32, msb=31)
    spec["top_ports"].append({"name": "y", "direction": "input", "width": 1})
    write(project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json", spec)
    intent = {"requires_scan": True, "requires_dft": True, "test_port_def": {
        role: {"public": name, "native": role} for role, name in role_names.items()}}
    declaration = project / "plugin_output/declaration.json"
    write(declaration, {"dft": intent})
    d01 = layout.report_path(project, "phase1_one_shot.json")
    write(d01, {"software_upstream_fixture": True, "project": str(project)})
    binding = {"path": "plugin_output/declaration.json", "sha256": digest(declaration),
               "sources": {"input/docs/L3_external_interface.md":
                           "sha256:" + digest(project / "input/docs/L3_external_interface.md")},
               "intent": intent}
    def upstream(p, **_kwargs):
        return ((copy.deepcopy(binding), []) if p.resolve() == project.resolve()
                else (None, ["foreign software upstream project"]))
    monkeypatch.setattr(scan, "load_d09_dft_contract", upstream)
    def record(rel):
        return {"path": rel, "sha256": digest(project / rel)}
    identity = {"producer": {"authority": "requirements_owner"},
        "checker": {"authority": "independent_source_reviewer"},
        "tool_execution": {"kind": "SOURCE_REVIEW_ONLY", "native_execution": False},
        "requirements": {"basis": "synthetic independent planned pad choice"},
        "configuration": {"purpose": "D09.default.planned_test_pads"},
        "consumed_inputs": {"D01": record(d01.relative_to(project).as_posix()),
            "declaration": {"path": binding["path"], "sha256": binding["sha256"]},
            "declaration_sources": binding["sources"],
            "functional_pad_source": record("input/docs/L3_external_interface.md"),
            "functional_interface": record("phase1/generated_docs/L9_INTEGRATION_SPEC.json"),
            "tapeout_declaration": record(TD.DECLARATION_REL),
            "rtl_inputs": frontend_inputs.source_binding(project, "core",
                sources.rtl_source_files(project))["files"]}}
    rows = [{"name": role_names[r], "direction": "output" if r == "scan_out" else "input",
             "side": "E" if r == "tck" else "S"} for r in role_names]
    body = {"schema": "vibeic.dft-test-access.v1", "profile": "default_planned",
            "mapping": "dedicated_pads", "reference": {"ports": rows},
            "reference_identity": identity}
    authority_input = project / "input/flow109/pad-choice.json"
    def approve():
        payload = {k: body[k] for k in ("profile", "mapping", "reference", "reference_identity")}
        write(authority_input, {"dft_test_access": payload})
        body["approval"] = {"status": "APPROVED", "authority": "requirements_owner",
                            "source_reference": {"path": "input/flow109/pad-choice.json",
                                                 "sha256": digest(authority_input)}}
        write(project / "config/dft_test_access.json", body)
    approve()
    features = copy.deepcopy(next(r["features"] for r in flow109.load_registry()["reference_profiles"]
        if r["name"] == "Small digital IC without DFT"))
    features.update(requires_scan=True, requires_dft=True)
    context = flow109.execution_context(flow109.resolve_plan(features), "D32", "D32")
    context_path = tmp_path / "context.json"
    write(context_path, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_path))
    netlist = project / "phase2/stage2/synth/post_dft_netlist.v"
    netlist.parent.mkdir(parents=True)
    # Yosys publishes the non-ANSI shape consumed by netlist_top_ports.
    netlist.write_text("module core(clk, rst, d, y, q, enable_i, serial_i, serial_o, test_i, test_clock_i);\n"
        "input clk;\ninput rst;\ninput [31:0] d;\ninput y;\noutput q;\n"
        "input enable_i;\ninput serial_i;\noutput serial_o;\ninput test_i;\n"
        "input test_clock_i;\nassign q=d[0];\nassign serial_o=q;\nendmodule\n")
    native = {"adopted_netlist": {"path": netlist.relative_to(project).as_posix(),
                                 "sha256": digest(netlist)},
              "software_upstream_fixture": True}
    monkeypatch.setattr(flow109, "dft_source_intent", lambda p, c: binding)
    monkeypatch.setattr(flow109, "physical_d24_binding", lambda p, c, i: copy.deepcopy(native))
    monkeypatch.setattr(backend, "pnr_input_netlist", lambda p, t: (netlist, "software D24 precondition", True))
    return project, body, approve, native, netlist


def run_budget(project):
    output = project / "reports/phase2/gates/slot_pad_budget.json"
    rc = budget.main([str(project), "--top", "core", "--json", str(output)])
    return rc, json.loads(output.read_text())


def test_planned_budget_and_actual_wrapper_share_one_source_plan(subject, tmp_path):
    project, body, _, _, _ = subject
    old_source = digest(project / "input/docs/L3_external_interface.md")
    rc, report = run_budget(project)
    assert rc == 0 and report["verdict"] == "FITS", report
    assert report["own_ring"]["unbonded_count"] == 0
    assert report["own_ring_arithmetic"]["signal_pads_owed"] == 39
    assert report["own_ring_arithmetic"]["ring_capacity_pads"] == 41
    assert report["own_ring_arithmetic"]["ring_geometric_capacity_pads"] is None
    rc, physical_record = physical.run(project, str(io_fixture._pdk(tmp_path / "pdk")), "testpdk")
    assert rc == 0
    early = report["derived_ring"]["planned_test_access"]
    assert early["declaration_sha256"] == physical_record["test_access"]["declaration_sha256"]
    assert early["source_identity"] == physical_record["test_access"]["source_identity"]
    assert physical_record["scan_interface"]["scan_chain_qualification"] == "NOT_MEASURED"
    assert physical_record["pad_placement"]["source"] == "input/docs/L3_external_interface.md"
    assert report["derived_ring"]["by_side"]["E"] == ["clk", "test_clock_i"]
    assert report["derived_ring"]["by_side"]["S"] == ["rst", "enable_i", "serial_i", "serial_o", "test_i"]
    assert report["derived_ring"]["by_side"]["N"] == [f"d[{bit}]" for bit in range(31, -1, -1)]
    assert report["derived_ring"]["by_side"]["W"] == ["q", "y"]
    assert len(physical_record["pad_instances"]) == 41
    wrapper = (project / "phase3/stage3/pnr/chip_top_io.v").read_text()
    for row in body["reference"]["ports"]:
        assert f".{row['name']}({row['name']})" in wrapper
        assert f"u_pad_{row['name']}" in wrapper
    assert digest(project / "input/docs/L3_external_interface.md") == old_source


@pytest.mark.parametrize("damage", ["missing_role", "duplicate", "wrong_direction",
    "bad_side", "unapproved", "self_resealed", "changed_D01", "changed_RTL", "changed_pad_source"])
def test_current_plan_refusals_reach_the_budget(subject, damage):
    project, body, approve, _, _ = subject
    rows = body["reference"]["ports"]
    if damage == "missing_role": rows.pop()
    elif damage == "duplicate": rows[-1] = copy.deepcopy(rows[0])
    elif damage == "wrong_direction": rows[0]["direction"] = "output"
    elif damage == "bad_side": rows[0]["side"] = "inside"
    elif damage == "unapproved": body["approval"]["status"] = "UNAPPROVED"
    elif damage == "self_resealed": rows[0]["side"] = "W"
    else:
        path = {"changed_D01": layout.report_path(project, "phase1_one_shot.json"),
                "changed_RTL": project / "phase2/stage1/rtl/core.v",
                "changed_pad_source": project / "input/docs/L3_external_interface.md"}[damage]
        path.write_bytes(path.read_bytes() + b"\n")
    if damage in {"missing_role", "duplicate", "wrong_direction", "bad_side"}: approve()
    elif damage in {"unapproved", "self_resealed"}: write(project / "config/dft_test_access.json", body)
    rc, report = run_budget(project)
    assert rc != 0 and report["verdict"] != "FITS", report
    assert "DFT_TEST_PAD_PLAN_INVALID" in report["reason"], report


@pytest.mark.parametrize("damage", ["unknown", "missing", "wrong_direction", "stale", "unqualified"])
def test_default_physical_consumer_requires_actual_current_native_ports(subject, damage):
    project, _, _, native, netlist = subject
    ports = json.loads((project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())["top_ports"]
    _, _, current = physical._declared_test_access(project, ports)
    assert current["netlist_sha256"] == digest(netlist)
    text = netlist.read_text()
    if damage == "unknown": text = text.replace("core(clk,", "core(unknown_i, clk,").replace("input clk;", "input unknown_i;\ninput clk;")
    elif damage == "missing": text = text.replace("enable_i, ", "").replace("input enable_i;\n", "")
    elif damage == "wrong_direction": text = text.replace("input enable_i", "output enable_i")
    elif damage == "unqualified": native["adopted_netlist"]["path"] = "phase2/stage2/synth/foreign.v"
    else: text += "\n// stale changed native bytes\n"
    netlist.write_text(text)
    if damage in {"unknown", "missing", "wrong_direction"}:
        native["adopted_netlist"]["sha256"] = digest(netlist)
    with pytest.raises(physical.Refusal) as caught:
        physical._declared_test_access(project, ports)
    assert caught.value.rule == "DFT_TEST_ACCESS_INVALID"


def test_plan_does_not_waive_missing_real_pad_library_or_supply_pair(subject, tmp_path):
    project, _, _, _, _ = subject
    pdk = io_fixture._pdk(tmp_path / "pdk")
    with pytest.raises(physical.Refusal) as caught:
        physical.run(project, str(pdk), "testpdk", power_net="power", ground_net="ground")
    assert caught.value.rule == "SUPPLY_PAD_PAIR_UNRESOLVED"


def test_truthy_strings_cannot_replace_normal_D01_admission(subject, monkeypatch):
    project, _, _, _, _ = subject
    monkeypatch.setattr(scan, "load_d09_dft_contract", NORMAL_D01)
    rc, report = run_budget(project)
    assert rc != 0 and report["verdict"] != "FITS", report
    assert "current D01 full-scan authority unavailable" in report["reason"]


def test_planned_view_cannot_override_typed_pad_ring(subject):
    project, body, approve, _, _ = subject
    path = project / TD.DECLARATION_REL
    declared = json.loads(path.read_text())
    declared, _ = TD.merge_answers(declared, {"pad_signal_map": {"existing": "clk"},
        "pad_order_by_side": {"east": ["existing"]}})
    write(path, declared)
    body["reference_identity"]["consumed_inputs"]["tapeout_declaration"]["sha256"] = digest(path)
    approve()
    rc, report = run_budget(project)
    assert rc != 0 and report["verdict"] != "FITS", report
    assert "cannot override a typed declared ring" in report["reason"]


def test_duplicate_planned_authority_keys_are_unresolved(subject):
    project, _, _, _, _ = subject
    path = project / "config/dft_test_access.json"
    path.write_text(path.read_text().replace('"mapping":', '"mapping":"alias", "mapping":', 1))
    rc, report = run_budget(project)
    assert rc != 0 and report["verdict"] != "FITS", report
    assert "duplicate planned-input key" in report["reason"]


def test_planned_view_refuses_real_missing_output_pad_master(subject, tmp_path):
    project, _, _, _, _ = subject
    pdk = io_fixture._pdk(tmp_path / "pdk", macros=io_fixture.FULL_MACROS.replace("PAD INOUT", "PAD INPUT"))
    with pytest.raises(physical.Refusal) as caught:
        physical.run(project, str(pdk), "testpdk")
    assert caught.value.rule == "NO_PAD_MASTER_FOR_DIRECTION"


def test_fully_rebound_side_conflict_cannot_replace_a_functional_pad(subject):
    project, body, approve, _, _ = subject
    path = project / "input/docs/L3_external_interface.md"
    path.write_text(path.read_text().replace("`clk` |", "`clk`, `enable_i` |"))
    inputs = body["reference_identity"]["consumed_inputs"]
    inputs["functional_pad_source"]["sha256"] = digest(path)
    inputs["declaration_sources"]["input/docs/L3_external_interface.md"] = "sha256:" + digest(path)
    approve()
    rc, report = run_budget(project)
    assert rc != 0 and report["verdict"] != "FITS", report
    assert "cannot alias or replace the functional partition" in report["reason"]
