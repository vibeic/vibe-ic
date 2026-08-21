"""ORGANIC #549 — sv_package_closure_check: scoped pkg::sym closure validation."""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sv_package_closure_check as C  # noqa: E402


def test_scoped_ref_only_dependency_is_caught():
    files = {
        # uses top_pkg::WIDTH via a SCOPED ref, with NO import and NO def
        "rtl/dut.sv":
            "module dut;\n"
            "  logic [top_pkg::WIDTH-1:0] bus;\n"
            "  assign bus = lc_ctrl_pkg::Off;\n"
            "endmodule\n",
    }
    rep = C.audit(files)
    assert rep["verdict"] == "FAIL"
    assert "top_pkg" in rep["missing_packages"]
    assert "lc_ctrl_pkg" in rep["missing_packages"]


def test_complete_closure_passes():
    files = {
        "rtl/top_pkg.sv":
            "package top_pkg;\n  parameter WIDTH = 8;\nendpackage\n",
        "rtl/dut.sv":
            "module dut;\n"
            "  logic [top_pkg::WIDTH-1:0] bus;\n"
            "endmodule\n",
    }
    assert C.audit(files)["verdict"] == "PASS"


def test_import_still_validated():
    files = {
        "rtl/dut.sv":
            "module dut;\n  import missing_pkg::*;\nendmodule\n",
    }
    rep = C.audit(files)
    assert rep["verdict"] == "FAIL"
    assert "missing_pkg" in rep["missing_packages"]


def test_missing_include_caught_and_present_include_ok():
    files = {
        "rtl/a.sv": 'module a;\n`include "defs.svh"\nendmodule\n',
    }
    assert C.audit(files)["verdict"] == "FAIL"
    files["rtl/defs.svh"] = "// defs\n"
    assert C.audit(files)["verdict"] == "PASS"


def test_scoped_ref_in_comment_or_string_not_counted():
    files = {
        "rtl/a.sv":
            "package p;\nendpackage\n"
            "module a;\n"
            "  // ghost_pkg::sym in a comment must not count\n"
            '  string s = "other_pkg::sym";\n'
            "  logic x = p::y;\n"
            "endmodule\n",
    }
    rep = C.audit(files)
    assert rep["verdict"] == "PASS"
    assert "ghost_pkg" not in rep["missing_packages"]
    assert "other_pkg" not in rep["missing_packages"]


def test_std_scope_never_missing():
    files = {"rtl/a.sv": "module a;\n  int q[$]; std::randomize(q);\n"
                         "endmodule\n"}
    rep = C.audit(files)
    assert "std" not in rep["missing_packages"]


def test_cli_dir(tmp_path):
    (tmp_path / "dut.sv").write_text(
        "module dut;\n  logic x = foo_pkg::BAR;\nendmodule\n")
    assert C.main([str(tmp_path)]) == 1
    (tmp_path / "foo_pkg.sv").write_text("package foo_pkg;\nendpackage\n")
    assert C.main([str(tmp_path)]) == 0
