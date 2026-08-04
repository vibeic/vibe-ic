"""Unit tests for _design_module_set.py (vibe-ic#760).

The module answers one question — "does the design declare this module?" — and
every test here runs that real code against a real on-disk design, because the
whole point of the helper is that a NAME is not evidence and only the staged
artefacts are.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))

import _design_module_set as dms  # noqa: E402


# ---------------------------------------------------------------------------
# Declaration scanning
# ---------------------------------------------------------------------------
def test_module_names_in_text_finds_declarations():
    txt = ("module alpha(input a);\nendmodule\n"
           "  module beta;\n  endmodule\n")
    assert dms.module_names_in_text(txt) == {"alpha", "beta"}


def test_endmodule_is_never_a_module_name():
    assert "endmodule" not in dms.module_names_in_text(
        "module alpha;\nendmodule\n")


def test_commented_out_declaration_is_not_a_declaration():
    txt = ("// module ghost;\n"
           "/* module phantom;\n   endmodule */\n"
           "module real_one;\nendmodule\n")
    assert dms.module_names_in_text(txt) == {"real_one"}


def test_unterminated_module_still_counts_as_declared():
    """Widening the set is always the safe direction — a truncated source must
    not make its module look absent."""
    assert dms.module_names_in_text("module alpha(input a);\n") == {"alpha"}


def test_design_module_set_is_recursive(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.v").write_text("module a;\nendmodule\n")
    (tmp_path / "sub" / "b.sv").write_text("module b;\nendmodule\n")
    assert dms.design_module_set([tmp_path]) == {"a", "b"}


def test_design_module_set_of_missing_dir_is_empty(tmp_path):
    assert dms.design_module_set([tmp_path / "nope"]) == set()


# ---------------------------------------------------------------------------
# Instantiation roots
# ---------------------------------------------------------------------------
def _write_hier(tmp_path):
    (tmp_path / "top.v").write_text(
        "module chip_top_asic(input clk);\n"
        "    core u_core(.clk(clk));\n"
        "endmodule\n")
    (tmp_path / "core.v").write_text(
        "module core(input clk);\n    leaf u_leaf(.clk(clk));\nendmodule\n")
    (tmp_path / "leaf.v").write_text("module leaf(input clk);\nendmodule\n")
    return tmp_path


def test_instantiation_root_is_the_module_nothing_instantiates(tmp_path):
    _write_hier(tmp_path)
    bodies = dms.design_module_bodies([tmp_path])
    assert dms.instantiation_roots(bodies) == {"chip_top_asic"}


def test_parameterised_instantiation_counts(tmp_path):
    (tmp_path / "top.v").write_text(
        "module wrapper(input clk);\n"
        "    child #(.W(8)) u_child(.clk(clk));\n"
        "endmodule\n")
    (tmp_path / "child.v").write_text("module child(input clk);\nendmodule\n")
    bodies = dms.design_module_bodies([tmp_path])
    assert dms.instantiation_roots(bodies) == {"wrapper"}


def test_commented_out_instantiation_does_not_hide_a_root(tmp_path):
    (tmp_path / "top.v").write_text(
        "module wrapper(input clk);\n"
        "    // child u_child(.clk(clk));\n"
        "endmodule\n")
    (tmp_path / "child.v").write_text("module child(input clk);\nendmodule\n")
    bodies = dms.design_module_bodies([tmp_path])
    assert dms.instantiation_roots(bodies) == {"wrapper", "child"}


def test_two_roots_is_reported_as_two(tmp_path):
    _write_hier(tmp_path)
    (tmp_path / "spare.v").write_text("module spare(input clk);\nendmodule\n")
    bodies = dms.design_module_bodies([tmp_path])
    assert dms.instantiation_roots(bodies) == {"chip_top_asic", "spare"}


# ---------------------------------------------------------------------------
# Reconciliation — the only verdict that licenses a refusal is ABSENT
# ---------------------------------------------------------------------------
def test_present_name_is_present():
    r = dms.reconcile_declared_top("chip_top_asic", {"chip_top_asic", "core"})
    assert r["verdict"] == dms.PRESENT
    assert r["module_set_size"] == 2


def test_absent_name_is_absent():
    r = dms.reconcile_declared_top("SPI", {"chip_top_asic", "core"})
    assert r["verdict"] == dms.ABSENT
    assert r["declared"] == "SPI"


def test_empty_module_set_refutes_nothing():
    """"I found no modules" must never become "that module is absent"."""
    assert dms.reconcile_declared_top("SPI", set())["verdict"] == \
        dms.UNVERIFIABLE


def test_no_declaration_is_its_own_verdict():
    for declared in (None, "", "   "):
        r = dms.reconcile_declared_top(declared, {"a"})
        assert r["verdict"] == dms.NO_DECLARATION
        assert r["declared"] is None
