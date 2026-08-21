#!/usr/bin/env python3
"""Correcting the LEC top may cross to a SIBLING; it may never descend.

An equivalence miter needs the top to exist on both sides. When the requested
top is not declared in the gold, `_resolve_gold_top` may substitute one — a
wrong top makes Yosys build 0 `$equiv` cells and produce a "may genuinely
differ" FAIL that proved nothing, so the correction is worth having.

But "may I substitute this?" was being answered with "is it a root?", and
rootedness is the wrong question. In a real gold hierarchy:

    chip_top_pad_wrapper  instantiates  chip_top_asic
    de10lite_top          instantiates  chip_top

Substituting a SIBLING top corrects a naming mismatch: the two names denote the
same design boundary, and the comparison still covers what was asked about.
Substituting a DESCENDANT silently SHRINKS the comparison — the miter compares
an interior block while the verdict is still published under the requested top's
name. That is the same defect the correction exists to remove, one level down:
a verdict about something other than what it names.

So the bar is: the candidate must be the gate's sole root, declared by the gold,
and NOT a descendant of the requested top.

These tests exist because the round that authored the fix hit its session quota
before writing any, and because its own notes record that its FIRST version of
this bar was the wrong one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import lec_run  # noqa: E402


def _v(tmp_path: Path, name: str, text: str) -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


# The gold declares the REQUESTED top, so the first correction stage (absent top
# -> sole root) never fires and every test below exercises the gate-side bar,
# which is what this fix changed. Two sibling tops keep "sole root" from being
# the discriminator on the gold side.
_GOLD = """
module chip_top(input a, output y);
  core u (.a(a), .y(y));
endmodule
module chip_top_asic(input a, output y);
  core u (.a(a), .y(y));
endmodule
module core(input a, output y);
  assign y = ~a;
endmodule
"""


def test_a_sibling_top_is_substituted(tmp_path):
    """The case the correction exists for: the gold declares the requested top,
    but the GATE netlist does not -- it was elaborated under a sibling name. The
    gate's sole root is that sibling, so the comparison still covers the same
    design boundary and the substitution is safe."""
    gold = _v(tmp_path, "gold.v", _GOLD)
    gate = _v(tmp_path, "gate.v",
              "module chip_top_asic(input a, output y);\n"
              "  assign y = ~a;\nendmodule\n")
    resolved, note = lec_run._resolve_gold_top([gold], "chip_top", gate)
    assert resolved == "chip_top_asic", (resolved, note)
    assert note, "a substitution must be reported, never silent"


def test_a_descendant_is_refused(tmp_path):
    """THE LEAK. `core` is the gate's sole root and the gold declares it -- both
    of the old conditions -- but it sits BELOW the requested top. Comparing it
    would answer a smaller question under the larger question's name."""
    gold = _v(tmp_path, "gold.v", _GOLD)
    gate = _v(tmp_path, "gate.v",
              "module core(input a, output y);\n  assign y = ~a;\nendmodule\n")
    resolved, note = lec_run._resolve_gold_top([gold], "chip_top", gate)
    assert resolved == "chip_top", (
        f"descended to {resolved!r}: the miter would compare an interior block "
        f"while the verdict still names the requested top")


def test_the_requested_top_is_left_alone_when_it_exists(tmp_path):
    """No correction is owed, so none is made."""
    gold = _v(tmp_path, "gold.v", _GOLD)
    gate = _v(tmp_path, "gate.v",
              "module chip_top(input a, output y);\n"
              "  assign y = ~a;\nendmodule\n")
    resolved, _ = lec_run._resolve_gold_top([gold], "chip_top", gate)
    assert resolved == "chip_top"


def test_an_ambiguous_gate_is_refused(tmp_path):
    """Two roots shared by both sides: nothing distinguishes them, so the
    program must not pick. Guessing here is how a verdict acquires a subject
    nobody chose."""
    gold = _v(tmp_path, "gold.v", _GOLD)
    gate = _v(tmp_path, "gate.v",
              "module chip_top(input a, output y);\n assign y=~a;\nendmodule\n"
              "module chip_top_asic(input a, output y);\n"
              " assign y=~a;\nendmodule\n")
    resolved, _ = lec_run._resolve_gold_top([gold], "chip_top", gate)
    assert resolved == "chip_top", "picked one of two equally plausible tops"


def test_a_gate_sharing_no_module_is_refused(tmp_path):
    gold = _v(tmp_path, "gold.v", _GOLD)
    gate = _v(tmp_path, "gate.v",
              "module something_else(input a, output y);\n"
              " assign y=~a;\nendmodule\n")
    resolved, _ = lec_run._resolve_gold_top([gold], "chip_top", gate)
    assert resolved == "chip_top"


def test_no_gate_netlist_means_no_substitution(tmp_path):
    """The gate is half the evidence. Without it the gold alone must not decide
    what the comparison is about."""
    gold = _v(tmp_path, "gold.v", _GOLD)
    resolved, _ = lec_run._resolve_gold_top([gold], "chip_top", None)
    assert resolved == "chip_top"


def test_an_unreadable_gate_path_does_not_raise(tmp_path):
    """A directory where a file was expected must not take the run down -- an
    exception here would turn a diagnostic into a crash."""
    d = tmp_path / "not_a_file"
    d.mkdir()
    gold = _v(tmp_path, "gold.v", _GOLD)
    resolved, _ = lec_run._resolve_gold_top([gold], "chip_top", str(d))
    assert resolved == "chip_top"


# ---------------------------------------------------------------------------
# the helper the bar is built on
# ---------------------------------------------------------------------------
def test_descendants_walks_the_whole_subtree():
    children = {"a": ["b"], "b": ["c"], "c": [], "x": ["y"]}
    assert lec_run._descendants(children, "a") == {"b", "c"}
    assert lec_run._descendants(children, "c") == set()
    assert "a" not in lec_run._descendants(children, "a"), (
        "a module is not its own descendant; making it one would refuse the "
        "no-correction-needed case")


def test_descendants_terminates_on_a_cycle():
    """Malformed input must not hang the run."""
    assert lec_run._descendants({"a": ["b"], "b": ["a"]}, "a") == {"a", "b"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
