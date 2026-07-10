"""Tests for lec_run gold-top self-healing (synthetic RTL only).

Guards the defense-in-depth fix: a wrong LEC gold top (e.g. the default
'chip_top' on a standalone 'spm') must NOT yield a misleading 0-point FAIL — it
auto-corrects to the sole RTL root, or emits an honest 'top not found' note when
the choice is ambiguous.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lec_run as L  # noqa: E402


def _rtl(tmp_path, files):
    out = []
    for name, text in files.items():
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        out.append(str(p))
    return out


def test_valid_top_is_unchanged(tmp_path):
    gf = _rtl(tmp_path, {"spm.v": "module spm(input a);\nendmodule\n"})
    top, note = L._resolve_gold_top(gf, "spm")
    assert top == "spm" and note == ""


def test_wrong_top_autocorrects_to_sole_root(tmp_path):
    gf = _rtl(tmp_path, {"spm.v": "module spm(input a);\nendmodule\n"})
    top, note = L._resolve_gold_top(gf, "chip_top")
    assert top == "spm"
    assert "auto-corrected" in note and "spm" in note


def test_hierarchical_root_is_selected_over_child(tmp_path):
    gf = _rtl(tmp_path, {
        "top.v": "module widget();\n  child #(.W(4)) u0(.x(1'b0));\nendmodule\n",
        "child.v": "module child(input x);\nendmodule\n",
    })
    top, note = L._resolve_gold_top(gf, "chip_top")
    assert top == "widget"  # the sole root (child is instantiated)


def test_ambiguous_multiroot_keeps_top_with_honest_note(tmp_path):
    gf = _rtl(tmp_path, {
        "a.v": "module aaa(input x);\nendmodule\n",
        "b.v": "module bbb(input y);\nendmodule\n",
    })
    top, note = L._resolve_gold_top(gf, "chip_top")
    assert top == "chip_top"          # unchanged → caller emits honest verdict
    assert "not found" in note and "no unique root" in note


def test_gold_modules_detects_instantiation(tmp_path):
    gf = _rtl(tmp_path, {
        "p.v": "module parent();\n  child u0(.x(1'b0));\nendmodule\n",
        "c.v": "module child(input x);\nendmodule\n",
    })
    decls, insts = L._gold_modules(gf)
    assert decls == {"parent", "child"}
    assert "child" in insts and "parent" not in insts
