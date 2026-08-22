"""A refusal that says a declared name was NOT FOUND must say WHERE IT LOOKED.

THE CLASS
=========
A step resolved a name against files it had discovered itself, found nothing,
and refused. Its message named a real number — how many candidates it had found
— and the search space behind that number was ONE view of the two the
distribution uses. The count was true and the sentence was misleading: it read
as a fact about the input when it was a fact about where the step looked.

    "not found" and "not looked for" reached the reader as the same sentence.

The step now reads both views, and the enumeration of what it read is in the
artefact. NOTHING PINNED THAT. The success path is tested (which view each
resolved name came from); the REFUSAL path — the one where the enumeration is
the whole point, because there is no resolved name to attribute — was not.
A property that is implemented and unchecked is one refactor from being gone,
and its loss looks exactly like the original defect.

WHY THIS FILE IS SEPARATE FROM `test_pad_ring.py`
=================================================
It is a property of REFUSALS, not of rings. It happens to be measurable on the
first step that was corrected for it. Keeping it apart also keeps it off a file
with an open change against it.

WHAT IS ASSERTED, AND WHY EACH CLAUSE
=====================================
  * BOTH view kinds appear, on the refusal record, AS DATA — a reader and a
    downstream gate must see the same list, and prose in a message is only
    readable by one of them.
  * each view names its RESOLVED PATHS, not merely a count. A count answers
    "how many did you find", never "where did you look", and the second
    question is the one the original defect turned on.
  * each view names its YIELD, so a view that was consulted and returned
    nothing is distinguishable from one that was never consulted.
  * the human message names both views too, because the message is what a
    person reads first.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_pad_ring_test_helpers",
                                               HERE / "test_pad_ring.py")
_H = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _H
_spec.loader.exec_module(_H)

_project, _config, _gen, _report = _H._project, _H._config, _H._gen, _H._report


def _refusal_for_an_undeclared_site(tmp_path):
    root = _project(tmp_path, config=_config(PAD_SITE_NAME="no_such_site"))
    assert _gen(root) == 1, "an undeclared site name must still be refused"
    return _report(root)


def test_the_refusal_enumerates_every_view_it_consulted_as_data(tmp_path):
    """The enumeration is a structure, not a sentence."""
    rep = _refusal_for_an_undeclared_site(tmp_path)
    lib = rep["io_cell_library"]
    for view_paths, view_yield in (("lefs", "n_sites"),
                                   ("site_declarations", "n_declared_sites")):
        assert view_paths in lib, (
            f"the refusal record does not name the {view_paths!r} view it "
            f"consulted; a reader cannot tell whether it was searched and "
            f"empty or never opened")
        assert view_yield in lib, (
            f"the {view_paths!r} view is named with no yield, so a view that "
            f"returned nothing is indistinguishable from one nobody read")


def test_each_view_names_the_paths_it_resolved_not_only_a_count(tmp_path):
    """A count answers how many, never where."""
    lib = _refusal_for_an_undeclared_site(tmp_path)["io_cell_library"]
    for key in ("lefs", "site_declarations"):
        assert isinstance(lib[key], list), f"{key} must be a list of paths"
        assert all(isinstance(p, str) for p in lib[key])
    assert lib["lefs"], (
        "this fixture stages a LEF, so an empty LEF list here means the "
        "enumeration is not reporting what was actually read")


def test_a_consulted_but_empty_view_is_distinguishable_from_an_unread_one(
        tmp_path):
    """The fixture declares its sites in the LEF view only. The tech view is
    therefore CONSULTED AND EMPTY, and the record has to be able to say so —
    that exact state is the one the original defect could not express."""
    lib = _refusal_for_an_undeclared_site(tmp_path)["io_cell_library"]
    assert lib["n_declared_sites"] == 0
    assert lib["site_declarations"] == []
    assert lib["n_sites"] >= 1, (
        "the LEF view yielded sites, so the two views must read differently "
        "in the record; if both read as empty the record is not measuring")


def test_the_message_a_person_reads_names_both_views_too(tmp_path):
    """The artefact is for the gate; the message is for the human, and the
    defect was that the human sentence was true and incomplete."""
    rep = _refusal_for_an_undeclared_site(tmp_path)
    reason = rep["reason"]
    assert "PAD_SITE_NOT_FOUND" in reason
    for phrase in ("LEF", "tech-view"):
        assert phrase in reason, (
            f"the refusal message does not name the {phrase!r} view; a count "
            f"without its search space is what made the original refusal read "
            f"as a fact about the input")
    assert "neither" in reason, (
        "the message must say the name was declared by NEITHER view — the "
        "word that distinguishes an exhausted search from a partial one")
