"""RB2-04 (#2063) — spec_conformance_check hard-ERRORed on a port name whose
ALTERNATIVE SPELLING the input itself offers, and never read the design's own
`plugin_output/declaration.json` that the same input defers the choice to.

MEASURED on the subservient cell (lane rbsub2, 8HD-8, 2026-09-06), whose L3
writes `` `o_sram_data` (or `o_sram_wdata`) `` and says the name is declared in
declaration.json:

    base  FAIL 4 error  port-missing o_sram_data / i_sram_data
                        port-extra   o_sram_wdata / i_sram_rdata
    fixed PASS 0 error  2x INFO port-alternative-spelling

Every direction of the rule is asserted here on one 2-port fixture.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'spec_conformance_check.py'

RTL = """
module dut(input i_clk, input [7:0] i_sram_rdata, output [7:0] o_sram_wdata);
  assign o_sram_wdata = i_sram_rdata;
endmodule
"""

SPEC_PORTS = [
    {"name": "i_clk", "direction": "input", "width": 1},
    {"name": "i_sram_data", "direction": "input", "width": 8},
    {"name": "o_sram_data", "direction": "output", "width": 8},
]


def _project(tmp_path, doc_text, declaration=None):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(RTL)
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    spec = gd / "L9_INTEGRATION_SPEC.json"
    spec.write_text(json.dumps({"top_module": "dut", "ports": SPEC_PORTS}))
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L3_external_interface.md").write_text(doc_text)
    if declaration is not None:
        po = tmp_path / "plugin_output"
        po.mkdir(parents=True)
        (po / "declaration.json").write_text(json.dumps(declaration))
    return rtl, spec


def _run(rtl, spec):
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--rtl-dir', str(rtl),
         '--spec', str(spec)], capture_output=True, text=True)
    return res


ALT_DOC = ("| `o_sram_data` (or `o_sram_wdata`) | 8-bit | output | write |\n"
           "| `i_sram_data` (or `i_sram_rdata`) | 8-bit | input  | read  |\n")
NO_ALT_DOC = "| `o_sram_data` | 8-bit | output | write |\n"


def test_alternative_stated_by_the_input_is_accepted(tmp_path):
    res = _run(*_project(tmp_path, ALT_DOC))
    assert res.returncode == 0, res.stdout
    assert 'port-missing' not in res.stdout
    assert 'port-extra' not in res.stdout
    assert res.stdout.count('port-alternative-spelling') == 2


def test_without_the_alternative_the_finding_stays_visible(tmp_path):
    """The negative control. Same RTL, same spec, same absence of a
    declaration — only the input's `(or ...)` sentence removed."""
    res = _run(*_project(tmp_path, NO_ALT_DOC))
    assert res.returncode == 1, res.stdout
    assert 'port-missing' in res.stdout
    assert 'port-extra' in res.stdout


def test_a_declaration_naming_the_shipped_spelling_is_recorded(tmp_path):
    res = _run(*_project(tmp_path, ALT_DOC,
                         declaration={"sram_write_port_name": "o_sram_wdata",
                                      "sram_read_port_name": "i_sram_rdata"}))
    assert res.returncode == 0, res.stdout
    assert 'declared in plugin_output/declaration.json' in res.stdout


def test_declaring_one_spelling_and_shipping_the_other_is_an_ERROR(tmp_path):
    """The alternative mechanism is not a free pass: a design that DECLARES
    one name and ships the other is caught by a finding that did not exist
    before this change."""
    res = _run(*_project(tmp_path, ALT_DOC,
                         declaration={"sram_write_port_name": "o_sram_data"}))
    assert res.returncode == 1, res.stdout
    assert 'port-declared-spelling-mismatch' in res.stdout


def test_an_undeclared_extra_port_is_untouched(tmp_path):
    rtl, spec = _project(tmp_path, ALT_DOC)
    (rtl / "dut.v").write_text(RTL.replace(
        "output [7:0] o_sram_wdata)",
        "output [7:0] o_sram_wdata, output o_undeclared)").replace(
        "endmodule", "assign o_undeclared = 1'b0;\nendmodule"))
    res = _run(rtl, spec)
    assert res.returncode == 1, res.stdout
    assert 'o_undeclared' in res.stdout
