"""Document scope removes only explicitly declared external timing findings."""
import json
from pathlib import Path

import pytest

import flow_engine as engine
import phase1_doc_one_shot_runner as phase1


def declared_project(project, description="Unused by this design", switch=0):
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    text = ("# unit external interface\n\n"
            "```verilog\nmodule unit(input clk, event_in, unknown, inout spare); endmodule\n```\n\n"
            "| Port | Dir | Width | Description |\n|---|---|---|---|\n"
            f"| `spare` | inout | 1 | {description} |\n"
            "| `event_in` | in | 1 | External event |\n"
            "| `unknown` | in | 1 | Required input |\n")
    (docs / "interface.md").write_text(text)
    sdc = project / "input/constraints/source.sdc"
    sdc.parent.mkdir(parents=True)
    sdc.write_text(f"""# IO ports are assumed to be asynchronous. If synchronous, set IO_SYNC to 1.
set ::env(IO_SYNC) {switch}
create_clock -name core -period 10 [get_ports clk]
if {{ $::env(IO_SYNC) }} {{
  set_input_delay 2 -clock core [get_ports {{event_in}}]
}}
""")
    phase1.gen_l1_datasheet(project, {"interface.md": text})
    result = phase1.gen_l9_integration_spec(project, {"interface.md": text}, {})
    return json.loads(Path(result.path).read_text()), sdc


def native_result(project, sdc, findings):
    row = next(r for r in json.loads(engine.TABLE.read_text())["steps"] if r["name"] == "pre_layout_timing")
    directory = project / "steps/pre_layout_timing/openroad_staprepnr/tt"
    directory.mkdir(parents=True)
    (directory / "checks.rpt").write_text("check_setup -verbose\n" + findings)
    (directory / "sta.log").write_text(f"Reading design constraints file at '{sdc}'\n")
    return engine.finish_step(project, row, row["tool"], engine.ToolResult(True, 0),
                              {"PNR_SDC_FILE": str(sdc)}, {"always": True, "digital_netlist": True}, elapsed=0)


def refresh_scope(project):
    import l9_l19_contract_carrythrough as carry

    gd = project / "phase1/generated_docs"
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({"fields": {}}))
    carry.run(project)
    return json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())


def test_phase1_records_timing_class_with_exact_source_lines(tmp_path):
    l9, _ = declared_project(tmp_path)
    ports = {p["name"]: p for p in l9["top_ports"]}
    assert ports["spare"].get("timing_class") == "unused"
    assert ports["event_in"].get("timing_class") == "asynchronous"
    assert "timing_class" not in ports["unknown"]
    for name in ("spare", "event_in"):
        quoted = []
        for source in ports[name]["timing_class_sources"]:
            assert source["line"] > 0
            quoted.append((tmp_path / source["file"]).read_text().splitlines()[source["line"] - 1])
            assert quoted[-1]
        assert any(name in line for line in quoted)


@pytest.mark.parametrize("remaining,expected", [("", "PASS"), (
    "Warning: There is 1 unconstrained endpoint.\n  unknown\n", "FAIL"), (
    "Warning: There is 1 unconstrained endpoint.\n  u_logic/spare\n", "FAIL")])
def test_actual_row_excludes_documented_ports_and_keeps_other_findings(tmp_path, remaining, expected):
    _, sdc = declared_project(tmp_path)
    result = native_result(tmp_path, sdc,
        "Warning: There are 2 input ports missing set_input_delay.\n  event_in\n  spare\n"
        "Warning: There is 1 unconstrained endpoint.\n  spare\n" + remaining)
    assert result["status"] == expected
    assert result["native_metrics"]["unconstrained_endpoints"] == (0 if expected == "PASS" else 1)
    excluded = {item["port"]: item for item in result["observations"]
                if item.get("kind") == "documented_port_timing"}
    assert set(excluded) == {"event_in", "spare"}
    assert excluded["event_in"]["timing_class"] == "asynchronous"
    assert excluded["spare"]["timing_class"] == "unused"
    assert all(item["sources"] for item in excluded.values())


@pytest.mark.parametrize("description", ["May be unused", "Asynchronous? Undecided", "Not unused; required interface",
                                          "Unused during sleep; active in operation"])
def test_ambiguous_or_denied_statement_excludes_nothing(tmp_path, description):
    _, sdc = declared_project(tmp_path, description)
    result = native_result(tmp_path, sdc, "Warning: There is 1 unconstrained endpoint.\n  spare\n")
    assert result["status"] == "FAIL"
    assert result["native_metrics"]["unconstrained_endpoints"] == 1
    assert not any(o.get("port") == "spare" for o in result["observations"])


def test_enabled_synchronous_sdc_switch_does_not_declare_asynchronous_port(tmp_path):
    l9, _ = declared_project(tmp_path, switch=1)
    port = next(p for p in l9["top_ports"] if p["name"] == "event_in")
    assert "timing_class" not in port


@pytest.mark.parametrize("note", [
    "# IO ports may be asynchronous. If synchronous, set IO_SYNC to 1.",
    "# IO ports are assumed to be asynchronous. IO_SYNC enables debug logging.",
])
def test_sdc_requires_an_explicit_asynchronous_mode_and_its_own_switch(tmp_path, note):
    _, sdc = declared_project(tmp_path)
    sdc.write_text(note + "\n" + "\n".join(sdc.read_text().splitlines()[1:]) + "\n")
    l9 = refresh_scope(tmp_path)
    port = next(p for p in l9["top_ports"] if p["name"] == "event_in")
    assert "timing_class" not in port


def test_conflicting_port_descriptions_declare_nothing(tmp_path):
    declared_project(tmp_path)
    (tmp_path / "input/docs/other.md").write_text(
        "| Port | Dir | Description |\n|---|---|---|\n| `spare` | inout | Not unused |\n")
    l9 = refresh_scope(tmp_path)
    assert "timing_class" not in next(p for p in l9["top_ports"] if p["name"] == "spare")


def test_child_module_port_with_the_same_name_cannot_exclude_a_top_port(tmp_path):
    declared_project(tmp_path, description="Required interface")
    (tmp_path / "input/docs/child.md").write_text(
        "```verilog\nmodule child(inout spare); endmodule\n```\n"
        "| Port | Dir | Description |\n|---|---|---|\n| `spare` | inout | Unused |\n")
    l9 = refresh_scope(tmp_path)
    assert "timing_class" not in next(p for p in l9["top_ports"] if p["name"] == "spare")


@pytest.mark.parametrize("shape", ["flat", "nested", "legacy"])
def test_literal_scalar_sdc_ports_and_l9_record_shapes(tmp_path, shape):
    _, sdc = declared_project(tmp_path)
    sdc.write_text(sdc.read_text().replace("[get_ports {event_in}]", "[get_ports event_in]"))
    path = tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    body = json.loads(path.read_text())
    if shape == "nested":
        body = {"fields": body}
    else:
        if shape == "legacy":
            body.pop("top_ports")
        body["fields"] = {"other_annotation": "preserve"}
    path.write_text(json.dumps(body))
    refresh_scope(tmp_path)
    result = native_result(tmp_path, sdc,
        "Warning: There is 1 input port missing set_input_delay.\n  event_in\n")
    assert result["status"] == "PASS"
    excluded = [o for o in result["observations"] if o.get("kind") == "documented_port_timing"]
    assert [o["port"] for o in excluded] == ["event_in"]


def test_unlisted_native_findings_and_internal_clock_pins_remain(tmp_path):
    _, sdc = declared_project(tmp_path)
    result = native_result(tmp_path, sdc,
        "Warning: There are 2 unconstrained endpoints.\n  spare\n"
        "Warning: There is 1 register clock pin with no clock.\n  u_logic/CLK\n")
    assert result["status"] == "FAIL"
    assert result["native_metrics"]["unconstrained_endpoints"] == 1
    assert result["native_metrics"]["unconstrained_required_paths"] == 2


def test_phase1_carrythrough_refreshes_scope_from_current_documents(tmp_path):
    declared_project(tmp_path)
    path = tmp_path / "input/docs/interface.md"
    path.write_text(path.read_text().replace("Unused by this design", "May be unused"))
    l9 = refresh_scope(tmp_path)
    port = next(p for p in l9["top_ports"] if p["name"] == "spare")
    assert "timing_class" not in port


def test_only_literal_bus_bits_of_a_declared_port_are_excluded(tmp_path):
    _, sdc = declared_project(tmp_path)
    result = native_result(tmp_path, sdc,
        "Warning: There are 3 unconstrained endpoints.\n  spare[0]\n  spare_extra\n  u_logic/spare[0]\n")
    assert result["status"] == "FAIL"
    assert result["native_metrics"]["unconstrained_endpoints"] == 2
    assert {o["port"] for o in result["observations"] if o.get("kind") == "documented_port_timing"} == {"spare[0]"}
