"""Inactive pad directions need a declared direction and native constant controls."""
import json
from pathlib import Path
import shutil

import pytest

import flow_engine as engine
import phase1_doc_one_shot_runner as phase1


def project_inputs(project, missing):
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    text = ("# unit external interface\n\n```verilog\nmodule unit; endmodule\n```\n\n"
            "| Port | Dir | Width | Description |\n|---|---|---|---|\n"
            "| `rx` | in | 1 | Receive data |\n")
    if missing != "document":
        text += "| `tx` | out | 1 | Transmit data |\n"
    (docs / "interface.md").write_text(text)
    phase1.gen_l1_datasheet(project, {"interface.md": text})
    phase1.gen_l9_integration_spec(project, {"interface.md": text}, {})
    liberty = project / "pads.lib"
    liberty.write_text('''library (neutral) {
  delay_model : table_lookup; time_unit : "1ns"; voltage_unit : "1V";
  current_unit : "1mA"; capacitive_load_unit (1,pf);
  cell (neutral_pad) {
    pin (BOND) {
      direction : inout;
      is_pad : true;
      function : "DATA";
      three_state : "!DRIVE";
    }
    pin (RECEIVE) {
      direction : output;
      function : "BOND & RECEIVE_ENABLE";
    }
    pin (DATA) {
      direction : input;
    }
    pin (DRIVE) {
      direction : input;
    }
    pin (RECEIVE_ENABLE) {
      direction : input;
    }
  }
}
''')
    netlist = project / "chip.nl.v"
    drive = "mode" if missing == "control_rx" else "1'b0"
    receive = "mode" if missing == "control_tx" else "1'b0"
    netlist.write_text(f'''module unit_chip(inout rx, tx, input mode);
neutral_pad receiver(.BOND(rx), .RECEIVE(), .DATA(1'b0), .DRIVE({drive}), .RECEIVE_ENABLE(1'b1));
neutral_pad transmitter(.BOND(tx), .RECEIVE(), .DATA(mode), .DRIVE(1'b1), .RECEIVE_ENABLE({receive}));
endmodule
''')
    return liberty, netlist


def test_phase1_preserves_the_direction_of_every_documented_port(tmp_path):
    text = ("# unit external interface\n```verilog\nmodule unit; endmodule\n```\n"
            "| Port | Dir | Width | Description |\n|---|---|---|---|\n"
            + "".join(f"| `signal_{i}` | input | 1 | Required signal |\n" for i in range(55)))
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "interface.md").write_text(text)
    phase1.gen_l1_datasheet(tmp_path, {"interface.md": text})
    result = phase1.gen_l9_integration_spec(tmp_path, {"interface.md": text}, {})
    rows = json.loads(Path(result.path).read_text())["top_ports"]
    assert {p["name"] for p in rows} == {f"signal_{i}" for i in range(55)}


@pytest.mark.parametrize("missing,remaining,excluded", [
    ("none", 0, {"rx", "tx"}),
    ("document", 1, {"rx"}),
    ("control_rx", 1, {"tx"}),
    ("control_tx", 1, {"rx"}),
])
def test_real_native_controls_and_document_declarations_both_required(tmp_path, missing, remaining, excluded):
    if not shutil.which("sta"):
        pytest.skip("native OpenSTA required")
    liberty, netlist = project_inputs(tmp_path, missing)
    row = next(r for r in engine.read_json(engine.TABLE)["steps"] if r["name"] == "pre_layout_timing")
    directory = tmp_path / "steps/pre_layout_timing/openroad_staprepnr"
    corner = directory / "tt"
    corner.mkdir(parents=True)
    source = tmp_path / "source.sdc"
    source.write_text("# Authored timing deck remains untouched\n")
    (corner / "checks.rpt").write_text(
        "check_setup -verbose\nWarning: There is 1 input port missing set_input_delay.\n  tx\n"
        "Warning: There is 1 unconstrained endpoint.\n  rx\n")
    (corner / "sta.log").write_text(f"Reading design constraints file at '{source}'\n")
    (directory / "state_in.json").write_text(json.dumps({"nl": str(netlist)}))
    config = {"DESIGN_NAME": "unit_chip", "LIB": [str(liberty)], "DEFAULT_CORNER": "tt",
              "PNR_SDC_FILE": str(source)}
    result = engine.finish_step(tmp_path, row, row["tool"], engine.ToolResult(True, 0), config,
                               {"always": True, "digital_netlist": True}, elapsed=0)
    assert result["native_metrics"]["unconstrained_required_paths"] == remaining, result
    assert result["status"] == ("FAIL" if remaining else "PASS"), result
    records = [o for o in result["observations"] if o.get("kind") == "inactive_pad_direction"]
    assert {o["port"] for o in records} == excluded
    for record in records:
        assert any(s.get("file") == str(tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json")
                   and s.get("field", "").startswith("top_ports[") for s in record["sources"])
        native = [s for s in record["sources"] if s.get("controls")]
        assert native and all(s["file"] == str(netlist) and s["liberty"] == str(liberty) for s in native)
        assert all(Path(s["report"]).is_file() for s in native)
    assert source.read_text() == "# Authored timing deck remains untouched\n"
    assert result["tool_seconds"] > 0


@pytest.mark.parametrize("missing,remaining", [
    ("none", 0), ("protocol", 2), ("delegation", 2), ("wrong_top", 2), ("control_rx", 1),
    ("undeclared_top", 0), ("undeclared_top_missing_choice", 2), ("undeclared_top_bad_name", 2),
])
def test_selected_interface_direction_keeps_both_sources(tmp_path, missing, remaining):
    if not shutil.which("sta"):
        pytest.skip("native OpenSTA required")
    from flow_native_timing import read_sta_reports

    liberty, netlist = project_inputs(tmp_path, missing)
    doc = ("Top module: `unit`.\n"
           "The memory sub-port names are illustrative and chosen in declaration.json.\n"
           "| Port | Dir | Width | Description |\n|---|---|---|---|\n"
           "| o_memory_addr | output | 10 | address (typical) |\n"
           "| o_memory_data | output | 8 | write data (typical) |\n"
           "| i_memory_data | input | 8 | read data (typical) |\n"
           "| o_memory_we | output | 1 | write enable (typical) |\n")
    if missing == "delegation":
        doc = doc.replace("illustrative", "fixed").replace("(typical)", "")
    if missing.startswith("undeclared_top"):
        (tmp_path / "input/docs/interface.md").unlink()
        doc = doc.replace("Top module: `unit`.\n", "# Delegated memory interface\n")
    (tmp_path / "input/docs/L3_interface.md").write_text(doc)
    docs = {p.name: p.read_text() for p in (tmp_path / "input/docs").iterdir()}
    phase1.gen_l1_datasheet(tmp_path, docs)
    phase1.gen_l9_integration_spec(tmp_path, docs, {})
    l9 = tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    original_l9 = l9.read_bytes()
    if missing.startswith("undeclared_top"):
        assert json.loads(original_l9)["top_module"] is None
    choice = {"top_module": "unit", "memory_interface_protocol": "separate_address",
              "memory_interface": {"read_address": "read_pointer", "write_address": "write_pointer",
                                   "write_data": "payload_o", "read_data": "payload_i",
                                   "write_enable": "commit_o"}}
    if missing == "protocol":
        del choice["memory_interface_protocol"]
    elif missing == "wrong_top":
        choice["top_module"] = "another_unit"
    elif missing == "undeclared_top_missing_choice":
        del choice["top_module"]
    elif missing == "undeclared_top_bad_name":
        choice["top_module"] = "not a module identifier"
    declaration = tmp_path / "plugin_output/declaration.json"
    declaration.parent.mkdir()
    declaration.write_text(json.dumps(choice))
    netlist.write_text(netlist.read_text().replace("rx", "payload_i").replace("tx", "payload_o"))
    directory = tmp_path / "steps/pre_layout_timing/openroad_staprepnr"
    corner = directory / "tt"
    corner.mkdir(parents=True)
    (corner / "checks.rpt").write_text(
        "check_setup -verbose\nWarning: There is 1 input port missing set_input_delay.\n  payload_o\n"
        "Warning: There is 1 unconstrained endpoint.\n  payload_i\n")
    (directory / "state_in.json").write_text(json.dumps({"nl": str(netlist)}))
    result = read_sta_reports(directory, {"DESIGN_NAME": "unit_chip", "LIB": [str(liberty)],
                                          "DEFAULT_CORNER": "tt"}, project=tmp_path)
    assert result["metrics"]["unconstrained_required_paths"] == remaining, result
    records = result["observations"]
    assert len(records) == 2 - remaining
    for record in records:
        assert any(s["file"] == str(l9) for s in record["sources"])
        assert any(s["file"] == str(declaration)
                   and s.get("field") in {"memory_interface.write_data", "memory_interface.read_data"}
                   for s in record["sources"])
        assert any(s.get("controls") for s in record["sources"])
    assert l9.read_bytes() == original_l9
