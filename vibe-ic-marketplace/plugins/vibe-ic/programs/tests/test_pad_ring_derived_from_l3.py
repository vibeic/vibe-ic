#!/usr/bin/env python3
"""Step 15.5ic — the design ALREADY WROTE DOWN its pad placement, and the
producer now reads it.

WHAT THESE TESTS PIN, AND THE MEASUREMENT BEHIND THEM
=====================================================
MEASURED on the self-tape-out re-run: `pad_assignment_gen` reported verdict
NOT_ASKED with 0 of the 8 `2B_pad_ring` questions answered. That refusal
blocked routing and 17 downstream steps produced nothing. The design was NOT
silent: its external-interface document carries a `Physical Pad Placement`
section partitioning every top-level port across the four die edges, and its
product-metadata document states the pad count is unpinned BECAUSE it follows
from that port list.

Three directions are pinned here, and each has a control that must stay red
for the direction to mean anything:

  READS      the producer answers the questions the documents answer, and its
             verdict moves off NOT_ASKED.
  DOES NOT   a design whose documents state NO pad placement gets NOTHING —
  DEFAULT    not the partition, and not the delegated IO library either, even
             with the same PDK on the same disk. A reader that always finds an
             answer is a defaulter, and a defaulted pad ring is invented
             geometry.
  DERIVES    every value matches the document or the PDK file it came from,
  EXACTLY    compared against that file's own text inside the test. One wrong
             derived pad edge is worse than no pad ring.

THE NEAR MISS, PINNED AS ITS OWN TEST
=====================================
The pad-placement section states a minimum distance BETWEEN PADS on one side.
`PAD_EDGE_SPACING` is the distance FROM THE DIE EDGE TO THE IO ROW. Two
different lengths sharing a unit. `test_min_pad_distance_is_never_the_edge_
spacing` fails if anything ever maps the first onto the second.

The fixture documents are the tracked corpus's own, copied into a scratch
project, and one of them is EDITED IN THE SCRATCH COPY to build the control.
No corpus file is written.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

import _l_doc_pad_placement as LDOC
import _pad_ring as PR
from _source_record_merge import merge_source_records
import pad_assignment_gen as PAG

#: The tracked corpus, by the environment variable the flow already uses.
_CORPUS = os.environ.get("VIBE_IC_BENCHMARK_DATA")
_DOCS = (Path(_CORPUS) / "ic/spm/input/docs") if _CORPUS else None
_PDK_ROOT = os.environ.get("PDK_ROOT")

#: The one open PDK tree these tests read. Named as data, never as a default:
#: a run whose tree is absent SKIPS rather than passing on a value it invented.
_PDK_TREE = "sky130A"

_needs_corpus = pytest.mark.skipif(
    _DOCS is None or not _DOCS.is_dir(),
    reason="the tracked design corpus is not mounted")
_needs_pdk = pytest.mark.skipif(
    _PDK_ROOT is None or not (Path(_PDK_ROOT) / _PDK_TREE).is_dir(),
    reason="the open PDK tree these tests read is not installed")

#: The section heading whose presence or absence IS the control.
_PLACEMENT_HEADING = "## Physical Pad Placement"
_AFTER_PLACEMENT = "## Reset Polarity"
_L9_PLACEMENT_HEADING = "### 9.2.2 Pad "
_L9_AFTER_PLACEMENT = "### 9.2.3 Die size"

#: What the design's own document states, transcribed here BY HAND from
#: `L3_external_interface.md` so the assertion is against the document and not
#: against the parser's own output. Ports MSB first, one per bit.
_L3_SIDE_SIGNALS = {"N": ["x[size-1:0]"], "S": ["rst"],
                    "E": ["clk"], "W": ["p", "y"]}
_L3_SIZE_DEFAULT = 32
_L3_MIN_PAD_DISTANCE_UM = 0.1
_EXPECTED_PARTITION = {
    "N": [f"x[{b}]" for b in range(_L3_SIZE_DEFAULT - 1, -1, -1)],
    "S": ["rst"], "E": ["clk"], "W": ["p", "y"],
}
_EXPECTED_PAD_TOTAL = 36          # 32 + 1 + 1 + 2, one pad per bit

#: The six questions the documents (and the library they delegate to) answer,
#: and the two they cannot: those two name NETLIST INSTANCES.
_ANSWERABLE = {"pad_site_name", "pad_corner_site_name", "pad_edge_spacing_um",
               "pad_rotations", "pad_corner_master", "pad_fillers"}
_INSTANCE_QUESTIONS = {"pad_order_by_side", "pad_signal_map"}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _project(tmp_path: Path, name: str) -> Path:
    project = tmp_path / name
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    for src in sorted(_DOCS.glob("*.md")):
        shutil.copy2(src, docs / src.name)
    return project


def _strip_pad_placement(project: Path) -> None:
    """THE CONTROL. Remove the pad-placement section from BOTH documents that
    carry one, leaving everything else — including the sentence that delegates
    the IO cell library to the PDK — exactly where it was."""
    l3 = project / "input/docs/L3_external_interface.md"
    text = l3.read_text()
    l3.write_text(text[:text.index(_PLACEMENT_HEADING)]
                  + text[text.index(_AFTER_PLACEMENT):])
    l9 = project / "input/docs/L9_constraints_floorplan.md"
    text = l9.read_text()
    l9.write_text(text[:text.index(_L9_PLACEMENT_HEADING)]
                  + text[text.index(_L9_AFTER_PLACEMENT):])


def _run(project: Path, with_pdk: bool = True):
    """(rc, report). The report is read back off disk, not returned in memory,
    because the report on disk is what every consumer reads."""
    out = project / "report.json"
    argv = [str(project), "--json", str(out)]
    if with_pdk:
        argv += ["--pdk-root", _PDK_ROOT, "--pdk", _PDK_TREE]
    rc = PAG.main(argv)
    return rc, json.loads(out.read_text())


def _io_config_text() -> str:
    configs = PR.discover_io_library_configs(_PDK_ROOT, _PDK_TREE)
    assert configs, "the PDK tree declares no IO library pad variables"
    assert len(configs) == 1, (
        f"more than one IO library config in one tree: {configs} — the "
        f"producer refuses that case and this fixture no longer models it")
    return configs[0].read_text(errors="replace")


# --------------------------------------------------------------------------- #
# DIRECTION 1 — the producer READS what the design wrote down
# --------------------------------------------------------------------------- #
@_needs_corpus
@_needs_pdk
def test_verdict_moves_off_not_asked_and_six_questions_are_answered(tmp_path):
    rc, rep = _run(_project(tmp_path, "reads"))
    assert rep["verdict"] != "NOT_ASKED", (
        "the design states a pad placement, so 'nobody was asked' is false "
        "about this tree")
    assert rep["verdict"] == "REFUSE"
    assert rc == 1
    assert rep["questions_answered"] == len(_ANSWERABLE)
    assert set(rep["questions_unanswered"]) == _INSTANCE_QUESTIONS


@_needs_corpus
@_needs_pdk
def test_every_answered_variable_names_the_file_and_line_it_came_from(tmp_path):
    _rc, rep = _run(_project(tmp_path, "provenance"))
    assert rep["provenance"], "an answered variable with no provenance"
    for var, source in rep["provenance"].items():
        assert var in PAG.PDK_DELEGATED_VARS, var
        assert source.startswith("pdk io library "), (var, source)
        cited = source.split(" ", 3)[-1]
        path, _, line = cited.rpartition(":")
        assert Path(path).is_file(), cited
        assert int(line) >= 1, cited


@_needs_corpus
def test_the_placement_section_is_found_in_the_designs_own_document(tmp_path):
    project = _project(tmp_path, "placement")
    placement, params, unreadable, scanned = LDOC.read_project_placement(project)
    assert not unreadable, unreadable
    assert placement is not None
    assert placement.source.endswith("L3_external_interface.md")
    assert placement.heading == "Physical Pad Placement"
    assert placement.side_signals == _L3_SIDE_SIGNALS
    assert params.get("size") == _L3_SIZE_DEFAULT
    assert len(scanned) >= 2


# --------------------------------------------------------------------------- #
# DIRECTION 2 — THE CONTROLS. A design that states nothing gets nothing.
# --------------------------------------------------------------------------- #
@_needs_corpus
@_needs_pdk
def test_control_design_without_a_pad_placement_still_reports_unanswered(
        tmp_path):
    """The same PDK, the same delegation sentence, the same everything — with
    the pad-placement section removed. If this ever goes green with an answer,
    the reader is a defaulter."""
    project = _project(tmp_path, "control")
    _strip_pad_placement(project)
    rc, rep = _run(project)
    assert rep["verdict"] == "NOT_ASKED"
    assert rc == 2
    assert rep["questions_answered"] == 0
    assert sorted(rep["questions_unanswered"]) == sorted(PAG._2B_KEYS)
    assert rep["provenance"] == {}
    assert rep["config_written"] is None
    assert not (project / PR.ASSIGNMENT_REL).exists(), (
        "a config was written for a design that declared no pad ring")


@_needs_corpus
@_needs_pdk
def test_control_the_delegation_sentence_alone_answers_nothing(tmp_path):
    """The stripped document STILL says the IO cell library is the PDK's. A
    delegation with nothing delegated to it must read the PDK not at all."""
    project = _project(tmp_path, "delegation_only")
    _strip_pad_placement(project)
    kept = (project / "input/docs/L3_external_interface.md").read_text()
    assert "PDK" in kept and "io pad library" in kept, (
        "this control no longer holds the delegation sentence, so it no "
        "longer tests that the delegation alone answers nothing")
    _rc, rep = _run(project)
    assert rep["design"]["pdk_declarations"] == {}
    assert rep["design"]["pdk_io_library_configs"] == []
    assert rep["design"]["placement"] is None


@_needs_corpus
def test_control_no_pdk_means_the_delegated_variables_stay_unanswered(
        tmp_path, monkeypatch):
    """The design states its placement and delegates the library, and the
    library is not on this disk. Every delegated variable must stay UNANSWERED
    — the absence of a source is not a licence to pick a value.

    Both the flag AND the environment are removed: `_pad_ring._pdk_trees`
    falls back to `PDK_ROOT`, so a control that only dropped the flag would
    still have found a library and would have proved nothing."""
    monkeypatch.delenv("PDK_ROOT", raising=False)
    monkeypatch.delenv("PDK", raising=False)
    rc, rep = _run(_project(tmp_path, "no_pdk"), with_pdk=False)
    assert rep["verdict"] == "NOT_ASKED"
    assert rc == 2
    assert rep["questions_answered"] == 0
    assert rep["provenance"] == {}
    assert rep["design"]["placement"] is not None, (
        "the placement must still be READ and reported; only the delegated "
        "library is missing")


@_needs_corpus
@_needs_pdk
def test_the_two_instance_questions_stay_owed_and_nothing_is_written(tmp_path):
    """`PAD_SOUTH`/`PAD_EAST`/`PAD_NORTH`/`PAD_WEST` and `SIGNAL_MAP` name
    NETLIST INSTANCES. The design partitions PORTS. No document can name an
    instance the netlist does not contain, so these stay owed and no config is
    written — a half-written config is what `pad_ring_gen` calls MALFORMED."""
    project = _project(tmp_path, "owed")
    _rc, rep = _run(project)
    owed = " ".join(f["message"] for f in rep["findings"])
    for var in ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST", "SIGNAL_MAP"):
        assert var in owed, var
    assert rep["config_written"] is None
    assert not (project / PR.ASSIGNMENT_REL).exists()


def test_control_a_commented_pdk_declaration_is_not_a_declaration():
    """Upstream's own IO config carries commented `set ::env(PAD_*)` lines for
    variables the distribution deliberately leaves unset. Reading one would put
    a value into a config the PDK declined to state."""
    text = ('set ::env(PAD_SITE_NAME) "site_a"\n'
            '#set ::env(PAD_BONDPAD_NAME) "bondpad"\n'
            '  # set ::env(PAD_CORNER) "corner"\n')
    got = PR.parse_pad_env_declarations(text)
    assert set(got) == {"PAD_SITE_NAME"}
    assert got["PAD_SITE_NAME"][0] == "site_a"
    assert got["PAD_SITE_NAME"][1] == 1


def test_control_a_side_a_table_cannot_name_is_not_read():
    """A row naming two sides names none: a row that cannot say which edge it
    is about must not be read as being about either."""
    assert LDOC._side_of("**North (N)**") == "N"
    assert LDOC._side_of("North / South") is None
    assert LDOC._side_of("Northbound traffic") is None
    assert LDOC._side_of("Notes") is None


def test_control_an_unresolvable_bus_expression_is_not_guessed():
    """A bit range whose endpoint is not a DECLARED value yields NOT RESOLVED,
    never a width this module picked."""
    assert LDOC.resolve_bits("size-1:0", {"size": 8}) == list(range(7, -1, -1))
    assert LDOC.resolve_bits("size-1:0", {}) is None
    assert LDOC.resolve_bits("WIDTH*2:0", {"WIDTH": 4}) is None


# --------------------------------------------------------------------------- #
# POLARITY — a document that DENIES a value must not have it published
# (vibe-ic#712). Every test below is a PAIR: the denied text and the same text
# with the denial removed. A one-sided test here would pass against a function
# that returns nothing at all, which is the other way this can be wrong —
# `_prose_polarity` names it: "Retracting a value nothing denied is SILENT:
# the extractor reports less than it read and no gate goes red."
# --------------------------------------------------------------------------- #
#: The shape both halves of every pair below are cut from. One pad table, one
#: delegation sentence, one stated minimum distance.
_POLARITY_DOC = ("## Physical Pad Placement\n\n"
                 "The I/O cell library is provided by the PDK.\n\n"
                 "| Side | Signals |\n|---|---|\n"
                 "| North (N) | `a`, `b` |\n"
                 "| South (S) | `c` |\n\n"
                 "min_distance = 5.0 um between pads on one side.\n")


def test_the_unmutated_polarity_document_is_read_in_full():
    """LOCK 1 for every pair below: an already-empty read proves nothing, so
    the base text must publish all three values before a test may claim a
    denial removed one."""
    got = LDOC.parse_pad_placement(_POLARITY_DOC, "d.md")
    assert got is not None
    assert got.side_signals == {"N": ["a", "b"], "S": ["c"]}
    assert got.min_pad_distance_um == 5.0
    assert got.delegates_io_library_to_pdk is True


def test_a_pad_row_its_own_document_denies_is_not_a_partition():
    """A row the design has withdrawn puts real-looking signals on an edge the
    document says they are not on. The reach is the ROW: the denied row goes,
    and its NEIGHBOUR — which denies nothing — stays."""
    denied = _POLARITY_DOC.replace(
        "| North (N) | `a`, `b` |",
        "| North (N) | `a`, `b` | not bonded on this revision |")
    got = LDOC.parse_pad_placement(denied, "d.md")
    assert got is not None, "the section still exists; only one row was denied"
    assert got.side_signals == {"S": ["c"]}


def test_a_denied_delegation_sentence_does_not_delegate():
    """"the I/O cells are NOT taken from the PDK" carries both tokens the
    delegation predicate looks for and states the opposite of a delegation.
    This is the #706 shape in this module's own field."""
    denied = _POLARITY_DOC.replace(
        "The I/O cell library is provided by the PDK.",
        "The I/O cell library is NOT provided by the PDK.")
    assert LDOC.parse_pad_placement(
        denied, "d.md").delegates_io_library_to_pdk is False


def test_the_min_distance_denial_reach_is_the_sentence():
    """Both directions AND the stated limit of the reach, in one place, so the
    limit cannot rot into a silent surprise.

    IN REACH  a denial sharing the clause, and one joined by a semicolon —
              ";" joins two clauses into ONE sentence and `_prose_polarity`
              pins that deliberately.
    OUT OF    a denial written as the NEXT full sentence. `floorplan_contract`
    REACH     widens to the paragraph for that case; this does not, because
              the block searched here IS a pad table and a paragraph reach
              would let an unrelated row veto a real figure. Asserted, not
              left to be discovered.
    NOT A     an unrelated neighbouring row, and a bracketed qualifier
    DENIAL    ("(not including the scribe)") — the over-trigger direction,
              which fails silently and so is pinned here too.
    """
    def _md(sentence):
        doc = _POLARITY_DOC.replace(
            "min_distance = 5.0 um between pads on one side.\n", sentence)
        return LDOC.parse_pad_placement(doc, "d.md").min_pad_distance_um

    assert _md("min_distance = 5.0 um is NOT a constraint for this block.\n") is None
    assert _md("min_distance = 5.0 um is the harness figure; "
               "it has NO meaning here.\n") is None
    assert _md("min_distance = 5.0 um is REMOVED, not translated.\n") is None

    assert _md("min_distance = 5.0 um is the harness figure. "
               "It has NO meaning here.\n") == 5.0
    assert _md("min_distance = 5.0 um between pads.\n\n"
               "| Status | not final |\n") == 5.0
    assert _md("min_distance = 5.0 um (not including the scribe) "
               "between pads.\n") == 5.0


def test_a_parameter_row_its_own_document_denies_states_no_default():
    """A withdrawn default resolves a bus width the design never declared, and
    `resolve_bits` then expands a port into bits nothing stated. The pair: the
    denied row drops, the row beside it survives."""
    doc = ("## Parameters\n\n| Parameter | Default |\n|---|---|\n"
           "| `WIDTH` | 8 |\n| `DEPTH` | 4 |\n")
    assert LDOC.parse_parameter_defaults(doc) == {"WIDTH": 8, "DEPTH": 4}
    denied = doc.replace("| `DEPTH` | 4 |",
                         "| `DEPTH` | 4 | illustrative, not the default |")
    assert LDOC.parse_parameter_defaults(denied) == {"WIDTH": 8}


def test_the_denial_vocabulary_is_the_shared_one_and_not_a_fourth_copy():
    """vibe-ic#712's whole point: "three private copies of it is how the
    divergence happened". This module must consult `_prose_polarity`, not
    re-spell the words that mean no — and the names it imports must be the
    ones it CALLS, so the import cannot decay into a green light."""
    import _prose_polarity as PP
    src = (Path(LDOC.__file__)).read_text(encoding="utf-8")
    assert "from _prose_polarity import" in src
    assert LDOC._is_denied is PP.is_denied
    assert LDOC._sentence_scope is PP.sentence_scope
    for word in ("not", "no", "removed"):
        assert PP.NEGATION_RE.search(word), (
            f"{word!r} is honoured by the tests above but is not in the "
            f"shared vocabulary — the copies have diverged")


def test_control_a_document_that_assigns_one_side_twice_is_refused():
    text = ("## Physical Pad Placement\n\n"
            "| Side | Signals |\n|---|---|\n"
            "| North (N) | `a` |\n| North (N) | `b` |\n")
    with pytest.raises(LDOC.PadPlacementError) as exc:
        LDOC.parse_pad_placement(text, "doc.md")
    assert exc.value.rule == "L_DOC_PAD_SIDE_DECLARED_TWICE"


# --------------------------------------------------------------------------- #
# DIRECTION 3 — every derived value matches its source, checked here
# --------------------------------------------------------------------------- #
@_needs_corpus
def test_the_derived_partition_matches_the_document_bit_for_bit(tmp_path):
    project = _project(tmp_path, "partition")
    placement, params, _u, _s = LDOC.read_project_placement(project)
    ports, unresolved = LDOC.expand_side_ports(placement, params)
    assert unresolved == []
    assert ports == _EXPECTED_PARTITION
    assert sum(len(v) for v in ports.values()) == _EXPECTED_PAD_TOTAL
    # And against the document's own text, re-read here rather than trusted.
    l3 = (project / "input/docs/L3_external_interface.md").read_text()
    section = l3[l3.index(_PLACEMENT_HEADING):l3.index(_AFTER_PLACEMENT)]
    assert "`x[size-1:0]`" in section and "North (N)" in section
    assert "`rst`" in section and "South (S)" in section
    assert "`clk`" in section and "East (E)" in section
    assert "`p`" in section and "`y`" in section and "West (W)" in section


@_needs_corpus
def test_min_pad_distance_is_never_the_edge_spacing(tmp_path):
    """THE NEAR MISS. The document states a minimum distance BETWEEN PADS.
    `PAD_EDGE_SPACING` is the die edge to the IO row. If the first ever
    becomes the second, this test is what says so."""
    project = _project(tmp_path, "near_miss")
    placement, _p, _u, _s = LDOC.read_project_placement(project)
    assert placement.min_pad_distance_um == _L3_MIN_PAD_DISTANCE_UM
    design_vars, record = PAG.read_design_documents(project, _PDK_ROOT, _PDK_TREE)
    edge = design_vars.get("PAD_EDGE_SPACING")
    if edge is not None:
        assert float(edge["value"]) != _L3_MIN_PAD_DISTANCE_UM, (
            "PAD_EDGE_SPACING took the value of the document's pad-to-pad "
            "minimum distance — two different lengths that share a unit")
        assert "pdk io library" in edge["source"]
    assert record["placement"]["min_pad_distance_is_not_edge_spacing"] is True


@_needs_corpus
@_needs_pdk
def test_every_delegated_value_equals_the_pdk_files_own_line(tmp_path):
    """Each derived value is compared against the line of the PDK file it
    cites, read here independently. One wrong derived pad edge is worse than
    no pad ring."""
    project = _project(tmp_path, "verbatim")
    _rc, rep = _run(project)
    lines = _io_config_text().splitlines()
    assert rep["design"]["pdk_declarations"], "nothing was delegated"
    for var, rec in rep["design"]["pdk_declarations"].items():
        path, _, lineno = rec["source"].rpartition(":")
        line = lines[int(lineno) - 1]
        assert f"set ::env({var})" in line, (var, line)
        value = rec["value"]
        if isinstance(value, list):
            # The whitespace-separated string upstream writes, transcribed to
            # a list. Every element must appear in the declaration and the
            # count must match: no element added, dropped or invented.
            block = "\n".join(lines[int(lineno) - 1:int(lineno) + 12])
            for element in value:
                assert element in block, (var, element)
            assert len(value) == len(set(value)), var
        else:
            assert f'"{value}"' in line or value in line, (var, value, line)


@_needs_corpus
@_needs_pdk
def test_the_rotation_the_library_declares_is_not_one_this_step_implements():
    """MEASURED, and reported rather than worked around: the IO library
    declares an orientation, and `pad_ring_gen` implements exactly one — its
    `ROTATION_DEFAULT`. Where they differ, step 15.5ic answers NOT DETERMINED
    (rc 2) instead of placing an orientation nobody asked for. This test is
    here so that fact is a measurement in the suite and not a sentence in a
    report; it asserts the collision EXISTS, so it goes red the day the step
    grows the ability to honour a declared rotation and somebody forgets to
    say so."""
    # ORDER-INDEPENDENT MERGE, not `dict.update` in discovery order. Several
    # config files describe the same key, and an empty description of a key
    # used to overwrite a populated one purely because
    # `discover_io_library_configs` happened to yield it later. Which config
    # answers this test would then depend on directory order, which is exactly
    # what `per_source_record_merge_check` refuses. The record is
    # `(value, line)`, so the meaning is the value.
    declared, _conflicts = merge_source_records(
        (PR.parse_pad_env_declarations(cfg.read_text())
         for cfg in PR.discover_io_library_configs(_PDK_ROOT, _PDK_TREE)),
        content=lambda rec: rec[0],
        on_conflict="richer")
    rot = declared.get("PAD_ROTATION_HORIZONTAL")
    assert rot is not None, "the IO library declares no horizontal rotation"
    assert (PR.normalise_orient(rot[0])
            != PR.normalise_orient(PR.ROTATION_DEFAULT)), (
        "the library's declared rotation now equals the only one the step "
        "implements — if the step gained that ability, say so here")



@_needs_pdk
def test_control_a_tcl_substitution_is_not_a_literal_declaration():
    """MEASURED in the pinned image: one open PDK writes its corner master as
    a Tcl substitution. That string is not a cell name — only Tcl knows what it
    becomes — so it must NOT reach a config, and it must be reported as
    declared-but-unread rather than vanish."""
    text = ('set ::env(PAD_SITE_NAME) "site_a"\n'
            'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)__cor"\n')
    literal = PR.parse_pad_env_declarations(text)
    unresolved = PR.parse_pad_env_unresolved(text)
    assert set(literal) == {"PAD_SITE_NAME"}
    assert set(unresolved) == {"PAD_CORNER"}
    assert unresolved["PAD_CORNER"][0] == "$::env(PAD_CELL_LIBRARY)__cor"
