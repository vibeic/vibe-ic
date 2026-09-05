"""spec_conformance_check must CONSUME the declared interface rename.

`phase2/stage1/rtl/SOURCE_MANIFEST.json -> renamed_interfaces` is the flow's
documented way (catalog-glue-author/SKILL.md, ORGANIC #711) for a design to say
"this L9 illustrative interface is delivered under these RTL names". It had a
parser (`l9_rtl_pin_consistency_check._manifest_renamed_groups`) and NO consumer
in the 44-step flow, so an author who declared a rename as instructed still got
port-missing + port-extra ERRORs from this gate.

The rename is an ACCEPTED DECLARATION, never a suppression: these tests pin both
halves — the declared rename reconciles, and every malformed / dishonest
declaration still ERRORs, as does any UNDECLARED mismatch.
"""
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1] / "spec_conformance_check.py"

SPEC = {
    "top_module": "dut",
    "ports": [
        {"name": "i_clk",      "direction": "input",  "width": 1},
        {"name": "o_mem_addr", "direction": "output", "width": 10},
        {"name": "o_mem_data", "direction": "output", "width": 8},
    ],
}

RTL_RENAMED = """
module dut(
   input  wire       i_clk,
   output wire [9:0] o_mem_waddr,
   output wire [9:0] o_mem_raddr,
   output wire [7:0] o_mem_wdata);
   assign o_mem_waddr = 10'd0;
   assign o_mem_raddr = 10'd0;
   assign o_mem_wdata = 8'd0;
endmodule
"""


def _project(tmp_path, rtl_src, manifest):
    """Lay out the paths the gate resolves: <proj>/phase2/stage1/rtl."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(rtl_src)
    if manifest is not None:
        (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    spec = tmp_path / "L9.json"
    spec.write_text(json.dumps(SPEC))
    return rtl, spec


def _run(tmp_path, rtl_src, manifest):
    rtl, spec = _project(tmp_path, rtl_src, manifest)
    out = tmp_path / "f.json"
    rc = subprocess.run(
        [sys.executable, str(PROG), "--rtl-dir", str(rtl),
         "--spec", str(spec), "--json", str(out)],
        capture_output=True, text=True).returncode
    findings = json.loads(out.read_text()) if out.is_file() else []
    rules = {f["rule"] for f in findings if f["severity"] == "ERROR"}
    return rc, rules, findings


_GOOD = {"reused_ip": True, "renamed_interfaces": [
    {"l9": ["o_mem_addr"], "rtl": ["o_mem_waddr", "o_mem_raddr"]},
    {"l9": ["o_mem_data"], "rtl": ["o_mem_wdata"]}]}


def test_declared_rename_is_accepted(tmp_path):
    """THE FIX: a 1->N rename with matching direction+width reconciles."""
    rc, rules, findings = _run(tmp_path, RTL_RENAMED, _GOOD)
    assert rc == 0, f"declared rename must reconcile; got ERRORs {rules}"
    assert not rules
    assert any(f["rule"] == "port-renamed-by-manifest" for f in findings)


def test_without_the_manifest_the_same_rtl_still_errors(tmp_path):
    """NEGATIVE CONTROL: no declaration ⇒ the exact-name comparison stands."""
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, None)
    assert rc != 0
    assert "port-missing" in rules and "port-extra" in rules


def test_reused_ip_false_is_not_a_declaration(tmp_path):
    """The keystone flag gates the whole relaxation (fail-closed)."""
    mf = dict(_GOOD, reused_ip=False)
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-missing" in rules and "port-extra" in rules


def test_undeclared_missing_port_still_errors(tmp_path):
    """A port dropped WITHOUT declaring it is still a hard ERROR."""
    rtl = RTL_RENAMED.replace(
        "   output wire [7:0] o_mem_wdata);", "   output wire [7:0] o_unrelated);"
    ).replace("   assign o_mem_wdata = 8'd0;", "   assign o_unrelated = 8'd0;")
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_addr"], "rtl": ["o_mem_waddr", "o_mem_raddr"]}]}
    rc, rules, _ = _run(tmp_path, rtl, mf)
    assert rc != 0
    assert "port-missing" in rules, rules


def test_rename_from_a_port_the_spec_lacks_errors(tmp_path):
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_not_in_spec"], "rtl": ["o_mem_waddr"]}]}
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-rename-undeclared-spec-port" in rules, rules


def test_rename_to_a_port_the_rtl_lacks_errors(tmp_path):
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_addr"], "rtl": ["o_absent"]}]}
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-rename-missing-rtl-port" in rules, rules


def test_rename_may_not_change_width(tmp_path):
    """o_mem_addr is 10 bits; o_mem_wdata is 8 — a rename cannot re-shape it."""
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_addr"], "rtl": ["o_mem_wdata"]}]}
    rc, rules, _ = _run(tmp_path, RTL_RENAMED, mf)
    assert rc != 0
    assert "port-rename-width-mismatch" in rules, rules


def test_rename_may_not_change_direction(tmp_path):
    rtl = RTL_RENAMED.replace("   output wire [7:0] o_mem_wdata);",
                              "   input  wire [7:0] i_mem_rdata);").replace(
        "   assign o_mem_wdata = 8'd0;", "   wire _u = &{1'b0, i_mem_rdata};")
    mf = {"reused_ip": True, "renamed_interfaces": [
        {"l9": ["o_mem_data"], "rtl": ["i_mem_rdata"]}]}
    rc, rules, _ = _run(tmp_path, rtl, mf)
    assert rc != 0
    assert "port-rename-direction-mismatch" in rules, rules
