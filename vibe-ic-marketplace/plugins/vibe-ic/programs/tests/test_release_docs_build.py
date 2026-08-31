#!/usr/bin/env python3
"""test_release_docs_build.py — a fact carries its artefact, or it is a HOLE.

WHY THIS FILE EXISTS
====================
`_release_docs_build` is the machinery BOTH release-document producers share,
and it was one of two programs `plugin_full_audit` D1 reported as having no test
naming it. Its own docstring records why it is shared rather than copied: two
`Field.row()` implementations are two definitions of the `Derived from` column,
and three landings in one week (v1.13.19, v1.13.36, v1.13.39) were that same
defect — in v1.13.39 the hand-written copy was the wrong one.

A module that exists to make ONE rule structural should be driven at that rule
directly, not only through the producers that consume it:

    Every quantitative field is DERIVED from a named artefact and carries that
    artefact's path, or it is explicitly NOT_MEASURED with a reason.

`Field.measured` is a PROPERTY of the value, not a flag beside it, so the
falsification below is the interesting one: there must be NO way to construct a
Field that claims to be measured while carrying NOT_MEASURED, and no way to
construct one that is measured and carries no path.

chip-AGNOSTIC: no design, vendor, foundry, node or SKU name appears here. Every
identifier is a fixture literal invented for this file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _release_docs_build as B  # noqa: E402
from _release_docs_contract import (  # noqa: E402
    DERIVED_COLUMN,
    NOT_MEASURED,
    REASON_PREFIX,
)


# ── the two states, and there is no third ─────────────────────────────────
def test_measured_is_derived_from_the_value_not_carried_beside_it():
    """The property that makes the flag and the value unable to disagree."""
    hit = B.measured("Die area", 1234, "reports/phase3/area.json")
    hole = B.unmeasured("Die area", "reports/phase3/area.json is absent")

    assert hit.measured is True
    assert hole.measured is False

    # There is no setter: `measured` has no backing attribute to overwrite, and
    # the dataclass is frozen, so a caller cannot mark a hole as measured.
    assert not hasattr(hit, "_measured")
    with pytest.raises(Exception):
        hole.value = "1234"                      # frozen dataclass

    # And the ONLY way to be unmeasured is to carry the sentinel — a field
    # built through `measured()` with the sentinel as its value reads as a hole,
    # which is the safe direction.
    assert B.measured("X", NOT_MEASURED, "a/path.json").measured is False


def test_a_measured_row_cites_its_artefact_and_a_hole_states_its_reason():
    """The third column is the contract. The two shapes must not be confusable."""
    hit = B.measured("Cells", 4, "phase3/final/metrics.json")
    hole = B.unmeasured("Cells", "phase3/final/metrics.json is absent")

    assert hit.row() == "| Cells | 4 | `phase3/final/metrics.json` |"
    assert hole.row() == (
        f"| Cells | {NOT_MEASURED} | "
        f"{REASON_PREFIX} phase3/final/metrics.json is absent |")

    # A reader (and `release_docs_check`) tells them apart by shape, not by
    # reading the prose: the measured row backticks a path, the hole does not.
    assert "`" in hit.row() and REASON_PREFIX not in hit.row()
    assert "`" not in hole.row() and REASON_PREFIX in hole.row()


def test_the_table_header_is_the_contract_column():
    body = B.table([B.measured("A", 1, "p.json"),
                    B.unmeasured("B", "p.json declares no B")])

    head, sep, row_a, row_b = body.splitlines()
    assert head == f"| Field | Value | {DERIVED_COLUMN} |"
    assert sep == "| --- | --- | --- |"
    assert row_a.endswith("`p.json` |")
    assert NOT_MEASURED in row_b


@pytest.mark.parametrize("value,expected", [
    (True, "yes"), (False, "no"),          # bool BEFORE int: bool IS an int
    (3, "3"), (0, "0"),
    (1.5, "1.5"), (2.0, "2"), (1e-9, "1e-09"),
    ("text", "text"),
])
def test_render_states_a_bool_as_a_word_and_never_as_a_number(value, expected):
    """`True` rendering as `1` in a datasheet column is a wrong answer, not a
    formatting choice, and `isinstance(True, int)` makes the order load-bearing.
    """
    assert B.render(value) == expected


# ── never a default, always a stated hole ─────────────────────────────────
def test_identity_states_a_hole_rather_than_guessing_a_design(tmp_path):
    """A guessed design name makes a document that names the wrong part, and
    nothing in the file says it was a guess."""
    project = tmp_path / "p"
    (project / "input").mkdir(parents=True)

    # No project.json at all.
    design, pdk = B.identity(project)
    assert (design.measured, pdk.measured) == (False, False)
    assert B.PROJECT_JSON in design.source and B.PROJECT_JSON in pdk.source

    # Present but declaring neither key: still a hole, still with the reason.
    (project / B.PROJECT_JSON).write_text('{"unrelated": "x"}',
                                          encoding="utf-8")
    design, pdk = B.identity(project)
    assert (design.measured, pdk.measured) == (False, False)

    # Present and blank-valued: whitespace is not a declaration.
    (project / B.PROJECT_JSON).write_text('{"design": "   ", "pdk": ""}',
                                          encoding="utf-8")
    design, pdk = B.identity(project)
    assert (design.measured, pdk.measured) == (False, False)

    # Declared: measured, and cited to project.json.
    (project / B.PROJECT_JSON).write_text(
        '{"design": "widget", "target_pdk": "openpdkA"}', encoding="utf-8")
    design, pdk = B.identity(project)
    assert (design.value, design.source) == ("widget", B.PROJECT_JSON)
    assert (pdk.value, pdk.source) == ("openpdkA", B.PROJECT_JSON)


def test_read_json_returns_none_for_anything_that_is_not_an_object(tmp_path):
    """Absent, unparseable and "parsed to a list" must all reach the SAME
    None — a list that reached `.get()` would raise inside a document build."""
    missing = tmp_path / "nope.json"
    broken = tmp_path / "broken.json"
    listy = tmp_path / "listy.json"
    ok = tmp_path / "ok.json"
    broken.write_text("{not json", encoding="utf-8")
    listy.write_text("[1, 2]", encoding="utf-8")
    ok.write_text('{"a": 1}', encoding="utf-8")

    assert B.read_json(missing) is None
    assert B.read_json(broken) is None
    assert B.read_json(listy) is None
    assert B.read_json(ok) == {"a": 1}


# ── both corpus shapes, because both ship ─────────────────────────────────
def test_a_layer_is_read_at_the_top_level_AND_under_fields(tmp_path):
    """Extracted layers carry content at the top level; skeleton-emitted ones
    nest it under `fields`. A reader that knows one reports a FALSE hole over a
    document that states the answer — the worse of the two directions."""
    project = tmp_path / "p"
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)

    (docs / "L9_IO.json").write_text('{"summary": "top-level"}',
                                     encoding="utf-8")
    flat = B.layer_text(project, "L9_IO", "Summary", ("summary",))

    (docs / "L9_IO.json").write_text('{"fields": {"summary": "nested"}}',
                                     encoding="utf-8")
    nested = B.layer_text(project, "L9_IO", "Summary", ("summary",))

    assert (flat.value, flat.source) == ("top-level",
                                         "phase1/generated_docs/L9_IO.json")
    assert (nested.value, nested.source) == ("nested",
                                             "phase1/generated_docs/L9_IO.json")
    assert flat.measured and nested.measured

    # And an absent layer is a hole naming the path it looked for.
    gone = B.layer_text(project, "L99_ABSENT", "Summary", ("summary",))
    assert gone.measured is False
    assert "phase1/generated_docs/L99_ABSENT.json" in gone.source


def test_layer_count_measures_zero_and_distinguishes_it_from_absent(tmp_path):
    """An EMPTY list is a measured 0. A MISSING key is NOT_MEASURED. Collapsing
    them is how "nothing was measured" gets published as "there are none"."""
    project = tmp_path / "p"
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)

    (docs / "L4_REGMAP.json").write_text('{"registers": []}', encoding="utf-8")
    empty = B.layer_count(project, "L4_REGMAP", "Registers", ("registers",))

    (docs / "L4_REGMAP.json").write_text('{"other": 1}', encoding="utf-8")
    absent = B.layer_count(project, "L4_REGMAP", "Registers", ("registers",))

    (docs / "L4_REGMAP.json").write_text('{"registers": [1, 2, 3]}',
                                         encoding="utf-8")
    three = B.layer_count(project, "L4_REGMAP", "Registers", ("registers",))

    assert (empty.measured, empty.value) == (True, "0")
    assert absent.measured is False
    assert (three.measured, three.value) == (True, "3")


@pytest.mark.parametrize("value,expected", [
    ("plain", "plain"),
    ("   ", ""),
    (7, "7"),
    (True, ""),                       # a bool is not prose
    ({"a": "x", "b": ""}, "a: x"),    # empty members are dropped, not rendered
    ([{"a": "x"}, "y", ""], "a: x; y"),
    (None, ""),
])
def test_flatten_reads_all_three_shapes_the_corpus_ships(value, expected):
    assert B.flatten(value) == expected


def test_one_line_cannot_end_a_markdown_table_early():
    """A newline inside a cell ends the table and takes every row after it out
    of the document a reader — and the gate — sees."""
    out = B.one_line("a\nb\tc   d | e")

    assert "\n" not in out and "\t" not in out
    assert out == "a b c d \\| e"

    long = B.one_line("x" * 900, limit=50)
    assert len(long) == 50 and long.endswith("…")


# ── conditional documents are DERIVED, never decided by eye ───────────────
def test_register_rich_returns_the_artefact_that_decided_it(tmp_path):
    """"Conditional" is where a document set quietly loses a required document:
    somebody decides the condition and the decision is recorded nowhere."""
    project = tmp_path / "p"
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    rel = "phase1/generated_docs/L4_REGMAP.json"

    absent_verdict, absent_why = B.register_rich(project)
    assert (absent_verdict, absent_why) == (False, f"{rel} is absent or "
                                                   f"unreadable in this run")

    (docs / "L4_REGMAP.json").write_text('{"registers": []}', encoding="utf-8")
    assert B.register_rich(project) == (False, rel)

    (docs / "L4_REGMAP.json").write_text('{"registers": [{"name": "r0"}]}',
                                         encoding="utf-8")
    assert B.register_rich(project) == (True, rel)


def test_register_rows_says_the_layer_declares_none_rather_than_emitting_nothing(
        tmp_path):
    """An empty table and a table nobody built print the same in Markdown."""
    rel = "phase1/generated_docs/L4_REGMAP.json"

    nothing = B.register_rows({"register_groups": []}, rel)
    assert rel in nothing and "no register group" in nothing

    body = B.register_rows(
        {"register_groups": [{"group": "ctrl", "fields": ["en", "mode"]}]},
        rel)
    assert body.splitlines()[0] == "| Group | Fields |"
    assert "| ctrl | en, mode |" in body

    # A group that declares no fields is NOT_MEASURED, not an empty cell.
    holed = B.register_rows({"register_groups": [{"group": "ctrl"}]}, rel)
    assert f"| ctrl | {NOT_MEASURED} |" in holed


def test_sha256_of_reads_the_bytes_that_are_there(tmp_path):
    import hashlib
    blob = tmp_path / "artefact.bin"
    payload = b"\x00\x01" * 5000
    blob.write_bytes(payload)

    assert B.sha256_of(blob) == hashlib.sha256(payload).hexdigest()


def test_tree_sha_is_a_stated_hole_when_the_run_dir_is_not_a_work_tree(
        tmp_path):
    """A run directory is very often not a work tree, and that is a HOLE rather
    than a licence to invent an identifier."""
    field = B.tree_sha(tmp_path)

    if not field.measured:
        assert field.value == NOT_MEASURED
        assert field.source, "a hole with no reason is not a stated hole"
    else:                       # pragma: no cover - only if tmp_path is in a repo
        assert field.value and field.value != NOT_MEASURED
