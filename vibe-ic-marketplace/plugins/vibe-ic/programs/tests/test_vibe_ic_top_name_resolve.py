"""Tests for vibe_ic_one_shot_runner._resolve_top_name (synthetic RTL only).

Guards the Bucket-A fix for the phase-3 "'chip_top' is not a valid top-level
module" failure: when --top-name is OMITTED, the orchestrator must derive the
real top from the source RTL instead of forwarding the literal default.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vibe_ic_one_shot_runner as R  # noqa: E402


def _mk(tmp_path, files):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    for name, text in files.items():
        (rtl / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_sole_root_no_chip_top_derives_that_module(tmp_path):
    _mk(tmp_path, {"spm.v": "module spm(input clk, output q);\nendmodule\n"})
    top, note = R._resolve_top_name(tmp_path, "spm", "chip_top", explicit=False)
    assert top == "spm"
    assert "auto-derived" in note


def test_explicit_top_is_honored_even_if_absent(tmp_path):
    _mk(tmp_path, {"spm.v": "module spm();\nendmodule\n"})
    top, note = R._resolve_top_name(tmp_path, "spm", "my_top", explicit=True)
    assert top == "my_top" and note == ""


def test_real_chip_top_wrapper_is_kept(tmp_path):
    _mk(tmp_path, {
        "spm.v": "module spm(input a);\nendmodule\n",
        "chip_top.v": "module chip_top();\n  spm u0(.a(1'b0));\nendmodule\n",
    })
    top, note = R._resolve_top_name(tmp_path, "spm", "chip_top", explicit=False)
    assert top == "chip_top" and note == ""


def test_ic_name_preferred_over_leaf_when_both_declared(tmp_path):
    # ic-name matches a declared (root) module -> use it, not a random leaf.
    _mk(tmp_path, {
        "top.v": "module widget(input a);\n  leaf u0(.a(a));\nendmodule\n",
        "leaf.v": "module leaf(input a);\nendmodule\n",
    })
    top, note = R._resolve_top_name(tmp_path, "widget", "chip_top", explicit=False)
    assert top == "widget"


def test_instantiated_child_is_not_a_root(tmp_path):
    _mk(tmp_path, {
        "parent.v": "module parent();\n  child #(.W(4)) u0(.x(1'b0));\nendmodule\n",
        "child.v": "module child(input x);\nendmodule\n",
    })
    decls, insts = R._scan_rtl_modules(tmp_path / "phase2" / "stage1" / "rtl")
    assert decls == {"parent", "child"}
    assert "child" in insts and "parent" not in insts


def test_ambiguous_multi_root_preserves_default(tmp_path):
    # Two independent roots, ic-name matches neither -> keep the default.
    _mk(tmp_path, {
        "a.v": "module aaa(input x);\nendmodule\n",
        "b.v": "module bbb(input y);\nendmodule\n",
    })
    top, note = R._resolve_top_name(tmp_path, "zzz", "chip_top", explicit=False)
    assert top == "chip_top" and note == ""


def test_no_rtl_keeps_default(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    top, note = R._resolve_top_name(tmp_path, "spm", "chip_top", explicit=False)
    assert top == "chip_top" and note == ""


def test_sanitize_module():
    assert R._sanitize_module("spm") == "spm"
    assert R._sanitize_module("my-chip 2") == "my_chip_2"
    assert R._sanitize_module("2bad") == ""
    assert R._sanitize_module("") == ""
