"""`upstream_mirror_is_pinned_check` — the reds, and the shipped-tree sweep."""
from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "_umip", PROGRAMS / "upstream_mirror_is_pinned_check.py")
UM = importlib.util.module_from_spec(_spec)
sys.modules["_umip"] = UM
_spec.loader.exec_module(UM)

_MOD = '''\
"""a module that borrows upstream."""
UPSTREAM_MIRROR = {
    "upstream": "up/scripts/thing.tcl",
    "mirrors": "the per-side arithmetic",
    "pinned_by": "tests/test_pin.py::test_it",
}
'''


def _tree(tmp_path, module_src=_MOD, pin_src=None):
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "m.py").write_text(module_src)
    if pin_src is not None:
        (tmp_path / "tests" / "test_pin.py").write_text(pin_src)
    return tmp_path


# ── the reds ────────────────────────────────────────────────────────────────

def test_a_declared_mirror_with_no_pin_file_fails(tmp_path):
    _tree(tmp_path)
    assert UM.main(["--programs-dir", str(tmp_path)]) == 1


def test_a_pin_file_without_the_named_test_fails(tmp_path):
    _tree(tmp_path, pin_src='def test_other():\n    assert "up/scripts/thing.tcl"\n')
    assert UM.main(["--programs-dir", str(tmp_path)]) == 1


def test_a_pin_that_mentions_neither_the_path_nor_the_declaration_fails(tmp_path):
    """The core requirement: OUR half was already pinned when the drift
    happened, and it did not help. A pin that never reads upstream is the
    state this gate exists to improve on."""
    _tree(tmp_path, pin_src='def test_it():\n    assert our_extent() == 75\n')
    res = UM.scan(tmp_path)
    assert len(res["problems"]) == 1
    assert "does not read upstream" in res["problems"][0]
    assert UM.main(["--programs-dir", str(tmp_path)]) == 1


def test_a_declaration_missing_a_required_key_fails(tmp_path):
    _tree(tmp_path, module_src='UPSTREAM_MIRROR = {"upstream": "up/scripts/t.tcl"}\n',
          pin_src='def test_it():\n    pass\n')
    assert UM.main(["--programs-dir", str(tmp_path)]) == 1


def test_a_computed_declaration_is_refused_not_imported(tmp_path):
    """This gate reads source. A declaration it would have to RUN the module to
    read is refused by name rather than silently skipped — a gate that imports
    its subjects inherits their side effects."""
    _tree(tmp_path, module_src="UPSTREAM_MIRROR = dict(build_it())\n",
          pin_src='def test_it():\n    pass\n')
    res = UM.scan(tmp_path)
    assert res["problems"] and "not a literal" in res["problems"][0]


# ── the greens ──────────────────────────────────────────────────────────────

def test_a_pin_naming_the_path_passes(tmp_path):
    _tree(tmp_path,
          pin_src='def test_it():\n    read("up/scripts/thing.tcl")\n')
    assert UM.main(["--programs-dir", str(tmp_path)]) == 0


def test_a_pin_taking_the_path_from_the_declaration_passes(tmp_path):
    """Stronger than repeating the literal: one copy of the fact, so the two
    halves cannot drift apart the way the mirror itself did."""
    _tree(tmp_path,
          pin_src='def test_it():\n    read(M.UPSTREAM_MIRROR["upstream"])\n')
    assert UM.main(["--programs-dir", str(tmp_path)]) == 0


# ── the exit contract ───────────────────────────────────────────────────────

def test_an_empty_population_is_not_checked_not_clean(tmp_path):
    """Zero declared mirrors is a question with no subject."""
    (tmp_path / "a.py").write_text("x = 1\n")
    assert UM.main(["--programs-dir", str(tmp_path)]) == 2


def test_an_absent_directory_is_not_checked(tmp_path):
    assert UM.main(["--programs-dir", str(tmp_path / "nope")]) == 2


# ── candidates are counted, never failed ────────────────────────────────────

def test_a_prose_borrowing_claim_is_counted_not_failed(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "m.py").write_text(_MOD)
    (tmp_path / "tests" / "test_pin.py").write_text(
        'def test_it():\n    read("up/scripts/thing.tcl")\n')
    (tmp_path / "other.py").write_text(
        '"""mirrors up/scripts/other.tcl, verbatim."""\n')
    res = UM.scan(tmp_path)
    assert [c["module"] for c in res["undeclared_candidates"]] == ["other.py"]
    assert res["problems"] == []
    assert UM.main(["--programs-dir", str(tmp_path)]) == 0


# ── the shipped tree ────────────────────────────────────────────────────────

def test_the_shipped_tree_is_clean():
    res = UM.scan(PROGRAMS)
    assert res["declared"], "empty population — this proves nothing"
    assert res["problems"] == [], "; ".join(res["problems"])
