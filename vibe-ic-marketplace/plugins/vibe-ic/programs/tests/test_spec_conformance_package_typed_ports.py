"""Package-scoped SystemVerilog port types must not become port names.

The affected whole-IC run generated an ordinary ANSI header containing forms
such as ``output pkg::word_t data_o``.  The conformance parser reported
``pkg`` as the port and lost ``data_o``.  These fixtures exercise the grammar,
not any design-specific identifier.
"""
import json
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
SCRIPT = PROGRAMS / "spec_conformance_check.py"
sys.path.insert(0, str(PROGRAMS))
from _specrtl_common import parse_rtl_ports  # noqa: E402


RTL = """\
module widget
  import header_pkg::*;
(
  input  logic                         clk_i,
  output payload_pkg::payload_t         payload_o,
  input  control_pkg::control_t [N-1:0] control_i
);
endmodule
"""


def test_package_scoped_types_keep_the_declared_port_names():
    name, ports = parse_rtl_ports(RTL, "widget")
    assert name == "widget"
    assert [(p.name, p.direction) for p in ports] == [
        ("clk_i", "input"),
        ("payload_o", "output"),
        ("control_i", "input"),
    ]


def test_untyped_comma_list_is_not_consumed_as_a_type():
    _, ports = parse_rtl_ports(
        "module plain(input a, b, output logic y); endmodule", "plain")
    assert [(p.name, p.direction) for p in ports] == [
        ("a", "input"), ("b", "input"), ("y", "output")]


def test_real_missing_spec_port_still_fails(tmp_path):
    rtl = tmp_path / "widget.sv"
    rtl.write_text(RTL)
    spec = tmp_path / "L9.json"
    spec.write_text(json.dumps({
        "top_module": "widget",
        "ports": [
            {"name": "clk_i", "direction": "input", "width": 1},
            {"name": "payload_o", "direction": "output", "width": 1},
            {"name": "control_i", "direction": "input", "width": -1},
            {"name": "required_i", "direction": "input", "width": 1},
        ],
    }))
    out = tmp_path / "findings.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(spec),
         "--json", str(out), str(rtl)], capture_output=True, text=True)
    findings = json.loads(out.read_text())
    assert proc.returncode == 1
    assert {(f["rule"], f["symbol"]) for f in findings} == {
        ("port-missing", "required_i")}
