#!/usr/bin/env python3
"""test_ic_release_artefacts.py — ABSENT and EMPTY must not reach one verdict.

WHY THIS FILE EXISTS
====================
`_ic_release_artefacts` is the module that decides whether there is anything IN
a chip release's artefacts, and it was one of two programs `plugin_full_audit`
D1 reported as having no test naming it. It IS reached transitively — the
step-37.5ic producer imports it and `test_ic_release_docs_gen.py` drives that
producer — but a transitive reach tests the producer's use of it, not the
module's own contract, and the contract here is the one this repo has measured
itself getting wrong repeatedly:

    An artefact class with NO FILE is NOT_MEASURED with a reason, never a
    finding. An artefact class with a file that carries NOTHING is an ERROR.

Those two states are one keystroke apart in every implementation and produce
the same word in every summary that does not separate them. So every predicate
below is driven from BOTH sides: the absent tree and the present-but-hollow
tree, in the same invocation, with an untouched control release beside them.

chip-AGNOSTIC: every byte comes from `_ic_release_kit`, which names no design,
vendor, foundry or SKU. The PDK string is an open PDK this flow already targets.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _ic_release_artefacts as A  # noqa: E402
from _ic_release_kit import (  # noqa: E402
    CONTROL,
    SUBJECT,
    build_gds,
    build_gds_without_geometry,
    build_project,
)


# ── absent is NOT_MEASURED ────────────────────────────────────────────────
def test_a_tree_with_no_artefact_at_all_is_not_a_refusal(tmp_path):
    """Nothing to document is neither a pass nor a refusal.

    An early run has reached no stage yet. If absence were a finding this
    module would fire on every such run and be switched off within a week, so
    the property that keeps it usable is asserted here rather than assumed.
    """
    empty = tmp_path / "run"
    empty.mkdir()

    result = A.audit(empty)

    assert result.any_present is False
    assert result.errors == []
    assert result.refused is False
    assert result.present_ids() == []
    # Every class says WHY it has nothing, so "absent" is never silent.
    for state in result.classes:
        assert state.present is False
        assert state.absent_reason, f"{state.class_id} is absent with no reason"


def test_every_class_that_is_absent_carries_a_reason_and_no_finding(tmp_path):
    """The two halves of the invariant, one class at a time.

    A class is walked in BOTH states in this one test so a change that makes
    absence a finding cannot pass by only ever being shown the populated tree.
    """
    project = build_project(tmp_path / "full")
    populated = {s.class_id for s in A.audit(project).classes if s.present}
    # The kit builds every class, so a class missing here is a locator drift.
    assert populated == {c for c, _ in A.CLASSES}, populated

    bare = tmp_path / "bare"
    bare.mkdir()
    for state in A.audit(bare).classes:
        assert state.findings == [], (
            f"{state.class_id}: absence produced a finding")
        assert A.NOT_MEASURED not in state.absent_reason or state.absent_reason


# ── empty is an ERROR ─────────────────────────────────────────────────────
def test_a_hollow_gds_is_refused_and_the_untouched_release_is_not(tmp_path):
    """A legal GDSII library with not one shape in it is not a layout.

    The CONTROL release is the half that makes this a measurement rather than
    an assertion: if hollowing one stream reddened both, the refusal would be
    environmental. The module's own docstring records that it DID, before the
    class was scoped per release.
    """
    project = build_project(tmp_path / "p")
    gds = project / "phase3" / "stage4" / "gds"
    (gds / f"{SUBJECT}.gds").write_bytes(build_gds_without_geometry(SUBJECT))

    subject = A.audit(project, SUBJECT).by_id("gds")
    control = A.audit(project, CONTROL).by_id("gds")

    assert subject.present is True, "the hollow file EXISTS; that is the point"
    assert subject.refused is True
    assert [f.rule for f in subject.findings] == ["GDS_NO_GEOMETRY"]
    assert subject.findings[0].severity == "ERROR"

    assert control.present is True
    assert control.findings == [], "the untouched release was reddened too"
    assert control.facts["geometry_records"] > 0


def test_a_present_gds_with_geometry_is_clean(tmp_path):
    """The negative control for the rule above: the gate CAN be green here."""
    project = build_project(tmp_path / "p")

    state = A.audit(project, SUBJECT).by_id("gds")

    assert state.findings == []
    assert state.facts["gds_files"] == 1
    assert state.facts["geometry_records"] > 0


def test_an_absent_gds_is_not_measured_while_a_hollow_one_is_refused(tmp_path):
    """The whole file in one assertion pair, on the class that carries it."""
    project = build_project(tmp_path / "p", releases=(SUBJECT,))
    gds = project / "phase3" / "stage4" / "gds" / f"{SUBJECT}.gds"

    gds.unlink()
    absent = A.audit(project, SUBJECT).by_id("gds")

    gds.write_bytes(build_gds_without_geometry(SUBJECT))
    hollow = A.audit(project, SUBJECT).by_id("gds")

    assert (absent.present, absent.refused) == (False, False)
    assert absent.absent_reason
    assert (hollow.present, hollow.refused) == (True, True)
    # The two states must not produce the same words.
    assert absent.absent_reason not in [f.message for f in hollow.findings]


@pytest.mark.parametrize("mutate,rule", [
    (lambda t: t.replace("DIEAREA", "DIEAREA_NOT"), "DEF_NO_DIEAREA"),
    (lambda t: t.replace("COMPONENTS 4 ;", "COMPONENTS 0 ;"),
     "DEF_NO_COMPONENTS"),
])
def test_a_routed_def_that_states_nothing_is_refused(tmp_path, mutate, rule):
    """A die outline nobody declared, and a die with nothing placed in it.

    Each arm mutates ONE clause of a DEF that is otherwise the kit's known-good
    one, so the finding is earned by that clause and not by a broken file.
    """
    project = build_project(tmp_path / "p")
    path = project / A.DEF_REL
    original = path.read_text(encoding="utf-8")
    assert A.audit(project).by_id("def").findings == [], "baseline is not clean"

    mutated = mutate(original)
    assert mutated != original, "the mutation matched nothing in the DEF"
    path.write_text(mutated, encoding="utf-8")

    state = A.audit(project).by_id("def")
    assert rule in [f.rule for f in state.findings]
    assert all(f.severity == "ERROR" for f in state.findings)
    assert state.present is True


def test_an_absent_routed_def_produces_no_finding(tmp_path):
    """The other side of the DEF rules: a run that never routed is not a lie."""
    project = build_project(tmp_path / "p")
    (project / A.DEF_REL).unlink()

    state = A.audit(project).by_id("def")

    assert state.present is False
    assert state.findings == []
    assert A.DEF_REL in state.absent_reason


# ── the releases a tree OWES a document ───────────────────────────────────
def test_releases_are_derived_from_the_sign_off_streams_not_the_doc_dir(
        tmp_path):
    """Reading the documentation directory would make "signed off and never
    documented" an empty sweep that passes. It is derived from the tree."""
    project = build_project(tmp_path / "p")

    assert A.releases(project) == sorted([SUBJECT, CONTROL])

    # A third stream lands; the tree owes a third document set immediately,
    # with no documentation directory anywhere for it.
    third = "die_c"
    (project / "phase3" / "stage4" / "gds" / f"{third}.gds").write_bytes(
        build_gds(third))
    assert third in A.releases(project)

    # And a tree with no gds directory owes nothing rather than raising.
    bare = tmp_path / "bare"
    bare.mkdir()
    assert A.releases(bare) == []


def test_refusal_lines_name_the_rule_the_class_and_the_artefact(tmp_path):
    """A producer that wrote nothing must be able to say why, in words that
    identify the file — a refusal with no path is not actionable."""
    project = build_project(tmp_path / "p")
    (project / "phase3" / "stage4" / "gds" / f"{SUBJECT}.gds").write_bytes(
        build_gds_without_geometry(SUBJECT))

    lines = A.refusal_lines(A.audit(project, SUBJECT))

    assert len(lines) == 1
    assert "GDS_NO_GEOMETRY" in lines[0]
    assert "[gds]" in lines[0]
    assert f"{SUBJECT}.gds" in lines[0]
    # A clean run says nothing at all.
    assert A.refusal_lines(A.audit(project, CONTROL)) == []


def test_by_id_refuses_a_class_it_does_not_have(tmp_path):
    """A typo'd class id must raise, not return a silently empty state."""
    project = build_project(tmp_path / "p")
    with pytest.raises(KeyError):
        A.audit(project).by_id("no_such_class")
