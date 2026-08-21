"""ORGANIC-20260801 — staged hard-macro model discovery + blackbox staging.

A design that instantiates a hard-macro whose model is STAGED under its own
input/pdk_local/ (L8 abstract triplet .lib/.lef/.v) previously failed the
Phase-2 reference-TB, the generic sanity-synth, and the LEC gold build with
`Unknown module type: <macro>` because all three glob rtl/ only. These tests
pin the shared discovery/blackbox helper: a POSITIVE case (staged macro found +
blackboxed) and NEGATIVE controls (no staged root, and a macro defined in rtl/
is NOT treated as staged) so the helper stays a no-op on designs without a
staged hard-macro.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _hardmacro_stage as hms  # noqa: E402


def _mk_project(tmp_path, *, stage_macro=True, define_in_rtl=False,
                record_manifest=True):
    proj = tmp_path
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    body = (
        "module dut(input clk, output [7:0] q);\n"
        "  ram2048x8 u_ram (.clk(clk), .q(q));\n"
        "endmodule\n"
    )
    if define_in_rtl:
        body += ("module ram2048x8(input clk, output reg [7:0] q);\n"
                 "  always @(posedge clk) q <= 8'h0;\n"
                 "endmodule\n")
    (rtl / "dut.v").write_text(body)
    if stage_macro:
        macro_dir = proj / "input" / "pdk_local" / "vendorX"
        macro_dir.mkdir(parents=True)
        (macro_dir / "ram2048x8.v").write_text(
            "module ram2048x8(input clk, output reg [7:0] q);\n"
            "  reg [7:0] mem [0:2047];\n"
            "  always @(posedge clk) q <= mem[0];\n"
            "endmodule\n")
        (macro_dir / "ram2048x8.lib").write_text(
            "library(vendorX) { cell (ram2048x8) { area : 1.0; } }\n")
        if record_manifest:
            (proj / "phase1").mkdir(exist_ok=True)
            (proj / "phase1" / "pdk_staging_read.json").write_text(
                '{"staged_pdk_roots": ["input/pdk_local"]}')
    return proj


def _rtl_files(proj):
    rtl = proj / "phase2" / "stage1" / "rtl"
    return sorted(rtl.glob("*.v"))


def test_positive_staged_macro_discovered(tmp_path):
    proj = _mk_project(tmp_path)
    found = hms.staged_hardmacro_models(proj, _rtl_files(proj))
    assert len(found) == 1
    m = found[0]
    assert m["name"] == "ram2048x8"
    assert m["v"] is not None and m["v"].name == "ram2048x8.v"
    assert m["lib"] is not None and m["lib"].name == "ram2048x8.lib"


def test_positive_manifest_absent_falls_back_to_pdk_local(tmp_path):
    # No pdk_staging_read.json manifest → fall back to input/pdk_local.
    proj = _mk_project(tmp_path, record_manifest=False)
    found = hms.staged_hardmacro_models(proj, _rtl_files(proj))
    assert [m["name"] for m in found] == ["ram2048x8"]


def test_blackbox_stub_marks_every_module(tmp_path):
    proj = _mk_project(tmp_path)
    m = hms.staged_hardmacro_models(proj, _rtl_files(proj))[0]
    out = tmp_path / "bb"
    stub = hms.emit_blackbox_stub(m["v"], m["name"], out)
    text = stub.read_text()
    assert stub.name == "ram2048x8.bb.v"
    # attribute precedes the module decl; body preserved for interface parse.
    assert "(* blackbox *)\nmodule ram2048x8" in text
    assert text.count("(* blackbox *)") == 1


def test_negative_no_staged_root_is_noop(tmp_path):
    proj = _mk_project(tmp_path, stage_macro=False)
    assert hms.staged_hardmacro_models(proj, _rtl_files(proj)) == []


def test_negative_macro_defined_in_rtl_not_treated_as_staged(tmp_path):
    # The macro is authored in rtl/ AND staged; a module DEFINED in rtl/ is
    # never injected (it would double-define). staged-but-also-authored → skip.
    proj = _mk_project(tmp_path, define_in_rtl=True)
    found = hms.staged_hardmacro_models(proj, _rtl_files(proj))
    assert found == []


def test_negative_staged_but_not_instantiated_skipped(tmp_path):
    # Stage a macro the RTL never instantiates → not injected.
    proj = _mk_project(tmp_path)
    extra = proj / "input" / "pdk_local" / "vendorX" / "unused_macro.v"
    extra.write_text("module unused_macro(input a); endmodule\n")
    names = {m["name"] for m in hms.staged_hardmacro_models(proj, _rtl_files(proj))}
    assert "unused_macro" not in names
    assert names == {"ram2048x8"}
