"""Selected memory ports come from the design declaration, not its RTL."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAM = Path(__file__).resolve().parents[1] / "spec_conformance_check.py"
SPEC = {"top_module": "controller", "ports": [
    {"name": "clk", "direction": "input", "width": 1},
    {"name": "o_memory_addr", "direction": "output", "width": 10},
    {"name": "o_memory_data", "direction": "output", "width": 8},
    {"name": "i_memory_data", "direction": "input", "width": 8},
    {"name": "o_memory_we", "direction": "output", "width": 1},
]}
CHOICE = {"top_module": "controller",
          "memory_interface_protocol": "sdp8_waddr_wdata_wen_raddr_rdata_sync1r",
          "memory_interface": {
              "read_address": "read_pointer", "write_address": "write_pointer",
              "write_data": "payload_o", "read_data": "payload_i",
              "write_enable": "commit_o", "read_latency_cycles": 1}}
RTL = """module controller(input clk, input [7:0] payload_i,
output [9:0] read_pointer, output [9:0] write_pointer,
output [7:0] payload_o, output commit_o);
endmodule
"""
DOC = """The memory protocol may use a shared address or separate read/write addresses.
The memory sub-port names are illustrative and chosen in declaration.json.
| Port | Width | Direction | Description |
| --- | --- | --- | --- |
| o_memory_addr | 10 | output | address (typical) |
| o_memory_data | 8 | output | write data (typical) |
| i_memory_data | 8 | input | read data (typical) |
| o_memory_we | 1 | output | write enable (typical) |
"""


def run_check(project, *, choice=CHOICE, rtl=RTL, doc=DOC, manifest=None, spec=SPEC):
    source = project / "phase2/stage1/rtl"
    source.mkdir(parents=True)
    (source / "controller.v").write_text(rtl)
    if manifest is not None:
        (source / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "L3_interface.md").write_text(doc)
    if choice is not None:
        declaration = project / "plugin_output/declaration.json"
        declaration.parent.mkdir()
        declaration.write_text(json.dumps(choice))
    spec_path = project / "L9.json"
    spec_path.write_text(json.dumps(spec))
    result = project / "findings.json"
    proc = subprocess.run([sys.executable, str(PROGRAM), "--spec", str(spec_path),
                           "--rtl-dir", str(source), "--top", "controller",
                           "--json", str(result)], capture_output=True, text=True)
    findings = json.loads(result.read_text())
    return proc, findings


def test_declared_dual_port_passes_without_manifest_or_binding(tmp_path):
    proc, findings = run_check(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not [f for f in findings if f["severity"] == "ERROR"]
    assert not (tmp_path / "phase2/stage1/rtl/SOURCE_MANIFEST.json").exists()


def test_undeclared_dual_port_fails(tmp_path):
    proc, findings = run_check(tmp_path, choice=None)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert {"port-missing", "port-extra"} <= {f["rule"] for f in findings}


def test_rtl_must_use_the_declared_names(tmp_path):
    proc, findings = run_check(tmp_path, rtl=RTL.replace("commit_o", "other_enable"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    errors = [f for f in findings if f["severity"] == "ERROR"]
    assert any(f["rule"] == "port-missing" and f["symbol"] == "commit_o" for f in errors)
    assert any(f["rule"] == "port-extra" and f["symbol"] == "other_enable" for f in errors)


@pytest.mark.parametrize("mutation", [
    "incomplete", "ambiguous", "duplicate", "address-modes", "no-protocol", "wrong-top",
])
def test_unresolved_choice_keeps_document_default(tmp_path, mutation):
    choice = json.loads(json.dumps(CHOICE))
    if mutation == "incomplete":
        del choice["memory_interface"]["write_address"]
    elif mutation == "ambiguous":
        choice["memory_interface"]["read_address"] = ["read_pointer", "other_pointer"]
    elif mutation == "duplicate":
        choice["memory_interface"]["write_address"] = "read_pointer"
    elif mutation == "address-modes":
        choice["memory_interface"]["address"] = "read_pointer"
    elif mutation == "no-protocol":
        del choice["memory_interface_protocol"]
    else:
        choice["top_module"] = "another_controller"
    proc, findings = run_check(tmp_path, choice=choice)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert {"port-missing", "port-extra"} <= {f["rule"] for f in findings}


@pytest.mark.parametrize("rtl,rule", [
    (RTL.replace("[9:0] read_pointer", "[8:0] read_pointer"), "port-width-mismatch"),
    (RTL.replace("output commit_o", "input commit_o"), "port-direction-mismatch"),
])
def test_selected_ports_preserve_document_electrical_requirements(tmp_path, rtl, rule):
    proc, findings = run_check(tmp_path, rtl=rtl)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert rule in {f["rule"] for f in findings}


def test_fixed_document_name_is_not_replaced(tmp_path):
    proc, findings = run_check(tmp_path, doc=DOC + "o_memory_addr is a mandatory fixed port name.\n")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert any(f["rule"] == "port-missing" and f["symbol"] == "o_memory_addr" for f in findings)


@pytest.mark.parametrize("flag", ["required", "mandatory"])
def test_required_document_name_survives_a_declared_choice(tmp_path, flag):
    spec = json.loads(json.dumps(SPEC))
    spec["ports"][1][flag] = True
    proc, findings = run_check(tmp_path, spec=spec)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert any(f["rule"] == "port-missing" and f["symbol"] == "o_memory_addr"
               for f in findings)
    assert not (tmp_path / "phase2/stage1/rtl/SOURCE_MANIFEST.json").exists()


def test_declaration_cannot_override_an_undelegated_interface(tmp_path):
    doc = DOC.replace("illustrative", "fixed").replace("(typical)", "")
    proc, findings = run_check(tmp_path, doc=doc)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert {"port-missing", "port-extra"} <= {f["rule"] for f in findings}


@pytest.mark.parametrize("incomplete", [False, True])
def test_legacy_rename_cannot_override_a_structured_choice(tmp_path, incomplete):
    choice = json.loads(json.dumps(CHOICE))
    if incomplete:
        del choice["memory_interface"]["write_address"]
    manifest = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_memory_addr"], "rtl": ["read_pointer", "write_pointer"]},
        {"l9": ["o_memory_data"], "rtl": ["payload_o"]},
        {"l9": ["i_memory_data"], "rtl": ["payload_i"]},
        {"l9": ["o_memory_we"], "rtl": ["other_enable"]},
    ]}
    proc, findings = run_check(tmp_path, choice=choice, manifest=manifest,
                               rtl=RTL.replace("commit_o", "other_enable"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert {"port-missing", "port-extra"} <= {f["rule"] for f in findings}
